import argparse
import json

from llm_security_platform.app import db
from llm_security_platform.app.dataset import load_dataset
from llm_security_platform.app.evaluator import compare_policies
from llm_security_platform.app.seed import DEFAULT_CASES_PATH, seed_cases


def main():
    parser = argparse.ArgumentParser(description="Run an LLM security defense comparison benchmark.")
    parser.add_argument("--provider", choices=["mock", "ollama", "openai_compatible"], default="mock")
    parser.add_argument("--model", default=None)
    args = parser.parse_args()
    db.init_db()
    seed_cases()
    case_ids = [case["case_id"] for case in load_dataset(DEFAULT_CASES_PATH)]
    report = compare_policies(
        "default security benchmark",
        provider=args.provider,
        model=args.model,
        case_ids=case_ids,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
