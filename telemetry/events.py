# telemetry/events.py
import aiosqlite

DB_PATH = "/data/gateway_logs.db"

async def init_events_db():
    """Creates the SQLite telemetry database and enables high-concurrency mode."""
    async with aiosqlite.connect(DB_PATH) as db:
        # 🚨 Turn on Write-Ahead Logging for async concurrency safety
        await db.execute("PRAGMA journal_mode=WAL;")
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS request_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                client_ip TEXT,
                model TEXT,
                cache_hit TEXT,
                latency_ms REAL,
                total_tokens INTEGER,
                status_code INTEGER,
                error TEXT,  -- Brilliant addition!
                query_class TEXT
            )
        """)
        
        # Add column if table already exists from previous version
        try:
            await db.execute("ALTER TABLE request_logs ADD COLUMN query_class TEXT")
        except aiosqlite.OperationalError:
            pass
            
        await db.commit()
        print("📊 Telemetry Events Database Initialized (WAL Mode Enabled).")

async def log_event(client_ip: str, model: str, cache_hit: str, latency_ms: float, total_tokens: int, status_code: int, error: str = None, query_class: str = None):
    """Short-lived, fire-and-forget connection to prevent thread locking."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """
                INSERT INTO request_logs 
                (client_ip, model, cache_hit, latency_ms, total_tokens, status_code, error, query_class) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (client_ip, model, cache_hit, latency_ms, total_tokens, status_code, error, query_class)
            )
            await db.commit()
    except Exception as e:
        print(f"⚠️ Telemetry Drop: Failed to write event to DB: {str(e)}")