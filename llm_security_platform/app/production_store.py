from contextlib import contextmanager
import contextvars
import json
import os
from uuid import uuid4
from cryptography.fernet import Fernet

from sqlalchemy import create_engine, delete, event, select, text, inspect
from sqlalchemy.orm import sessionmaker

from llm_security_platform.app.config import DATABASE_URL
from llm_security_platform.app.production_models import AsyncCaseResult, AsyncRun, AuditLog, TenantConfig, Base, utc_now

# Context variable to hold the current tenant ID dynamically for multi-tenant schema routing
current_tenant = contextvars.ContextVar("current_tenant", default="default")

DEFAULT_ENCRYPTION_KEY = "7S64g16Hk3WjGqY0oP9zLmN4vB8xCxX9vB8xCxX9vB8="
ENCRYPTION_KEY = os.environ.get("LLM_SECURITY_ENCRYPTION_KEY")
from llm_security_platform.app.config import LLM_SECURITY_ENV
is_prod = (LLM_SECURITY_ENV == "production")

if is_prod:
    if not ENCRYPTION_KEY:
        raise ValueError(
            "CRITICAL SECURITY ERROR: LLM_SECURITY_ENCRYPTION_KEY environment variable is required and must be configured in production."
        )
    if ENCRYPTION_KEY == DEFAULT_ENCRYPTION_KEY:
        raise ValueError(
            "CRITICAL SECURITY ERROR: Default Fernet encryption key cannot be used in production environments. "
            "Please configure a unique secure key in the LLM_SECURITY_ENCRYPTION_KEY environment variable."
        )
else:
    if not ENCRYPTION_KEY:
        ENCRYPTION_KEY = DEFAULT_ENCRYPTION_KEY
_fernet = Fernet(ENCRYPTION_KEY.encode())

def encrypt_data(data: str) -> str:
    if not data:
        return ""
    return _fernet.encrypt(data.encode()).decode()

def decrypt_data(token: str) -> str:
    if not token:
        return ""
    try:
        return _fernet.decrypt(token.encode()).decode()
    except Exception:
        return token


TERMINAL_STATUSES = {"PARTIAL_FAILED", "FAILED", "COMPLETED", "CANCELLED"}
_engine = None
_engine_url = None
_initialized_schemas = set()


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
    engine = get_engine(database_url)
    Base.metadata.create_all(engine)
    # Ensure tenant_id column exists for async_evaluation_runs and operation_audit_logs
    inspector = inspect(engine)
    for table_name in ["async_evaluation_runs", "operation_audit_logs"]:
        if table_name in inspector.get_table_names():
            columns = [c["name"] for c in inspector.get_columns(table_name)]
            if "tenant_id" not in columns:
                with engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN tenant_id VARCHAR(100) DEFAULT 'default'"))


@contextmanager
def session_scope(database_url=None):
    tenant_id = current_tenant.get()
    factory = sessionmaker(bind=get_engine(database_url), expire_on_commit=False)
    
    import re
    is_valid_tenant = bool(tenant_id and re.match(r"^[a-zA-Z0-9_]+$", tenant_id))
    
    with factory.begin() as session:
        url = str(session.bind.url)
        is_postgres = url.startswith("postgresql")
        print(f"[DB_DEBUG] session_scope tenant_id: {tenant_id}, url: {url}", flush=True)
        # Multi-tenant schema routing for PostgreSQL
        if is_valid_tenant and tenant_id != "default" and is_postgres:
            print(f"[DB_DEBUG] Creating schema and setting LOCAL search_path to: {tenant_id}", flush=True)
            session.execute(text(f"CREATE SCHEMA IF NOT EXISTS {tenant_id}"))
            session.execute(text(f"SET LOCAL search_path TO {tenant_id}"))
            res = session.execute(text("SHOW search_path")).fetchone()
            print(f"[DB_DEBUG] Current search_path inside session: {res}", flush=True)
            global _initialized_schemas
            if tenant_id not in _initialized_schemas:
                Base.metadata.create_all(session.connection())
                _initialized_schemas.add(tenant_id)
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
        "tenant_id": run.tenant_id,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }


def get_run_fingerprint(request, case_ids: list[str]) -> str:
    import hashlib
    data = {
        "provider": request.provider,
        "model": request.model,
        "defense_policy": request.defense_policy,
        "case_ids": sorted(case_ids),
        "versions": request.versions,
        "inference_config": request.inference_config,
        "defense_config": request.defense_config,
    }
    serialized = json.dumps(data, sort_keys=True)
    return hashlib.sha256(serialized.encode()).hexdigest()


