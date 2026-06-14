from contextlib import contextmanager
from uuid import uuid4

from sqlalchemy import create_engine, delete, event, select
from sqlalchemy.orm import Session, sessionmaker

from llm_security_platform.app.config import DATABASE_URL
from llm_security_platform.app.production_models import AsyncCaseResult, AsyncRun, AuditLog, Base, utc_now


TERMINAL_STATUSES = {"PARTIAL_FAILED", "FAILED", "COMPLETED", "CANCELLED"}
_engine = None
_engine_url = None


def get_engine(database_url=None):
    global _engine, _engine_url
    url = database_url or DATABASE_URL
    if _engine is None or _engine_url != url:
        kwargs = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
        _engine = create_engine(url, **kwargs)
        if url.startswith("sqlite"):
            @event.listens_for(_engine, "connect")
            def enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()
        _engine_url = url
    return _engine


def init_production_db(database_url=None):
    Base.metadata.create_all(get_engine(database_url))


@contextmanager
def session_scope(database_url=None):
    factory = sessionmaker(bind=get_engine(database_url), expire_on_commit=False)
    with factory.begin() as session:
        yield session


def serialize_run(run):
    return {
        "run_id": run.id,
        "name": run.name,
        "status": run.status,
        "provider": run.provider,
        "model": run.model,
        "defense_policy": run.defense_policy,
        "total_cases": run.total_cases,
        "completed_cases": run.completed_cases,
        "success_cases": run.success_cases,
        "failed_cases": run.failed_cases,
        "progress": run.progress,
        "error_summary": run.error_summary,
        "cancel_requested": run.cancel_requested,
        "retry_count": run.retry_count,
        "celery_task_id": run.celery_task_id,
        "run_metadata": run.run_metadata_json,
        "created_by": run.created_by,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }


def create_async_run(request, cases, actor, metadata):
    run_id = str(uuid4())
    request_data = request.model_dump(by_alias=True)
    model = request.model or ("mock-vulnerable-model" if request.provider == "mock" else "default")
    with session_scope() as session:
        run = AsyncRun(
            id=run_id,
            name=request.name,
            provider=request.provider,
            model=model,
            defense_policy=request.defense_policy,
            request_json=request_data,
            run_metadata_json=metadata,
            total_cases=len(cases),
            created_by=actor,
        )
        session.add(run)
        session.flush()
        session.add_all(
            AsyncCaseResult(run_id=run_id, case_id=case["case_id"], case_json=case)
            for case in cases
        )
    return get_async_run(run_id)


def get_async_run(run_id):
    with session_scope() as session:
        run = session.get(AsyncRun, run_id)
        return serialize_run(run) if run else None


def list_async_runs(limit=50):
    with session_scope() as session:
        rows = session.scalars(
            select(AsyncRun).order_by(AsyncRun.created_at.desc()).limit(limit)
        ).all()
        return [serialize_run(row) for row in rows]


def get_async_request(run_id):
    with session_scope() as session:
        run = session.get(AsyncRun, run_id)
        return dict(run.request_json) if run else None


def list_case_results(run_id):
    with session_scope() as session:
        rows = session.scalars(
            select(AsyncCaseResult).where(AsyncCaseResult.run_id == run_id).order_by(AsyncCaseResult.id)
        ).all()
        return [
            {
                "case_id": row.case_id,
                "status": row.status,
                "attempts": row.attempts,
                "result": row.result_json,
                "error": row.error,
            }
            for row in rows
        ]


def build_async_report(run_id):
    run = get_async_run(run_id)
    if run is None:
        return None
    rows = list_case_results(run_id)
    results = [row["result"] for row in rows if row["result"]]
    attacks = [item for item in results if item["risk_type"] != "benign"]
    benign = [item for item in results if item["risk_type"] == "benign"]
    successful_attacks = sum(bool(item["detector"]["attack_success"]) for item in attacks)
    raw_compromises = sum(
        bool(item.get("raw_detector", item["detector"])["attack_success"])
        for item in attacks
    )
    benign_completed = sum(bool(item["detector"].get("business_completed")) for item in benign)
    benign_blocked = sum(item["status"] == "blocked" for item in benign)
    latencies = sorted(float(item.get("latency_ms", 0)) for item in results)

    def percentile(values, fraction):
        if not values:
            return 0.0
        index = max(0, min(len(values) - 1, int(len(values) * fraction + 0.9999) - 1))
        return round(values[index], 2)

    return {
        "run_id": run_id,
        "status": run["status"],
        "total_cases": run["total_cases"],
        "completed_cases": run["completed_cases"],
        "failed_cases": run["failed_cases"],
        "attack_success_rate": round(successful_attacks / len(attacks), 4) if attacks else 0.0,
        "raw_model_compromise_rate": round(raw_compromises / len(attacks), 4)
        if attacks else 0.0,
        "delivered_attack_success_rate": round(successful_attacks / len(attacks), 4)
        if attacks else 0.0,
        "normal_task_success_rate": round(benign_completed / len(benign), 4) if benign else 0.0,
        "false_positive_rate": round(benign_blocked / len(benign), 4) if benign else 0.0,
        "p50_latency_ms": percentile(latencies, 0.5),
        "p95_latency_ms": percentile(latencies, 0.95),
        "total_tokens": sum(item.get("token_usage", {}).get("total_tokens", 0) for item in results),
        "estimated_total_cost": round(sum(float(item.get("estimated_cost", 0)) for item in results), 8),
    }


