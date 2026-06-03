# main.py — llmgateway entry point
import os
from fastapi import FastAPI, HTTPException
from dotenv import load_dotenv
import litellm

load_dotenv()

app = FastAPI(title="llmgateway", version="0.1.0")

DEFAULT_MODEL = "groq/llama3-8b-8192" 

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/v1/chat")
async def proxy(body: dict):
    target_model = body.pop("model", DEFAULT_MODEL)
    
    # FIX: Use .pop() instead of .get() so it gets removed from the body dict!
    messages = body.pop("messages", [])
    
    if not messages:
        raise HTTPException(status_code=400, detail="The 'messages' array cannot be empty.")
    
    try:
        response = await litellm.acompletion(
            model=target_model,
            messages=messages,
            **body  
        )
        return response
        
    except litellm.exceptions.APIConnectionError as e:
        raise HTTPException(status_code=502, detail="Bad Gateway: Upstream provider is offline.")
        
    except litellm.exceptions.RateLimitError as e:
        raise HTTPException(status_code=429, detail=f"Rate Limit Exceeded: {str(e)}")
        
    except litellm.exceptions.APIError as e:
        status = getattr(e, "status_code", 500)
        raise HTTPException(status_code=status, detail=f"Upstream API Error: {str(e)}")
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal Gateway Error: {str(e)}")