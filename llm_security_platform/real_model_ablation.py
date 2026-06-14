import json
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean

from llm_security_platform.app import db
from llm_security_platform.app.dataset import load_dataset
from llm_security_platform.app.evaluator import execute_run
from llm_security_platform.app.providers import build_provider
from llm_security_platform.app.schemas import EvaluationRunCreate
from llm_security_platform.app.seed import DEFAULT_CASES_PATH, seed_cases


MODELS = ["qwen3:8b", "qwen3.6:latest"]
STRATEGIES = [
    "none",
    "baseline",
    "input_defense",
    "rag_defense",
    "output_defense",
    "input_defense+rag_defense+output_defense",
]
CORE_STRATEGIES = ["none", "baseline", "input_defense+rag_defense+output_defense"]
FULL_DEFENSE = "input_defense+rag_defense+output_defense"
METRIC_KEYS = [
    "attack_success_rate",
    "raw_model_compromise_rate",
    "delivered_attack_success_rate",
    "rag_leakage_asr",
    "prompt_injection_asr",
    "jailbreak_asr",
    "false_positive_rate",
    "normal_task_success_rate",
    "blocked_ratio",
    "review_rate",
    "p50_latency_ms",
    "p95_latency_ms",
    "total_tokens",
    "estimated_total_cost",
    "failed_cases",
]


def compact_report(report, expected_case_count=64):
    by_risk = report.by_risk_type
    return {
        "run_id": report.run_id,
        "status": report.status,
        "total_cases": report.total_cases,
        "attack_success_rate": report.attack_success_rate,
        "raw_model_compromise_rate": getattr(
            report, "raw_model_compromise_rate", report.attack_success_rate
        ),
        "delivered_attack_success_rate": getattr(
            report, "delivered_attack_success_rate", report.attack_success_rate
        ),
        "rag_leakage_asr": by_risk.get("rag_data_leakage", {}).get("attack_success_rate", 0.0),
        "prompt_injection_asr": by_risk.get("prompt_injection", {}).get("attack_success_rate", 0.0),
        "jailbreak_asr": by_risk.get("jailbreak", {}).get("attack_success_rate", 0.0),
        "false_positive_rate": report.false_positive_rate,
        "normal_task_success_rate": report.normal_task_success_rate,
        "blocked_ratio": round(report.blocked_cases / report.total_cases, 4) if report.total_cases else 0.0,
        "blocked_cases": report.blocked_cases,
        "review_rate": report.review_rate,
        "p50_latency_ms": report.p50_latency_ms,
        "p95_latency_ms": report.p95_latency_ms,
        "total_tokens": report.total_tokens,
        "estimated_total_cost": report.estimated_total_cost,
        "failed_cases": report.failed_cases,
        "defense_action_counts": report.defense_action_counts,
        "by_risk_type": report.by_risk_type,
        "run_metadata": report.run_metadata,
        "valid": report.failed_cases == 0 and report.total_cases == expected_case_count,
    }


def aggregate(runs):
    valid = [item for item in runs if item.get("valid")]
    summary = {"valid_runs": len(valid), "total_runs": len(runs)}
    for key in METRIC_KEYS:
        values = [float(item[key]) for item in valid if item.get(key) is not None]
        summary[key] = {
            "mean": round(mean(values), 4),
            "min": round(min(values), 4),
            "max": round(max(values), 4),
        } if values else None
    return summary


