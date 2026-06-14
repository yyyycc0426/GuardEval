import json
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from llm_security_platform.app.schemas import EvaluationReport
from llm_security_platform.run_real_defense_validation import MODELS, STRATEGIES, run


def fake_report(request):
    return EvaluationReport(
        run_id=1,
        status="completed",
        total_cases=64,
        completed_cases=64,
        failed_cases=0,
        blocked_cases=0,
        attack_case_count=48,
        successful_attacks=12,
        attack_success_rate=0.25,
        raw_model_compromise_rate=0.25,
        delivered_attack_success_rate=0.25,
        benign_case_count=16,
        benign_block_count=0,
        false_positive_rate=0.0,
        normal_task_success_rate=1.0,
        average_latency_ms=10,
        p50_latency_ms=9,
        p95_latency_ms=12,
        total_tokens=100,
        estimated_total_cost=0,
        failure_rate=0,
        defense_precision=1,
        defense_recall=1,
        defense_f1=1,
        defense_false_negative_rate=0,
        review_rate=0,
        defense_action_counts={},
        by_risk_type={"rag_data_leakage": {"attack_success_rate": 0.1}},
        by_language={},
        by_attack_method={},
        run_metadata={"model": request.model, "defense_policy": request.defense_policy},
    )


class RealDefenseValidationTests(unittest.TestCase):
    def test_runner_persists_each_model_strategy_and_can_resume(self):
        directory = Path("llm_security_platform/.test_artifacts") / str(uuid4())
        directory.mkdir(parents=True)
        try:
            output = directory / "report.json"
            with patch(
                "llm_security_platform.run_real_defense_validation.execute_run",
                side_effect=fake_report,
            ) as mocked:
                report = run(output, models=[MODELS[0]], strategies=STRATEGIES[:2])
                self.assertEqual(mocked.call_count, 2)
                self.assertTrue(output.is_file())
                self.assertEqual(set(report["results"][MODELS[0]]), set(STRATEGIES[:2]))
                run(output, resume=True, models=[MODELS[0]], strategies=STRATEGIES[:2])
                self.assertEqual(mocked.call_count, 2)
            persisted = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(persisted["case_count"], 64)
        finally:
            shutil.rmtree(directory, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
