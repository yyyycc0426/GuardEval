import hashlib
import json
import logging
import os
import uuid
import numpy as np

from llm_security_platform.app.config import REDIS_URL
from llm_security_platform.app.providers import ModelCallResult
from llm_security_platform.app.semantic_classifier import SentenceTransformerEmbedder

logger = logging.getLogger("llm_security_platform.semantic_cache")

# Lazy-loaded singletons
_embedder = None
_redis_client = None

# Qdrant client imports with fallback mock classes
try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue
    HAS_QDRANT = True
except ImportError:
    HAS_QDRANT = False
    class Distance:
        COSINE = "Cosine"
    class VectorParams:
        def __init__(self, size, distance):
            self.size = size
            self.distance = distance
    class PointStruct:
        def __init__(self, id, vector, payload):
            self.id = id
            self.vector = vector
            self.payload = payload
    class MatchValue:
        def __init__(self, value):
            self.value = value
    class FieldCondition:
        def __init__(self, key, match):
            self.key = key
            self.match = match
    class Filter:
        def __init__(self, must):
            self.must = must

class MockQdrantClient:
    """In-memory Qdrant simulation to ensure tests run without live cluster dependencies."""
    def __init__(self, url=None, **kwargs):
        self.url = url
        self.collections = {}
        
    def collection_exists(self, collection_name):
        return collection_name in self.collections
        
    def create_collection(self, collection_name, vectors_config):
        self.collections[collection_name] = []
        return True
        
    def upsert(self, collection_name, points):
        if collection_name not in self.collections:
            self.collections[collection_name] = []
        ids_to_add = {p.id for p in points}
        self.collections[collection_name] = [x for x in self.collections[collection_name] if x.id not in ids_to_add]
        self.collections[collection_name].extend(points)
        return True
        
    def search(self, collection_name, query_vector, query_filter=None, limit=1, **kwargs):
        if collection_name not in self.collections:
            return []
        candidates = self.collections[collection_name]
        results = []
        
        for c in candidates:
            match = True
            if query_filter and hasattr(query_filter, 'must') and query_filter.must:
                for cond in query_filter.must:
                    key = cond.key
                    val = cond.match.value
                    if c.payload.get(key) != val:
                        match = False
                        break
            if not match:
                continue
                
            similarity = float(np.dot(query_vector, c.vector))
            results.append((c, similarity))
            
        results.sort(key=lambda x: x[1], reverse=True)
        
        class ScoredPoint:
            def __init__(self, id, payload, score):
                self.id = id
                self.payload = payload
                self.score = score
        return [ScoredPoint(c.id, c.payload, score) for c, score in results[:limit]]

def get_embedder():
    global _embedder
    if _embedder is None:
        try:
            _embedder = SentenceTransformerEmbedder()
        except Exception as exc:
            logger.warning(f"Failed to load SentenceTransformer for semantic cache: {exc}")
            _embedder = False
    return _embedder if _embedder is not False else None


def get_redis():
    global _redis_client
    if _redis_client is None:
        import redis
        try:
            _redis_client = redis.from_url(REDIS_URL, socket_timeout=1.0, socket_connect_timeout=1.0)
            _redis_client.ping()
        except Exception as exc:
            logger.warning(f"Failed to connect to Redis at {REDIS_URL} for semantic cache: {exc}")
            _redis_client = False
    return _redis_client if _redis_client is not False else None


