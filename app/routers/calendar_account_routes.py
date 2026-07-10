from fastapi import APIRouter, HTTPException
from ..services import calendar_account_service as service
from ..utils.decorators import handle_errors   # ← add

router = APIRouter(prefix="/calendar-accounts", tags=["Calendar Accounts"])


@router.post("/")
@handle_errors                                 # ← add
async def create_account(payload: dict):
    return await service.create_account(payload)


@router.get("/{user_id}")
@handle_errors                                 # ← add
async def get_accounts(user_id: int):
    return await service.get_user_accounts(user_id)


@router.get("/{user_id}/{provider}")
@handle_errors                                 # ← add
async def get_provider_account(user_id: int, provider: str):
    return await service.get_provider_account(user_id, provider)


@router.patch("/deactivate/{account_id}")
@handle_errors                                 # ← add
async def deactivate(account_id: int):
    return await service.deactivate_account(account_id)