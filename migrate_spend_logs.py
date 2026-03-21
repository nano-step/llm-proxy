#!/usr/bin/env python3
"""
Migrate LiteLLM usage data from SQLite to PostgreSQL.
"""
import sqlite3
import psycopg2
from psycopg2.extras import execute_values
import uuid
from datetime import datetime

# ── SQLite source ──────────────────────────────────────────────────────────────
SQLITE_DB = '/data/litellm/usage.db'

# ── PostgreSQL target ──────────────────────────────────────────────────────────
PG_CONN = "postgresql://capyhome:changeme@localhost:5433/litellm"

# ── Model pricing map (from SQLite model_pricing table) ───────────────────────
# format: {pattern_keyword: (input_cost_per_1M, output_cost_per_1M)}
MODEL_PRICING = {
    'opus':     (3.0, 15.0),   # $3/M input, $15/M output (Claude 4.6 Opus)
    'sonnet':   (3.0, 15.0),   # $3/M input, $15/M output (Claude 4.6 Sonnet)
    'haiku':    (0.8, 4.0),    # $0.80/M input, $4/M output (Claude 4.5 Haiku)
    'gemini':   (1.25, 5.0),   # ~$1.25/M input, $5/M output (Gemini)
}
# Fallback: average Anthropic pricing
DEFAULT_PRICING = (3.0, 15.0)  # $3/M input, $15/M output


def get_spend(model_name, prompt_tokens, completion_tokens):
    """Calculate estimated spend based on model name."""
    if not model_name:
        return 0.0
    model_lower = model_name.lower()
    for key, (in_cost, out_cost) in MODEL_PRICING.items():
        if key in model_lower:
            prompt_spend = (prompt_tokens / 1_000_000) * in_cost
            completion_spend = (completion_tokens / 1_000_000) * out_cost
            return round(prompt_spend + completion_spend, 6)
    # Fallback
    in_cost, out_cost = DEFAULT_PRICING
    return round((prompt_tokens / 1_000_000) * in_cost + (completion_tokens / 1_000_000) * out_cost, 6)


def parse_timestamp(ts_str):
    """Parse ISO timestamp string to PostgreSQL-compatible format."""
    if not ts_str:
        return None
    try:
        dt = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
        return dt
    except Exception:
        return None


def migrate():
    # ── Read from SQLite ───────────────────────────────────────────────────────
    conn = sqlite3.connect(SQLITE_DB)
    cur = conn.cursor()
    cur.execute('SELECT id, timestamp, model, agent, prompt_tokens, completion_tokens, total_tokens, duration_ms, status, error_message FROM usage_log ORDER BY id')
    rows = cur.fetchall()
    conn.close()
    print(f"Read {len(rows)} rows from SQLite")

    if not rows:
        print("Nothing to migrate")
        return

    # ── Prepare records for PostgreSQL ─────────────────────────────────────────
    records = []
    skipped = 0
    for row in rows:
        row_id, timestamp, model, agent, prompt_tokens, completion_tokens, total_tokens, duration_ms, status, error_message = row

        start_time = parse_timestamp(timestamp)
        if not start_time:
            skipped += 1
            continue

        # end_time = start + duration_ms
        from datetime import timedelta
        end_time = start_time + timedelta(milliseconds=duration_ms or 0)

        spend = get_spend(model, prompt_tokens or 0, completion_tokens or 0)
        request_id = str(uuid.uuid4())

        # Map to LiteLLM_SpendLogs columns
        records.append((
            request_id,
            'chat_completeions',
            'migrated-api-key',
            spend,
            total_tokens or 0,
            prompt_tokens or 0,
            completion_tokens or 0,
            start_time,
            end_time,
            duration_ms,
            model or 'unknown',
            '',
            '',
            '',
            '',
            'migrated-user',
            '{}',
            '',
            '',
            '[]',
            None,
            None,
            None,
            None,
            '{}',
            '{}',
            None,
            status or '',
            None,
            agent or None,
            '{}',
        ))

    print(f"Prepared {len(records)} records ({skipped} skipped due to bad timestamps)")

    if not records:
        print("No records to insert")
        return

    # ── Insert into PostgreSQL ─────────────────────────────────────────────────
    pg_conn = psycopg2.connect(PG_CONN)
    pg_cur = pg_conn.cursor()

    insert_sql = """
        INSERT INTO "LiteLLM_SpendLogs" (request_id, call_type, api_key, spend, total_tokens, prompt_tokens, completion_tokens, "startTime", "endTime", request_duration_ms, model, model_id, model_group, custom_llm_provider, api_base, "user", metadata, cache_hit, cache_key, request_tags, team_id, organization_id, end_user, requester_ip_address, messages, response, session_id, status, mcp_namespaced_tool_name, agent_id, proxy_server_request)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (request_id) DO NOTHING
    """

    batch_size = 200
    total_inserted = 0
    for i in range(0, len(records), batch_size):
        batch = records[i:i+batch_size]
        psycopg2.extras.execute_batch(pg_cur, insert_sql, batch)
        pg_conn.commit()
        total_inserted += len(batch)
        print(f"  Inserted {total_inserted}/{len(records)} records...")

    pg_cur.close()
    pg_conn.close()

    print(f"\n✅ Migration complete! {total_inserted} records inserted into LiteLLM_SpendLogs")

    # Verify
    pg_conn2 = psycopg2.connect(PG_CONN)
    pg_cur2 = pg_conn2.cursor()
    pg_cur2.execute('SELECT COUNT(*) FROM \"LiteLLM_SpendLogs\"')
    total = pg_cur2.fetchone()[0]
    print(f"   Total records now in LiteLLM_SpendLogs: {total}")
    pg_cur2.execute('SELECT model, COUNT(*) FROM \"LiteLLM_SpendLogs\" GROUP BY model ORDER BY COUNT(*) DESC LIMIT 10')
    print("   Top models:")
    for r in pg_cur2.fetchall():
        print(f"     {r[0]}: {r[1]}")
    pg_cur2.close()
    pg_conn2.close()


if __name__ == '__main__':
    migrate()
