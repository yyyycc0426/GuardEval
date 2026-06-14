import json

from fastapi import Depends, Header, HTTPException

from llm_security_platform.app.config import API_KEY, API_KEYS_JSON


ROLE_PERMISSIONS = {
    "viewer": {"run:read"},
    "analyst": {"run:read", "run:create", "run:cancel", "run:retry", "case:read"},
    "reviewer": {"run:read", "audit:read", "review:read", "review:write", "case:read"},
    "admin": {"*"},
}


def _principals():
    defaults = {
        API_KEY: {"actor": "local-admin", "role": "admin"},
        "viewer-key": {"actor": "demo-viewer", "role": "viewer"},
        "analyst-key": {"actor": "demo-analyst", "role": "analyst"},
        "reviewer-key": {"actor": "demo-reviewer", "role": "reviewer"},
    }
    if not API_KEYS_JSON:
        return defaults
    configured = json.loads(API_KEYS_JSON)
    return {**defaults, **configured}


def require_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    principal = _principals().get(x_api_key)
    if principal is None:
        raise HTTPException(status_code=401, detail="invalid or missing X-API-Key")
    return principal


def require_permission(permission):
    def dependency(principal=Depends(require_api_key)):
        allowed = ROLE_PERMISSIONS.get(principal["role"], set())
        if "*" not in allowed and permission not in allowed:
            raise HTTPException(status_code=403, detail=f"missing permission: {permission}")
        return principal

    return dependency
