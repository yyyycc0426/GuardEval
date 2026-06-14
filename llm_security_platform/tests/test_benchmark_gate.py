import unittest

from llm_security_platform.benchmark_gate import evaluate_gate


class BenchmarkGateTests(unittest.TestCase):
    def test_gate_passes_for_effective_low_false_positive_defense(self):
        report = {
            "attack_success_rate_reduction": 0.8,
            "with_defense": {
                "false_positive_rate": 0.05,
                "normal_task_success_rate": 0.95,
                "failed_cases": 0,
            },
        }
        self.assertEqual(evaluate_gate(report), [])

    def test_gate_reports_quality_regressions(self):
        report = {
            "attack_success_rate_reduction": 0.2,
            "with_defense": {
                "false_positive_rate": 0.3,
                "normal_task_success_rate": 0.5,
                "failed_cases": 1,
            },
        }
        failures = evaluate_gate(report)
        self.assertEqual(len(failures), 4)


if __name__ == "__main__":
    unittest.main()
