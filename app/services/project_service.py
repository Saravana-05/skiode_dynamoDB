from fastapi import HTTPException

from ..db.repositories.postgres import project_repo, module_repo, project_user_repo
from . import rbac_service


async def _member_ids(current_user: dict) -> set[str]:
    from ..idam.repositories import project_member_repo
    return set(await project_member_repo.project_ids_of(current_user["user_id"]))


def _restricted(current_user: dict | None) -> bool:
    """True when this caller must only see projects they are a member of.

    No caller (token-less / legacy anonymous access) and admins are never
    restricted; project membership only exists on PostgreSQL.
    """
    return (current_user is not None
            and not rbac_service.is_admin(current_user)
            and rbac_service.settings_project_isolation())




async def project_id_of_page(slug: str) -> str | None:
    """Project a published page belongs to (None = no project / unknown page)."""
    from ..core.database import fetchrow
    row = await fetchrow("SELECT project_id FROM pages WHERE slug = $1 AND is_active = TRUE", slug)
    return str(row["project_id"]) if row and row["project_id"] is not None else None


async def check_login_project(user_id: str, role: str, project_id) -> str | None:
    """Project-scoped login: may this user sign in FOR this project?

    Returns None when allowed, otherwise the message to show. Admins may enter
    any project; everyone else only a project whose user table they are in.
    Fails closed: if membership can't be checked, the login is refused.
    """
    try:
        pid = int(project_id)
    except (TypeError, ValueError):
        return f"Project not found (id {project_id})"
    try:
        project = await project_repo.get_project(pid)
        if not project:
            return f"Project not found (id {pid})"
        user = {"user_id": user_id, "role": role}
        if rbac_service.is_admin(user) or not rbac_service.settings_project_isolation():
            return None
        if str(pid) in await _member_ids(user):
            return None
        # Name the project (and id) so it's obvious which one the client asked for.
        return f"You are not a member of the project '{project['name']}' (id {pid}). Ask an admin to add you."
    except Exception as exc:
        print(f"[projects] project login check failed: {exc}")
        return "Could not verify your access to this project"


async def projects_of_user(current_user: dict) -> list[dict] | None:
    """Projects this user can enter, as [{id, name}] (admins: every project).

    None = "unknown / not tracked" (non-PostgreSQL backend or lookup failed) -
    callers must not treat that as "no projects".
    """
    try:
        if not rbac_service.settings_project_isolation():
            return None
        projects = await project_repo.list_projects()
        if not _restricted(current_user):
            return [{"id": p["id"], "name": p["name"]} for p in projects]
        member = await _member_ids(current_user)
        return [{"id": p["id"], "name": p["name"]} for p in projects if p["id"] in member]
    except Exception as exc:
        print(f"[projects] could not resolve projects of user: {exc}")
        return None


async def create_project(payload: dict, current_user: dict | None = None) -> dict:
    name = (payload.get("name") or "").strip()
    if not name:
        return {"status": "error", "message": "name is required"}

    project = await project_repo.create_project(
        name=name,
        description=payload.get("description"),
    )
    result = {"status": "success", "data": project}
    created_by = current_user

    # Every project gets its own (empty) user table. Users entered into it are
    # linked to RBAC - see project_user_repo. A failure here (e.g. idam tables
    # not initialised yet) must not lose the project: the table is re-created
    # lazily on first use, and the warning tells the caller what to run.
    try:
        await project_user_repo.ensure_table(project["id"])
    except Exception as exc:
        print(f"[projects] could not create user table for project {project['id']}: {exc}")
        result["warning"] = ("Project created, but its user table could not be created yet - "
                             "run `python -m app.db.init_rbac` and `python -m app.idam.init_idam`.")
        return result

    # A non-admin who creates a project must be able to see it afterwards
    # (non-admins only see projects they are a member of), so they join it.
    if _restricted(created_by):
        try:
            await project_user_repo.add_user(project["id"], created_by["user_id"], None,
                                             added_by=str(created_by["user_id"]))
        except Exception as exc:
            print(f"[projects] could not add creator to project {project['id']}: {exc}")
    return result


async def get_project(project_id: str, current_user: dict | None = None) -> dict:
    project = await project_repo.get_project(project_id)
    if not project:
        return {"status": "error", "message": f"Project '{project_id}' not found"}
    if _restricted(current_user) and str(project_id) not in await _member_ids(current_user):
        raise HTTPException(status_code=403, detail="You are not a member of this project")
    return {"status": "success", "data": project}


async def list_projects(current_user: dict | None = None) -> dict:
    """Admins (and token-less legacy callers) get every project; any other
    signed-in user only the projects they are a member of."""
    projects = await project_repo.list_projects()
    if _restricted(current_user):
        member = await _member_ids(current_user)
        projects = [p for p in projects if p["id"] in member]
    return {"status": "success", "count": len(projects), "data": projects}


async def update_project(project_id: str, payload: dict) -> dict:
    project = await project_repo.update_project(
        project_id,
        name=payload.get("name"),
        description=payload.get("description"),
    )
    if not project:
        return {"status": "error", "message": f"Project '{project_id}' not found"}
    # The user table is named after the project, so keep it in step with a rename.
    if payload.get("name"):
        try:
            await project_user_repo.rename_table(project_id, project["name"])
        except Exception as exc:
            print(f"[projects] could not rename user table of project {project_id}: {exc}")
    return {"status": "success", "data": project}


async def delete_project(project_id: str) -> dict:
    existing = await project_repo.get_project(project_id)
    if not existing:
        return {"status": "error", "message": f"Project '{project_id}' not found"}
    # Modules can't outlive their project. Their domain models are kept
    # (detached from the module), same leniency projects already had.
    await module_repo.delete_modules_of_project(project_id)
    await project_user_repo.drop_table(project_id)
    await project_repo.delete_project(project_id)
    return {"status": "success", "message": f"Project '{project_id}' deleted"}