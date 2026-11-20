"""
PostgreSQL implementation of the dynamic datastore repo.

- Schema definitions stored in datastore_schemas table (table_name PK, schema TEXT)
- datastore_schemas is auto-created on first use (no manual init needed)
- Dynamic tables created with CREATE TABLE on first call
- Schema updates handled via ALTER TABLE ADD COLUMN IF NOT EXISTS
- Each field stored as its own typed column (VARCHAR / NUMERIC / BOOLEAN)
- domain_attributes stores one row per (domain, field) with English label
- attribute_translations is a LINKED TABLE (FK -> domain_attributes.id)
  storing one row per (attribute, language) — en / ta / ar labels
"""
import json
import re

from datetime import datetime, timezone
from ....core.database import execute, fetch, fetchrow, ensure_pool


# ── type map: schema type → PostgreSQL column type ─────────────

_PG_TYPE = {
    "text":          "VARCHAR",
    "formattedText": "VARCHAR",
    "date":          "VARCHAR",
    "number":        "NUMERIC",
    "boolean":       "BOOLEAN",
    # A field tagged as a domain model: logical type is "domain_model" (kept in
    # the saved schema + domain_attributes.field_type); physically it holds the
    # related record's id, so the column is VARCHAR like the other id columns.
    "domain_model":  "VARCHAR",
}


def _stringify_id(row: dict) -> dict:
    """
    `id` columns here hold values well beyond JavaScript's safe integer
    range (Number.MAX_SAFE_INTEGER ≈ 9×10^15, ~16 digits) — these ids run
    to 19 digits. Returned as a bare JSON number, the browser's JSON.parse
    silently rounds it during parsing, before any frontend code even sees
    it. That corrupted id is then sent back on update/delete calls, matches
    zero rows in Postgres, and the call still reports "success" — looking
    exactly like a successful no-op. Stringifying `id` here (matching how
    insert_row/update_row/delete_row already return record_id as a string)
    keeps the exact value intact end to end.
    """
    if row.get("id") is not None:
        row["id"] = str(row["id"])
    return row


# ── auto-create the datastore_schemas meta-table ────────────────

_schemas_table_ready = False   # module-level flag, checked once per process


async def _ensure_datastore_schemas_table() -> None:
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
    # Backfill: project_id is nullable so pre-existing domain models
    # (created before Projects existed) stay valid and global/unassigned —
    # they just never get a project_id set.
    await execute(
        "ALTER TABLE datastore_schemas ADD COLUMN IF NOT EXISTS project_id INTEGER"
    )
    # Modules (Project → Module → Domain model): nullable for the same reason.
    await execute(
        "ALTER TABLE datastore_schemas ADD COLUMN IF NOT EXISTS module_id INTEGER"
    )
    # Business label — the human-friendly name the user typed for the domain
    # model (e.g. "Client Details") while table_name keeps the storage name
    # (e.g. "ClientDetails"). Nullable so pre-existing domain models stay valid.
    await execute(
        "ALTER TABLE datastore_schemas ADD COLUMN IF NOT EXISTS label VARCHAR"
    )
    # Physical Postgres schema the domain model's table lives in. Domain models
    # that belong to a project are created in that project's own schema (see
    # ensure_project_schema); the rest — and every table created before this
    # column existed — stay in "public", which is exactly what the DEFAULT gives.
    await execute(
        "ALTER TABLE datastore_schemas ADD COLUMN IF NOT EXISTS pg_schema VARCHAR NOT NULL DEFAULT 'public'"
    )
    # Visible name + physical table name of the domain model. table_name stays the
    # unique internal KEY every API, ABAC rule, attribute and relationship uses;
    # domain_name is what the user typed and what the table is called inside the
    # project's schema. Two projects can therefore both have a "Department":
    # keys "Department" and "Department__5", both with domain_name "Department".
    # NULL (rows from before this column) means domain_name == table_name.
    await execute(
        "ALTER TABLE datastore_schemas ADD COLUMN IF NOT EXISTS domain_name VARCHAR"
    )
    # Safety net: whenever a domain model row disappears from
    # datastore_schemas (API delete, manual DELETE in DBeaver, a script...),
    # Postgres itself removes its attributes (attribute_translations cascade
    # from domain_attributes via FK) and its relationships. No code path can
    # forget to clean up.
    #
    # NOTE: this trigger is OPTIONAL. Some PostgreSQL-compatible backends
    # (e.g. CockroachDB) reject the PL/pgSQL function body ("no data source
    # matches prefix: old"). If that happens we must NOT fail every request
    # that touches datastore_schemas, so any error here is logged and
    # skipped. delete_domain() already removes attributes and relationships
    # explicitly inside its own transaction, so the API delete path stays
    # correct without the trigger.
    try:
        await execute(
            """
            CREATE OR REPLACE FUNCTION cleanup_deleted_domain() RETURNS trigger AS $$
            BEGIN
                IF to_regclass('domain_attributes') IS NOT NULL THEN
                    DELETE FROM domain_attributes WHERE dmo_name = OLD.table_name;
                END IF;
                IF to_regclass('domain_relationships') IS NOT NULL THEN
                    DELETE FROM domain_relationships
                    WHERE from_dmo = OLD.table_name OR to_dmo = OLD.table_name;
                END IF;
                RETURN OLD;
            END;
            $$ LANGUAGE plpgsql
            """
        )
        await execute("DROP TRIGGER IF EXISTS trg_cleanup_deleted_domain ON datastore_schemas")
        await execute(
            """
            CREATE TRIGGER trg_cleanup_deleted_domain
            AFTER DELETE ON datastore_schemas
            FOR EACH ROW EXECUTE FUNCTION cleanup_deleted_domain()
            """
        )
    except Exception as exc:
        print(
            "[datastore] Skipping optional cleanup trigger "
            f"(not supported by this database): {exc}"
        )
    print("[datastore] Meta-table 'datastore_schemas' ready (PostgreSQL).")
    _schemas_table_ready = True


# ── per-project datastore_schemas ───────────────────────────────
#
# Every project gets its OWN datastore_schemas table inside its Postgres schema
# (bank_management.datastore_schemas) holding only that project's domain models.
# Domain models without a project stay in public.datastore_schemas.
#
# Because most APIs only know a domain model's key (table_name), a tiny
# directory table public.datastore_registry maps key -> (physical schema,
# schema holding its datastore_schemas row, project). The registry holds no
# schema JSON - the real record always lives in the project's own table.
#
# Rows created before this change still sit in public.datastore_schemas; the
# registry is back-filled from them with meta_schema = 'public', so everything
# keeps working until migrate_domains_to_project_schemas moves them.

_registry_ready = False
_meta_ready: set[str] = set()


async def _ensure_registry() -> None:
    global _registry_ready
    if _registry_ready:
        return
    await _ensure_datastore_schemas_table()
    await execute(
        """
        CREATE TABLE IF NOT EXISTS datastore_registry (
            table_name   VARCHAR PRIMARY KEY,
            pg_schema    VARCHAR NOT NULL DEFAULT 'public',
            meta_schema  VARCHAR NOT NULL DEFAULT 'public',
            project_id   INTEGER
        )
        """
    )
    await backfill_registry()
    print("[datastore] Directory table 'datastore_registry' ready (PostgreSQL).")
    _registry_ready = True


async def backfill_registry() -> None:
    """Register every row still in the legacy public.datastore_schemas (idempotent).
    Also run by the migration script, in case an older instance wrote rows there
    after the registry was first created."""
    await execute(
        "INSERT INTO datastore_registry (table_name, pg_schema, meta_schema, project_id) "
        "SELECT table_name, COALESCE(pg_schema, 'public'), 'public', project_id "
        "FROM datastore_schemas ON CONFLICT (table_name) DO NOTHING"
    )


