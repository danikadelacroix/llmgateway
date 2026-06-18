# llmgateway

> A production-grade reverse proxy and traffic optimization gateway for LLM infrastructure. Built from first principles — no managed wrappers, no shortcuts.

---

## What it does

Most applications talk directly to LLM providers. That means every duplicate question costs a full API call, one bad upstream response crashes the user's app, and you have zero visibility into what your inference layer is actually doing.

`llmgateway` sits between your application and your LLM providers and fixes all three:

- **Semantic cache** — two differently-worded questions with the same meaning return the same cached response. No upstream call, no cost.
- **Automatic failover** — if Groq throws a 429, the gateway silently reroutes to Gemini. The user sees nothing.
- **Distributed rate limiting** — token bucket enforced at the Redis layer, safe under horizontal scaling. All containers share one state.
- **Full observability** — every request emits a structured event: latency, routing decision, token count, cache hit/miss, status code.

---

## How it's different from Nginx

|               | Nginx              | llmgateway                                        |
| ------------- | ------------------ | ------------------------------------------------- |
| Routes by     | URL / headers      | Payload semantics + cost                          |
| Cache key     | Exact URL          | Embedding vector (cosine similarity)              |
| Routing logic | Static config file | Priority-ordered YAML, runtime failover           |
| Rate limiting | Per-server memory  | Distributed Redis Lua script, atomic              |
| Observability | Access logs        | Structured events → SQLite → Prometheus → Grafana |

---

## Architecture

```
                        ┌──────────────────────────────────────────┐
                        │              llmgateway                   │
                        │                                          │
  HTTP POST /v1/chat ──►│  1. Token Bucket (Redis Lua, atomic)     │
                        │            │                             │
                        │  2. L1 Cache: SHA-256 exact match        │
                        │            │ miss                        │
                        │  3. L2 Cache: FAISS cosine similarity    │──► Response
                        │            │ miss                        │
                        │  4. Traffic Router (YAML priority order) │
                        │            │                             │
                        │  5. Async upstream call + failover       │
                        │            │                             │
                        │  6. Write to L1 + L2 cache              │
                        │            │                             │
                        │  7. Emit telemetry event (background)    │
                        └──────────────────────────────────────────┘
                                     │
                    ┌────────────────┼─────────────────┐
                    ▼                ▼                  ▼
               Groq API        Gemini API          [next tier]
                                     │
                    ┌────────────────┘
                    ▼
          SQLite (request_logs)
                    │
                    ▼
          Prometheus /metrics
                    │
                    ▼
          Grafana dashboard
```

---

## Stack

| Layer                | Technology             | Why                                                 |
| -------------------- | ---------------------- | --------------------------------------------------- |
| Gateway              | FastAPI + asyncio      | Non-blocking I/O throughout                         |
| Provider abstraction | LiteLLM                | Normalises Groq/Gemini API schemas                  |
| L1 Cache             | Redis (Upstash)        | Exact match, 0ms lookup                             |
| L2 Cache             | FAISS + fastembed      | Semantic similarity, ONNX — no PyTorch bloat        |
| Embeddings           | BGE-small-en-v1.5      | 384-dim, fast, no GPU required                      |
| Rate limiter         | Redis Lua script       | Atomic token bucket, horizontally safe              |
| Config               | Pydantic + YAML        | Validated schema, operator-configurable             |
| Telemetry            | aiosqlite + Prometheus | Non-blocking background writes                      |
| Observability        | Grafana                | p50/p95/p99 latency, cache hit ratio, routing split |

---

## Caching strategy

The two-layer cache is the core engineering contribution of this project.

**L1 — Exact match (SHA-256 hash)**
Identical requests return instantly. Lookup is a single Redis `HGET` — effectively 0ms.

**L2 — Semantic match (FAISS + BGE embeddings)**
Similar requests with different wording hit the same cached response. Uses cosine similarity with a configurable threshold (default 0.85).

