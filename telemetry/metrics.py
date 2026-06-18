# telemetry/metrics.py
import aiosqlite
from prometheus_client import Counter, Histogram, Gauge, make_asgi_app

DB_PATH = "/data/gateway_logs.db"

# ==========================================
# PROMETHEUS TIME-SERIES METRICS
# ==========================================
requests_total = Counter(
    "llmgateway_requests_total",
    "Total requests processed",
    ["routing"]  # L1_CACHE, L2_CACHE, groq, gemini, error
)

request_latency_ms = Histogram(
    "llmgateway_request_latency_ms",
    "End-to-end request latency in milliseconds",
    buckets=[10, 25, 50, 100, 250, 500, 1000, 2500, 5000]
)

faiss_vectors_loaded = Gauge(
    "llmgateway_faiss_vectors_total",
    "Number of vectors currently loaded in FAISS index"
)

tokens_consumed = Counter(
    "llmgateway_tokens_total",
    "Total tokens consumed from upstream providers",
    ["model"]
)

# Expose the /metrics endpoint in Prometheus text format
metrics_app = make_asgi_app()

# ==========================================
# SQLITE ALL-TIME STATS (/stats)
# ==========================================
async def get_dashboard_stats() -> dict:
    """Runs fast SQL aggregations for the all-time /stats snapshot."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        
        cursor = await db.execute("""
            SELECT 
                COUNT(*) as total_requests,
                ROUND(AVG(latency_ms), 2) as avg_latency,
                SUM(total_tokens) as total_tokens,
                SUM(CASE WHEN status_code != 200 THEN 1 ELSE 0 END) as total_errors
            FROM request_logs
        """)
        global_stats = dict(await cursor.fetchone())
        global_stats = {k: (v if v is not None else 0) for k, v in global_stats.items()}

        cursor = await db.execute("SELECT cache_hit, COUNT(*) as count FROM request_logs GROUP BY cache_hit")
        cache_stats = {row["cache_hit"]: row["count"] for row in await cursor.fetchall()}
        
        total = global_stats["total_requests"]
        misses = cache_stats.get("MISS", 0)
        hit_rate = round(((total - misses) / total * 100), 1) if total > 0 else 0.0

        cursor = await db.execute("SELECT model, COUNT(*) as count FROM request_logs GROUP BY model")
        model_stats = {row["model"]: row["count"] for row in await cursor.fetchall()}

        return {
            "global": global_stats,
            "hit_rate_percent": hit_rate,
            "cache_breakdown": cache_stats,
            "model_routing": model_stats
        }