def _meta_ref(meta_schema: str | None) -> str:
    if not meta_schema or meta_schema == "public":
        return "datastore_schemas"
    return f'"{meta_schema}".datastore_schemas'


async def _ensure_meta(meta_schema: str | None) -> str:
    """Make sure <meta_schema>.datastore_schemas exists; return its quoted reference."""
    if not meta_schema or meta_schema == "public":
        await _ensure_datastore_schemas_table()
        return "datastore_schemas"
    if meta_schema not in _meta_ready:
        await execute(f'CREATE SCHEMA IF NOT EXISTS "{meta_schema}"')
        await execute(
            f"""
            CREATE TABLE IF NOT EXISTS "{meta_schema}".datastore_schemas (
                table_name   VARCHAR PRIMARY KEY,
                schema       TEXT    NOT NULL,
                created_at   VARCHAR,
                project_id   INTEGER,
                module_id    INTEGER,
                label        VARCHAR,
                pg_schema    VARCHAR NOT NULL DEFAULT '{meta_schema}',
                domain_name  VARCHAR
            )
            """
        )
        _meta_ready.add(meta_schema)
        print(f"[datastore] '{meta_schema}'.datastore_schemas ready.")
    return _meta_ref(meta_schema)


async def _meta_of(table_name: str) -> str:
    """Reference of the datastore_schemas table that holds this domain model's row
    (public one for unregistered keys)."""
    await _ensure_registry()
    row = await fetchrow("SELECT meta_schema FROM datastore_registry WHERE table_name = $1", table_name)
    return await _ensure_meta(row["meta_schema"] if row else "public")


async def _meta_schemas() -> list[str]:
    await _ensure_registry()
    rows = await fetch("SELECT DISTINCT meta_schema FROM datastore_registry")
    return sorted({r["meta_schema"] for r in rows} | {"public"})


async def _fetch_all_meta(sql: str, *args) -> list:
    """Run `sql` against every datastore_schemas table. Write the table as {t}."""
    out: list = []
    for s in await _meta_schemas():
        out.extend(await fetch(sql.replace("{t}", await _ensure_meta(s)), *args))
    return out


async def _register(table_name: str, pg_schema: str, meta_schema: str, project_id) -> None:
    await execute(
        "INSERT INTO datastore_registry (table_name, pg_schema, meta_schema, project_id) "
        "VALUES ($1, $2, $3, $4) "
        "ON CONFLICT (table_name) DO UPDATE SET pg_schema = EXCLUDED.pg_schema, "
        "meta_schema = EXCLUDED.meta_schema, project_id = EXCLUDED.project_id",
        table_name, pg_schema or "public", meta_schema or "public",
        int(project_id) if project_id not in (None, "") else None,
    )


async def move_meta_row(table_name: str, target_schema: str) -> bool:
    """Move one domain model's datastore_schemas row into <target_schema>.datastore_schemas
    (used by the migration script and when a model changes project). True if it moved."""
    src_ref = await _meta_of(table_name)
    dst_ref = await _ensure_meta(target_schema)
    if src_ref == dst_ref:
        return False
    cols = "table_name, schema, created_at, project_id, module_id, label, domain_name"
    moved = await fetchrow(f"SELECT 1 FROM {src_ref} WHERE table_name = $1", table_name)
    if not moved:
        return False
    await execute(
        f"INSERT INTO {dst_ref} ({cols}, pg_schema) "
        f"SELECT {cols}, $2 FROM {src_ref} WHERE table_name = $1 "
        f"ON CONFLICT (table_name) DO NOTHING",
        table_name, target_schema,
    )
    await execute(f"DELETE FROM {src_ref} WHERE table_name = $1", table_name)
    await execute(
        "UPDATE datastore_registry SET pg_schema = $2, meta_schema = $2 WHERE table_name = $1",
        table_name, target_schema,
    )
    return True


async def ensure_project_meta(project_id) -> str | None:
    """Create the project's schema and its own datastore_schemas table (idempotent).
    Called when a project is created, so the table exists before the first domain
    model. Returns the schema name, or None if the project doesn't exist."""
    await _ensure_registry()
    schema = await ensure_project_schema(project_id)
    if schema == "public":
        return None
    await _ensure_meta(schema)
    return schema


async def count_domains_in_module(module_id) -> int:
    rows = await _fetch_all_meta("SELECT COUNT(*) AS n FROM {t} WHERE module_id = $1", int(module_id))
    return sum(int(r["n"]) for r in rows)


async def detach_module_domains(module_ids: list[int]) -> None:
    for s in await _meta_schemas():
        t = await _ensure_meta(s)
        await execute(f"UPDATE {t} SET module_id = NULL WHERE module_id = ANY($1::INTEGER[])", module_ids)


# ── per-project Postgres schemas ────────────────────────────────
#
# Project "Bank Management" -> schema bank_management, so its domain models are
# bank_management."Department", bank_management."Branch", ... and DBeaver groups
# them under the project instead of one flat list in "public".
#
# The schema each domain model lives in is recorded in
# datastore_schemas.pg_schema (and the project's schema in projects.pg_schema),
# so renaming/deleting a project or running on several workers never has to
# re-derive it from a name.

_RESERVED_SCHEMAS = {"public", "idam", "information_schema", "pg_catalog", "pg_toast", "crdb_internal"}
_projects_schema_col_ready = False


def _schema_slug(name: str | None) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")[:40].strip("_")
    if s and s[0].isdigit():
        s = "p_" + s
    return s


def _qualify(pg_schema: str | None, table_name: str) -> str:
    """Quoted table reference; "public" stays unqualified (legacy behaviour)."""
    if pg_schema and pg_schema != "public":
        return f'"{pg_schema}"."{table_name}"'
    return f'"{table_name}"'


async def _stored_location(table_name: str) -> tuple[str, str] | None:
    """(pg_schema, physical table name) for a domain-model key, or None if unregistered."""
    meta = await _meta_of(table_name)
    row = await fetchrow(
        "SELECT pg_schema, COALESCE(domain_name, table_name) AS physical "
        f"FROM {meta} WHERE table_name = $1", table_name)
    return ((row["pg_schema"] or "public"), row["physical"]) if row else None


async def _stored_schema(table_name: str) -> str | None:
    loc = await _stored_location(table_name)
    return loc[0] if loc else None


async def _ref(table_name: str) -> str:
    """Schema-qualified, quoted reference to a domain model's physical table
    (table_name is the internal key; unregistered names fall back to themselves)."""
    loc = await _stored_location(table_name)
    return _qualify(*loc) if loc else _qualify("public", table_name)


async def schemas_of(table_names: list[str]) -> dict[str, tuple[str, str]]:
    """{key: (pg_schema, physical table name)} for the given domain models (query builder)."""
    if not table_names:
        return {}
    rows = await _fetch_all_meta(
        "SELECT table_name, pg_schema, COALESCE(domain_name, table_name) AS physical "
        "FROM {t} WHERE table_name = ANY($1::varchar[])",
        list(table_names),
    )
    return {r["table_name"]: ((r["pg_schema"] or "public"), r["physical"]) for r in rows}


def _same_project(a, b) -> bool:
    return str(a or "") == str(b or "")


