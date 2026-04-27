from datetime import datetime, timedelta
from jose import jwt
from ..core.config import settings


def create_reset_token(user_id: int):
    payload = {
        "user_id": user_id,
        "type": "reset",
        "exp": datetime.utcnow() + timedelta(hours=24)
    }

    return jwt.encode(payload, settings.DJANGO_SECRET_KEY, algorithm="HS256")
