from ...core.config import settings

if settings.DB_BACKEND == "dynamodb":
    from .dynamo.calendar_participant_repo import (
        create,
        get_by_event,
        get_by_email,
        get_events_by_email,
        update_status,
    )
else:
    from .postgres.calendar_participant_repo import (
        create,
        get_by_event,
        get_by_email,
        get_events_by_email,
        update_status,
    )

__all__ = [
    "create",
    "get_by_event",
    "get_by_email",
    "get_events_by_email",
    "update_status",
]
