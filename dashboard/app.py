"""FastAPI server for LiteLLM token usage dashboard."""
import sqlite3
import threading
import urllib.request
from datetime import datetime, timedelta
import json as json_module
from pathlib import Path
from typing import Dict, List, Any

from cachetools import TTLCache, cached
from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

try:
    import litellm
    HAS_LITELLM = True
except ImportError:
    litellm = None
    HAS_LITELLM = False

DB_PATH = "/data/litellm/usage.db"
alltime_cache = TTLCache(maxsize=32, ttl=60)
cost_cache = TTLCache(maxsize=32, ttl=60)

app = FastAPI(title="LiteLLM Token Usage Dashboard")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db():
    """Get database connection."""
    return sqlite3.connect(DB_PATH)


PRICING_GITHUB_URL = "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"

DEFAULT_PRICING = [
    ("claude-opus-4-6", "%opus-4-6%", 0.000005, 0.000025),
    ("claude-sonnet-4-6", "%sonnet-4-6%", 0.000003, 0.000015),
    ("claude-sonnet-4-5", "%sonnet-4-5%", 0.000003, 0.000015),
    ("claude-haiku-4-5", "%haiku-4-5%", 0.000001, 0.000005),
    ("gemini-3-pro", "%gemini-3-pro%", 0.000002, 0.000012),
]


