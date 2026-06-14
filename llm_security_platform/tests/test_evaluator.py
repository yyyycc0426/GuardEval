import shutil
import unittest
from unittest.mock import patch
from pathlib import Path
from uuid import uuid4

from llm_security_platform.app import db
from llm_security_platform.app.evaluator import compare_policies, execute_run
from llm_security_platform.app.schemas import EvaluationRunCreate
from llm_security_platform.app.seed import seed_cases
from llm_security_platform.app.providers import ModelCallResult, ModelProviderError


class FailsOnceProvider:
    name = "mock"
    model = "fails-once"

    def __init__(self):
        self.calls = 0

    def generate(self, _system_prompt, _user_prompt):
        self.calls += 1
        if self.calls == 1:
            raise ModelProviderError("synthetic single-call failure")
        return ModelCallResult("I can help with the allowed business request.")


class EvaluatorTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path("llm_security_platform/.test_artifacts") / str(uuid4())
        self.temp_dir.mkdir(parents=True)
        self.original_path = db.DATABASE_PATH
        db.DATABASE_PATH = self.temp_dir / "test.db"
        db.init_db()
        seed_cases()

    def tearDown(self):
        db.DATABASE_PATH = self.original_path
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_mock_run_produces_attack_success_report(self):
        report = execute_run(
            EvaluationRunCreate(name="baseline", provider="mock", defense_policy="none")
        )
        self.assertEqual(report.total_cases, 64)
        self.assertEqual(report.attack_case_count, 48)
        self.assertEqual(report.attack_success_rate, 1.0)
        self.assertEqual(report.raw_model_compromise_rate, 1.0)
        self.assertEqual(report.delivered_attack_success_rate, 1.0)
        self.assertEqual(report.false_positive_rate, 0.0)
        self.assertEqual(report.normal_task_success_rate, 1.0)
        self.assertEqual(report.run_metadata["versions"]["dataset_version"], "attackset_v2")
        self.assertEqual(len(report.run_metadata["run_config_hash"]), 64)
        self.assertGreater(report.total_tokens, 0)
        self.assertIn("zh", report.by_language)
        self.assertIn("direct_injection", report.by_attack_method)

    def test_baseline_defense_reduces_attack_success_without_blocking_benign_cases(self):
        comparison = compare_policies("comparison", provider="mock")
        self.assertEqual(comparison["without_defense"]["attack_success_rate"], 1.0)
        self.assertEqual(comparison["with_defense"]["attack_success_rate"], 0.0)
        self.assertEqual(comparison["with_defense"]["false_positive_rate"], 0.0)
        self.assertGreaterEqual(comparison["with_defense"]["normal_task_success_rate"], 0.9)
        self.assertEqual(comparison["attack_success_rate_reduction"], 1.0)

    def test_single_model_call_failure_does_not_abort_the_run(self):
        with patch(
            "llm_security_platform.app.evaluator.build_provider",
            return_value=FailsOnceProvider(),
        ):
            report = execute_run(
                EvaluationRunCreate(
                    name="failure isolation",
                    provider="mock",
                    case_ids=["atk-001", "ok-001"],
                )
            )
        self.assertEqual(report.status, "completed_with_errors")
        self.assertEqual(report.total_cases, 2)
        self.assertEqual(report.failed_cases, 1)
        self.assertEqual(report.completed_cases, 1)


if __name__ == "__main__":
    unittest.main()
