"""Rationale/explainability benchmark (HateXplain).

Scores whether the offline TF-IDF baseline's token-importance aligns with human
rationales — i.e. when it flags a post as toxic, does it look at the same words a
human annotator highlighted? Reports macro token-level precision / recall / F1 /
IoU over toxic-gold posts that carry a human rationale and that the model also
predicts as toxic.

Offline and deterministic (no API/quota). Example:

    python -m llm_security_platform.run_rationale_benchmark
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from llm_security_platform.app.content_safety.classifiers import TfidfLogRegBaseline
from llm_security_platform.app.content_safety.hatexplain_loader import (
    DEFAULT_DATASET_PATH,
    DEFAULT_SPLITS_PATH,
    load_records,
    split_records,
)
from llm_security_platform.app.content_safety.rationale import aggregate_rationale

ROOT = Path(__file__).resolve().parent
TOXIC = {"offensive", "hatespeech"}


def run_benchmark(
    dataset_path=DEFAULT_DATASET_PATH,
    splits_path=DEFAULT_SPLITS_PATH,
) -> dict:
    grouped = split_records(load_records(dataset_path, splits_path))
    train, test = grouped.get("train", []), grouped.get("test", [])

    model = TfidfLogRegBaseline().fit(train)

    pairs = []
    eligible = 0  # toxic gold with a human rationale
    correct_toxic = 0  # of those, model also predicted toxic
    for record in test:
        if record.gold_label not in TOXIC or not any(record.rationale_mask):
            continue
        eligible += 1
        predicted = model.predict(record.text)
        if predicted not in TOXIC:
            continue
        correct_toxic += 1
        pred_mask = model.explain_tokens(record.tokens, predicted)
        pairs.append((pred_mask, record.rationale_mask))

    metrics = aggregate_rationale(pairs)
    return {
        "dataset": "hatexplain",
        "dataset_sha256": hashlib.sha256(Path(dataset_path).read_bytes()).hexdigest(),
        "classifier": model.name,
        "classifier_version": model.version,
        "attribution": "linear_coefficient_token_contribution",
        "eligible_toxic_posts_with_rationale": eligible,
        "model_predicted_toxic": correct_toxic,
        "rationale_metrics": metrics,
        "note": (
            "Token-level overlap of model attribution vs human rationale, on "
            "toxic posts the model correctly flags. Offline/deterministic."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Rationale/explainability benchmark (HateXplain).")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET_PATH))
    parser.add_argument("--splits", default=str(DEFAULT_SPLITS_PATH))
    parser.add_argument(
        "--output", default=str(ROOT / "reports" / "content_safety_rationale.json")
    )
    args = parser.parse_args()
    report = run_benchmark(args.dataset, args.splits)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
