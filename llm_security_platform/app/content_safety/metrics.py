"""Classification metrics for the content-safety track.

Mirrors the structure of ``run_detection_benchmark.metric_block`` so the JSON
reports look consistent across the platform: accuracy, macro/weighted P-R-F1,
per-class breakdown, and a confusion matrix. A binary toxic/non-toxic view is
also reported (toxic = hatespeech or offensive), echoing the attack/benign
binary split used elsewhere.
"""

from __future__ import annotations

from sklearn.metrics import accuracy_score, classification_report, confusion_matrix

from llm_security_platform.app.content_safety.hatexplain_loader import (
    LABELS,
    TOXIC_LABELS,
)


def _round(value: float) -> float:
    return round(float(value), 4)


def metric_block(expected: list[str], predicted: list[str], labels: list[str]) -> dict:
    report = classification_report(
        expected,
        predicted,
        labels=labels,
        output_dict=True,
        zero_division=0,
    )
    return {
        "accuracy": _round(accuracy_score(expected, predicted)),
        "macro_precision": _round(report["macro avg"]["precision"]),
        "macro_recall": _round(report["macro avg"]["recall"]),
        "macro_f1": _round(report["macro avg"]["f1-score"]),
        "weighted_f1": _round(report["weighted avg"]["f1-score"]),
        "per_class": {
            label: {
                "precision": _round(report[label]["precision"]),
                "recall": _round(report[label]["recall"]),
                "f1": _round(report[label]["f1-score"]),
                "support": int(report[label]["support"]),
            }
            for label in labels
        },
        "confusion_matrix": {
            "labels": labels,
            "matrix": confusion_matrix(expected, predicted, labels=labels).tolist(),
        },
    }


def _to_toxic(label: str) -> str:
    return "non-toxic" if label == "normal" else "toxic"


def classification_metrics(expected: list[str], predicted: list[str]) -> dict:
    """Full content-safety metric payload: 3-class and binary toxic views."""
    toxic_expected = [_to_toxic(label) for label in expected]
    toxic_predicted = [_to_toxic(label) for label in predicted]
    return {
        "sample_count": len(expected),
        "three_class": metric_block(expected, predicted, LABELS),
        "binary_toxic": metric_block(toxic_expected, toxic_predicted, TOXIC_LABELS),
    }
