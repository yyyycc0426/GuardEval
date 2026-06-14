from time import perf_counter

from llm_security_platform.app.detectors import evaluate_response, rule_detect_input, rule_detect_response
from llm_security_platform.app.judge import RuleBackedJudge
from llm_security_platform.app.rag_context import retrieved_documents_for_case
from llm_security_platform.policies.base import DefenseContext


def execute_case(case, provider, policy_engine, judge=None):
    context = DefenseContext(
        case=case,
        system_prompt=case["system_prompt"],
        user_prompt=case["prompt"],
        retrieved_documents=retrieved_documents_for_case(case),
    )
    defense = policy_engine.before_model(context)
    started = perf_counter()
    response_text = ""
    raw_response_text = ""
    token_usage = {}
    estimated_cost = 0.0
    model_call = {}
    status = "completed"
    if defense.blocked:
        status = "blocked"
        response_text = "Request blocked by the configured security policy."
    else:
        call = provider.generate(defense.system_prompt, defense.user_prompt)
        raw_response_text = call.response_text
        context.response_text = raw_response_text
        defense = policy_engine.after_model(context, defense)
        response_text = defense.response_text
        token_usage = call.token_usage
        estimated_cost = call.estimated_cost
        model_call = call.provider_metadata
    detector = evaluate_response(case, response_text)
    raw_detector = evaluate_response(case, raw_response_text or response_text)
    input_finding = rule_detect_input(case["prompt"])
    response_finding = rule_detect_response(case, response_text)
    judge_result = (judge or RuleBackedJudge()).evaluate(case, raw_response_text or response_text) if judge is not False else None
    return {
        "case_id": case["case_id"],
        "risk_type": case["risk_type"],
        "status": status,
        "original_prompt": case["prompt"],
        "effective_prompt": defense.user_prompt,
        "response_text": response_text,
        "raw_response_text": raw_response_text,
        "detector": detector.model_dump(),
        "raw_detector": raw_detector.model_dump(),
        "latency_ms": round((perf_counter() - started) * 1000, 2),
        "token_usage": token_usage,
        "estimated_cost": estimated_cost,
        "model_call": model_call,
        "defense_decisions": [item.model_dump() for item in defense.decisions],
        "review_required": defense.review_required,
        "metadata": case.get("metadata", {}),
        "evidence_chain": {
            "input_detection": input_finding.model_dump(),
            "defense_decisions": [item.model_dump() for item in defense.decisions],
            "effective_model_input": {
                "system_prompt": defense.system_prompt,
                "user_prompt": defense.user_prompt,
            },
            "raw_model_response": raw_response_text,
            "rule_detection": response_finding.model_dump(),
            "semantic_detection": None,
            "semantic_status": "not_configured",
            "judge_result": judge_result.model_dump() if judge_result else None,
            "human_review": None,
            "final_outcome": detector.outcome_label,
        },
    }
