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
    print("[datastore] Meta-table 'datastore_schemas' ready (PostgreSQL).")
    _schemas_table_ready = True


# ── schema meta-table helpers ────────────────────────────────────

async def save_schema(table_name: str, schema: list, project_id: int | str | None = None) -> None:
    await _ensure_datastore_schemas_table()
    now = datetime.now(timezone.utc).isoformat()
    # Note: project_id is only ever SET on INSERT or when a value is
    # explicitly passed in — a plain re-save (e.g. adding a field to an
    # existing domain model, project_id=None) must not silently detach
    # the domain model from the project it already belongs to.
    await execute(
        """
        INSERT INTO datastore_schemas (table_name, schema, created_at, project_id)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (table_name) DO UPDATE
            SET schema = EXCLUDED.schema,
                created_at = EXCLUDED.created_at,
                project_id = COALESCE(EXCLUDED.project_id, datastore_schemas.project_id)
        """,
        table_name, json.dumps(schema), now,
        int(project_id) if project_id is not None else None,
    )


async def get_schema(table_name: str) -> dict | None:
    await _ensure_datastore_schemas_table()
    row = await fetchrow(
        "SELECT schema, project_id FROM datastore_schemas WHERE table_name = $1", table_name
    )
    if not row:
        return None
    return {
        "schema":     json.loads(row["schema"]),
        "db_backend": "postgresql",
        "project_id": str(row["project_id"]) if row["project_id"] is not None else None,
    }


async def list_schemas(project_id: int | str | None = None) -> list[dict]:
    await _ensure_datastore_schemas_table()
    if project_id is not None:
        rows = await fetch(
            "SELECT table_name, schema, created_at, project_id FROM datastore_schemas "
            "WHERE project_id = $1 ORDER BY created_at DESC",
            int(project_id),
        )
    else:
        rows = await fetch(
            "SELECT table_name, schema, created_at, project_id FROM datastore_schemas "
            "ORDER BY created_at DESC"
        )
    return [
        {
            "table_name": r["table_name"],
            "schema":     json.loads(r["schema"]),
            "created_at": str(r["created_at"]) if r["created_at"] else None,
            "db_backend": "postgresql",
            "project_id": str(r["project_id"]) if r["project_id"] is not None else None,
        }
        for r in rows
    ]


# ── dynamic table creation ──────────────────────────────────────

async def create_table_from_schema(table_name: str, schema: list) -> dict:
    pool = await ensure_pool()
    async with pool.acquire() as conn:

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
            col_defs = ["id SERIAL PRIMARY KEY", "created_at VARCHAR", "deleted_at VARCHAR"]

            for field in schema:
                col_name = field["field_id"]
                pg_type  = _PG_TYPE.get(field.get("type", "text"), "VARCHAR")
                col_defs.append(f'"{col_name}" {pg_type}')

            ddl = f'CREATE TABLE "{table_name}" ({", ".join(col_defs)})'
            await conn.execute(ddl)

            await conn.execute(
                f'CREATE INDEX IF NOT EXISTS "idx_{table_name}_created_at" '
                f'ON "{table_name}"(created_at)'
            )

            print(f"[datastore] Table '{table_name}' created in PostgreSQL.")
            return {"created": True, "table_name": table_name}

        else:
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

            # ── Backfill baseline columns ────────────────────────────
            # Older tables (or ones created before `deleted_at` became
            # part of the baseline) can be missing these. Every table
            # is expected to have them by list_rows / delete_row /
            # list_archived_rows, so guarantee they exist on every
            # POST /datastore/create call, not just at initial creation.
            for base_col, base_type in (("created_at", "VARCHAR"), ("deleted_at", "VARCHAR")):
                if base_col not in existing_cols:
                    await conn.execute(
                        f'ALTER TABLE "{table_name}" ADD COLUMN IF NOT EXISTS "{base_col}" {base_type}'
                    )
                    added.append(base_col)
                    print(f"[datastore] Backfilled baseline column '{base_col}' on '{table_name}'.")

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
            f'INSERT INTO "{table_name}" ({col_str}) VALUES ({placeholders}) RETURNING id',
            *vals
        )
    return str(record_id)


# ── row queries ─────────────────────────────────────────────────

async def list_rows(table_name: str, include_deleted: bool = False) -> list[dict]:
    if include_deleted:
        rows = await fetch(f'SELECT * FROM "{table_name}" ORDER BY created_at DESC')
    else:
        rows = await fetch(f'SELECT * FROM "{table_name}" WHERE deleted_at IS NULL ORDER BY created_at DESC')
    return [_stringify_id(dict(r)) for r in rows]

async def list_archived_rows(table_name: str) -> list[dict]:
    rows = await fetch(
        f'SELECT * FROM "{table_name}" WHERE deleted_at IS NOT NULL ORDER BY deleted_at DESC'
    )
    return [_stringify_id(dict(r)) for r in rows]

async def get_row(table_name: str, record_id: str) -> dict | None:
    row = await fetchrow(f'SELECT * FROM "{table_name}" WHERE id = $1', int(record_id))
    return _stringify_id(dict(row)) if row else None


# ── row update ──────────────────────────────────────────────────

async def update_row(table_name: str, record_id: str, row_data: dict) -> dict:
    if not row_data:
        return {"status": "error", "message": "No data provided"}

    schema_row = await fetchrow(
        "SELECT schema FROM datastore_schemas WHERE table_name = $1", table_name
    )
    schema = json.loads(schema_row["schema"]) if schema_row else []

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
                WHERE n.nspname = 'public' AND c.relname = $1
                AND a.attnum > 0 AND NOT a.attisdropped
                """,
                table_name,
            )
        }

        is_versioned = "versionOf" in existing_cols or "versionof" in existing_cols

        if is_versioned:
            now = datetime.now(timezone.utc).isoformat()

            # 1. Mark old row inactive
            await conn.execute(
                f'UPDATE "{table_name}" SET "toDate" = $1, "isActive" = $2 WHERE id = $3',
                now, False, int(record_id)
            )

            # 2. Get old row data to copy into new row
            old_row = await conn.fetchrow(
                f'SELECT * FROM "{table_name}" WHERE id = $1', int(record_id)
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
                f'INSERT INTO "{table_name}" ({col_str}) VALUES ({placeholders}) RETURNING id',
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
                f'UPDATE "{table_name}" SET {set_clause} WHERE id = ${len(vals)}',
                *vals
            )
        return {"status": "success", "record_id": record_id}

# ── row delete ──────────────────────────────────────────────────

async def delete_row(table_name: str, record_id: str) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    pool = await ensure_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            f'UPDATE "{table_name}" SET deleted_at = $1 WHERE id = $2',
            now, int(record_id)
        )
    return {"status": "success", "record_id": record_id}


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