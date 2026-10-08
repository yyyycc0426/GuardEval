import shutil
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from llm_security_platform.app import db, production_store
from llm_security_platform.app.api import app


class StageFiveRBACTests(unittest.TestCase):
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

    def test_role_permissions_are_enforced_by_backend(self):
        viewer = {"X-API-Key": "viewer-key"}
        analyst = {"X-API-Key": "analyst-key"}
        reviewer = {"X-API-Key": "reviewer-key"}
        self.assertEqual(self.client.get("/cases", headers=viewer).status_code, 403)
        self.assertEqual(
            self.client.post("/async-runs", headers=viewer, json={"name": "denied"}).status_code,
            403,
        )
        self.assertEqual(self.client.get("/audit-logs", headers=analyst).status_code, 403)
        self.assertEqual(self.client.get("/human-reviews", headers=reviewer).status_code, 200)

        with patch("llm_security_platform.app.api.dispatch_run", return_value="task-1"):
            response = self.client.post(
                "/async-runs",
                headers=analyst,
                json={"name": "allowed"},
            )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["data"]["status"], "PENDING")
        listing = self.client.get("/async-runs", headers=analyst)
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(len(listing.json()["data"]), 1)

    def test_admin_can_import_versioned_dataset_and_console_is_served(self):
        admin = {"X-API-Key": "dev-security-key"}
        response = self.client.post(
            "/datasets/import",
            headers=admin,
            json={
                "dataset_version": "ui-import-v1",
                "cases": [{
                    "case_id": "ui-import-001",
                    "name": "UI import sample",
                    "risk_type": "benign",
                    "prompt": "Summarize the public policy.",
                    "metadata": {
                        "attack_method": "benign_hard_negative",
                        "language": "en",
                        "severity": "none",
                        "expected_behavior": "allow",
                        "human_label": True,
                    },
                }],
            },
        )
        self.assertEqual(response.status_code, 200)
        imported = db.list_attack_cases(["ui-import-001"])[0]
        self.assertEqual(imported["metadata"]["dataset_version"], "ui-import-v1")
        console = self.client.get("/console/")
        self.assertEqual(console.status_code, 200)
        self.assertIn("测试集管理", console.text)


if __name__ == "__main__":
    unittest.main()
