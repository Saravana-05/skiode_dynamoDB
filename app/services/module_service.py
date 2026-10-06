"""
Module business logic. Hierarchy: Project → Module → Domain model.
"""
from ..db.repositories.postgres import module_repo, project_repo


async def create_module(project_id: str, payload: dict) -> dict:
    project = await project_repo.get_project(project_id)
    if not project:
        return {"status": "error", "code": 404, "message": f"Project '{project_id}' not found"}

    name = (payload.get("name") or "").strip()
    if not name:
        return {"status": "error", "code": 400, "message": "name is required"}

    if await module_repo.get_module_by_name(project_id, name):
        return {
            "status": "error", "code": 409,
            "message": f"Module '{name}' already exists in this project",
        }

    module = await module_repo.create_module(project_id, name, payload.get("description"))
    return {"status": "success", "data": module}


async def list_modules(project_id: str | None = None) -> dict:
    if project_id not in (None, ""):
        if not await project_repo.get_project(project_id):
            return {"status": "error", "code": 404, "message": f"Project '{project_id}' not found"}
    modules = await module_repo.list_modules(project_id)
    return {"status": "success", "count": len(modules), "project_id": project_id, "data": modules}


async def get_module(module_id: str) -> dict:
    module = await module_repo.get_module(module_id)
    if not module:
        return {"status": "error", "code": 404, "message": f"Module '{module_id}' not found"}
    return {"status": "success", "data": module}


async def update_module(module_id: str, payload: dict) -> dict:
    existing = await module_repo.get_module(module_id)
    if not existing:
        return {"status": "error", "code": 404, "message": f"Module '{module_id}' not found"}

    name = payload.get("name")
    if name is not None:
        name = name.strip()
        if not name:
            return {"status": "error", "code": 400, "message": "name cannot be empty"}
        clash = await module_repo.get_module_by_name(existing["project_id"], name)
        if clash and clash["id"] != existing["id"]:
            return {
                "status": "error", "code": 409,
                "message": f"Module '{name}' already exists in this project",
            }

    module = await module_repo.update_module(
        module_id, name=name, description=payload.get("description"),
    )
    return {"status": "success", "data": module}


async def delete_module(module_id: str) -> dict:
    existing = await module_repo.get_module(module_id)
    if not existing:
        return {"status": "error", "code": 404, "message": f"Module '{module_id}' not found"}

    n = await module_repo.count_domains(module_id)
    if n:
        return {
            "status": "error", "code": 409,
            "message": (
                f"Module '{existing['name']}' still has {n} domain model(s)/draft(s). "
                f"Move or delete them first."
            ),
        }
    await module_repo.delete_module(module_id)
    return {"status": "success", "message": f"Module '{module_id}' deleted"}


async def resolve_scope(project_id, module_id) -> dict:
    """
    Validate the (project, module) pair a domain model is being placed in.

      - no module_id            → pass project_id through untouched
                                  (exactly the pre-modules behaviour)
      - module_id only          → project is taken from the module
      - module_id + project_id  → must match, otherwise error

    Returns {"status": "success", "project_id": ..., "module_id": ...}
    or {"status": "error", "code": ..., "message": ...}.
    """
    if module_id in (None, ""):
        return {"status": "success", "project_id": project_id, "module_id": None}

    module = await module_repo.get_module(module_id)
    if not module:
        return {"status": "error", "code": 404, "message": f"Module '{module_id}' not found"}

    if project_id not in (None, "") and str(project_id) != module["project_id"]:
        return {
            "status": "error", "code": 400,
            "message": f"Module '{module_id}' does not belong to project '{project_id}'",
        }
    return {"status": "success", "project_id": module["project_id"], "module_id": module["id"]}