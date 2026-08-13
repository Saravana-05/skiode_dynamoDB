"""
Dynamic datastore — create PostgreSQL / CockroachDB tables from a JSON
schema, then insert / query rows against those tables.

Schema field types supported:
    text          -> TEXT
    formattedText -> TEXT
    number        -> NUMERIC
    boolean       -> BOOLEAN
    date          -> TIMESTAMPTZ

Fields with cardinality == "list" are stored as TEXT holding a JSON array,
regardless of their declared type.

Self-initializing: the datastore_schemas and domain_attributes meta-tables
are created automatically on first use if they don't exist yet.
"""
import json
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from ....core.database import execute, fetch, fetchrow
from ..utils import clean, strip_none


# ── type helpers ────────────────────────────────────────────────

_PG_TYPE = {
    "text":          "TEXT",
    "formattedText": "TEXT",
    "date":          "TIMESTAMPTZ",
    "number":        "NUMERIC",
    "boolean":       "BOOLEAN",
}

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _safe_identifier(name: str) -> str:
    """
    Validate that `name` is safe to interpolate directly into SQL as an
    identifier (table or column name). asyncpg has no bind mechanism for
    identifiers, so this check is what stands between user input and SQL
    injection via table/column names. Raises ValueError if invalid.
    """
    if not name or not _IDENTIFIER_RE.match(name):
        raise ValueError(f"Invalid identifier: {name!r}")
    return name


def _column_type(field: dict) -> str:
    if field.get("cardinality") == "list":
        return "TEXT"  # JSON-encoded array stored as text
    return _PG_TYPE.get(field.get("type", "text"), "TEXT")


def _cast(value, field: dict):
    """Cast a Python value to the correct Postgres-bindable type."""
    if field.get("cardinality") == "list":
        return json.dumps(value) if value is not None else None
    if value is None:
        return None
    field_type = field.get("type", "text")
    if field_type == "number":
        return Decimal(str(value))
    if field_type == "boolean":
        return bool(value)
    if field_type == "date":
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value))
    return str(value)


# ── meta-table bootstrap ─────────────────────────────────────────

_meta_ready = False


