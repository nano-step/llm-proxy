## ADDED Requirements

### Requirement: Cost daily API endpoint
The backend SHALL expose `GET /api/cost/daily?days=N` (default 30, max 9999) that returns daily cost bucketed by date. Each entry SHALL contain: `date`, `cost` (total cost for that day), `input_cost`, `output_cost`, `requests`. Cost SHALL be computed via the same JOIN as the cost summary.

#### Scenario: Daily cost for last 7 days
- **WHEN** `GET /api/cost/daily?days=7` is called
- **THEN** the response contains daily cost entries for the last 7 days

#### Scenario: All-time daily cost
- **WHEN** `GET /api/cost/daily?days=9999` is called
- **THEN** the response covers all days from the earliest record to now

### Requirement: Cost over time chart
The dashboard SHALL display a bar chart showing daily cost over the selected time range. The chart SHALL respond to the global time range selector (24h/7d/30d/All). For 24h, it SHALL show hourly cost buckets. The bars SHALL use an emerald/green color (`#10b981`). The Y-axis SHALL format values as dollars (`$X`). The tooltip SHALL show date, total cost, input cost, and output cost.

#### Scenario: Cost chart renders with daily data
- **WHEN** "7d" range is selected and `/api/cost/daily?days=7` returns data
- **THEN** a bar chart renders with daily cost bars in emerald green

#### Scenario: Cost chart responds to range change
- **WHEN** user switches from "7d" to "30d"
- **THEN** the cost chart re-fetches with `days=30` and updates

#### Scenario: Tooltip shows cost breakdown
- **WHEN** user hovers over a bar
- **THEN** tooltip displays: date, total cost ($X.XX), input cost ($X.XX), output cost ($X.XX)
