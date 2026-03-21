## Context

The LiteLLM proxy (port 4000) serves as the AI gateway for all Claude/Anthropic requests on this VPS. It is consumed by:
- **cliproxyapi** (port 8317) — forwards OpenAI-compatible requests to `http://localhost:4000/v1`
- **openclaw-gateway** — uses cliproxyapi for AI calls
- **opencode** — uses cliproxyapi for AI calls

The token tracking stack consists of:
1. **`token_logger.py`** — LiteLLM `CustomLogger` callback that writes to SQLite
2. **`token_db.py`** — SQLite helper (WAL mode, `/data/litellm/usage.db`)
3. **`litellm-dashboard/app.py`** — FastAPI dashboard (port 8099) that reads `usage.db`

Current state: `usage.db` has 0 records. The `TokenLogger.async_log_success_event` fires but extracts `(0, 0, 0)` because it reads `response_obj.usage` — which is empty for streaming responses. The actual usage lives in `kwargs["async_complete_streaming_response"].usage`.

The proxy also suffers from instability: two PM2 ecosystem configs exist, and the legacy `proxy.py` wrapper (which ran its own OIDC refresh + logging proxy server) conflicts with the current architecture where `gitlab_token_callback.py` handles OIDC inline.

## Goals / Non-Goals

**Goals:**
- Fix token extraction to correctly capture usage from streaming Anthropic/Claude responses
- Ensure every successful and failed request is logged to `usage.db`
- Stabilize the LiteLLM PM2 process (eliminate restart loops and port conflicts)
- Zero schema changes — existing `usage_log` table and dashboard code remain as-is
- Graceful restart — minimize proxy downtime during deployment

**Non-Goals:**
- Dashboard UI changes (dashboard already works, just needs data)
- Changing the LiteLLM model configuration or routing
- Adding authentication to the dashboard (separate concern)
- Upgrading LiteLLM version (avoid unnecessary risk)
- Changing `token_db.py` schema or adding new tables

## Decisions

### Decision 1: Fix streaming token extraction in callback

**Choice**: Check `kwargs["async_complete_streaming_response"]` first, fall back to `response_obj.usage`

**Why**: LiteLLM's callback system passes the complete streaming response (with aggregated usage) in `kwargs["async_complete_streaming_response"]` for streaming requests. The `response_obj` parameter only contains the last chunk (no usage). This is documented LiteLLM behavior since v1.40+.

**Alternative considered**: Use `log_stream_event` to accumulate token counts per-chunk. Rejected — more complex, error-prone, and unnecessary since LiteLLM already aggregates for us.

### Decision 2: Add `always_include_stream_usage: true` to litellm config

**Choice**: Set `litellm_settings.always_include_stream_usage: true` in `litellm_config.yaml`

**Why**: This guarantees Anthropic streaming responses include usage data in the final event. Without it, some providers may not include usage in streaming responses. Belt-and-suspenders approach.

### Decision 3: Keep both sync and async callback methods

**Choice**: Implement both `log_success_event`/`log_failure_event` (sync) and `async_log_success_event`/`async_log_failure_event` (async) with the same logic.

**Why**: LiteLLM proxy primarily uses async paths, but some edge cases (non-streaming, direct SDK calls) may use sync. Implementing both ensures no requests are missed.

### Decision 4: Remove legacy ecosystem.config.js, keep only .cjs

**Choice**: Rename `ecosystem.config.js` to `ecosystem.config.js.legacy` to prevent PM2 from accidentally loading it.

**Why**: The `.js` file starts `proxy.py` via python3 without loading `.env`, causing `KeyError: 'GITLAB_PAT'` on import. The `.cjs` file correctly loads `.env` and starts the litellm CLI binary. Having both creates ambiguity and crash risk.

**Alternative considered**: Delete `.js` entirely. Rejected — keeping as `.legacy` provides rollback reference.

### Decision 5: Add `__init__` diagnostic logging to TokenLogger

**Choice**: Add a print statement in `TokenLogger.__init__` to confirm callback registration on proxy startup.

**Why**: Currently there's no way to tell from logs whether the callback was imported and registered. This makes debugging callback loading issues trivial.

### Decision 6: Graceful restart strategy

**Choice**: Edit files first, then do a single `pm2 restart litellm-proxy`. Use health-check polling to confirm the proxy is back.

**Why**: The proxy is PRODUCTION. Minimize downtime to a single restart (~5-10s). No rolling restart needed since there's only 1 worker.

## Risks / Trade-offs

**[Risk] Restart causes brief downtime** → Mitigation: Single restart, health-check verification, ~5-10s gap. Upstream services (cliproxyapi) will retry failed requests.

**[Risk] Callback import failure after edit** → Mitigation: Test imports manually (`python3 -c "import token_logger"`) before restarting the proxy.

**[Risk] `async_complete_streaming_response` key might not be present in all cases** → Mitigation: Defensive check with multiple fallback paths (check kwargs key → check response_obj.usage → log 0s with warning).

**[Risk] SQLite write contention under load** → Mitigation: Already using WAL mode. At current volume (~200-500 requests/day), this is not a concern.

**[Risk] Legacy proxy.py accidentally started** → Mitigation: Rename ecosystem.config.js to .legacy, not delete. Verify PM2 process list after restart.

## Migration Plan

1. Edit `token_logger.py` (fix streaming extraction, add init logging, add sync methods)
2. Edit `litellm_config.yaml` (add `always_include_stream_usage: true`)
3. Rename `ecosystem.config.js` → `ecosystem.config.js.legacy`
4. Test imports: `cd /home/deployer/litellm && python3 -c "import token_logger; print('OK')"`
5. Restart: `pm2 restart litellm-proxy`
6. Verify health: poll `http://localhost:4000/health/liveliness`
7. Send test request and verify `usage.db` has a new record
8. Verify dashboard at port 8099 shows data

**Rollback**: If callback causes proxy crash, revert `token_logger.py` from git and restart. If PM2 config is wrong, rename `.legacy` back.

## Open Questions

- Should we add a `cache_tokens` field to `usage_log` for Anthropic prompt caching? (Deferred — can be added later without breaking changes)
- Should we add request_id tracking for deduplication? (Deferred — low volume doesn't warrant it yet)
