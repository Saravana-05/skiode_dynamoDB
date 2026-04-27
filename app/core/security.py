from jose import jwt, JWTError
from fastapi import HTTPException, status
from ..core.config import settings


# def verify_token(token: str):
#     try:
#         payload = jwt.decode(
#             token,
#             settings.DJANGO_SECRET_KEY,
#             algorithms=[settings.ALGORITHM]
#         )
#
#         return payload
#
#     except JWTError as e:
#         raise HTTPException(
#             status_code=status.HTTP_401_UNAUTHORIZED,
#             detail=f"Invalid token: {str(e)}"
#         )

def verify_token(token: str):
    try:
        payload = jwt.decode(
            token,
            settings.DJANGO_SECRET_KEY,
            algorithms=[settings.ALGORITHM]
        )

        if payload.get("token_type") != "access":
            raise Exception("Invalid token type")

        if "user_id" not in payload:
            raise Exception("Invalid token")

        return payload

    except Exception:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token"
        )

