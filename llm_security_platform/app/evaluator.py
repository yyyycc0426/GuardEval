from collections import Counter, defaultdict
import math
from time import perf_counter
from concurrent.futures import ThreadPoolExecutor

from llm_security_platform.app import db
from llm_security_platform.app.detectors import evaluate_response
from llm_security_platform.app.judge import RuleBackedJudge
from llm_security_platform.app.layered_detection import assess_response
from llm_security_platform.app.providers import ModelProviderError, build_provider
from llm_security_platform.app.provenance import build_run_metadata
from llm_security_platform.app.rag_context import retrieved_documents_for_case
from llm_security_platform.app.schemas import DetectorDecision, EvaluationReport, EvaluationResult
from llm_security_platform.policies.base import DefenseContext
from llm_security_platform.policies.policy_engine import PolicyEngine


def execute_run(request, tenant_id="default"):
    cases = db.list_attack_cases(request.case_ids or None)
    if not cases:
        raise ValueError("No attack cases are available for this run")
    provider = build_provider(request.provider, request.model, request.inference_config)
    run_metadata = build_run_metadata(request, provider)
    run_id = db.create_run(
        request.name,
        provider.name,
        provider.model,
        request.defense_policy,
        len(cases),
        run_metadata,
        tenant_id=tenant_id,
    )

    policy_engine = PolicyEngine(request.defense_policy, request.versions)
    prepared_cases = _prepare_cases(cases, policy_engine)
    execution_results = _run_concurrent_evaluation(prepared_cases, provider)
    failed = _process_and_save_outcomes(run_id, execution_results, policy_engine, provider, request.defense_policy, tenant_id)

    db.complete_run(run_id, status="completed_with_errors" if failed else "completed")
    return build_report(run_id, tenant_id=tenant_id)


def _prepare_cases(cases, policy_engine):
    prepared = []
    for case in cases:
        context = DefenseContext(
            case=case,
            system_prompt=case["system_prompt"],
            user_prompt=case["prompt"],
            retrieved_documents=retrieved_documents_for_case(case),
        )
        defense = policy_engine.before_model(context)
        prepared.append({
            "case": case,
            "context": context,
            "defense": defense,
        })
    return prepared


def _run_concurrent_evaluation(prepared_cases, provider):
    def call_provider(item):
        case = item["case"]
        context = item["context"]
        defense = item["defense"]

        started_at = perf_counter()
        status = "completed"
        response_text = ""
        raw_response_text = ""
        token_usage = {}
        estimated_cost = 0.0
        model_call = {}
        error = None

        if defense.blocked:
            status = "blocked"
            response_text = "Request blocked by the configured security policy."
        else:
            try:
                call_result = provider.generate(defense.system_prompt, defense.user_prompt)
                raw_response_text = call_result.response_text
                context.response_text = raw_response_text
                token_usage = call_result.token_usage
                estimated_cost = call_result.estimated_cost
                model_call = call_result.provider_metadata
            except (ModelProviderError, OSError, ValueError) as exc:
                status = "failed"
                error = str(exc)

        latency_ms = round((perf_counter() - started_at) * 1000, 2)
        return {
            "case": case,
            "context": context,
            "defense": defense,
            "status": status,
            "response_text": response_text,
            "raw_response_text": raw_response_text,
            "token_usage": token_usage,
            "estimated_cost": estimated_cost,
            "model_call": model_call,
            "error": error,
            "latency_ms": latency_ms,
        }

    max_workers = min(16, len(prepared_cases))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        return list(executor.map(call_provider, prepared_cases))


def _process_and_save_outcomes(run_id, execution_results, policy_engine, provider, defense_policy, tenant_id):
    failed = False
    for res in execution_results:
        case = res["case"]
        context = res["context"]
        defense = res["defense"]
        status = res["status"]
        response_text = res["response_text"]
        raw_response_text = res["raw_response_text"]
        token_usage = res["token_usage"]
        estimated_cost = res["estimated_cost"]
        model_call = res["model_call"]
        error = res["error"]
        latency_ms = res["latency_ms"]

        if status == "failed":
            failed = True
            detector = _build_failed_detector_decision()
        elif status == "blocked":
            detector = evaluate_response(case, response_text)
        else:
            # apply after_model defense
            defense = policy_engine.after_model(context, defense)
            response_text = defense.response_text
            detector = evaluate_response(case, response_text)

        if status != "failed":
            try:
                for decision in defense.decisions:
                    db.save_defense_audit(run_id, case["case_id"], decision, tenant_id=tenant_id)
                if defense.review_required and raw_response_text:
                    assess_response(
                        case,
                        raw_response_text,
                        RuleBackedJudge(),
                        sample_rate=0,
                        tenant_id=tenant_id,
                    )
            except Exception as exc:
                failed = True
                status = "failed"
                error = str(exc)
                detector = _build_failed_detector_decision()

        result = EvaluationResult(
            run_id=run_id,
            case_id=case["case_id"],
            risk_type=case["risk_type"],
            provider=provider.name,
            model=provider.model,
            defense_policy=defense_policy,
            status=status,
            original_prompt=case["prompt"],
            effective_prompt=defense.user_prompt,
            response_text=response_text,
            detector=detector,
            latency_ms=latency_ms,
            token_usage=token_usage,
            estimated_cost=estimated_cost,
            model_call=model_call,
            defense_decisions=defense.decisions,
            raw_response_text=raw_response_text,
            review_required=defense.review_required,
            error=error,
            created_at=db.now_iso(),
        )
        db.save_result(result, tenant_id=tenant_id)
    return failed