async def resolve_for_save(name: str, project_id, is_new: bool = False) -> dict:
    """Decide what a create/save request for `name` in `project_id` means.

    Names are unique PER PROJECT (case-insensitive). Returns
      {"key", "domain_name", "exists": bool}              -> go ahead
      {"conflict": "<message>"}                           -> duplicate, reject
    `name` may be the visible name or the key of an existing model (the frontend
    sends back the table_name it was given when it saves edits).
    """
    await _ensure_registry()
    if name.lower() == "datastore_schemas":     # would collide with the per-project meta table
        return {"conflict": "'datastore_schemas' is a reserved name. Choose a different name."}
    rows = await _fetch_all_meta(
        "SELECT table_name, project_id, COALESCE(domain_name, table_name) AS dn "
        "FROM {t} WHERE lower(table_name) = lower($1) "
        "OR lower(COALESCE(domain_name, table_name)) = lower($1)", name)
    mine = [r for r in rows if _same_project(r["project_id"], project_id)]
    # editing an existing model: exact key, or exact visible name, in this project
    for r in mine:
        if r["table_name"] == name or r["dn"] == name:
            if is_new:
                return {"conflict": f"A domain model named '{r['dn']}' already exists in this project. Choose a different name."}
            return {"key": r["table_name"], "domain_name": r["dn"], "exists": True}
    if mine:   # differs only by letter case
        return {"conflict": f"A domain model named '{mine[0]['dn']}' already exists in this project. Choose a different name."}
    # brand-new in this project: the key is the name itself when free, else name__<project>
    taken = {r["table_name"] for r in await fetch(
        "SELECT table_name FROM datastore_registry WHERE lower(table_name) LIKE lower($1) || '%'", name)}
    key, n = name, 0
    suffix = str(project_id) if project_id not in (None, "") else "np"
    while key in taken:
        key = f"{name}__{suffix}" + (f"_{n}" if n else "")
        n += 1
    return {"key": key, "domain_name": name, "exists": False}


async def find_domains_ci(table_name: str) -> list[dict]:
    """Registered domain models with this key or visible name (any letter case)."""
    rows = await _fetch_all_meta(
        "SELECT table_name, project_id, COALESCE(domain_name, table_name) AS dn FROM {t} "
        "WHERE lower(table_name) = lower($1) OR lower(COALESCE(domain_name, table_name)) = lower($1)",
        table_name,
    )
    return [{"table_name": r["table_name"], "domain_name": r["dn"],
             "project_id": str(r["project_id"]) if r["project_id"] is not None else None}
            for r in rows]


async def _ensure_projects_schema_col() -> None:
    global _projects_schema_col_ready
    if _projects_schema_col_ready:
        return
    await execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS pg_schema VARCHAR")
    _projects_schema_col_ready = True


async def _pick_schema_name(project_id: int, project_name: str | None, current: str | None = None) -> str:
    slug = _schema_slug(project_name)
    candidates = ([slug, f"{slug}_{project_id}"] if slug else []) + [f"project_{project_id}"]
    for name in candidates:
        if name in _RESERVED_SCHEMAS or name.startswith("pg_"):
            continue
        if name == current:
            return name
        in_db = await fetchrow("SELECT 1 FROM pg_catalog.pg_namespace WHERE nspname = $1", name)
        used = await fetchrow(
            "SELECT 1 FROM projects WHERE pg_schema = $1 AND id <> $2", name, project_id
        )
        if not in_db and not used:
            return name
    return f"project_{project_id}"


async def project_schema_name(project_id) -> str:
    """Schema recorded for a project WITHOUT creating anything ("public" if none)."""
    if project_id in (None, ""):
        return "public"
    await _ensure_projects_schema_col()
    row = await fetchrow("SELECT pg_schema FROM projects WHERE id = $1", int(project_id))
    return (row["pg_schema"] if row and row["pg_schema"] else "public")


async def ensure_project_schema(project_id) -> str:
    """Create (once) and return the Postgres schema that holds a project's domain
    models. Falls back to "public" if the project doesn't exist."""
    if project_id in (None, ""):
        return "public"
    pid = int(project_id)
    await _ensure_projects_schema_col()
    row = await fetchrow("SELECT name, pg_schema FROM projects WHERE id = $1", pid)
    if not row:
        return "public"
    name = row["pg_schema"] or await _pick_schema_name(pid, row["name"])
    await execute(f'CREATE SCHEMA IF NOT EXISTS "{name}"')
    if not row["pg_schema"]:
        await execute("UPDATE projects SET pg_schema = $2 WHERE id = $1", pid, name)
        print(f"[datastore] Project {pid} -> schema '{name}'.")
    return name


async def rename_project_schema(project_id, new_project_name: str) -> str | None:
    """Project renamed: rename its schema to match. Returns the schema name (None =
    the project has no schema yet; it gets one, named after the new name, on first use)."""
    pid = int(project_id)
    await _ensure_projects_schema_col()
    row = await fetchrow("SELECT pg_schema FROM projects WHERE id = $1", pid)
    old = row["pg_schema"] if row else None
    if not old:
        return None
    new = await _pick_schema_name(pid, new_project_name, current=old)
    if new == old:
        return old
    await execute(f'ALTER SCHEMA "{old}" RENAME TO "{new}"')
    await execute("UPDATE projects SET pg_schema = $2 WHERE id = $1", pid, new)
    # The project's own datastore_schemas table moved with the schema; repoint its rows,
    # the legacy rows still in public, and the directory.
    _meta_ready.discard(old)
    await _ensure_registry()
    await _ensure_meta(new)
    await execute(f'UPDATE "{new}".datastore_schemas SET pg_schema = $2 WHERE pg_schema = $1', old, new)
    await execute("UPDATE datastore_schemas SET pg_schema = $2 WHERE pg_schema = $1", old, new)
    await execute(
        "UPDATE datastore_registry SET pg_schema = $2, "
        "meta_schema = CASE WHEN meta_schema = $1 THEN $2 ELSE meta_schema END "
        "WHERE pg_schema = $1 OR meta_schema = $1", old, new)
    return new


# ── schema meta-table helpers ────────────────────────────────────

async def save_schema(
    table_name: str,
    schema: list,
    project_id: int | str | None = None,
    module_id: int | str | None = None,
    label: str | None = None,
    domain_name: str | None = None,
) -> None:
    await _ensure_registry()
    now = datetime.now(timezone.utc).isoformat()
    # An existing domain model keeps the schema it physically lives in; a new one
    # goes into its project's schema, and its datastore_schemas row into that
    # project's own datastore_schemas table ("public" when it has no project).
    reg = await fetchrow(
        "SELECT pg_schema, meta_schema FROM datastore_registry WHERE table_name = $1", table_name)
    if reg:
        pg_schema, meta_schema = reg["pg_schema"], reg["meta_schema"]
    else:
        pg_schema = await ensure_project_schema(project_id)
        meta_schema = pg_schema
    t = await _ensure_meta(meta_schema)
    # Note: project_id is only ever SET on INSERT or when a value is
    # explicitly passed in - a plain re-save (e.g. adding a field to an
    # existing domain model, project_id=None) must not silently detach
    # the domain model from the project it already belongs to.
    await execute(
        f"""
        INSERT INTO {t} (table_name, schema, created_at, project_id, module_id, label, pg_schema, domain_name)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        ON CONFLICT (table_name) DO UPDATE
            SET schema = EXCLUDED.schema,
                created_at = EXCLUDED.created_at,
                project_id = COALESCE(EXCLUDED.project_id, {t}.project_id),
                module_id  = COALESCE(EXCLUDED.module_id,  {t}.module_id),
                -- Same rule as project_id: a plain re-save that sends no
                -- label must not wipe the label that was typed earlier.
                label      = COALESCE(EXCLUDED.label,      {t}.label)
        """,
        table_name, json.dumps(schema), now,
        int(project_id) if project_id is not None else None,
        int(module_id) if module_id is not None else None,
        (label.strip() or None) if isinstance(label, str) else None,
        # Only used when the row is new (ON CONFLICT never rewrites pg_schema).
        pg_schema,
        domain_name or table_name,
    )
    stored = await fetchrow(f"SELECT project_id FROM {t} WHERE table_name = $1", table_name)
    await _register(table_name, pg_schema, meta_schema, stored["project_id"] if stored else project_id)


