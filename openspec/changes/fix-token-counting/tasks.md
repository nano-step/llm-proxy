## 1. Fix Token Logger Callback

- [ ] 1.1 Update `token_logger.py` `_extract_usage()` to check `kwargs["async_complete_streaming_response"].usage` first, fall back to `response_obj.usage` for non-streaming. Add a `_get_response_obj()` helper that takes both kwargs and response_obj and returns the correct response object.
- [ ] 1.2 Update `async_log_success_event` to pass kwargs to `_get_response_obj()` and use returned object for usage extraction
- [ ] 1.3 Update `async_log_failure_event` — no usage extraction changes needed, but ensure error_message is captured correctly
- [ ] 1.4 Add sync `log_success_event` and `log_failure_event` methods with identical logic to async counterparts
- [ ] 1.5 Add `__init__` method to `TokenLogger` with print: `[TokenLogger] initialized, logging to /data/litellm/usage.db`

## 2. Update LiteLLM Config

- [ ] 2.1 Add `always_include_stream_usage: true` under `litellm_settings` in `litellm_config.yaml`

## 3. Stabilize PM2 Configuration

- [ ] 3.1 Rename `ecosystem.config.js` to `ecosystem.config.js.legacy` to prevent accidental PM2 pickup
- [ ] 3.2 Verify `ecosystem.config.cjs` correctly loads `.env` and starts litellm CLI binary (read and confirm, no edit needed)

## 4. Pre-deployment Validation

- [ ] 4.1 Run `cd /home/deployer/litellm && python3 -c "from token_logger import token_logger_instance; print('OK')"` to verify callback imports cleanly
- [ ] 4.2 Run `cd /home/deployer/litellm && python3 -c "from token_db import log_usage, init_db; init_db(); print('DB OK')"` to verify DB is writable

## 5. Deploy and Verify

- [ ] 5.1 Restart litellm-proxy: `pm2 restart litellm-proxy`
- [ ] 5.2 Verify health endpoint responds: poll `http://localhost:4000/health/liveliness` within 30s
- [ ] 5.3 Check PM2 logs for `[TokenLogger] initialized` message confirming callback loaded
- [ ] 5.4 Send a test chat completion request through the proxy and verify a new record appears in `usage.db` with non-zero token counts
- [ ] 5.5 Verify the dashboard at port 8099 shows the test request data via `/api/summary`
