
from ...core.config import settings

if settings.DB_BACKEND == "dynamodb":
    from .dynamo.rbac_repo import *  # noqa: F401,F403
else:
    from .postgres.rbac_repo import *  # noqa: F401,F403