async def get_schema(table_name: str) -> dict | None:
    meta = await _meta_of(table_name)
    row = await fetchrow(
        "SELECT schema, project_id, module_id, label, COALESCE(domain_name, table_name) AS domain_name "
        f"FROM {meta} WHERE table_name = $1", table_name
    )
    if not row:
        return None
    return {
        "schema":     json.loads(row["schema"]),
        "label":      row["label"],
        "domain_name": row["domain_name"],
        "db_backend": "postgresql",
        "project_id": str(row["project_id"]) if row["project_id"] is not None else None,
        "module_id":  str(row["module_id"]) if row["module_id"] is not None else None,
    }


async def list_schemas(
    project_id: int | str | None = None,
    module_id: int | str | None = None,
) -> list[dict]:
    clauses, args = [], []
    if project_id is not None:
        args.append(int(project_id))
        clauses.append(f"project_id = ${len(args)}")
    if module_id is not None:
        args.append(int(module_id))
        clauses.append(f"module_id = ${len(args)}")
    where = f"WHERE {' AND '.join(clauses)} " if clauses else ""
    # A project's models are all in ITS datastore_schemas table (+ public for rows
    # not migrated yet); with no project filter every table is read.
    if project_id is not None:
        await _ensure_registry()
        proj_schema = await project_schema_name(project_id)
        schemas = sorted({proj_schema, "public"})
    else:
        schemas = await _meta_schemas()
    rows = []
    for s in schemas:
        t = await _ensure_meta(s)
        rows.extend(await fetch(
            "SELECT table_name, schema, created_at, project_id, module_id, label, "
            f"COALESCE(domain_name, table_name) AS domain_name FROM {t} {where}",
            *args,
        ))
    rows.sort(key=lambda r: r["created_at"] or "", reverse=True)
    return [
        {
            "table_name": r["table_name"],
            "domain_name": r["domain_name"],
            "label":      r["label"],
            "schema":     json.loads(r["schema"]),
            "created_at": str(r["created_at"]) if r["created_at"] else None,
            "db_backend": "postgresql",
            "project_id": str(r["project_id"]) if r["project_id"] is not None else None,
            "module_id":  str(r["module_id"]) if r["module_id"] is not None else None,
        }
        for r in rows
    ]


# ── dynamic table creation ──────────────────────────────────────

async def create_table_from_schema(table_name: str, schema: list, project_id: int | str | None = None,
                                   domain_name: str | None = None) -> dict:
    # table_name is the internal key; the physical table is called domain_name
    # (default: the key). A domain model that is already registered stays where
    # it physically is; a new one goes into its project's schema ("public" when
    # it has no project).
    loc = await _stored_location(table_name)
    if loc:
        pg_schema, physical = loc
    else:
        pg_schema = await ensure_project_schema(project_id)
        physical = domain_name or table_name
    tref = _qualify(pg_schema, physical)

    pool = await ensure_pool()
    async with pool.acquire() as conn:

        exists = await conn.fetchval(
            """
            SELECT EXISTS (
                SELECT 1 FROM pg_catalog.pg_tables
                WHERE schemaname = $2 AND tablename = $1
            )
            """,
            physical, pg_schema,
        )

        if not exists:
            col_defs = ["id SERIAL PRIMARY KEY", "created_at VARCHAR", "deleted_at VARCHAR"]

            for field in schema:
                col_name = field["field_id"]
                pg_type  = _PG_TYPE.get(field.get("type", "text"), "VARCHAR")
                col_defs.append(f'"{col_name}" {pg_type}')

            ddl = f'CREATE TABLE {tref} ({", ".join(col_defs)})'
            await conn.execute(ddl)

            await conn.execute(
                f'CREATE INDEX IF NOT EXISTS "idx_{physical}_created_at" '
                f'ON {tref}(created_at)'
            )

            print(f"[datastore] Table '{table_name}' created in PostgreSQL (schema '{pg_schema}').")
            return {"created": True, "table_name": table_name, "domain_name": physical, "schema": pg_schema}

        else:
            existing_cols = {
                r["attname"]
                for r in await conn.fetch(
                    """
                    SELECT a.attname
                    FROM   pg_catalog.pg_attribute a
                    JOIN   pg_catalog.pg_class     c ON c.oid = a.attrelid
                    JOIN   pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                    WHERE  n.nspname = $2
                      AND  c.relname = $1
                      AND  a.attnum  > 0
                      AND  NOT a.attisdropped
                    """,
                    physical, pg_schema,
                )
            }

            added = []

            # ── Backfill baseline columns ────────────────────────────
            # Older tables (or ones created before `deleted_at` became
            # part of the baseline) can be missing these. Every table
            # is expected to have them by list_rows / delete_row /
            # list_archived_rows, so guarantee they exist on every
            # POST /datastore/create call, not just at initial creation.
            for base_col, base_type in (("created_at", "VARCHAR"), ("deleted_at", "VARCHAR")):
                if base_col not in existing_cols:
                    await conn.execute(
                        f'ALTER TABLE {tref} ADD COLUMN IF NOT EXISTS "{base_col}" {base_type}'
                    )
                    added.append(base_col)
                    print(f"[datastore] Backfilled baseline column '{base_col}' on '{table_name}'.")

            for field in schema:
                col_name = field["field_id"]
                if col_name not in existing_cols:
                    pg_type = _PG_TYPE.get(field.get("type", "text"), "VARCHAR")
                    await conn.execute(
                        f'ALTER TABLE {tref} ADD COLUMN IF NOT EXISTS "{col_name}" {pg_type}'
                    )
                    added.append(col_name)
                    print(f"[datastore] Added column '{col_name}' ({pg_type}) to '{table_name}'.")

            if added:
                print(f"[datastore] '{table_name}' updated — added {len(added)} column(s): {added}")

            return {"created": False, "table_name": table_name, "domain_name": physical, "schema": pg_schema}


# ── row insert ──────────────────────────────────────────────────

async def insert_row(table_name: str, schema: list, row_data: dict) -> str:
    now  = datetime.now(timezone.utc).isoformat()

    cols = ["created_at"]
    vals = [now]

    for field in schema:
        fid   = field["field_id"]
        ftype = field.get("type", "text")
        val   = row_data.get(fid)

        if val is None:
            val = field.get("value")

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

    pool = await ensure_pool()
    async with pool.acquire() as conn:
        record_id = await conn.fetchval(
            f'INSERT INTO {await _ref(table_name)} ({col_str}) VALUES ({placeholders}) RETURNING id',
            *vals
        )
    return str(record_id)


# ── row queries ─────────────────────────────────────────────────

async def list_rows(table_name: str, include_deleted: bool = False) -> list[dict]:
    if include_deleted:
        rows = await fetch(f'SELECT * FROM {await _ref(table_name)} ORDER BY created_at DESC')
    else:
        rows = await fetch(f'SELECT * FROM {await _ref(table_name)} WHERE deleted_at IS NULL ORDER BY created_at DESC')
    return [_stringify_id(dict(r)) for r in rows]

async def list_archived_rows(table_name: str) -> list[dict]:
    rows = await fetch(
        f'SELECT * FROM {await _ref(table_name)} WHERE deleted_at IS NOT NULL ORDER BY deleted_at DESC'
    )
    return [_stringify_id(dict(r)) for r in rows]

async def get_row(table_name: str, record_id: str) -> dict | None:
    row = await fetchrow(f'SELECT * FROM {await _ref(table_name)} WHERE id = $1', int(record_id))
    return _stringify_id(dict(row)) if row else None


# ── row update ──────────────────────────────────────────────────

