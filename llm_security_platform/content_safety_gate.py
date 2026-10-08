"""Quality gate for the content-safety (HateXplain) track.

Fails closed if the offline baseline regresses below an absolute macro-F1 floor
or fails to beat the majority-class baseline by a margin. Keeps the public
benchmark reproducible and guards against silently broken loading / training.
"""

from __future__ import annotations

import argparse
import json
import sys

from llm_security_platform.run_content_safety_benchmark import run_benchmark


def evaluate_gate(
    baseline_report: dict,
    majority_report: dict,
    minimum_macro_f1: float = 0.55,
    minimum_margin_over_majority: float = 0.2,
) -> list[str]:
    failures = []
    baseline_f1 = baseline_report["metrics"]["three_class"]["macro_f1"]
    majority_f1 = majority_report["metrics"]["three_class"]["macro_f1"]
    if baseline_f1 < minimum_macro_f1:
        failures.append(f"baseline macro_f1={baseline_f1} < {minimum_macro_f1}")
    margin = round(baseline_f1 - majority_f1, 4)
    if margin < minimum_margin_over_majority:
        failures.append(
            f"macro_f1 margin over majority={margin} < {minimum_margin_over_majority}"
        )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the content-safety quality gate.")
    parser.add_argument("--minimum-macro-f1", type=float, default=0.55)
    parser.add_argument("--minimum-margin-over-majority", type=float, default=0.2)
    args = parser.parse_args()

    baseline_report = run_benchmark("tfidf")
    majority_report = run_benchmark("majority")
    failures = evaluate_gate(
        baseline_report,
        majority_report,
        minimum_macro_f1=args.minimum_macro_f1,
        minimum_margin_over_majority=args.minimum_margin_over_majority,
    )
    summary = {
        "baseline_macro_f1": baseline_report["metrics"]["three_class"]["macro_f1"],
        "majority_macro_f1": majority_report["metrics"]["three_class"]["macro_f1"],
        "gate": {"status": "failed" if failures else "passed", "failures": failures},
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
