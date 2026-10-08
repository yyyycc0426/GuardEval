import shutil
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from uuid import uuid4

# Dynamic mock injection for Google Cloud modules when they are not installed in the local environment
try:
    from google.cloud import tasks_v2
    from google.oauth2 import id_token
    from google.api_core import exceptions
    import google.auth
    from google.auth.transport import requests
except ModuleNotFoundError:
    from types import ModuleType
    
    if "google" in sys.modules:
        google = sys.modules["google"]
    else:
        google = ModuleType("google")
        google.__path__ = []
        sys.modules["google"] = google
        
    if hasattr(google, "cloud"):
        cloud = google.cloud
    elif "google.cloud" in sys.modules:
        cloud = sys.modules["google.cloud"]
        google.cloud = cloud
    else:
        cloud = ModuleType("google.cloud")
        cloud.__path__ = []
        sys.modules["google.cloud"] = cloud
        google.cloud = cloud
        
    if hasattr(google, "oauth2"):
        oauth2 = google.oauth2
    elif "google.oauth2" in sys.modules:
        oauth2 = sys.modules["google.oauth2"]
        google.oauth2 = oauth2
    else:
        oauth2 = ModuleType("google.oauth2")
        oauth2.__path__ = []
        sys.modules["google.oauth2"] = oauth2
        google.oauth2 = oauth2
        
    if hasattr(google, "api_core"):
        api_core = google.api_core
    elif "google.api_core" in sys.modules:
        api_core = sys.modules["google.api_core"]
        google.api_core = api_core
    else:
        api_core = ModuleType("google.api_core")
        api_core.__path__ = []
        sys.modules["google.api_core"] = api_core
        google.api_core = api_core

    if hasattr(google, "auth"):
        auth = google.auth
    elif "google.auth" in sys.modules:
        auth = sys.modules["google.auth"]
        google.auth = auth
    else:
        auth = ModuleType("google.auth")
        auth.__path__ = []
        sys.modules["google.auth"] = auth
        google.auth = auth

    google.cloud.tasks_v2 = ModuleType("google.cloud.tasks_v2")
    google.oauth2.id_token = ModuleType("google.oauth2.id_token")
    google.api_core.exceptions = ModuleType("google.api_core.exceptions")
    google.auth.transport = ModuleType("google.auth.transport")
    google.auth.transport.requests = ModuleType("google.auth.transport.requests")
    
    class MockAlreadyExistsException(Exception):
        pass
        
    class MockCloudTasksClient(MagicMock):
        pass
        
    class MockVerifyOAuth2Token(MagicMock):
        pass

    class MockRequest(MagicMock):
        pass
        
    google.cloud.tasks_v2.CloudTasksClient = MockCloudTasksClient
    google.api_core.exceptions.AlreadyExists = MockAlreadyExistsException
    google.oauth2.id_token.verify_oauth2_token = MockVerifyOAuth2Token
    google.auth.transport.requests.Request = MockRequest
    
    sys.modules["google.cloud.tasks_v2"] = google.cloud.tasks_v2
    sys.modules["google.oauth2.id_token"] = google.oauth2.id_token
    sys.modules["google.api_core.exceptions"] = google.api_core.exceptions
    sys.modules["google.auth.transport"] = google.auth.transport
    sys.modules["google.auth.transport.requests"] = google.auth.transport.requests
    
    from google.cloud import tasks_v2
    from google.oauth2 import id_token

from fastapi.testclient import TestClient

from llm_security_platform.app import db, production_store
from llm_security_platform.app.api import app
from llm_security_platform.app.production_store import get_tenant_config, init_production_db
from llm_security_platform.app.production_models import TenantConfig


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

    def pipeline(self):
        return MockRedisPipeline(self)

    def ping(self):
        return True