def _init_pricing_table():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS model_pricing (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            model_name TEXT UNIQUE NOT NULL,
            model_pattern TEXT NOT NULL,
            input_cost_per_token REAL NOT NULL DEFAULT 0,
            output_cost_per_token REAL NOT NULL DEFAULT 0,
            updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
        )
    """)
    conn.commit()
    conn.close()


def _seed_pricing():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM model_pricing")
    if cursor.fetchone()[0] > 0:
        conn.close()
        return

    pricing_data = DEFAULT_PRICING
    if HAS_LITELLM:
        mc = getattr(litellm, "model_cost", {})
        litellm_pricing = []
        for name, pattern, default_in, default_out in DEFAULT_PRICING:
            for key in [name, f"anthropic/{name}", name.replace("-", "."), f"anthropic/{name.replace('-', '.')}" ]:
                entry = mc.get(key)
                if entry and "input_cost_per_token" in entry:
                    litellm_pricing.append((
                        name,
                        pattern,
                        entry["input_cost_per_token"],
                        entry["output_cost_per_token"],
                    ))
                    break
            else:
                litellm_pricing.append((name, pattern, default_in, default_out))
        pricing_data = litellm_pricing

    for model_name, model_pattern, input_cost, output_cost in pricing_data:
        cursor.execute(
            "INSERT OR IGNORE INTO model_pricing (model_name, model_pattern, input_cost_per_token, output_cost_per_token) VALUES (?, ?, ?, ?)",
            (model_name, model_pattern, input_cost, output_cost),
        )
    conn.commit()
    conn.close()


def _refresh_pricing_from_github():
    try:
        req = urllib.request.Request(PRICING_GITHUB_URL, headers={"User-Agent": "litellm-dashboard"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json_module.loads(resp.read().decode())

        conn = get_db()
        cursor = conn.cursor()
        for model_name, pattern, _, _ in DEFAULT_PRICING:
            for key in [model_name, f"anthropic/{model_name}", model_name.replace("-", "."), f"anthropic/{model_name.replace('-', '.')}" ]:
                entry = data.get(key)
                if entry and "input_cost_per_token" in entry:
                    cursor.execute("""
                        INSERT INTO model_pricing (model_name, model_pattern, input_cost_per_token, output_cost_per_token, updated_at)
                        VALUES (?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%S','now'))
                        ON CONFLICT(model_name) DO UPDATE SET
                            input_cost_per_token=excluded.input_cost_per_token,
                            output_cost_per_token=excluded.output_cost_per_token,
                            updated_at=excluded.updated_at
                    """, (model_name, pattern, entry["input_cost_per_token"], entry["output_cost_per_token"]))
                    break
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[Pricing] Refresh failed: {e}")
        return False


def _weekly_pricing_refresh():
    import time
    while True:
        time.sleep(7 * 24 * 3600)
        _refresh_pricing_from_github()


def add_security_headers(response: JSONResponse) -> JSONResponse:
    """Add security headers to response."""
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    return response


@app.middleware("http")
async def add_security_headers_middleware(request, call_next):
    """Add security headers to all responses."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    return response


_init_pricing_table()
_seed_pricing()
threading.Thread(target=_weekly_pricing_refresh, daemon=True).start()


@app.get("/")
async def root():
    """Serve the main dashboard page."""
    static_path = Path(__file__).parent / "static" / "index.html"
    return FileResponse(static_path)


@app.get("/api/summary")
async def get_summary() -> Dict[str, Any]:
    """Get today's summary statistics."""
    conn = get_db()
    cursor = conn.cursor()
    
    # Get today's date
    today = datetime.now().strftime("%Y-%m-%d")
    
    # Total tokens today
    cursor.execute("""
        SELECT 
            COALESCE(SUM(total_tokens), 0) as total_tokens,
            COALESCE(SUM(prompt_tokens), 0) as input_tokens,
            COALESCE(SUM(completion_tokens), 0) as output_tokens,
            COUNT(*) as requests
        FROM usage_log
        WHERE DATE(timestamp) = ?
    """, (today,))
    
    row = cursor.fetchone()
    total_tokens_today = row[0]
    total_input_today = row[1]
    total_output_today = row[2]
    requests_today = row[3]
    
    # Top agent today
    cursor.execute("""
        SELECT agent, SUM(total_tokens) as tokens
        FROM usage_log
        WHERE DATE(timestamp) = ?
        GROUP BY agent
        ORDER BY tokens DESC
        LIMIT 1
    """, (today,))
    
    top_agent_row = cursor.fetchone()
    top_agent = {"name": top_agent_row[0], "tokens": top_agent_row[1]} if top_agent_row else {"name": "N/A", "tokens": 0}
    
    # Top model today
    cursor.execute("""
        SELECT model, SUM(total_tokens) as tokens
        FROM usage_log
        WHERE DATE(timestamp) = ?
        GROUP BY model
        ORDER BY tokens DESC
        LIMIT 1
    """, (today,))
    
    top_model_row = cursor.fetchone()
    top_model = {"name": top_model_row[0], "tokens": top_model_row[1]} if top_model_row else {"name": "N/A", "tokens": 0}
    
    # Per-agent breakdown
    cursor.execute("""
        SELECT 
            agent,
            SUM(total_tokens) as total_tokens,
            SUM(prompt_tokens) as input_tokens,
            SUM(completion_tokens) as output_tokens,
            COUNT(*) as requests
        FROM usage_log
        WHERE DATE(timestamp) = ?
        GROUP BY agent
        ORDER BY total_tokens DESC
    """, (today,))
    
    per_agent = [
        {
            "agent": row[0],
            "total_tokens": row[1],
            "input_tokens": row[2],
            "output_tokens": row[3],
            "requests": row[4]
        }
        for row in cursor.fetchall()
    ]
    
    # Per-model breakdown
    cursor.execute("""
        SELECT 
            model,
            SUM(total_tokens) as total_tokens,
            SUM(prompt_tokens) as input_tokens,
            SUM(completion_tokens) as output_tokens,
            COUNT(*) as requests
        FROM usage_log
        WHERE DATE(timestamp) = ?
        GROUP BY model
        ORDER BY total_tokens DESC
    """, (today,))
    
    per_model = [
        {
            "model": row[0],
            "total_tokens": row[1],
            "input_tokens": row[2],
            "output_tokens": row[3],
            "requests": row[4]
        }
        for row in cursor.fetchall()
    ]
    
    conn.close()
    
    return {
        "total_tokens_today": total_tokens_today,
        "total_input_today": total_input_today,
        "total_output_today": total_output_today,
        "requests_today": requests_today,
        "top_agent": top_agent,
        "top_model": top_model,
        "per_agent": per_agent,
        "per_model": per_model
    }


@app.get("/api/hourly")
async def get_hourly(days: int = Query(1, ge=1, le=30)) -> Dict[str, List[Dict[str, Any]]]:
    """Get hourly token usage data."""
    conn = get_db()
    cursor = conn.cursor()
    
    # Calculate start time
    start_time = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
    
    cursor.execute("""
        SELECT 
            strftime('%Y-%m-%dT%H:00', timestamp) as hour,
            SUM(prompt_tokens) as input_tokens,
            SUM(completion_tokens) as output_tokens,
            ROUND(AVG(duration_ms)) as avg_duration_ms,
            COUNT(*) as requests
        FROM usage_log
        WHERE timestamp >= ? AND total_tokens > 0
        GROUP BY hour
        ORDER BY hour
    """, (start_time,))
    
    data = [
        {
            "hour": row[0],
            "input_tokens": row[1],
            "output_tokens": row[2],
            "avg_duration_ms": row[3],
            "requests": row[4]
        }
        for row in cursor.fetchall()
    ]
    
    conn.close()
    
    return {"data": data}


@app.get("/api/daily")
async def get_daily(days: int = Query(30, ge=1, le=365)) -> Dict[str, List[Dict[str, Any]]]:
    """Get daily token usage data."""
    conn = get_db()
    cursor = conn.cursor()
    
    # Calculate start date
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    
    cursor.execute("""
        SELECT 
            DATE(timestamp) as date,
            SUM(prompt_tokens) as input_tokens,
            SUM(completion_tokens) as output_tokens,
            ROUND(AVG(duration_ms)) as avg_duration_ms,
            COUNT(*) as requests
        FROM usage_log
        WHERE DATE(timestamp) >= ? AND total_tokens > 0
        GROUP BY date
        ORDER BY date
    """, (start_date,))
    
    data = [
        {
            "date": row[0],
            "input_tokens": row[1],
            "output_tokens": row[2],
            "avg_duration_ms": row[3],
            "requests": row[4]
        }
        for row in cursor.fetchall()
    ]
    
    conn.close()
    
    return {"data": data}


@cached(alltime_cache)
def _fetch_alltime_data() -> Dict[str, Any]:
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            COALESCE(SUM(total_tokens), 0),
            COALESCE(SUM(prompt_tokens), 0),
            COALESCE(SUM(completion_tokens), 0),
            COUNT(*),
            ROUND(AVG(duration_ms)),
            MIN(timestamp),
            MAX(timestamp)
        FROM usage_log
        WHERE total_tokens > 0
    """)

    row = cursor.fetchone()
    conn.close()

    total_requests = row[3] if row else 0
    avg_duration_ms = row[4] if row and row[4] is not None else 0

    return {
        "total_tokens": row[0] if row else 0,
        "total_input": row[1] if row else 0,
        "total_output": row[2] if row else 0,
        "total_requests": total_requests,
        "avg_duration_ms": avg_duration_ms,
        "first_seen": row[5] if row and total_requests > 0 else None,
        "last_seen": row[6] if row and total_requests > 0 else None,
    }


@app.get("/api/alltime")
async def get_alltime() -> Dict[str, Any]:
    return _fetch_alltime_data()


@app.get("/api/latency")
async def get_latency(days: int = Query(1, ge=1, le=365)) -> Dict[str, List[Dict[str, Any]]]:
    conn = get_db()
    cursor = conn.cursor()

    start_time = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")

    if days == 1:
        cursor.execute("""
            SELECT
                strftime('%Y-%m-%dT%H:00', timestamp) as hour,
                ROUND(AVG(duration_ms)) as avg_duration_ms,
                COUNT(*) as requests
            FROM usage_log
            WHERE timestamp >= ? AND total_tokens > 0
            GROUP BY hour
            ORDER BY hour
        """, (start_time,))

        data = [
            {
                "hour": row[0],
                "avg_duration_ms": row[1],
                "requests": row[2]
            }
            for row in cursor.fetchall()
        ]
    else:
        cursor.execute("""
            SELECT
                DATE(timestamp) as date,
                ROUND(AVG(duration_ms)) as avg_duration_ms,
                COUNT(*) as requests
            FROM usage_log
            WHERE timestamp >= ? AND total_tokens > 0
            GROUP BY date
            ORDER BY date
        """, (start_time,))

        data = [
            {
                "date": row[0],
                "avg_duration_ms": row[1],
                "requests": row[2]
            }
            for row in cursor.fetchall()
        ]

    conn.close()
    return {"data": data}


@app.get("/api/cumulative")
async def get_cumulative(days: int = Query(30, ge=1, le=9999)) -> Dict[str, List[Dict[str, Any]]]:
    conn = get_db()
    cursor = conn.cursor()

    start_time = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")

    if days == 1:
        cursor.execute("""
            SELECT
                strftime('%Y-%m-%dT%H:00', timestamp) as hour,
                SUM(total_tokens) as tokens
            FROM usage_log
            WHERE timestamp >= ?
            GROUP BY hour
            ORDER BY hour
        """, (start_time,))

        data = [
            {
                "hour": row[0],
                "tokens": row[1]
            }
            for row in cursor.fetchall()
        ]
    else:
        cursor.execute("""
            SELECT
                DATE(timestamp) as date,
                SUM(total_tokens) as tokens
            FROM usage_log
            WHERE timestamp >= ?
            GROUP BY date
            ORDER BY date
        """, (start_time,))

        data = [
            {
                "date": row[0],
                "tokens": row[1]
            }
            for row in cursor.fetchall()
        ]

    conn.close()

    cumulative = 0
    for item in data:
        cumulative += item["tokens"]
        item["cumulative_tokens"] = cumulative

    return {"data": data}


@app.get("/api/pricing")
async def get_pricing():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT model_name, model_pattern, input_cost_per_token, output_cost_per_token, updated_at FROM model_pricing ORDER BY model_name")
    rows = [
        {
            "model_name": r[0],
            "model_pattern": r[1],
            "input_cost_per_token": r[2],
            "output_cost_per_token": r[3],
            "updated_at": r[4],
        }
        for r in cursor.fetchall()
    ]
    conn.close()
    return {"pricing": rows}


@app.post("/api/pricing/refresh")
async def refresh_pricing():
    success = _refresh_pricing_from_github()
    return {"success": success}


@cached(cost_cache)
def _fetch_alltime_cost():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            COALESCE(SUM(u.prompt_tokens * COALESCE(p.input_cost_per_token, 0)), 0),
            COALESCE(SUM(u.completion_tokens * COALESCE(p.output_cost_per_token, 0)), 0)
        FROM usage_log u
        LEFT JOIN model_pricing p ON u.model LIKE p.model_pattern
    """)
    row = cursor.fetchone()
    conn.close()
    return {
        "alltime_input_cost": row[0],
        "alltime_output_cost": row[1],
        "alltime_cost": row[0] + row[1],
    }


