"""SQLite database helper for LiteLLM token usage tracking."""
import sqlite3
import os
from pathlib import Path

DB_PATH = "/data/litellm/usage.db"


def get_connection():
    """Get a database connection with WAL mode enabled."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    """Initialize the database with the usage_log table and indexes."""
    # Ensure directory exists
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    
    conn = get_connection()
    cursor = conn.cursor()
    
    # Create table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS usage_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now')),
            model TEXT DEFAULT 'unknown',
            agent TEXT DEFAULT 'unknown',
            prompt_tokens INTEGER DEFAULT 0,
            completion_tokens INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            duration_ms INTEGER DEFAULT 0,
            status TEXT DEFAULT 'success',
            error_message TEXT
        )
    """)
    
    # Create indexes
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_timestamp_agent 
        ON usage_log(timestamp, agent)
    """)
    
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_model 
        ON usage_log(model)
    """)
    
    conn.commit()
    conn.close()
    print(f"Database initialized at {DB_PATH}")


def log_usage(
    model="unknown",
    agent="unknown",
    prompt_tokens=0,
    completion_tokens=0,
    total_tokens=0,
    duration_ms=0,
    status="success",
    error_message=None
):
    """Log a usage event to the database."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO usage_log (
                model, agent, prompt_tokens, completion_tokens, 
                total_tokens, duration_ms, status, error_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            model, agent, prompt_tokens, completion_tokens,
            total_tokens, duration_ms, status, error_message
        ))
        
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error logging usage: {e}")
        return False


if __name__ == "__main__":
    # Initialize database when run directly
    init_db()
    
    # Test insert
    log_usage(
        model="test-model",
        agent="test-agent",
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150,
        duration_ms=1000,
        status="success"
    )
    print("Test record inserted successfully")
