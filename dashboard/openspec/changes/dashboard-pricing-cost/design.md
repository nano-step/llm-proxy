## Context

The dashboard already tracks per-request token usage in `usage_log` (model, prompt_tokens, completion_tokens, timestamp, agent). LiteLLM (v1.82.4) ships with a built-in `litellm.model_cost` dict containing per-model pricing (input_cost_per_token, output_cost_per_token). The canonical source is `https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json`. The current DB models include `claude-opus-4-6`, `claude-sonnet-4-6`, `claude-haiku-4-5-20251001`, and some prefixed variants (`gitlab/claude-*`).

## Goals / Non-Goals

**Goals:**
- Compute cost for all historical and new usage data retroactively
- Show cost everywhere: summary cards (today + all-time), time-series chart, per-model breakdown, per-agent breakdown, model table column
- Store pricing rates in SQLite so cost queries are fast JOINs, not Python lookups per row
- Support weekly auto-refresh of pricing from LiteLLM's GitHub JSON
- Handle model name normalization (DB stores `claude-sonnet-4-6` but litellm.model_cost keys may be `anthropic/claude-sonnet-4-6` or `claude-sonnet-4.6`)

**Non-Goals:**
- Per-request cost column in `usage_log` — computing on the fly via JOIN is simpler and retroactive
- Cache-aware pricing (cache_creation_token_cost, cache_read_token_cost) — we don't track cache tokens
- Tiered pricing (above_200k_tokens) — our requests rarely exceed this and the complexity isn't worth it
- Real-time pricing updates — weekly is sufficient
- Billing/invoicing system — this is a visibility tool, not a billing engine

## Decisions

### 1. Cost computation: SQL JOIN at query time over storing per-row cost

**Choice**: Compute cost in SQL via `JOIN usage_log u ON model_pricing p WHERE u.model LIKE p.model_pattern`, multiplying tokens × rates at query time.

**Rationale**: The `usage_log` table already has all token data. A JOIN-based approach means: (a) all historical data is costed retroactively without backfill, (b) pricing updates apply retroactively, (c) no schema change to `usage_log`, (d) query is fast because the pricing table has <20 rows.

**Alternatives considered**:
- Add `cost` column to `usage_log` and compute on write in token_logger: Would require backfill of 3,400 existing rows, wouldn't retroactively apply pricing updates, and couples cost computation with the logging hot path.
- Compute in Python per-row: Too slow for aggregate queries over large datasets.

### 2. Model name normalization: Pattern matching in pricing table

**Choice**: The `model_pricing` table stores a `model_pattern` column (e.g., `%sonnet-4-6%`) alongside the exact model name. The SQL JOIN uses `u.model LIKE p.model_pattern` to match DB model names to pricing rows.

**Rationale**: The DB stores model names inconsistently — `claude-sonnet-4-6`, `gitlab/claude-sonnet-4-6`, `claude-haiku-4-5-20251001`, etc. LiteLLM's model_cost uses different keys (`anthropic/claude-sonnet-4.6`). A LIKE pattern handles all variants without requiring exact name mapping.

**Alternatives considered**:
- Normalize on write in token_logger: Would require changing the logger and backfilling old data.
- Regex matching in Python: SQLite doesn't support regex natively. LIKE patterns are simpler and sufficient.

### 3. Pricing storage: SQLite `model_pricing` table

**Choice**: New table `model_pricing(id, model_name, model_pattern, input_cost_per_token REAL, output_cost_per_token REAL, updated_at TEXT)`. Seeded on first dashboard start from `litellm.model_cost`, refreshed weekly.

**Schema**:
```sql
CREATE TABLE IF NOT EXISTS model_pricing (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_name TEXT UNIQUE NOT NULL,
    model_pattern TEXT NOT NULL,
    input_cost_per_token REAL NOT NULL DEFAULT 0,
    output_cost_per_token REAL NOT NULL DEFAULT 0,
    updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
);
```

**Seed data** (from litellm.model_cost verified prices):
| model_name | model_pattern | input $/token | output $/token |
|---|---|---|---|
| claude-opus-4-6 | %opus-4-6% | 0.000005 | 0.000025 |
| claude-sonnet-4-6 | %sonnet-4-6% | 0.000003 | 0.000015 |
| claude-sonnet-4-5 | %sonnet-4-5% | 0.000003 | 0.000015 |
| claude-haiku-4-5 | %haiku-4-5% | 0.000001 | 0.000005 |

### 4. Weekly refresh: Background thread on app startup

**Choice**: A background thread starts on FastAPI startup, sleeps for 7 days, then fetches the GitHub JSON and upserts into `model_pricing`. Also exposes `POST /api/pricing/refresh` for manual trigger.

**Rationale**: Simple, no cron dependency, no external scheduler. If the app restarts, the thread restarts. The seed data ensures pricing exists even without network access.

### 5. Cost API endpoints: Mirror existing usage endpoints

**Choice**: Add cost-specific endpoints that mirror the existing usage structure:
- `GET /api/cost/summary` → today's cost + all-time cost (cached 60s like `/api/alltime`)
- `GET /api/cost/daily?days=N` → daily cost over time (same bucketing as `/api/daily`)
- `GET /api/cost/models` → cost breakdown per model
- `GET /api/cost/agents` → cost breakdown per agent
- `GET /api/pricing` → current pricing table
- `POST /api/pricing/refresh` → trigger manual refresh

All cost endpoints use the same SQL JOIN pattern: `SELECT ... FROM usage_log u LEFT JOIN model_pricing p ON u.model LIKE p.model_pattern`.

### 6. Frontend layout: Cost section between all-time cards and today cards

**Choice**: Add a "COST" section with 2 summary cards (Today's Cost, All-Time Cost) between the all-time and today sections. Cost over time chart in a new full-width row. Cost per model donut replaces or sits alongside the existing model donut. Cost column added to model table.

## Risks / Trade-offs

- **LIKE pattern collisions** → If two patterns both match a model name, the JOIN could double-count. Mitigation: use specific enough patterns (e.g., `%opus-4-6%` won't match `sonnet-4-6`). Add a `GROUP BY` or use a subquery with `LIMIT 1` per model.
- **Unknown models get $0 cost** → Models not in the pricing table will show $0. Mitigation: LEFT JOIN (not INNER JOIN) so all rows appear; flag $0-cost models in the UI as "unpriced".
- **GitHub JSON unavailable during refresh** → Mitigation: catch exceptions, keep existing pricing data, log warning. Seed data ensures baseline always exists.
- **Model name drift** → If Anthropic releases new models with different naming, patterns may not match. Mitigation: the manual refresh endpoint + admin visibility of the pricing table lets users fix this.
