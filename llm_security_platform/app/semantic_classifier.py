import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression

from llm_security_platform.app.schemas import DetectorResult


DEFAULT_EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
SEMANTIC_DETECTOR_VERSION = "embedding_lr_v1"


class SentenceTransformerEmbedder:
    def __init__(self, model_name=DEFAULT_EMBEDDING_MODEL, local_files_only=True):
        from sentence_transformers import SentenceTransformer

        self.model_name = model_name
        self.model = SentenceTransformer(model_name, local_files_only=local_files_only)

    def encode(self, texts):
        return np.asarray(
            self.model.encode(
                list(texts),
                convert_to_numpy=True,
                normalize_embeddings=True,
            ),
            dtype=float,
        )


@dataclass
class SemanticArtifact:
    classifier: LogisticRegression
    labels: list[str]
    embedding_model: str
    detector_version: str
    train_dataset_sha256: str
    train_prompts: list[str]
    train_labels: list[str]
    train_embeddings: np.ndarray


class SemanticRiskClassifier:
    def __init__(self, artifact, embedder=None):
        self.artifact = artifact
        self.embedder = embedder or SentenceTransformerEmbedder(artifact.embedding_model)

    @classmethod
    def train(
        cls,
        cases,
        embedder=None,
        embedding_model=DEFAULT_EMBEDDING_MODEL,
        train_dataset_sha256=None,
    ):
        embedder = embedder or SentenceTransformerEmbedder(embedding_model)
        prompts = [case["prompt"] for case in cases]
        labels = [case["risk_type"] for case in cases]
        embeddings = np.asarray(embedder.encode(prompts), dtype=float)
        classifier = LogisticRegression(
            max_iter=1000,
            class_weight="balanced",
            random_state=42,
        )
        classifier.fit(embeddings, labels)
        serialized = json.dumps(cases, sort_keys=True, ensure_ascii=True).encode("utf-8")
        artifact = SemanticArtifact(
            classifier=classifier,
            labels=list(classifier.classes_),
            embedding_model=getattr(embedder, "model_name", embedding_model),
            detector_version=SEMANTIC_DETECTOR_VERSION,
            train_dataset_sha256=train_dataset_sha256 or hashlib.sha256(serialized).hexdigest(),
            train_prompts=prompts,
            train_labels=labels,
            train_embeddings=embeddings,
        )
        return cls(artifact, embedder=embedder)

    def save(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self.artifact, path)

    @classmethod
    def load(cls, path, embedder=None):
        return cls(joblib.load(path), embedder=embedder)

    def predict(self, prompt):
        embedding = np.asarray(self.embedder.encode([prompt]), dtype=float)[0]
        probabilities = self.artifact.classifier.predict_proba([embedding])[0]
        by_label = {
            label: float(probability)
            for label, probability in zip(self.artifact.classifier.classes_, probabilities, strict=True)
        }
        predicted = max(by_label, key=by_label.get)
        confidence = by_label[predicted]
        benign_probability = by_label.get("benign", 0.0)
        risk_score = 1.0 - benign_probability
        similarities = np.dot(self.artifact.train_embeddings, embedding)
        neighbor_indexes = np.argsort(similarities)[-3:][::-1]
        neighbors = [
            {
                "case_label": self.artifact.train_labels[index],
                "similarity": round(float(similarities[index]), 4),
                "snippet": self.artifact.train_prompts[index][:100],
            }
            for index in neighbor_indexes
        ]
        if risk_score >= 0.7:
            decision = "high_risk"
        elif risk_score >= 0.35:
            decision = "medium_risk"
        else:
            decision = "low_risk"
        return DetectorResult(
            detector="semantic_classifier",
            detector_version=self.artifact.detector_version,
            scope="input",
            risk_type=predicted,
            risk_score=round(risk_score, 4),
            confidence=round(confidence, 4),
            evidence=[
                f"nearest={item['case_label']}; similarity={item['similarity']}; snippet={item['snippet']}"
                for item in neighbors
            ],
            decision=decision,
            metadata={
                "probabilities": {key: round(value, 4) for key, value in by_label.items()},
                "embedding_model": self.artifact.embedding_model,
                "train_dataset_sha256": self.artifact.train_dataset_sha256,
                "nearest_neighbors": neighbors,
            },
        )
