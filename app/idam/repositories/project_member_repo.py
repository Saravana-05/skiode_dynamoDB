"""idam.user_project — which projects a user may access."""
from ...core.database import execute, fetch, fetchrow


async def add(user_id, project_id) -> None:
    await execute(
        "INSERT INTO idam.user_project (user_id, project_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
        int(user_id), int(project_id),
    )


async def remove(user_id, project_id) -> None:
    await execute(
        "DELETE FROM idam.user_project WHERE user_id = $1 AND project_id = $2",
        int(user_id), int(project_id),
    )


async def is_member(user_id, project_id) -> bool:
    row = await fetchrow(
        "SELECT 1 FROM idam.user_project WHERE user_id = $1 AND project_id = $2",
        int(user_id), int(project_id),
    )
    return row is not None


async def project_ids_of(user_id) -> list[str]:
    rows = await fetch("SELECT project_id FROM idam.user_project WHERE user_id = $1 ORDER BY project_id", int(user_id))
    return [str(r["project_id"]) for r in rows]


async def user_ids_of(project_id) -> list[str]:
    rows = await fetch("SELECT user_id FROM idam.user_project WHERE project_id = $1 ORDER BY user_id", int(project_id))
    return [str(r["user_id"]) for r in rows]