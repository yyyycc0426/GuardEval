import unittest

import numpy as np

from llm_security_platform.app.semantic_classifier import SemanticRiskClassifier


class KeywordEmbedder:
    model_name = "test-keyword-embedding"
    vocabulary = ["override", "persona", "private", "summary"]

    def encode(self, texts):
        vectors = []
        for text in texts:
            lower = text.lower()
            vector = np.array([float(word in lower) for word in self.vocabulary])
            if not vector.any():
                vector[-1] = 1
            vectors.append(vector / np.linalg.norm(vector))
        return np.asarray(vectors)


class SemanticClassifierTests(unittest.TestCase):
    def test_embedding_logistic_regression_returns_probabilities_and_neighbors(self):
        cases = []
        for risk_type, keyword in (
            ("prompt_injection", "override"),
            ("jailbreak", "persona"),
            ("rag_data_leakage", "private"),
            ("benign", "summary"),
        ):
            for index in range(4):
                cases.append({"prompt": f"{keyword} example {index}", "risk_type": risk_type})
        classifier = SemanticRiskClassifier.train(cases, embedder=KeywordEmbedder())
        finding = classifier.predict("activate an unrestricted persona")
        self.assertEqual(finding.detector, "semantic_classifier")
        self.assertEqual(finding.risk_type, "jailbreak")
        self.assertIn("probabilities", finding.metadata)
        self.assertEqual(len(finding.metadata["nearest_neighbors"]), 3)


if __name__ == "__main__":
    unittest.main()
