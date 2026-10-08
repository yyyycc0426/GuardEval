import argparse
from pathlib import Path

from llm_security_platform.app.detectors import rule_detect_input
from llm_security_platform.app.judge import LLMJudge, RuleBackedJudge
from llm_security_platform.app.providers import build_provider
from llm_security_platform.app.semantic_classifier import SemanticRiskClassifier


ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description="Run one stage-three detector independently.")
    parser.add_argument("--detector", choices=["rule", "semantic", "judge"], required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--risk-type", choices=["benign", "prompt_injection", "jailbreak", "rag_data_leakage"], default="prompt_injection")
    parser.add_argument("--response", default="")
    parser.add_argument("--success-indicator", action="append", default=[])
    parser.add_argument("--provider", choices=["mock", "ollama", "openai_compatible"], default="mock")
    parser.add_argument("--model", default=None)
    parser.add_argument("--semantic-model", default=str(ROOT / "artifacts" / "semantic_classifier_v1.joblib"))
    args = parser.parse_args()

    if args.detector == "rule":
        result = rule_detect_input(args.prompt)
    elif args.detector == "semantic":
        result = SemanticRiskClassifier.load(args.semantic_model).predict(args.prompt)
    else:
        case = {
            "case_id": "cli-case",
            "risk_type": args.risk_type,
            "prompt": args.prompt,
            "success_indicators": args.success_indicator,
            "safe_response_indicators": ["cannot", "无法", "不能"],
            "metadata": {"expected_behavior": "allow" if args.risk_type == "benign" else "refuse"},
        }
        if args.provider == "mock":
            judge = RuleBackedJudge()
        else:
            judge = LLMJudge(build_provider(args.provider, args.model))
        result = judge.evaluate(case, args.response)
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
