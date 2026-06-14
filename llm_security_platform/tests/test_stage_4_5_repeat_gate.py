import unittest

from llm_security_platform.real_model_ablation import FULL_DEFENSE
from llm_security_platform.stage_4_5_repeat_gate import check


def metric(value=0.1):
    return {"mean": value, "min": value, "max": value}


def valid_report():
    results = {}
    for model in ("qwen3:8b", "qwen3.6:latest"):
        results[model] = {}
        for strategy in ("none", "rag_defense", FULL_DEFENSE):
            results[model][strategy] = {
                "summary": {
                    "valid_runs": 3,
                    "raw_model_compromise_rate": metric(),
                    "delivered_attack_success_rate": metric(),
                    "rag_leakage_asr": metric(),
                    "normal_task_success_rate": metric(0.9),
                    "false_positive_rate": metric(0.05),
                    "p95_latency_ms": metric(1000),
                    "failed_cases": metric(0),
                    "blocked_ratio": metric(0.2),
                }
            }
    return {"results": results}


class Stage45RepeatGateTests(unittest.TestCase):
    def test_accepts_complete_repeated_report(self):
        self.assertEqual(check(valid_report())["status"], "passed")

    def test_rejects_missing_repeat(self):
        report = valid_report()
        report["results"]["qwen3:8b"]["none"]["summary"]["valid_runs"] = 2

        result = check(report)

        self.assertEqual(result["status"], "failed")
        self.assertIn("qwen3:8b/none requires three valid runs", result["failures"])


if __name__ == "__main__":
    unittest.main()
