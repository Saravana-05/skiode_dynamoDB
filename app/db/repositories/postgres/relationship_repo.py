"""
PostgreSQL repo for the Query Builder's relationship graph + query persistence.

- domain_relationships stores one row per join edge between two domain
  objects (dmo == table_name in datastore_schemas). from_field/to_field are
  REAL column names on the REAL tables — there is no separate physical
  mapping layer, because each dmo already *is* its own physical table.
- query_definitions stores the business Query JSON the user builds in the UI.
- generated_sql stores the exact SQL text produced for a given query
  version — immutable, kept for audit / re-execution / debugging.

Follows the same lazy _ensure_*_table() pattern used in datastore_repo.py
so no manual migration step is required.
"""
import json
from datetime import datetime, timezone

from ....core.database import execute, fetch, fetchrow, ensure_pool


# ── domain_relationships ────────────────────────────────────────

_relationships_table_ready = False


async def _ensure_relationships_table() -> None:
    global _relationships_table_ready
    if _relationships_table_ready:
        return
    await execute(
        """
        CREATE TABLE IF NOT EXISTS domain_relationships (
            id          SERIAL PRIMARY KEY,
            from_dmo    VARCHAR NOT NULL,
            to_dmo      VARCHAR NOT NULL,
            from_field  VARCHAR NOT NULL,
            to_field    VARCHAR NOT NULL,
            cardinality VARCHAR NOT NULL,
            label       VARCHAR,
            created_at  VARCHAR
        )
        """
    )
    await execute(
        "CREATE INDEX IF NOT EXISTS idx_domain_relationships_from ON domain_relationships (from_dmo)"
    )
    await execute(
        "CREATE INDEX IF NOT EXISTS idx_domain_relationships_to ON domain_relationships (to_dmo)"
    )
    print("[query-builder] Meta-table 'domain_relationships' ready (PostgreSQL).")
    _relationships_table_ready = True


async def save_relationship(
    from_dmo: str,
    to_dmo: str,
    from_field: str,
    to_field: str,
    cardinality: str,
    label: str | None = None,
) -> dict:
    await _ensure_relationships_table()
    now = datetime.now(timezone.utc).isoformat()
    row = await fetchrow(
        """
        INSERT INTO domain_relationships
            (from_dmo, to_dmo, from_field, to_field, cardinality, label, created_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        RETURNING id
        """,
        from_dmo, to_dmo, from_field, to_field, cardinality, label, now,
    )
    return {"status": "success", "id": row["id"]}


async def list_relationships() -> list[dict]:
    await _ensure_relationships_table()
    rows = await fetch(
        """
        SELECT id, from_dmo, to_dmo, from_field, to_field, cardinality, label, created_at
        FROM domain_relationships
        ORDER BY id
        """
    )
    return [dict(r) for r in rows]


async def list_relationships_for(dmo: str) -> list[dict]:
    """Relationships where dmo is on either side — used by the frontend's
    'show related objects' navigator."""
    await _ensure_relationships_table()
    rows = await fetch(
        """
        SELECT id, from_dmo, to_dmo, from_field, to_field, cardinality, label, created_at
        FROM domain_relationships
        WHERE from_dmo = $1 OR to_dmo = $1
        ORDER BY id
        """,
        dmo,
    )
    return [dict(r) for r in rows]


async def delete_relationship(relationship_id: int) -> dict:
    await _ensure_relationships_table()
    result = await execute(
        "DELETE FROM domain_relationships WHERE id = $1", relationship_id
    )
    deleted = result.endswith("1")
    return {"status": "success" if deleted else "not_found", "id": relationship_id}


# ── query_definitions + generated_sql ───────────────────────────

_query_tables_ready = False


