import argparse
import hashlib
import json
from pathlib import Path

from llm_security_platform.app.semantic_classifier import SemanticRiskClassifier


ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description="Train the stage-three semantic risk classifier.")
    parser.add_argument(
        "--dataset",
        default=str(ROOT / "data" / "attack_cases_v3_train.json"),
    )
    parser.add_argument(
        "--output",
        default=str(ROOT / "artifacts" / "semantic_classifier_v1.joblib"),
    )
    args = parser.parse_args()
    cases = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
    classifier = SemanticRiskClassifier.train(
        cases,
        train_dataset_sha256=hashlib.sha256(Path(args.dataset).read_bytes()).hexdigest(),
    )
    classifier.save(args.output)
    print(
        json.dumps(
            {
                "output": args.output,
                "train_cases": len(cases),
                "detector_version": classifier.artifact.detector_version,
                "embedding_model": classifier.artifact.embedding_model,
                "train_dataset_sha256": classifier.artifact.train_dataset_sha256,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