def set_task_id(run_id, task_id):
    with session_scope() as session:
        run = session.get(AsyncRun, run_id)
        if run:
            run.celery_task_id = task_id
            run.updated_at = utc_now()


def start_run(run_id):
    with session_scope() as session:
        run = session.get(AsyncRun, run_id)
        if not run or run.status in {"COMPLETED", "CANCELLED"}:
            return False
        run.status = "RUNNING"
        run.started_at = run.started_at or utc_now()
        run.completed_at = None
        run.updated_at = utc_now()
        return True


def pending_cases(run_id):
    with session_scope() as session:
        rows = session.scalars(select(AsyncCaseResult).where(
            AsyncCaseResult.run_id == run_id,
            AsyncCaseResult.status != "COMPLETED",
        ).order_by(AsyncCaseResult.id)).all()
        return [{"case_id": row.case_id, "case": row.case_json} for row in rows]


def begin_case(run_id, case_id):
    with session_scope() as session:
        row = session.scalar(select(AsyncCaseResult).where(
            AsyncCaseResult.run_id == run_id, AsyncCaseResult.case_id == case_id
        ))
        if not row or row.status == "COMPLETED":
            return False
        row.status = "RUNNING"
        row.attempts += 1
        row.error = None
        row.started_at = utc_now()
        return True


def finish_case(run_id, case_id, result=None, error=None):
    with session_scope() as session:
        row = session.scalar(select(AsyncCaseResult).where(
            AsyncCaseResult.run_id == run_id, AsyncCaseResult.case_id == case_id
        ))
        if not row:
            return
        row.status = "FAILED" if error else "COMPLETED"
        row.result_json = result
        row.error = error
        row.completed_at = utc_now()
    refresh_progress(run_id)


def refresh_progress(run_id):
    with session_scope() as session:
        run = session.get(AsyncRun, run_id)
        rows = session.scalars(select(AsyncCaseResult).where(AsyncCaseResult.run_id == run_id)).all()
        if not run:
            return
        run.success_cases = sum(row.status == "COMPLETED" for row in rows)
        run.failed_cases = sum(row.status == "FAILED" for row in rows)
        run.completed_cases = run.success_cases + run.failed_cases
        run.progress = round(run.completed_cases / run.total_cases, 4) if run.total_cases else 1.0
        run.updated_at = utc_now()


def finalize_run(run_id):
    refresh_progress(run_id)
    with session_scope() as session:
        run = session.get(AsyncRun, run_id)
        if not run:
            return None
        if run.cancel_requested:
            run.status = "CANCELLED"
        elif run.failed_cases == 0:
            run.status = "COMPLETED"
        elif run.success_cases == 0:
            run.status = "FAILED"
        else:
            run.status = "PARTIAL_FAILED"
        run.completed_at = utc_now()
        run.updated_at = utc_now()
        return run.status


def fail_run(run_id, error):
    with session_scope() as session:
        run = session.get(AsyncRun, run_id)
        if not run or run.status == "COMPLETED":
            return False
        run.status = "FAILED"
        run.error_summary = str(error)
        run.completed_at = utc_now()
        run.updated_at = utc_now()
        return True


def request_cancel(run_id):
    with session_scope() as session:
        run = session.get(AsyncRun, run_id)
        if not run or run.status in TERMINAL_STATUSES:
            return False
        run.cancel_requested = True
        run.updated_at = utc_now()
        return True


def is_cancel_requested(run_id):
    with session_scope() as session:
        run = session.get(AsyncRun, run_id)
        return bool(run and run.cancel_requested)


def prepare_retry(run_id):
    with session_scope() as session:
        run = session.get(AsyncRun, run_id)
        if not run or run.status not in {"FAILED", "PARTIAL_FAILED"}:
            return False
        run.status = "PENDING"
        run.cancel_requested = False
        run.retry_count += 1
        run.completed_at = None
        run.error_summary = None
        run.updated_at = utc_now()
        return True


def save_audit(*, actor, role, action, target_type, target_id, request_id, run_id=None, metadata=None):
    with session_scope() as session:
        session.add(AuditLog(
            actor=actor, role=role, action=action, target_type=target_type,
            target_id=str(target_id), request_id=request_id, run_id=run_id,
            metadata_json=metadata or {},
        ))


def list_audits(run_id=None):
    with session_scope() as session:
        query = select(AuditLog).order_by(AuditLog.id.desc())
        if run_id:
            query = query.where(AuditLog.run_id == run_id)
        rows = session.scalars(query).all()
        return [{
            "id": row.id, "actor": row.actor, "role": row.role, "action": row.action,
            "target_type": row.target_type, "target_id": row.target_id,
            "request_id": row.request_id, "run_id": row.run_id,
            "metadata": row.metadata_json, "timestamp": row.created_at.isoformat(),
        } for row in rows]


def delete_run_for_test(run_id):
    with session_scope() as session:
        session.execute(delete(AsyncRun).where(AsyncRun.id == run_id))