async def _ensure_meta_tables() -> None:
    """Create the datastore_schemas / domain_attributes meta-tables if
    they don't exist yet. Runs at most once per process."""
    global _meta_ready
    if _meta_ready:
        return

    await execute("""
        CREATE TABLE IF NOT EXISTS datastore_schemas (
            table_name  TEXT PRIMARY KEY,
            schema      TEXT NOT NULL,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    await execute("""
        CREATE TABLE IF NOT EXISTS domain_attributes (
            id               TEXT PRIMARY KEY,
            domain_model_id  TEXT NOT NULL,
            attribute_name   TEXT NOT NULL,
            label            TEXT,
            field_type       TEXT,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    _meta_ready = True


# ── schemas meta-table helpers ───────────────────────────────────

async def save_schema(table_name: str, schema: list) -> None:
    """Persist the schema definition to the datastore_schemas table."""
    await _ensure_meta_tables()
    await execute(
        """
        INSERT INTO datastore_schemas (table_name, schema, created_at)
        VALUES ($1, $2, now())
        ON CONFLICT (table_name) DO UPDATE
            SET schema = EXCLUDED.schema
        """,
        table_name,
        json.dumps(schema),
    )


async def get_schema(table_name: str) -> list | None:
    """Return the schema list for a table, or None if not found."""
    await _ensure_meta_tables()
    row = await fetchrow(
        "SELECT schema FROM datastore_schemas WHERE table_name = $1", table_name
    )
    if not row:
        return None
    return json.loads(row["schema"])


async def list_schemas() -> list[dict]:
    """List all registered schemas."""
    await _ensure_meta_tables()
    rows = await fetch("SELECT table_name, schema, created_at FROM datastore_schemas")
    return [
        {
            "table_name": r["table_name"],
            "schema":     json.loads(r["schema"]),
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]


# ── domain attribute helpers ──────────────────────────────────────

async def save_domain_attribute(
    domain_model_id: str,
    attribute_name: str,
    label: str | None = None,
    field_type: str | None = None,
) -> str:
    """
    Persist a single domain-model attribute definition (this is the
    function the route handler was calling that previously didn't exist).
    Returns the generated attribute id.
    """
    await _ensure_meta_tables()
    attr_id = str(uuid.uuid4())
    await execute(
        """
        INSERT INTO domain_attributes
            (id, domain_model_id, attribute_name, label, field_type, created_at)
        VALUES ($1, $2, $3, $4, $5, now())
        """,
        attr_id,
        domain_model_id,
        attribute_name,
        label,
        field_type,
    )
    return attr_id


async def list_domain_attributes(domain_model_id: str) -> list[dict]:
    """List all attributes registered for a given domain model."""
    await _ensure_meta_tables()
    rows = await fetch(
        """
        SELECT id, domain_model_id, attribute_name, label, field_type, created_at
        FROM domain_attributes
        WHERE domain_model_id = $1
        ORDER BY created_at
        """,
        domain_model_id,
    )
    return [dict(r) for r in rows]


# ── dynamic table creation ───────────────────────────────────────

async def create_table_from_schema(table_name: str, schema: list) -> dict:
    """
    Create a real Postgres/CockroachDB table named `table_name`.

    - Primary key: id (TEXT)
    - Fixed columns: created_at, deleted_at (deleted_at enables the
      soft-delete / archive semantics that list_archived_rows expects)
    - One column per schema field, typed per _PG_TYPE. List-cardinality
      fields are stored as TEXT holding a JSON array.

    The schema itself is persisted separately via save_schema() — call
    that after this succeeds, same as before.

    Returns:
        {"created": True,  "table_name": ...}   <- new table
        {"created": False, "table_name": ..., "reason": "already exists"}
    """
    safe_table = _safe_identifier(table_name)

    await _ensure_meta_tables()

    existing = await fetchrow("SELECT to_regclass($1) AS reg", f'"{safe_table}"')
    if existing and existing["reg"]:
        return {"created": False, "table_name": table_name, "reason": "already exists"}

    columns = [
        '"id" TEXT PRIMARY KEY',
        '"created_at" TIMESTAMPTZ NOT NULL DEFAULT now()',
        '"deleted_at" TIMESTAMPTZ',
    ]

    for field in schema:
        col_name = _safe_identifier(field["field_id"])
        col_type = _column_type(field)
        columns.append(f'"{col_name}" {col_type}')

    ddl = f'CREATE TABLE "{safe_table}" (\n    ' + ",\n    ".join(columns) + "\n)"

    print(f"[datastore] Creating table '{safe_table}'...")
    await execute(ddl)
    print(f"[datastore] Table '{safe_table}' created.")

    return {"created": True, "table_name": table_name}


# ── row insert ───────────────────────────────────────────────────

async def insert_row(table_name: str, schema: list, row_data: dict) -> str:
    """
    Insert one row into a dynamic table.
    Each schema field becomes its own column.
    row_data keys must match field_id values in the schema.
    Returns the generated record_id (UUID string).
    """
    safe_table = _safe_identifier(table_name)

    record_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    columns = ['"id"', '"created_at"']
    values = [record_id, now]

    for field in schema:
        field_id = field["field_id"]
        col_name = _safe_identifier(field_id)
        value = row_data.get(field_id)
        if value is None:
            value = field.get("value")

        casted = _cast(value, field)
        if casted is not None:
            columns.append(f'"{col_name}"')
            values.append(casted)

    placeholders = ", ".join(f"${i + 1}" for i in range(len(values)))
    col_list = ", ".join(columns)

    query = f'INSERT INTO "{safe_table}" ({col_list}) VALUES ({placeholders})'
    await execute(query, *values)
    return record_id


# ── row queries ──────────────────────────────────────────────────

async def list_rows(table_name: str) -> list[dict]:
    """Return all non-deleted rows from a dynamic table."""
    safe_table = _safe_identifier(table_name)
    rows = await fetch(f'SELECT * FROM "{safe_table}" WHERE deleted_at IS NULL')
    return [clean(dict(r)) for r in rows]


async def list_archived_rows(table_name: str) -> list[dict]:
    """Return all soft-deleted (archived) rows, most recently deleted first."""
    safe_table = _safe_identifier(table_name)
    rows = await fetch(
        f'SELECT * FROM "{safe_table}" WHERE deleted_at IS NOT NULL ORDER BY deleted_at DESC'
    )
    return [dict(r) for r in rows]


async def get_row(table_name: str, record_id: str) -> dict | None:
    """Get one row by id."""
    safe_table = _safe_identifier(table_name)
    row = await fetchrow(f'SELECT * FROM "{safe_table}" WHERE id = $1', record_id)
    return clean(dict(row)) if row else None