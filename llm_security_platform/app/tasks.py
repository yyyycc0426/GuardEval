from concurrent.futures import ThreadPoolExecutor, as_completed

from llm_security_platform.app.case_execution import execute_case
from llm_security_platform.app.celery_app import celery_app
from llm_security_platform.app.production_store import (
    begin_case,
    fail_run,
    finalize_run,
    finish_case,
    init_production_db,
    is_cancel_requested,
    pending_cases,
    start_run,
)
from llm_security_platform.app.providers import build_provider
from llm_security_platform.app.judge import LLMJudge, RuleBackedJudge
from llm_security_platform.app.schemas import EvaluationRunCreate
from llm_security_platform.policies.policy_engine import PolicyEngine


def run_evaluation_logic(run_id, tenant_id="default", trace_id=None):
    from llm_security_platform.app.tracing import current_trace_id
    if trace_id:
        current_trace_id.set(trace_id)
    from llm_security_platform.app.production_store import current_tenant
    current_tenant.set(tenant_id)
    init_production_db()
    from llm_security_platform.app.production_store import session_scope
    from llm_security_platform.app.production_models import AsyncRun
    
    with session_scope() as session:
        run = session.get(AsyncRun, run_id)
        if run is None:
            raise ValueError(f"async run {run_id} not found")
        tenant_id = run.tenant_id
        current_tenant.set(tenant_id)
        payload = dict(run.request_json)
        created_by = run.created_by or "system"
        
    if not start_run(run_id):
        return {"run_id": run_id, "status": "ignored"}
    try:
        request = EvaluationRunCreate.model_validate(payload)
        from llm_security_platform.app.production_store import get_tenant_config
        config = get_tenant_config(tenant_id)
        tenant_keys = config.get("keys", {})
        if tenant_keys:
            if not request.inference_config:
                request.inference_config = {}
            request.inference_config["_tenant_keys"] = tenant_keys
            
        provider = build_provider(request.provider, request.model, request.inference_config)
        policy_engine = PolicyEngine(request.defense_policy, versions=request.versions, tenant_id=tenant_id)
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
        # Heartbeat: renew Redis lock key if present
        try:
            from llm_security_platform.app.middleware import get_redis
            r = get_redis()
            if r:
                with session_scope() as session:
                    run_obj = session.get(AsyncRun, run_id)
                    if run_obj and run_obj.run_metadata_json:
                        lock_key = run_obj.run_metadata_json.get("run_lock_key")
                        if lock_key:
                            r.expire(lock_key, 300)
        except Exception:
            pass
        batch = remaining[offset:offset + request.concurrency]
        runnable = [item for item in batch if begin_case(run_id, item["case_id"])]
        with ThreadPoolExecutor(max_workers=request.concurrency) as executor:
            futures = {
                executor.submit(
                    execute_case,
                    item["case"],
                    provider,
                    policy_engine,
                    judge,
                    run_id=run_id,
                    tenant_id=tenant_id,
                    user_id=created_by
                ): item
                for item in runnable
            }
            for future in as_completed(futures):
                item = futures[future]
                try:
                    res_val = future.result()
                    finish_case(run_id, item["case_id"], result=res_val)

                    # SaaS Token Metering
                    if res_val and isinstance(res_val, dict) and "token_usage" in res_val:
                        usage = res_val["token_usage"] or {}
                        p_tok = usage.get("prompt_tokens", 0) or 0
                        c_tok = usage.get("completion_tokens", 0) or 0
                        if p_tok or c_tok:
                            from llm_security_platform.app.metrics import GLOBAL_METRICS
                            GLOBAL_METRICS.record_tenant_tokens(
                                tenant_id=tenant_id,
                                provider=request.provider,
                                model=getattr(provider, "model", None) or request.model or "default",
                                token_type="prompt",
                                count=p_tok
                            )
                            GLOBAL_METRICS.record_tenant_tokens(
                                tenant_id=tenant_id,
                                provider=request.provider,
                                model=getattr(provider, "model", None) or request.model or "default",
                                token_type="completion",
                                count=c_tok
                            )
                except Exception as exc:
                    finish_case(run_id, item["case_id"], error=str(exc))
                    # Terminate remaining cases immediately if budget is exceeded
                    if "BUDGET_EXCEEDED" in str(exc) or "budget exceeded" in str(exc).lower():
                        from llm_security_platform.app.production_store import request_cancel
                        request_cancel(run_id)

    status = finalize_run(run_id)

    try:
        from llm_security_platform.app.production_store import build_async_report
        from llm_security_platform.app.gcs_store import gcs_store
        report_data = build_async_report(run_id, tenant_id=tenant_id)
        if report_data:
            gcs_store.upload_json(report_data, f"reports/{tenant_id}/{run_id}_report.json")
    except Exception as exc:
        import logging
        logger = logging.getLogger("llm_security_platform.tasks")
        logger.error(f"Failed to upload report to GCS: {exc}")

    # Release distributed idempotency lock
    try:
        from llm_security_platform.app.middleware import get_redis
        from llm_security_platform.app.production_store import session_scope
        from llm_security_platform.app.production_models import AsyncRun
        with session_scope() as session:
            run = session.get(AsyncRun, run_id)
            if run:
                lock_key = run.run_metadata_json.get("run_lock_key")
                if lock_key:
                    r = get_redis()
                    if r:
                        r.delete(lock_key)
    except Exception as exc:
        import logging
        logger = logging.getLogger("llm_security_platform.tasks")
        logger.error(f"Failed to release distributed lock: {exc}")

    return {"run_id": run_id, "status": status}


@celery_app.task(bind=True, name="security.execute_evaluation_run")
def execute_evaluation_run(self, run_id, tenant_id="default", trace_id=None):
    return run_evaluation_logic(run_id, tenant_id=tenant_id, trace_id=trace_id)


@celery_app.task(name="security.cleanup_stale_fallback_reports")
def cleanup_stale_fallback_reports():
    from llm_security_platform.app.gcs_store import gcs_store
    try:
        gcs_store._cleanup_old_local_files()
        return {"status": "success", "message": "Stale reports cleaned up"}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}