@app.get("/api/cost/summary")
async def get_cost_summary():
    today = datetime.now().strftime("%Y-%m-%d")
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            COALESCE(SUM(u.prompt_tokens * COALESCE(p.input_cost_per_token, 0)), 0),
            COALESCE(SUM(u.completion_tokens * COALESCE(p.output_cost_per_token, 0)), 0)
        FROM usage_log u
        LEFT JOIN model_pricing p ON u.model LIKE p.model_pattern
        WHERE DATE(u.timestamp) = ?
    """, (today,))
    row = cursor.fetchone()
    conn.close()
    today_input = row[0]
    today_output = row[1]

    alltime = _fetch_alltime_cost()
    return {
        "today_cost": round(today_input + today_output, 6),
        "today_input_cost": round(today_input, 6),
        "today_output_cost": round(today_output, 6),
        "alltime_cost": round(alltime["alltime_cost"], 6),
        "alltime_input_cost": round(alltime["alltime_input_cost"], 6),
        "alltime_output_cost": round(alltime["alltime_output_cost"], 6),
    }


@app.get("/api/cost/daily")
async def get_cost_daily(days: int = Query(30, ge=1, le=9999)):
    conn = get_db()
    cursor = conn.cursor()
    start_time = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")

    if days == 1:
        cursor.execute("""
            SELECT
                strftime('%Y-%m-%dT%H:00', u.timestamp) as hour,
                COALESCE(SUM(u.prompt_tokens * COALESCE(p.input_cost_per_token, 0)), 0) as input_cost,
                COALESCE(SUM(u.completion_tokens * COALESCE(p.output_cost_per_token, 0)), 0) as output_cost,
                COUNT(*) as requests
            FROM usage_log u
            LEFT JOIN model_pricing p ON u.model LIKE p.model_pattern
            WHERE u.timestamp >= ?
            GROUP BY hour
            ORDER BY hour
        """, (start_time,))
        data = [
            {"hour": r[0], "input_cost": r[1], "output_cost": r[2], "cost": r[1] + r[2], "requests": r[3]}
            for r in cursor.fetchall()
        ]
    else:
        cursor.execute("""
            SELECT
                DATE(u.timestamp) as date,
                COALESCE(SUM(u.prompt_tokens * COALESCE(p.input_cost_per_token, 0)), 0) as input_cost,
                COALESCE(SUM(u.completion_tokens * COALESCE(p.output_cost_per_token, 0)), 0) as output_cost,
                COUNT(*) as requests
            FROM usage_log u
            LEFT JOIN model_pricing p ON u.model LIKE p.model_pattern
            WHERE u.timestamp >= ?
            GROUP BY date
            ORDER BY date
        """, (start_time,))
        data = [
            {"date": r[0], "input_cost": r[1], "output_cost": r[2], "cost": r[1] + r[2], "requests": r[3]}
            for r in cursor.fetchall()
        ]

    conn.close()
    return {"data": data}


@app.get("/api/cost/models")
async def get_cost_models():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            u.model,
            COALESCE(SUM(u.prompt_tokens * COALESCE(p.input_cost_per_token, 0)), 0) as input_cost,
            COALESCE(SUM(u.completion_tokens * COALESCE(p.output_cost_per_token, 0)), 0) as output_cost,
            COUNT(*) as requests,
            SUM(u.prompt_tokens) as input_tokens,
            SUM(u.completion_tokens) as output_tokens
        FROM usage_log u
        LEFT JOIN model_pricing p ON u.model LIKE p.model_pattern
        GROUP BY u.model
        ORDER BY (input_cost + output_cost) DESC
    """)
    models = [
        {
            "model": r[0],
            "input_cost": r[1],
            "output_cost": r[2],
            "cost": r[1] + r[2],
            "requests": r[3],
            "input_tokens": r[4],
            "output_tokens": r[5],
        }
        for r in cursor.fetchall()
    ]
    conn.close()
    return {"models": models}