class SaaSUpgradesTests(unittest.TestCase):
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
        self.redis_patcher = patch("llm_security_platform.app.api.get_redis", return_value=None)
        self.redis_patcher.start()

    def tearDown(self):
        self.redis_patcher.stop()
        self.context.__exit__(None, None, None)
        if production_store._engine is not None:
            production_store._engine.dispose()
        db.DATABASE_PATH = self.original_db_path
        production_store.DATABASE_URL = self.original_url
        production_store._engine = None
        production_store._engine_url = None
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_tenant_signup_onboarding_and_validation(self):
        # 1. Sign up a new tenant successfully
        payload = {
            "tenant_id": "tenant_saas_test",
            "actor": "saas-admin",
            "keys": {"OPENAI_COMPATIBLE_API_KEY": "sk-proj-test-12345"},
            "qps_limit": 5
        }
        res = self.client.post("/tenants/signup", json=payload, headers={"X-API-Key": "dev-security-key"})
        self.assertEqual(res.status_code, 200)
        res_data = res.json()["data"]
        self.assertEqual(res_data["tenant_id"], "tenant_saas_test")
        self.assertEqual(res_data["qps_limit"], 5)
        self.assertIn("token", res_data)

        # 2. Assert signing up duplicate tenant ID returns 400
        res_dup = self.client.post("/tenants/signup", json=payload, headers={"X-API-Key": "dev-security-key"})
        self.assertEqual(res_dup.status_code, 400)
        self.assertIn("already registered", res_dup.json()["detail"])

        # 3. Assert invalid tenant ID (e.g. contains special symbols) returns 400
        bad_payload = dict(payload)
        bad_payload["tenant_id"] = "tenant-with-hyphen;--" # invalid schema char
        res_bad = self.client.post("/tenants/signup", json=bad_payload, headers={"X-API-Key": "dev-security-key"})
        self.assertEqual(res_bad.status_code, 400)
        self.assertIn("contain only alphanumeric characters", res_bad.json()["detail"])

    def test_byok_encryption_and_decryption(self):
        payload = {
            "tenant_id": "tenant_byok",
            "actor": "byok-user",
            "keys": {"OPENAI_COMPATIBLE_API_KEY": "secret-byok-key-value"},
            "qps_limit": 10
        }
        res = self.client.post("/tenants/signup", json=payload, headers={"X-API-Key": "dev-security-key"})
        self.assertEqual(res.status_code, 200)

        # Retrieve direct record from database default context to assert it is encrypted
        with production_store.session_scope() as session:
            config = session.get(TenantConfig, "tenant_byok")
            self.assertIsNotNone(config)
            # Verify the stored value is encrypted and not raw plain text
            self.assertNotEqual(config.encrypted_keys_json, "secret-byok-key-value")
            self.assertNotIn("secret-byok-key-value", config.encrypted_keys_json)

        # Retrieve through get_tenant_config to verify it is decrypted correctly
        decrypted_config = get_tenant_config("tenant_byok")
        self.assertEqual(decrypted_config["keys"]["OPENAI_COMPATIBLE_API_KEY"], "secret-byok-key-value")

    @patch("llm_security_platform.app.middleware.get_redis")
    def test_qps_rate_limiting_middleware(self, mock_get_redis):
        # Configure Mock Redis
        mock_redis = MockRedisClient()
        mock_get_redis.return_value = mock_redis

        # Sign up tenant with low QPS limit for easy testing
        payload = {
            "tenant_id": "tenant_limiter",
            "actor": "limiter-user",
            "keys": {},
            "qps_limit": 2 # Maximum 2 QPS
        }
        res_signup = self.client.post("/tenants/signup", json=payload, headers={"X-API-Key": "dev-security-key"})
        self.assertEqual(res_signup.status_code, 200)
        token = res_signup.json()["data"]["token"]
        headers = {"X-API-Key": token}

        # First request -> Allowed
        res1 = self.client.get("/cases", headers=headers)
        self.assertEqual(res1.status_code, 200)

        # Second request -> Allowed
        res2 = self.client.get("/cases", headers=headers)
        self.assertEqual(res2.status_code, 200)

        # Third request -> 429 Rate Limit Exceeded
        res3 = self.client.get("/cases", headers=headers)
        self.assertEqual(res3.status_code, 429)
        self.assertIn("Rate limit exceeded", res3.json()["message"])

    @patch("llm_security_platform.app.middleware.get_redis")
    def test_rate_limiting_redis_outage_fail_closed(self, mock_get_redis):
        # Simulates Redis connection down
        mock_get_redis.return_value = None

        import os
        os.environ["LLM_SECURITY_TEST_REDIS_DOWN"] = "true"
        try:
            payload = {
                "tenant_id": "tenant_redis_down",
                "actor": "redis-user",
                "keys": {},
                "qps_limit": 5
            }
            # SignUp is allowed since /tenants/signup skips rate limiting
            res_signup = self.client.post("/tenants/signup", json=payload, headers={"X-API-Key": "dev-security-key"})
            self.assertEqual(res_signup.status_code, 200)
            token = res_signup.json()["data"]["token"]
            headers = {"X-API-Key": token}

            # 1. Write request (POST) -> Fail-closed with 503
            res_write = self.client.post("/cases/seed", headers=headers)
            self.assertEqual(res_write.status_code, 503)
            self.assertIn("Service temporarily unavailable", res_write.json()["message"])

            # 2. Read request (GET) -> Degrades to local rate limit (Allowed)
            res_read = self.client.get("/cases", headers=headers)
            self.assertEqual(res_read.status_code, 200)
        finally:
            os.environ.pop("LLM_SECURITY_TEST_REDIS_DOWN", None)

    def test_celery_byok_keys_propagation(self):
        # 1. Sign up tenant with dynamic keys
        payload = {
            "tenant_id": "tenant_byok_runner",
            "actor": "byok-admin",
            "keys": {"OPENAI_COMPATIBLE_API_KEY": "secret-byok-value"},
            "qps_limit": 10
        }
        res_signup = self.client.post("/tenants/signup", json=payload, headers={"X-API-Key": "dev-security-key"})
        self.assertEqual(res_signup.status_code, 200)
        token = res_signup.json()["data"]["token"]

        # 2. Create an evaluation run under this tenant
        headers = {"X-API-Key": token}
        with patch("llm_security_platform.app.api.dispatch_run", return_value="task-tenant-byok"):
            res_create = self.client.post(
                "/async-runs",
                headers=headers,
                json={"name": "BYOK Test Run", "provider": "openai_compatible", "model": "gpt-4"},
            )
        self.assertEqual(res_create.status_code, 202)
        run_id = res_create.json()["data"]["run_id"]

        # 3. Trigger the Celery task synchronously
        from llm_security_platform.app.tasks import execute_evaluation_run
        
        with patch("llm_security_platform.app.tasks.build_provider") as mock_build_provider:
            from llm_security_platform.app.providers import MockProvider
            mock_build_provider.return_value = MockProvider()
            
            # Execute celery task synchronously
            execute_evaluation_run.run(run_id, tenant_id="tenant_byok_runner")
            
            # Assert build_provider was called with correct overridden keys in config
            mock_build_provider.assert_any_call(
                "openai_compatible", "gpt-4", {
                    "temperature": 0,
                    "top_p": 1,
                    "seed": 42,
                    "max_tokens": 256,
                    "timeout_seconds": 120,
                    "_tenant_keys": {"OPENAI_COMPATIBLE_API_KEY": "secret-byok-value"}
                }
            )

    @patch("google.cloud.tasks_v2.CloudTasksClient")
    def test_forged_host_header_injection_mitigation(self, mock_client_cls):
        import os
        from unittest.mock import MagicMock
        
        # 1. Setup environment variables to enforce worker service URL
        original_env = os.environ.get("LLM_SECURITY_ENV")
        original_mode = os.environ.get("LLM_SECURITY_QUEUE_MODE")
        original_url = os.environ.get("LLM_SECURITY_WORKER_SERVICE_URL")
        original_project = os.environ.get("GOOGLE_CLOUD_PROJECT")
        original_sa = os.environ.get("LLM_SECURITY_TASKS_SERVICE_ACCOUNT")
        
        os.environ["LLM_SECURITY_ENV"] = "production"
        os.environ["LLM_SECURITY_QUEUE_MODE"] = "cloud"
        os.environ["LLM_SECURITY_WORKER_SERVICE_URL"] = "https://legit-worker.service"
        os.environ["GOOGLE_CLOUD_PROJECT"] = "test-project"
        os.environ["LLM_SECURITY_TASKS_SERVICE_ACCOUNT"] = "task-sa@test-project.iam.gserviceaccount.com"
        
        # We need to re-initialize or mock the task_queue choice
        from llm_security_platform.app import task_queue
        # Temporarily swap task_queue to CloudTasksTaskQueue
        from llm_security_platform.app.task_queue import CloudTasksTaskQueue
        old_queue = task_queue.task_queue
        task_queue.task_queue = CloudTasksTaskQueue()
        
        # Setup mock CloudTasksClient
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.queue_path.return_value = "projects/test-project/locations/us-central1/queues/evaluation-run-queue"
        
        mock_response = MagicMock()
        mock_response.name = "projects/test-project/locations/us-central1/queues/evaluation-run-queue/tasks/test-task"
        mock_client.create_task.return_value = mock_response

        try:
            # Create a run and dispatch it with a forged Host header
            payload = {
                "name": "Host Header Test Run",
                "provider": "openai_compatible",
                "model": "gpt-4",
            }
            # Sign up a tenant to get a valid token
            signup_payload = {
                "tenant_id": "tenant_host_test",
                "actor": "host-admin",
                "keys": {},
                "qps_limit": 10
            }
            res_signup = self.client.post("/tenants/signup", json=signup_payload, headers={"X-API-Key": "dev-security-key"})
            token = res_signup.json()["data"]["token"]
            
            # Send POST to /async-runs with Host header set to forged value
            headers = {
                "X-API-Key": token,
                "Host": "malicious-attacker.com",
            }
            res = self.client.post("/async-runs", json=payload, headers=headers)
            self.assertEqual(res.status_code, 202)
            
            # Check the task structure created by create_task
            mock_client.create_task.assert_called_once()
            called_args = mock_client.create_task.call_args[1]
            enqueued_task = called_args["request"]["task"]
            
            # The URL MUST use the legit worker service URL, not the spoofed host
            enqueued_url = enqueued_task["http_request"]["url"]
            self.assertTrue(enqueued_url.startswith("https://legit-worker.service"))
            self.assertNotIn("malicious-attacker.com", enqueued_url)
            
            # 2. Test verify_cloud_tasks_oidc OIDC audience verification
            from llm_security_platform.app.security import verify_cloud_tasks_oidc
            with patch("google.oauth2.id_token.verify_oauth2_token") as mock_verify_oauth2_token:
                mock_verify_oauth2_token.return_value = {
                    "iss": "https://accounts.google.com",
                    "email": "task-sa@test-project.iam.gserviceaccount.com"
                }
                
                # verify_cloud_tasks_oidc should strictly require audience matches legit worker service URL
                verify_cloud_tasks_oidc("Bearer mockedtoken")
                mock_verify_oauth2_token.assert_called_once_with(
                    "mockedtoken",
                    patch.name if hasattr(patch, 'name') else unittest.mock.ANY,
                    "https://legit-worker.service"
                )
            
        finally:
            # Restore state
            task_queue.task_queue = old_queue
            if original_env is not None:
                os.environ["LLM_SECURITY_ENV"] = original_env
            else:
                os.environ.pop("LLM_SECURITY_ENV", None)
            if original_mode is not None:
                os.environ["LLM_SECURITY_QUEUE_MODE"] = original_mode
            else:
                os.environ.pop("LLM_SECURITY_QUEUE_MODE", None)
            if original_url is not None:
                os.environ["LLM_SECURITY_WORKER_SERVICE_URL"] = original_url
            else:
                os.environ.pop("LLM_SECURITY_WORKER_SERVICE_URL", None)
            if original_project is not None:
                os.environ["GOOGLE_CLOUD_PROJECT"] = original_project
            else:
                os.environ.pop("GOOGLE_CLOUD_PROJECT", None)
            if original_sa is not None:
                os.environ["LLM_SECURITY_TASKS_SERVICE_ACCOUNT"] = original_sa
            else:
                os.environ.pop("LLM_SECURITY_TASKS_SERVICE_ACCOUNT", None)


if __name__ == "__main__":
    unittest.main()
