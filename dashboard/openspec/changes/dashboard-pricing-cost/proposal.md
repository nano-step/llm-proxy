## Why

The dashboard tracks token usage but has zero visibility into monetary cost. Users cannot answer "how much am I spending?" without manually multiplying tokens by model rates. With 3,400+ requests and 204M tokens already logged, there's no way to see the $$ impact. Adding cost computation turns the dashboard from a usage monitor into a cost management tool.

## What Changes

- **Pricing table in SQLite**: New `model_pricing` table storing per-model input/output rates ($/token). Seeded from LiteLLM's built-in `litellm.model_cost` dict, refreshed weekly via a background task or manual trigger.
- **Cost computation on the fly**: All cost is computed at query time as `(prompt_tokens × input_rate) + (completion_tokens × output_rate)` per row. This means all historical data gets costed retroactively — no backfill needed.
- **Cost summary cards**: "Today's Cost" and "All-Time Cost" cards showing total spend with per-model breakdown.
- **Cost over time chart**: Line/bar chart showing daily cost, respecting the global time range selector.
- **Cost per model breakdown**: Donut chart + table column showing which model costs the most.
- **Cost per agent breakdown**: Donut chart or table showing spend per agent.
- **Cost column in model table**: Add a "Cost" column to the existing model usage table.
- **Backend API additions**: New `/api/cost/summary`, `/api/cost/daily`, `/api/cost/models`, `/api/cost/agents` endpoints and a `/api/pricing` endpoint to view/refresh rates.

## Capabilities

### New Capabilities
- `pricing-table`: SQLite table for model pricing rates, seeded from `litellm.model_cost`, refreshable weekly from the GitHub JSON source
- `cost-summary-cards`: Dashboard cards showing today's cost and all-time cost with input/output split
- `cost-over-time-chart`: Line chart showing daily cost over the selected time range, stacked by model or total
- `cost-per-model`: Donut chart and table column for cost breakdown by model
- `cost-per-agent`: Chart/table for cost breakdown by agent
- `cost-api-endpoints`: Backend endpoints for cost queries — summary, daily, per-model, per-agent, pricing management

### Modified Capabilities
<!-- No existing spec changes — cost is purely additive -->

## Impact

- **Backend (`app.py`)**: 5-6 new API endpoints for cost data. New pricing table management (create, seed, refresh). Cost computed via SQL JOIN between `usage_log` and `model_pricing`.
- **Backend (new `pricing.py` or inline)**: Logic to fetch/parse `litellm.model_cost` and the GitHub JSON, normalize model names, and upsert into pricing table.
- **DB (`usage.db`)**: New `model_pricing` table (model, input_cost_per_token, output_cost_per_token, updated_at). No changes to existing `usage_log` table.
- **Frontend (`index.html`)**: New cost summary cards, cost chart canvas, cost donut canvas. New cost column in model table.
- **Frontend (`app.js`)**: New chart functions for cost visualizations, cost formatting ($ with 2 decimal places), cost data fetching.
- **Frontend (`style.css`)**: Cost card accent colors, cost chart layout.
- **Dependencies**: Uses existing `litellm` package for initial seed. `requests` or `urllib` for weekly refresh from GitHub. No new pip packages required.
