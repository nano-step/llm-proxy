## 1. Backend: Caching & Dependencies

- [x] 1.1 Install `cachetools` via pip and verify import works
- [x] 1.2 Add `TTLCache(maxsize=32, ttl=60)` and `cached` decorator to `app.py` imports

## 2. Backend: New API Endpoints

- [x] 2.1 Add `GET /api/alltime` endpoint — returns `total_tokens`, `total_input`, `total_output`, `total_requests`, `avg_duration_ms`, `first_seen`, `last_seen`. Wrap query function with `@cached(alltime_cache)` using the TTLCache from 1.2
- [x] 2.2 Add `GET /api/latency` endpoint with `days` param (default 1, max 365) — returns `[{ hour|date, avg_duration_ms, requests }]`. Hourly buckets for days=1, daily otherwise
- [x] 2.3 Add `GET /api/cumulative` endpoint with `days` param (default 30, max 365) — returns `[{ hour|date, tokens, cumulative_tokens }]`. Compute running total in Python after fetching per-bucket sums

## 3. Backend: Modify Existing Endpoints

- [x] 3.1 Add `avg_duration_ms` field to `/api/hourly` response (add `ROUND(AVG(duration_ms))` to the SQL query)
- [x] 3.2 Add `avg_duration_ms` field to `/api/daily` response (same approach)

## 4. Frontend: All-Time Summary Cards

- [x] 4.1 Add HTML section for all-time cards row above existing today cards in `index.html` — 4 cards: All-Time Tokens (with in/out split), All-Time Requests, Avg Latency, Tracking Since
- [x] 4.2 Add CSS styles for the all-time cards row in `style.css` — reuse `.cards-grid` pattern, add `.card-alltime` accent color
- [x] 4.3 Add `loadAllTimeSummary()` function in `app.js` — fetches `/api/alltime`, populates the 4 cards with formatted values
- [x] 4.4 Add `loadAllTimeSummary` to the `refreshAll()` function in `app.js`

## 5. Frontend: Time Range Selector

- [x] 5.1 Replace the existing Hourly/Daily toggle HTML in `index.html` with a 4-button group: 24h, 7d, 30d, All
- [x] 5.2 Update `app.js` state management — replace `currentTimeMode` (hourly/daily) with `currentRange` (24h/7d/30d/all). Map 24h → hourly endpoint, others → daily endpoint with appropriate `days` param
- [x] 5.3 Update `initTimeToggle()` in `app.js` to handle the new 4-button group and trigger reloads for all time-series charts (bar, latency, requests, cumulative)

## 6. Frontend: Model Donut Chart

- [x] 6.1 Add HTML canvas and legend container for model donut chart in `index.html` — place in a new chart row alongside the I/O ratio chart
- [x] 6.2 Add model color assignment function in `app.js` — opus→purple, sonnet→indigo, haiku→teal, unknown→gray
- [x] 6.3 Add `loadModelDonutChart()` function in `app.js` — fetches `/api/models` (reuse data with model table), renders doughnut chart with legend

## 7. Frontend: Latency Line Chart

- [x] 7.1 Add HTML canvas for latency chart in `index.html` — place in new chart row alongside requests chart
- [x] 7.2 Add `loadLatencyChart()` function in `app.js` — fetches `/api/latency?days=N` based on current range, renders line chart with amber/orange color, Y-axis formatted with "ms" suffix
- [x] 7.3 Wire `loadLatencyChart` into `refreshAll()` and time range change handler

## 8. Frontend: Requests Volume Line Chart

- [x] 8.1 Add HTML canvas for requests chart in `index.html` — alongside latency chart
- [x] 8.2 Add `loadRequestsChart()` function in `app.js` — reuses data from `/api/hourly` or `/api/daily` fetch (same response as bar chart), renders line chart with green color
- [x] 8.3 Refactor `loadBarChart()` to share fetched data with `loadRequestsChart()` — store the response in a shared variable, both charts read from it

## 9. Frontend: I/O Ratio Horizontal Bar Chart

- [x] 9.1 Add HTML canvas for I/O ratio chart in `index.html` — alongside model donut chart
- [x] 9.2 Add `loadIORatioChart()` function in `app.js` — reuses data from `/api/models` fetch, renders horizontal stacked bar with indigo (input) and purple (output). Models ordered by total tokens, highest at top

## 10. Frontend: Cumulative Area Chart

- [x] 10.1 Add HTML canvas for cumulative chart in `index.html` — full-width section above the model table
- [x] 10.2 Add `loadCumulativeChart()` function in `app.js` — fetches `/api/cumulative?days=N` based on current range, renders area chart (line with gradient fill) using primary indigo color
- [x] 10.3 Wire `loadCumulativeChart` into `refreshAll()` and time range change handler

## 11. Frontend: Layout & Styling

- [x] 11.1 Add CSS grid layout for the two new chart rows in `style.css` — latency+requests row (2-col) and model-donut+io-ratio row (2-col)
- [x] 11.2 Add CSS for full-width cumulative chart section in `style.css`
- [x] 11.3 Add responsive breakpoints for new charts — single column on mobile (<768px)
- [x] 11.4 Add new color constants in `app.js` for latency (amber), requests (green), and model colors (opus purple, sonnet indigo, haiku teal)

## 12. Integration & Verification

- [x] 12.1 Verify all 7 charts render without console errors on page load
- [x] 12.2 Verify time range selector updates all 4 time-series charts (bar, latency, requests, cumulative)
- [x] 12.3 Verify all-time cards display correct totals matching raw DB query
- [x] 12.4 Verify `/api/alltime` caching — second call within 60s should not log a new DB query
- [x] 12.5 Verify responsive layout at 768px and 1024px breakpoints
