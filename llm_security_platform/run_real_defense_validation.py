import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from llm_security_platform.app import db
from llm_security_platform.app.dataset import load_dataset
from llm_security_platform.app.evaluator import execute_run
from llm_security_platform.app.schemas import EvaluationRunCreate
from llm_security_platform.app.seed import DEFAULT_CASES_PATH, seed_cases


ROOT = Path(__file__).resolve().parent
MODELS = ["qwen3:8b", "qwen3.6:latest"]
STRATEGIES = [
    "none",
    "baseline",
    "input_defense+rag_defense+output_defense",
]


def compact_report(report):
    rag_metrics = report.by_risk_type.get("rag_data_leakage", {})
    return {
        "run_id": report.run_id,
        "status": report.status,
        "total_cases": report.total_cases,
        "attack_success_rate": report.attack_success_rate,
        "rag_leakage_asr": rag_metrics.get("attack_success_rate", 0.0),
        "normal_task_success_rate": report.normal_task_success_rate,
        "false_positive_rate": report.false_positive_rate,
        "p50_latency_ms": report.p50_latency_ms,
        "p95_latency_ms": report.p95_latency_ms,
        "failed_cases": report.failed_cases,
        "total_tokens": report.total_tokens,
        "estimated_total_cost": report.estimated_total_cost,
        "review_rate": report.review_rate,
        "blocked_cases": report.blocked_cases,
        "defense_action_counts": report.defense_action_counts,
        "run_metadata": report.run_metadata,
    }


def load_or_initialize(path, resume):
    if resume and path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {
        "experiment": "stage_4_5_real_model_defense_validation",
        "dataset_version": "attackset_v2",
        "case_count": 64,
        "models": MODELS,
        "strategies": STRATEGIES,
        "started_at": datetime.now(UTC).isoformat(),
        "results": {},
    }


def save(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    report["updated_at"] = datetime.now(UTC).isoformat()
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(output_path, resume=False, models=None, strategies=None, max_tokens=32):
    db.init_db()
    seed_cases()
    case_ids = [case["case_id"] for case in load_dataset(DEFAULT_CASES_PATH)]
    output_path = Path(output_path)
    experiment = load_or_initialize(output_path, resume)
    selected_models = models or MODELS
    selected_strategies = strategies or STRATEGIES
    for model in selected_models:
        model_results = experiment["results"].setdefault(model, {})
        for strategy in selected_strategies:
            if resume and model_results.get(strategy, {}).get("status") in {
                "completed",
                "completed_with_errors",
            }:
                continue
            report = execute_run(
                EvaluationRunCreate(
                    name=f"stage-4.5-{model}-{strategy}",
                    provider="ollama",
                    model=model,
                    defense_policy=strategy,
                    case_ids=case_ids,
                    versions={
                        "dataset_version": "attackset_v2",
                        "policy_version": "defense_suite_v1",
                        "experiment_version": "stage_4_5_v1",
                    },
                    inference_config={
                        "temperature": 0,
                        "top_p": 1,
                        "seed": 42,
                        "max_tokens": max_tokens,
                        "timeout_seconds": 180,
                        "reasoning": False,
                    },
                )
            )
            model_results[strategy] = compact_report(report)
            save(output_path, experiment)
    experiment["completed_at"] = datetime.now(UTC).isoformat()
    save(output_path, experiment)
    return experiment


def main():
    parser = argparse.ArgumentParser(description="Run the stage 4.5 real-model defense validation.")
    parser.add_argument("--model", action="append", choices=MODELS, default=[])
    parser.add_argument("--strategy", action="append", choices=STRATEGIES, default=[])
    parser.add_argument("--max-tokens", type=int, default=32)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--output",
        default=str(ROOT / "reports" / "stage_4_5_real_model_defense.json"),
    )
    args = parser.parse_args()
    result = run(
        args.output,
        resume=args.resume,
        models=args.model or None,
        strategies=args.strategy or None,
        max_tokens=args.max_tokens,
    )
    summary = {
        model: {
            strategy: {
                key: values[key]
                for key in (
                    "attack_success_rate",
                    "rag_leakage_asr",
                    "normal_task_success_rate",
                    "false_positive_rate",
                    "p95_latency_ms",
                    "failed_cases",
                )
            }
            for strategy, values in strategies.items()
        }
        for model, strategies in result["results"].items()
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
