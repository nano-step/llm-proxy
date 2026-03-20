## ADDED Requirements

### Requirement: Cumulative token usage API endpoint
The backend SHALL expose a `GET /api/cumulative` endpoint with an optional `days` query parameter (default 30, max 365). The endpoint SHALL return time-bucketed data with a running total of tokens. Each entry SHALL contain: `hour` or `date`, `tokens` (tokens in that bucket), and `cumulative_tokens` (running sum up to and including that bucket). For `days=1`, buckets SHALL be hourly. For `days>1`, buckets SHALL be daily. The running total SHALL be computed server-side in Python (not as a SQL window function) for SQLite compatibility.

#### Scenario: Cumulative data for last 7 days
- **WHEN** `GET /api/cumulative?days=7` is called
- **THEN** the response contains daily buckets where `cumulative_tokens` increases monotonically from the first to the last bucket

#### Scenario: Cumulative data for all time
- **WHEN** `GET /api/cumulative?days=9999` is called
- **THEN** the response covers all data from the earliest record to now, with the final `cumulative_tokens` equaling the all-time total

### Requirement: Cumulative token area chart
The dashboard SHALL display a full-width area chart (line chart with fill) showing cumulative token usage over the selected time range. The X-axis SHALL show time labels. The Y-axis SHALL show cumulative token count. The area SHALL use a gradient fill from the primary color (indigo) fading to transparent. The chart SHALL respond to the global time range selector.

#### Scenario: Cumulative chart renders with gradient fill
- **WHEN** "30d" range is selected and `/api/cumulative?days=30` returns data
- **THEN** a full-width area chart renders with a gradient indigo fill showing the running token total

#### Scenario: Cumulative chart responds to time range change
- **WHEN** user switches from "30d" to "All" range
- **THEN** the cumulative chart re-fetches with `days=9999` and updates to show all-time accumulation

#### Scenario: Tooltip shows cumulative details
- **WHEN** user hovers over a point on the cumulative chart
- **THEN** a tooltip displays the time label, tokens in that bucket, and cumulative total up to that point
