from time import perf_counter

from llm_security_platform.app.detectors import evaluate_response, rule_detect_input, rule_detect_response
from llm_security_platform.app.judge import RuleBackedJudge
from llm_security_platform.app.rag_context import retrieved_documents_for_case
from llm_security_platform.policies.base import DefenseContext
from llm_security_platform.app.circuit_breaker import CircuitBreaker, CircuitBreakerOpenException

import logging

logger = logging.getLogger(__name__)
model_breaker = CircuitBreaker("LLM_Model_Breaker", failure_threshold=3, recovery_timeout=30.0)


def execute_case(case, provider, policy_engine, judge=None, run_id=None, tenant_id="default", user_id="system"):
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
        from llm_security_platform.app.semantic_cache import SemanticCache
        tenant_id = getattr(policy_engine, "tenant_id", "default")
        provider_name = getattr(provider, "name", "default")
        model_name = getattr(provider, "model", "default")
        policy_str = "+".join(policy_engine.bundle) if getattr(policy_engine, "bundle", None) else "none"
        cache = SemanticCache(
            tenant_id=tenant_id,
            provider=provider_name,
            model=model_name,
            defense_policy=policy_str
        )

        pre_allocated_tokens = 0
        if run_id:
            from llm_security_platform.app.cost_guardrail import check_and_record_usage
            # Pre-check budget exhaustion before making any calls
            check_and_record_usage(tenant_id, user_id, run_id, 0)
            
            from llm_security_platform.app.config import PRE_ALLOCATED_TOKENS
            MAX_TOKENS_PER_CASE = PRE_ALLOCATED_TOKENS
            check_and_record_usage(tenant_id, user_id, run_id, MAX_TOKENS_PER_CASE)
            pre_allocated_tokens = MAX_TOKENS_PER_CASE

        try:
            cached_result = cache.lookup(defense.system_prompt, defense.user_prompt)
            if cached_result:
                call = cached_result
                if not isinstance(call.provider_metadata, dict):
                    call.provider_metadata = {}
                call.provider_metadata["semantic_cache_hit"] = True
            else:
                if not model_breaker.allow_request():
                    logger.error("Circuit Breaker is OPEN - failing fast.")
                    raise CircuitBreakerOpenException("Circuit Breaker OPEN - failing fast")
                try:
                    call = provider.generate(defense.system_prompt, defense.user_prompt)
                    model_breaker.record_success()
                except Exception as exc:
                    model_breaker.record_failure()
                    raise exc
                cache.store(defense.system_prompt, defense.user_prompt, call)

            raw_response_text = call.response_text
            context.response_text = raw_response_text
            defense = policy_engine.after_model(context, defense)
            response_text = defense.response_text
            token_usage = call.token_usage
            estimated_cost = call.estimated_cost
            model_call = call.provider_metadata

            # Record token usage against budgets after model completion
            total_tokens = token_usage.get("total_tokens", 0) if isinstance(token_usage, dict) else 0
            if run_id and pre_allocated_tokens > 0:
                from llm_security_platform.app.cost_guardrail import check_and_record_usage
                reconcile_tokens = total_tokens - pre_allocated_tokens
                check_and_record_usage(tenant_id, user_id, run_id, reconcile_tokens)
                pre_allocated_tokens = 0
        except CircuitBreakerOpenException as exc:
            status = "failed"
            response_text = "Request failed fast: LLM provider is currently undergoing circuit breaker protection."
            raw_response_text = ""
            token_usage = {}
            estimated_cost = 0.0
            model_call = {}
        finally:
            if run_id and pre_allocated_tokens > 0:
                from llm_security_platform.app.cost_guardrail import check_and_record_usage
                try:
                    check_and_record_usage(tenant_id, user_id, run_id, -pre_allocated_tokens)
                except Exception:
                    pass

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
