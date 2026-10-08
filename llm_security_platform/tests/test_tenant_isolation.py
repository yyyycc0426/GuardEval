import shutil
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from llm_security_platform.app import db, production_store
from llm_security_platform.app.api import app


class TenantIsolationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path("llm_security_platform/.test_artifacts") / str(uuid4())
        self.temp_dir.mkdir(parents=True)
        self.original_db_path = db.DATABASE_PATH
        self.original_url = production_store.DATABASE_URL
        db.DATABASE_PATH = self.temp_dir / "legacy.db"
        production_store.DATABASE_URL = f"sqlite:///{(self.temp_dir / 'production.db').resolve().as_posix()}"
        production_store._engine = None
        production_store._engine_url = None
        
        self.context = TestClient(app)
        self.client = self.context.__enter__()

        # Setup test keys/principals
        self.principals = {
            "key-tenant-a": {"actor": "user-a", "role": "admin", "tenant_id": "tenant_a"},
            "key-tenant-b": {"actor": "user-b", "role": "admin", "tenant_id": "tenant_b"},
            "analyst-a": {"actor": "analyst-a", "role": "analyst", "tenant_id": "tenant_a"},
            "analyst-b": {"actor": "analyst-b", "role": "analyst", "tenant_id": "tenant_b"},
        }
        self.patcher = patch("llm_security_platform.app.security._principals", return_value=self.principals)
        self.patcher.start()
        self.redis_patcher = patch("llm_security_platform.app.api.get_redis", return_value=None)
        self.redis_patcher.start()

    def tearDown(self):
        self.redis_patcher.stop()
        self.patcher.stop()
        self.context.__exit__(None, None, None)
        if production_store._engine is not None:
            production_store._engine.dispose()
        db.DATABASE_PATH = self.original_db_path
        production_store.DATABASE_URL = self.original_url
        production_store._engine = None
        production_store._engine_url = None
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_run_isolation_between_tenants(self):
        headers_a = {"X-API-Key": "analyst-a"}
        headers_b = {"X-API-Key": "analyst-b"}

        # Tenant A creates a run
        with patch("llm_security_platform.app.api.dispatch_run", return_value="task-tenant-a"):
            res_create = self.client.post(
                "/async-runs",
                headers=headers_a,
                json={"name": "Run Tenant A", "provider": "mock"},
            )
        self.assertEqual(res_create.status_code, 202)
        run_id = res_create.json()["data"]["run_id"]

        # Tenant B should NOT see the run in list
        res_list_b = self.client.get("/async-runs", headers=headers_b)
        self.assertEqual(res_list_b.status_code, 200)
        self.assertEqual(len(res_list_b.json()["data"]), 0)

        # Tenant A should see the run in list
        res_list_a = self.client.get("/async-runs", headers=headers_a)
        self.assertEqual(res_list_a.status_code, 200)
        self.assertEqual(len(res_list_a.json()["data"]), 1)
        self.assertEqual(res_list_a.json()["data"][0]["run_id"], run_id)

        # Tenant B should NOT be able to access the run detail directly
        res_detail_b = self.client.get(f"/async-runs/{run_id}", headers=headers_b)
        self.assertEqual(res_detail_b.status_code, 404)

        # Tenant A should be able to access the run detail
        res_detail_a = self.client.get(f"/async-runs/{run_id}", headers=headers_a)
        self.assertEqual(res_detail_a.status_code, 200)

    def test_policy_isolation_between_tenants(self):
        headers_a = {"X-API-Key": "key-tenant-a"}
        headers_b = {"X-API-Key": "key-tenant-b"}

        # Tenant A creates custom policy version
        res_create = self.client.post(
            "/policies",
            headers=headers_a,
            json={
                "name": "input_defense",
                "version": "custom_v2",
                "description": "Tenant A custom policy",
                "config": {"block_threshold": 0.85}
            }
        )
        self.assertEqual(res_create.status_code, 200)

        # Tenant B lists policies: should NOT see custom_v2
        res_list_b = self.client.get("/policies", headers=headers_b)
        self.assertEqual(res_list_b.status_code, 200)
        policy_versions_b = [p["version"] for p in res_list_b.json()["data"] if p["name"] == "input_defense"]
        self.assertNotIn("custom_v2", policy_versions_b)

        # Tenant B fetches custom_v2: should return 404
        res_get_b = self.client.get("/policies/input_defense/custom_v2", headers=headers_b)
        self.assertEqual(res_get_b.status_code, 404)

        # Tenant A lists policies: should see custom_v2
        res_list_a = self.client.get("/policies", headers=headers_a)
        self.assertEqual(res_list_a.status_code, 200)
        policy_versions_a = [p["version"] for p in res_list_a.json()["data"] if p["name"] == "input_defense"]
        self.assertIn("custom_v2", policy_versions_a)

    def test_jwt_and_rbac_e2e(self):
        from llm_security_platform.app.security import encode_jwt

        # Create JWTs for different roles and tenants
        token_a_analyst = "Bearer " + encode_jwt("jwt-user-a", "analyst", "tenant_a")
        token_b_viewer = "Bearer " + encode_jwt("jwt-user-b", "viewer", "tenant_b")

        # 1. Verify RBAC restriction: viewer cannot create runs
        res_create_fail = self.client.post(
            "/async-runs",
            headers={"X-API-Key": token_b_viewer},
            json={"name": "Run Tenant B", "provider": "mock"},
        )
        self.assertEqual(res_create_fail.status_code, 403)  # Forbidden

        # 2. Verify analyst can create runs
        with patch("llm_security_platform.app.api.dispatch_run", return_value="task-tenant-a-jwt") as mock_dispatch:
            res_create = self.client.post(
                "/async-runs",
                headers={"X-API-Key": token_a_analyst},
                json={"name": "Run Tenant A JWT", "provider": "mock"},
            )
            self.assertEqual(res_create.status_code, 202)
            mock_dispatch.assert_called_once()
            self.assertEqual(mock_dispatch.call_args[1].get("tenant_id"), "tenant_a")

        run_id = res_create.json()["data"]["run_id"]

        # 3. Verify tenant isolation: tenant B viewer cannot see or access tenant A's run
        res_list_b = self.client.get("/async-runs", headers={"X-API-Key": token_b_viewer})
        self.assertEqual(res_list_b.status_code, 200)
        self.assertEqual(len(res_list_b.json()["data"]), 0)

        # 4. Verify tenant A analyst can see tenant A's run
        res_list_a = self.client.get("/async-runs", headers={"X-API-Key": token_a_analyst})
        self.assertEqual(res_list_a.status_code, 200)
        self.assertEqual(len(res_list_a.json()["data"]), 1)
        self.assertEqual(res_list_a.json()["data"][0]["run_id"], run_id)

    def test_celery_task_tenant_propagation(self):
        # Create a run inside tenant_a database context
        headers_a = {"X-API-Key": "analyst-a"}
        with patch("llm_security_platform.app.api.dispatch_run", return_value="task-tenant-a"):
            res_create = self.client.post(
                "/async-runs",
                headers=headers_a,
                json={"name": "Run Tenant A For Worker", "provider": "mock"},
            )
        self.assertEqual(res_create.status_code, 202)
        run_id = res_create.json()["data"]["run_id"]

        # Run the celery task synchronously using execute_evaluation_run.run(run_id, tenant_id="tenant_a")
        from llm_security_platform.app.tasks import execute_evaluation_run
        
        # We temporarily patch build_provider to return standard mock provider
        from llm_security_platform.app.providers import MockProvider
        with patch("llm_security_platform.app.tasks.build_provider", return_value=MockProvider()):
            # Run task
            res = execute_evaluation_run.run(run_id, tenant_id="tenant_a")
            self.assertEqual(res["status"], "COMPLETED")

        # Verify that we can query the run details from tenant A's context, but not from tenant B's context
        res_detail_b = self.client.get(f"/async-runs/{run_id}", headers={"X-API-Key": "analyst-b"})
        self.assertEqual(res_detail_b.status_code, 404)

        res_detail_a = self.client.get(f"/async-runs/{run_id}", headers={"X-API-Key": "analyst-a"})
        self.assertEqual(res_detail_a.status_code, 200)

    def test_dataset_import_isolation(self):
        headers_a = {"X-API-Key": "key-tenant-a"}
        headers_b = {"X-API-Key": "key-tenant-b"}

        # 1. Tenant A imports a dataset with a case
        import_payload = {
            "dataset_version": "v_import_a",
            "cases": [
                {
                    "case_id": "imported_case_1",
                    "name": "Jailbreak A",
                    "risk_type": "jailbreak",
                    "prompt": "Attacker prompt",
                    "system_prompt": "System prompt",
                    "success_indicators": ["compromised"],
                    "safe_response_indicators": [],
                    "metadata": {}
                }
            ]
        }
        res_import = self.client.post("/datasets/import", headers=headers_a, json=import_payload)
        self.assertEqual(res_import.status_code, 200)

        # 2. Tenant B should NOT see the imported case in their cases list
        res_cases_b = self.client.get("/cases", headers=headers_b)
        self.assertEqual(res_cases_b.status_code, 200)
        case_ids_b = [c["case_id"] for c in res_cases_b.json()["data"]]
        self.assertNotIn("imported_case_1", case_ids_b)

        # 3. Tenant A should see the case in their cases list
        res_cases_a = self.client.get("/cases", headers=headers_a)
        self.assertEqual(res_cases_a.status_code, 200)
        case_ids_a = [c["case_id"] for c in res_cases_a.json()["data"]]
        self.assertIn("imported_case_1", case_ids_a)

        # 4. Tenant B can import a case with the same case_id but different name/prompt without conflict/overwrite
        import_payload_b = {
            "dataset_version": "v_import_b",
            "cases": [
                {
                    "case_id": "imported_case_1",
                    "name": "Jailbreak B",
                    "risk_type": "jailbreak",
                    "prompt": "Different prompt B",
                    "system_prompt": "System prompt B",
                    "success_indicators": ["compromised"],
                    "safe_response_indicators": [],
                    "metadata": {}
                }
            ]
        }
        res_import_b = self.client.post("/datasets/import", headers=headers_b, json=import_payload_b)
        self.assertEqual(res_import_b.status_code, 200)

        # 5. Verify that each tenant retrieves their own prompt/version of the case
        res_cases_a2 = self.client.get("/cases", headers=headers_a)
        case_a = next(c for c in res_cases_a2.json()["data"] if c["case_id"] == "imported_case_1")
        self.assertEqual(case_a["name"], "Jailbreak A")
        self.assertEqual(case_a["prompt"], "Attacker prompt")

        res_cases_b2 = self.client.get("/cases", headers=headers_b)
        case_b = next(c for c in res_cases_b2.json()["data"] if c["case_id"] == "imported_case_1")
        self.assertEqual(case_b["name"], "Jailbreak B")
        self.assertEqual(case_b["prompt"], "Different prompt B")

    def test_cross_tenant_token_rejection(self):
        # 1. Tenant A (analyst-a) requests a token. It should only be issued for tenant_a.
        res_token = self.client.post("/tenants/token", headers={"X-API-Key": "analyst-a"})
        self.assertEqual(res_token.status_code, 200)
        token_data = res_token.json()["data"]
        self.assertEqual(token_data["tenant_id"], "tenant_a")
        
        # Verify the decoded JWT payload
        from llm_security_platform.app.security import decode_jwt
        decoded = decode_jwt(token_data["token"])
        self.assertIsNotNone(decoded)
        self.assertEqual(decoded["tenant_id"], "tenant_a")
        self.assertEqual(decoded["actor"], "analyst-a")
        self.assertEqual(decoded["role"], "analyst")

        # 2. Verify that Tenant A cannot call /tenants/signup to create a tenant or fetch a cross-tenant token
        payload = {
            "tenant_id": "tenant_cross",
            "actor": "cross-admin",
            "keys": {},
            "qps_limit": 10
        }
        res_signup = self.client.post("/tenants/signup", headers={"X-API-Key": "analyst-a"}, json=payload)
        self.assertEqual(res_signup.status_code, 403)

        # 3. Verify that calling /tenants/token with invalid key fails with 401
        res_fail = self.client.post("/tenants/token", headers={"X-API-Key": "invalid-key"})
        self.assertEqual(res_fail.status_code, 401)


if __name__ == "__main__":
    unittest.main()
