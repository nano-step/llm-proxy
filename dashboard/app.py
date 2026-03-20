"""FastAPI server for LiteLLM token usage dashboard."""
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any

from cachetools import TTLCache, cached
from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

DB_PATH = "/data/litellm/usage.db"
alltime_cache = TTLCache(maxsize=32, ttl=60)

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
        WHERE timestamp >= ?
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
        WHERE DATE(timestamp) >= ?
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
            WHERE timestamp >= ?
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
            WHERE timestamp >= ?
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
