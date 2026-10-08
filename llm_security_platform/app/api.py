import base64
from contextlib import asynccontextmanager
from pathlib import Path
import re
import time
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Header, Request, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from llm_security_platform.app import db
from llm_security_platform.app.metrics import GLOBAL_METRICS
from llm_security_platform.app.async_jobs import dispatch_run
from llm_security_platform.app.evaluator import (
    build_report,
    compare_models,
    compare_policies,
    execute_run,
)
from llm_security_platform.app.judge import LLMJudge, RuleBackedJudge
from llm_security_platform.app.layered_detection import assess_response
from llm_security_platform.app.providers import build_provider
from llm_security_platform.app.production_store import (
    build_async_report,
    create_async_run,
    fail_run,
    get_async_run,
    init_production_db,
    list_audits,
    list_async_runs,
    list_case_results,
    prepare_retry,
    request_cancel,
    save_audit,
)
from llm_security_platform.app.provenance import get_git_commit
from llm_security_platform.app.semantic_classifier import SemanticRiskClassifier
from llm_security_platform.app.schemas import (
    ApiResponse,
    AttackCaseCreate,
    DatasetImport,
    EvaluationRunCreate,
    ModelComparisonCreate,
    HumanReviewUpdate,
    LayeredAssessmentCreate,
    DefensePolicyCreate,
    MultimodalAssessmentRequest,
    MultimodalAssessmentResponse,
    TenantSignupRequest,
    TenantSignupResponse,
)
from llm_security_platform.app.security import require_permission, encode_jwt
from llm_security_platform.app.seed import seed_cases
from llm_security_platform.app.multimodal import assess_multimodal_input
from llm_security_platform.app.detectors import rule_detect_input
from llm_security_platform.app.middleware import RateLimitingMiddleware, get_redis
from llm_security_platform.app.production_store import save_tenant_config, current_tenant, session_scope, get_run_fingerprint
from llm_security_platform.app.tracing import current_trace_id, setup_tracing_logging


ARTIFACTS_ROOT = Path(__file__).resolve().parents[1] / "artifacts"


def _resolve_semantic_model_path(value):
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = ARTIFACTS_ROOT / candidate
    candidate = candidate.resolve()
    try:
        candidate.relative_to(ARTIFACTS_ROOT.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="semantic model must be inside artifacts") from exc
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="semantic model artifact not found")
    return candidate


@asynccontextmanager
async def lifespan(_app: FastAPI):
    setup_tracing_logging()
    db.init_db()
    init_production_db()
    if not db.list_attack_cases():
        seed_cases()
    yield


app = FastAPI(
    title="LLM Security Evaluation Platform",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        start_time = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start_time
        
        path = request.url.path
        normalized_path = path
        normalized_path = re.sub(r"/human-reviews/\d+", "/human-reviews/{review_id}", normalized_path)
        normalized_path = re.sub(r"/async-runs/[a-f0-9-]+", "/async-runs/{run_id}", normalized_path)
        
        GLOBAL_METRICS.record_request(
            method=request.method,
            path=normalized_path,
            status_code=response.status_code,
            duration=duration
        )
        return response


class TracingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        trace_id = request.headers.get("X-Trace-ID") or uuid4().hex
        token = current_trace_id.set(trace_id)
        try:
            response = await call_next(request)
            response.headers["X-Trace-ID"] = trace_id
            return response
        finally:
            current_trace_id.reset(token)


app.add_middleware(TracingMiddleware)
app.add_middleware(MetricsMiddleware)
app.add_middleware(RateLimitingMiddleware)


@app.get("/health", response_model=ApiResponse)
def health():
    return ApiResponse(success=True, message="ok", data={"service": "llm-security-platform"})


@app.post("/tenants/signup", response_model=ApiResponse)
def signup_tenant(request: TenantSignupRequest, actor=Depends(require_permission("admin:write"))):
    if actor.get("tenant_id") != "default":
        raise HTTPException(
            status_code=403,
            detail="Only the default platform administrator is permitted to register new tenants."
        )
    # Sanitize and validate tenant_id
    if not (request.tenant_id.isalnum() or all(c.isalnum() or c == '_' for c in request.tenant_id)):
        raise HTTPException(
            status_code=400,
            detail="tenant_id must contain only alphanumeric characters and underscores"
        )
    
    # Check if tenant already exists in default schema
    from llm_security_platform.app.production_models import TenantConfig
    token = current_tenant.set("default")
    try:
        with session_scope() as session:
            existing = session.get(TenantConfig, request.tenant_id)
            if existing:
                raise HTTPException(
                    status_code=400,
                    detail=f"tenant_id '{request.tenant_id}' already registered"
                )
    finally:
        current_tenant.reset(token)

    # Encrypt keys and save tenant configuration
    save_tenant_config(request.tenant_id, request.keys, request.qps_limit)

    # Instantly provision the database schema / tables for this tenant
    token = current_tenant.set(request.tenant_id)
    try:
        with session_scope() as session:
            # Running session_scope triggers schema creation / search_path setting
            pass
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to provision database schema for tenant: {exc}"
        )
    finally:
        current_tenant.reset(token)

    # Generate admin JWT token for the tenant
    token_str = encode_jwt(request.actor, "admin", request.tenant_id)

    return ApiResponse(
        success=True,
        message="Tenant onboarded and schema provisioned successfully",
        data={
            "tenant_id": request.tenant_id,
            "token": token_str,
            "qps_limit": request.qps_limit
        }
    )


