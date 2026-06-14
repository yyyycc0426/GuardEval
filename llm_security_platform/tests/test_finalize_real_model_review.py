import unittest

from llm_security_platform.scripts.finalize_real_model_review import build_report


class FinalizeRealModelReviewTests(unittest.TestCase):
    def test_compares_raw_and_delivered_labels_with_matching_evaluators(self):
        packet = {
            "items": [
                {
                    "judge_result": {"attack_success": True, "outcome": "partial_leak"},
                    "detector_result": {"attack_success": False, "outcome_label": "refuse"},
                    "human_final_label": "refuse",
                    "human_attack_success": False,
                    "raw_model_compromise": True,
                }
            ]
        }

        report = build_report(packet)

        self.assertEqual(report["raw_judge_human_raw_agreement"], 1.0)
        self.assertEqual(report["delivered_detector_human_delivered_agreement"], 1.0)
        self.assertEqual(report["delivered_detector_human_outcome_agreement"], 1.0)

    def test_omits_raw_agreement_until_raw_labels_exist(self):
        packet = {
            "items": [
                {
                    "judge_result": {"attack_success": False, "outcome": "refuse"},
                    "detector_result": {"attack_success": False, "outcome_label": "refuse"},
                    "human_final_label": "refuse",
                    "human_attack_success": False,
                }
            ]
        }

        report = build_report(packet)

        self.assertIsNone(report["raw_judge_human_raw_agreement"])
        self.assertEqual(report["raw_reviewed_count"], 0)


if __name__ == "__main__":
    unittest.main()
