import unittest

from llm_security_platform.scripts.assign_spotcheck_reviewer import assign_reviewer


class AssignSpotcheckReviewerTests(unittest.TestCase):
    def test_assigns_reviewer_without_claiming_human_verification(self):
        packet = {
            "status": "awaiting_human_spot_check",
            "items": [
                {
                    "review_id": "1:case",
                    "reviewer": "codex-assisted-v1",
                    "review_status": "provisional_ai_assisted",
                }
            ],
        }

        updated = assign_reviewer(packet, "reviewer-01")

        self.assertEqual(updated["human_reviewer"], "reviewer-01")
        self.assertEqual(updated["status"], "human_spot_check_in_progress")
        self.assertEqual(updated["items"][0]["reviewer"], "reviewer-01")
        self.assertEqual(
            updated["items"][0]["review_status"],
            "awaiting_human_confirmation",
        )

    def test_rejects_empty_reviewer(self):
        with self.assertRaises(ValueError):
            assign_reviewer({"items": []}, "  ")


if __name__ == "__main__":
    unittest.main()
