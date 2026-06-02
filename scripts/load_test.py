# scripts/load_test.py — Locust load test
# Run: locust -f scripts/load_test.py --host=http://localhost:8000
# Tests: 100 / 500 / 1000 concurrent users
# Records: p95/p99 latency, cache hit ratio, error rate
# from locust import HttpUser, task, between
