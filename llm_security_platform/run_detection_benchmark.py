import argparse
import hashlib
import json
from pathlib import Path
from time import perf_counter

from sklearn.metrics import accuracy_score, classification_report, confusion_matrix

from llm_security_platform.app.detectors import rule_detect_input
from llm_security_platform.app.semantic_classifier import SemanticRiskClassifier


ROOT = Path(__file__).resolve().parent
LABELS = ["benign", "prompt_injection", "jailbreak", "rag_data_leakage"]


def metric_block(expected, predicted):
    report = classification_report(
        expected,
        predicted,
        labels=LABELS,
        output_dict=True,
        zero_division=0,
    )
    expected_attack = [item != "benign" for item in expected]
    predicted_attack = [item != "benign" for item in predicted]
    tn, fp, fn, tp = confusion_matrix(
        expected_attack,
        predicted_attack,
        labels=[False, True],
    ).ravel()
    return {
        "accuracy": round(float(accuracy_score(expected, predicted)), 4),
        "macro_precision": round(float(report["macro avg"]["precision"]), 4),
        "macro_recall": round(float(report["macro avg"]["recall"]), 4),
        "macro_f1": round(float(report["macro avg"]["f1-score"]), 4),
        "false_positive_rate": round(float(fp / (fp + tn)), 4) if fp + tn else 0.0,
        "false_negative_rate": round(float(fn / (fn + tp)), 4) if fn + tp else 0.0,
        "per_class": {
            label: {
                key: round(float(report[label][key]), 4)
                for key in ("precision", "recall", "f1-score")
            }
            for label in LABELS
        },
        "confusion_matrix": confusion_matrix(expected, predicted, labels=LABELS).tolist(),
    }


def run_benchmark(dataset_path, model_path):
    cases = json.loads(Path(dataset_path).read_text(encoding="utf-8"))
    classifier = SemanticRiskClassifier.load(model_path)
    expected = []
    rule_predictions = []
    semantic_predictions = []
    fused_predictions = []
    conflicts = []
    started = perf_counter()
    for case in cases:
        rule = rule_detect_input(case["prompt"])
        semantic = classifier.predict(case["prompt"])
        expected.append(case["risk_type"])
        rule_predictions.append(rule.risk_type)
        semantic_predictions.append(semantic.risk_type)
        if rule.risk_type == "benign" and semantic.risk_type != "benign":
            fused = semantic.risk_type
        elif rule.risk_type != "benign":
            fused = rule.risk_type
        else:
            fused = semantic.risk_type
        fused_predictions.append(fused)
        if rule.risk_type != semantic.risk_type:
            conflicts.append(
                {
                    "case_id": case["case_id"],
                    "expected": case["risk_type"],
                    "rule": rule.risk_type,
                    "semantic": semantic.risk_type,
                    "rule_confidence": rule.confidence,
                    "semantic_confidence": semantic.confidence,
                }
            )
    elapsed_ms = (perf_counter() - started) * 1000
    rule_correct = [expected[index] == value for index, value in enumerate(rule_predictions)]
    semantic_correct = [expected[index] == value for index, value in enumerate(semantic_predictions)]
    contributions = {
        "both_correct": sum(rule and semantic for rule, semantic in zip(rule_correct, semantic_correct, strict=True)),
        "rule_only_correct": sum(rule and not semantic for rule, semantic in zip(rule_correct, semantic_correct, strict=True)),
        "semantic_only_correct": sum(semantic and not rule for rule, semantic in zip(rule_correct, semantic_correct, strict=True)),
        "neither_correct": sum(not rule and not semantic for rule, semantic in zip(rule_correct, semantic_correct, strict=True)),
    }
    return {
        "dataset_version": "attackset_v2",
        "dataset_path": str(dataset_path),
        "case_count": len(cases),
        "frozen_dataset_sha256": hashlib.sha256(Path(dataset_path).read_bytes()).hexdigest(),
        "semantic_detector_version": classifier.artifact.detector_version,
        "embedding_model": classifier.artifact.embedding_model,
        "train_dataset_sha256": classifier.artifact.train_dataset_sha256,
        "average_pipeline_latency_ms": round(elapsed_ms / len(cases), 2),
        "rule_detector": metric_block(expected, rule_predictions),
        "semantic_classifier": metric_block(expected, semantic_predictions),
        "rule_first_fusion": metric_block(expected, fused_predictions),
        "conflict_count": len(conflicts),
        "conflict_rate": round(len(conflicts) / len(cases), 4),
        "independent_contribution": contributions,
        "conflicts": conflicts,
    }


def main():
    parser = argparse.ArgumentParser(description="Benchmark layered input-risk detectors.")
    parser.add_argument("--dataset", default=str(ROOT / "data" / "attack_cases_v2.json"))
    parser.add_argument(
        "--model",
        default=str(ROOT / "artifacts" / "semantic_classifier_v1.joblib"),
    )
    parser.add_argument(
        "--output",
        default=str(ROOT / "reports" / "stage_three_detection_benchmark.json"),
    )
    args = parser.parse_args()
    report = run_benchmark(args.dataset, args.model)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "conflicts"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
