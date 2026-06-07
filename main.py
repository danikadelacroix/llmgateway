# main.py — llmgateway entry point
import os
import json
import hashlib
import time  #for latency tracking
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends, Request, BackgroundTasks 
from dependencies.rate_limiter import token_bucket_limit
from dotenv import load_dotenv
import litellm
import redis.asyncio as aioredis
from telemetry.events import init_events_db, log_event

from config_manager import load_config  
from cache.semantic_cache import SemanticCache

load_dotenv()
config = load_config()

# redis_client = None
# semantic_cache = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 Booting LLM Gateway...")
    app.state.redis = aioredis.from_url(os.getenv("REDIS_URL"), decode_responses=True)
    app.state.semantic_cache = SemanticCache(app.state.redis)
    await app.state.semantic_cache.hydrate_from_redis()
    await init_events_db()
    yield
    print("🛑 Shutting down...")
    await app.state.redis.close()

app = FastAPI(title="llmgateway", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health(request: Request):
    return {
        "status": "ok",
        "redis_connected": await request.app.state.redis.ping(),
        "faiss_vectors_loaded": request.app.state.semantic_cache.index.ntotal,
        "active_tiers": [name for name, _ in config.ordered_tiers()]
    }

# 🚨 Inject BackgroundTasks and Request into the endpoint
@app.post("/v1/chat", dependencies=[Depends(token_bucket_limit)])
async def proxy(body: dict, request: Request, background_tasks: BackgroundTasks):
    start_time = time.time()
    client_ip = request.client.host
    
    messages = body.pop("messages", [])
    if not messages:
        raise HTTPException(status_code=400, detail="The 'messages' array cannot be empty.")

    body.pop("model", None) 

    # CACHE PRE-PROCESSING
    formatted_messages = [f"{m.get('role', 'USER').upper()}: {m.get('content', '')}" for m in messages]
    text_to_embed = "\n".join(formatted_messages)
    
    prompt_hash = hashlib.sha256(json.dumps(messages, sort_keys=True).encode('utf-8')).hexdigest()
    redis_key = f"llm_cache:{prompt_hash}"

    # ==========================================
    # L1 CACHE: EXACT MATCH
    # ==========================================
    try:
        exact_data = await request.app.state.redis.hget(redis_key, "response")
        if exact_data:
            print("⚡ L1 EXACT CACHE HIT! (0ms)")
            latency = (time.time() - start_time) * 1000
            
            background_tasks.add_task(log_event, client_ip, "cache", "L1", latency, 0, 200)
            return json.loads(exact_data)
    except Exception as e:
        print(f"⚠️ L1 cache error: {str(e)}")

    # ==========================================
    # L2 CACHE: SEMANTIC MATCH 
    # ==========================================
    try:
        cached_response = await request.app.state.semantic_cache.search(text_to_embed)
        if cached_response:
            latency = (time.time() - start_time) * 1000
            
            background_tasks.add_task(log_event, client_ip, "cache", "L2", latency, 0, 200)
            return cached_response
    except Exception as e:
        print(f"⚠️ L2 Semantic cache error: {str(e)}")

    # ==========================================
    # THE FALLBACK LOOP (Network Layer)
    # ==========================================
    last_exception = None
    final_response = None
    successful_model = "unknown"
    
    for tier_name, tier_info in config.ordered_tiers():
        try:
            print(f"🚀 Cache Miss. Routing to: {tier_name} ({tier_info.model})")
            final_response = await litellm.acompletion(
                model=tier_info.model,
                messages=messages,
                timeout=tier_info.timeout,
                **body  
            )
            successful_model = tier_info.model
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
        latency = (time.time() - start_time) * 1000
        background_tasks.add_task(log_event, client_ip, "failed", "MISS", latency, 0, 502, str(last_exception))
        raise HTTPException(status_code=502, detail=f"All models failed. Last error: {str(last_exception)}")

    # ==========================================
    # WRITE TO L1 & L2 CACHE
    # ==========================================
    try:
        response_json = json.dumps(final_response.model_dump())
        await request.app.state.semantic_cache.add(text_to_embed, redis_key, response_json)
        print("New prompt! Saved to L1 and L2 cache.")
    except Exception as e:
        print(f"⚠️ Failed to save to cache: {str(e)}")

    # ==========================================
    # LOG UPSTREAM SUCCESS
    # ==========================================
    # Safely extract tokens used from the LiteLLM response object
    tokens_used = 0
    if hasattr(final_response, "usage") and final_response.usage:
        tokens_used = getattr(final_response.usage, "total_tokens", 0)
        
    latency = (time.time() - start_time) * 1000
    background_tasks.add_task(log_event, client_ip, successful_model, "MISS", latency, tokens_used, 200)

    return final_response