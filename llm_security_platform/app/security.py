import json
import os
from fastapi import Depends, Header, HTTPException, Query
import jwt

from llm_security_platform.app.config import API_KEY, API_KEYS_JSON


ROLE_PERMISSIONS = {
    "viewer": {"run:read"},
    "analyst": {"run:read", "run:create", "run:cancel", "run:retry", "case:read"},
    "reviewer": {"run:read", "audit:read", "review:read", "review:write", "case:read"},
    "admin": {"*"},
}

import warnings
import logging

logger = logging.getLogger("llm_security_platform.security")
DEFAULT_JWT_SECRET = "security-jwt-secret-key-9417-supersecret-32-bytes-long"
JWT_SECRET = os.environ.get("LLM_SECURITY_JWT_SECRET")
from llm_security_platform.app.config import LLM_SECURITY_ENV
is_prod = (LLM_SECURITY_ENV == "production")

if is_prod:
    if not JWT_SECRET:
        raise ValueError(
            "CRITICAL SECURITY ERROR: LLM_SECURITY_JWT_SECRET environment variable is required and must be configured in production."
        )
    if JWT_SECRET == DEFAULT_JWT_SECRET:
        raise ValueError(
            "CRITICAL SECURITY ERROR: Default JWT secret key cannot be used in production environments. "
            "Please configure a unique secure key in the LLM_SECURITY_JWT_SECRET environment variable."
        )
else:
    if not JWT_SECRET:
        JWT_SECRET = DEFAULT_JWT_SECRET

JWT_ALGORITHM = "HS256"


def decode_jwt(token: str) -> dict | None:
    try:
        if token.startswith("Bearer "):
            token = token[7:]
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except Exception:
        return None


def encode_jwt(actor: str, role: str, tenant_id: str) -> str:
    payload = {
        "actor": actor,
        "role": role,
        "tenant_id": tenant_id
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _principals():
    defaults = {
        API_KEY: {"actor": "local-admin", "role": "admin", "tenant_id": "default"},
        "viewer-key": {"actor": "demo-viewer", "role": "viewer", "tenant_id": "tenant_a"},
        "analyst-key": {"actor": "demo-analyst", "role": "analyst", "tenant_id": "tenant_a"},
        "reviewer-key": {"actor": "demo-reviewer", "role": "reviewer", "tenant_id": "tenant_a"},
    }
    if not API_KEYS_JSON:
        return defaults
    configured = json.loads(API_KEYS_JSON)
    for k, v in configured.items():
        if isinstance(v, dict) and "tenant_id" not in v:
            v["tenant_id"] = "default"
    return {**defaults, **configured}


async def require_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    token: str | None = Query(default=None)
):
    key = x_api_key or token
    if not key:
        raise HTTPException(status_code=401, detail="invalid or missing X-API-Key")
    
    principal = None
    if key.startswith("Bearer ") or key.startswith("ey"):
        principal = decode_jwt(key)
        
    if principal is None:
        principal = _principals().get(key)
        
    if principal is None:
        raise HTTPException(status_code=401, detail="invalid or missing X-API-Key")
        
    # Set the tenant_id in contextvars for schema routing
    from llm_security_platform.app.production_store import current_tenant
    current_tenant.set(principal.get("tenant_id", "default"))
    
    return principal


def require_permission(permission):
    async def dependency(principal=Depends(require_api_key)):
        allowed = ROLE_PERMISSIONS.get(principal["role"], set())
        if "*" not in allowed and permission not in allowed:
            raise HTTPException(status_code=403, detail=f"missing permission: {permission}")
        return principal

    return dependency


def verify_cloud_tasks_oidc(authorization: str | None) -> dict:
    """
    Verifies the OIDC JWT token issued by Google Cloud Tasks.
    Raises HTTPException 401 if invalid.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization Bearer token")
        
    token = authorization[7:]
    
    # Verify using Google auth library
    from google.oauth2 import id_token
    from google.auth.transport import requests
    
    expected_audience = os.environ.get("LLM_SECURITY_WORKER_SERVICE_URL")
    if not expected_audience:
        raise HTTPException(
            status_code=500,
            detail="LLM_SECURITY_WORKER_SERVICE_URL environment variable is not configured."
        )
        
    try:
        # verify_oauth2_token handles signature checking, expiration, and audience verification.
        decoded = id_token.verify_oauth2_token(token, requests.Request(), expected_audience)
        
        # Verify issuer
        if decoded.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
            raise ValueError("Wrong issuer")
            
        # Verify specific service account email
        expected_sa = os.environ.get("LLM_SECURITY_TASKS_SERVICE_ACCOUNT")
        if expected_sa and decoded.get("email") != expected_sa:
            raise ValueError(f"Unauthorized service account: {decoded.get('email')}")
            
        return decoded
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Google OIDC token verification failed: {exc}")