@app.get("/api/cost/agents")
async def get_cost_agents():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            u.agent,
            COALESCE(SUM(u.prompt_tokens * COALESCE(p.input_cost_per_token, 0)), 0) as input_cost,
            COALESCE(SUM(u.completion_tokens * COALESCE(p.output_cost_per_token, 0)), 0) as output_cost,
            COUNT(*) as requests
        FROM usage_log u
        LEFT JOIN model_pricing p ON u.model LIKE p.model_pattern
        GROUP BY u.agent
        ORDER BY (input_cost + output_cost) DESC
    """)
    agents = [
        {"agent": r[0], "input_cost": r[1], "output_cost": r[2], "cost": r[1] + r[2], "requests": r[3]}
        for r in cursor.fetchall()
    ]
    conn.close()
    return {"agents": agents}


@app.get("/api/agents")
async def get_agents() -> Dict[str, List[Dict[str, Any]]]:
    """Get all agents with their total usage."""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT 
            agent,
            SUM(total_tokens) as total_tokens,
            SUM(prompt_tokens) as input_tokens,
            SUM(completion_tokens) as output_tokens,
            COUNT(*) as requests
        FROM usage_log
        GROUP BY agent
        ORDER BY total_tokens DESC
    """)
    
    agents = [
        {
            "agent": row[0],
            "total_tokens": row[1],
            "input_tokens": row[2],
            "output_tokens": row[3],
            "requests": row[4]
        }
        for row in cursor.fetchall()
    ]
    
    conn.close()
    
    return {"agents": agents}


@app.get("/api/models")
async def get_models() -> Dict[str, List[Dict[str, Any]]]:
    """Get all models with their total usage."""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT 
            model,
            SUM(prompt_tokens) as input_tokens,
            SUM(completion_tokens) as output_tokens,
            SUM(total_tokens) as total_tokens,
            COUNT(*) as requests
        FROM usage_log
        GROUP BY model
        ORDER BY total_tokens DESC
    """)
    
    models = [
        {
            "model": row[0],
            "input_tokens": row[1],
            "output_tokens": row[2],
            "total_tokens": row[3],
            "requests": row[4]
        }
        for row in cursor.fetchall()
    ]
    
    conn.close()
    
    return {"models": models}


# Mount static files
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8099)
