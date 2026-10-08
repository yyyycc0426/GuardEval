"""Content-safety benchmark runner (HateXplain).

Calibrates a classifier under test against the public, human-labeled HateXplain
benchmark and writes a reproducible JSON report (accuracy / macro-F1 /
confusion matrix, 3-class and binary-toxic views).

This is a *content classification* benchmark, separate from the attack/defense
ASR pipeline. Example:

    python -m llm_security_platform.run_content_safety_benchmark
    python -m llm_security_platform.run_content_safety_benchmark --classifier majority
    python -m llm_security_platform.run_content_safety_benchmark \
        --classifier llm --provider mock --limit 200
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path
from time import perf_counter

from llm_security_platform.app.content_safety.classifiers import ERROR_LABEL, build_classifier
from llm_security_platform.app.content_safety.hatexplain_loader import (
    DEFAULT_DATASET_PATH,
    DEFAULT_SPLITS_PATH,
    LABELS,
    label_distribution,
    load_records,
    split_records,
)
from llm_security_platform.app.content_safety.metrics import classification_metrics

ROOT = Path(__file__).resolve().parent


def run_benchmark(
    classifier_name: str,
    dataset_path: str | Path = DEFAULT_DATASET_PATH,
    splits_path: str | Path = DEFAULT_SPLITS_PATH,
    provider: str = "mock",
    model: str | None = None,
    limit: int | None = None,
    sample_per_class: int | None = None,
    seed: int = 20260628,
    request_delay: float = 0.0,
) -> dict:
    records = load_records(dataset_path, splits_path)
    grouped = split_records(records)
    train = grouped.get("train", [])
    test = grouped.get("test", [])
    if not test:
        raise RuntimeError("no test-split records found; check post_id_divisions.json")

    sampling = "full"
    if sample_per_class:
        rng = random.Random(seed)
        balanced = []
        for label in LABELS:
            pool = [record for record in test if record.gold_label == label]
            rng.shuffle(pool)
            balanced.extend(pool[:sample_per_class])
        rng.shuffle(balanced)
        test = balanced
        sampling = f"stratified_{sample_per_class}_per_class_seed_{seed}"
    elif limit:
        test = test[:limit]
        sampling = f"first_{limit}"

    classifier = build_classifier(
        classifier_name, provider=provider, model=model, request_delay=request_delay
    )
    classifier.fit(train)

    started = perf_counter()
    raw_predicted = classifier.predict_batch([record.text for record in test])
    elapsed_ms = (perf_counter() - started) * 1000
    raw_expected = [record.gold_label for record in test]

    # Exclude failed calls (rate limit / timeout) from metrics — a failed call
    # is not a prediction and must not be counted as a real label.
    expected, predicted = [], []
    error_count = 0
    for gold, pred in zip(raw_expected, raw_predicted, strict=True):
        if pred == ERROR_LABEL:
            error_count += 1
            continue
        expected.append(gold)
        predicted.append(pred)
    if not expected:
        raise RuntimeError(f"all {len(test)} calls failed; check provider/quota")

    metrics = classification_metrics(expected, predicted)
    return {
        "dataset": "hatexplain",
        "dataset_path": str(dataset_path),
        "dataset_sha256": hashlib.sha256(Path(dataset_path).read_bytes()).hexdigest(),
        "splits": {name: len(items) for name, items in grouped.items()},
        "train_label_distribution": label_distribution(train),
        "test_label_distribution": label_distribution(test),
        "classifier": classifier.name,
        "classifier_version": classifier.version,
        "provider": provider if classifier_name == "llm" else None,
        "sampling": sampling,
        "sampled_count": len(test),
        "error_count": error_count,
        "evaluated_count": len(expected),
        "average_inference_latency_ms": round(elapsed_ms / len(test), 3),
        "metrics": metrics,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark a classifier against the HateXplain content-safety dataset."
    )
    parser.add_argument(
        "--classifier",
        default="tfidf",
        help="tfidf (default, offline) | majority | llm",
    )
    parser.add_argument(
        "--provider",
        choices=["mock", "ollama", "openai_compatible", "gemini", "vertexai"],
        default="mock",
        help="target provider when --classifier llm",
    )
    parser.add_argument("--model", default=None)
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET_PATH))
    parser.add_argument("--splits", default=str(DEFAULT_SPLITS_PATH))
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="evaluate only the first N test posts (useful for the llm path)",
    )
    parser.add_argument(
        "--sample-per-class",
        type=int,
        default=None,
        help="seeded stratified sample of N posts per class (overrides --limit)",
    )
    parser.add_argument("--seed", type=int, default=20260628)
    parser.add_argument(
        "--request-delay",
        type=float,
        default=0.0,
        help="seconds to pace between LLM calls (helps stay under API quota)",
    )
    parser.add_argument(
        "--output",
        default=str(ROOT / "reports" / "content_safety_hatexplain.json"),
    )
    args = parser.parse_args()

    report = run_benchmark(
        args.classifier,
        dataset_path=args.dataset,
        splits_path=args.splits,
        provider=args.provider,
        model=args.model,
        limit=args.limit,
        sample_per_class=args.sample_per_class,
        seed=args.seed,
        request_delay=args.request_delay,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
