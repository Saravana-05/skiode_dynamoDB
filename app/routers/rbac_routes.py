"""
RBAC admin API.

All endpoints require an admin token (role PRODUCT_ADMIN or ORG_ADMIN),
except GET /rbac/me which any logged-in user can call.

  Resources & permissions
    GET    /rbac/resources                    list resources (each with its permissions)
    POST   /rbac/resources                    create a resource
    DELETE /rbac/resources/{id}               delete resource (+ its permissions)
    GET    /rbac/permissions[?resource_id=]   list permissions
    POST   /rbac/permissions                  create one (idempotent per resource+action)
    DELETE /rbac/permissions/{id}

  Roles
    GET    /rbac/roles
    POST   /rbac/roles
    GET    /rbac/roles/{id}                   role + its granted permissions
    DELETE /rbac/roles/{id}
    PUT    /rbac/roles/{id}/permissions       replace the role's permission set

  Users
    GET    /rbac/users                        users + assigned roles
    POST   /rbac/users                        create a user (in the caller's organization)
    GET    /rbac/users/{id}/roles
    PUT    /rbac/users/{id}/roles             replace the user's roles
    GET    /rbac/users/{id}/permissions       effective permissions

  Self
    GET    /rbac/me                           my roles + effective permissions
"""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, SecretStr

from ..dependencies.auth_dependency import get_current_user
from ..dependencies.rbac_dependency import require_admin
from ..services import rbac_service as svc
from ..utils.decorators import handle_errors

router = APIRouter(prefix="/rbac", tags=["RBAC"])
admin = [Depends(require_admin)]


class CreateNamed(BaseModel):
    name: str
    description: str | None = None


class CreatePermissionRequest(BaseModel):
    resource_id: str
    action: str
    description: str | None = None


class SetPermissionsRequest(BaseModel):
    permission_ids: list[str] = []


class SetRolesRequest(BaseModel):
    role_ids: list[str] = []


class CreateUserRequest(BaseModel):
    user_name: str
    email: str
    # SecretStr: handle_errors copies request bodies into audit_log, and a
    # SecretStr serialises as '**********' there instead of the real password.
    password: SecretStr
    is_superuser: bool = False


# ── Self ──────────────────────────────────────────────────────────────────────

@router.get("/me", summary="My roles and effective permissions")
@handle_errors
async def my_permissions(request: Request, current_user: dict = Depends(get_current_user)):
    ctx = await svc.get_auth_context(current_user["user_id"])
    return {"status": "success", "data": {"role": current_user.get("role"), **ctx}}


# ── Resources ─────────────────────────────────────────────────────────────────

@router.get("/resources", dependencies=admin, summary="List resources with their permissions")
@handle_errors
async def list_resources(request: Request):
    return await svc.list_resources()


@router.post("/resources", dependencies=admin, summary="Create a resource")
@handle_errors
async def create_resource(body: CreateNamed, request: Request):
    return await svc.create_resource(body.name, body.description)


@router.delete("/resources/{resource_id}", dependencies=admin, summary="Delete a resource and its permissions")
@handle_errors
async def delete_resource(resource_id: str, request: Request):
    return await svc.delete_resource(resource_id)


# ── Permissions ───────────────────────────────────────────────────────────────

@router.get("/permissions", dependencies=admin, summary="List permissions")
@handle_errors
async def list_permissions(request: Request, resource_id: str | None = None):
    return await svc.list_permissions(resource_id)


@router.post("/permissions", dependencies=admin, summary="Create a permission (resource + action)")
@handle_errors
async def create_permission(body: CreatePermissionRequest, request: Request):
    return await svc.create_permission(body.resource_id, body.action, body.description)


@router.delete("/permissions/{permission_id}", dependencies=admin, summary="Delete a permission")
@handle_errors
async def delete_permission(permission_id: str, request: Request):
    return await svc.delete_permission(permission_id)


# ── Roles ─────────────────────────────────────────────────────────────────────

@router.get("/roles", dependencies=admin, summary="List roles")
@handle_errors
async def list_roles(request: Request):
    return await svc.list_roles()


@router.post("/roles", dependencies=admin, summary="Create a role")
@handle_errors
async def create_role(body: CreateNamed, request: Request):
    return await svc.create_role(body.name, body.description)


@router.get("/roles/{role_id}", dependencies=admin, summary="Get a role with its permissions")
@handle_errors
async def get_role(role_id: str, request: Request):
    return await svc.get_role(role_id)


@router.delete("/roles/{role_id}", dependencies=admin, summary="Delete a role")
@handle_errors
async def delete_role(role_id: str, request: Request):
    return await svc.delete_role(role_id)


@router.put("/roles/{role_id}/permissions", dependencies=admin, summary="Replace a role's permissions")
@handle_errors
async def set_role_permissions(role_id: str, body: SetPermissionsRequest, request: Request):
    return await svc.set_role_permissions(role_id, body.permission_ids)


# ── Users ─────────────────────────────────────────────────────────────────────

@router.get("/users", summary="List users with their roles")
@handle_errors
async def list_users(request: Request, caller: dict = Depends(require_admin)):
    return await svc.list_users(caller)


@router.post("/users", summary="Create a user in your organization")
@handle_errors
async def create_user(body: CreateUserRequest, request: Request, caller: dict = Depends(require_admin)):
    return await svc.create_user(caller, body.user_name, body.email,
                                   body.password.get_secret_value(), body.is_superuser)


@router.get("/users/{user_id}/roles", summary="A user's roles")
@handle_errors
async def get_user_roles(user_id: str, request: Request, caller: dict = Depends(require_admin)):
    return await svc.get_user_roles(caller, user_id)


@router.put("/users/{user_id}/roles", summary="Replace a user's roles")
@handle_errors
async def set_user_roles(user_id: str, body: SetRolesRequest, request: Request,
                         caller: dict = Depends(require_admin)):
    return await svc.set_user_roles(caller, user_id, body.role_ids)


@router.get("/users/{user_id}/permissions", summary="A user's effective permissions")
@handle_errors
async def get_user_permissions(user_id: str, request: Request, caller: dict = Depends(require_admin)):
    return await svc.get_user_permissions(caller, user_id)