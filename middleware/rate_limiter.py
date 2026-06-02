# middleware/rate_limiter.py — Token bucket rate limiter (custom, no library)
# TODO: implement Token Bucket algorithm
# Buckets refill at REFILL_RATE tokens/sec up to CAPACITY
# Each request consumes 1 token; reject with 429 if bucket empty

CAPACITY = 100       # max burst
REFILL_RATE = 10     # tokens per second
