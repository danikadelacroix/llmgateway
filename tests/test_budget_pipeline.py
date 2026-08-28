import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException
from unittest.mock import patch, AsyncMock

from main import app
from dependencies.rate_limiter import token_bucket_limit

@pytest.fixture
def client():
    # We mock the redis connect in lifespan so it doesn't try to connect to a real redis during tests
    with patch("redis.asyncio.from_url", return_value=AsyncMock()) as mock_redis, \
         patch("cache.semantic_cache.SemanticCache.hydrate_from_redis", new_callable=AsyncMock), \
         patch("main.init_events_db", new_callable=AsyncMock):
        with TestClient(app) as test_client:
            yield test_client

@pytest.fixture
def mock_cache_and_provider():
    with patch("cache.semantic_cache.SemanticCache.search", new_callable=AsyncMock) as mock_search, \
         patch("cache.semantic_cache.SemanticCache.add", new_callable=AsyncMock) as mock_add, \
         patch("litellm.acompletion", new_callable=AsyncMock) as mock_litellm:
        yield mock_search, mock_add, mock_litellm

from fastapi import Request

def test_over_budget_returns_402_and_does_not_call_downstream(client, mock_cache_and_provider):
    mock_search, mock_add, mock_litellm = mock_cache_and_provider

    async def mock_rate_limit(request: Request):
        pass # allow

    app.dependency_overrides[token_bucket_limit] = mock_rate_limit

    try:
        # A very large prompt to trigger 402 based on the default test configuration
        response = client.post("/v1/chat", json={
            "model": "auto",
            "messages": [{"role": "user", "content": "x" * 100000}]
        })

        assert response.status_code == 402, f"Expected 402 but got {response.status_code}: {response.text}"
        assert response.json()["detail"]["error"] == "request_exceeds_budget"
        
        # Assert caches and litellm were never called
        mock_search.assert_not_called()
        mock_add.assert_not_called()
        mock_litellm.assert_not_called()
    finally:
        app.dependency_overrides.clear()

def test_rate_limit_429_returned_before_402_budget(client, mock_cache_and_provider):
    mock_search, mock_add, mock_litellm = mock_cache_and_provider

    # We patch token_bucket_limit to always raise 429
    async def mock_rate_limit(request: Request):
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again in 1.0s.")

    app.dependency_overrides[token_bucket_limit] = mock_rate_limit

    try:
        # Very large prompt, but should fail with 429 first
        response = client.post("/v1/chat", json={
            "model": "auto",
            "messages": [{"role": "user", "content": "x" * 100000}]
        })

        assert response.status_code == 429, f"Expected 429 but got {response.status_code}: {response.text}"
        assert "Rate limit exceeded" in response.json()["detail"]

        # Caches and provider not called
        mock_search.assert_not_called()
        mock_add.assert_not_called()
        mock_litellm.assert_not_called()
    finally:
        app.dependency_overrides.clear()
