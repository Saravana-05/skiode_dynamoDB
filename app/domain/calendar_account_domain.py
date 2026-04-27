from typing import Optional
from datetime import datetime


class CalendarAccount:

    def __init__(
        self,
        organization_id: int,
        user_id: int,
        provider: str,
        access_token: str,
        refresh_token: str,
        token_expiry: Optional[datetime] = None,
        is_active: bool = True
    ):
        self.organization_id = organization_id
        self.user_id = user_id
        self.provider = provider
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.token_expiry = token_expiry
        self.is_active = is_active

    # ✅ small improvement (optional)
    def is_token_expired(self) -> bool:
        if not self.token_expiry:
            return False
        return self.token_expiry < datetime.utcnow()