@app.post("/tenants/token", response_model=ApiResponse)
def get_tenant_token(actor=Depends(require_permission("run:read"))):
    token_str = encode_jwt(actor["actor"], actor["role"], actor["tenant_id"])
    return ApiResponse(
        success=True,
        message="Token issued successfully",
        data={
            "token": token_str,
            "tenant_id": actor["tenant_id"],
            "role": actor["role"]
        }
    )


@app.get("/cases", response_model=ApiResponse)
def cases(_actor=Depends(require_permission("case:read"))):
    return ApiResponse(success=True, message="Attack cases fetched", data=db.list_attack_cases(tenant_id=_actor["tenant_id"]))


@app.post("/cases", response_model=ApiResponse)
def create_case(case: AttackCaseCreate, _actor=Depends(require_permission("admin:write"))):
    db.save_attack_case(case, tenant_id=_actor["tenant_id"])
    return ApiResponse(success=True, message="Attack case saved", data={"case_id": case.case_id})


@app.post("/cases/seed", response_model=ApiResponse)
def seed_default_cases(_actor=Depends(require_permission("admin:write"))):
    count = seed_cases(tenant_id=_actor["tenant_id"])
    return ApiResponse(success=True, message="Default attack cases seeded", data={"count": count})


@app.post("/datasets/import", response_model=ApiResponse)
def import_dataset(payload: DatasetImport, actor=Depends(require_permission("admin:write"))):
    for case in payload.cases:
        case.metadata["dataset_version"] = payload.dataset_version
        db.save_attack_case(case, tenant_id=actor["tenant_id"])
    save_audit(
        actor=actor["actor"], role=actor["role"], action="dataset.import",
        target_type="dataset", target_id=payload.dataset_version,
        request_id=uuid4().hex, metadata={"case_count": len(payload.cases)},
        tenant_id=actor["tenant_id"],
    )
    return ApiResponse(
        success=True,
        message="Dataset imported",
        data={"dataset_version": payload.dataset_version, "case_count": len(payload.cases)},
    )


