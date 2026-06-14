import unittest

from llm_security_platform.stage_four_gate import evaluate_stage_four_gate


class StageFourGateTests(unittest.TestCase):
    def test_gate_rejects_all_blocking_defense(self):
        strategies = {}
        from llm_security_platform.run_defense_ablation import STRATEGIES

        for strategy in STRATEGIES:
            strategies[strategy] = {
                "attack_success_rate": 1.0 if strategy == "none" else 0.0,
                "normal_task_success_rate": 0.0,
                "false_positive_rate": 1.0,
                "p95_latency_ms": 1.0,
                "blocked_ratio": 1.0,
                "blocked_cases": 64,
                "total_cases": 64,
                "audit_evidence_coverage": 1.0,
                "failed_cases": 0,
                "by_risk_type": {"rag_data_leakage": {"attack_success_rate": 1.0}},
                "defense_action_counts": {"block": 64},
            }
        failures = evaluate_stage_four_gate(
            {"strategies": strategies, "independent_contribution": {}}
        )
        self.assertIn("defense relies on excessive blocking", failures)
        self.assertIn("all cases were blocked", failures)


if __name__ == "__main__":
    unittest.main()
