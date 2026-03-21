## ADDED Requirements

### Requirement: Extract client IP from callback metadata
The `TokenLogger` callback SHALL extract `requester_ip_address` from `kwargs["litellm_params"]["metadata"]` and pass it to `log_usage()`. If the field is missing or empty, `None` SHALL be stored.

#### Scenario: IP present in metadata
- **WHEN** a request completes and `kwargs["litellm_params"]["metadata"]["requester_ip_address"]` is `"192.168.1.100"`
- **THEN** `log_usage()` is called with `client_ip="192.168.1.100"`

#### Scenario: IP missing from metadata
- **WHEN** a request completes and `requester_ip_address` is absent or empty in metadata
- **THEN** `log_usage()` is called with `client_ip=None`

### Requirement: Extract and normalize user-agent from callback metadata
The `TokenLogger` callback SHALL extract `user_agent` from `kwargs["litellm_params"]["metadata"]`, resolve it to a `user_agent_id` via the `user_agents` lookup table, and pass the id to `log_usage()`.

#### Scenario: Known user-agent
- **WHEN** a request completes with `user_agent` = `"Mozilla/5.0 ..."` and this string already exists in `user_agents`
- **THEN** the existing `user_agent_id` is used without inserting a new row

#### Scenario: New user-agent
- **WHEN** a request completes with a `user_agent` not yet in `user_agents`
- **THEN** a new row is inserted into `user_agents` and the new `id` is used

#### Scenario: User-agent missing from metadata
- **WHEN** `user_agent` is absent or empty in metadata
- **THEN** `log_usage()` is called with `user_agent_id=None`

### Requirement: In-memory user-agent cache
The `token_db` module SHALL maintain an in-memory dictionary mapping user-agent strings to their `user_agent_id`. The cache SHALL be populated on first lookup and updated on new inserts. The cache eliminates redundant DB queries for repeated user-agent strings.

#### Scenario: Cache hit avoids DB query
- **WHEN** `resolve_user_agent_id("curl/7.81.0")` is called and `"curl/7.81.0"` is already in the cache
- **THEN** the cached `id` is returned without executing any SQL

#### Scenario: Cache miss triggers insert-or-ignore
- **WHEN** `resolve_user_agent_id("new-agent/1.0")` is called and `"new-agent/1.0"` is not in the cache
- **THEN** the function inserts (or ignores if exists), selects the `id`, stores it in the cache, and returns it

### Requirement: log_usage accepts new parameters
The `log_usage()` function SHALL accept optional `client_ip` (str or None) and `user_agent_id` (int or None) parameters. These SHALL be inserted into the corresponding columns in `usage_log`.

#### Scenario: Full parameters provided
- **WHEN** `log_usage(client_ip="10.0.0.1", user_agent_id=3, ...)` is called
- **THEN** the inserted row has `client_ip="10.0.0.1"` and `user_agent_id=3`

#### Scenario: Parameters omitted (backward compatibility)
- **WHEN** `log_usage(model="x", agent="y", ...)` is called without `client_ip` or `user_agent_id`
- **THEN** the inserted row has `NULL` for both columns
