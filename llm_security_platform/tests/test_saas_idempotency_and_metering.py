import shutil
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from llm_security_platform.app import db, production_store
from llm_security_platform.app.api import app
from llm_security_platform.app.production_store import init_production_db
from llm_security_platform.app.metrics import GLOBAL_METRICS, generate_prometheus_exposition


class MockRedisPipeline:
    def __init__(self, parent):
        self.parent = parent
        self.commands = []

    def zremrangebyscore(self, key, min_val, max_val):
        self.commands.append("zrem")
        return self

    def zcard(self, key):
        self.commands.append("zcard")
        return self

    def zadd(self, key, mapping):
        self.commands.append("zadd")
        return self

    def expire(self, key, ttl):
        self.commands.append("expire")
        return self

    def execute(self):
        results = []
        card_val = self.parent.count
        for cmd in self.commands:
            if cmd == "zrem":
                results.append(0)
            elif cmd == "zcard":
                results.append(card_val)
            elif cmd == "zadd":
                self.parent.count += 1
                results.append(1)
            elif cmd == "expire":
                results.append(1)
        return results


class MockRedisClient:
    def __init__(self):
        self.count = 0
        self.kv = {}

    def pipeline(self):
        return MockRedisPipeline(self)

    def ping(self):
        return True

    def get(self, key):
        val = self.kv.get(key)
        if val is not None:
            if isinstance(val, str):
                return val.encode()
            return val
        return None

    def set(self, key, value, ex=None, nx=False):
        if nx and key in self.kv:
            return False
        self.kv[key] = value
        return True

    def delete(self, key):
        if key in self.kv:
            del self.kv[key]
            return 1
        return 0


class SaaSIdempotencyAndMeteringTests(unittest.TestCase):
    def setUp(self):
        self.patcher_api_redis = patch("llm_security_platform.app.api.get_redis")
        self.patcher_mw_redis = patch("llm_security_platform.app.middleware.get_redis")
        self.mock_api_redis = self.patcher_api_redis.start()
        self.mock_mw_redis = self.patcher_mw_redis.start()
        
        self.mock_redis = MockRedisClient()
        self.mock_api_redis.return_value = self.mock_redis
        self.mock_mw_redis.return_value = self.mock_redis

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

        # Register a test tenant
        payload = {
            "tenant_id": "tenant_metrics_test",
            "actor": "metrics-admin",
            "keys": {},
            "qps_limit": 10
        }
        res = self.client.post("/tenants/signup", json=payload, headers={"X-API-Key": "dev-security-key"})
        self.assertEqual(res.status_code, 200)
        self.token = res.json()["data"]["token"]
        self.headers = {"X-API-Key": self.token}

        # Clear global metrics state
        with GLOBAL_METRICS.lock:
            GLOBAL_METRICS.tenant_token_usage.clear()

    def tearDown(self):
        self.patcher_api_redis.stop()
        self.patcher_mw_redis.stop()
        self.context.__exit__(None, None, None)
        if production_store._engine is not None:
            production_store._engine.dispose()
        db.DATABASE_PATH = self.original_db_path
        production_store.DATABASE_URL = self.original_url
        production_store._engine = None
        production_store._engine_url = None
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_run_idempotency_and_lock_release(self):
        # 1. First run submission -> 202 Accepted
        with patch("llm_security_platform.app.api.dispatch_run", return_value="task-idem-1"):
            res1 = self.client.post(
                "/async-runs",
                headers=self.headers,
                json={"name": "Run Idempotency 1", "provider": "mock", "defense_policy": "none"},
            )
        self.assertEqual(res1.status_code, 202)
        run_id1 = res1.json()["data"]["run_id"]

        # 2. Duplicate submission with exact same parameters -> 409 Conflict
        with patch("llm_security_platform.app.api.dispatch_run", return_value="task-idem-2"):
            res2 = self.client.post(
                "/async-runs",
                headers=self.headers,
                json={"name": "Run Idempotency 1", "provider": "mock", "defense_policy": "none"},
            )
        self.assertEqual(res2.status_code, 409)
        self.assertEqual(res2.json()["detail"]["run_id"], run_id1)

        # 3. Submission with different parameters -> 202 Accepted
        with patch("llm_security_platform.app.api.dispatch_run", return_value="task-idem-3"):
            res3 = self.client.post(
                "/async-runs",
                headers=self.headers,
                json={"name": "Run Idempotency 1", "provider": "mock", "defense_policy": "input_defense"},
            )
        self.assertEqual(res3.status_code, 202)

        # 4. Trigger Celery task synchronously to complete task 1 and release lock
        from llm_security_platform.app.tasks import execute_evaluation_run
        from llm_security_platform.app.providers import MockProvider
        with patch("llm_security_platform.app.tasks.build_provider", return_value=MockProvider()):
            execute_evaluation_run.run(run_id1, tenant_id="tenant_metrics_test")

        # 5. Re-submitting the original request should now succeed since lock is deleted
        with patch("llm_security_platform.app.api.dispatch_run", return_value="task-idem-4"):
            res4 = self.client.post(
                "/async-runs",
                headers=self.headers,
                json={"name": "Run Idempotency 1", "provider": "mock", "defense_policy": "none"},
            )
        self.assertEqual(res4.status_code, 202)

    def test_tenant_token_metering_metrics(self):
        # 1. Create a run under our tenant
        with patch("llm_security_platform.app.api.dispatch_run", return_value="task-meter"):
            res_create = self.client.post(
                "/async-runs",
                headers=self.headers,
                json={"name": "Run Metering Test", "provider": "mock"},
            )
        self.assertEqual(res_create.status_code, 202)
        run_id = res_create.json()["data"]["run_id"]

        # 2. Configure mock provider to yield exact token usage counts
        from llm_security_platform.app.providers import MockProvider, ModelCallResult
        mock_provider = MockProvider()
        # Mock generate to return 120 prompt tokens, 80 completion tokens
        mock_provider.generate = lambda sys, user: ModelCallResult(
            response_text="Mock evaluation success",
            token_usage={"prompt_tokens": 120, "completion_tokens": 80, "total_tokens": 200},
            estimated_cost=0.0004
        )

        from llm_security_platform.app.tasks import execute_evaluation_run
        with patch("llm_security_platform.app.tasks.build_provider", return_value=mock_provider):
            execute_evaluation_run.run(run_id, tenant_id="tenant_metrics_test")

        # 3. Retrieve exposed Prometheus metrics
        metrics_output = generate_prometheus_exposition()
        
        # 4. Assert tenant usage metrics exist
        self.assertIn('tenant_token_usage_total{tenant_id="tenant_metrics_test",provider="mock",model="mock-vulnerable-model",token_type="prompt"}', metrics_output)
        self.assertIn('tenant_token_usage_total{tenant_id="tenant_metrics_test",provider="mock",model="mock-vulnerable-model",token_type="completion"}', metrics_output)


if __name__ == "__main__":
    unittest.main()
