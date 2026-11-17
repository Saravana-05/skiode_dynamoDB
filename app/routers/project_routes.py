"""
Projects API.

A project is a container that domain models (see datastore_routes.py)
can optionally be created inside of. Creating a domain model with a
project_id scopes it to that project; project_id is optional so
existing/global domain models keep working unchanged.

  1. POST   /projects            → create a project
  2. GET    /projects            → list projects (admins: all; other users: only their own projects)
  3. GET    /projects/{id}       → get one project (403 if the user is not a member)
  4. PUT    /projects/{id}       → update a project
  5. DELETE /projects/{id}       → delete a project (also removes its modules + user table)

Project users (admin only). Each project has its own user table, created empty
with the project; entering a user there links them to RBAC (project membership
+ roles that apply only inside this project):
  6. GET    /projects/{id}/users                      → rows of the project's user table
  7. POST   /projects/{id}/users                      → add an existing user (user_id) or create one (new_user)
  8. PUT    /projects/{id}/users/{user_id}/roles      → replace the user's roles in this project
  9. DELETE /projects/{id}/users/{user_id}            → remove the user from the project

Modules (see module_routes.py) live inside a project:
Project → Module → Domain model.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, SecretStr

from ..core.security import verify_token
from ..dependencies.rbac_dependency import require_admin

from ..utils.decorators import handle_errors

router = APIRouter(prefix="/projects", tags=["Projects"])

_optional_bearer = HTTPBearer(auto_error=False)


def _caller(credentials: HTTPAuthorizationCredentials | None = Depends(_optional_bearer)) -> dict | None:
    """The signed-in user, or None for a token-less / stale-token call (legacy
    behaviour: those still see everything, exactly as before)."""
    if credentials is None:
        return None
    try:
        return verify_token(credentials.credentials)
    except HTTPException:
        return None


class CreateProjectRequest(BaseModel):
    name: str
    description: str | None = None


class UpdateProjectRequest(BaseModel):
    name: str | None = None
    description: str | None = None


@router.post("", summary="Create a project")
@handle_errors
async def create_project_route(body: CreateProjectRequest, request: Request,
                               caller: dict | None = Depends(_caller)):
    from ..services.project_service import create_project
    result = await create_project(body.model_dump(), caller)
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("message"))
    return result


@router.get("", summary="List all projects")
@handle_errors
async def list_projects_route(request: Request, caller: dict | None = Depends(_caller)):
    from ..services.project_service import list_projects
    return await list_projects(caller)


@router.get("/{project_id}", summary="Get one project")
@handle_errors
async def get_project_route(project_id: str, request: Request, caller: dict | None = Depends(_caller)):
    from ..services.project_service import get_project
    result = await get_project(project_id, caller)
    if result.get("status") == "error":
        raise HTTPException(status_code=404, detail=result.get("message"))
    return result


@router.put("/{project_id}", summary="Update a project")
@handle_errors
async def update_project_route(project_id: str, body: UpdateProjectRequest, request: Request):
    from ..services.project_service import update_project
    result = await update_project(project_id, body.model_dump())
    if result.get("status") == "error":
        raise HTTPException(status_code=404, detail=result.get("message"))
    return result


@router.delete("/{project_id}", summary="Delete a project")
@handle_errors
async def delete_project_route(project_id: str, request: Request):
    from ..services.project_service import delete_project
    result = await delete_project(project_id)
    if result.get("status") == "error":
        raise HTTPException(status_code=404, detail=result.get("message"))
    return result


# ── Project users (per-project user table, linked to RBAC) ────────────────────

class NewProjectUser(BaseModel):
    user_name: str
    email: str
    password: SecretStr   # SecretStr: handle_errors copies bodies into audit_log
    is_superuser: bool = False


class AddProjectUserRequest(BaseModel):
    user_id: str | None = None          # an existing user ...
    new_user: NewProjectUser | None = None   # ... or create one now
    role_ids: list[str] | None = None   # roles inside this project (omit = leave unchanged)


class SetProjectUserRolesRequest(BaseModel):
    role_ids: list[str] = []


@router.get("/{project_id}/users", summary="List the project's users")
@handle_errors
async def list_project_users_route(project_id: str, request: Request,
                                   caller: dict = Depends(require_admin)):
    from ..services import project_user_service as svc
    return await svc.list_users(project_id)


@router.post("/{project_id}/users", summary="Add a user to the project (links to RBAC)")
@handle_errors
async def add_project_user_route(project_id: str, body: AddProjectUserRequest, request: Request,
                                 caller: dict = Depends(require_admin)):
    from ..services import project_user_service as svc
    new_user = None
    if body.new_user:
        new_user = {**body.new_user.model_dump(exclude={"password"}),
                    "password": body.new_user.password.get_secret_value()}
    return await svc.add_user(caller, project_id, body.user_id, body.role_ids, new_user)


@router.put("/{project_id}/users/{user_id}/roles", summary="Replace a user's roles in this project")
@handle_errors
async def set_project_user_roles_route(project_id: str, user_id: str, body: SetProjectUserRolesRequest,
                                       request: Request, caller: dict = Depends(require_admin)):
    from ..services import project_user_service as svc
    return await svc.set_user_roles(caller, project_id, user_id, body.role_ids)


@router.delete("/{project_id}/users/{user_id}", summary="Remove a user from the project")
@handle_errors
async def remove_project_user_route(project_id: str, user_id: str, request: Request,
                                    caller: dict = Depends(require_admin)):
    from ..services import project_user_service as svc
    return await svc.remove_user(caller, project_id, user_id)