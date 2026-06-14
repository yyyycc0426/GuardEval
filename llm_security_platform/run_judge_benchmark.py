import argparse
import json
from pathlib import Path
from time import perf_counter

from sklearn.metrics import accuracy_score, precision_recall_fscore_support

from llm_security_platform.app.judge import LLMJudge, RuleBackedJudge
from llm_security_platform.app.providers import build_provider


ROOT = Path(__file__).resolve().parent


def run(cases, judge, response_rule_judge=None):
    expected = []
    predicted = []
    outcome_hits = 0
    evidence_valid = 0
    successful_with_evidence = 0
    reviews = 0
    details = []
    baseline_predictions = []
    started = perf_counter()
    for case in cases:
        decision = judge.evaluate(case, case["model_response"])
        expected.append(case["gold_attack_success"])
        predicted.append(decision.attack_success)
        if response_rule_judge:
            baseline_predictions.append(
                response_rule_judge.evaluate(case, case["model_response"]).attack_success
            )
        outcome_hits += decision.outcome == case["gold_outcome"]
        if decision.attack_success:
            successful_with_evidence += bool(decision.evidence_quotes)
        evidence_valid += all(quote in case["model_response"] for quote in decision.evidence_quotes)
        reviews += decision.needs_human_review
        details.append(
            {
                "case_id": case["case_id"],
                "gold_attack_success": case["gold_attack_success"],
                "gold_outcome": case["gold_outcome"],
                "decision": decision.model_dump(exclude={"raw_response"}),
            }
        )
    precision, recall, f1, _ = precision_recall_fscore_support(
        expected, predicted, average="binary", zero_division=0
    )
    report = {
        "case_count": len(cases),
        "attack_success_accuracy": round(float(accuracy_score(expected, predicted)), 4),
        "attack_success_precision": round(float(precision), 4),
        "attack_success_recall": round(float(recall), 4),
        "attack_success_f1": round(float(f1), 4),
        "false_positive_rate": round(
            sum(not gold and pred for gold, pred in zip(expected, predicted, strict=True))
            / max(1, sum(not gold for gold in expected)),
            4,
        ),
        "false_negative_rate": round(
            sum(gold and not pred for gold, pred in zip(expected, predicted, strict=True))
            / max(1, sum(expected)),
            4,
        ),
        "judge_human_attack_success_agreement": round(float(accuracy_score(expected, predicted)), 4),
        "judge_human_outcome_agreement": round(outcome_hits / len(cases), 4),
        "outcome_exact_match": round(outcome_hits / len(cases), 4),
        "evidence_quote_validity": round(evidence_valid / len(cases), 4),
        "successful_decision_evidence_coverage": round(
            successful_with_evidence / max(1, sum(predicted)), 4
        ),
        "human_review_rate": round(reviews / len(cases), 4),
        "average_latency_ms": round((perf_counter() - started) * 1000 / len(cases), 2),
        "details": details,
    }
    if response_rule_judge:
        judge_correct = [gold == pred for gold, pred in zip(expected, predicted, strict=True)]
        rule_correct = [
            gold == pred for gold, pred in zip(expected, baseline_predictions, strict=True)
        ]
        report["independent_contribution"] = {
            "both_correct": sum(judge and rule for judge, rule in zip(judge_correct, rule_correct, strict=True)),
            "judge_only_correct": sum(judge and not rule for judge, rule in zip(judge_correct, rule_correct, strict=True)),
            "response_rule_only_correct": sum(rule and not judge for judge, rule in zip(judge_correct, rule_correct, strict=True)),
            "neither_correct": sum(not judge and not rule for judge, rule in zip(judge_correct, rule_correct, strict=True)),
        }
    return report


def main():
    parser = argparse.ArgumentParser(description="Benchmark the response-security judge.")
    parser.add_argument("--provider", choices=["mock", "ollama", "openai_compatible"], default="mock")
    parser.add_argument("--model", default=None)
    parser.add_argument("--dataset", default=str(ROOT / "data" / "judge_eval_cases_v1.json"))
    parser.add_argument("--output", default=str(ROOT / "reports" / "stage_three_judge_benchmark.json"))
    args = parser.parse_args()
    cases = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
    if args.provider == "mock":
        judge = RuleBackedJudge()
    else:
        provider = build_provider(
            args.provider,
            args.model,
            {"temperature": 0, "top_p": 1, "seed": 42, "max_tokens": 256, "timeout_seconds": 180, "reasoning": False},
        )
        judge = LLMJudge(provider)
    report = {
        "dataset_version": "judge_eval_v1",
        "provider": args.provider,
        "model": args.model,
        **run(cases, judge, response_rule_judge=RuleBackedJudge()),
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "details"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
