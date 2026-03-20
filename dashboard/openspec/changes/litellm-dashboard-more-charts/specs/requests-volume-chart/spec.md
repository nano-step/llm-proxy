## ADDED Requirements

### Requirement: Requests volume line chart
The dashboard SHALL display a line chart showing the number of requests over time. The data SHALL be sourced from the `requests` field already returned by `/api/hourly` and `/api/daily` endpoints. The X-axis SHALL show time labels matching the selected range. The Y-axis SHALL show request count. The line SHALL use a green color consistent with the "Requests Today" card.

#### Scenario: Requests chart renders with hourly data
- **WHEN** "24h" range is selected and `/api/hourly?days=1` returns data
- **THEN** a line chart renders with hourly time labels and request counts per hour

#### Scenario: Requests chart responds to time range change
- **WHEN** user switches from "24h" to "30d" range
- **THEN** the requests chart re-fetches daily data and updates with daily request counts

#### Scenario: Tooltip shows request details
- **WHEN** user hovers over a point on the requests line
- **THEN** a tooltip displays the time label and request count for that bucket

### Requirement: Requests chart data reuse
The frontend SHALL NOT make a separate API call for requests data. It SHALL reuse the response from `/api/hourly` or `/api/daily` (which already includes a `requests` field per bucket) to avoid duplicate network requests.

#### Scenario: Single fetch serves both token bar and requests charts
- **WHEN** the dashboard refreshes
- **THEN** `/api/hourly` (or `/api/daily`) is called once, and both the token bar chart and the requests line chart are updated from the same response data
