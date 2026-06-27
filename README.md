# llmgateway

**Production-ready LLM gateway with semantic caching, intelligent routing, provider failover, rate limiting, and live AWS deployment.**

> 🚀 **Live Demo (Swagger):** http://35.154.90.4:8000/docs
> 🟢 **Health Endpoint:** http://35.154.90.4:8000/health
>
> ☁️ **Deployment:** AWS EC2 · Docker · Upstash Redis
> 🧠 **Core Technologies:** FastAPI · LiteLLM · FAISS · fastembed · Redis Lua
>
> 🚧 **Interactive Gradio chat interface with live gateway insights is under development.**

---

## Architecture

Requests first traverse an atomic Redis token bucket, then an exact-match Redis cache, followed by a semantic FAISS cache before being routed to the highest-priority available LLM provider, minimizing latency and upstream API usage.

```
Client Request
      │
      ▼
┌─────────────────────────────────────────┐
│           llmgateway Gateway            │
│                                         │
│  Redis Token Bucket Limiter (Lua)       │
│         │                               │
│  L1 Redis Hash Cache ──── hit ─────────►│── Response (<50ms)
│         │ miss                          │
│  L2 FAISS Semantic Cache ───── hit ────►│── Response (<200ms)
│         │ miss                          │
│  Cost-Aware Traffic Router              │
│         │                               │
│  Async Connection Pool                  │
│         │                               │
│  Telemetry Event Pipeline               │
└─────────────────────────────────────────┘
      │
      ▼
Upstream Endpoints (Groq / Gemini)
      │
      ▼
Prometheus /metrics ──► Grafana Dashboard
```

---

## Why llmgateway?

| Feature       | Standard Proxy     | llmgateway                                    |
| ------------- | ------------------ | --------------------------------------------- |
| Routes by     | URL / headers      | Payload semantics + cost                      |
| Cache key     | URL string         | Embedding vector (cosine similarity)          |
| Routing logic | Static config      | Priority-ordered with automatic failover      |
| Rate limiting | Middleware counter | Atomic Redis Lua token bucket                 |
| Observability | Access logs        | p95/p99 latency, token burn, cache statistics |

---

## Technology Stack

### Backend
- **FastAPI**
- **asyncio**
- **httpx**
- **LiteLLM**

### Infrastructure
- **Docker**
- **AWS EC2**
- **Upstash Redis**
- **FAISS**
- **fastembed (BGE-small-en-v1.5)**

### Reliability
- Priority-based provider failover (Groq → Gemini)
- Dual-layer semantic cache (Redis + FAISS)
- Atomic Redis Lua token-bucket rate limiting

### Observability
- Prometheus
- Grafana
- SQLite WAL telemetry

---

## Caching Architecture

Requests flow through two cache layers before hitting any upstream model.

### L1 — Exact Match (Redis)

A SHA-256 hash of the serialized message array is used as the cache key. Exact matches are served directly from Redis in sub-millisecond time with zero compute cost.

### L2 — Semantic Match (FAISS + fastembed)

BGE-small-en-v1.5 embeds each prompt into a 384-dimensional vector. FAISS performs cosine similarity search against previously cached requests. Queries with a similarity score ≥ **0.85** return the cached response without contacting any upstream LLM.

New responses are written to both cache layers simultaneously. FAISS vectors are restored from Redis during startup, allowing semantic cache persistence across container restarts.

---

## Local Development

```bash
git clone https://github.com/danikadelacroix/llmgateway.git
cd llmgateway

cp .env.example .env
# Fill in your API keys

docker compose up -d
```

The development compose starts:
- Gateway
- Prometheus
- Grafana

---

## Production Deployment

```bash
cp .env.example .env
# Configure Upstash Redis + API keys

docker compose -f docker-compose.prod.yml up -d
```

---

## API Usage

```bash
curl -X POST http://localhost:8000/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "model": "auto",
    "messages": [
      {
        "role": "user",
        "content": "hello"
      }
    ]
  }'
```

Available endpoints:

- `POST /v1/chat` — OpenAI-compatible chat completion endpoint
- `GET /health` — Health check + FAISS vector count
- `GET /stats` — SQLite telemetry aggregates
- `GET /metrics` — Prometheus metrics

---

## Benchmarks

Run against a warm semantic cache:

```bash
python scripts/benchmark.py
```

| Concurrent Users | p50    | p95     | p99     |
| ---------------- | ------ | ------- | ------- |
| 10               | 110 ms | 157 ms  | 407 ms  |
| 50               | 328 ms | 1125 ms | 1547 ms |
| 100              | 359 ms | 672 ms  | 734 ms  |

> p99 latency at 100 concurrent users outperformed the 50-user run because constraining ONNX embedding threads to one produced a smoother request distribution during the initial cache warm-up phase.

---

## System Characteristics

| Property                  | Value                                        |
| ------------------------- | -------------------------------------------- |
| L1 Cache Latency          | <50 ms                                       |
| L2 Semantic Cache Latency | <200 ms                                      |
| Upstream LLM Latency      | 500–2000 ms                                  |
| Cache Speedup             | 10–40× (L1), 2.5–10× (L2)                    |
| FAISS Search (1k vectors) | <0.1 ms                                      |
| Similarity Threshold      | 0.85                                         |
| Rate Limiter              | 5,000 token capacity, 1,000 token/sec refill |

---

## Observability

The gateway exposes Prometheus metrics for:
- Request throughput
- p95 / p99 latency
- Token consumption
- Cache hit ratio
- Provider routing

Import `docs/grafana_dashboard.json` to restore the complete dashboard.

---

## Environment Variables

```bash
GROQ_API_KEY=your_key_here
GEMINI_API_KEY=your_key_here

# Local Redis or Upstash
REDIS_URL=rediss://<upstash-url>

RATE_LIMIT_CAPACITY=5000
RATE_LIMIT_REFILL_RATE=1000
```

---

## Roadmap

- Interactive Gradio chat interface
- Live gateway insights (cache hit/miss, provider, latency, similarity score)
- HTTPS (Let's Encrypt) and optional custom domain
- Support for additional LLM providers

---

**Author:** Anushka Rajput  
*Built to optimize LLM infrastructure.*
