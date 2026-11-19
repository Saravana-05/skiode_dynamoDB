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
    # Project this template belongs to (None = no project).
    project_id: Optional[int] = None


class UpdateSavedTemplateRequest(BaseModel):
    name: Optional[str] = None
    plugin_id: Optional[str] = None
    instance: Optional[Dict[str, Any]] = None
    # Send null to detach the template from its project; leave it out to keep it.
    project_id: Optional[int] = None


@router.get("/")
async def list_templates(project_id: Optional[int] = None):
    try:
        result = await saved_templates_service.list_templates(project_id)
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


@router.put("/{id}")
async def update_template(id: int, payload: UpdateSavedTemplateRequest):
    try:
        # exclude_unset (not exclude_none): an explicit "project_id": null must reach the
        # service so it can clear the project, while omitted fields stay untouched.
        data = payload.model_dump(exclude_unset=True)
        data = {k: v for k, v in data.items() if v is not None or k == "project_id"}
        result = await saved_templates_service.update_template(id, data)
        if result is None:
            return JSONResponse(content=error_response("Template not found"), status_code=404)
        return success_response(result)
    except Exception as e:
        return JSONResponse(content=error_response(str(e)), status_code=400)