## Context

The LiteLLM dashboard tracks token usage per model/agent but has no visibility into request origins. LiteLLM proxy v1.82.4 already extracts `requester_ip_address` (from `X-Forwarded-For` or `request.client.host`) and `user_agent` (from `User-Agent` header) into `kwargs["litellm_params"]["metadata"]` before callbacks fire. The custom `TokenLogger` callback (`token_logger.py`) currently ignores these fields.

The database is SQLite at `/data/litellm/usage.db` with ~8,000 rows growing at ~2,600/day. The dashboard is a FastAPI + vanilla JS single-page app.

## Goals / Non-Goals

**Goals:**
- Capture client IP and user-agent on every request logged to `usage_log`
- Normalize user-agent strings into a lookup table to minimize disk usage
- Surface IP data in the dashboard: list of IPs with request count, last seen, associated user-agent
- Enable filtering all dashboard views by client IP

**Non-Goals:**
- GeoIP resolution or IP-to-location mapping
- Rate limiting or blocking by IP
- Retroactively populating IP/UA for existing rows (they'll remain NULL)
- Tracking IP changes over time (history/audit log)

## Decisions

### Decision 1: Normalized `user_agents` table vs inline storage

**Choice**: Create a `user_agents(id, user_agent)` lookup table. Store `user_agent_id INTEGER` FK in `usage_log`.

**Rationale**: User-agent strings are 50-200 bytes and repeat heavily (most traffic comes from 2-3 clients). With ~2,600 rows/day, inline storage would add ~200KB/day of redundant text. A lookup table reduces this to ~4 bytes/row (integer FK). At current growth rate, this saves ~70MB/year.

**Alternative considered**: Store UA inline as TEXT column. Simpler schema, but wasteful for a field with <10 distinct values.

### Decision 2: `client_ip` stored inline vs normalized

**Choice**: Store `client_ip TEXT` directly in `usage_log`, not normalized.

**Rationale**: IPv4 addresses are max 15 bytes, IPv6 max 45 bytes. The space savings of normalizing would be marginal (~10 bytes/row) and adds join complexity to every query. IPs are also more likely to have many distinct values than user-agents, reducing normalization benefit.

### Decision 3: Schema migration strategy

**Choice**: Use `ALTER TABLE ADD COLUMN` for new columns. Run migration at `init_db()` startup time with `IF NOT EXISTS`-style safety.

**Rationale**: SQLite supports `ALTER TABLE ADD COLUMN` safely. New columns default to NULL, which is correct for existing rows (we don't have historical IP/UA data). No data migration needed.

### Decision 4: User-agent upsert strategy

**Choice**: Use `INSERT OR IGNORE` to upsert into `user_agents`, then `SELECT id` to get the FK. Cache the mapping in-memory in `token_db.py` to avoid repeated DB lookups.

**Rationale**: With <10 distinct user-agents, an in-memory dict eliminates a DB round-trip on every log call. The cache is process-local and small enough to never evict.

### Decision 5: Dashboard IP filter mechanism

**Choice**: Add an `ip` query parameter to existing dashboard API endpoints (`/api/hourly`, `/api/daily`, `/api/summary`, etc.) that appends `AND client_ip = ?` to SQL queries. Reuse the existing agent filter UI pattern (click → filter banner → clear button).

**Rationale**: Consistent with existing agent filter pattern. Users already understand click-to-filter from the agent donut chart. Adding IP filter follows the same UX.

## Risks / Trade-offs

- **NULL values for historical data** → Acceptable. Dashboard UI should handle NULL gracefully (show "—" or exclude from IP list). No mitigation needed.
- **IP behind reverse proxy shows proxy IP instead of real client** → LiteLLM already reads `X-Forwarded-For` header. As long as the upstream proxy (cli-proxy) forwards this header, real IPs are captured. Mitigation: Verify cli-proxy forwards `X-Forwarded-For`.
- **In-memory UA cache grows unbounded** → With <10 distinct user-agents, this is a non-issue. If it ever exceeds 1000 entries, consider LRU eviction. No action needed now.
- **SQLite write contention during UA upsert** → The upsert + select happens in the same connection within the existing `log_usage` call. WAL mode is already enabled. No additional contention.