def create_async_run(request, cases, actor, metadata, tenant_id="default", run_id=None):
    run_id = run_id or str(uuid4())
    request_data = request.model_dump(by_alias=True)
    model = request.model or ("mock-vulnerable-model" if request.provider == "mock" else "default")
    fingerprint = metadata.get("fingerprint")
    with session_scope() as session:
        if fingerprint:
            active_runs = session.scalars(
                select(AsyncRun).where(
                    AsyncRun.tenant_id == tenant_id,
                    AsyncRun.status.notin_(TERMINAL_STATUSES)
                )
            ).all()
            from datetime import datetime, timezone
            for r in active_runs:
                if r.run_metadata_json and r.run_metadata_json.get("fingerprint") == fingerprint:
                    now_val = datetime.now(timezone.utc)
                    last_active = r.updated_at or r.created_at
                    if last_active.tzinfo is None:
                        last_active = last_active.replace(tzinfo=timezone.utc)
                    delta = (now_val - last_active).total_seconds()
                    from llm_security_platform.app.config import STALE_RUN_TIMEOUT_SECONDS
                    if delta > STALE_RUN_TIMEOUT_SECONDS:
                        r.status = "FAILED"
                        r.error_summary = "Task timed out or worker terminated unexpectedly (Stale Run)."
                        r.completed_at = now_val
                        session.add(r)
                        continue
                    raise ValueError(
                        f"Duplicate evaluation run request. A run with identical parameters is already active (Run ID: {r.id})."
                    )
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
            tenant_id=tenant_id,
        )
        session.add(run)
        session.flush()
        session.add_all(
            AsyncCaseResult(run_id=run_id, case_id=case["case_id"], case_json=case)
            for case in cases
        )
    return get_async_run(run_id, tenant_id=tenant_id)


def get_async_run(run_id, tenant_id=None):
    with session_scope() as session:
        run = session.get(AsyncRun, run_id)
        if not run:
            return None
        if tenant_id and run.tenant_id != tenant_id:
            return None
        return serialize_run(run)


def list_async_runs(limit=50, tenant_id="default"):
    with session_scope() as session:
        rows = session.scalars(
            select(AsyncRun).where(AsyncRun.tenant_id == tenant_id).order_by(AsyncRun.created_at.desc()).limit(limit)
        ).all()
        return [serialize_run(row) for row in rows]


def get_async_request(run_id):
    with session_scope() as session:
        run = session.get(AsyncRun, run_id)
        return dict(run.request_json) if run else None


def list_case_results(run_id, tenant_id=None):
    if tenant_id:
        with session_scope() as session:
            run = session.get(AsyncRun, run_id)
            if not run or run.tenant_id != tenant_id:
                return []
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


def build_async_report(run_id, tenant_id=None):
    run = get_async_run(run_id, tenant_id=tenant_id)
    if run is None:
        return None
    rows = list_case_results(run_id, tenant_id=tenant_id)
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


def save_audit(*, actor, role, action, target_type, target_id, request_id, run_id=None, metadata=None, tenant_id="default"):
    with session_scope() as session:
        session.add(AuditLog(
            actor=actor, role=role, action=action, target_type=target_type,
            target_id=str(target_id), request_id=request_id, run_id=run_id,
            metadata_json=metadata or {},
            tenant_id=tenant_id,
        ))


def list_audits(run_id=None, tenant_id="default"):
    with session_scope() as session:
        query = select(AuditLog).where(AuditLog.tenant_id == tenant_id).order_by(AuditLog.id.desc())
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


def save_tenant_config(tenant_id: str, keys_dict: dict, qps_limit: int = 10):
    encrypted_keys = encrypt_data(json.dumps(keys_dict))
    token = current_tenant.set("default")
    try:
        with session_scope() as session:
            config = session.get(TenantConfig, tenant_id)
            if not config:
                config = TenantConfig(
                    tenant_id=tenant_id,
                    encrypted_keys_json=encrypted_keys,
                    qps_limit=qps_limit
                )
                session.add(config)
            else:
                config.encrypted_keys_json = encrypted_keys
                config.qps_limit = qps_limit
    finally:
        current_tenant.reset(token)


def get_tenant_config(tenant_id: str) -> dict:
    token = current_tenant.set("default")
    try:
        with session_scope() as session:
            config = session.get(TenantConfig, tenant_id)
            if not config:
                return {"tenant_id": tenant_id, "keys": {}, "qps_limit": 10}
            
            decrypted_json = decrypt_data(config.encrypted_keys_json)
            try:
                keys = json.loads(decrypted_json) if decrypted_json else {}
            except Exception:
                keys = {}
            return {
                "tenant_id": tenant_id,
                "keys": keys,
                "qps_limit": config.qps_limit
            }
    finally:
        current_tenant.reset(token)
