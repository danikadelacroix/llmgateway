# telemetry/events.py
import aiosqlite

# In a production environment, this would be an absolute path from your config
DB_PATH = "gateway_logs.db"

async def init_events_db():
    """Creates the SQLite telemetry database if it doesn't exist."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS request_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                client_ip TEXT,
                model TEXT,
                cache_hit TEXT,  -- 'L1', 'L2', or 'MISS'
                latency_ms REAL,
                total_tokens INTEGER,
                status_code INTEGER,
                error TEXT
            )
        """)
        await db.commit()
        print("📊 Telemetry Events Database Initialized.")
        return db

async def log_event(db, client_ip, model, cache_hit, latency_ms, total_tokens, status_code):
    try:
        await db.execute(
            "INSERT INTO request_logs (client_ip, model, cache_hit, latency_ms, total_tokens, status_code) VALUES (?, ?, ?, ?, ?, ?)",
            (client_ip, model, cache_hit, latency_ms, total_tokens, status_code)
        )
        await db.commit()
    except Exception as e:
        print(f"⚠️ Telemetry drop: {str(e)}")