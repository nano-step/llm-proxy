# LLM Proxy

LiteLLM-based proxy that routes OpenAI-compatible requests to GitLab Duo (and soon GitHub Models). Handles OIDC token refresh inline — no cron jobs, no restarts.

## How it works

```mermaid
flowchart LR
    subgraph Clients
        A[OpenAI SDK]
        B[OpenClaw]
        C[OpenCode]
    end

    subgraph LLM Proxy
        D["LiteLLM<br/>:4000"]
        E["Token Callback<br/>(async_pre_call_hook)"]
        F["Token Cache<br/>(in-memory)"]
    end

    subgraph Providers
        G["GitLab Duo API<br/>cloud.gitlab.com"]
        H["GitHub Models<br/>(planned)"]
    end

    A & B & C -->|OpenAI-compatible| D
    D -->|every request| E
    E -->|check expiry| F
    F -->|fresh?| E
    E -->|expired?| G2["GitLab OIDC<br/>/api/v4/ai/..."]
    G2 -->|new token| F
    E -->|inject headers| D
    D -->|authenticated| G
    D -.->|future| H
```

```mermaid
sequenceDiagram
    participant C as Client
    participant L as LiteLLM :4000
    participant CB as Token Callback
    participant Cache as Token Cache
    participant GL as GitLab OIDC

    C->>L: POST /v1/chat/completions
    L->>CB: async_pre_call_hook(data)

    alt Token cached & valid (>5 min to expiry)
        CB->>Cache: get headers
        Cache-->>CB: cached headers (<1ms)
    else Token expired or near-expiry
        CB->>GL: fetch OIDC token (~200ms)
        GL-->>CB: token + headers + expires_at
        CB->>Cache: update cache
    end

    CB-->>L: data with extra_headers injected
    L->>GL: API call with fresh OIDC headers

    alt Success
        GL-->>L: LLM response
        L-->>C: OpenAI-format response
    else 401 Auth Failure (reactive invalidation)
        GL-->>L: 401 Unauthorized
        L->>CB: async_log_failure_event(kwargs)
        CB->>Cache: invalidate (expires_at = 0)
        L-->>C: error response (caller retries)
        Note over C,Cache: Next request auto-heals:<br/>async_pre_call_hook sees expired token,<br/>fetches fresh one from GitLab OIDC
    end
```

The callback (`gitlab_token_callback.py`) uses LiteLLM's `CustomLogger.async_pre_call_hook` to:
- Cache OIDC tokens in memory
- Refresh 5 minutes before expiry (single-flight via `asyncio.Lock`)
- Fall back to last-known-good token if refresh fails
- Reactively invalidate the cached token on 401 auth failures (`async_log_failure_event` sets expiry to 0, so the next request's `async_pre_call_hook` fetches a fresh token automatically). The failed request itself is not retried — callers retry at their level.

Zero restarts. Zero cron jobs. Token stays fresh automatically, and recovers after auth failures.

## Why not call GitLab Duo directly?

GitLab Duo requires OIDC tokens that expire every ~60 minutes. Without this proxy, every client would need to:

1. **Handle OIDC auth** — fetch tokens from `/api/v4/ai/third_party_agents/direct_access`, track expiry, refresh before timeout
2. **Inject GitLab-specific headers** — 12+ custom `x-gitlab-*` headers on every request
3. **Manage credentials** — each client needs the GitLab PAT

With the proxy, clients just use the standard OpenAI SDK with a single API key. The proxy handles all the GitLab auth complexity.

| | Direct to GitLab Duo | Via LLM Proxy |
|---|---|---|
| Client auth | OIDC token + 12 headers | Single API key |
| Token refresh | Every client implements it | Handled once, centrally |
| SDK compatibility | Custom HTTP client needed | Any OpenAI SDK works |
| Multi-provider | Hardcoded to GitLab | Swap providers in config |
| Observability | Per-client logging | Centralized token/usage logging |

## Setup

### Prerequisites

- Python 3.10+
- PostgreSQL 14+ (for admin dashboard)
- [LiteLLM](https://github.com/BerriAI/litellm): `pip install litellm`
- [PM2](https://pm2.keymetrics.io/): `npm install -g pm2`

### 1. Clone and configure

```bash
git clone git@github.com:nano-step/llm-proxy.git
cd llm-proxy

cp .env.example .env
# Edit .env with your values:
#   GITLAB_PAT=glpat-your-token-here
#   LITELLM_MASTER_KEY=your-api-key
#   LITELLM_PORT=4000
#   DATABASE_URL=postgresql://user:pass@host:5432/litellm
#   UI_USERNAME=admin
#   UI_PASSWORD=your-dashboard-password
#   STORE_MODEL_IN_DB=True
```

### 2. Configure models

Edit `litellm_config.yaml` to add/remove models. Each model needs:
- `model_name`: what clients use (e.g., `gitlab/claude-sonnet-4-6`)
- `model`: upstream provider model ID
- `api_base`: provider endpoint
- `api_key`: set to `gitlab-oidc` (actual auth handled by callback)

### 3. Start

```bash
pm2 start ecosystem.config.cjs
pm2 save
```

### 4. Test

```bash
curl http://localhost:4000/v1/chat/completions \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model": "gitlab/claude-haiku-4-5", "messages": [{"role": "user", "content": "Hello"}]}'
```

## Admin Dashboard

Access the built-in LiteLLM Admin UI at:

```
https://litellm.thnkandgrow.com/ui/
```

Login with:
- **Username:** `admin`
- **Password:** set via `UI_PASSWORD` env var (default: `openclaw2026`)

The dashboard provides spend tracking, virtual key management, model management, and usage analytics.

## Files

| File | Purpose |
|---|---|
| `gitlab_token_callback.py` | OIDC token manager + LiteLLM callback (proactive refresh + reactive 401 invalidation) |
| `litellm_config.yaml` | Model definitions + callback registration + DB config |
| `ecosystem.config.cjs` | PM2 process config (reads `.env`) |
| `.env` | Secrets (gitignored) — GITLAB_PAT, DATABASE_URL, UI_USERNAME, UI_PASSWORD, etc. |
| `proxy.py` | Legacy wrapper (`write_config()` preserves callbacks section) |
| `token_db.py` / `token_logger.py` | Token usage logging to SQLite; `token_logger.py` is an active callback in config |
| `migrate_spend_logs.py` | One-time migration script: SQLite usage.db → PostgreSQL LiteLLM_SpendLogs |

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `GITLAB_PAT` | Yes | GitLab Personal Access Token with Duo access |
| `LITELLM_MASTER_KEY` | Yes | API key clients use to authenticate to the proxy |
| `LITELLM_PORT` | No | Proxy port (default: 4000) |
| `GITLAB_INSTANCE` | No | GitLab instance URL (default: https://gitlab.com) |
| `DATABASE_URL` | Yes (for dashboard) | PostgreSQL connection string (e.g. `postgresql://user:pass@host:5432/litellm`) |
| `UI_USERNAME` | No | Admin dashboard username (default: `admin`) |
| `UI_PASSWORD` | No | Admin dashboard password |
| `STORE_MODEL_IN_DB` | No | Store model configs in DB (default: `True`) |
