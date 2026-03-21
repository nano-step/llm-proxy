## Why

The LiteLLM token usage tracking system is non-functional: `usage.db` has **0 records** despite the `token_logger` callback being registered in `litellm_config.yaml` and the dashboard (`litellm-dashboard`) being fully built. All Anthropic/Claude requests go through LiteLLM but no token counts are captured, making cost monitoring and usage attribution impossible.

The root cause is that `token_logger.py`'s `_extract_usage()` reads `response_obj.usage` directly, but for **streaming responses** (which is the default for all Anthropic/Claude models via LiteLLM proxy), the usage data is delivered in `kwargs["async_complete_streaming_response"]` — not in `response_obj`. The callback silently returns `(0, 0, 0)` for every request. Additionally, the LiteLLM proxy has stability issues (6+ restarts, port binding conflicts) caused by legacy `proxy.py` interference and dual PM2 ecosystem configs.

## What Changes

- **Fix streaming token extraction**: Update `token_logger.py` to read usage from `kwargs["async_complete_streaming_response"]` for streaming requests, falling back to `response_obj.usage` for non-streaming
- **Add callback initialization logging**: Add `__init__` print to `TokenLogger` class to confirm callback registration on startup
- **Add sync callback fallbacks**: Implement `log_success_event` and `log_failure_event` (sync versions) alongside async to ensure logging works regardless of call path
- **Stabilize PM2 configuration**: Remove or rename the legacy `ecosystem.config.js` (which starts `proxy.py` and crashes without env vars) — keep only `ecosystem.config.cjs` which correctly loads `.env` and runs the litellm CLI binary
- **Clean up legacy proxy.py from startup path**: `proxy.py` is no longer needed since `gitlab_token_callback.py` handles OIDC token refresh inline via `async_pre_call_hook`. Remove proxy.py from any startup config references
- **Enable `always_include_stream_usage`**: Add `litellm_settings.always_include_stream_usage: true` to `litellm_config.yaml` to guarantee Anthropic streaming responses include usage data
- **Verify end-to-end**: Confirm a test request produces a record in `usage.db` and the dashboard displays it

## Capabilities

### New Capabilities
- `streaming-token-capture`: Correctly extract and log token usage from streaming LiteLLM responses (Anthropic/Claude) to SQLite
- `proxy-stability`: Stabilize the LiteLLM proxy PM2 configuration to prevent restart loops and port conflicts

### Modified Capabilities
_(none — no existing OpenSpec specs to modify)_

## Impact

- **Files modified**: `token_logger.py`, `litellm_config.yaml`, `ecosystem.config.js` (rename/remove)
- **Files unchanged**: `gitlab_token_callback.py`, `token_db.py`, `proxy.py` (kept as reference but removed from startup)
- **Services affected**: `litellm-proxy` PM2 process (requires restart — planned as graceful rolling restart)
- **Dependencies**: No new dependencies. Uses existing `litellm.integrations.custom_logger.CustomLogger` API
- **Risk**: PM2 restart of litellm-proxy causes brief (~5s) unavailability. Mitigated by health-check wait before declaring ready. No schema changes to `usage.db`
- **Dashboard**: `litellm-dashboard` (port 8099) requires no changes — it already queries `usage_log` table which will now receive records
