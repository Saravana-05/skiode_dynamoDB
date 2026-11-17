from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from ..services.auth_service import login_user, reset_password
from ..dependencies.auth_dependency import get_current_user
from ..core.security import verify_token
from ..utils.jwt import create_access_token
from ..utils.decorators import handle_errors   # ← add
from ..services import rbac_service, project_service

router = APIRouter(prefix="/auth", tags=["Auth"])


class LoginRequest(BaseModel):
    mail_id: Optional[str] = None
    password: Optional[str] = None
    id_token: Optional[str] = None
    # Sign in FOR this project: only its users (and admins) are let in.
    project_id: Optional[str] = None
    # Or sign in FOR a published page: the page's project is looked up and the
    # same membership rule applies (so the client only needs to send the slug).
    page_slug: Optional[str] = None

    model_config = {"json_schema_extra": {"example": {"mail_id": "user@example.com", "password": "yourpassword"}}}


class RefreshRequest(BaseModel):
    refresh: str


class ResetPasswordRequest(BaseModel):
    password: str


@router.post("/login")
@handle_errors                                 # ← add
async def login(body: LoginRequest):
    return await login_user(body.model_dump())


@router.post("/refresh")
@handle_errors                                 # ← add
async def refresh_token(body: RefreshRequest):
    payload = verify_token(body.refresh, expected_type="refresh")   # was verify_token(body.refresh), which only accepts ACCESS tokens -> refresh always 401
    if payload.get("token_type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid refresh token")  # ← proper 401

    new_access = create_access_token({
        "user_id": payload.get("user_id"),
        "org_id":  payload.get("org_id"),
        "auth_type": payload.get("auth_type"),
        "role":    payload.get("role"),   # without this, a refreshed token has no role -> RBAC treats the user as role-less
    })
    return {"status": "success", "access": new_access}


@router.get("/me")
@handle_errors                                 # ← add
async def get_me(project_id: Optional[str] = None, page_slug: Optional[str] = None,
                 current_user: dict = Depends(get_current_user)):
    # page_slug: the client renderer only knows the page it is showing; its project decides the scope.
    if not project_id and page_slug:
        try:
            project_id = await project_service.project_id_of_page(page_slug.strip())
        except Exception:
            project_id = None   # can't resolve: fall back to the unscoped context (UI only; the server re-checks every request)
    try:
        ctx = await rbac_service.get_auth_context(current_user["user_id"], project_id)   # project_id -> scoped to it
    except Exception:
        ctx = {"roles": [], "permissions": []}   # RBAC tables not created yet
    projects = await project_service.projects_of_user(current_user)   # None = not tracked
    data = {**current_user, **ctx, "is_admin": rbac_service.is_admin(current_user), "projects": projects}
    if project_id:
        # may this token's user work in this project? (admins always; others only as members)
        denial = await project_service.check_login_project(current_user["user_id"], current_user.get("role"), project_id)
        data["in_project"] = denial is None
    return {"status": "success", "data": data}


@router.post("/logout")
async def logout():
    return {"status": "success", "message": "Logged out successfully"}


@router.post("/reset-password/{user_id}/{token}")
@handle_errors                                 # ← add
async def reset_password_api(user_id: str, token: str, body: ResetPasswordRequest):
    return await reset_password(user_id, token, body.password)