def _legacy_run(item):
    converted = dict(item)
    by_risk = converted.get("by_risk_type", {})
    stored_results = db.list_results(converted["run_id"]) if converted.get("run_id") else []

    def historical_asr(risk_type):
        items = [
            result for result in stored_results
            if result["risk_type"] == risk_type and result["status"] != "failed"
        ]
        if not items:
            return None
        return round(sum(result["detector"]["attack_success"] for result in items) / len(items), 4)

    converted.setdefault(
        "prompt_injection_asr",
        by_risk.get("prompt_injection", {}).get("attack_success_rate", historical_asr("prompt_injection")),
    )
    converted.setdefault(
        "jailbreak_asr",
        by_risk.get("jailbreak", {}).get("attack_success_rate", historical_asr("jailbreak")),
    )
    converted.setdefault("blocked_ratio", round(converted.get("blocked_cases", 0) / 64, 4))
    converted["valid"] = converted.get("failed_cases") == 0 and converted.get("total_cases") == 64
    return converted


def _backfill_dual_asr(item):
    converted = dict(item)
    stored_results = db.list_results(converted["run_id"]) if converted.get("run_id") else []
    cases = {case["case_id"]: case for case in db.list_attack_cases()}
    attacks = [result for result in stored_results if result["risk_type"] != "benign" and result["status"] != "failed"]
    if attacks:
        from llm_security_platform.app.detectors import evaluate_response

        raw_successes = sum(
            evaluate_response(
                cases[result["case_id"]],
                result.get("raw_response_text") or result.get("response_text", ""),
            ).attack_success
            for result in attacks
        )
        converted["raw_model_compromise_rate"] = round(raw_successes / len(attacks), 4)
        converted["delivered_attack_success_rate"] = converted.get("attack_success_rate", 0.0)
    else:
        converted.setdefault("raw_model_compromise_rate", converted.get("attack_success_rate", 0.0))
        converted.setdefault("delivered_attack_success_rate", converted.get("attack_success_rate", 0.0))
    return converted


def load_report(
    path,
    *,
    dataset_version="attackset_v2_frozen_64",
    case_count=64,
    experiment_version="stage_4_5_v2",
    models=None,
    strategies=None,
):
    if not path.is_file():
        return {
            "experiment": "stage_4_5_real_model_ablation",
            "experiment_version": experiment_version,
            "dataset_version": dataset_version,
            "case_count": case_count,
            "models": list(models or MODELS),
            "strategies": list(strategies or STRATEGIES),
            "started_at": datetime.now(UTC).isoformat(),
            "results": {},
        }
    report = json.loads(path.read_text(encoding="utf-8"))
    stored_dataset = report.get("dataset_version")
    if stored_dataset and stored_dataset != dataset_version:
        raise ValueError(
            f"Output already contains dataset {stored_dataset}; use a new output file "
            f"for {dataset_version}."
        )
    for model, strategies in report.get("results", {}).items():
        for strategy, value in list(strategies.items()):
            if "runs" not in value:
                run = _backfill_dual_asr(_legacy_run(value))
                strategies[strategy] = {"runs": [run], "summary": aggregate([run])}
            else:
                value["runs"] = [_backfill_dual_asr(run) for run in value["runs"]]
                value["summary"] = aggregate(value["runs"])
    report["experiment"] = "stage_4_5_real_model_ablation"
    report["experiment_version"] = experiment_version
    report["dataset_version"] = dataset_version
    report["case_count"] = case_count
    report["models"] = sorted(set(report.get("models", [])) | set(models or MODELS))
    report["strategies"] = [
        strategy
        for strategy in STRATEGIES
        if strategy in set(report.get("strategies", [])) | set(strategies or STRATEGIES)
    ]
    return report


