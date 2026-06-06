# main.py — llmgateway entry point
import os
import json
import hashlib
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends
from dependencies.rate_limiter import token_bucket_limit
from dotenv import load_dotenv
import litellm
import redis.asyncio as aioredis

from config_manager import load_config  
from cache.semantic_cache import SemanticCache

load_dotenv()
config = load_config()

redis_client = None
semantic_cache = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_client, semantic_cache
    print("🚀 Booting LLM Gateway...")
    redis_client = aioredis.from_url(os.getenv("REDIS_URL"), decode_responses=True)
    semantic_cache = SemanticCache(redis_client)
    await semantic_cache.hydrate_from_redis()
    yield 
    print("🛑 Shutting down Gateway...")
    await redis_client.close()

app = FastAPI(title="llmgateway", version="0.1.0", lifespan=lifespan)

@app.get("/health")
async def health():
    return {
        "status": "ok", 
        "redis_connected": await redis_client.ping(),
        "faiss_vectors_loaded": semantic_cache.index.ntotal if semantic_cache else 0,
        "active_tiers": [name for name, _ in config.ordered_tiers()]
    }

@app.post("/v1/chat", dependencies=[Depends(token_bucket_limit)])
async def proxy(body: dict):
    messages = body.pop("messages", [])
    if not messages:
        raise HTTPException(status_code=400, detail="The 'messages' array cannot be empty.")

    # FIX 2: Strip the user model. The Gateway dictates routing now.
    body.pop("model", None) 

    # CACHE PRE-PROCESSING

    # FIX 3: Multi-turn structural separators for high-quality embeddings
    formatted_messages = [f"{m.get('role', 'USER').upper()}: {m.get('content', '')}" for m in messages]
    text_to_embed = "\n".join(formatted_messages)
    
    # Generate exact-match ID
    prompt_hash = hashlib.sha256(json.dumps(messages, sort_keys=True).encode('utf-8')).hexdigest()
    redis_key = f"llm_cache:{prompt_hash}"

    # L1 CACHE: EXACT MATCH (0ms, no math)
    try:
        # Check if the exact hash exists in Redis and grab the response field
        exact_data = await redis_client.hget(redis_key, "response")
        if exact_data:
            print("⚡ L1 EXACT CACHE HIT! (0ms)")
            return json.loads(exact_data)
    except Exception as e:
        print(f"⚠️ L1 cache error: {str(e)}")

    # L2 CACHE: SEMANTIC MATCH (1-5ms FAISS math)
    try:
        cached_response = await semantic_cache.search(text_to_embed)
        if cached_response:
            # semantic_cache already parses the JSON for us
            return cached_response
    except Exception as e:
        print(f"⚠️ L2 Semantic cache error: {str(e)}")

    # THE FALLBACK LOOP (Network Layer)

    last_exception = None
    final_response = None
    
    for tier_name, tier_info in config.ordered_tiers():
        try:
            print(f"🚀 Cache Miss. Routing to: {tier_name} ({tier_info.model})")
            final_response = await litellm.acompletion(
                model=tier_info.model,
                messages=messages,
                timeout=tier_info.timeout,
                **body  
            )
            break  
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

    # WRITE TO L1 & L2 CACHE
    try:
        response_json = json.dumps(final_response.model_dump())
        # This writes the vector to FAISS (L2) and the Hash/JSON to Redis (L1 & L2 backup)
        await semantic_cache.add(text_to_embed, redis_key, response_json)
        print("💾 Learned new prompt! Saved to L1 and L2 cache.")
    except Exception as e:
        print(f"⚠️ Failed to save to cache: {str(e)}")

    return final_response