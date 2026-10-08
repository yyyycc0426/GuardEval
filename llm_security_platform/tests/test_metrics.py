import shutil
import unittest
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from llm_security_platform.app import db, production_store
from llm_security_platform.app.api import app


class MetricsTests(unittest.TestCase):
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

    def tearDown(self):
        self.context.__exit__(None, None, None)
        if production_store._engine is not None:
            production_store._engine.dispose()
        db.DATABASE_PATH = self.original_db_path
        production_store.DATABASE_URL = self.original_url
        production_store._engine = None
        production_store._engine_url = None
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_metrics_endpoint_returns_prometheus_exposition_format(self):
        # Trigger an API request to populate the request count metrics
        self.client.get("/health")
        
        res = self.client.get("/metrics", headers={"X-API-Key": "reviewer-key"})
        self.assertEqual(res.status_code, 200)
        self.assertIn("text/plain", res.headers.get("content-type", ""))
        
        content = res.text
        self.assertIn("# HELP http_requests_total", content)
        self.assertIn("# TYPE http_requests_total counter", content)
        self.assertIn("http_requests_total", content)
        self.assertIn('method="GET"', content)
        self.assertIn('path="/health"', content)
        
        self.assertIn("# HELP raw_model_compromise_rate", content)
        self.assertIn("raw_model_compromise_rate", content)
        self.assertIn("# HELP completed_reviews_total", content)
        self.assertIn("completed_reviews_total", content)


if __name__ == "__main__":
    unittest.main()
