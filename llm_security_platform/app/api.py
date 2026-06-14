from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from llm_security_platform.app import db
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
)
from llm_security_platform.app.security import require_permission
from llm_security_platform.app.seed import seed_cases


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


@app.get("/health", response_model=ApiResponse)
def health():
    return ApiResponse(success=True, message="ok", data={"service": "llm-security-platform"})


@app.get("/cases", response_model=ApiResponse)
def cases(_actor=Depends(require_permission("case:read"))):
    return ApiResponse(success=True, message="Attack cases fetched", data=db.list_attack_cases())


@app.post("/cases", response_model=ApiResponse)
def create_case(case: AttackCaseCreate, _actor=Depends(require_permission("admin:write"))):
    db.save_attack_case(case)
    return ApiResponse(success=True, message="Attack case saved", data={"case_id": case.case_id})


@app.post("/cases/seed", response_model=ApiResponse)
def seed_default_cases(_actor=Depends(require_permission("admin:write"))):
    count = seed_cases()
    return ApiResponse(success=True, message="Default attack cases seeded", data={"count": count})


@app.post("/datasets/import", response_model=ApiResponse)
def import_dataset(payload: DatasetImport, actor=Depends(require_permission("admin:write"))):
    for case in payload.cases:
        case.metadata["dataset_version"] = payload.dataset_version
        db.save_attack_case(case)
    save_audit(
        actor=actor["actor"], role=actor["role"], action="dataset.import",
        target_type="dataset", target_id=payload.dataset_version,
        request_id=uuid4().hex, metadata={"case_count": len(payload.cases)},
    )
    return ApiResponse(
        success=True,
        message="Dataset imported",
        data={"dataset_version": payload.dataset_version, "case_count": len(payload.cases)},
    )


@app.post("/runs", response_model=ApiResponse)
def run_evaluation(request: EvaluationRunCreate, _actor=Depends(require_permission("run:create"))):
    try:
        report = execute_run(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ApiResponse(success=True, message="Evaluation completed", data=report.model_dump())


@app.get("/runs/{run_id}", response_model=ApiResponse)
def run_detail(run_id: int, _actor=Depends(require_permission("run:read"))):
    report = build_report(run_id)
    if report is None:
        raise HTTPException(status_code=404, detail="evaluation run not found")
    return ApiResponse(
        success=True,
        message="Evaluation run fetched",
        data={"report": report.model_dump(), "results": db.list_results(run_id)},
    )


@app.get("/runs/{run_id}/defense-audits", response_model=ApiResponse)
def run_defense_audits(run_id: int, _actor=Depends(require_permission("audit:read"))):
    if db.get_run(run_id) is None:
        raise HTTPException(status_code=404, detail="evaluation run not found")
    return ApiResponse(
        success=True,
        message="Defense audit records fetched",
        data=db.list_defense_audits(run_id),
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
    )
    return ApiResponse(success=True, message="Defense comparison completed", data=comparison)


@app.post("/model-comparisons", response_model=ApiResponse)
def model_comparison(request: ModelComparisonCreate, _actor=Depends(require_permission("run:create"))):
    return ApiResponse(
        success=True,
        message="Model comparison completed",
        data=compare_models(request),
    )


@app.post("/layered-assessments", response_model=ApiResponse)
def create_layered_assessment(
    request: LayeredAssessmentCreate,
    _actor=Depends(require_permission("run:create")),
):
    matching = db.list_attack_cases([request.case_id])
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
    )
    return ApiResponse(
        success=True,
        message="Layered assessment completed",
        data={"assessment_id": assessment_id, "assessment": assessment.model_dump()},
    )


@app.get("/human-reviews", response_model=ApiResponse)
def human_reviews(status: str | None = "pending", _actor=Depends(require_permission("review:read"))):
    if status not in {None, "pending", "completed"}:
        raise HTTPException(status_code=400, detail="unsupported review status")
    return ApiResponse(
        success=True,
        message="Human review queue fetched",
        data=db.list_review_items(status),
    )


