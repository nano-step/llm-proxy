## 1. Database Schema Migration

- [ ] 1.1 Add `user_agents` table to `init_db()` in `token_db.py`: `CREATE TABLE IF NOT EXISTS user_agents (id INTEGER PRIMARY KEY AUTOINCREMENT, user_agent TEXT UNIQUE NOT NULL)`
- [ ] 1.2 Add `client_ip TEXT DEFAULT NULL` column to `usage_log` via `ALTER TABLE ADD COLUMN`
- [ ] 1.3 Add `user_agent_id INTEGER DEFAULT NULL` column to `usage_log` via `ALTER TABLE ADD COLUMN`
- [ ] 1.4 Add `FOREIGN KEY (user_agent_id) REFERENCES user_agents(id)` constraint to `usage_log`
- [ ] 1.5 Add `CREATE INDEX IF NOT EXISTS idx_client_ip ON usage_log(client_ip)` index
- [ ] 1.6 Verify migration: restart LiteLLM proxy, confirm no errors, check schema with `PRAGMA table_info(usage_log)`

## 2. Token Logger — Extract IP and User-Agent

- [ ] 2.1 In `TokenLogger._extract_agent()` or new method, extract `requester_ip_address` from `kwargs["litellm_params"]["metadata"]["requester_ip_address"]`
- [ ] 2.2 Extract `user_agent` from `kwargs["litellm_params"]["metadata"]["user_agent"]`
- [ ] 2.3 Pass both values to `log_usage()` in `_handle_success()` and `_handle_failure()`

## 3. Token DB — In-Memory Cache and log_usage Update

- [ ] 3.1 Add `_ua_cache: Dict[str, int] = {}` module-level cache in `token_db.py`
- [ ] 3.2 Add `resolve_user_agent_id(user_agent: str) -> int | None` function that checks cache, does `INSERT OR IGNORE`, selects `id`, updates cache
- [ ] 3.3 Update `log_usage()` signature: add `client_ip: str | None = None`, `user_agent_id: int | None = None` parameters
- [ ] 3.4 Update `INSERT INTO usage_log (...)` to include `client_ip, user_agent_id` columns and pass new params
- [ ] 3.5 Restart LiteLLM proxy, send a test request, verify `usage_log` row has non-NULL `client_ip` and `user_agent_id`

## 4. Dashboard Backend — New API Endpoints

- [ ] 4.1 Add `GET /api/user-agents` endpoint returning all rows from `user_agents` table as `{ user_agents: [{ id, user_agent }] }`
- [ ] 4.2 Add `GET /api/ips` endpoint: SQL query joining `usage_log` + `user_agents` GROUP BY `client_ip`, returning `{ ips: [{ ip, request_count, last_seen, last_user_agent, total_tokens, total_cost }] }` sorted by request_count desc
- [ ] 4.3 Add `ip` query parameter to `GET /api/hourly`, `GET /api/daily`, `GET /api/summary`, `GET /api/alltime`, `GET /api/latency`, `GET /api/cumulative` endpoints: append `AND client_ip = ?` when `ip` param is provided
- [ ] 4.4 Verify all endpoints work with and without `ip` param

## 5. Dashboard Frontend — IP Filter State

- [ ] 5.1 Add `currentIpFilter` state variable in `app.js`
- [ ] 5.2 Add `loadIpList()` function: fetch `/api/ips`, store in `cachedIpData`, render IP chips
- [ ] 5.3 Add `renderIpChips()` function: generate clickable IP chip HTML, each chip has `data-ip` attribute
- [ ] 5.4 Add IP chips to DOM in `index.html` header area (adjacent to time toggle)
- [ ] 5.5 Add `ipChipsContainer` reference to DOM map
- [ ] 5.6 Wire click on IP chip → set `currentIpFilter`, show filter banner, refresh all charts
- [ ] 5.7 Wire clear filter button → clear `currentIpFilter`, hide banner, refresh
- [ ] 5.8 Add `ip` param to all `apiFetch()` calls when `currentIpFilter` is set
- [ ] 5.9 Ensure agent filter and IP filter are mutually exclusive (clearing one doesn't break the other)
- [ ] 5.10 Call `loadIpList()` in `refreshAll()` first batch alongside pricing data
- [ ] 5.11 Add CSS for IP chips: pill shape, cursor pointer, hover highlight, active state styling

## 6. Dashboard Frontend — User-Agent Tooltip on IP Chips

- [ ] 6.1 Pass `last_user_agent` from `/api/ips` response to IP chip rendering
- [ ] 6.2 Add tooltip CSS for IP chips showing full user-agent string on hover
- [ ] 6.3 Verify tooltip displays correctly on hover over IP chips

## 7. Verification

- [ ] 7.1 Hard-refresh dashboard, confirm IP chips appear in header
- [ ] 7.2 Click an IP chip, verify filter banner shows, charts/table update to that IP only
- [ ] 7.3 Clear filter, verify all data returns
- [ ] 7.4 Verify hover tooltip shows user-agent on IP chips
- [ ] 7.5 Verify existing functionality (pricing tooltips, cost column, time range, all charts) still works
- [ ] 7.6 Commit and push
