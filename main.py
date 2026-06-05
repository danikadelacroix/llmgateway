# main.py — llmgateway entry point
import os
import json
import hashlib
from fastapi import FastAPI, HTTPException
from dotenv import load_dotenv
import litellm
import redis.asyncio as aioredis  # The async Redis driver

from config_manager import load_config  

load_dotenv()

app = FastAPI(title="llmgateway", version="0.1.0")
config = load_config()

# Initialize the persistent connection to your Upstash Cloud Redis
# decode_responses=True ensures Redis gives us clean Python strings, not raw bytes
redis_client = aioredis.from_url(os.getenv("REDIS_URL"), decode_responses=True)

@app.get("/health")
async def health():
    # Quick check to ensure Redis is alive
    redis_status = await redis_client.ping()
    return {
        "status": "ok", 
        "redis_connected": redis_status,
        "active_tiers": [name for name, _ in config.ordered_tiers()]
    }

@app.post("/v1/chat")
async def proxy(body: dict):
    messages = body.pop("messages", [])
    if not messages:
        raise HTTPException(status_code=400, detail="The 'messages' array cannot be empty.")

    user_requested_model = body.pop("model", None)

    # PHASE 1: THE CACHE INTERCEPTOR

    # 1. Convert the exact messages array into a standardized string
    prompt_string = json.dumps(messages, sort_keys=True)
    
    # 2. Crush it into a unique SHA-256 hash ID
    prompt_hash = hashlib.sha256(prompt_string.encode('utf-8')).hexdigest()
    cache_key = f"llm_cache:{prompt_hash}"

    # 3. Check Redis for this exact key
    try:
        cached_data = await redis_client.get(cache_key)
        if cached_data:
            print("⚡ CACHE HIT! Returning instant response (0ms network latency).")
            # Convert the saved JSON string back into a Python dictionary and return it
            return json.loads(cached_data)
    except Exception as e:
        print(f"⚠️ Redis read failed: {str(e)} — Bypassing cache.")

    # PHASE 2: THE FALLBACK LOOP (Only runs on a Cache Miss)

    last_exception = None
    final_response = None
    
    if user_requested_model:
        try:
            final_response = await litellm.acompletion(model=user_requested_model, messages=messages, **body)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    else:
        for tier_name, tier_info in config.ordered_tiers():
            try:
                print(f"🚀 Cache Miss. Routing to: {tier_name} ({tier_info.model})")
                final_response = await litellm.acompletion(
                    model=tier_info.model,
                    messages=messages,
                    timeout=tier_info.timeout,
                    **body  
                )
                break  # Success! Break the loop.
                
            except litellm.exceptions.APIError as e:
                status = getattr(e, "status_code", 500)
                last_exception = e
                if status in config.gateway.failover_on:
                    print(f"⚠️ {tier_name} failed with {status}. Falling back...")
                    continue 
                else:
                    raise HTTPException(status_code=status, detail=f"Upstream Error: {str(e)}")
            except Exception as e:
                print(f"⚠️ {tier_name} offline. Falling back...")
                last_exception = e
                continue

    if not final_response:
        raise HTTPException(status_code=502, detail=f"All models failed. Last error: {str(last_exception)}")

    # PHASE 3: SAVE TO CACHE FOR NEXT TIME
    
    try:
        # litellm returns a Pydantic object, we convert it to a dictionary, then to a JSON string
        response_dict = final_response.model_dump()
        
        # Save to Redis with an expiration of 24 hours (86400 seconds)
        # This prevents your cloud database from filling up with old data
        await redis_client.setex(cache_key, 86400, json.dumps(response_dict))
        print("💾 Saved new response to Redis cache.")
    except Exception as e:
        print(f"⚠️ Failed to save to Redis: {str(e)}")

    return final_response