from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from ..services.auth_service import login_user, reset_password
from ..dependencies.auth_dependency import get_current_user
from ..core.security import verify_token
from ..utils.jwt import create_access_token
from ..utils.decorators import handle_errors   # ← add

router = APIRouter(prefix="/auth", tags=["Auth"])


class LoginRequest(BaseModel):
    mail_id: Optional[str] = None
    password: Optional[str] = None
    id_token: Optional[str] = None

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
    payload = verify_token(body.refresh)
    if payload.get("token_type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid refresh token")  # ← proper 401

    new_access = create_access_token({
        "user_id": payload.get("user_id"),
        "org_id":  payload.get("org_id"),
        "auth_type": payload.get("auth_type"),
    })
    return {"status": "success", "access": new_access}


@router.get("/me")
@handle_errors                                 # ← add
async def get_me(current_user: dict = Depends(get_current_user)):
    return {"status": "success", "data": current_user}


@router.post("/logout")
async def logout():
    return {"status": "success", "message": "Logged out successfully"}


@router.post("/reset-password/{user_id}/{token}")
@handle_errors                                 # ← add
async def reset_password_api(user_id: str, token: str, body: ResetPasswordRequest):
    return await reset_password(user_id, token, body.password)