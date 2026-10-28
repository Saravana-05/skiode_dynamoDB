"""
FastAPI dependencies for RBAC.

  require_admin                       → /rbac admin API (PRODUCT_ADMIN / ORG_ADMIN only)
  require_permission("view", "Employee")
  require_permission("edit")          → resource is read from the URL, default {table_name}

Usage on a route:

    @router.get("/{table_name}/rows", dependencies=[Depends(require_permission("view"))])

Permissions are looked up in the database on every call (not copied from
the JWT), so role changes take effect immediately without a re-login.
"""
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..core.config import settings
from ..core.security import verify_token
from ..services import rbac_service
from .auth_dependency import get_current_user

_optional_bearer = HTTPBearer(auto_error=False)


def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    if not rbac_service.is_admin(current_user):
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


def _anonymous_allowed(action: str) -> bool:
    """Token-less (or stale-token) access, opt-in via env flags."""
    if action == "view":
        return settings.ALLOW_ANONYMOUS_VIEW
    return settings.ALLOW_ANONYMOUS_WRITE


def require_permission(action: str, resource: str | None = None, resource_param: str = "table_name"):
    """
    Build a dependency that allows the request only if the caller may
    perform `action` on `resource` (fixed name, or the `resource_param`
    path parameter when `resource` is None).

    With RBAC_ENFORCE=false the check is skipped entirely (the route keeps
    working exactly as it did before RBAC, including without a token).
    """
    async def _dependency(
        request: Request,
        credentials: HTTPAuthorizationCredentials | None = Depends(_optional_bearer),
    ):
        if not settings.RBAC_ENFORCE:
            return None
        if credentials is None:
            # Token-less callers (view-builder): only when the env flag allows it.
            if _anonymous_allowed(action):
                return None
            raise HTTPException(status_code=401, detail="Not authenticated")
        try:
            current_user = verify_token(credentials.credentials)  # 401 on bad/expired token
        except HTTPException:
            # Stale/expired token left in the browser: treated like a token-less one.
            if _anonymous_allowed(action):
                return None
            raise

        target = resource or request.path_params.get(resource_param)
        if not target:
            raise HTTPException(status_code=500, detail="RBAC: could not determine the protected resource")

        if not await rbac_service.user_has_permission(current_user, target, action):
            raise HTTPException(status_code=403, detail=f"Permission denied: cannot {action} {target}")
        request.state.current_user = current_user   # lets the route apply field-level rules
        return current_user

    return _dependency