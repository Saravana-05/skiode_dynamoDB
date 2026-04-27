from datetime import datetime
from typing import Optional, Dict


class CalendarParticipant:
    def __init__(
        self,
        event_id: int,
        role: str,
        name: str,
        email: str,
        user_id: Optional[int] = None,
        extra: Optional[Dict] = None,
        status: str = "pending",
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ):
        self.event_id = event_id
        self.user_id = user_id
        self.role = role
        self.name = name
        self.email = email
        self.extra = extra or {}
        self.status = status
        self.created_at = created_at
        self.updated_at = updated_at