async def update_row(table_name: str, record_id: str, row_data: dict) -> dict:
    if not row_data:
        return {"status": "error", "message": "No data provided"}

    meta = await _meta_of(table_name)
    schema_row = await fetchrow(
        "SELECT schema, pg_schema, COALESCE(domain_name, table_name) AS physical "
        f"FROM {meta} WHERE table_name = $1", table_name
    )
    schema = json.loads(schema_row["schema"]) if schema_row else []
    pg_schema = (schema_row["pg_schema"] if schema_row else None) or "public"
    physical = (schema_row["physical"] if schema_row else None) or table_name
    tref = _qualify(pg_schema, physical)

    # Check if table has versionOf column (versioned table)
    pool = await ensure_pool()
    async with pool.acquire() as conn:
        existing_cols = {
            r["attname"]
            for r in await conn.fetch(
                """
                SELECT a.attname FROM pg_catalog.pg_attribute a
                JOIN pg_catalog.pg_class c ON c.oid = a.attrelid
                JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = $2 AND c.relname = $1
                AND a.attnum > 0 AND NOT a.attisdropped
                """,
                physical, pg_schema,
            )
        }

        is_versioned = "versionOf" in existing_cols or "versionof" in existing_cols

        if is_versioned:
            now = datetime.now(timezone.utc).isoformat()

            # 1. Mark old row inactive
            await conn.execute(
                f'UPDATE {tref} SET "toDate" = $1, "isActive" = $2 WHERE id = $3',
                now, False, int(record_id)
            )

            # 2. Get old row data to copy into new row
            old_row = await conn.fetchrow(
                f'SELECT * FROM {tref} WHERE id = $1', int(record_id)
            )
            old_dict = dict(old_row) if old_row else {}

            # 3. Build insert with updated values
            cols = ["created_at", "isActive", "fromDate", "toDate", "versionOf"]
            vals = [now, True, now, None, str(record_id)] # versionOf = previous row id

            for field in schema:
                fid = field["field_id"]
                if fid in ("id", "created_at", "isActive", "fromDate", "toDate", "versionOf"):
                    continue
                ftype = field.get("type", "text")
                # use updated value if provided, else keep old value
                val = row_data.get(fid, old_dict.get(fid))
                if ftype == "number" and val is not None:
                    val = float(val)
                elif ftype == "boolean" and val is not None:
                    val = bool(val)
                elif val is not None:
                    val = str(val)
                cols.append(fid)
                vals.append(val)

            col_str = ", ".join(f'"{c}"' for c in cols)
            placeholders = ", ".join(f"${i + 1}" for i in range(len(vals)))

            new_id = await conn.fetchval(
                f'INSERT INTO {tref} ({col_str}) VALUES ({placeholders}) RETURNING id',
                *vals
            )
            return {"status": "success", "record_id": str(new_id), "versioned": True, "previous_id": record_id}

        # Non-versioned: plain update (original logic)
        cols = []
        vals = []
        for field in schema:
            fid = field["field_id"]
            ftype = field.get("type", "text")
            if fid not in row_data:
                continue
            val = row_data[fid]
            if ftype == "number" and val is not None:
                val = float(val)
            elif ftype == "boolean" and val is not None:
                val = bool(val)
            elif val is not None:
                val = str(val)
            cols.append(fid)
            vals.append(val)

        if not cols:
            return {"status": "error", "message": "No valid fields to update"}

        set_clause = ", ".join(f'"{c}" = ${i + 1}' for i, c in enumerate(cols))
        vals.append(int(record_id))

        async with pool.acquire() as conn:
            await conn.execute(
                f'UPDATE {tref} SET {set_clause} WHERE id = ${len(vals)}',
                *vals
            )
        return {"status": "success", "record_id": record_id}

# ── row delete ──────────────────────────────────────────────────

async def delete_row(table_name: str, record_id: str) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    pool = await ensure_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            f'UPDATE {await _ref(table_name)} SET deleted_at = $1 WHERE id = $2',
            now, int(record_id)
        )
    return {"status": "success", "record_id": record_id}


async def restore_row(table_name: str, record_id: str) -> dict:
    """Undo delete_row: clear deleted_at so the archived row is active again."""
    try:
        _check_ident(table_name, "table name")
        pool = await ensure_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                f'UPDATE {await _ref(table_name)} SET deleted_at = NULL '
                f'WHERE id = $1 AND deleted_at IS NOT NULL',
                int(record_id),
            )
        # asyncpg returns a command tag such as "UPDATE 1"
        if result.endswith(" 0"):
            return {"status": "error", "code": 404,
                    "message": f"No archived record {record_id} found in '{table_name}'"}
        return {"status": "success", "record_id": record_id}
    except Exception as e:
        return {"status": "error", "code": 400, "message": str(e)}


# ════════════════════════════════════════════════════════════════════════
# domain_attributes — one row per (domain, field), holds the English label
# ════════════════════════════════════════════════════════════════════════

_domain_attributes_table_ready = False   # module-level flag, checked once per process


async def _ensure_domain_attributes_table() -> None:
    global _domain_attributes_table_ready
    if _domain_attributes_table_ready:
        return
    await execute(
        """
        CREATE TABLE IF NOT EXISTS domain_attributes (
            id                  SERIAL PRIMARY KEY,
            dmo_name            VARCHAR NOT NULL,
            dmo_attribute_name  VARCHAR NOT NULL,
            label               VARCHAR,
            field_type          VARCHAR,
            created_at          VARCHAR,
            UNIQUE (dmo_name, dmo_attribute_name)
        )
        """
    )
    await execute(
        """
        CREATE INDEX IF NOT EXISTS idx_domain_attributes_dmo_name
        ON domain_attributes (dmo_name)
        """
    )
    print("[datastore] Meta-table 'domain_attributes' ready (PostgreSQL).")
    _domain_attributes_table_ready = True


async def set_attribute_field_types(domain_model_id: str, schema: list) -> None:
    """Record each schema field's type in domain_attributes.field_type (so a
    domain-model field is stored as "domain_model"). Only field_type is written —
    labels already saved for the attribute are left untouched."""
    await _ensure_domain_attributes_table()
    now = datetime.now(timezone.utc).isoformat()
    for f in schema:
        fid = f.get("field_id")
        if not fid:
            continue
        await execute(
            """
            INSERT INTO domain_attributes
                (dmo_name, dmo_attribute_name, label, field_type, created_at)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (dmo_name, dmo_attribute_name) DO UPDATE
                SET field_type = EXCLUDED.field_type
            """,
            domain_model_id, fid, f.get("label") or fid, f.get("type", "text"), now,
        )


async def save_domain_attribute(
    domain_model_id: str,
    attribute_name: str,
    label: str | None = None,
    field_type: str | None = None,
) -> dict:
    """
    Upserts the (domain, field) row with its English label.
    NOTE: this no longer writes a `translations` column — translations
    now live in the separate attribute_translations linked table
    (see save_attribute_translation / get_domain_translations below).
    The old `build_translations()` call was removed — it referenced an
    undefined function and was silently failing on every call.
    """
    try:
        await _ensure_domain_attributes_table()
        display_label = label or attribute_name
        now = datetime.now(timezone.utc).isoformat()

        await execute(
            """
            INSERT INTO domain_attributes
                (dmo_name, dmo_attribute_name, label, field_type, created_at)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (dmo_name, dmo_attribute_name) DO UPDATE
                SET label = EXCLUDED.label,
                    field_type = EXCLUDED.field_type
            """,
            domain_model_id, attribute_name, display_label, field_type, now,
        )
        print(f"[datastore] Attribute '{attribute_name}' saved for domain '{domain_model_id}'.")
        return {"status": "success"}
    except Exception as e:
        print(f"[datastore] WARNING: Could not save attribute: {e}")
        return {"status": "error", "message": str(e)}


async def list_domain_attributes(domain_model_id: str) -> list[dict]:
    try:
        await _ensure_domain_attributes_table()
        rows = await fetch(
            """
            SELECT dmo_attribute_name, label, field_type
            FROM domain_attributes
            WHERE dmo_name = $1
            ORDER BY created_at ASC
            """,
            domain_model_id,
        )
        return [
            {
                "attribute_name": r["dmo_attribute_name"],
                "label": r["label"],
                "field_type": r["field_type"],
            }
            for r in rows
        ]
    except Exception as e:
        print(f"[datastore] WARNING: Could not list attributes: {e}")
        return []


