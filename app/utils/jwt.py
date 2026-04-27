from datetime import datetime, timedelta
from jose import jwt
from ..core.config import settings


def create_access_token(data: dict):
    to_encode = data.copy()

    now = datetime.utcnow()
    expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({
        "exp": expire,
        "iat": now,
        "token_type": "access"
    })

    return jwt.encode(
        to_encode,
        settings.DJANGO_SECRET_KEY,
        algorithm=settings.ALGORITHM
    )


def create_refresh_token(data: dict):
    to_encode = data.copy()

    now = datetime.utcnow()
    expire = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

    to_encode.update({
        "exp": expire,
        "iat": now,
        "token_type": "refresh"
    })

    return jwt.encode(
        to_encode,
        settings.DJANGO_SECRET_KEY,
        algorithm=settings.ALGORITHM
    )


def create_tokens(data: dict):
    return {
        "access": create_access_token(data),
        "refresh": create_refresh_token(data)
    }
