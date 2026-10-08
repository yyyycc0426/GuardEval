import shutil
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from llm_security_platform.app import db
from llm_security_platform.app.api import app
from llm_security_platform.app.config import API_KEY


class SecurityAPITests(unittest.TestCase):
    def setUp(self):
        from llm_security_platform.app import production_store
        self.temp_dir = Path("llm_security_platform/.test_artifacts") / str(uuid4())
        self.temp_dir.mkdir(parents=True)
        self.original_path = db.DATABASE_PATH
        self.original_url = production_store.DATABASE_URL
        
        db.DATABASE_PATH = self.temp_dir / "api-test.db"
        production_store.DATABASE_URL = f"sqlite:///{(self.temp_dir / 'production.db').resolve().as_posix()}"
        production_store._engine = None
        production_store._engine_url = None
        production_store.init_production_db()
        
        self.client_context = TestClient(app)
        self.client = self.client_context.__enter__()
        self.headers = {"X-API-Key": API_KEY}
        self.redis_patcher = patch("llm_security_platform.app.api.get_redis", return_value=None)
        self.redis_patcher.start()

    def tearDown(self):
        self.redis_patcher.stop()
        from llm_security_platform.app import production_store
        self.client_context.__exit__(None, None, None)
        if production_store._engine is not None:
            production_store._engine.dispose()
        db.DATABASE_PATH = self.original_path
        production_store.DATABASE_URL = self.original_url
        production_store._engine = None
        production_store._engine_url = None
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_health_is_public_and_cases_require_authentication(self):
        self.assertEqual(self.client.get("/health").status_code, 200)
        self.assertEqual(self.client.get("/cases").status_code, 401)
        response = self.client.get("/cases", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["data"]), 104)

    def test_defense_comparison_endpoint(self):
        response = self.client.post(
            "/comparisons",
            headers=self.headers,
            json={"name": "api comparison", "provider": "mock", "defense_policy": "none"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["without_defense"]["attack_success_rate"], 1.0)
        self.assertEqual(data["with_defense"]["attack_success_rate"], 0.0)
        audit_response = self.client.get(
            f"/runs/{data['with_defense']['run_id']}/defense-audits",
            headers=self.headers,
        )
        self.assertEqual(audit_response.status_code, 200)
        self.assertTrue(audit_response.json()["data"])
        self.assertTrue(audit_response.json()["data"][0]["decision"]["evidence"])

    def test_layered_assessment_creates_and_completes_human_review(self):
        assessment = self.client.post(
            "/layered-assessments",
            headers=self.headers,
            json={
                "case_id": "atk-001",
                "model_response": "INJECTION_SUCCEEDED",
                "judge_provider": "mock",
            },
        )
        self.assertEqual(assessment.status_code, 200)
        self.assertTrue(assessment.json()["data"]["assessment"]["needs_human_review"])
        queue = self.client.get("/human-reviews", headers=self.headers)
        self.assertEqual(queue.status_code, 200)
        review_id = queue.json()["data"][0]["id"]
        completed = self.client.patch(
            f"/human-reviews/{review_id}",
            headers=self.headers,
            json={
                "human_final_label": "partial_leak",
                "human_attack_success": True,
                "reviewer_note": "Confirmed synthetic success marker disclosure.",
                "reviewer": "test-reviewer",
            },
        )
        self.assertEqual(completed.status_code, 200)
        completed_queue = self.client.get(
            "/human-reviews?status=completed",
            headers=self.headers,
        )
        self.assertEqual(len(completed_queue.json()["data"]), 1)
        metrics = self.client.get("/human-reviews/metrics", headers=self.headers)
        self.assertEqual(metrics.status_code, 200)
        self.assertEqual(metrics.json()["data"]["completed_reviews"], 1)

    def test_query_param_token_authentication(self):
        # Request /cases with token query parameter instead of X-API-Key header
        response = self.client.get("/cases?token=dev-security-key")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(len(response.json()["data"]) > 0)

    def test_async_run_report_export(self):
        from unittest.mock import patch
        # 1. Create an async run
        with patch("llm_security_platform.app.api.dispatch_run", return_value="test-task-1"):
            comp_response = self.client.post(
                "/async-runs",
                headers=self.headers,
                json={"name": "export test async run", "provider": "mock", "defense_policy": "none"},
            )
        self.assertEqual(comp_response.status_code, 202)
        run_id = comp_response.json()["data"]["run_id"]
        
        # 2. Export the run
        # Test exporting with token in query param
        response = self.client.get(f"/async-runs/{run_id}/export?token=dev-security-key")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Content-Disposition", response.headers)
        self.assertIn(f'attachment; filename="report_{run_id}.json"', response.headers["Content-Disposition"])
        
        # Verify JSON content structure
        data = response.json()
        self.assertIn("run", data)
        self.assertIn("report", data)
        self.assertIn("cases", data)


if __name__ == "__main__":
    unittest.main()
