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
│  Token Bucket Rate Limiter              │
│         │                               │
│  Redis Semantic Cache ──── cache hit ──►│── Response
│         │ miss                          │
│  Cost-Aware Traffic Router              │
│         │                               │
│  Async Connection Pool                  │
│         │                               │
│  Telemetry Event Pipeline               │
└─────────────────────────────────────────┘
      │
      ▼
Upstream Endpoints (GPT-4o / Claude / Gemini)
      │
      ▼
Prometheus /metrics ──► Grafana Dashboard
```

## What makes this different from Nginx

| Feature | Nginx | llmgateway |
|---|---|---|
| Routes by | URL / headers | Payload semantics + cost |
| Cache key | URL | Embedding vector (semantic similarity) |
| Routing logic | Static config | Outcome-adaptive |
| Observability | Access logs | p95/p99 latency, cost-per-request, cache hit ratio |

## Stack

- **Gateway:** FastAPI + asyncio + httpx
- **Rate limiting:** Custom token bucket (no library)
- **Cache:** Redis — hash cache → semantic vector cache
- **Telemetry:** Prometheus + Grafana
- **Load testing:** Locust

## Quick start

```bash
cp .env.example .env          # fill in API keys
docker-compose up -d          # starts Redis, Postgres, Prometheus, Grafana
pip install -r requirements.txt
uvicorn main:app --reload
```

Hit the proxy:
```bash
curl -X POST http://localhost:8000/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"model": "auto", "messages": [{"role": "user", "content": "hello"}]}'
```

Grafana dashboard: `http://localhost:3000`

## Benchmarks

| Concurrent users | p50 | p95 | p99 | Cache hit ratio |
|---|---|---|---|---|
| 100 | — | — | — | — |
| 500 | — | — | — | — |
| 1000 | — | — | — | — |

*Fill in after running `python scripts/benchmark.py`*

## Roadmap

- [x] Proxy skeleton
- [ ] Token bucket rate limiter
- [ ] Redis hash cache
- [ ] Cost-aware traffic router
- [ ] Semantic similarity cache
- [ ] Prometheus + Grafana
- [ ] Adaptive routing feedback loop
