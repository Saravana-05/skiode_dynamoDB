"""
Projects API.

A project is a container that domain models (see datastore_routes.py)
can optionally be created inside of. Creating a domain model with a
project_id scopes it to that project; project_id is optional so
existing/global domain models keep working unchanged.

  1. POST   /projects            → create a project
  2. GET    /projects            → list all projects
  3. GET    /projects/{id}       → get one project
  4. PUT    /projects/{id}       → update a project
  5. DELETE /projects/{id}       → delete a project
"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..utils.decorators import handle_errors

router = APIRouter(prefix="/projects", tags=["Projects"])


class CreateProjectRequest(BaseModel):
    name: str
    description: str | None = None


class UpdateProjectRequest(BaseModel):
    name: str | None = None
    description: str | None = None


@router.post("", summary="Create a project")
@handle_errors
async def create_project_route(body: CreateProjectRequest, request: Request):
    from ..services.project_service import create_project
    result = await create_project(body.model_dump())
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("message"))
    return result


@router.get("", summary="List all projects")
@handle_errors
async def list_projects_route(request: Request):
    from ..services.project_service import list_projects
    return await list_projects()


@router.get("/{project_id}", summary="Get one project")
@handle_errors
async def get_project_route(project_id: str, request: Request):
    from ..services.project_service import get_project
    result = await get_project(project_id)
    if result.get("status") == "error":
        raise HTTPException(status_code=404, detail=result.get("message"))
    return result


@router.put("/{project_id}", summary="Update a project")
@handle_errors
async def update_project_route(project_id: str, body: UpdateProjectRequest, request: Request):
    from ..services.project_service import update_project
    result = await update_project(project_id, body.model_dump())
    if result.get("status") == "error":
        raise HTTPException(status_code=404, detail=result.get("message"))
    return result


@router.delete("/{project_id}", summary="Delete a project")
@handle_errors
async def delete_project_route(project_id: str, request: Request):
    from ..services.project_service import delete_project
    result = await delete_project(project_id)
    if result.get("status") == "error":
        raise HTTPException(status_code=404, detail=result.get("message"))
    return result