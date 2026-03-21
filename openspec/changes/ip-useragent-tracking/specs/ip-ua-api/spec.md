## ADDED Requirements

### Requirement: IP list endpoint
The dashboard SHALL expose a `GET /api/ips` endpoint returning a list of all distinct client IPs with aggregated statistics. The response SHALL be a JSON object `{ ips: [{ ip, request_count, last_seen, last_user_agent, total_tokens, total_cost }] }` sorted by `request_count` descending.

#### Scenario: Return all IPs with stats
- **WHEN** `GET /api/ips` is called
- **THEN** the response contains one entry per distinct `client_ip` with request count, most recent timestamp, the user-agent associated with the most recent request, total tokens, and estimated cost

### Requirement: IP filter on existing endpoints
The dashboard SHALL accept an optional `ip` query parameter on all time-series and aggregate endpoints. When provided, the SQL queries SHALL filter to rows matching that `client_ip`.

#### Scenario: Filter hourly data by IP
- **WHEN** `GET /api/hourly?days=1&ip=192.168.1.100` is called
- **THEN** the returned data contains only rows where `client_ip = '192.168.1.100'`

#### Scenario: Filter summary by IP
- **WHEN** `GET /api/summary?ip=192.168.1.100` is called
- **THEN** the response reflects only requests from that IP

### Requirement: IP filter does not break when IP is NULL
Existing endpoints SHALL continue to function correctly when `ip` is not provided. Endpoints SHALL return empty or zero results when a non-existent IP is requested.

#### Scenario: Missing IP returns all data
- **WHEN** `GET /api/hourly?days=1` is called without an `ip` parameter
- **THEN** all IPs are included in the response

### Requirement: User-agent lookup endpoint
The dashboard SHALL expose a `GET /api/user-agents` endpoint returning the `user_agents` lookup table contents.

#### Scenario: Return all user-agents
- **WHEN** `GET /api/user-agents` is called
- **THEN** the response contains `{ user_agents: [{ id, user_agent }] }` for all rows in the `user_agents` table
