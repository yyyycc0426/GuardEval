from concurrent.futures import ThreadPoolExecutor, as_completed

from llm_security_platform.app.case_execution import execute_case
from llm_security_platform.app.celery_app import celery_app
from llm_security_platform.app.production_store import (
    begin_case,
    fail_run,
    finalize_run,
    finish_case,
    get_async_request,
    init_production_db,
    is_cancel_requested,
    pending_cases,
    start_run,
)
from llm_security_platform.app.providers import build_provider
from llm_security_platform.app.judge import LLMJudge, RuleBackedJudge
from llm_security_platform.app.schemas import EvaluationRunCreate
from llm_security_platform.policies.policy_engine import PolicyEngine


@celery_app.task(bind=True, name="security.execute_evaluation_run")
def execute_evaluation_run(self, run_id):
    init_production_db()
    payload = get_async_request(run_id)
    if payload is None:
        raise ValueError(f"async run {run_id} not found")
    if not start_run(run_id):
        return {"run_id": run_id, "status": "ignored"}
    try:
        request = EvaluationRunCreate.model_validate(payload)
        provider = build_provider(request.provider, request.model, request.inference_config)
        policy_engine = PolicyEngine(request.defense_policy)
        if request.judge_provider == "disabled":
            judge = False
        elif request.judge_provider == "mock":
            judge = RuleBackedJudge()
        else:
            judge = LLMJudge(build_provider(
                request.judge_provider,
                request.model,
                request.inference_config,
            ))
    except Exception as exc:
        fail_run(run_id, f"worker initialization failed: {exc}")
        raise
    remaining = pending_cases(run_id)
    for offset in range(0, len(remaining), request.concurrency):
        if is_cancel_requested(run_id):
            break
        batch = remaining[offset:offset + request.concurrency]
        runnable = [item for item in batch if begin_case(run_id, item["case_id"])]
        with ThreadPoolExecutor(max_workers=request.concurrency) as executor:
            futures = {
                executor.submit(execute_case, item["case"], provider, policy_engine, judge): item
                for item in runnable
            }
            for future in as_completed(futures):
                item = futures[future]
                try:
                    finish_case(run_id, item["case_id"], result=future.result())
                except Exception as exc:
                    finish_case(run_id, item["case_id"], error=str(exc))
    status = finalize_run(run_id)
    return {"run_id": run_id, "status": status}
