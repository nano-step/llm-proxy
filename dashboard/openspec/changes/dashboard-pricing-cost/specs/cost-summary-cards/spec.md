## ADDED Requirements

### Requirement: Cost summary API endpoint
The backend SHALL expose `GET /api/cost/summary` that returns today's cost and all-time cost. Cost SHALL be computed via SQL JOIN: `SUM(u.prompt_tokens * p.input_cost_per_token + u.completion_tokens * p.output_cost_per_token)` joining `usage_log u` with `model_pricing p` on `u.model LIKE p.model_pattern`. The all-time portion SHALL be cached with a 60s TTL (same pattern as `/api/alltime`). The response SHALL include: `today_cost`, `today_input_cost`, `today_output_cost`, `alltime_cost`, `alltime_input_cost`, `alltime_output_cost`.

#### Scenario: Cost summary returns today and all-time
- **WHEN** `GET /api/cost/summary` is called
- **THEN** the response contains today's cost and all-time cost, both split into input and output components

#### Scenario: Cost matches manual calculation
- **WHEN** the DB has 100 requests to claude-sonnet-4-6 with 1M prompt tokens and 10K completion tokens
- **THEN** the cost equals `(1,000,000 × $0.000003) + (10,000 × $0.000015)` = $3.15

#### Scenario: Unknown model contributes $0
- **WHEN** a usage row has a model not in the pricing table
- **THEN** that row contributes $0 to cost (LEFT JOIN, not INNER JOIN)

### Requirement: Cost summary cards in dashboard
The dashboard SHALL display 2 cost cards in a "COST" section: "Today's Cost" showing `$X.XX` with input/output split, and "All-Time Cost" showing `$X.XX` with input/output split. Cards SHALL use a dollar-sign icon and a green/emerald accent color.

#### Scenario: Cost cards render on page load
- **WHEN** the dashboard loads and `/api/cost/summary` returns data
- **THEN** two cost cards are visible with formatted dollar amounts

#### Scenario: Cost formatting
- **WHEN** today's cost is 3.156
- **THEN** the card displays "$3.16" (2 decimal places, rounded)

#### Scenario: Large cost formatting
- **WHEN** all-time cost exceeds $1,000
- **THEN** the card displays "$1,234.56" (comma-separated with 2 decimals)
