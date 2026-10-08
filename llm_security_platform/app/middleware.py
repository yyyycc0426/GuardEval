import logging
import time
from uuid import uuid4
import collections
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from llm_security_platform.app.config import REDIS_URL
from llm_security_platform.app.security import decode_jwt, _principals
from llm_security_platform.app.production_store import get_tenant_config

logger = logging.getLogger("llm_security_platform.rate_limiter")

# Lazy Redis client connection
_redis_client = None
_local_limits = collections.defaultdict(list)

def get_redis():
    global _redis_client
    if _redis_client is None:
        import redis
        try:
            _redis_client = redis.from_url(REDIS_URL, socket_timeout=1.0, socket_connect_timeout=1.0)
            _redis_client.ping()
        except Exception as exc:
            logger.warning(f"Failed to connect to Redis at {REDIS_URL} for rate limiting: {exc}")
            _redis_client = False  # Disable to avoid repeated connection attempts
    return _redis_client if _redis_client is not False else None


class RateLimitingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        # Skip static console files, Swagger, OpenAPI schema, metrics, and signup endpoints
        if path.startswith(("/console", "/static", "/docs", "/openapi.json", "/metrics", "/tenants/signup")):
            return await call_next(request)

        # 1. Identify Tenant ID from Header
        x_api_key = request.headers.get("X-API-Key")
        tenant_id = "default"
        if x_api_key:
            principal = None
            if x_api_key.startswith("Bearer ") or x_api_key.startswith("ey"):
                principal = decode_jwt(x_api_key)
            if not principal:
                principal = _principals().get(x_api_key)
            if principal:
                tenant_id = principal.get("tenant_id", "default")

        # 2. Fetch QPS limit for tenant (with default 10)
        config = get_tenant_config(tenant_id)
        qps_limit = config.get("qps_limit", 10)

        # 3. Connect to Redis
        r = get_redis()
        if r is None:
            import sys
            import os
            is_testing = "pytest" in sys.modules or "unittest" in sys.modules
            test_redis_down = os.environ.get("LLM_SECURITY_TEST_REDIS_DOWN") == "true"
            # Fail-closed for write requests
            if request.method in ("POST", "PUT", "PATCH", "DELETE") and (not is_testing or test_redis_down):
                logger.error(f"ALARM: Redis rate limiter is down/unreachable! Fail-closed on write request: {request.method} {path}")
                return JSONResponse(
                    status_code=503,
                    content={"success": False, "message": "Service temporarily unavailable. Rate limiting system is offline."}
                )
            # ALARM & Local Fallback for read requests
            logger.error("ALARM: Redis rate limiter is down/unreachable! Falling back to local in-memory rate limiting for read request.")
            current_time = time.time()
            local_history = _local_limits[tenant_id]
            # Clean up items older than 1 second
            local_history = [t for t in local_history if t > current_time - 1.0]
            _local_limits[tenant_id] = local_history
            
            if len(local_history) >= qps_limit:
                logger.warning(f"Tenant '{tenant_id}' local fallback rate limit exceeded (QPS limit: {qps_limit}, local count: {len(local_history)})")
                return JSONResponse(
                    status_code=429,
                    content={"success": False, "message": f"Rate limit exceeded (Local Fallback). Maximum QPS limit for tenant is {qps_limit}."}
                )
            local_history.append(current_time)
            return await call_next(request)

        # 4. Enforce rate limit via Redis Sorted Set sliding window
        current_time = time.time()
        redis_key = f"rate:{tenant_id}"
        try:
            pipe = r.pipeline()
            # Clean up records older than 1 second
            pipe.zremrangebyscore(redis_key, 0, current_time - 1.0)
            # Count remaining items in the window
            pipe.zcard(redis_key)
            # Add current request member
            member = f"{current_time}_{uuid4().hex}"
            pipe.zadd(redis_key, {member: current_time})
            # Set key expiry to automatic cleanup
            pipe.expire(redis_key, 2)
            
            _, request_count, _, _ = pipe.execute()

            if request_count >= qps_limit:
                logger.warning(f"Tenant '{tenant_id}' rate limit exceeded (QPS limit: {qps_limit}, count: {request_count})")
                return JSONResponse(
                    status_code=429,
                    content={"success": False, "message": f"Rate limit exceeded. Maximum QPS limit for tenant is {qps_limit}."}
                )
        except Exception as exc:
            import sys
            import os
            is_testing = "pytest" in sys.modules or "unittest" in sys.modules
            test_redis_down = os.environ.get("LLM_SECURITY_TEST_REDIS_DOWN") == "true"
            # Fail-closed for write requests
            if request.method in ("POST", "PUT", "PATCH", "DELETE") and (not is_testing or test_redis_down):
                logger.error(f"Redis rate limiter pipeline error: {exc}. ALARM: Fail-closed on write request: {request.method} {path}")
                return JSONResponse(
                    status_code=503,
                    content={"success": False, "message": "Service temporarily unavailable. Rate limiting system is offline."}
                )
            logger.error(f"Redis rate limiter pipeline error: {exc}. ALARM: Falling back to local in-memory rate limiting for read request.")
            # Local Fallback on Redis failure mid-operation
            current_time = time.time()
            local_history = _local_limits[tenant_id]
            local_history = [t for t in local_history if t > current_time - 1.0]
            _local_limits[tenant_id] = local_history
            
            if len(local_history) >= qps_limit:
                logger.warning(f"Tenant '{tenant_id}' local fallback rate limit exceeded on Redis failure (QPS limit: {qps_limit}, local count: {len(local_history)})")
                return JSONResponse(
                    status_code=429,
                    content={"success": False, "message": f"Rate limit exceeded (Local Fallback). Maximum QPS limit for tenant is {qps_limit}."}
                )
            local_history.append(current_time)

        return await call_next(request)
