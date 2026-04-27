from datetime import datetime

from ..db.repositories import calendar_account_repo as repo


class Obj:
    def __init__(self, data: dict):
        for k, v in data.items():
            setattr(self, k, v)


async def create_account(data):
    if isinstance(data, dict):
        data = Obj(data)

    data.provider = data.provider.upper()

    if data.provider not in ["GOOGLE", "OUTLOOK"]:
        raise ValueError("Invalid provider")

    if data.token_expiry and isinstance(data.token_expiry, str):
        token_expiry = data.token_expiry
    elif data.token_expiry and isinstance(data.token_expiry, datetime):
        token_expiry = data.token_expiry.isoformat()
    else:
        token_expiry = None

    return await repo.upsert(
        organization_id=str(data.organization_id),
        user_id=str(data.user_id),
        provider=data.provider,
        access_token=data.access_token,
        refresh_token=data.refresh_token,
        token_expiry=token_expiry,
    )


async def get_user_accounts(user_id):
    return await repo.get_user_accounts(str(user_id))


async def get_provider_account(user_id, provider: str):
    return await repo.get_provider_account(str(user_id), provider.upper())


async def deactivate_account(account_id):
    await repo.deactivate(str(account_id))
    return {"message": "Account deactivated"}


async def update_tokens(account_id, access_token: str, refresh_token: str):
    await repo.update_tokens(str(account_id), access_token, refresh_token)
