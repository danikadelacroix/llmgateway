# telemetry/metrics.py — Prometheus metrics endpoint
# telemetry/metrics.py
import aiosqlite

DB_PATH = "gateway_logs.db"

async def get_dashboard_metrics() -> dict:
    """Runs fast SQL aggregations on the raw event stream."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        
        # 1. Global System Stats
        cursor = await db.execute("""
            SELECT 
                COUNT(*) as total_requests,
                ROUND(AVG(latency_ms), 2) as avg_latency,
                SUM(total_tokens) as total_tokens,
                SUM(CASE WHEN status_code != 200 THEN 1 ELSE 0 END) as total_errors
            FROM request_logs
        """)
        global_stats = dict(await cursor.fetchone())
        
        # Handle empty database edge-case (None -> 0)
        global_stats = {k: (v if v is not None else 0) for k, v in global_stats.items()}

        # 2. Cache Performance (L1 vs L2 vs Miss)
        cursor = await db.execute("""
            SELECT cache_hit, COUNT(*) as count 
            FROM request_logs 
            GROUP BY cache_hit
        """)
        cache_raw = await cursor.fetchall()
        cache_stats = {row["cache_hit"]: row["count"] for row in cache_raw}
        
        # Calculate overall Hit Rate percentage
        total = global_stats["total_requests"]
        misses = cache_stats.get("MISS", 0)
        hits = total - misses
        hit_rate = round((hits / total * 100), 1) if total > 0 else 0.0

        # 3. Model Routing Distribution
        cursor = await db.execute("""
            SELECT model, COUNT(*) as count 
            FROM request_logs 
            GROUP BY model
        """)
        model_stats = {row["model"]: row["count"] for row in await cursor.fetchall()}

        return {
            "global": global_stats,
            "hit_rate_percent": hit_rate,
            "cache_breakdown": cache_stats,
            "model_routing": model_stats
        }
