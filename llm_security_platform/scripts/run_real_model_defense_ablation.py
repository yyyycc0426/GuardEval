import argparse
import json
from pathlib import Path

from llm_security_platform.real_model_ablation import MODELS, STRATEGIES, run_ablation


def main():
    parser = argparse.ArgumentParser(description="Run stage 4.5 real-model defense ablation")
    parser.add_argument("--model", action="append", choices=MODELS, default=[])
    parser.add_argument("--strategy", action="append", choices=STRATEGIES, default=[])
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--max-tokens", type=int, default=32)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument(
        "--dataset",
        default="llm_security_platform/data/attack_cases_v2.json",
    )
    parser.add_argument("--dataset-version")
    parser.add_argument("--warmup-calls", type=int, default=2)
    parser.add_argument(
        "--output",
        default="llm_security_platform/reports/stage_4_5_real_model_ablation.json",
    )
    args = parser.parse_args()
    report = run_ablation(
        Path(args.output), models=args.model or None, strategies=args.strategy or None,
        repeats=args.repeats, max_tokens=args.max_tokens, timeout=args.timeout,
        dataset_path=Path(args.dataset), dataset_version=args.dataset_version,
        warmup_calls=args.warmup_calls,
    )
    print(json.dumps({
        model: {strategy: value["summary"] for strategy, value in strategies.items()}
        for model, strategies in report["results"].items()
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
