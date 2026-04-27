from typing import Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from ..services.auth_service import login_user, reset_password
from ..dependencies.auth_dependency import get_current_user
from ..core.security import verify_token
from ..utils.jwt import create_access_token

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
async def login(body: LoginRequest):
    try:
        return await login_user(body.model_dump())
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/refresh")
async def refresh_token(body: RefreshRequest):
    try:
        payload = verify_token(body.refresh)

        if payload.get("token_type") != "refresh":
            return {"status": "error", "message": "Invalid refresh token"}

        new_access = create_access_token({
            "user_id": payload.get("user_id"),
            "org_id": payload.get("org_id"),
            "auth_type": payload.get("auth_type"),
        })

        return {"status": "success", "access": new_access}

    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    return {"status": "success", "data": current_user}


@router.post("/logout")
async def logout():
    return {"status": "success", "message": "Logged out successfully"}


@router.post("/reset-password/{user_id}/{token}")
async def reset_password_api(user_id: str, token: str, body: ResetPasswordRequest):
    return await reset_password(user_id, token, body.password)