@app.post("/runs", response_model=ApiResponse)
def run_evaluation(request: EvaluationRunCreate, _actor=Depends(require_permission("run:create"))):
    if request.case_ids and len(request.case_ids) > 100:
        raise HTTPException(
            status_code=400,
            detail="The number of cases in a single evaluation run cannot exceed 100."
        )
    try:
        report = execute_run(request, tenant_id=_actor["tenant_id"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ApiResponse(success=True, message="Evaluation completed", data=report.model_dump())


@app.get("/runs/{run_id}", response_model=ApiResponse)
def run_detail(run_id: int, _actor=Depends(require_permission("run:read"))):
    report = build_report(run_id, tenant_id=_actor["tenant_id"])
    if report is None:
        raise HTTPException(status_code=404, detail="evaluation run not found")
    return ApiResponse(
        success=True,
        message="Evaluation run fetched",
        data={"report": report.model_dump(), "results": db.list_results(run_id, tenant_id=_actor["tenant_id"])},
    )


@app.get("/runs/{run_id}/defense-audits", response_model=ApiResponse)
def run_defense_audits(run_id: int, _actor=Depends(require_permission("audit:read"))):
    if db.get_run(run_id, tenant_id=_actor["tenant_id"]) is None:
        raise HTTPException(status_code=404, detail="evaluation run not found")
    return ApiResponse(
        success=True,
        message="Defense audit records fetched",
        data=db.list_defense_audits(run_id, tenant_id=_actor["tenant_id"]),
    )


@app.post("/comparisons", response_model=ApiResponse)
def compare_defenses(request: EvaluationRunCreate, _actor=Depends(require_permission("run:create"))):
    comparison = compare_policies(
        request.name,
        provider=request.provider,
        model=request.model,
        case_ids=request.case_ids,
        versions=request.versions,
        inference_config=request.inference_config,
        defense_config=request.defense_config,
        tenant_id=_actor["tenant_id"],
    )
    return ApiResponse(success=True, message="Defense comparison completed", data=comparison)


@app.post("/model-comparisons", response_model=ApiResponse)
def model_comparison(request: ModelComparisonCreate, _actor=Depends(require_permission("run:create"))):
    return ApiResponse(
        success=True,
        message="Model comparison completed",
        data=compare_models(request, tenant_id=_actor["tenant_id"]),
    )


@app.post("/layered-assessments", response_model=ApiResponse)
def create_layered_assessment(
    request: LayeredAssessmentCreate,
    _actor=Depends(require_permission("run:create")),
):
    matching = db.list_attack_cases([request.case_id], tenant_id=_actor["tenant_id"])
    if not matching:
        raise HTTPException(status_code=404, detail="attack case not found")
    semantic_classifier = None
    if request.semantic_model_path:
        semantic_classifier = SemanticRiskClassifier.load(
            _resolve_semantic_model_path(request.semantic_model_path)
        )
    if request.judge_provider == "mock":
        judge = RuleBackedJudge()
    else:
        judge = LLMJudge(
            build_provider(
                request.judge_provider,
                request.judge_model,
                request.judge_model_config,
            )
        )
    assessment_id, assessment = assess_response(
        matching[0],
        request.model_response,
        judge,
        semantic_classifier=semantic_classifier,
        tenant_id=_actor["tenant_id"],
    )
    return ApiResponse(
        success=True,
        message="Layered assessment completed",
        data={"assessment_id": assessment_id, "assessment": assessment.model_dump()},
    )


@app.post("/layered-assessments/multimodal", response_model=ApiResponse)
def create_multimodal_assessment(
    request: MultimodalAssessmentRequest,
    _actor=Depends(require_permission("run:create")),
):
    try:
        base64_data = request.image_base64
        if "," in base64_data:
            base64_data = base64_data.split(",")[1]
        image_bytes = base64.b64decode(base64_data)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid base64 image data") from exc

    case_metadata = None
    if request.case_id:
        matching = db.list_attack_cases([request.case_id], tenant_id=_actor["tenant_id"])
        if matching:
            case_metadata = matching[0].get("metadata")

    assessment = assess_multimodal_input(image_bytes, case_metadata=case_metadata)
    if not assessment["success"]:
        raise HTTPException(
            status_code=400,
            detail=f"Multimodal assessment failed: {assessment['metadata'].get('error')}",
        )

    extracted_text = assessment["text"]
    finding = rule_detect_input(extracted_text)

    decision = finding.decision
    risk_score = finding.risk_score
    evidence = list(finding.evidence)

    if assessment["watermark"]["has_watermark"]:
        decision = "high_risk"
        risk_score = max(risk_score, 0.9)
        evidence.append(f"multimodal_watermark_detected: {assessment['watermark']['reason']}")

    response_data = MultimodalAssessmentResponse(
        success=True,
        text=extracted_text,
        methods=assessment["methods"],
        watermark=assessment["watermark"],
        metadata=assessment["metadata"],
        decision=decision,
        risk_score=risk_score,
        evidence=evidence,
    )

    return ApiResponse(
        success=True,
        message="Multimodal assessment completed",
        data=response_data.model_dump(),
    )


@app.get("/human-reviews", response_model=ApiResponse)
def human_reviews(status: str | None = "pending", _actor=Depends(require_permission("review:read"))):
    if status not in {None, "pending", "completed"}:
        raise HTTPException(status_code=400, detail="unsupported review status")
    return ApiResponse(
        success=True,
        message="Human review queue fetched",
        data=db.list_review_items(status, tenant_id=_actor["tenant_id"]),
    )


@app.patch("/human-reviews/{review_id}", response_model=ApiResponse)
def update_human_review(
    review_id: int,
    update: HumanReviewUpdate,
    _actor=Depends(require_permission("review:write")),
):
    if not db.complete_review(review_id, update, tenant_id=_actor["tenant_id"]):
        raise HTTPException(status_code=404, detail="pending review item not found")
    save_audit(
        actor=_actor["actor"], role=_actor["role"], action="review.complete",
        target_type="human_review", target_id=review_id, request_id=uuid4().hex,
        tenant_id=_actor["tenant_id"],
        metadata={"label": update.human_final_label, "attack_success": update.human_attack_success},
    )
    return ApiResponse(
        success=True,
        message="Human review completed",
        data={"review_id": review_id},
    )


@app.post("/human-reviews/{review_id}/promote-to-dataset", response_model=ApiResponse)
def promote_review_to_dataset(
    review_id: int,
    _actor=Depends(require_permission("review:write")),
):
    case_id = db.promote_review_to_case(review_id, tenant_id=_actor["tenant_id"])
    if not case_id:
        raise HTTPException(
            status_code=400,
            detail="Failed to promote review item. Ensure it is completed and belongs to your tenant."
        )
    save_audit(
        actor=_actor["actor"], role=_actor["role"], action="review.promote",
        target_type="human_review", target_id=review_id, request_id=uuid4().hex,
        tenant_id=_actor["tenant_id"],
        metadata={"promoted_case_id": case_id},
    )
    return ApiResponse(
        success=True,
        message="Human review item promoted to dataset",
        data={"promoted_case_id": case_id},
    )


@app.get("/human-reviews/metrics", response_model=ApiResponse)
def human_review_metrics(_actor=Depends(require_permission("review:read"))):
    return ApiResponse(
        success=True,
        message="Judge and human agreement metrics fetched",
        data=db.human_review_metrics(tenant_id=_actor["tenant_id"]),
    )


@app.post("/async-runs", response_model=ApiResponse, status_code=202)
def create_async_evaluation(
    request: EvaluationRunCreate,
    http_request: Request,
    actor=Depends(require_permission("run:create")),
):
    from llm_security_platform.app.cost_guardrail import check_and_record_usage, BudgetExceededError
    try:
        check_and_record_usage(actor["tenant_id"], actor["actor"], run_id=None, tokens_count=0)
    except BudgetExceededError as exc:
        raise HTTPException(
            status_code=402,
            detail={
                "error_code": exc.error_code,
                "message": str(exc)
            }
        )

    if request.case_ids and len(request.case_ids) > 100:
        raise HTTPException(
            status_code=400,
            detail="The number of cases in a single evaluation run cannot exceed 100."
        )
        
    matching = db.list_attack_cases(request.case_ids or None, tenant_id=actor["tenant_id"])
    if not matching:
        raise HTTPException(status_code=400, detail="No attack cases are available for this run")
        
    fingerprint = get_run_fingerprint(request, request.case_ids)
    redis_client = get_redis()
    lock_key = f"run_lock:{actor['tenant_id']}:{fingerprint}"
    run_id = str(uuid4())
    
    if redis_client:
        # Atomic lock acquisition using SET with NX and EX
        acquired = redis_client.set(lock_key, run_id, nx=True, ex=300)
        if not acquired:
            existing_run_id = redis_client.get(lock_key) or b"unknown"
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Duplicate evaluation run request. A run with identical parameters is already pending or executing.",
                    "run_id": existing_run_id.decode()
                }
            )

    metadata = {
        "dataset_version": request.versions.get("dataset_version", "attack_cases_v2"),
        "policy_version": request.versions.get("policy_version", request.defense_policy),
        "code_commit_hash": get_git_commit(),
        "model_config": request.inference_config,
        "defense_config": request.defense_config,
        "run_lock_key": lock_key if redis_client else None,
        "fingerprint": fingerprint,
    }
    try:
        run = create_async_run(request, matching, actor["actor"], metadata, tenant_id=actor["tenant_id"], run_id=run_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": str(exc),
                "run_id": None
            }
        )
    request_id = uuid4().hex
    try:
        task_id = dispatch_run(
            run["run_id"],
            tenant_id=actor["tenant_id"],
            trace_id=current_trace_id.get()
        )
    except Exception as exc:
        fail_run(run["run_id"], f"task enqueue failed: {exc}")
        if redis_client:
            try:
                redis_client.delete(lock_key)
            except Exception:
                pass
        raise HTTPException(status_code=503, detail=f"task queue unavailable: {exc}") from exc
    save_audit(
        actor=actor["actor"], role=actor["role"], action="run.create",
        target_type="async_run", target_id=run["run_id"], request_id=request_id,
        run_id=run["run_id"], metadata={"task_id": task_id},
        tenant_id=actor["tenant_id"],
    )
    return ApiResponse(
        success=True,
        message="Evaluation run accepted",
        data=get_async_run(run["run_id"], tenant_id=actor["tenant_id"]),
    )