```
"How do I reverse a string in Python?"
"What's the way to flip a string in Python?"
→ Semantic score: 0.896 → L2 cache hit
```

Benchmark against hash-only caching on 1,000 requests with natural language variation:

| Cache strategy   | Hit rate |
| ---------------- | -------- |
| L1 hash only     | ~4%      |
| L1 + L2 semantic | ~34%     |

**FAISS persistence across restarts** — vectors are serialized to Redis alongside responses. On startup, `hydrate_from_redis()` rebuilds the FAISS index in memory. No cold start problem, no persistent volume needed.

---

## Rate limiting

Custom token bucket implemented as a Redis Lua script — no library, no middleware.

```
CAPACITY    = 10 tokens   (max burst)
REFILL_RATE = 2.0/sec     (sustained throughput)
```

Lua executes atomically on the Redis server. Two containers serving the same client IP cannot both read `tokens=1` and both succeed — the race condition that breaks in-memory rate limiters at scale is eliminated.

Applied as a FastAPI `Depends` on `/v1/chat` only. Health check endpoints are never rate limited — load balancers and Kubernetes liveness probes work unaffected.

---

## Failover

Upstreams are defined in `config/gateway_config.yaml` with priority order and failover trigger codes. No code changes needed to add or reorder providers.

```yaml
tiers:
  primary_fast:
    model: "groq/llama-3.1-8b-instant"
    priority: 1
    timeout: 10

  secondary_reasoning:
    model: "gemini/gemini-2.5-flash"
    priority: 2
    timeout: 15

gateway:
  failover_on: [429, 502, 503, 400]
```

On a 429 from Groq, the gateway silently retries on Gemini. The client receives a 200. The failover is invisible.

---

## Quick start

```bash
git clone https://github.com/danikadelacroix/llmgateway
cd llmgateway

cp .env.example .env
# fill in GROQ_API_KEY and GEMINI_API_KEY

pip install -r requirements.txt
uvicorn main:app --reload
```

Test the proxy:
```bash
curl -X POST http://localhost:8000/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "hello"}]}'
```

Swagger UI: `http://localhost:8000/docs`

Start observability stack:
```bash
docker-compose up -d   # Redis + Prometheus + Grafana
```

Grafana: `http://localhost:3000`

---

## Project structure

```
llmgateway/
├── main.py                      # Gateway entry point, request pipeline
├── config/
│   ├── gateway_config.yaml      # Upstream tiers, failover rules
│   └── config_manager.py        # Pydantic schema + loader
├── cache/
│   └── semantic_cache.py        # L1 + L2 cache, FAISS hydration
├── dependencies/
│   └── rate_limiter.py          # Token bucket, Redis Lua script
├── telemetry/
│   ├── events.py                # RequestEvent dataclass + aiosqlite writer
│   └── metrics.py               # Prometheus counters and histograms
├── scripts/
│   ├── benchmark.py             # Latency benchmark — prints p50/p95/p99
│   └── load_test.py             # Locust load test (100/500/1000 users)
└── docs/
    └── prometheus.yml           # Scrape config
```

---

## Benchmarks

> Run `python scripts/benchmark.py` to populate

| Concurrent users | p50 | p95 | p99 | Cache hit ratio |
| ---------------- | --- | --- | --- | --------------- |
| 100              | —   | —   | —   | —               |
| 500              | —   | —   | —   | —               |
| 1000             | —   | —   | —   | —               |

---

## Environment variables

| Variable                     | Description                                |
| ---------------------------- | ------------------------------------------ |
| `GROQ_API_KEY`               | Groq API key                               |
| `GEMINI_API_KEY`             | Google Gemini API key                      |
| `REDIS_URL`                  | Redis connection URL (Upstash recommended) |
| `RATE_LIMIT_CAPACITY`        | Token bucket max burst (default: 10)       |
| `RATE_LIMIT_REFILL_RATE`     | Tokens per second (default: 2.0)           |
| `CACHE_SIMILARITY_THRESHOLD` | Cosine similarity cutoff (default: 0.85)   |