# ════════════════════════════════════════════════════════════════════════
# attribute_translations — LINKED TABLE (FK -> domain_attributes.id)
# One row per (attribute, language). Multilingual labels for forms.
# ════════════════════════════════════════════════════════════════════════

_attribute_translations_table_ready = False   # module-level flag, checked once per process


async def _ensure_attribute_translations_table() -> None:
    global _attribute_translations_table_ready
    if _attribute_translations_table_ready:
        return
    await execute(
        """
        CREATE TABLE IF NOT EXISTS attribute_translations (
            id            SERIAL PRIMARY KEY,
            attribute_id  INTEGER NOT NULL,
            lang_code     VARCHAR(5) NOT NULL,
            label         TEXT NOT NULL,
            created_at    VARCHAR,
            updated_at    VARCHAR,

            CONSTRAINT fk_attribute
                FOREIGN KEY (attribute_id)
                REFERENCES domain_attributes (id)
                ON DELETE CASCADE,

            UNIQUE (attribute_id, lang_code)
        )
        """
    )
    await execute(
        """
        CREATE INDEX IF NOT EXISTS idx_attribute_translations_attribute_id
        ON attribute_translations (attribute_id)
        """
    )
    print("[datastore] Linked table 'attribute_translations' ready (PostgreSQL).")
    _attribute_translations_table_ready = True


async def _get_attribute_id(domain_model_id: str, attribute_name: str) -> int | None:
    """
    Looks up domain_attributes.id for a given (dmo_name, dmo_attribute_name)
    pair. Returns None if the attribute doesn't exist yet — caller should
    save the attribute first via save_domain_attribute() before saving
    its translations.
    """
    await _ensure_domain_attributes_table()
    row = await fetchrow(
        """
        SELECT id FROM domain_attributes
        WHERE dmo_name = $1 AND dmo_attribute_name = $2
        """,
        domain_model_id, attribute_name,
    )
    return row["id"] if row else None


async def save_attribute_translation(
    domain_model_id: str,
    attribute_name: str,
    lang_code: str,
    label: str,
) -> dict:
    """
    Upserts ONE row — one language's label for one attribute.
    Resolves attribute_name -> attribute_id first (FK lookup), then
    upserts into attribute_translations keyed on (attribute_id, lang_code).
    """
    try:
        await _ensure_attribute_translations_table()

        attribute_id = await _get_attribute_id(domain_model_id, attribute_name)
        if attribute_id is None:
            return {
                "status": "error",
                "message": (
                    f"Attribute '{attribute_name}' not found in domain "
                    f"'{domain_model_id}'. Save the attribute itself first "
                    f"(POST /domain-attributes) before saving translations."
                ),
            }

        now = datetime.now(timezone.utc).isoformat()

        await execute(
            """
            INSERT INTO attribute_translations
                (attribute_id, lang_code, label, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $4)
            ON CONFLICT (attribute_id, lang_code) DO UPDATE
                SET label = EXCLUDED.label,
                    updated_at = EXCLUDED.updated_at
            """,
            attribute_id, lang_code, label, now,
        )
        print(f"[datastore] Translation '{lang_code}' saved for '{domain_model_id}.{attribute_name}' (attribute_id={attribute_id}).")
        return {
            "status": "success",
            "domain_model_id": domain_model_id,
            "attribute_name": attribute_name,
            "attribute_id": attribute_id,
            "lang_code": lang_code,
            "label": label,
        }
    except Exception as e:
        print(f"[datastore] WARNING: Could not save translation: {e}")
        return {"status": "error", "message": str(e)}


async def get_domain_translations(domain_model_id: str) -> dict:
    """
    Returns translations grouped by attribute_name, ready for the
    frontend FormPlugin's resolveLabel() to consume directly:

        {
          "clinic_name": { "en": "Clinic Name", "ta": "...", "ar": "..." },
          "ph_no":       { "en": "Phone Number", "ta": "...", "ar": "..." }
        }

    Joins domain_attributes -> attribute_translations via attribute_id.
    """
    try:
        await _ensure_attribute_translations_table()
        rows = await fetch(
            """
            SELECT da.dmo_attribute_name AS attribute_name,
                   at.lang_code,
                   at.label
            FROM domain_attributes da
            JOIN attribute_translations at ON at.attribute_id = da.id
            WHERE da.dmo_name = $1
            ORDER BY da.dmo_attribute_name, at.lang_code
            """,
            domain_model_id,
        )
        grouped: dict = {}
        for r in rows:
            attr = r["attribute_name"]
            grouped.setdefault(attr, {})[r["lang_code"]] = r["label"]
        return grouped
    except Exception as e:
        print(f"[datastore] WARNING: Could not load translations: {e}")
        return {}

# ════════════════════════════════════════════════════════════════════════
# validation_rules — named, reusable validation rule registry
# Backs the "Create new rule" flow in the Schema Inspector's field builder
# (Validations tab / Registry Rules picker). Supports both authoring
# shapes the frontend already knows about, side by side on the same row:
#   - legacy flat shape:  { type, value, message }
#   - new kind-based shape: { kind, expression, min, max, validations }
# A row uses one or the other — never both — same as the frontend's
# NamedValidationRule type (see src/core/schema/types.ts).
# ════════════════════════════════════════════════════════════════════════

_validation_rules_table_ready = False   # module-level flag, checked once per process


async def _ensure_validation_rules_table() -> None:
    global _validation_rules_table_ready
    if _validation_rules_table_ready:
        return
    await execute(
        """
        CREATE TABLE IF NOT EXISTS validation_rules (
            tag             VARCHAR PRIMARY KEY,
            version         VARCHAR,
            description     TEXT,
            category        VARCHAR NOT NULL DEFAULT 'common',

            kind            VARCHAR,
            expression      TEXT,
            min_value       NUMERIC,
            max_value       NUMERIC,
            validations     TEXT,

            legacy_type     VARCHAR,
            legacy_value    TEXT,
            legacy_message  TEXT,

            created_at      VARCHAR,
            updated_at      VARCHAR
        )
        """
    )
    await execute(
        """
        CREATE INDEX IF NOT EXISTS idx_validation_rules_category
        ON validation_rules (category)
        """
    )
    print("[datastore] Meta-table 'validation_rules' ready (PostgreSQL).")
    _validation_rules_table_ready = True


def _validation_rule_row_to_wire(r: dict) -> dict:
    """
    DB row -> exactly the JSON shape the frontend's NamedValidationRule
    expects — drops whichever shape's columns are unused (kind-based vs
    legacy) instead of returning nulls for every column on every rule.
    """
    out: dict = {
        "tag":         r["tag"],
        "version":     r["version"],
        "description": r["description"],
        "category":    r["category"],
    }
    if r["kind"]:
        out["kind"] = r["kind"]
        if r["expression"] is not None:
            out["expression"] = r["expression"]
        if r["min_value"] is not None:
            out["min"] = float(r["min_value"])
        if r["max_value"] is not None:
            out["max"] = float(r["max_value"])
        if r["validations"] is not None:
            out["validations"] = json.loads(r["validations"])
    if r["legacy_type"]:
        out["type"] = r["legacy_type"]
        if r["legacy_value"] is not None:
            out["value"] = json.loads(r["legacy_value"])
        if r["legacy_message"] is not None:
            out["message"] = r["legacy_message"]
    return out


async def list_validation_rules() -> list[dict]:
    try:
        await _ensure_validation_rules_table()
        rows = await fetch(
            "SELECT * FROM validation_rules ORDER BY category, tag"
        )
        return [_validation_rule_row_to_wire(dict(r)) for r in rows]
    except Exception as e:
        print(f"[datastore] WARNING: Could not list validation rules: {e}")
        return []