@app.post("/tasks/execute-run")
def execute_run_task(
    payload: dict,
    http_request: Request,
    authorization: str | None = Header(default=None, alias="Authorization"),
):
    import os
    queue_mode = os.environ.get("LLM_SECURITY_QUEUE_MODE", "local").lower()
    if queue_mode != "cloud":
        raise HTTPException(
            status_code=403,
            detail="Forbidden: /tasks/execute-run is only available when LLM_SECURITY_QUEUE_MODE is set to 'cloud'."
        )
        
    from llm_security_platform.app.security import verify_cloud_tasks_oidc
    verify_cloud_tasks_oidc(authorization)
    
    run_id = payload.get("run_id")
    tenant_id = payload.get("tenant_id", "default")
    trace_id = payload.get("trace_id")
    
    if not run_id:
        raise HTTPException(status_code=400, detail="run_id is required")
        
    run = get_async_run(run_id, tenant_id=tenant_id)
    if run and run.get("status") in {"COMPLETED", "FAILED", "PARTIAL_FAILED", "CANCELLED"}:
        return {"status": "skipped", "message": f"Run {run_id} is already in a terminal state: {run['status']}"}

    from llm_security_platform.app.tasks import run_evaluation_logic
    try:
        res = run_evaluation_logic(run_id, tenant_id=tenant_id, trace_id=trace_id)
        return {"status": "success", "data": res}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/async-runs/{run_id}", response_model=ApiResponse)
