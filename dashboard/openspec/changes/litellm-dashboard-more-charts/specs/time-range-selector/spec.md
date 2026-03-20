## ADDED Requirements

### Requirement: Global time range selector
The dashboard SHALL display a button group with options: "24h", "7d", "30d", "All". This selector SHALL replace the existing Hourly/Daily toggle. Selecting a range SHALL update all time-series charts (token bar chart, latency chart, requests chart, cumulative chart). The default selection SHALL be "24h".

#### Scenario: Selecting 7d range updates all charts
- **WHEN** user clicks the "7d" button
- **THEN** all time-series charts re-fetch data for the last 7 days and the "7d" button shows as active

#### Scenario: 24h range uses hourly buckets
- **WHEN** "24h" is selected
- **THEN** time-series charts use hourly time buckets (same as current hourly mode)

#### Scenario: 7d/30d/All ranges use daily buckets
- **WHEN** "7d", "30d", or "All" is selected
- **THEN** time-series charts use daily time buckets

#### Scenario: Default state on page load
- **WHEN** the dashboard loads for the first time
- **THEN** the "24h" button is active and all charts show last-24-hour data

### Requirement: Time range propagation to API calls
The frontend SHALL translate the selected range into the appropriate `days` query parameter when calling `/api/hourly`, `/api/daily`, `/api/latency`, and `/api/cumulative`. "24h" SHALL use `/api/hourly?days=1`. "7d" SHALL use daily endpoints with `days=7`. "30d" SHALL use `days=30`. "All" SHALL use `days=9999` (effectively unlimited).

#### Scenario: 30d range fetches 30 days of daily data
- **WHEN** "30d" is selected
- **THEN** the frontend calls `/api/daily?days=30`, `/api/latency?days=30`, `/api/cumulative?days=30`
