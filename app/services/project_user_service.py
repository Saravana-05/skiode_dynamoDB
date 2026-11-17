"""
Project users: the per-project user table, linked to RBAC.

Adding a user here (existing user, or a brand-new one created on the spot)
puts them in idam."project_<id>_user", makes them a member of the project and
assigns their roles *inside that project only* (see project_user_repo).
"""
from fastapi import HTTPException

from ..db.repositories import rbac_repo
from ..db.repositories.postgres import project_repo, project_user_repo
from . import rbac_service


def _bad(msg: str, code: int = 400):
    raise HTTPException(status_code=code, detail=msg)


async def _project_or_404(project_id: str) -> dict:
    project = await project_repo.get_project(project_id)
    if not project:
        _bad(f"Project '{project_id}' not found", 404)
    return project


async def _check_roles(role_ids: list[str]) -> list[str]:
    ids = list(dict.fromkeys(role_ids))
    for rid in ids:
        if not await rbac_repo.get_role(rid):
            _bad(f"Role not found: {rid}", 400)
    return ids


async def list_users(project_id: str) -> dict:
    await _project_or_404(project_id)
    users = await project_user_repo.list_users(project_id)
    table = await project_user_repo.table_name_of(project_id)
    return {"status": "success", "count": len(users), "table": f"idam.{table}" if table else None,
            "data": users}


async def add_user(caller: dict, project_id: str, user_id: str | None, role_ids: list[str] | None,
                   new_user: dict | None = None) -> dict:
    """Enter a user into the project table.

    user_id          -> an existing user
    new_user         -> {user_name, email, password, is_superuser?}: create then add
    role_ids         -> roles for this project (None = leave roles alone)
    """
    await _project_or_404(project_id)
    roles = await _check_roles(role_ids) if role_ids is not None else None

    if user_id:
        await rbac_service._assert_user_in_scope(caller, user_id)   # 404 for other orgs
    elif new_user:
        created = await rbac_service.create_user(
            caller, new_user.get("user_name"), new_user.get("email"),
            new_user.get("password"), bool(new_user.get("is_superuser")),
        )
        user_id = created["data"]["user_id"]
    else:
        _bad("Provide user_id of an existing user, or new_user details")

    await project_user_repo.add_user(project_id, user_id, roles, added_by=str(caller.get("user_id")))
    users = await project_user_repo.list_users(project_id)
    entry = next((u for u in users if u["user_id"] == str(user_id)), None)
    return {"status": "success", "data": entry}


async def set_user_roles(caller: dict, project_id: str, user_id: str, role_ids: list[str]) -> dict:
    await _project_or_404(project_id)
    await rbac_service._assert_user_in_scope(caller, user_id)
    if not await project_user_repo.is_in_project(project_id, user_id):
        _bad("User is not in this project's user table", 404)
    await project_user_repo.set_roles(project_id, user_id, await _check_roles(role_ids))
    users = await project_user_repo.list_users(project_id)
    return {"status": "success", "data": next((u for u in users if u["user_id"] == str(user_id)), None)}


async def remove_user(caller: dict, project_id: str, user_id: str) -> dict:
    await _project_or_404(project_id)
    await rbac_service._assert_user_in_scope(caller, user_id)
    if not await project_user_repo.remove_user(project_id, user_id):
        _bad("User is not in this project's user table", 404)
    return {"status": "success", "message": "User removed from project"}