def _build_failed_detector_decision():
    return DetectorDecision(
        input_risk_score=0.0,
        input_signals=[],
        output_signals=[],
        attack_success=False,
        decision_reason="Evaluation failed before a security decision could be made.",
        outcome_label="unclear",
        business_completed=False,
    )



def build_report(run_id, tenant_id="default"):
    run = db.get_run(run_id, tenant_id=tenant_id)
    if run is None:
        return None
    results = db.list_results(run_id, tenant_id=tenant_id)
    cases_by_id = {item["case_id"]: item for item in db.list_attack_cases()}
    attack_results = [item for item in results if item["risk_type"] != "benign" and item["status"] != "failed"]
    benign_results = [item for item in results if item["risk_type"] == "benign"]
    successful_attacks = sum(item["detector"]["attack_success"] for item in attack_results)
    raw_successful_attacks = sum(
        evaluate_response(
            cases_by_id[item["case_id"]],
            item.get("raw_response_text") or item.get("response_text", ""),
        ).attack_success
        for item in attack_results
    ) if attack_results else 0
    benign_blocks = sum(item["status"] == "blocked" for item in benign_results)
    benign_completed = sum(
        item["detector"].get("business_completed", False) for item in benign_results
    )
    grouped = defaultdict(list)
    by_language_items = defaultdict(list)
    by_method_items = defaultdict(list)
    for item in results:
        grouped[item["risk_type"]].append(item)
        metadata = cases_by_id.get(item["case_id"], {}).get("metadata", {})
        by_language_items[metadata.get("language", "unknown")].append(item)
        by_method_items[metadata.get("attack_method", "unknown")].append(item)
    by_risk_type = {}
    for risk_type, items in grouped.items():
        valid = [item for item in items if item["status"] != "failed"]
        attacks = sum(item["detector"]["attack_success"] for item in valid)
        by_risk_type[risk_type] = {
            "case_count": len(items),
            "successful_attacks": attacks,
            "attack_success_rate": round(attacks / len(valid), 4) if valid and risk_type != "benign" else 0.0,
            "blocked_count": sum(item["status"] == "blocked" for item in items),
        }
    latencies = [item["latency_ms"] for item in results if item["status"] != "failed"]
    sorted_latencies = sorted(latencies)
    p50_index = max(0, math.ceil(len(sorted_latencies) * 0.50) - 1) if sorted_latencies else 0
    p95_index = max(0, math.ceil(len(sorted_latencies) * 0.95) - 1) if sorted_latencies else 0

    def summarize_dimension(groups):
        summary = {}
        for key, items in groups.items():
            attack_items = [
                item for item in items if item["risk_type"] != "benign" and item["status"] != "failed"
            ]
            success = sum(item["detector"]["attack_success"] for item in attack_items)
            summary[key] = {
                "case_count": len(items),
                "attack_case_count": len(attack_items),
                "successful_attacks": success,
                "attack_success_rate": round(success / len(attack_items), 4) if attack_items else 0.0,
                "failed_count": sum(item["status"] == "failed" for item in items),
            }
        return summary

    total_tokens = sum(item["token_usage"].get("total_tokens", 0) for item in results)
    total_cost = sum(float(item.get("estimated_cost") or 0) for item in results)
    all_decisions = [decision for item in results for decision in item["defense_decisions"]]
    action_counts = Counter(decision["action"] for decision in all_decisions)
    defended_positive = [
        item
        for item in results
        if any(
            decision["action"] in {"block", "sanitize", "rewrite", "redact", "review"}
            for decision in item["defense_decisions"]
        )
    ]
    true_positive = sum(item["risk_type"] != "benign" for item in defended_positive)
    false_positive = sum(item["risk_type"] == "benign" for item in defended_positive)
    false_negative = sum(
        item["risk_type"] != "benign" and item not in defended_positive for item in results
    )
    precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0
    recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0
    defense_f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0
    return EvaluationReport(
        run_id=run_id,
        status=run["status"],
        total_cases=len(results),
        completed_cases=sum(item["status"] == "completed" for item in results),
        failed_cases=sum(item["status"] == "failed" for item in results),
        blocked_cases=sum(item["status"] == "blocked" for item in results),
        attack_case_count=len(attack_results),
        successful_attacks=successful_attacks,
        attack_success_rate=round(successful_attacks / len(attack_results), 4) if attack_results else 0.0,
        raw_model_compromise_rate=round(raw_successful_attacks / len(attack_results), 4)
        if attack_results else 0.0,
        delivered_attack_success_rate=round(successful_attacks / len(attack_results), 4)
        if attack_results else 0.0,
        benign_case_count=len(benign_results),
        benign_block_count=benign_blocks,
        false_positive_rate=round(benign_blocks / len(benign_results), 4) if benign_results else 0.0,
        normal_task_success_rate=round(benign_completed / len(benign_results), 4)
        if benign_results
        else 0.0,
        average_latency_ms=round(sum(latencies) / len(latencies), 2) if latencies else 0.0,
        p50_latency_ms=round(sorted_latencies[p50_index], 2) if sorted_latencies else 0.0,
        p95_latency_ms=round(sorted_latencies[p95_index], 2) if sorted_latencies else 0.0,
        total_tokens=total_tokens,
        estimated_total_cost=round(total_cost, 8),
        failure_rate=round(sum(item["status"] == "failed" for item in results) / len(results), 4)
        if results
        else 0.0,
        defense_precision=round(precision, 4),
        defense_recall=round(recall, 4),
        defense_f1=round(defense_f1, 4),
        defense_false_negative_rate=round(
            false_negative / len(attack_results), 4
        ) if attack_results else 0.0,
        review_rate=round(sum(item["review_required"] for item in results) / len(results), 4)
        if results else 0.0,
        defense_action_counts=dict(action_counts),
        by_risk_type=by_risk_type,
        by_language=summarize_dimension(by_language_items),
        by_attack_method=summarize_dimension(by_method_items),
        run_metadata=run["run_metadata"],
    )


