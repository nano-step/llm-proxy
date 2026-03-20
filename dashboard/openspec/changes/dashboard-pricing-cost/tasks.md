## 1. Backend: Pricing Table & Seed

- [x] 1.1 Add `model_pricing` table creation to `app.py` startup — `CREATE TABLE IF NOT EXISTS model_pricing (id INTEGER PRIMARY KEY AUTOINCREMENT, model_name TEXT UNIQUE NOT NULL, model_pattern TEXT NOT NULL, input_cost_per_token REAL NOT NULL DEFAULT 0, output_cost_per_token REAL NOT NULL DEFAULT 0, updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now')))`
- [x] 1.2 Add seed function `_seed_pricing()` — checks if table is empty, if so inserts Claude model rates from `litellm.model_cost` (opus-4-6, sonnet-4-6, sonnet-4-5, haiku-4-5) + gemini-3-pro with LIKE patterns
- [x] 1.3 Call `_init_pricing_table()` and `_seed_pricing()` at module level (before FastAPI routes) to run on startup
- [x] 1.4 Add background thread for weekly refresh — `threading.Thread(target=_weekly_pricing_refresh, daemon=True)` started on module load. Thread sleeps 7 days then fetches GitHub JSON and upserts

## 2. Backend: Pricing Management Endpoints

- [x] 2.1 Add `GET /api/pricing` endpoint — returns all rows from `model_pricing` as JSON array
- [x] 2.2 Add `POST /api/pricing/refresh` endpoint — triggers `_refresh_pricing_from_github()`, returns success/failure

## 3. Backend: Cost API Endpoints

- [x] 3.1 Add `GET /api/cost/summary` endpoint — computes today's cost and all-time cost via JOIN. All-time portion cached with `@cached(cost_cache)` using a separate TTLCache(maxsize=32, ttl=60). Returns `{ today_cost, today_input_cost, today_output_cost, alltime_cost, alltime_input_cost, alltime_output_cost }`
- [x] 3.2 Add `GET /api/cost/daily?days=N` endpoint — returns `{ data: [{ date, cost, input_cost, output_cost, requests }] }`. For days=1 use hourly buckets (hour instead of date). Same JOIN pattern
- [x] 3.3 Add `GET /api/cost/models` endpoint — returns `{ models: [{ model, cost, input_cost, output_cost, requests, input_tokens, output_tokens }] }` ordered by cost DESC
- [x] 3.4 Add `GET /api/cost/agents` endpoint — returns `{ agents: [{ agent, cost, input_cost, output_cost, requests }] }` ordered by cost DESC

## 4. Backend: Verify All Endpoints

- [x] 4.1 Verify `model_pricing` table was created and seeded on startup — 5 models (4 Claude + 1 Gemini)
- [x] 4.2 Verify all cost endpoints return valid JSON — all return 200 OK
- [x] 4.3 Verify cost math — alltime_cost $1,033.22 matches SQL verification

## 5. Frontend: Cost Summary Cards

- [x] 5.1 Add HTML section for cost cards in `index.html` — "COST" label + 2 cards: "Today's Cost" (with in/out split) and "All-Time Cost" (with in/out split). Place between all-time cards and today cards
- [x] 5.2 Add CSS styles for cost cards in `style.css` — emerald accent color (`#10b981`)
- [x] 5.3 Add `loadCostSummary()` function in `app.js` — fetches `/api/cost/summary`, populates cost cards with `$X.XX` formatting
- [x] 5.4 Add `formatCost(n)` helper in `app.js` — returns `$X.XX` with comma separators for large numbers
- [x] 5.5 Wire `loadCostSummary` into `refreshAll()`

## 6. Frontend: Cost Over Time Chart

- [x] 6.1 Add HTML canvas for cost chart in `index.html` — full-width section, similar to cumulative chart
- [x] 6.2 Add `loadCostChart()` function in `app.js` — fetches `/api/cost/daily?days=N` based on currentRange, renders bar chart with emerald color, Y-axis as `$X` format
- [x] 6.3 Wire `loadCostChart` into `refreshAll()` and time range change handler (`refreshTimeSeries`)

## 7. Frontend: Cost Per Model

- [x] 7.1 Add HTML canvas for cost model donut chart in `index.html` — place in a new row alongside cost agent donut
- [x] 7.2 Add `loadCostModelDonut()` function in `app.js` — fetches `/api/cost/models`, renders doughnut using model colors, with legend showing `$X.XX` per model
- [x] 7.3 Add "Cost" column to model usage table in `index.html` — new `<th>Cost</th>`
- [x] 7.4 Update `renderModelTable()` in `app.js` — fetch `/api/cost/models` data, merge cost into each model row, display as `$X.XX`

## 8. Frontend: Cost Per Agent

- [x] 8.1 Add cost agent donut chart with legend showing `$X.XX` per agent

## 9. Frontend: Layout & Styling

- [x] 9.1 Add CSS for cost cards section, cost chart, cost donut in `style.css`
- [x] 9.2 Add responsive breakpoints for new cost sections
- [x] 9.3 Bump cache-bust version in `index.html` (`?v=3` for style.css and app.js)

## 10. Integration & Verification

- [x] 10.1 Verify all cost displays render without console errors
- [x] 10.2 Verify cost values match between cards and charts
- [x] 10.3 Verify time range selector updates cost chart
- [x] 10.4 Verify model table shows cost column
- [x] 10.5 Verify agent legend shows cost
- [x] 10.6 Restart dashboard process and verify pricing table persists
