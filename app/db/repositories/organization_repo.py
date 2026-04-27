from ...core.config import settings

if settings.DB_BACKEND == "dynamodb":
    from .dynamo.organization_repo import (
        get_by_code,
        get_by_id,
        create_org,
        get_auth_config,
        create_auth_config,
        get_usergroup,
    )
else:
    from .postgres.organization_repo import (
        get_by_code,
        get_by_id,
        create_org,
        get_auth_config,
        create_auth_config,
        get_usergroup,
    )

__all__ = [
    "get_by_code",
    "get_by_id",
    "create_org",
    "get_auth_config",
    "create_auth_config",
    "get_usergroup",
]
