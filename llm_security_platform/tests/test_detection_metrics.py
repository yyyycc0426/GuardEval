import unittest

from llm_security_platform.run_detection_benchmark import metric_block


class DetectionMetricsTests(unittest.TestCase):
    def test_metric_block_reports_macro_and_per_class_metrics(self):
        expected = ["benign", "prompt_injection", "jailbreak", "rag_data_leakage"]
        predicted = ["benign", "prompt_injection", "benign", "rag_data_leakage"]
        metrics = metric_block(expected, predicted)
        self.assertEqual(metrics["accuracy"], 0.75)
        self.assertIn("macro_f1", metrics)
        self.assertEqual(metrics["false_positive_rate"], 0.0)
        self.assertGreater(metrics["false_negative_rate"], 0.0)
        self.assertEqual(len(metrics["confusion_matrix"]), 4)


if __name__ == "__main__":
    unittest.main()
