## ADDED Requirements

### Requirement: User agents lookup table
The database SHALL have a `user_agents` table with columns `id INTEGER PRIMARY KEY AUTOINCREMENT` and `user_agent TEXT UNIQUE NOT NULL`. This table stores normalized user-agent strings to avoid redundant storage in `usage_log`.

#### Scenario: Table creation on startup
- **WHEN** `init_db()` is called
- **THEN** the `user_agents` table is created if it does not exist

#### Scenario: Unique constraint prevents duplicates
- **WHEN** a user-agent string that already exists is inserted
- **THEN** the insert is ignored and the existing row's `id` is returned

### Requirement: New columns on usage_log
The `usage_log` table SHALL have two new columns: `client_ip TEXT DEFAULT NULL` and `user_agent_id INTEGER DEFAULT NULL`. The `user_agent_id` column references `user_agents(id)`.

#### Scenario: Migration adds columns to existing table
- **WHEN** `init_db()` is called on a database that lacks `client_ip` or `user_agent_id` columns
- **THEN** the columns are added via `ALTER TABLE ADD COLUMN` without data loss

#### Scenario: Existing rows have NULL for new columns
- **WHEN** the migration completes
- **THEN** all pre-existing rows have `NULL` for `client_ip` and `user_agent_id`

### Requirement: Index on client_ip
The database SHALL have an index on `usage_log(client_ip)` to support efficient IP-based filtering.

#### Scenario: Index creation on startup
- **WHEN** `init_db()` is called
- **THEN** an index `idx_client_ip` on `usage_log(client_ip)` is created if it does not exist
