import os
import logging
from datetime import UTC, datetime
from llm_security_platform.app.middleware import get_redis

logger = logging.getLogger("llm_security_platform.cost_guardrail")

# Budget limits from environment variables
MAX_TOKENS_PER_RUN = int(os.environ.get("LLM_SECURITY_MAX_TOKENS_PER_RUN", 50000))
MAX_TOKENS_PER_USER_DAILY = int(os.environ.get("LLM_SECURITY_MAX_TOKENS_PER_USER_DAILY", 200000))
MAX_TOKENS_PER_TENANT_DAILY = int(os.environ.get("LLM_SECURITY_MAX_TOKENS_PER_TENANT_DAILY", 1000000))

# Local in-memory fallback store for budgets when Redis is offline/disabled
_in_memory_budgets = {}

class BudgetExceededError(Exception):
    def __init__(self, message, error_code="BUDGET_EXCEEDED"):
        super().__init__(message)
        self.error_code = error_code

def get_current_date_str():
    return datetime.now(UTC).strftime("%Y-%m-%d")

def _get_key_val(key: str) -> int:
    r = get_redis()
    if r:
        try:
            val = r.get(key)
            return int(val) if val else 0
        except Exception as exc:
            logger.debug(f"Redis get failed for {key}: {exc}")
    return _in_memory_budgets.get(key, 0)

def _incr_key_val(key: str, amount: int) -> int:
    r = get_redis()
    if r:
        try:
            pipe = r.pipeline()
            pipe.incrby(key, amount)
            pipe.expire(key, 86400)  # 24 hours TTL
            res = pipe.execute()
            return int(res[0])
        except Exception as exc:
            logger.debug(f"Redis incrby failed for {key}: {exc}")
    
    current = _in_memory_budgets.get(key, 0)
    new_val = current + amount
    _in_memory_budgets[key] = new_val
    return new_val

def _load_initial_from_db(tenant_id: str, user_id: str, date_str: str) -> tuple[int, int]:
    """
    Loads initial daily counts from the SQL database.
    Returns (tenant_total, user_total).
    """
    from llm_security_platform.app.production_store import session_scope
    from llm_security_platform.app.production_models import TenantBudgetMeter
    from sqlalchemy import select, func

    tenant_total = 0
    user_total = 0
    try:
        with session_scope() as session:
            # Query tenant total for the date across all users
            stmt_tenant = select(func.sum(TenantBudgetMeter.tokens_consumed)).where(
                TenantBudgetMeter.tenant_id == tenant_id,
                TenantBudgetMeter.date_str == date_str
            )
            res_tenant = session.execute(stmt_tenant).scalar()
            if res_tenant is not None:
                tenant_total = int(res_tenant)

            # Query user total for the date
            stmt_user = select(func.sum(TenantBudgetMeter.tokens_consumed)).where(
                TenantBudgetMeter.tenant_id == tenant_id,
                TenantBudgetMeter.user_id == user_id,
                TenantBudgetMeter.date_str == date_str
            )
            res_user = session.execute(stmt_user).scalar()
            if res_user is not None:
                user_total = int(res_user)
    except Exception as exc:
        logger.warning(f"Failed to load budget from database: {exc}")
    return tenant_total, user_total


