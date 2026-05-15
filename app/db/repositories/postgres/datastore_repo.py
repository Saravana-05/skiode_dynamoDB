"""
PostgreSQL implementation of the dynamic datastore repo.

- Schema definitions stored in datastore_schemas table (table_name PK, schema TEXT)
- datastore_schemas is auto-created on first use (no manual init needed)
- Dynamic tables created with CREATE TABLE on first call
- Schema updates handled via ALTER TABLE ADD COLUMN IF NOT EXISTS
- Each field stored as its own typed column (VARCHAR / NUMERIC / BOOLEAN)
"""
import json
import uuid
from datetime import datetime, timezone
from ....core.database import execute, fetch, fetchrow, ensure_pool


# ── type map: schema type → PostgreSQL column type ─────────────

_PG_TYPE = {
    "text":          "VARCHAR",
    "formattedText": "VARCHAR",
    "date":          "VARCHAR",
    "number":        "NUMERIC",
    "boolean":       "BOOLEAN",
}


# ── auto-create the datastore_schemas meta-table ────────────────

_schemas_table_ready = False   # module-level flag, checked once per process


async def _ensure_datastore_schemas_table() -> None:
    """
    Create the datastore_schemas meta-table if it does not exist.
    Uses a module-level flag so the check runs at most once per process.
    """
    global _schemas_table_ready
    if _schemas_table_ready:
        return
    await execute(
        """
        CREATE TABLE IF NOT EXISTS datastore_schemas (
            table_name  VARCHAR PRIMARY KEY,
            schema      TEXT    NOT NULL,
            created_at  VARCHAR
        )
        """
    )
    print("[datastore] Meta-table 'datastore_schemas' ready (PostgreSQL).")
    _schemas_table_ready = True


# ── schema meta-table helpers ────────────────────────────────────

async def save_schema(table_name: str, schema: list) -> None:
    await _ensure_datastore_schemas_table()
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
    await _ensure_datastore_schemas_table()
    row = await fetchrow(
        "SELECT schema FROM datastore_schemas WHERE table_name = $1", table_name
    )
    if not row:
        return None
    return json.loads(row["schema"])


async def list_schemas() -> list[dict]:
    await _ensure_datastore_schemas_table()
    rows = await fetch(
        "SELECT table_name, schema, created_at FROM datastore_schemas ORDER BY created_at DESC"
    )
    return [
        {
            "table_name": r["table_name"],
            "schema":     json.loads(r["schema"]),
            "created_at": str(r["created_at"]) if r["created_at"] else None,
        }
        for r in rows
    ]


# ── dynamic table creation ──────────────────────────────────────

async def create_table_from_schema(table_name: str, schema: list) -> dict:
    """
    Create or update a real PostgreSQL table from a schema definition.

    First call:
      - CREATE TABLE with id (VARCHAR PK), created_at, and all schema fields
      - CREATE INDEX on created_at
      - Returns {"created": True}

    Subsequent calls (table already exists):
      - ALTER TABLE ADD COLUMN IF NOT EXISTS for any new fields
      - Returns {"created": False}

    Column names and table names are double-quoted to handle camelCase safely.
    """
    pool = await ensure_pool()
    async with pool.acquire() as conn:

        # ── Check whether the table already exists ──────────────
        # Use pg_catalog (works identically on PostgreSQL and CockroachDB)
        exists = await conn.fetchval(
            """
            SELECT EXISTS (
                SELECT 1 FROM pg_catalog.pg_tables
                WHERE schemaname = 'public' AND tablename = $1
            )
            """,
            table_name,
        )

        if not exists:
            # ── CREATE TABLE ────────────────────────────────────
            col_defs = ["id VARCHAR PRIMARY KEY", "created_at VARCHAR"]
            for field in schema:
                col_name = field["field_id"]
                pg_type  = _PG_TYPE.get(field.get("type", "text"), "VARCHAR")
                col_defs.append(f'"{col_name}" {pg_type}')

            ddl = f'CREATE TABLE "{table_name}" ({", ".join(col_defs)})'
            await conn.execute(ddl)

            # Index on created_at for date-range queries
            await conn.execute(
                f'CREATE INDEX IF NOT EXISTS "idx_{table_name}_created_at" '
                f'ON "{table_name}"(created_at)'
            )

            print(f"[datastore] Table '{table_name}' created in PostgreSQL.")
            return {"created": True, "table_name": table_name}

        else:
            # ── Table exists → add any new columns ──────────────
            existing_cols = {
                r["attname"]
                for r in await conn.fetch(
                    """
                    SELECT a.attname
                    FROM   pg_catalog.pg_attribute a
                    JOIN   pg_catalog.pg_class     c ON c.oid = a.attrelid
                    JOIN   pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                    WHERE  n.nspname = 'public'
                      AND  c.relname = $1
                      AND  a.attnum  > 0
                      AND  NOT a.attisdropped
                    """,
                    table_name,
                )
            }

            added = []
            for field in schema:
                col_name = field["field_id"]
                if col_name not in existing_cols:
                    pg_type = _PG_TYPE.get(field.get("type", "text"), "VARCHAR")
                    await conn.execute(
                        f'ALTER TABLE "{table_name}" ADD COLUMN IF NOT EXISTS "{col_name}" {pg_type}'
                    )
                    added.append(col_name)
                    print(f"[datastore] Added column '{col_name}' ({pg_type}) to '{table_name}'.")

            if added:
                print(f"[datastore] '{table_name}' updated — added {len(added)} column(s): {added}")

            return {"created": False, "table_name": table_name}


# ── row insert ──────────────────────────────────────────────────

async def insert_row(table_name: str, schema: list, row_data: dict) -> str:
    record_id = str(uuid.uuid4())
    now       = datetime.now(timezone.utc).isoformat()

    cols = ["id", "created_at"]
    vals = [record_id, now]

    for field in schema:
        fid   = field["field_id"]
        ftype = field.get("type", "text")
        val   = row_data.get(fid)

        # Fall back to schema default if caller didn't supply a value
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

    col_str      = ", ".join(f'"{c}"' for c in cols)
    placeholders = ", ".join(f"${i + 1}" for i in range(len(vals)))
    sql          = f'INSERT INTO "{table_name}" ({col_str}) VALUES ({placeholders})'

    await execute(sql, *vals)
    return record_id


# ── row queries ─────────────────────────────────────────────────

async def list_rows(table_name: str) -> list[dict]:
    rows = await fetch(f'SELECT * FROM "{table_name}" ORDER BY created_at DESC')
    return [dict(r) for r in rows]


async def get_row(table_name: str, record_id: str) -> dict | None:
    row = await fetchrow(f'SELECT * FROM "{table_name}" WHERE id = $1', record_id)
    return dict(row) if row else None
