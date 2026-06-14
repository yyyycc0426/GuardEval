import argparse
import json
from pathlib import Path

from llm_security_platform.real_model_ablation import FULL_DEFENSE


MODELS = ("qwen3:8b", "qwen3.6:latest")
STRATEGIES = ("none", "rag_defense", FULL_DEFENSE)
REQUIRED_METRICS = (
    "raw_model_compromise_rate",
    "delivered_attack_success_rate",
    "rag_leakage_asr",
    "normal_task_success_rate",
    "false_positive_rate",
    "p95_latency_ms",
    "failed_cases",
)


def check(report: dict) -> dict:
    failures = []
    for model in MODELS:
        for strategy in STRATEGIES:
            summary = (
                report.get("results", {})
                .get(model, {})
                .get(strategy, {})
                .get("summary", {})
            )
            if summary.get("valid_runs", 0) < 3:
                failures.append(f"{model}/{strategy} requires three valid runs")
            for metric in REQUIRED_METRICS:
                values = summary.get(metric)
                if not values or any(key not in values for key in ("mean", "min", "max")):
                    failures.append(f"{model}/{strategy} missing {metric} mean/min/max")

            blocked = summary.get("blocked_ratio") or {}
            if blocked.get("mean", 0) >= 0.95:
                failures.append(f"{model}/{strategy} appears to block nearly all cases")

    return {"status": "passed" if not failures else "failed", "failures": failures}


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate the repeated key real-model experiment")
    parser.add_argument(
        "--report",
        default="llm_security_platform/reports/stage_4_5_key_repeated_3x.json",
    )
    args = parser.parse_args()
    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    result = check(report)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] == "passed" else 1)


if __name__ == "__main__":
    main()