async def delete_validation_rule(tag: str) -> dict:
    """
    Deletes one validation rule by tag. Safe to call on a tag that's
    already gone or never existed — returns success either way, since
    the end state (row absent) is what the caller actually wants.
    """
    try:
        await _ensure_validation_rules_table()
        await execute("DELETE FROM validation_rules WHERE tag = $1", tag)
        print(f"[datastore] Validation rule '{tag}' deleted.")
        return {"status": "success", "tag": tag}
    except Exception as e:
        print(f"[datastore] WARNING: Could not delete validation rule '{tag}': {e}")
        return {"status": "error", "message": str(e)}

async def save_validation_rule(tag: str, rule: dict) -> dict:
    """
    Upserts one validation rule, keyed by tag. `rule` is the raw dict sent
    by the frontend (see apiSaveValidationRule in datastoreApi.ts) — may
    contain either the kind-based fields or the legacy flat fields, never
    both.
    """
    try:
        await _ensure_validation_rules_table()
        now = datetime.now(timezone.utc)

        validations = rule.get("validations")
        value = rule.get("value")

        await execute(
            """
            INSERT INTO validation_rules (
                tag, version, description, category,
                kind, expression, min_value, max_value, validations,
                legacy_type, legacy_value, legacy_message,
                created_at, updated_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $13)
            ON CONFLICT (tag) DO UPDATE
                SET version        = EXCLUDED.version,
                    description    = EXCLUDED.description,
                    category       = EXCLUDED.category,
                    kind           = EXCLUDED.kind,
                    expression     = EXCLUDED.expression,
                    min_value      = EXCLUDED.min_value,
                    max_value      = EXCLUDED.max_value,
                    validations    = EXCLUDED.validations,
                    legacy_type    = EXCLUDED.legacy_type,
                    legacy_value   = EXCLUDED.legacy_value,
                    legacy_message = EXCLUDED.legacy_message,
                    updated_at     = EXCLUDED.updated_at
            """,
            tag,
            rule.get("version"),
            rule.get("description"),
            rule.get("category") or "common",
            rule.get("kind"),
            rule.get("expression"),
            rule.get("min"),
            rule.get("max"),
            json.dumps(validations) if validations is not None else None,
            rule.get("type"),
            json.dumps(value) if value is not None else None,
            rule.get("message"),
            now,
        )
        print(f"[datastore] Validation rule '{tag}' saved.")
        return {"status": "success"}
    except Exception as e:
        print(f"[datastore] WARNING: Could not save validation rule '{tag}': {e}")
        return {"status": "error", "message": str(e)}

# ════════════════════════════════════════════════════════════════════════
# Domain model management — rename / delete a domain, rename / retype /
# delete a field. Schema JSON in datastore_schemas stays the source of
# truth for the UI; the physical table/columns are changed to match.
# ════════════════════════════════════════════════════════════════════════

import re as _re

_IDENT_RE = _re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_PROTECTED_COLS = {"id", "created_at", "deleted_at"}


def _check_ident(name: str, what: str) -> str:
    if not name or not _IDENT_RE.match(name):
        raise ValueError(f"Invalid {what} '{name}' — use letters, digits and underscores only.")
    return name


async def delete_domain(table_name: str, drop_table: bool = True) -> dict:
    """Remove a domain model: its schema row, its attribute rows (translations
    cascade from them), its relationships, and (by default) the physical table
    with all its data. Everything runs in ONE transaction, so a failure part-way
    leaves nothing half-deleted."""
    try:
        _check_ident(table_name, "table name")
        await _ensure_datastore_schemas_table()
        await _ensure_domain_attributes_table()
        await _ensure_attribute_translations_table()   # translations cascade from attributes
        meta = await _meta_of(table_name)
        existing = await fetchrow(
            "SELECT pg_schema, COALESCE(domain_name, table_name) AS physical "
            f"FROM {meta} WHERE table_name = $1", table_name
        )
        if not existing:
            return {"status": "error", "code": 404, "message": f"Domain '{table_name}' not found"}
        tref = _qualify(existing["pg_schema"], existing["physical"])   # before the row is deleted

        # Check for the optional relationships table OUTSIDE the transaction.
        # A fetchval/fetchrow inside it leaves a suspended portal open, and
        # CockroachDB then rejects the next statement ("multiple active portals").
        _rel = await fetchrow("SELECT to_regclass('domain_relationships') AS t")
        has_relationships = bool(_rel and _rel["t"])

        pool = await ensure_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                # Attributes first (attribute_translations ON DELETE CASCADE).
                attrs = await conn.execute(
                    "DELETE FROM domain_attributes WHERE dmo_name = $1", table_name
                )
                if has_relationships:
                    await conn.execute(
                        "DELETE FROM domain_relationships WHERE from_dmo = $1 OR to_dmo = $1",
                        table_name,
                    )
                await conn.execute(f"DELETE FROM {meta} WHERE table_name = $1", table_name)
                await conn.execute("DELETE FROM datastore_registry WHERE table_name = $1", table_name)
                if drop_table:
                    await conn.execute(f'DROP TABLE IF EXISTS {tref}')
        print(f"[datastore] Domain '{table_name}' deleted with its attributes "
              f"({attrs}); drop_table={drop_table}.")
        return {"status": "success", "table_name": table_name, "table_dropped": drop_table}
    except Exception as e:
        return {"status": "error", "code": 400, "message": str(e)}


async def purge_orphan_attributes() -> dict:
    """One-off cleanup: delete domain_attributes (and their translations) whose
    domain no longer exists in datastore_schemas, plus dangling relationships.
    Safe to call any time (e.g. from an admin route)."""
    await _ensure_registry()
    await _ensure_domain_attributes_table()
    await _ensure_attribute_translations_table()
    attrs = await execute(
        "DELETE FROM domain_attributes WHERE dmo_name NOT IN (SELECT table_name FROM datastore_registry)"
    )
    rels = "DELETE 0"
    _rel = await fetchrow("SELECT to_regclass('domain_relationships') AS t")
    if _rel and _rel["t"]:
        rels = await execute(
            "DELETE FROM domain_relationships "
            "WHERE from_dmo NOT IN (SELECT table_name FROM datastore_registry) "
            "OR to_dmo NOT IN (SELECT table_name FROM datastore_registry)"
        )
    return {"status": "success", "attributes_removed": attrs, "relationships_removed": rels}


