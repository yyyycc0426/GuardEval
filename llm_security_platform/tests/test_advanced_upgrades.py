import logging
import shutil
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import numpy as np
from fastapi.testclient import TestClient

from llm_security_platform.app import db, production_store
from llm_security_platform.app.api import app
from llm_security_platform.app.production_store import init_production_db
from llm_security_platform.app.providers import build_provider, ModelCallResult, ModelProvider, ModelProviderError


class FailingRawProvider(ModelProvider):
    name = "failing_test_provider"
    model = "fail-model"

    def __init__(self):
        self.call_count = 0

    def generate(self, system_prompt: str, user_prompt: str) -> ModelCallResult:
        self.call_count += 1
        raise ModelProviderError("API connection timeout")


class TestAdvancedUpgrades(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path("llm_security_platform/.test_artifacts") / str(uuid4())
        self.temp_dir.mkdir(parents=True)
        self.original_db_path = db.DATABASE_PATH
        self.original_url = production_store.DATABASE_URL
        db.DATABASE_PATH = self.temp_dir / "legacy.db"
        production_store.DATABASE_URL = f"sqlite:///{(self.temp_dir / 'production.db').resolve().as_posix()}"
        production_store._engine = None
        production_store._engine_url = None
        init_production_db()

        self.context = TestClient(app)
        self.client = self.context.__enter__()

    def tearDown(self):
        self.context.__exit__(None, None, None)
        if production_store._engine is not None:
            production_store._engine.dispose()
        db.DATABASE_PATH = self.original_db_path
        production_store.DATABASE_URL = self.original_url
        production_store._engine = None
        production_store._engine_url = None
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_trace_id_propagation_and_middleware(self):
        custom_trace = "custom-trace-id-1234"
        res = self.client.get("/health", headers={"X-Trace-ID": custom_trace})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers.get("X-Trace-ID"), custom_trace)

        # Confirm default generation of Trace ID if header is absent
        res_default = self.client.get("/health")
        self.assertEqual(res_default.status_code, 200)
        self.assertIsNotNone(res_default.headers.get("X-Trace-ID"))

    def test_circuit_breaker_transitions_and_fallback(self):
        # 1. Instantiate the provider and verify it wraps in CircuitBreakerProviderWrapper
        raw_prov = FailingRawProvider()
        
        # We manually register/patch it inside the global _breakers
        from llm_security_platform.app.providers import CircuitBreakerProviderWrapper
        wrapped = CircuitBreakerProviderWrapper(raw_prov)
        
        # Reset breaker state to CLOSED for testing
        wrapped.breaker.state = "CLOSED"
        wrapped.breaker.failure_count = 0

        # 2. Trigger failures to breach threshold (5 failures)
        for i in range(5):
            self.assertTrue(wrapped.breaker.allow_request())
            with self.assertRaises(ModelProviderError):
                wrapped.generate("sys", "user")

        # Verify state transitioned to OPEN
        self.assertEqual(wrapped.breaker.state, "OPEN")
        self.assertEqual(raw_prov.call_count, 5)

        # 3. Subsequent request should trip breaker immediately and return fallback model result
        res_fallback = wrapped.generate("sys", "user")
        self.assertEqual(res_fallback.provider_metadata.get("circuit_breaker_fallback"), True)
        self.assertIn("Circuit Breaker Triggered", res_fallback.response_text)
        # Verify it did NOT call the raw provider (call_count remains 5)
        self.assertEqual(raw_prov.call_count, 5)

    @patch("llm_security_platform.app.semantic_cache.get_redis")
    @patch("llm_security_platform.app.semantic_cache.get_embedder")
    def test_semantic_cache_matching_logic(self, mock_get_embedder, mock_get_redis):
        # Mock Embedder returning unit normalized arrays
        mock_embedder = MagicMock()
        mock_get_embedder.return_value = mock_embedder

        # Mock Redis storing data in a local dict
        class LocalMockRedis:
            def __init__(self):
                self.db = {}
                self.keys_set = set()

            def smembers(self, name):
                return {k.encode() for k in self.keys_set}

            def pipeline(self):
                return self

            def get(self, key):
                return self.db.get(key)

            def set(self, key, val):
                self.db[key] = val.encode() if isinstance(val, str) else val
                return self

            def sadd(self, key, val):
                self.keys_set.add(val)
                return self

            def expire(self, key, ttl):
                return self

            def execute(self):
                # Returns results for pipelined get queries in the test order
                return [self.db.get(k) for k in self.keys_set]

            def ping(self):
                return True

        mock_redis = LocalMockRedis()
        mock_get_redis.return_value = mock_redis

        # Set up prompts & embeddings:
        # Query: [1.0, 0.0, 0.0]
        # Match (Similarity 0.98): [0.98, 0.19899, 0.0] -> dot product = 0.98
        # Miss (Similarity 0.50): [0.5, 0.866, 0.0] -> dot product = 0.50
        
        # Instantiate Semantic Cache
        from llm_security_platform.app.semantic_cache import SemanticCache
        cache = SemanticCache(tenant_id="test_tenant", similarity_threshold=0.96)

        # Save an entry to cache
        mock_embedder.encode.return_value = [np.array([1.0, 0.0, 0.0])]
        dummy_result = ModelCallResult(response_text="Cached output text", token_usage={}, estimated_cost=0.0)
        cache.store("system_prompt", "target prompt", dummy_result)

        # Lookup with similar query (returns similarity 0.98 > 0.96) -> Cache HIT
        mock_embedder.encode.return_value = [np.array([0.98, 0.19899, 0.0])]
        hit_res = cache.lookup("system_prompt", "target prompt similar")
        self.assertIsNotNone(hit_res)
        self.assertEqual(hit_res.response_text, "Cached output text")

        # Lookup with dissimilar query (returns similarity 0.50 < 0.96) -> Cache MISS
        mock_embedder.encode.return_value = [np.array([0.5, 0.866, 0.0])]
        miss_res = cache.lookup("system_prompt", "completely different prompt")
        self.assertIsNone(miss_res)


if __name__ == "__main__":
    unittest.main()