class SemanticCache:
    def __init__(
        self,
        tenant_id: str,
        provider: str = "default",
        model: str = "default",
        defense_policy: str = "default",
        similarity_threshold: float = 0.96
    ):
        self.tenant_id = tenant_id
        self.provider = provider
        self.model = model
        self.defense_policy = defense_policy
        self.similarity_threshold = similarity_threshold
        
        self.qdrant_url = os.environ.get("LLM_SECURITY_QDRANT_URL")
        self.qdrant = None
        
        if self.qdrant_url:
            if HAS_QDRANT:
                self.qdrant = QdrantClient(url=self.qdrant_url)
            else:
                logger.warning("LLM_SECURITY_QDRANT_URL is set but qdrant_client is missing. Falling back to MockQdrantClient.")
                self.qdrant = MockQdrantClient(url=self.qdrant_url)
            
            # Setup collection for semantic caching
            self.collection_name = "llm_security_semantic_cache"
            try:
                if not self.qdrant.collection_exists(self.collection_name):
                    self.qdrant.create_collection(
                        collection_name=self.collection_name,
                        vectors_config=VectorParams(size=384, distance=Distance.COSINE)
                    )
            except Exception as exc:
                logger.error(f"Failed to initialize Qdrant collection: {exc}")
                self.qdrant = None

        self.redis = get_redis()
        self.embedder = get_embedder()

    def lookup(self, system_prompt: str, user_prompt: str) -> ModelCallResult | None:
        if not self.embedder:
            return None

        try:
            full_prompt = f"system: {system_prompt}\nuser: {user_prompt}"
            query_emb = self.embedder.encode([full_prompt])[0]  # normalized numpy array

            # If Qdrant integration is configured, query Qdrant with metadata filters
            if self.qdrant:
                query_filter = Filter(
                    must=[
                        FieldCondition(key="tenant_id", match=MatchValue(value=self.tenant_id)),
                        FieldCondition(key="provider", match=MatchValue(value=self.provider)),
                        FieldCondition(key="model", match=MatchValue(value=self.model)),
                        FieldCondition(key="defense_policy", match=MatchValue(value=self.defense_policy))
                    ]
                )
                search_results = self.qdrant.search(
                    collection_name=self.collection_name,
                    query_vector=query_emb.tolist(),
                    query_filter=query_filter,
                    limit=1
                )
                if search_results:
                    hit = search_results[0]
                    if hit.score >= self.similarity_threshold:
                        logger.info(f"Qdrant Semantic Cache HIT (similarity: {hit.score:.4f} >= {self.similarity_threshold})")
                        res = hit.payload["result"]
                        return ModelCallResult(
                            response_text=res["response_text"],
                            token_usage=res.get("token_usage", {}),
                            estimated_cost=res.get("estimated_cost", 0.0),
                            provider_metadata=res.get("provider_metadata", {}),
                        )
                return None

            # Fallback Redis-based lookups
            if not self.redis:
                return None

            index_key = f"semcache_keys:{self.tenant_id}:{self.provider}:{self.model}:{self.defense_policy}"
            keys = [k.decode() for k in self.redis.smembers(index_key) if k]
            if not keys:
                return None

            pipe = self.redis.pipeline()
            for key in keys:
                pipe.get(key)
            raw_entries = pipe.execute()

            best_similarity = -1.0
            best_entry = None

            for raw_entry in raw_entries:
                if not raw_entry:
                    continue
                entry = json.loads(raw_entry.decode())
                emb = np.array(entry["embedding"])
                
                similarity = float(np.dot(query_emb, emb))
                if similarity > best_similarity:
                    best_similarity = similarity
                    best_entry = entry

            if best_similarity >= self.similarity_threshold and best_entry:
                logger.info(f"Redis Semantic Cache HIT (similarity: {best_similarity:.4f} >= {self.similarity_threshold})")
                res = best_entry["result"]
                return ModelCallResult(
                    response_text=res["response_text"],
                    token_usage=res.get("token_usage", {}),
                    estimated_cost=res.get("estimated_cost", 0.0),
                    provider_metadata=res.get("provider_metadata", {}),
                )
        except Exception as exc:
            logger.error(f"Semantic Cache lookup exception: {exc}")

        return None

    def store(self, system_prompt: str, user_prompt: str, result: ModelCallResult):
        if not self.embedder:
            return

        try:
            full_prompt = f"system: {system_prompt}\nuser: {user_prompt}"
            query_emb = self.embedder.encode([full_prompt])[0]

            # If Qdrant is configured, write the point to Qdrant
            if self.qdrant:
                point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{self.tenant_id}:{self.provider}:{self.model}:{self.defense_policy}:{full_prompt}"))
                payload = {
                    "tenant_id": self.tenant_id,
                    "provider": self.provider,
                    "model": self.model,
                    "defense_policy": self.defense_policy,
                    "prompt": full_prompt,
                    "result": {
                        "response_text": result.response_text,
                        "token_usage": result.token_usage,
                        "estimated_cost": result.estimated_cost,
                        "provider_metadata": result.provider_metadata,
                    }
                }
                self.qdrant.upsert(
                    collection_name=self.collection_name,
                    points=[PointStruct(id=point_id, vector=query_emb.tolist(), payload=payload)]
                )
                logger.info(f"Stored entry in Qdrant Vector Cache (ID: {point_id})")
                return

            # Fallback Redis-based storage
            if not self.redis:
                return

            prompt_hash = hashlib.md5(full_prompt.encode("utf-8")).hexdigest()
            cache_key = f"semcache_data:{self.tenant_id}:{self.provider}:{self.model}:{self.defense_policy}:{prompt_hash}"
            index_key = f"semcache_keys:{self.tenant_id}:{self.provider}:{self.model}:{self.defense_policy}"

            entry = {
                "prompt": full_prompt,
                "embedding": query_emb.tolist(),
                "result": {
                    "response_text": result.response_text,
                    "token_usage": result.token_usage,
                    "estimated_cost": result.estimated_cost,
                    "provider_metadata": result.provider_metadata,
                }
            }

            pipe = self.redis.pipeline()
            pipe.set(cache_key, json.dumps(entry))
            pipe.sadd(index_key, cache_key)
            pipe.expire(cache_key, 3600)  # TTL of 1 hour
            pipe.execute()
        except Exception as exc:
            logger.error(f"Semantic Cache store exception: {exc}")
