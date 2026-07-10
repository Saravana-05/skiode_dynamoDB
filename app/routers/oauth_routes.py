from fastapi import APIRouter, HTTPException
from ..integrations.google_integration import GoogleIntegration
from ..integrations.outlook_integration import OutlookIntegration
from ..services.calendar_account_service import create_account
from ..utils.decorators import handle_errors   # ← add
import json
import base64

router = APIRouter(prefix="/calendar")


def encode_state(data: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).decode()


def decode_state(state: str) -> dict:
    return json.loads(base64.urlsafe_b64decode(state.encode()).decode())


@router.get("/connect/{provider}")
@handle_errors                                 # ← add
async def connect(provider: str, user_id: int, organization_id: int):
    state_data = {"user_id": user_id, "organization_id": organization_id}
    state = encode_state(state_data)

    if provider == "google":
        auth_url = GoogleIntegration().get_auth_url(state)
    elif provider == "outlook":
        auth_url = OutlookIntegration().get_auth_url(state)
    else:
        raise HTTPException(status_code=400, detail="Invalid provider")  # ← proper error

    return {"status": "success", "auth_url": auth_url}


@router.get("/{provider}/callback")
@handle_errors                                 # ← add
async def callback(provider: str, code: str, state: str):
    state_data = decode_state(state)
    user_id = state_data["user_id"]
    organization_id = state_data["organization_id"]

    if provider == "google":
        token = await GoogleIntegration().exchange_token(code)
    elif provider == "outlook":
        token = await OutlookIntegration().exchange_token(code)
    else:
        raise HTTPException(status_code=400, detail="Invalid provider")  # ← proper error

    await create_account({
        "organization_id": organization_id,
        "user_id": user_id,
        "provider": provider.upper(),
        "access_token": token.get("access_token"),
        "refresh_token": token.get("refresh_token"),
        "token_expiry": None
    })

    return {"status": "success", "message": f"{provider} calendar connected successfully"}