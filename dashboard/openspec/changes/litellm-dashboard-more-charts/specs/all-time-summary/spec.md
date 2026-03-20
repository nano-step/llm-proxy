## ADDED Requirements

### Requirement: All-time summary API endpoint
The backend SHALL expose a `GET /api/alltime` endpoint that returns lifetime aggregate statistics from the `usage_log` table. The response SHALL include `total_tokens`, `total_input`, `total_output`, `total_requests`, `avg_duration_ms`, `first_seen` (earliest timestamp), and `last_seen` (latest timestamp). The response SHALL be cached server-side with a 60-second TTL.

#### Scenario: First load returns all-time aggregates
- **WHEN** the dashboard loads and calls `GET /api/alltime`
- **THEN** the response contains accurate lifetime totals computed from all rows in `usage_log`

#### Scenario: Cached response within TTL
- **WHEN** `GET /api/alltime` is called twice within 60 seconds
- **THEN** the second call returns the cached result without executing a new SQL query

#### Scenario: Cache expires after TTL
- **WHEN** `GET /api/alltime` is called after 60 seconds since last cache fill
- **THEN** a fresh SQL query is executed and the cache is repopulated

### Requirement: All-time summary cards UI
The dashboard SHALL display a row of all-time summary cards above the existing "today" cards. The row SHALL contain: "All-Time Tokens" (with input/output split), "All-Time Requests", "Avg Latency", and "Tracking Since" (showing the first_seen date). Cards SHALL use the same glassmorphism card style as existing summary cards.

#### Scenario: All-time cards render on page load
- **WHEN** the dashboard loads and `/api/alltime` returns data
- **THEN** four all-time summary cards are visible above the today cards with formatted numbers

#### Scenario: All-time cards show formatted numbers
- **WHEN** total tokens exceed 1,000,000
- **THEN** the card displays the value as "XXX.XM" (millions with one decimal)

#### Scenario: Empty database
- **WHEN** the `usage_log` table has zero rows
- **THEN** all-time cards display "—" for numeric values and "N/A" for the tracking date
