"""
PostgreSQL implementation of the dynamic datastore repo.

- Schema definitions stored in datastore_schemas table (table_name PK, schema TEXT)
- Dynamic tables created with CREATE TABLE ... using schema field types
- Each field stored as its own column (VARCHAR / NUMERIC / BOOLEAN)
"""
import json
import uuid
from datetime import datetime, timezone
from ....core.database import execute, fetch, fetchrow, get_pool


# ── type map: schema type → PostgreSQL column type ─────────────

_PG_TYPE = {
    "text":          "VARCHAR",
    "formattedText": "VARCHAR",
    "date":          "VARCHAR",
    "number":        "NUMERIC",
    "boolean":       "BOOLEAN",
}


# ── schema meta-table ───────────────────────────────────────────

async def save_schema(table_name: str, schema: list) -> None:
    now = datetime.now(timezone.utc).isoformat()
    await execute(
        """
        INSERT INTO datastore_schemas (table_name, schema, created_at)
        VALUES ($1, $2, $3)
        ON CONFLICT (table_name) DO UPDATE
            SET schema = EXCLUDED.schema, created_at = EXCLUDED.created_at
        """,
        table_name, json.dumps(schema), now,
    )


async def get_schema(table_name: str) -> list | None:
    row = await fetchrow(
        "SELECT schema FROM datastore_schemas WHERE table_name = $1", table_name
    )
    if not row:
        return None
    return json.loads(row["schema"])


async def list_schemas() -> list[dict]:
    rows = await fetch("SELECT table_name, schema, created_at FROM datastore_schemas")
    return [
        {
            "table_name": r["table_name"],
            "schema":     json.loads(r["schema"]),
            "created_at": str(r["created_at"]) if r["created_at"] else None,
        }
        for r in rows
    ]


# ── dynamic table creation ─────────────────────────────────────

async def create_table_from_schema(table_name: str, schema: list) -> dict:
    """
    Dynamically CREATE TABLE in PostgreSQL.
    Primary key: id VARCHAR.
    Each schema field becomes its own typed column.
    """
    # Build column definitions
    col_defs = ["id VARCHAR PRIMARY KEY", "created_at VARCHAR"]
    for field in schema:
        col_name = field["field_id"]
        pg_type  = _PG_TYPE.get(field.get("type", "text"), "VARCHAR")
        col_defs.append(f"{col_name} {pg_type}")

    ddl = f"CREATE TABLE IF NOT EXISTS {table_name} ({', '.join(col_defs)})"

    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(ddl)
        # Index on created_at for date range queries
        await conn.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{table_name}_created_at ON {table_name}(created_at)"
        )

    return {"created": True, "table_name": table_name}


# ── row insert ─────────────────────────────────────────────────

async def insert_row(table_name: str, schema: list, row_data: dict) -> str:
    record_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    cols   = ["id", "created_at"]
    vals   = [record_id, now]
    params = []

    for field in schema:
        fid   = field["field_id"]
        ftype = field.get("type", "text")
        val   = row_data.get(fid)

        if val is None:
            val = field.get("value")

        # Cast to correct Python type for asyncpg
        if ftype == "number" and val is not None:
            val = float(val)
        elif ftype == "boolean" and val is not None:
            val = bool(val)
        elif val is not None:
            val = str(val)

        cols.append(fid)
        vals.append(val)

    placeholders = ", ".join(f"${i+1}" for i in range(len(vals)))
    col_str = ", ".join(cols)
    sql = f"INSERT INTO {table_name} ({col_str}) VALUES ({placeholders})"

    await execute(sql, *vals)
    return record_id


# ── row queries ────────────────────────────────────────────────

async def list_rows(table_name: str) -> list[dict]:
    rows = await fetch(f"SELECT * FROM {table_name} ORDER BY created_at DESC")
    return [dict(r) for r in rows]


async def get_row(table_name: str, record_id: str) -> dict | None:
    row = await fetchrow(f"SELECT * FROM {table_name} WHERE id = $1", record_id)
    return dict(row) if row else None