async def _ensure_query_tables() -> None:
    global _query_tables_ready
    if _query_tables_ready:
        return
    await execute(
        """
        CREATE TABLE IF NOT EXISTS query_definitions (
            id          SERIAL PRIMARY KEY,
            name        VARCHAR,
            query_json  TEXT NOT NULL,
            created_by  VARCHAR,
            created_at  VARCHAR,
            version     INT NOT NULL DEFAULT 1
        )
        """
    )
    await execute(
        """
        CREATE TABLE IF NOT EXISTS generated_sql (
            id                    SERIAL PRIMARY KEY,
            query_definition_id   INT NOT NULL REFERENCES query_definitions (id),
            sql_text              TEXT NOT NULL,
            generated_at          VARCHAR,
            execution_status      VARCHAR,
            execution_time_ms     NUMERIC,
            row_count             INT,
            error_message         TEXT
        )
        """
    )
    await execute(
        "CREATE INDEX IF NOT EXISTS idx_generated_sql_query_def "
        "ON generated_sql (query_definition_id)"
    )
    print("[query-builder] Meta-tables 'query_definitions'/'generated_sql' ready (PostgreSQL).")
    _query_tables_ready = True


async def save_query_definition(
    name: str | None, query_json: dict, created_by: str | None = None
) -> dict:
    await _ensure_query_tables()
    now = datetime.now(timezone.utc).isoformat()
    row = await fetchrow(
        """
        INSERT INTO query_definitions (name, query_json, created_by, created_at, version)
        VALUES ($1, $2, $3, $4, 1)
        RETURNING id, version
        """,
        name, json.dumps(query_json), created_by, now,
    )
    return {"id": row["id"], "version": row["version"], "created_at": now}


async def save_generated_sql(
    query_definition_id: int,
    sql_text: str,
    execution_status: str | None = None,
    execution_time_ms: float | None = None,
    row_count: int | None = None,
    error_message: str | None = None,
) -> dict:
    await _ensure_query_tables()
    now = datetime.now(timezone.utc).isoformat()
    row = await fetchrow(
        """
        INSERT INTO generated_sql
            (query_definition_id, sql_text, generated_at, execution_status,
             execution_time_ms, row_count, error_message)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        RETURNING id
        """,
        query_definition_id, sql_text, now, execution_status,
        execution_time_ms, row_count, error_message,
    )
    return {"id": row["id"], "generated_at": now}


async def get_query_definition(query_definition_id: int) -> dict | None:
    await _ensure_query_tables()
    row = await fetchrow(
        "SELECT id, name, query_json, created_by, created_at, version "
        "FROM query_definitions WHERE id = $1",
        query_definition_id,
    )
    if not row:
        return None
    d = dict(row)
    d["query_json"] = json.loads(d["query_json"])
    return d


async def list_query_definitions() -> list[dict]:
    await _ensure_query_tables()
    rows = await fetch(
        "SELECT id, name, created_by, created_at, version "
        "FROM query_definitions ORDER BY created_at DESC"
    )
    return [dict(r) for r in rows]


# ── generic parameterized execution (used by the SQL generator's caller) ──

async def run_select(sql_text: str, params: list) -> list[dict]:
    """Runs a SELECT built by sql_generator.py. sql_text must only ever be
    produced by sql_generator.py (identifiers whitelisted there); values are
    always passed here as bound $-params, never interpolated into sql_text.
    """
    pool = await ensure_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql_text, *params)
        return [dict(r) for r in rows]

async def list_domain_objects() -> list[dict]:
    """Groups domain_attributes by dmo_name into objects with their fields,
    for the Query Builder's schema/objects picker."""
    rows = await fetch(
        """
        SELECT dmo_name, dmo_attribute_name, field_type, label
        FROM domain_attributes
        ORDER BY dmo_name, dmo_attribute_name
        """
    )
    objects: dict[str, dict] = {}
    for r in rows:
        dmo = r["dmo_name"]
        if dmo not in objects:
            objects[dmo] = {"name": dmo, "fields": []}
        objects[dmo]["fields"].append({
            "name": r["dmo_attribute_name"],
            "type": r["field_type"],
            "label": r["label"],
        })
    return list(objects.values())