def compare_policies(
    name,
    provider="mock",
    model=None,
    case_ids=None,
    versions=None,
    inference_config=None,
    defense_config=None,
    tenant_id="default",
):
    from llm_security_platform.app.schemas import EvaluationRunCreate, default_inference_config

    effective_inference_config = (
        inference_config if inference_config is not None else default_inference_config()
    )

    baseline = execute_run(
        EvaluationRunCreate(
            name=f"{name} - no defense",
            provider=provider,
            model=model,
            defense_policy="none",
            case_ids=case_ids or [],
            versions=versions or {},
            inference_config=effective_inference_config,
            defense_config=defense_config or {},
        ),
        tenant_id=tenant_id,
    )
    defended = execute_run(
        EvaluationRunCreate(
            name=f"{name} - baseline defense",
            provider=provider,
            model=model,
            defense_policy="baseline",
            case_ids=case_ids or [],
            versions=versions or {},
            inference_config=effective_inference_config,
            defense_config=defense_config or {},
        ),
        tenant_id=tenant_id,
    )
    return {
        "without_defense": baseline.model_dump(),
        "with_defense": defended.model_dump(),
        "attack_success_rate_reduction": round(
            baseline.attack_success_rate - defended.attack_success_rate, 4
        ),
        "false_positive_rate_change": round(
            defended.false_positive_rate - baseline.false_positive_rate, 4
        ),
    }


def compare_models(request, tenant_id="default"):
    from llm_security_platform.app.schemas import EvaluationRunCreate

    reports = []
    for target in request.targets:
        try:
            report = execute_run(
                EvaluationRunCreate(
                    name=f"{request.name} - {target.provider}/{target.model or 'default'}",
                    provider=target.provider,
                    model=target.model,
                    defense_policy=request.defense_policy,
                    case_ids=request.case_ids,
                    versions=request.versions,
                    inference_config=target.inference_config,
                    defense_config=request.defense_config,
                ),
                tenant_id=tenant_id,
            )
            reports.append({"status": "completed", "report": report.model_dump()})
        except (ModelProviderError, OSError, ValueError) as exc:
            reports.append(
                {
                    "status": "failed",
                    "provider": target.provider,
                    "model": target.model,
                    "error": str(exc),
                }
            )
    return {"name": request.name, "models": reports}
