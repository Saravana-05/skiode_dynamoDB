from ..db.repositories.postgres import project_repo


async def create_project(payload: dict) -> dict:
    name = (payload.get("name") or "").strip()
    if not name:
        return {"status": "error", "message": "name is required"}

    project = await project_repo.create_project(
        name=name,
        description=payload.get("description"),
    )
    return {"status": "success", "data": project}


async def get_project(project_id: str) -> dict:
    project = await project_repo.get_project(project_id)
    if not project:
        return {"status": "error", "message": f"Project '{project_id}' not found"}
    return {"status": "success", "data": project}


async def list_projects() -> dict:
    projects = await project_repo.list_projects()
    return {"status": "success", "count": len(projects), "data": projects}


async def update_project(project_id: str, payload: dict) -> dict:
    project = await project_repo.update_project(
        project_id,
        name=payload.get("name"),
        description=payload.get("description"),
    )
    if not project:
        return {"status": "error", "message": f"Project '{project_id}' not found"}
    return {"status": "success", "data": project}


async def delete_project(project_id: str) -> dict:
    existing = await project_repo.get_project(project_id)
    if not existing:
        return {"status": "error", "message": f"Project '{project_id}' not found"}
    await project_repo.delete_project(project_id)
    return {"status": "success", "message": f"Project '{project_id}' deleted"}