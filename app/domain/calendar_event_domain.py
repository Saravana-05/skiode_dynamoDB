from datetime import datetime
from typing import Optional, Dict


class CalendarEvent:

    def __init__(
        self,
        created_by_id: int,
        title: str,
        start_datetime: datetime,
        end_datetime: datetime,
        event_type: str = "TASK",
        description: Optional[str] = None,
        timezone: str = "UTC",
        status: str = "SCHEDULED",
        google_event_id: Optional[str] = None,
        outlook_event_id: Optional[str] = None
    ):
        self.created_by_id = created_by_id
        self.title = title
        self.description = description
        self.start_datetime = start_datetime
        self.end_datetime = end_datetime
        self.event_type = event_type
        self.timezone = timezone
        self.status = status
        self.google_event_id = google_event_id
        self.outlook_event_id = outlook_event_id

        if self.event_type not in ("TASK", "MEETING"):
            raise ValueError("event_type must be 'TASK' or 'MEETING'")
