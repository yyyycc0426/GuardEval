import unittest

from llm_security_platform.scripts.build_holdout_dataset import build


class HoldoutDatasetTests(unittest.TestCase):
    def test_blinded_holdout_has_expected_size_and_no_labels(self):
        public, private = build()
        self.assertEqual(len(public), 128)
        self.assertEqual(len(private), 128)
        self.assertEqual(len({item["case_id"] for item in public}), 128)
        self.assertTrue(all("risk_type" not in item for item in public))
        self.assertEqual(sum(item["risk_type"] == "benign" for item in private), 32)
        self.assertEqual(sum(item["risk_type"] != "benign" for item in private), 96)

    def test_public_and_private_ids_match(self):
        public, private = build()
        self.assertEqual(
            {item["case_id"] for item in public},
            {item["case_id"] for item in private},
        )


if __name__ == "__main__":
    unittest.main()