def save_report(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    report["updated_at"] = datetime.now(UTC).isoformat()
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _warm_model(model, inference_config, calls):
    provider = build_provider("ollama", model, inference_config)
    for index in range(calls):
        print(f"[warmup] model={model} call={index + 1}/{calls}", flush=True)
        provider.generate(
            "You are a concise health-check assistant.",
            "Reply with exactly OK.",
        )


def run_ablation(
    output,
    models=None,
    strategies=None,
    repeats=1,
    max_tokens=32,
    timeout=180,
    dataset_path=None,
    dataset_version=None,
    warmup_calls=0,
):
    output = Path(output)
    selected_models = list(models or MODELS)
    selected_strategies = list(strategies or STRATEGIES)
    selected_dataset_path = Path(dataset_path or DEFAULT_CASES_PATH)
    db.init_db()
    seed_cases(selected_dataset_path)
    cases = load_dataset(selected_dataset_path)
    case_ids = [case["case_id"] for case in cases]
    if len(case_ids) != 64:
        raise ValueError(f"Frozen benchmark must contain 64 cases, got {len(case_ids)}")
    source_dataset_version = (
        cases[0].get("metadata", {}).get("dataset_version")
        or selected_dataset_path.stem
    )
    inferred_dataset_version = dataset_version or (
        "attackset_v2_frozen_64"
        if source_dataset_version == "attackset_v2"
        else source_dataset_version
    )
    experiment_version = (
        "stage_4_5_v3" if "v3" in inferred_dataset_version else "stage_4_5_v2"
    )
    report = load_report(
        output,
        dataset_version=inferred_dataset_version,
        case_count=len(case_ids),
        experiment_version=experiment_version,
        models=selected_models,
        strategies=selected_strategies,
    )
    report["methodology"] = {
        "warmup_calls": warmup_calls,
        "strategy_schedule": "round_robin_rotated",
        "temperature": 0,
        "seed": 42,
        "max_tokens": max_tokens,
        "timeout_seconds": timeout,
    }
    inference_config = {
        "temperature": 0,
        "top_p": 1,
        "seed": 42,
        "max_tokens": max_tokens,
        "timeout_seconds": timeout,
        "reasoning": False,
    }
    for model in selected_models:
        model_results = report["results"].setdefault(model, {})
        pending = any(
            sum(item.get("valid") for item in model_results.get(strategy, {}).get("runs", []))
            < repeats
            for strategy in selected_strategies
        )
        if pending and warmup_calls:
            _warm_model(model, inference_config, warmup_calls)
        for repeat_index in range(repeats):
            offset = repeat_index % len(selected_strategies)
            ordered_strategies = (
                selected_strategies[offset:] + selected_strategies[:offset]
            )
            for strategy in ordered_strategies:
                entry = model_results.setdefault(strategy, {"runs": [], "summary": {}})
                valid_count = sum(item.get("valid") for item in entry["runs"])
                if valid_count > repeat_index:
                    continue
                print(
                    f"[run] model={model} strategy={strategy} "
                    f"repeat={repeat_index + 1}/{repeats}",
                    flush=True,
                )
                evaluation = execute_run(EvaluationRunCreate(
                    name=(
                        f"{experiment_version}-{model}-{strategy}-r{repeat_index + 1}"
                    ),
                    provider="ollama",
                    model=model,
                    defense_policy=strategy,
                    case_ids=case_ids,
                    versions={
                        "dataset_version": inferred_dataset_version,
                        "policy_version": "defense_suite_v1",
                        "experiment_version": experiment_version,
                    },
                    inference_config=inference_config,
                ))
                result = compact_report(evaluation, expected_case_count=len(case_ids))
                entry["runs"].append(result)
                entry["summary"] = aggregate(entry["runs"])
                save_report(output, report)
                print(
                    f"[done] model={model} strategy={strategy} "
                    f"repeat={repeat_index + 1}/{repeats} "
                    f"raw_asr={result['raw_model_compromise_rate']:.4f} "
                    f"delivered_asr={result['delivered_attack_success_rate']:.4f} "
                    f"rag_asr={result['rag_leakage_asr']:.4f} "
                    f"p95_ms={result['p95_latency_ms']:.2f}",
                    flush=True,
                )
        for strategy in selected_strategies:
            entry = model_results.setdefault(strategy, {"runs": [], "summary": {}})
            entry["summary"] = aggregate(entry["runs"])
    report["completed_at"] = datetime.now(UTC).isoformat()
    save_report(output, report)
    return report
