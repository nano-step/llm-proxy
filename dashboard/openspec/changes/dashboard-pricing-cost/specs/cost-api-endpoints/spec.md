## ADDED Requirements

### Requirement: Cost SQL computation pattern
All cost API endpoints SHALL compute cost using the SQL pattern: `SUM(u.prompt_tokens * p.input_cost_per_token) as input_cost, SUM(u.completion_tokens * p.output_cost_per_token) as output_cost` with `LEFT JOIN model_pricing p ON u.model LIKE p.model_pattern`. Models not in the pricing table SHALL contribute $0 (via COALESCE with 0).

#### Scenario: LEFT JOIN includes all usage rows
- **WHEN** a usage row's model has no matching pricing entry
- **THEN** that row's cost contribution is $0 (not excluded from results)

#### Scenario: LIKE pattern matches model variants
- **WHEN** a usage row has model `gitlab/claude-sonnet-4-6` and pricing has pattern `%sonnet-4-6%`
- **THEN** the row is correctly matched and costed

### Requirement: Cost endpoint caching
The `GET /api/cost/summary` endpoint's all-time portion SHALL be cached with a 60s TTL using the same `cachetools.TTLCache` pattern as `/api/alltime`. Per-day and per-model/agent endpoints SHALL NOT be cached (same rationale as other time-series endpoints).

#### Scenario: Cached cost summary
- **WHEN** `/api/cost/summary` is called twice within 60 seconds
- **THEN** the second call returns the cached all-time cost without re-querying

### Requirement: Cost endpoint error handling
All cost endpoints SHALL return valid JSON even if the pricing table is empty or the JOIN produces no matches. Cost values SHALL default to 0.

#### Scenario: Empty pricing table
- **WHEN** the `model_pricing` table has no rows
- **THEN** all cost endpoints return $0 for all cost fields (not an error)
