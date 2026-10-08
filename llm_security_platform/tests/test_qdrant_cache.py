import os
import unittest
from unittest.mock import patch
from llm_security_platform.app.providers import ModelCallResult
from llm_security_platform.app.semantic_cache import SemanticCache

class QdrantCacheTests(unittest.TestCase):
    def setUp(self):
        # Configure env variables to activate Qdrant simulator
        self.patcher = patch.dict(os.environ, {"LLM_SECURITY_QDRANT_URL": "http://localhost:6333"})
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    def test_qdrant_cache_store_and_lookup_hit(self):
        cache = SemanticCache(
            tenant_id="tenant_a",
            provider="mock",
            model="model_a",
            defense_policy="input_defense",
            similarity_threshold=0.95
        )
        
        # Verify it instantiated the simulator
        self.assertIsNotNone(cache.qdrant)
        
        # Store an entry
        res = ModelCallResult(
            response_text="Sanitized cache test response",
            token_usage={"total_tokens": 15},
            estimated_cost=0.0001
        )
        cache.store("system configuration", "test query prompt", res)
        
        # Test exact prompt match (cosine similarity = 1.0)
        lookup_res = cache.lookup("system configuration", "test query prompt")
        self.assertIsNotNone(lookup_res)
        self.assertEqual(lookup_res.response_text, "Sanitized cache test response")
        self.assertEqual(lookup_res.token_usage["total_tokens"], 15)

    def test_qdrant_cache_isolation_between_policies(self):
        cache_policy_a = SemanticCache(
            tenant_id="tenant_a",
            provider="mock",
            model="model_a",
            defense_policy="policy_a",
            similarity_threshold=0.95
        )
        
        cache_policy_b = SemanticCache(
            tenant_id="tenant_a",
            provider="mock",
            model="model_a",
            defense_policy="policy_b",
            similarity_threshold=0.95
        )
        
        res = ModelCallResult("policy_a output")
        cache_policy_a.store("sys", "query", res)
        
        # Lookup on policy_a should succeed
        self.assertIsNotNone(cache_policy_a.lookup("sys", "query"))
        
        # Lookup on policy_b should miss due to metadata filter isolation
        self.assertIsNone(cache_policy_b.lookup("sys", "query"))
