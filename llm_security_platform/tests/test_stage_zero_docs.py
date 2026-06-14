import unittest
from pathlib import Path


class StageZeroDocumentationTests(unittest.TestCase):
    def test_threat_model_and_labeling_contract_are_documented(self):
        project_dir = Path(__file__).resolve().parents[1]
        files = [
            project_dir / "docs" / "threat_model.md",
            project_dir / "docs" / "success_criteria.md",
            project_dir / "docs" / "labeling_guide.md",
            project_dir / "docs" / "project_stages.md",
        ]
        combined = "\n".join(path.read_text(encoding="utf-8") for path in files)
        for term in (
            "攻击者",
            "保护资产",
            "Out Of Scope",
            "attack_success = true",
            "partial_leak",
            "full_leak",
            "人工复核",
            "malicious_chunk_recall",
            "normal_task_success_rate",
            "Adaptive Attack",
            "假密钥",
        ):
            with self.subTest(term=term):
                self.assertIn(term.lower(), combined.lower())


if __name__ == "__main__":
    unittest.main()
