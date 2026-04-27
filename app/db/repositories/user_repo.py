from ...core.config import settings

if settings.DB_BACKEND == "dynamodb":
    from .dynamo.user_repo import (
        get_by_email,
        get_by_user_id,
        get_by_username,
        create,
        update_password,
    )
else:
    from .postgres.user_repo import (
        get_by_email,
        get_by_user_id,
        get_by_username,
        create,
        update_password,
    )

__all__ = [
    "get_by_email",
    "get_by_user_id",
    "get_by_username",
    "create",
    "update_password",
]