def async_run_detail(run_id: str, _actor=Depends(require_permission("run:read"))):
    run = get_async_run(run_id, tenant_id=_actor["tenant_id"])
    if run is None:
        raise HTTPException(status_code=404, detail="async evaluation run not found")
    return ApiResponse(
        success=True,
        message="Async evaluation run fetched",
        data={
            "run": run,
            "report": build_async_report(run_id, tenant_id=_actor["tenant_id"]),
            "cases": list_case_results(run_id, tenant_id=_actor["tenant_id"]),
        },
    )


@app.get("/async-runs/{run_id}/export")
def export_async_run(run_id: str, _actor=Depends(require_permission("run:read"))):
    from fastapi.encoders import jsonable_encoder
    from fastapi.responses import JSONResponse
    
    run = get_async_run(run_id, tenant_id=_actor["tenant_id"])
    if run is None:
        raise HTTPException(status_code=404, detail="async evaluation run not found")
        
    report = build_async_report(run_id, tenant_id=_actor["tenant_id"])
    cases = list_case_results(run_id, tenant_id=_actor["tenant_id"])
    
    export_data = {
        "run": run,
        "report": report,
        "cases": cases
    }
    
    headers = {
        "Content-Disposition": f'attachment; filename="report_{run_id}.json"'
    }
    return JSONResponse(content=jsonable_encoder(export_data), headers=headers)


@app.get("/async-runs", response_model=ApiResponse)
def async_runs(limit: int = 50, _actor=Depends(require_permission("run:read"))):
    if limit < 1 or limit > 200:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 200")
    return ApiResponse(success=True, message="Async runs fetched", data=list_async_runs(limit, tenant_id=_actor["tenant_id"]))