@app.patch("/human-reviews/{review_id}", response_model=ApiResponse)
def update_human_review(
    review_id: int,
    update: HumanReviewUpdate,
    _actor=Depends(require_permission("review:write")),
):
    if not db.complete_review(review_id, update):
        raise HTTPException(status_code=404, detail="pending review item not found")
    save_audit(
        actor=_actor["actor"], role=_actor["role"], action="review.complete",
        target_type="human_review", target_id=review_id, request_id=uuid4().hex,
        metadata={"label": update.human_final_label, "attack_success": update.human_attack_success},
    )
    return ApiResponse(
        success=True,
        message="Human review completed",
        data={"review_id": review_id},
    )


@app.get("/human-reviews/metrics", response_model=ApiResponse)
def human_review_metrics(_actor=Depends(require_permission("review:read"))):
    return ApiResponse(
        success=True,
        message="Judge and human agreement metrics fetched",
        data=db.human_review_metrics(),
    )


@app.post("/async-runs", response_model=ApiResponse, status_code=202)
def create_async_evaluation(
    request: EvaluationRunCreate,
    actor=Depends(require_permission("run:create")),
):
    matching = db.list_attack_cases(request.case_ids or None)
    if not matching:
        raise HTTPException(status_code=400, detail="No attack cases are available for this run")
    metadata = {
        "dataset_version": request.versions.get("dataset_version", "attack_cases_v2"),
        "policy_version": request.versions.get("policy_version", request.defense_policy),
        "code_commit_hash": get_git_commit(),
        "model_config": request.inference_config,
        "defense_config": request.defense_config,
    }
    run = create_async_run(request, matching, actor["actor"], metadata)
    request_id = uuid4().hex
    try:
        task_id = dispatch_run(run["run_id"])
    except Exception as exc:
        fail_run(run["run_id"], f"task enqueue failed: {exc}")
        raise HTTPException(status_code=503, detail=f"task queue unavailable: {exc}") from exc
    save_audit(
        actor=actor["actor"], role=actor["role"], action="run.create",
        target_type="async_run", target_id=run["run_id"], request_id=request_id,
        run_id=run["run_id"], metadata={"task_id": task_id},
    )
    return ApiResponse(
        success=True,
        message="Evaluation run accepted",
        data=get_async_run(run["run_id"]),
    )


@app.get("/async-runs/{run_id}", response_model=ApiResponse)
def async_run_detail(run_id: str, _actor=Depends(require_permission("run:read"))):
    run = get_async_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="async evaluation run not found")
    return ApiResponse(
        success=True,
        message="Async evaluation run fetched",
        data={
            "run": run,
            "report": build_async_report(run_id),
            "cases": list_case_results(run_id),
        },
    )


@app.get("/async-runs", response_model=ApiResponse)
def async_runs(limit: int = 50, _actor=Depends(require_permission("run:read"))):
    if limit < 1 or limit > 200:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 200")
    return ApiResponse(success=True, message="Async runs fetched", data=list_async_runs(limit))


@app.post("/async-runs/{run_id}/cancel", response_model=ApiResponse)
def cancel_async_run(run_id: str, actor=Depends(require_permission("run:cancel"))):
    if not request_cancel(run_id):
        raise HTTPException(status_code=409, detail="run cannot be cancelled")
    save_audit(
        actor=actor["actor"], role=actor["role"], action="run.cancel",
        target_type="async_run", target_id=run_id, request_id=uuid4().hex, run_id=run_id,
    )
    return ApiResponse(success=True, message="Cancellation requested", data=get_async_run(run_id))


@app.post("/async-runs/{run_id}/retry", response_model=ApiResponse, status_code=202)
def retry_async_run(run_id: str, actor=Depends(require_permission("run:retry"))):
    if not prepare_retry(run_id):
        raise HTTPException(status_code=409, detail="only failed runs can be retried")
    task_id = dispatch_run(run_id)
    save_audit(
        actor=actor["actor"], role=actor["role"], action="run.retry",
        target_type="async_run", target_id=run_id, request_id=uuid4().hex, run_id=run_id,
        metadata={"task_id": task_id},
    )
    return ApiResponse(success=True, message="Retry accepted", data=get_async_run(run_id))


@app.get("/audit-logs", response_model=ApiResponse)
def audit_logs(run_id: str | None = None, _actor=Depends(require_permission("audit:read"))):
    return ApiResponse(success=True, message="Audit logs fetched", data=list_audits(run_id))


WEB_ROOT = Path(__file__).resolve().parents[1] / "web"
if WEB_ROOT.is_dir():
    app.mount("/console", StaticFiles(directory=WEB_ROOT, html=True), name="security-console")