def _get_or_load_budgets(tenant_id: str, user_id: str, date_str: str) -> tuple[int, int]:
    tenant_key = f"budget:tenant:{tenant_id}:{date_str}"
    user_key = f"budget:user:{tenant_id}:{user_id}:{date_str}"
    r = get_redis()
    
    tenant_val = None
    user_val = None
    
    if r:
        try:
            tenant_val = r.get(tenant_key)
            user_val = r.get(user_key)
        except Exception as exc:
            logger.debug(f"Redis get failed during budget query: {exc}")
            
    # If using memory fallback
    if not r:
        if tenant_key not in _in_memory_budgets or user_key not in _in_memory_budgets:
            db_tenant, db_user = _load_initial_from_db(tenant_id, user_id, date_str)
            if tenant_key not in _in_memory_budgets:
                _in_memory_budgets[tenant_key] = db_tenant
            if user_key not in _in_memory_budgets:
                _in_memory_budgets[user_key] = db_user
        return _in_memory_budgets[tenant_key], _in_memory_budgets[user_key]

    # If Redis is active, load from DB if either key is None
    if tenant_val is None or user_val is None:
        db_tenant, db_user = _load_initial_from_db(tenant_id, user_id, date_str)
        try:
            if tenant_val is None:
                r.set(tenant_key, db_tenant, ex=86400)
                tenant_val = str(db_tenant).encode()
            if user_val is None:
                r.set(user_key, db_user, ex=86400)
                user_val = str(db_user).encode()
        except Exception as exc:
            logger.debug(f"Redis set failed during budget init load: {exc}")
            
    return int(tenant_val) if tenant_val else 0, int(user_val) if user_val else 0


def _sync_incr_to_db(tenant_id: str, user_id: str, date_str: str, amount: int):
    from llm_security_platform.app.production_store import session_scope
    from llm_security_platform.app.production_models import TenantBudgetMeter
    try:
        with session_scope() as session:
            meter = session.get(TenantBudgetMeter, (tenant_id, user_id, date_str))
            if not meter:
                meter = TenantBudgetMeter(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    date_str=date_str,
                    tokens_consumed=amount
                )
                session.add(meter)
            else:
                meter.tokens_consumed += amount
    except Exception as exc:
        logger.error(f"Failed to sync budget increment to database: {exc}")


def check_and_record_usage(tenant_id: str, user_id: str, run_id: str, tokens_count: int):
    """
    Checks token budget compliance across:
    - Current run token limit
    - User daily token limit
    - Tenant daily token limit
    
    If limits are exceeded, raises BudgetExceededError.
    Otherwise, increments and commits the usage.
    """
    tenant_id = tenant_id or "default"
    user_id = user_id or "system"
    run_id = run_id or "default"

    date_str = get_current_date_str()
    tenant_key = f"budget:tenant:{tenant_id}:{date_str}"
    user_key = f"budget:user:{tenant_id}:{user_id}:{date_str}"
    run_key = f"budget:run:{run_id}"

    # Pre-check budgets
    current_run = _get_key_val(run_key)
    current_tenant, current_user = _get_or_load_budgets(tenant_id, user_id, date_str)

    if tokens_count > 0:
        if current_run + tokens_count > MAX_TOKENS_PER_RUN:
            raise BudgetExceededError(
                message=f"Evaluation Run token budget exceeded. Limit: {MAX_TOKENS_PER_RUN}, Current+Requested: {current_run + tokens_count}",
                error_code="RUN_BUDGET_EXCEEDED"
            )

        if current_user + tokens_count > MAX_TOKENS_PER_USER_DAILY:
            raise BudgetExceededError(
                message=f"Daily token budget exceeded for User: {user_id}. Limit: {MAX_TOKENS_PER_USER_DAILY}, Current+Requested: {current_user + tokens_count}",
                error_code="USER_BUDGET_EXCEEDED"
            )

        if current_tenant + tokens_count > MAX_TOKENS_PER_TENANT_DAILY:
            raise BudgetExceededError(
                message=f"Daily token budget exceeded for Tenant: {tenant_id}. Limit: {MAX_TOKENS_PER_TENANT_DAILY}, Current+Requested: {current_tenant + tokens_count}",
                error_code="TENANT_BUDGET_EXCEEDED"
            )

    # Commit usage
    if tokens_count != 0:
        _incr_key_val(run_key, tokens_count)
        _incr_key_val(user_key, tokens_count)
        _incr_key_val(tenant_key, tokens_count)
        _sync_incr_to_db(tenant_id, user_id, date_str, tokens_count)
        logger.debug(f"Recorded usage: run={run_id} tenant={tenant_id} user={user_id} added={tokens_count}")
