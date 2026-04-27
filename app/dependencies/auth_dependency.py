#
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from ..core.security import verify_token

security = HTTPBearer()


# def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
#     token = credentials.credentials
#     payload = verify_token(token)
#
#     if not payload:
#         raise HTTPException(status_code=401, detail="Invalid or expired token")
#
#     return {
#         "user_id": payload.get("user_id"),
#         "email": payload.get("email"),
#         "org_id": payload.get("org_id")
#     }

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    token = credentials.credentials
    return verify_token(token)
