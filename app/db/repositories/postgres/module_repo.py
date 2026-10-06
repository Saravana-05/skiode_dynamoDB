"""
PostgreSQL repo for Modules — the layer between a Project and its
domain models:

    Project  →  Module  →  Domain model (datastore_schemas row)

A module always belongs to exactly one project. Domain models point at a
module through the nullable `datastore_schemas.module_id` column, so
existing domain models (no module) keep working untouched.

Self-initializing, same as `projects`: the `modules` table is created on
first use, so no manual migration step is needed.
"""
from datetime import datetime, timezone

from ....core.database import execute, fetch, fetchrow

_modules_table_ready = False  # module-level flag, checked once per process

_COLS = "id, project_id, name, description, created_at, updated_at"


async def _ensure_modules_table() -> None:
    global _modules_table_ready
    if _modules_table_ready:
        return
    await execute(
        """
        CREATE TABLE IF NOT EXISTS modules (
            id          SERIAL PRIMARY KEY,
            project_id  INTEGER NOT NULL,
            name        VARCHAR NOT NULL,
            description VARCHAR,
            created_at  VARCHAR,
            updated_at  VARCHAR
        )
        """
    )
    # Module names are unique within a project (case-insensitive).
    await execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_modules_project_name "
        "ON modules (project_id, LOWER(name))"
    )
    await execute(
        "CREATE INDEX IF NOT EXISTS idx_modules_project ON modules (project_id)"
    )
    print("[modules] Meta-table 'modules' ready (PostgreSQL).")
    _modules_table_ready = True


def _to_wire(row) -> dict:
    d = dict(row)
    d["id"] = str(d["id"])
    d["project_id"] = str(d["project_id"])
    return d


async def create_module(project_id: int | str, name: str, description: str | None = None) -> dict:
    await _ensure_modules_table()
    now = datetime.now(timezone.utc).isoformat()
    row = await fetchrow(
        f"""
        INSERT INTO modules (project_id, name, description, created_at, updated_at)
        VALUES ($1, $2, $3, $4, $4)
        RETURNING {_COLS}
        """,
        int(project_id), name, description, now,
    )
    return _to_wire(row)


async def get_module(module_id: int | str) -> dict | None:
    await _ensure_modules_table()
    row = await fetchrow(f"SELECT {_COLS} FROM modules WHERE id = $1", int(module_id))
    return _to_wire(row) if row else None


async def get_module_by_name(project_id: int | str, name: str) -> dict | None:
    await _ensure_modules_table()
    row = await fetchrow(
        f"SELECT {_COLS} FROM modules WHERE project_id = $1 AND LOWER(name) = LOWER($2)",
        int(project_id), name,
    )
    return _to_wire(row) if row else None


async def list_modules(project_id: int | str | None = None) -> list[dict]:
    await _ensure_modules_table()
    if project_id not in (None, ""):
        rows = await fetch(
            f"SELECT {_COLS} FROM modules WHERE project_id = $1 ORDER BY created_at DESC",
            int(project_id),
        )
    else:
        rows = await fetch(f"SELECT {_COLS} FROM modules ORDER BY created_at DESC")
    return [_to_wire(r) for r in rows]


async def update_module(
    module_id: int | str,
    name: str | None = None,
    description: str | None = None,
) -> dict | None:
    await _ensure_modules_table()
    existing = await get_module(module_id)
    if not existing:
        return None
    now = datetime.now(timezone.utc).isoformat()
    row = await fetchrow(
        f"""
        UPDATE modules
           SET name = $2, description = $3, updated_at = $4
         WHERE id = $1
        RETURNING {_COLS}
        """,
        int(module_id),
        name if name is not None else existing["name"],
        description if description is not None else existing["description"],
        now,
    )
    return _to_wire(row)


async def count_domains(module_id: int | str) -> int:
    """Submitted domain models + open drafts that sit in this module."""
    await _ensure_modules_table()
    from .datastore_repo import _ensure_datastore_schemas_table
    from .domain_draft_repo import _ensure_drafts_table
    await _ensure_datastore_schemas_table()
    await _ensure_drafts_table()
    mid = int(module_id)
    a = await fetchrow("SELECT COUNT(*) AS n FROM datastore_schemas WHERE module_id = $1", mid)
    b = await fetchrow(
        "SELECT COUNT(*) AS n FROM domain_model_drafts WHERE module_id = $1 AND status = 'draft'",
        mid,
    )
    return int(a["n"]) + int(b["n"])


async def delete_module(module_id: int | str) -> bool:
    await _ensure_modules_table()
    row = await fetchrow("DELETE FROM modules WHERE id = $1 RETURNING id", int(module_id))
    return row is not None


async def delete_modules_of_project(project_id: int | str) -> int:
    """
    Used when a whole project is deleted. Removes the project's modules and
    detaches (module_id → NULL) any domain models / drafts that pointed at
    them, so nothing is left referencing a module that no longer exists.
    Domain models themselves are NOT deleted.
    """
    await _ensure_modules_table()
    from .datastore_repo import _ensure_datastore_schemas_table
    from .domain_draft_repo import _ensure_drafts_table
    await _ensure_datastore_schemas_table()
    await _ensure_drafts_table()
    pid = int(project_id)
    ids = [r["id"] for r in await fetch("SELECT id FROM modules WHERE project_id = $1", pid)]
    if not ids:
        return 0
    await execute("UPDATE datastore_schemas SET module_id = NULL WHERE module_id = ANY($1::INTEGER[])", ids)
    await execute("UPDATE domain_model_drafts SET module_id = NULL WHERE module_id = ANY($1::INTEGER[])", ids)
    await execute("DELETE FROM modules WHERE project_id = $1", pid)
    return len(ids)