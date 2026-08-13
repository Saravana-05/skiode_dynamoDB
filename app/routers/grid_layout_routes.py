from fastapi import APIRouter
from fastapi.responses import JSONResponse
from ..services.grid_layout_service import GridLayoutService
from ..utils.responses import success_response, error_response
from pydantic import BaseModel
from typing import Any, Dict, Optional

router = APIRouter(prefix="/grid-layout", tags=["Grid Layout"])

grid_layout_service = GridLayoutService()


class CreateGridLayoutRequest(BaseModel):
    page_name: str
    layout_data: Dict[str, Any]
    label: Optional[str] = "Untitled Layout"
    created_by: Optional[str] = None


class UpdateGridLayoutRequest(BaseModel):
    layout_data: Dict[str, Any]
    label: Optional[str] = "Untitled Layout"


@router.post("/")
async def create_layout(payload: CreateGridLayoutRequest):
    try:
        result = await grid_layout_service.create_layout(payload.model_dump())
        return success_response(result)
    except Exception as e:
        return JSONResponse(
            content=error_response(str(e)),
            status_code=400,
        )


@router.get("/{id}")
async def get_layout(id: int):
    try:
        result = await grid_layout_service.get_layout(id)
        if not result:
            return JSONResponse(
                content=error_response("Layout not found"),
                status_code=404,
            )
        return success_response(result)
    except Exception as e:
        return JSONResponse(
            content=error_response(str(e)),
            status_code=400,
        )


@router.get("/")
async def list_layouts(page_name: Optional[str] = None):
    try:
        result = await grid_layout_service.list_layouts(page_name)
        return success_response(result)
    except Exception as e:
        return JSONResponse(
            content=error_response(str(e)),
            status_code=400,
        )


@router.put("/{id}")
async def update_layout(id: int, payload: UpdateGridLayoutRequest):
    try:
        result = await grid_layout_service.update_layout(
            id,
            payload.model_dump(),
        )
        if not result:
            return JSONResponse(
                content=error_response("Layout not found"),
                status_code=404,
            )
        return success_response(result)
    except Exception as e:
        return JSONResponse(
            content=error_response(str(e)),
            status_code=400,
        )


@router.delete("/{id}")
async def delete_layout(id: int):
    try:
        await grid_layout_service.delete_layout(id)
        return success_response({"message": "Layout deleted"})
    except Exception as e:
        return JSONResponse(
            content=error_response(str(e)),
            status_code=400,
        )