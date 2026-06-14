import shutil
import unittest
from pathlib import Path
from uuid import uuid4

from llm_security_platform.app import db
from llm_security_platform.app.evaluator import compare_models
from llm_security_platform.app.schemas import ModelComparisonCreate, ModelTarget
from llm_security_platform.app.seed import seed_cases


class ModelComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path("llm_security_platform/.test_artifacts") / str(uuid4())
        self.temp_dir.mkdir(parents=True)
        self.original_path = db.DATABASE_PATH
        db.DATABASE_PATH = self.temp_dir / "comparison.db"
        db.init_db()
        seed_cases()

    def tearDown(self):
        db.DATABASE_PATH = self.original_path
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_comparison_keeps_successful_models_when_one_target_is_unavailable(self):
        result = compare_models(
            ModelComparisonCreate(
                name="comparison",
                targets=[
                    ModelTarget(provider="mock", model="mock-a"),
                    ModelTarget(provider="openai_compatible", model="remote-no-key"),
                ],
                case_ids=["atk-001", "ok-001"],
            )
        )
        self.assertEqual(result["models"][0]["status"], "completed")
        self.assertEqual(result["models"][1]["status"], "failed")
        self.assertIn("API_KEY", result["models"][1]["error"])


if __name__ == "__main__":
    unittest.main()
