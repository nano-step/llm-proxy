## Context

The LiteLLM dashboard is a single-page FastAPI app serving static HTML/JS/CSS with Chart.js v4. Backend reads from a SQLite DB (`/data/litellm/usage.db`) with a single `usage_log` table (~3,400 rows, growing at ~2,600/day). The current dashboard has 4 summary cards (today only), 1 stacked bar chart (hourly/daily tokens), 1 donut chart (agent breakdown), and 1 model table. The DB stores `duration_ms` and `status` fields that are never surfaced. There is no caching layer — every page load/refresh fires raw SQL queries.

The frontend is a single `app.js` IIFE using vanilla JS + Chart.js. No framework, no build step, no bundler. CSS uses CSS custom properties with a dark glassmorphism theme. The app auto-refreshes every 60 seconds.

## Goals / Non-Goals

**Goals:**
- Add 5 new charts (model donut, latency line, requests line, I/O ratio bar, cumulative area) and an all-time summary row
- Add a unified time range selector (24h / 7d / 30d / All) that controls all time-series charts
- Cache all-time aggregate queries server-side with TTL to avoid full-table scans on every refresh
- Maintain the existing dark glassmorphism design language and responsive layout
- Zero new frontend dependencies (Chart.js v4 already supports all needed chart types)

**Non-Goals:**
- Real-time WebSocket streaming — the 60s polling interval is sufficient
- User authentication or multi-tenant isolation
- Persistent server-side cache (Redis, disk) — in-memory TTL is enough for a single-process app
- DB schema changes or write operations
- Replacing Chart.js with a different charting library
- Mobile-first redesign — responsive adjustments only

## Decisions

### 1. Caching: `cachetools.TTLCache` over `fastapi-cache2`

**Choice**: Use `cachetools.TTLCache` with a simple decorator pattern.

**Rationale**: The project has zero caching dependencies today. `cachetools` is a single lightweight package (~15KB) that's near-stdlib quality. `fastapi-cache2` pulls in more machinery (backend abstraction, key builders, init lifecycle) that's overkill for caching 2-3 endpoints in a single-file app. A dict-based TTL cache with a 60-second TTL on all-time endpoints is the minimal viable solution.

**Alternatives considered**:
- `fastapi-cache2` with InMemoryBackend: More features, but adds framework-level abstraction we don't need. Would be the right choice if we had 20+ cached endpoints or planned Redis migration.
- Manual `dict` + `time.time()`: Even simpler but error-prone (no maxsize, no thread safety). `cachetools` handles these edge cases.
- `functools.lru_cache`: No TTL support — stale data would persist until process restart.

**Implementation**: Single `TTLCache(maxsize=32, ttl=60)` instance. Cached functions: `get_alltime_summary()` and `get_alltime_models()`. Cache key is just the function name (no args variation needed for aggregates).

### 2. Chart layout: 2-column grid with full-width cumulative chart

**Choice**: Extend the existing `.charts-grid` to a 2-column layout for the new charts, with the cumulative area chart spanning full width above the model table.

**Rationale**: The current layout uses `1.4fr 1fr` for the bar+donut row. Adding 4 more charts in a single row would be too cramped. A 2-column grid for pairs (latency + requests, model donut + I/O ratio) maintains readability. The cumulative chart is a key "big picture" visualization and deserves full width.

**Layout order** (top to bottom):
1. All-time summary cards (full width row)
2. Today summary cards (existing, full width row)
3. Time range selector + Token usage bar chart + Agent donut (existing row, selector added)
4. Latency chart + Requests volume chart (new row, 2-col)
5. Model donut + I/O ratio chart (new row, 2-col)
6. Cumulative token area chart (full width)
7. Model table (existing, full width)

### 3. Time range selector: Button group replacing hourly/daily toggle

**Choice**: Replace the existing Hourly/Daily toggle with a 24h / 7d / 30d / All button group that sets a global time range state. All time-series charts (bar, latency, requests, cumulative) react to this state.

**Rationale**: The current toggle only affects the bar chart. Having per-chart time controls would clutter the UI. A single global range is intuitive — "show me everything for the last 7 days." The bar chart switches between hourly buckets (for 24h) and daily buckets (for 7d/30d/All) automatically.

**Alternatives considered**:
- Date picker: Too complex for a dashboard that auto-refreshes. Predefined ranges cover 95% of use cases.
- Per-chart toggles: Would require 4 separate controls and create inconsistent views.

### 4. New API endpoints: Extend existing pattern, add 3 new endpoints

**Choice**: Add `/api/alltime`, `/api/latency`, `/api/cumulative`. Reuse existing `/api/hourly` and `/api/daily` for request counts (already returned). Extend `/api/hourly` and `/api/daily` to include `avg_duration_ms`.

**Rationale**: The existing hourly/daily endpoints already return `requests` counts — no need for a separate requests endpoint. Adding `avg_duration_ms` to their response is backward-compatible. The all-time summary and cumulative data are genuinely new query shapes.

**Endpoint details**:
- `GET /api/alltime` → `{ total_tokens, total_input, total_output, total_requests, avg_duration_ms, first_seen, last_seen }` — **cached 60s**
- `GET /api/latency?days=N` → `{ data: [{ hour|date, avg_duration_ms, p95_duration_ms, requests }] }` — same bucketing as hourly/daily
- `GET /api/cumulative?days=N` → `{ data: [{ hour|date, cumulative_tokens }] }` — running SUM
- `GET /api/hourly?days=N` (modified) → adds `avg_duration_ms` to each bucket
- `GET /api/daily?days=N` (modified) → adds `avg_duration_ms` to each bucket

### 5. Chart types: Reuse Chart.js configs with consistent theming

**Choice**: All new charts use the same Chart.js v4 configuration patterns (tooltip style, grid colors, font, legend) as the existing bar chart, just with different chart types (line, horizontalBar, area via line+fill).

**Rationale**: Visual consistency. The existing theme constants (`CHART_INPUT_COLOR`, tooltip styles, grid colors) should be reused. New color constants added only for latency (orange/amber) and request volume (green).

## Risks / Trade-offs

- **TTL cache staleness** → All-time data can be up to 60s stale. Acceptable for a dashboard that refreshes every 60s anyway. Mitigation: TTL matches the frontend refresh interval.
- **SQLite cumulative query performance** → Running SUM with window functions over large date ranges could be slow as table grows past 100K rows. Mitigation: The cumulative endpoint uses a simple running total in Python after fetching daily aggregates (not a SQL window function). Can add an index on `DATE(timestamp)` if needed.
- **Chart.js canvas count** → Going from 2 to 7 canvases increases memory usage. Mitigation: Chart.js v4 handles this fine. Each canvas is ~2-5MB. Total remains under 35MB.
- **Single-file app complexity** → `app.py` grows from 316 to ~450 lines, `app.js` from 526 to ~900 lines. Mitigation: Both files are well-structured with clear section comments. Splitting into modules would be over-engineering for this scale.
- **No p95 in SQLite** → SQLite lacks `PERCENTILE_CONT`. Mitigation: Approximate p95 by sorting durations in Python for the latency endpoint, or skip p95 and show only avg. Start with avg only.
