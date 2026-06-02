# main.py — llmgateway entry point
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="llmgateway", version="0.1.0")

UPSTREAM_URL = "https://api.anthropic.com/v1/messages"


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/v1/chat")
async def proxy(request: Request):
    body = await request.json()
    headers = {
        "x-api-key": "YOUR_KEY_HERE",
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    async with httpx.AsyncClient() as client:
        upstream = await client.post(
            UPSTREAM_URL, json=body, headers=headers, timeout=30.0
        )
    return upstream.json()
