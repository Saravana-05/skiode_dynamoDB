"""
Modules API.

Hierarchy:  Project → Module → Domain model

A module lives inside exactly one project and groups that project's
domain models (see datastore_routes.py — pass `module_id` to
POST /datastore/create, or filter GET /datastore/schemas?module_id=...).

  1. POST   /projects/{project_id}/modules   → create a module in a project
  2. GET    /projects/{project_id}/modules   → list a project's modules
  3. GET    /modules                         → list all modules (?project_id= optional)
  4. GET    /modules/{id}                    → get one module
  5. PUT    /modules/{id}                    → update a module
  6. DELETE /modules/{id}                    → delete a module (blocked while it has domain models)
  7. GET    /modules/{id}/domains            → domain models + drafts inside the module
"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..utils.decorators import handle_errors

router = APIRouter(tags=["Modules"])


class CreateModuleRequest(BaseModel):
    name: str
    description: str | None = None


class UpdateModuleRequest(BaseModel):
    name: str | None = None
    description: str | None = None


def _raise_if_error(result: dict) -> dict:
    if result.get("status") == "error":
        raise HTTPException(status_code=result.get("code", 400), detail=result.get("message"))
    return result


@router.post("/projects/{project_id}/modules", summary="Create a module inside a project")
@handle_errors
async def create_module_route(project_id: str, body: CreateModuleRequest, request: Request):
    from ..services.module_service import create_module
    return _raise_if_error(await create_module(project_id, body.model_dump()))


@router.get("/projects/{project_id}/modules", summary="List the modules of a project")
@handle_errors
async def list_project_modules_route(project_id: str, request: Request):
    from ..services.module_service import list_modules
    return _raise_if_error(await list_modules(project_id))


@router.get("/modules", summary="List all modules (optionally filtered by project_id)")
@handle_errors
async def list_modules_route(request: Request, project_id: str | None = None):
    from ..services.module_service import list_modules
    return _raise_if_error(await list_modules(project_id))


@router.get("/modules/{module_id}", summary="Get one module")
@handle_errors
async def get_module_route(module_id: str, request: Request):
    from ..services.module_service import get_module
    return _raise_if_error(await get_module(module_id))


@router.put("/modules/{module_id}", summary="Update a module")
@handle_errors
async def update_module_route(module_id: str, body: UpdateModuleRequest, request: Request):
    from ..services.module_service import update_module
    return _raise_if_error(await update_module(module_id, body.model_dump()))


@router.delete("/modules/{module_id}", summary="Delete a module (only when it has no domain models)")
@handle_errors
async def delete_module_route(module_id: str, request: Request):
    from ..services.module_service import delete_module
    return _raise_if_error(await delete_module(module_id))


@router.get("/modules/{module_id}/domains", summary="List the domain models and drafts inside a module")
@handle_errors
async def list_module_domains_route(module_id: str, request: Request):
    from ..services.module_service import get_module
    from ..db.repositories.datastore_repo import list_schemas
    from ..db.repositories.domain_draft_repo import list_drafts

    module = _raise_if_error(await get_module(module_id))["data"]
    schemas = await list_schemas(None, module["id"])
    drafts = await list_drafts(None, "draft", module["id"])
    return {
        "status": "success",
        "module": module,
        "schemas": schemas,
        "drafts": drafts,
        "count": len(schemas),
    }