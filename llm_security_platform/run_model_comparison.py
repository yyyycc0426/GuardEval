import argparse
import json
from pathlib import Path

from llm_security_platform.app import db
from llm_security_platform.app.dataset import load_dataset
from llm_security_platform.app.evaluator import compare_models
from llm_security_platform.app.schemas import ModelComparisonCreate, ModelTarget
from llm_security_platform.app.seed import DEFAULT_CASES_PATH, seed_cases


def parse_target(value):
    provider, separator, model = value.partition(":")
    if not separator:
        raise argparse.ArgumentTypeError("target must use provider:model format")
    return ModelTarget(provider=provider, model=model)


def main():
    parser = argparse.ArgumentParser(description="Compare models on one security dataset.")
    parser.add_argument("--target", action="append", type=parse_target, required=True)
    parser.add_argument("--name", default="stage-two-model-comparison")
    parser.add_argument("--defense-policy", choices=["none", "baseline"], default="none")
    parser.add_argument("--max-tokens", type=int, default=128)
    parser.add_argument("--timeout-seconds", type=int, default=120)
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    if len(args.target) < 2:
        parser.error("at least two --target values are required")

    db.init_db()
    seed_cases()
    for target in args.target:
        target.inference_config.update(
            {
                "temperature": 0,
                "top_p": 1,
                "seed": 42,
                "max_tokens": args.max_tokens,
                "timeout_seconds": args.timeout_seconds,
                "reasoning": False,
            }
        )
    result = compare_models(
        ModelComparisonCreate(
            name=args.name,
            targets=args.target,
            defense_policy=args.defense_policy,
            case_ids=args.case_id
            or [case["case_id"] for case in load_dataset(DEFAULT_CASES_PATH)],
        )
    )
    serialized = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(serialized + "\n", encoding="utf-8")
        print(f"comparison report written to {output_path}")
    else:
        print(serialized)


if __name__ == "__main__":
    main()
