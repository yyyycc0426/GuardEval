import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class StageThreeDatasetTests(unittest.TestCase):
    def test_frozen_benchmark_hash_matches_manifest(self):
        manifest = json.loads((ROOT / "data" / "dataset_manifest.json").read_text(encoding="utf-8"))
        benchmark = ROOT / "data" / "attack_cases_v2.json"
        self.assertFalse(manifest["frozen_benchmark"]["mutable"])
        self.assertEqual(
            hashlib.sha256(benchmark.read_bytes()).hexdigest(),
            manifest["frozen_benchmark"]["sha256"],
        )

    def test_training_data_is_separate_balanced_and_non_overlapping(self):
        train = json.loads((ROOT / "data" / "attack_cases_v3_train.json").read_text(encoding="utf-8"))
        dev = json.loads((ROOT / "data" / "attack_cases_v3_dev.json").read_text(encoding="utf-8"))
        frozen = json.loads((ROOT / "data" / "attack_cases_v2.json").read_text(encoding="utf-8"))
        self.assertEqual(len(train), 48)
        self.assertEqual(len(dev), 12)
        self.assertEqual(
            {risk: sum(case["risk_type"] == risk for case in train) for risk in {case["risk_type"] for case in train}},
            {"prompt_injection": 12, "jailbreak": 12, "rag_data_leakage": 12, "benign": 12},
        )
        self.assertTrue({case["prompt"] for case in train}.isdisjoint({case["prompt"] for case in frozen}))
        self.assertTrue({case["prompt"] for case in dev}.isdisjoint({case["prompt"] for case in train}))
        self.assertTrue({case["prompt"] for case in dev}.isdisjoint({case["prompt"] for case in frozen}))

    def test_judge_eval_hash_matches_manifest(self):
        manifest = json.loads((ROOT / "data" / "dataset_manifest.json").read_text(encoding="utf-8"))
        judge_eval = ROOT / "data" / "judge_eval_cases_v1.json"
        self.assertEqual(
            hashlib.sha256(judge_eval.read_bytes()).hexdigest(),
            manifest["judge_eval"]["sha256"],
        )


if __name__ == "__main__":
    unittest.main()
