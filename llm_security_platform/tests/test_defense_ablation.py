import shutil
import unittest
from pathlib import Path
from uuid import uuid4

from llm_security_platform.app import db
from llm_security_platform.run_defense_ablation import STRATEGIES, run_ablation


class DefenseAblationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path("llm_security_platform/.test_artifacts") / str(uuid4())
        self.temp_dir.mkdir(parents=True)
        self.original_path = db.DATABASE_PATH
        db.DATABASE_PATH = self.temp_dir / "ablation.db"

    def tearDown(self):
        db.DATABASE_PATH = self.original_path
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_nine_strategy_ablation_is_auditable_and_not_all_blocking(self):
        report = run_ablation()
        self.assertEqual(set(report["strategies"]), set(STRATEGIES))
        full = report["strategies"]["input_defense+rag_defense+output_defense"]
        self.assertLess(full["attack_success_rate"], report["strategies"]["none"]["attack_success_rate"])
        self.assertGreaterEqual(full["normal_task_success_rate"], 0.8)
        self.assertLess(full["blocked_ratio"], 1.0)
        self.assertTrue(db.list_defense_audits(full["run_id"]))
        self.assertEqual(full["failed_cases"], 0)


if __name__ == "__main__":
    unittest.main()
