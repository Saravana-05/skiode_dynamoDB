"""
PostgreSQL repo for Projects — the container that domain models
(datastore_schemas rows) can optionally belong to.

Self-initializing: the `projects` table is auto-created on first use,
mirroring how datastore_schemas / domain_attributes already do it, so
no manual migration step is needed to start using this feature.
"""
from datetime import datetime, timezone

from ....core.database import execute, fetch, fetchrow

_projects_table_ready = False  # module-level flag, checked once per process


async def _ensure_projects_table() -> None:
    global _projects_table_ready
    if _projects_table_ready:
        return
    await execute(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id          SERIAL PRIMARY KEY,
            name        VARCHAR NOT NULL,
            description VARCHAR,
            created_at  VARCHAR,
            updated_at  VARCHAR
        )
        """
    )
    print("[projects] Meta-table 'projects' ready (PostgreSQL).")
    _projects_table_ready = True


def _stringify_id(row: dict) -> dict:
    if row.get("id") is not None:
        row["id"] = str(row["id"])
    return row


async def create_project(name: str, description: str | None = None) -> dict:
    await _ensure_projects_table()
    now = datetime.now(timezone.utc).isoformat()
    row = await fetchrow(
        """
        INSERT INTO projects (name, description, created_at, updated_at)
        VALUES ($1, $2, $3, $3)
        RETURNING id, name, description, created_at, updated_at
        """,
        name, description, now,
    )
    return _stringify_id(dict(row))


async def get_project(project_id: int | str) -> dict | None:
    await _ensure_projects_table()
    row = await fetchrow(
        "SELECT id, name, description, created_at, updated_at FROM projects WHERE id = $1",
        int(project_id),
    )
    if not row:
        return None
    return _stringify_id(dict(row))


async def list_projects() -> list[dict]:
    await _ensure_projects_table()
    rows = await fetch(
        "SELECT id, name, description, created_at, updated_at FROM projects ORDER BY created_at DESC"
    )
    return [_stringify_id(dict(r)) for r in rows]


async def update_project(project_id: int | str, name: str | None = None, description: str | None = None) -> dict | None:
    await _ensure_projects_table()
    existing = await get_project(project_id)
    if not existing:
        return None
    now = datetime.now(timezone.utc).isoformat()
    row = await fetchrow(
        """
        UPDATE projects
        SET name = $2, description = $3, updated_at = $4
        WHERE id = $1
        RETURNING id, name, description, created_at, updated_at
        """,
        int(project_id),
        name if name is not None else existing["name"],
        description if description is not None else existing["description"],
        now,
    )
    return _stringify_id(dict(row))


async def delete_project(project_id: int | str) -> bool:
    await _ensure_projects_table()
    result = await execute("DELETE FROM projects WHERE id = $1", int(project_id))
    # asyncpg execute() returns a string like "DELETE 1"
    return result.endswith(" 0") is False