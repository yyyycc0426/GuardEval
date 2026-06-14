import argparse
import json
import random
from pathlib import Path

from llm_security_platform.app import db
from llm_security_platform.app.judge import RuleBackedJudge


def selected_results(ablation, safe_sample_rate, seed):
    selected = {}
    rng = random.Random(seed)
    for model, strategies in ablation["results"].items():
        for strategy, entry in strategies.items():
            for run in entry.get("runs", []):
                if not run.get("valid"):
                    continue
                for result in db.list_results(run["run_id"]):
                    attack_success = bool(result["detector"]["attack_success"])
                    output_intercept = strategy in {
                        "output_defense", "input_defense+rag_defense+output_defense"
                    } and any(
                        decision["policy_name"] == "output_defense"
                        and decision["action"] in {"redact", "rewrite", "review"}
                        for decision in result["defense_decisions"]
                    )
                    sampled_safe = not attack_success and not output_intercept and rng.random() < safe_sample_rate
                    if attack_success or output_intercept or sampled_safe:
                        key = (model, strategy, run["run_id"], result["case_id"])
                        selected[key] = (result, attack_success, output_intercept, sampled_safe)
    return selected


def main():
    parser = argparse.ArgumentParser(description="Build a human-review packet from real-model runs")
    parser.add_argument("--ablation", default="llm_security_platform/reports/stage_4_5_real_model_ablation.json")
    parser.add_argument("--output", default="llm_security_platform/reports/real_model_human_review_packet.json")
    parser.add_argument("--safe-sample-rate", type=float, default=0.10)
    parser.add_argument("--seed", type=int, default=9417)
    args = parser.parse_args()
    ablation = json.loads(Path(args.ablation).read_text(encoding="utf-8"))
    cases = {case["case_id"]: case for case in db.list_attack_cases()}
    items = []
    for (model, strategy, run_id, case_id), (result, success, intercepted, sampled) in selected_results(
        ablation, args.safe_sample_rate, args.seed
    ).items():
        case = cases[case_id]
        judge = RuleBackedJudge().evaluate(case, result.get("raw_response_text") or result["response_text"])
        items.append({
            "review_id": f"{run_id}:{case_id}",
            "model": model,
            "strategy": strategy,
            "run_id": run_id,
            "case_id": case_id,
            "selection_reason": {
                "delivered_attack_success": success,
                "output_defense_intercept": intercepted,
                "random_safe_sample": sampled,
            },
            "risk_type": case["risk_type"],
            "prompt": case["prompt"],
            "raw_model_response": result.get("raw_response_text", ""),
            "delivered_response": result["response_text"],
            "detector_result": result["detector"],
            "judge_result": judge.model_dump(),
            "human_final_label": None,
            "human_attack_success": None,
            "reviewer_note": None,
            "reviewer": None,
        })
    payload = {
        "status": "awaiting_human_review",
        "selection_policy": "all delivered successes + all output-defense interceptions + 10% seeded safe sample",
        "item_count": len(items),
        "items": items,
    }
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": args.output, "item_count": len(items)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
