## ADDED Requirements

### Requirement: Latency API endpoint
The backend SHALL expose a `GET /api/latency` endpoint with an optional `days` query parameter (default 1, max 365). The endpoint SHALL return time-bucketed latency data with fields: `hour` or `date` (depending on granularity), `avg_duration_ms` (average response time), and `requests` (count per bucket). For `days=1`, buckets SHALL be hourly. For `days>1`, buckets SHALL be daily.

#### Scenario: Hourly latency for last 24 hours
- **WHEN** `GET /api/latency?days=1` is called
- **THEN** the response contains hourly buckets with `hour`, `avg_duration_ms`, and `requests` for the last 24 hours

#### Scenario: Daily latency for last 30 days
- **WHEN** `GET /api/latency?days=30` is called
- **THEN** the response contains daily buckets with `date`, `avg_duration_ms`, and `requests` for the last 30 days

### Requirement: Latency line chart
The dashboard SHALL display a line chart showing average response time (`duration_ms`) over time. The X-axis SHALL show time labels matching the selected time range. The Y-axis SHALL show latency in milliseconds with the suffix "ms". The line SHALL use an amber/orange color to visually distinguish it from token charts.

#### Scenario: Latency chart renders with hourly data
- **WHEN** "24h" range is selected and `/api/latency?days=1` returns data
- **THEN** a line chart renders with hourly time labels and latency values in milliseconds

#### Scenario: Latency chart responds to time range change
- **WHEN** user switches from "24h" to "7d" range
- **THEN** the latency chart re-fetches `/api/latency?days=7` and updates with daily buckets

#### Scenario: Tooltip shows latency details
- **WHEN** user hovers over a point on the latency line
- **THEN** a tooltip displays the time label, average latency in ms, and request count for that bucket
