# telemetry/events.py — Async telemetry event pipeline
# TODO: every routing decision, cache hit/miss, latency → async write → Postgres
# Non-blocking: proxy must never wait on a telemetry write
