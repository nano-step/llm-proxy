## ADDED Requirements

### Requirement: Single PM2 ecosystem config
The LiteLLM proxy PM2 configuration SHALL use only `ecosystem.config.cjs` which loads environment variables from `.env` and starts the `litellm` CLI binary. The legacy `ecosystem.config.js` (which starts `proxy.py`) SHALL be renamed to `ecosystem.config.js.legacy` to prevent accidental use.

#### Scenario: PM2 starts litellm-proxy
- **WHEN** PM2 starts or restarts the `litellm-proxy` process
- **THEN** it SHALL use `ecosystem.config.cjs`, load `.env` variables (GITLAB_PAT, LITELLM_MASTER_KEY, etc.), and start `~/.local/bin/litellm` with `--config litellm_config.yaml --port 4000 --num_workers 1`

#### Scenario: Legacy ecosystem.config.js is not used
- **WHEN** a user or automation runs `pm2 start` in the litellm directory
- **THEN** the renamed `ecosystem.config.js.legacy` file SHALL NOT be picked up by PM2 as a valid config

### Requirement: No legacy proxy.py in startup path
The `proxy.py` wrapper script (which manages its own OIDC token refresh loop and logging proxy server) SHALL NOT be part of the active startup configuration. The OIDC token refresh is handled by `gitlab_token_callback.py` via `async_pre_call_hook`.

#### Scenario: LiteLLM starts without proxy.py
- **WHEN** the LiteLLM proxy starts via PM2
- **THEN** no `proxy.py` process SHALL be running, and no secondary logging proxy server SHALL bind additional ports

### Requirement: Graceful restart with health verification
After applying configuration changes, the LiteLLM proxy SHALL be restarted with health verification to minimize downtime.

#### Scenario: Restart and verify health
- **WHEN** the proxy is restarted via `pm2 restart litellm-proxy`
- **THEN** the health endpoint (`http://localhost:4000/health/liveliness`) SHALL respond within 30 seconds of restart
