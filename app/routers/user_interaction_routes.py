from fastapi import APIRouter
from fastapi.responses import JSONResponse
from ..services.user_interaction_service import UserInteractionService
from ..utils.responses import success_response, error_response
from pydantic import BaseModel
from typing import Any, Dict, Optional

router = APIRouter(prefix="/user-interaction", tags=["User Interaction"])

user_interaction_service = UserInteractionService()


class CreatePageRequest(BaseModel):
    page_name: str
    page_data: Dict[str, Any]
    created_by: Optional[str] = None


class UpdatePageRequest(BaseModel):
    page_data: Dict[str, Any]


@router.post("/")
async def create_page(payload: CreatePageRequest):
    try:
        result = await user_interaction_service.create_page(payload.model_dump())
        return success_response(result)
    except Exception as e:
        return JSONResponse(
            content=error_response(str(e)),
            status_code=400,
        )


@router.get("/{id}")
async def get_page(id: int):
    try:
        result = await user_interaction_service.get_page(id)
        if not result:
            return JSONResponse(
                content=error_response("Page not found"),
                status_code=404,
            )
        return success_response(result)
    except Exception as e:
        return JSONResponse(
            content=error_response(str(e)),
            status_code=400,
        )


@router.get("/")
async def list_pages():
    try:
        result = await user_interaction_service.list_pages()
        return success_response(result)
    except Exception as e:
        return JSONResponse(
            content=error_response(str(e)),
            status_code=400,
        )


@router.put("/{id}")
async def update_page(id: int, payload: UpdatePageRequest):
    try:
        result = await user_interaction_service.update_page(
            id,
            payload.model_dump(),
        )
        if not result:
            return JSONResponse(
                content=error_response("Page not found"),
                status_code=404,
            )
        return success_response(result)
    except Exception as e:
        return JSONResponse(
            content=error_response(str(e)),
            status_code=400,
        )


@router.delete("/{id}")
async def delete_page(id: int):
    try:
        await user_interaction_service.delete_page(id)
        return success_response({"message": "Page deleted"})
    except Exception as e:
        return JSONResponse(
            content=error_response(str(e)),
            status_code=400,
        )
