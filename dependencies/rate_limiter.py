# dependencies/rate_limiter.py
import time
from fastapi import Request, HTTPException

CAPACITY=5000
REFILL_RATE=1000

# Executes atomically on Redis — no race conditions under horizontal scaling
LUA_SCRIPT = """
local key         = KEYS[1]
local capacity    = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local now         = tonumber(ARGV[3])

local tokens      = capacity
local last_refill = now

-- Fetch current state
local bucket = redis.call('HMGET', key, 'tokens', 'last_refill')
if bucket[1] then
    tokens      = tonumber(bucket[1])
    last_refill = tonumber(bucket[2])
end

-- Calculate refill based on time passed
local time_passed = math.max(0, now - last_refill)
tokens = math.min(capacity, tokens + (time_passed * refill_rate))

-- Check bucket and deduct
if tokens >= 1 then
    tokens = tokens - 1
    redis.call('HMSET', key, 'tokens', tokens, 'last_refill', now)
    redis.call('EXPIRE', key, 60)
    return {1, tostring(tokens)}
else
    local wait_time = (1 - tokens) / refill_rate
    return {0, tostring(wait_time)}
end
"""

async def token_bucket_limit(request: Request):
    """Atomic Token Bucket using Redis Lua Scripting."""
    redis = request.app.state.redis
    client_ip = request.client.host
    key = f"rate_limit:{client_ip}"
    now = time.time()  # Universal epoch time for distributed containers

    # eval() args: script, num_keys, keys..., args...
    result = await redis.eval(LUA_SCRIPT, 1, key, CAPACITY, REFILL_RATE, now)

    allowed = result[0] == 1

    if not allowed:
        wait_time = float(result[1])
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Try again in {wait_time:.1f}s."
        )