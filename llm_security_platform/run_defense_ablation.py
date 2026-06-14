import argparse
import json
from pathlib import Path

from llm_security_platform.app import db
from llm_security_platform.app.dataset import load_dataset
from llm_security_platform.app.evaluator import execute_run
from llm_security_platform.app.schemas import EvaluationRunCreate, default_inference_config
from llm_security_platform.app.seed import DEFAULT_CASES_PATH, seed_cases


ROOT = Path(__file__).resolve().parent
STRATEGIES = [
    "none",
    "baseline",
    "input_defense",
    "rag_defense",
    "output_defense",
    "input_defense+rag_defense",
    "input_defense+output_defense",
    "rag_defense+output_defense",
    "input_defense+rag_defense+output_defense",
]


def successful_attack_ids(run_id):
    return {
        item["case_id"]
        for item in db.list_results(run_id)
        if item["risk_type"] != "benign" and item["detector"]["attack_success"]
    }


def run_ablation(provider="mock", model=None):
    db.init_db()
    seed_cases()
    case_ids = [case["case_id"] for case in load_dataset(DEFAULT_CASES_PATH)]
    reports = {}
    success_sets = {}
    for strategy in STRATEGIES:
        report = execute_run(
            EvaluationRunCreate(
                name=f"stage-four-ablation-{strategy}",
                provider=provider,
                model=model,
                defense_policy=strategy,
                case_ids=case_ids,
                versions={"policy_version": "defense_suite_v1"},
                inference_config=default_inference_config(),
            )
        )
        payload = report.model_dump()
        payload["blocked_ratio"] = round(report.blocked_cases / report.total_cases, 4)
        payload["policy_intervention_count"] = sum(
            count
            for action, count in report.defense_action_counts.items()
            if action != "allow"
        )
        audits = db.list_defense_audits(report.run_id)
        payload["audit_count"] = len(audits)
        payload["audit_evidence_coverage"] = round(
            sum(bool(item["decision"].get("evidence")) for item in audits) / len(audits),
            4,
        ) if audits else 1.0
        reports[strategy] = payload
        success_sets[strategy] = successful_attack_ids(report.run_id)

    baseline_success = success_sets["none"]
    prevented = {
        strategy: sorted(baseline_success - successes)
        for strategy, successes in success_sets.items()
        if strategy != "none"
    }
    singles = ("input_defense", "rag_defense", "output_defense")
    independent = {}
    for strategy in singles:
        others = set().union(*(set(prevented[item]) for item in singles if item != strategy))
        independent[strategy] = sorted(set(prevented[strategy]) - others)

    for strategy, report in reports.items():
        report["asr_reduction_vs_none"] = round(
            reports["none"]["attack_success_rate"] - report["attack_success_rate"],
            4,
        )
        if "+" in strategy:
            components = strategy.split("+")
            best_component_asr = min(reports[item]["attack_success_rate"] for item in components)
            report["stacking_gain_vs_best_component"] = round(
                best_component_asr - report["attack_success_rate"],
                4,
            )

    return {
        "dataset_version": "attackset_v2",
        "case_count": len(case_ids),
        "provider": provider,
        "model": model or ("mock-vulnerable-model" if provider == "mock" else "default"),
        "strategies": reports,
        "prevented_attack_ids": prevented,
        "independent_contribution": {
            strategy: {
                "unique_prevented_count": len(case_ids_for_strategy),
                "case_ids": case_ids_for_strategy,
            }
            for strategy, case_ids_for_strategy in independent.items()
        },
    }


def main():
    parser = argparse.ArgumentParser(description="Run stage-four defense ablation experiments.")
    parser.add_argument("--provider", choices=["mock", "ollama", "openai_compatible"], default="mock")
    parser.add_argument("--model", default=None)
    parser.add_argument(
        "--output",
        default=str(ROOT / "reports" / "stage_four_defense_ablation.json"),
    )
    args = parser.parse_args()
    report = run_ablation(args.provider, args.model)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {
        strategy: {
            key: values[key]
            for key in (
                "attack_success_rate",
                "false_positive_rate",
                "normal_task_success_rate",
                "p50_latency_ms",
                "p95_latency_ms",
                "total_tokens",
                "estimated_total_cost",
                "failed_cases",
                "review_rate",
                "blocked_ratio",
                "asr_reduction_vs_none",
            )
        }
        for strategy, values in report["strategies"].items()
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
