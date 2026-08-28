# cache/semantic_cache.py
import numpy as np
import faiss
import base64
from fastembed import TextEmbedding


class SemanticCache:
    def __init__(self, redis_client, threshold: float = 0.85):
        self.dimension = 384
        self.threshold = threshold
        self.redis = redis_client

        print("⏳ Loading BGE-small model via fastembed...")
        self.model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5", threads=1)

        self.index = faiss.IndexFlatIP(self.dimension)
        self.id_to_redis_key = {}
        self.current_id = 0

    def _embed(self, text: str) -> np.ndarray:
        vector = list(self.model.embed([text]))[0]
        vector_2d = vector.reshape(1, -1).astype("float32")
        faiss.normalize_L2(vector_2d)
        return vector_2d

    async def hydrate_from_redis(self):
        """Runs once on startup — rebuilds FAISS index from Redis."""
        print("🔄 Hydrating FAISS from Redis...")
        keys = await self.redis.keys("llm_cache:*")

        if not keys:
            print("✅ Redis empty. Starting fresh.")
            return

        loaded = 0
        for key in keys:
            vector_b64 = await self.redis.hget(key, "vector")
            if vector_b64:
                vector_bytes = base64.b64decode(vector_b64)
                vector_2d = np.frombuffer(
                    vector_bytes, dtype="float32"
                ).reshape(1, -1)
                self.index.add(vector_2d)
                self.id_to_redis_key[self.current_id] = key
                self.current_id += 1
                loaded += 1

        print(f"✅ Hydration complete. {loaded} vectors loaded into FAISS.")

    async def search(self, prompt: str) -> dict | None:
        """Returns cached response if semantically similar prompt exists."""
        if self.index.ntotal == 0:
            return None

        vector_2d = self._embed(prompt)
        scores, ids = self.index.search(vector_2d, k=1)

        best_score = float(scores[0][0])
        best_id = int(ids[0][0])

        if best_score < self.threshold:
            print(f"🔍 Semantic miss (score: {best_score:.3f} < {self.threshold})")
            return None

        redis_key = self.id_to_redis_key[best_id]
        cached_response = await self.redis.hget(redis_key, "response")

        if not cached_response:
            return None

        print(f"⚡ Semantic cache HIT (score: {best_score:.3f})")
        import json
        return json.loads(cached_response)

    async def add(self, prompt: str, redis_key: str, response_json: str, ttl: int = 86400):
        """Embeds prompt, adds to FAISS, backs vector + response to Redis with dynamic TTL."""
        vector_2d = self._embed(prompt)

        # add to in-memory FAISS
        self.index.add(vector_2d)
        self.id_to_redis_key[self.current_id] = redis_key
        self.current_id += 1

        # persist both vector and response to Redis as a Hash
        vector_b64 = base64.b64encode(vector_2d.tobytes()).decode("utf-8")
        await self.redis.hset(redis_key, mapping={
            "vector": vector_b64,
            "response": response_json,
        })

        # use dynamic TTL
        await self.redis.expire(redis_key, ttl)