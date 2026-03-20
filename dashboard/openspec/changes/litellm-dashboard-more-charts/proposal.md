## Why

The LiteLLM dashboard currently shows only 2 charts (a stacked bar for tokens over time and an agent donut) plus a model table. Key data stored in the DB — latency (`duration_ms`), error rates (`status`), per-model trends, and all-time aggregates — is completely invisible. Users have no way to see cumulative usage, response time trends, request volume patterns, or how model usage shifts over time. Adding more charts turns the dashboard from a "today glance" into a proper analytics tool.

## What Changes

- **All-time summary row**: New set of summary cards showing lifetime totals (tokens, requests, avg latency) above the existing "today" cards.
- **Time range selector**: Replace the simple Hourly/Daily toggle with a range picker (24h / 7d / 30d / All) that applies to all time-series charts.
- **Model breakdown donut chart**: Visual donut for model distribution (currently only a table).
- **Latency over time chart**: Line chart showing average response time (`duration_ms`) per time bucket — this data exists in the DB but is never displayed.
- **Requests volume over time chart**: Line chart showing request count trend (currently only a single "Requests Today" number, no trend).
- **Input/Output ratio per model chart**: Horizontal stacked bar comparing prompt vs completion token ratios across models.
- **Cumulative token usage chart**: Running-total area chart showing token accumulation over the selected time range.
- **Backend API additions**: New endpoints to serve latency aggregates, cumulative data, and model-over-time breakdowns.
- **In-memory TTL caching**: All-time aggregate queries cached server-side with `cachetools.TTLCache` (60s TTL) so repeated dashboard loads/refreshes don't re-scan the full table. Growth rate is ~2,600 rows/day — currently 4ms but will degrade without caching.

## Capabilities

### New Capabilities
- `all-time-summary`: All-time aggregate summary cards (total tokens, total requests, avg latency, uptime range)
- `time-range-selector`: Unified time range control (24h/7d/30d/All) that filters all time-series charts and the existing bar chart
- `model-donut-chart`: Doughnut chart for model token distribution, mirroring the existing agent donut
- `latency-chart`: Line chart for average response time over time using `duration_ms` from the DB
- `requests-volume-chart`: Line chart for request count over time (trend, not just today's number)
- `io-ratio-chart`: Horizontal stacked bar showing input vs output token ratio per model
- `cumulative-chart`: Area chart showing cumulative (running total) token usage over time
- `api-caching`: In-memory TTL caching layer for all-time aggregate endpoints using `cachetools.TTLCache`

### Modified Capabilities
<!-- No existing specs to modify — this is a greenfield openspec project -->

## Impact

- **Backend (`app.py`)**: 3-4 new API endpoints for latency, cumulative, model-over-time, and all-time summary data. Existing `/api/hourly` and `/api/daily` endpoints may gain an optional `days` range extension or be reused.
- **Frontend (`index.html`)**: New HTML sections for 5 additional chart canvases, all-time cards row, and a time range selector widget.
- **Frontend (`app.js`)**: New Chart.js chart instances, data fetching functions, and time range state management. Estimated ~300-400 new lines.
- **Frontend (`style.css`)**: Grid layout changes to accommodate more charts (likely a 2-column or 3-column chart grid), plus styles for the time range selector and all-time cards.
- **Dependencies**: One new Python dependency: `cachetools` (lightweight, near-stdlib). Frontend uses existing Chart.js v4 CDN. No DB schema changes needed — all data fields already exist.
- **DB (`usage.db`)**: Read-only. Uses existing `duration_ms`, `status`, `model`, `agent`, `timestamp` columns that are already populated but not surfaced.
