from typing import Any, Dict, Optional
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..services.saved_templates_service import SavedTemplatesService
from ..utils.responses import success_response, error_response

router = APIRouter(prefix="/saved-templates", tags=["Saved Templates"])

saved_templates_service = SavedTemplatesService()


class CreateSavedTemplateRequest(BaseModel):
    name: str
    plugin_id: str
    instance: Dict[str, Any]
    created_by: Optional[str] = None


@router.get("/")
async def list_templates():
    try:
        result = await saved_templates_service.list_templates()
        return success_response(result)
    except Exception as e:
        return JSONResponse(content=error_response(str(e)), status_code=400)


@router.post("/")
async def create_template(payload: CreateSavedTemplateRequest):
    try:
        result = await saved_templates_service.create_template(payload.model_dump())
        return success_response(result)
    except Exception as e:
        return JSONResponse(content=error_response(str(e)), status_code=400)


@router.delete("/{id}")
async def delete_template(id: int):
    try:
        await saved_templates_service.delete_template(id)
        return success_response({"message": "Template deleted"})
    except Exception as e:
        return JSONResponse(content=error_response(str(e)), status_code=400)