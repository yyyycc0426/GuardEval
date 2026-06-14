import unittest

from llm_security_platform.stage_three_gate import evaluate_stage_three_gate


class StageThreeGateTests(unittest.TestCase):
    def test_gate_reports_missing_metrics_and_low_quality(self):
        failures = evaluate_stage_three_gate(
            {
                "case_count": 64,
                "rule_detector": {},
                "semantic_classifier": {"macro_f1": 0.2},
                "rule_first_fusion": {},
            },
            {"attack_success_f1": 0.2, "evidence_quote_validity": 0.1},
            {"frozen_benchmark": {"path": "missing.json", "case_count": 64}},
        )
        self.assertGreaterEqual(len(failures), 10)


if __name__ == "__main__":
    unittest.main()
