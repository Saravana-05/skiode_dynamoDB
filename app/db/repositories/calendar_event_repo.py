from ...core.config import settings

if settings.DB_BACKEND == "dynamodb":
    from .dynamo.calendar_event_repo import (
        create,
        get_by_id,
        get_events_by_creator,
        update_google_event_id,
        update_outlook_event_id,
        update,
        check_conflict,
    )
else:
    from .postgres.calendar_event_repo import (
        create,
        get_by_id,
        get_events_by_creator,
        update_google_event_id,
        update_outlook_event_id,
        update,
        check_conflict,
    )

__all__ = [
    "create",
    "get_by_id",
    "get_events_by_creator",
    "update_google_event_id",
    "update_outlook_event_id",
    "update",
    "check_conflict",
]
