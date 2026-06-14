import unittest
import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from llm_security_platform.real_model_ablation import aggregate, compact_report, load_report
from llm_security_platform.tests.test_real_defense_validation import fake_report


class RealModelAblationTests(unittest.TestCase):
    def test_compact_report_contains_tradeoff_metrics(self):
        item = compact_report(fake_report(SimpleNamespace(model="qwen", defense_policy="none")))
        self.assertEqual(item["attack_success_rate"], 0.25)
        self.assertEqual(item["raw_model_compromise_rate"], 0.25)
        self.assertEqual(item["delivered_attack_success_rate"], 0.25)
        self.assertEqual(item["rag_leakage_asr"], 0.1)
        self.assertEqual(item["blocked_ratio"], 0.0)
        self.assertTrue(item["valid"])

    def test_aggregate_excludes_invalid_runs(self):
        valid = compact_report(fake_report(SimpleNamespace(model="qwen", defense_policy="none")))
        invalid = {**valid, "failed_cases": 61, "valid": False, "attack_success_rate": 0.0}
        summary = aggregate([valid, invalid])
        self.assertEqual(summary["valid_runs"], 1)
        self.assertEqual(summary["total_runs"], 2)
        self.assertEqual(summary["attack_success_rate"]["mean"], 0.25)

    def test_report_rejects_mixed_dataset_versions(self):
        directory = Path("llm_security_platform/.test_artifacts") / str(uuid4())
        directory.mkdir(parents=True)
        try:
            output = directory / "report.json"
            output.write_text(
                json.dumps({"dataset_version": "attackset_v2_frozen_64", "results": {}}),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "use a new output file"):
                load_report(output, dataset_version="attackset_v3")
        finally:
            shutil.rmtree(directory, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
