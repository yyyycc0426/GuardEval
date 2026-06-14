import unittest

from llm_security_platform.app.dataset import load_dataset, validate_dataset
from llm_security_platform.app.seed import DEFAULT_CASES_PATH


class DatasetTests(unittest.TestCase):
    def test_stage_two_dataset_meets_size_balance_and_label_contract(self):
        cases = load_dataset(DEFAULT_CASES_PATH)
        self.assertEqual(validate_dataset(cases), [])
        self.assertGreaterEqual(len(cases), 60)
        self.assertGreaterEqual(
            sum(case["risk_type"] == "benign" for case in cases) / len(cases),
            0.25,
        )
        self.assertEqual(
            {case["metadata"]["language"] for case in cases},
            {"zh", "en"},
        )
        self.assertGreaterEqual(
            len({case["metadata"]["attack_method"] for case in cases}),
            9,
        )


if __name__ == "__main__":
    unittest.main()
