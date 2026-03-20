## ADDED Requirements

### Requirement: Model pricing SQLite table
The backend SHALL create a `model_pricing` table in the existing SQLite DB with columns: `id` (autoincrement), `model_name` (TEXT UNIQUE), `model_pattern` (TEXT for LIKE matching), `input_cost_per_token` (REAL), `output_cost_per_token` (REAL), `updated_at` (TEXT). The table SHALL be created on application startup if it does not exist.

#### Scenario: Table creation on first startup
- **WHEN** the dashboard app starts and `model_pricing` table does not exist
- **THEN** the table is created with the specified schema

#### Scenario: Table already exists
- **WHEN** the dashboard app starts and `model_pricing` table already exists
- **THEN** no schema changes are made

### Requirement: Seed pricing from litellm.model_cost
On startup, if the `model_pricing` table is empty, the backend SHALL seed it with pricing data for known Claude models by reading from `litellm.model_cost`. Each entry SHALL include the model_name, a LIKE-compatible model_pattern (e.g., `%sonnet-4-6%`), input_cost_per_token, and output_cost_per_token. The seed SHALL cover at minimum: claude-opus-4-6, claude-sonnet-4-6, claude-sonnet-4-5, claude-haiku-4-5.

#### Scenario: Empty table gets seeded
- **WHEN** the app starts and `model_pricing` has zero rows
- **THEN** 4+ pricing rows are inserted with rates from `litellm.model_cost`

#### Scenario: Non-empty table is not re-seeded
- **WHEN** the app starts and `model_pricing` already has rows
- **THEN** no seed data is inserted (existing rates preserved)

### Requirement: Weekly pricing refresh
The backend SHALL run a background thread that refreshes pricing data from the LiteLLM GitHub JSON source (`https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json`) every 7 days. The refresh SHALL upsert rows (update existing, insert new models). A `POST /api/pricing/refresh` endpoint SHALL allow manual triggering.

#### Scenario: Weekly auto-refresh
- **WHEN** 7 days have elapsed since the last refresh
- **THEN** the background thread fetches the GitHub JSON and upserts pricing rows

#### Scenario: Manual refresh trigger
- **WHEN** `POST /api/pricing/refresh` is called
- **THEN** pricing is refreshed immediately from the GitHub JSON and a success response is returned

#### Scenario: Network failure during refresh
- **WHEN** the GitHub JSON fetch fails (timeout, 404, etc.)
- **THEN** existing pricing data is preserved, an error is logged, and the response indicates failure

### Requirement: Pricing API endpoint
The backend SHALL expose `GET /api/pricing` that returns the current contents of the `model_pricing` table as a JSON array.

#### Scenario: View current pricing
- **WHEN** `GET /api/pricing` is called
- **THEN** the response contains all model pricing rows with model_name, input_cost_per_token, output_cost_per_token, and updated_at