async def rename_domain(
    old_name: str,
    new_name: str | None,
    project_id: int | str | None = None,
    module_id: int | str | None = None,
    move_scope: bool = False,
    label: str | None = None,
    update_label: bool = False,
) -> dict:
    """Rename a domain model (visible name + physical table) and/or move it to
    another project/module (move_scope=True; None clears) and/or change its
    business label (update_label=True; empty/None clears).

    old_name is the model's internal key. new_name=None means "don't rename".
    Names are unique per project (case-insensitive). The key itself only changes
    when the new name is free as a key (the old behaviour for models whose key
    equals their name); otherwise it stays and only domain_name changes."""
    try:
        _check_ident(old_name, "table name")
        if new_name:
            _check_ident(new_name, "new table name")
        meta = await _meta_of(old_name)
        cur = await fetchrow(
            "SELECT pg_schema, project_id, COALESCE(domain_name, table_name) AS dn "
            f"FROM {meta} WHERE table_name = $1", old_name)
        if not cur:
            return {"status": "error", "code": 404, "message": f"Domain '{old_name}' not found"}
        cur_schema = cur["pg_schema"] or "public"
        visible = cur["dn"]
        key = old_name

        new_project = (int(project_id) if project_id not in (None, "") else None) if move_scope else cur["project_id"]
        renaming = bool(new_name) and new_name != visible
        if renaming or move_scope:
            target_name = new_name if renaming else visible
            clashes = await _fetch_all_meta(
                "SELECT COALESCE(domain_name, table_name) AS dn FROM {t} "
                "WHERE table_name <> $1 AND lower(COALESCE(domain_name, table_name)) = lower($2) "
                "AND project_id IS NOT DISTINCT FROM $3::int",
                old_name, target_name, new_project)
            clash = clashes[0] if clashes else None
            if clash:
                return {"status": "error", "code": 409,
                        "message": f"A domain model named '{clash['dn']}' already exists in this project. Choose a different name."}

        if renaming:
            await execute(f'ALTER TABLE IF EXISTS {_qualify(cur_schema, visible)} RENAME TO "{new_name}"')
            await execute(f"UPDATE {meta} SET domain_name = $1 WHERE table_name = $2", new_name, key)
            visible = new_name
            # keep the key in step with the name when that key is free (legacy behaviour)
            if new_name != key and not await fetchrow(
                    "SELECT 1 FROM datastore_registry WHERE table_name = $1", new_name):
                await execute(f"UPDATE {meta} SET table_name = $1 WHERE table_name = $2", new_name, key)
                await execute("UPDATE datastore_registry SET table_name = $1 WHERE table_name = $2", new_name, key)
                await _ensure_domain_attributes_table()
                await execute("UPDATE domain_attributes SET dmo_name = $1 WHERE dmo_name = $2", new_name, key)
                _rel = await fetchrow("SELECT to_regclass('domain_relationships') AS t")
                if _rel and _rel["t"]:
                    await execute("UPDATE domain_relationships SET from_dmo = $1 WHERE from_dmo = $2", new_name, key)
                    await execute("UPDATE domain_relationships SET to_dmo = $1 WHERE to_dmo = $2", new_name, key)
                key = new_name

        if move_scope:
            # Moving to another project moves the physical table to that
            # project's schema (or back to "public" when detached).
            target = await ensure_project_schema(project_id)
            if target != cur_schema:
                await execute(f'ALTER TABLE IF EXISTS {_qualify(cur_schema, visible)} SET SCHEMA "{target}"')
            # The model's datastore_schemas row follows it into the new project's own
            # datastore_schemas table (this also adopts rows still in the legacy public table).
            await move_meta_row(key, target)
            meta = await _meta_of(key)
            await execute(f"UPDATE {meta} SET pg_schema = $1 WHERE table_name = $2", target, key)
            await execute(
                f"UPDATE {meta} SET project_id = $1, module_id = $2 WHERE table_name = $3",
                new_project,
                int(module_id) if module_id not in (None, "") else None,
                key,
            )
            await execute(
                "UPDATE datastore_registry SET pg_schema = $1, project_id = $2 WHERE table_name = $3",
                target, new_project, key)
        if update_label:
            clean = label.strip() if isinstance(label, str) else ""
            await execute(
                f"UPDATE {meta} SET label = $1 WHERE table_name = $2",
                clean or None, key,
            )
        return {"status": "success", "table_name": key, "domain_name": visible, "old_name": old_name}
    except Exception as e:
        return {"status": "error", "code": 400, "message": str(e)}


async def delete_field(table_name: str, field_id: str) -> dict:
    """Remove one attribute: from the schema JSON, the table column, and
    the attribute/translation rows."""
    try:
        _check_ident(table_name, "table name")
        _check_ident(field_id, "field id")
        if field_id in _PROTECTED_COLS:
            return {"status": "error", "code": 400, "message": f"'{field_id}' is a system column and can't be deleted"}
        current = await get_schema(table_name)
        if not current:
            return {"status": "error", "code": 404, "message": f"Domain '{table_name}' not found"}
        schema = current["schema"]
        new_schema = [f for f in schema if f.get("field_id") != field_id]
        if len(new_schema) == len(schema):
            return {"status": "error", "code": 404, "message": f"Field '{field_id}' not found in '{table_name}'"}

        await execute(f'ALTER TABLE IF EXISTS {await _ref(table_name)} DROP COLUMN IF EXISTS "{field_id}"')
        await execute(
            f"UPDATE {await _meta_of(table_name)} SET schema = $1 WHERE table_name = $2",
            json.dumps(new_schema), table_name,
        )
        await _ensure_domain_attributes_table()
        await _ensure_attribute_translations_table()
        await execute(
            "DELETE FROM domain_attributes WHERE dmo_name = $1 AND dmo_attribute_name = $2",
            table_name, field_id,
        )
        return {"status": "success", "table_name": table_name, "field_id": field_id}
    except Exception as e:
        return {"status": "error", "code": 400, "message": str(e)}


async def update_field(
    table_name: str,
    field_id: str,
    new_field_id: str | None = None,
    new_type: str | None = None,
    new_label: str | None = None,
) -> dict:
    """Rename and/or retype one attribute — the column is altered to match
    and the schema JSON entry updated. Other schema keys (ui_config, rbac,
    validations…) are left as-is; the caller follows up with a normal
    save (POST /datastore/create) to write the full edited definition."""
    try:
        _check_ident(table_name, "table name")
        _check_ident(field_id, "field id")
        target = new_field_id or field_id
        _check_ident(target, "new field id")
        if field_id in _PROTECTED_COLS or target in _PROTECTED_COLS:
            return {"status": "error", "code": 400, "message": "System columns can't be edited"}

        current = await get_schema(table_name)
        if not current:
            return {"status": "error", "code": 404, "message": f"Domain '{table_name}' not found"}
        schema = current["schema"]
        entry = next((f for f in schema if f.get("field_id") == field_id), None)
        if entry is None:
            return {"status": "error", "code": 404, "message": f"Field '{field_id}' not found in '{table_name}'"}
        if target != field_id and any(f.get("field_id") == target for f in schema):
            return {"status": "error", "code": 409, "message": f"Field '{target}' already exists in '{table_name}'"}

        if target != field_id:
            await execute(f'ALTER TABLE IF EXISTS {await _ref(table_name)} RENAME COLUMN "{field_id}" TO "{target}"')
            entry["field_id"] = target
        if new_type and new_type != entry.get("type"):
            pg_type = _PG_TYPE.get(new_type)
            if not pg_type:
                return {"status": "error", "code": 400, "message": f"Unsupported type '{new_type}'"}
            await execute(
                f'ALTER TABLE IF EXISTS {await _ref(table_name)} ALTER COLUMN "{target}" TYPE {pg_type} '
                f'USING "{target}"::{pg_type}'
            )
            entry["type"] = new_type
        if new_label is not None:
            entry["label"] = new_label

        await execute(
            f"UPDATE {await _meta_of(table_name)} SET schema = $1 WHERE table_name = $2",
            json.dumps(schema), table_name,
        )
        if target != field_id:
            await _ensure_domain_attributes_table()
            await _ensure_attribute_translations_table()
            # The UI saves the attribute under its NEW name before calling
            # this, so a row for `target` usually exists already (with the
            # latest labels). Keep that one and drop the stale old row;
            # only rename when there is no row for the new name yet.
            if await fetchrow(
                "SELECT 1 FROM domain_attributes WHERE dmo_name = $1 AND dmo_attribute_name = $2",
                table_name, target,
            ):
                await execute(
                    "DELETE FROM domain_attributes WHERE dmo_name = $1 AND dmo_attribute_name = $2",
                    table_name, field_id,
                )
            else:
                await execute(
                    "UPDATE domain_attributes SET dmo_attribute_name = $1 "
                    "WHERE dmo_name = $2 AND dmo_attribute_name = $3",
                    target, table_name, field_id,
                )
        return {"status": "success", "table_name": table_name, "field_id": target, "old_field_id": field_id}
    except Exception as e:
        return {"status": "error", "code": 400, "message": str(e)}