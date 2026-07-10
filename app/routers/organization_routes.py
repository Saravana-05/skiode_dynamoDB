from typing import Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from ..services.organization_service import create_organization
from ..dependencies.auth_dependency import get_current_user
from ..utils.decorators import handle_errors   # ← add

router = APIRouter(prefix="/organizations", tags=["Organization"])


class CreateOrgRequest(BaseModel):
    org_name: str
    org_code: str
    email: str
    org_description: Optional[str] = None
    large_logo_url: Optional[str] = None
    small_logo_url: Optional[str] = None
    primary_color: Optional[str] = None
    secondary_color: Optional[str] = None
    accent1_color: Optional[str] = None
    accent2_color: Optional[str] = None
    accent3_color: Optional[str] = None
    bot_id: Optional[str] = None
    admin_set_password: bool = False

    model_config = {
        "json_schema_extra": {
            "example": {
                "org_name": "Skiode",
                "org_code": "SKIODE",
                "email": "org@skiode.com",
                "org_description": "My organization",
                "admin_set_password": False
            }
        }
    }


@router.post("")
@handle_errors                                 # ← add
async def create_org(body: CreateOrgRequest, current_user: dict = Depends(get_current_user)):
    return await create_organization(body.model_dump(), current_user)