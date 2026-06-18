# llmgateway

**High-availability reverse proxy and traffic optimization gateway for LLM infrastructure.**

Intercepts, inspects, and dynamically routes payloads across distributed upstream endpoints with semantic caching, cost-aware routing, and real-time observability.

---

## Architecture

```
Client Request
      │
      ▼
┌─────────────────────────────────────────┐
│           llmgateway Gateway            │
│                                         │
│  Redis Token Bucket Limiter(Lua)        │
│         │                               │
│  L1 Redis Hash Cache ──── hit ─────────►│── Response(<50ms)
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

## What makes this different from a standard proxy

| Feature       | Standard Proxy     | llmgateway                                        |
| ------------- | ------------------ | ------------------------------------------------- |
| Routes by     | URL / headers      | Payload semantics + cost                          |
| Cache key     | URL string         | Embedding vector (cosine similarity)              |
| Routing logic | Static config      | Priority-ordered with failover                    |
| Rate limiting | Middleware counter | Atomic Redis Lua token bucket                     |
| Observability | Access logs        | p95/p99 latency, token burn rate, cache hit ratio |

## Stack

- **Gateway:** FastAPI + asyncio + httpx
- **Rate limiting:** Custom token bucket via Redis Lua scripting (atomic, race-condition safe)
- **Cache:** Two-layer — L1 Redis exact hash match → L2 FAISS semantic similarity (BGE-small via fastembed)
- **Telemetry:** Prometheus (real-time metrics) + SQLite WAL (all-time event log)
- **Observability:** Grafana dashboard with 5 panels
- **Inference:** LiteLLM routing to Groq LLaMA 3.1 (primary) and Gemini 2.0 Flash (failover)

## Caching Architecture

Requests flow through two cache layers before hitting any upstream model:

**L1 — Exact Match (Redis hash)**
SHA-256 hash of the serialized message array. Sub-millisecond lookup. Zero network cost.

**L2 — Semantic Match (FAISS + fastembed)**
BGE-small-en-v1.5 embeds the prompt into a 384-dimension vector. FAISS searches for the nearest cached vector using cosine similarity. Hits at ≥0.85 similarity score return the cached response without touching any upstream API.

New responses are written to both layers simultaneously. L2 vectors persist across restarts via Redis hydration on boot.

## Quick start
Set up your environment and point `REDIS_URL` to an active Redis instance (like Upstash Cloud or a local Docker container)
```bash
cp .env.example .env          # fill in API keys
docker-compose up -d          # starts gateway, Prometheus, Grafana
```

Hit the proxy:
```bash
curl -X POST http://localhost:8000/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"model": "auto", "messages": [{"role": "user", "content": "hello"}]}'
```

Endpoints:
- `POST /v1/chat` — main proxy endpoint
- `GET /health` — container health + FAISS vector count
- `GET /stats` — all-time SQLite aggregates (hit rate, token usage, model routing)
- `GET /metrics` — Prometheus scrape endpoint

Grafana dashboard: `http://localhost:3000`

## Benchmarks

Run against a warm cache (semantic duplicates pre-seeded). All 100 requests succeed at each tier with zero upstream model calls after the warmup phase.

```bash
python scripts/benchmark.py
```

| Concurrent users | p50   | p95    | p99    | Cache hit ratio |
| ---------------- | ----- | ------ | ------ | --------------- |
| 10               | 110ms | 157ms  | 407ms  | ~100%           |
| 50               | 328ms | 1125ms | 1547ms | ~100%           |
| 100              | 359ms | 672ms  | 734ms  | ~100%           |

> p99 at concurrency 100 outperforms concurrency 50 because the FAISS embedding thread (capped at 1 to prevent OOM under Docker) serializes the initial concurrent wave more evenly than the 50-user burst pattern. Overall production hit rate across mixed traffic: **91.5%** (from `/stats` across 171 requests).

## Observability

Grafana panels:

| Panel                    | Query                                                                                                    |
| ------------------------ | -------------------------------------------------------------------------------------------------------- |
| Requests by routing      | `sum by (routing) (llmgateway_requests_total)`                                                           |
| p99 latency (ms)         | `histogram_quantile(0.99, sum(rate(llmgateway_request_latency_ms_bucket[5m])) by (le))`                  |
| Cache hit rate %         | `(sum(llmgateway_requests_total{routing=~"L1_CACHE\|L2_CACHE"}) / sum(llmgateway_requests_total)) * 100` |
| FAISS vectors loaded     | `llmgateway_faiss_vectors_total`                                                                         |
| Token burn rate by model | `sum(increase(llmgateway_tokens_total[$__rate_interval])) by (model)`                                    |

Import `docs/grafana_dashboard.json` to restore the full dashboard instantly.

## Environment variables

```bash
# .env.example
GROQ_API_KEY=your_key_here
GEMINI_API_KEY=your_key_here
REDIS_URL=redis://localhost:6379      # or Upstash cloud URL
RATE_LIMIT_CAPACITY=5000
RATE_LIMIT_REFILL_RATE=1000
```

## Core Learnings
This infrastructure was built to solve the specific bottlenecks of AI development: expensive API calls and unpredictable tail latencies. By constraining the C++ embedding threads and isolating the SQLite WAL volumes, the event loop remains entirely unblocked under heavy concurrent loads.

---
**Author:** Anushka Rajput
*Built to handle production concurrency without choking.*