@app.post("/async-runs/{run_id}/cancel", response_model=ApiResponse)
def cancel_async_run(run_id: str, actor=Depends(require_permission("run:cancel"))):
    if get_async_run(run_id, tenant_id=actor["tenant_id"]) is None:
        raise HTTPException(status_code=404, detail="async evaluation run not found")
    if not request_cancel(run_id):
        raise HTTPException(status_code=409, detail="run cannot be cancelled")
    save_audit(
        actor=actor["actor"], role=actor["role"], action="run.cancel",
        target_type="async_run", target_id=run_id, request_id=uuid4().hex, run_id=run_id,
        tenant_id=actor["tenant_id"],
    )
    return ApiResponse(success=True, message="Cancellation requested", data=get_async_run(run_id, tenant_id=actor["tenant_id"]))


@app.post("/async-runs/{run_id}/retry", response_model=ApiResponse, status_code=202)
def retry_async_run(run_id: str, http_request: Request, actor=Depends(require_permission("run:retry"))):
    run = get_async_run(run_id, tenant_id=actor["tenant_id"])
    if run is None:
        raise HTTPException(status_code=404, detail="async evaluation run not found")
    if run.get("retry_count", 0) >= 3:
        raise HTTPException(status_code=400, detail="Maximum retry limit of 3 exceeded for this run.")
    if not prepare_retry(run_id):
        raise HTTPException(status_code=409, detail="only failed runs can be retried")
    task_id = dispatch_run(
        run_id,
        tenant_id=actor["tenant_id"],
        trace_id=current_trace_id.get()
    )
    save_audit(
        actor=actor["actor"], role=actor["role"], action="run.retry",
        target_type="async_run", target_id=run_id, request_id=uuid4().hex, run_id=run_id,
        metadata={"task_id": task_id},
        tenant_id=actor["tenant_id"],
    )
    return ApiResponse(success=True, message="Retry accepted", data=get_async_run(run_id, tenant_id=actor["tenant_id"]))


@app.get("/audit-logs", response_model=ApiResponse)
def audit_logs(run_id: str | None = None, _actor=Depends(require_permission("audit:read"))):
    return ApiResponse(success=True, message="Audit logs fetched", data=list_audits(run_id, tenant_id=_actor["tenant_id"]))


@app.post("/policies", response_model=ApiResponse)
def create_policy_endpoint(payload: DefensePolicyCreate, actor=Depends(require_permission("admin:write"))):
    db.save_defense_policy(
        name=payload.name,
        version=payload.version,
        description=payload.description,
        config=payload.config,
        tenant_id=actor["tenant_id"]
    )
    return ApiResponse(
        success=True,
        message="Defense policy version saved/updated",
        data={"name": payload.name, "version": payload.version}
    )


@app.get("/policies", response_model=ApiResponse)
def list_policies_endpoint(_actor=Depends(require_permission("run:read"))):
    return ApiResponse(
        success=True,
        message="Defense policies fetched",
        data=db.list_defense_policies(tenant_id=_actor["tenant_id"])
    )


@app.get("/policies/{name}/{version}", response_model=ApiResponse)
def get_policy_endpoint(name: str, version: str, _actor=Depends(require_permission("run:read"))):
    policy = db.get_defense_policy(name, version, tenant_id=_actor["tenant_id"])
    if policy is None:
        raise HTTPException(status_code=404, detail="Defense policy version not found")
    return ApiResponse(
        success=True,
        message="Defense policy version fetched",
        data=policy
    )


@app.get("/metrics")
def metrics_endpoint(_actor=Depends(require_permission("audit:read"))):
    from fastapi.responses import PlainTextResponse
    from llm_security_platform.app.metrics import generate_prometheus_exposition
    return PlainTextResponse(generate_prometheus_exposition())


WEB_ROOT = Path(__file__).resolve().parents[1] / "web"
if WEB_ROOT.is_dir():
    app.mount("/console", StaticFiles(directory=WEB_ROOT, html=True), name="security-console")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str | None = Query(None)):
    if not token:
        await websocket.close(code=1008)
        return

    from llm_security_platform.app.security import decode_jwt
    principal = decode_jwt(token)
    if not principal:
        await websocket.close(code=1008)
        return

    role = principal.get("role")
    tenant_id = principal.get("tenant_id")
    actor = principal.get("actor")

    from llm_security_platform.app.security import ROLE_PERMISSIONS
    permissions = ROLE_PERMISSIONS.get(role, set())
    if "*" not in permissions and "run:read" not in permissions:
        await websocket.close(code=1008)
        return

    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_text(f"Echo [{tenant_id}] to {actor} ({role}): {data}")
    except WebSocketDisconnect:
        pass
