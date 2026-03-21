## Why

The dashboard has no visibility into who is making requests. All requests show as "unknown" agent with no IP or user-agent information. When debugging unexpected usage spikes, identifying misconfigured clients, or auditing access, there's no way to trace requests back to their source. LiteLLM already captures `requester_ip_address` and `user_agent` in callback metadata — we just don't store or surface it.

## What Changes

- Add a `user_agents` normalized lookup table to reduce disk usage (UA strings are long and repeat heavily)
- Add `client_ip` and `user_agent_id` columns to `usage_log`
- Extract IP and user-agent from LiteLLM callback metadata and persist them
- New dashboard API endpoints for IP-based querying and filtering
- New dashboard UI section showing client IPs with request counts, last seen times, user agents, and click-to-filter

## Capabilities

### New Capabilities
- `ip-ua-schema`: Database schema changes — `user_agents` lookup table, new columns on `usage_log` with migration for existing data
- `ip-ua-logging`: Callback changes to extract and persist IP + user-agent from LiteLLM metadata
- `ip-ua-api`: Dashboard API endpoints for IP listing, filtering, and user-agent resolution
- `ip-ua-dashboard`: Dashboard UI — IP list panel with request count, last seen, user agent, click-to-filter

### Modified Capabilities

## Impact

- **Database**: `/data/litellm/usage.db` — schema migration adds columns and table. Existing rows get NULL for new fields.
- **Callback**: `token_logger.py` and `token_db.py` — extract two new fields, upsert into lookup table
- **Dashboard backend**: `dashboard/app.py` — new API endpoints, modify existing endpoints to accept IP filter
- **Dashboard frontend**: `dashboard/static/app.js` and `dashboard/static/index.html` — new UI section
- **No breaking changes**: Existing functionality unchanged. New columns default to NULL for old rows.
