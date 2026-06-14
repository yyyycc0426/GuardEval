import argparse
import json
from pathlib import Path

from llm_security_platform.real_model_ablation import FULL_DEFENSE


def valid_summary(report, model, strategy):
    return report.get("results", {}).get(model, {}).get(strategy, {}).get("summary", {})


def check(report):
    failures = []
    results = report.get("results", {})
    core = ("none", "baseline", FULL_DEFENSE)
    qualifying_models = []
    for model in ("qwen3:8b", "qwen3.6:latest"):
        if all(valid_summary(report, model, strategy).get("valid_runs", 0) >= 1 for strategy in core):
            qualifying_models.append(model)
    if len(qualifying_models) < 2:
        failures.append("two real models must complete valid none/baseline/full_defense runs")

    repeated = ("none", "rag_defense", FULL_DEFENSE)
    for model in ("qwen3:8b", "qwen3.6:latest"):
        for strategy in repeated:
            summary = valid_summary(report, model, strategy)
            if summary.get("valid_runs", 0) < 3:
                failures.append(f"{model}/{strategy} must have at least three valid runs")
            for metric in ("raw_model_compromise_rate", "delivered_attack_success_rate"):
                if summary.get(metric) is None:
                    failures.append(f"{model}/{strategy} missing {metric}")

    singles = ("input_defense", "rag_defense", "output_defense")
    single_model = next((
        model for model in results
        if all(valid_summary(report, model, strategy).get("valid_runs", 0) >= 1 for strategy in singles)
    ), None)
    if single_model is None:
        failures.append("at least one model must complete all three single-defense runs")
    else:
        none = valid_summary(report, single_model, "none").get("rag_leakage_asr")
        rag = valid_summary(report, single_model, "rag_defense").get("rag_leakage_asr")
        if none is None or rag is None:
            failures.append("rag_defense must expose an independently measurable RAG leakage result")

    for model, strategies in results.items():
        for strategy, entry in strategies.items():
            for run in entry.get("runs", []):
                if not run.get("valid"):
                    continue
                metadata = run.get("run_metadata", {})
                versions = metadata.get("versions", {})
                for key in ("dataset_version", "policy_version", "experiment_version"):
                    if not versions.get(key):
                        failures.append(f"{model}/{strategy} missing {key}")
                for key in ("code_commit_hash", "run_config_hash", "model_config"):
                    if not metadata.get(key):
                        failures.append(f"{model}/{strategy} missing {key}")
                if run.get("blocked_ratio", 0) >= 0.95:
                    failures.append(f"{model}/{strategy} appears to reduce ASR by blocking everything")
    return {"status": "passed" if not failures else "failed", "failures": sorted(set(failures))}


def main():
    parser = argparse.ArgumentParser(description="Validate stage 4.5 real-model ablation")
    parser.add_argument(
        "--report",
        default="llm_security_platform/reports/stage_4_5_real_model_ablation.json",
    )
    args = parser.parse_args()
    result = check(json.loads(Path(args.report).read_text(encoding="utf-8")))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] == "passed" else 1)


if __name__ == "__main__":
    main()
