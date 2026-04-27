from ...core.config import settings

if settings.DB_BACKEND == "dynamodb":
    from .dynamo.calendar_account_repo import (
        upsert,
        get_user_accounts,
        get_provider_account,
        deactivate,
        update_tokens,
    )
else:
    from .postgres.calendar_account_repo import (
        upsert,
        get_user_accounts,
        get_provider_account,
        deactivate,
        update_tokens,
    )

__all__ = [
    "upsert",
    "get_user_accounts",
    "get_provider_account",
    "deactivate",
    "update_tokens",
]
