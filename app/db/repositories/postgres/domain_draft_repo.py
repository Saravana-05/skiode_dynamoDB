"""
PostgreSQL implementation of the domain-model DRAFT repo.

A draft is a saved-but-not-yet-submitted domain model. It lives entirely
in the `domain_model_drafts` meta-table:

  - Saving a draft writes ONE row here and does nothing else. No
    CREATE TABLE, no row in datastore_schemas, no physical columns.
  - Submitting a draft replays the backend create-requests stored on it
    (main domain + any related / junction domains) through the normal
    datastore path — create_table_from_schema + save_schema — and only
    then does the domain model exist as real tables.

Because drafts are kept out of datastore_schemas entirely, every
existing read path (GET /datastore/schemas, insert_row, the frontend's
handleLoadFromBackend, etc.) keeps seeing only submitted domain models.
Nothing downstream needs to learn about drafts to stay correct.

Draft payload shape (stored as JSON TEXT in `payload`):

    {
      "domain_name": "Patient",
      "db_backend":  "postgresql",
      "versioned":   false,
      "fields":      { ...FieldDraft map — lets the UI resume editing... },
      "payload":     { ...CreateDomainPayload — replayed client-side
                        after submit so UI hints / RBAC / ABAC /
                        translations land exactly as they would have... },
      "tables":      [ { "table_name": "...", "schema": [...],
                         "db_backend": "...", "versioned": false }, ... ]
    }

Only `tables` is interpreted by this module (on submit). Everything else
is opaque round-tripped state owned by the frontend.

Drafts are registry/config data, always PostgreSQL — same treatment as
validation_rules and attribute_translations (no DynamoDB equivalent).
"""
import json
from datetime import datetime, timezone

from ....core.database import execute, fetch, fetchrow


_drafts_table_ready = False   # module-level flag, checked once per process


async def _ensure_drafts_table() -> None:
    global _drafts_table_ready
    if _drafts_table_ready:
        return
    await execute(
        """
        CREATE TABLE IF NOT EXISTS domain_model_drafts (
            id           SERIAL PRIMARY KEY,
            domain_name  VARCHAR NOT NULL,
            project_id   INTEGER,
            status       VARCHAR NOT NULL DEFAULT 'draft',
            payload      TEXT    NOT NULL,
            created_by   VARCHAR,
            created_at   VARCHAR,
            updated_at   VARCHAR,
            submitted_at VARCHAR
        )
        """
    )
    # One live draft per (domain, project). project_id is nullable, and
    # NULLs don't compare equal in a plain unique index, so COALESCE it
    # to -1 — otherwise "no project (global)" drafts would silently
    # duplicate on every save instead of updating in place.
    await execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_domain_model_drafts_name
        ON domain_model_drafts (domain_name, COALESCE(project_id, -1))
        """
    )
    await execute(
        "CREATE INDEX IF NOT EXISTS idx_domain_model_drafts_status "
        "ON domain_model_drafts (status)"
    )
    print("[datastore] Meta-table 'domain_model_drafts' ready (PostgreSQL).")
    _drafts_table_ready = True


def _row_to_wire(row) -> dict:
    try:
        payload = json.loads(row["payload"]) if row["payload"] else {}
    except (ValueError, TypeError):
        payload = {}
    return {
        "id":           str(row["id"]),
        "domain_name":  row["domain_name"],
        "project_id":   str(row["project_id"]) if row["project_id"] is not None else None,
        "status":       row["status"],
        "payload":      payload,
        "created_by":   row["created_by"],
        "created_at":   row["created_at"],
        "updated_at":   row["updated_at"],
        "submitted_at": row["submitted_at"],
    }


# ── save (upsert, keyed by domain + project) ──────────────────────

async def save_draft(
    domain_name: str,
    payload: dict,
    project_id: int | str | None = None,
    created_by: str | None = None,
) -> dict:
    """
    Create or update a draft. Deliberately does NOT touch
    datastore_schemas and never issues DDL — that's what makes it a
    draft. Re-saving an already-submitted domain reopens it as a draft
    again (status flips back), so editing a live domain model still
    goes through the same submit gate.
    """
    await _ensure_drafts_table()
    now = datetime.now(timezone.utc).isoformat()
    pid = int(project_id) if project_id not in (None, "") else None

    existing = await fetchrow(
        "SELECT id FROM domain_model_drafts "
        "WHERE domain_name = $1 AND COALESCE(project_id, -1) = COALESCE($2::INTEGER, -1)",
        domain_name, pid,
    )

    if existing:
        await execute(
            """
            UPDATE domain_model_drafts
               SET payload      = $1,
                   status       = 'draft',
                   updated_at   = $2,
                   submitted_at = NULL
             WHERE id = $3
            """,
            json.dumps(payload), now, existing["id"],
        )
        draft_id = existing["id"]
    else:
        draft_id = await _insert(domain_name, pid, payload, created_by, now)

    return {
        "status":   "success",
        "draft_id": str(draft_id),
        "action":   "updated" if existing else "created",
        "message":  (
            f"Draft for '{domain_name}' saved. No tables were created — "
            f"submit the draft to generate the domain model tables."
        ),
    }


async def _insert(domain_name, pid, payload, created_by, now) -> int:
    row = await fetchrow(
        """
        INSERT INTO domain_model_drafts
            (domain_name, project_id, status, payload, created_by, created_at, updated_at)
        VALUES ($1, $2, 'draft', $3, $4, $5, $5)
        RETURNING id
        """,
        domain_name, pid, json.dumps(payload), created_by, now,
    )
    return row["id"]


# ── read ──────────────────────────────────────────────────────────

async def list_drafts(
    project_id: int | str | None = None,
    status: str | None = "draft",
) -> list[dict]:
    await _ensure_drafts_table()

    clauses, args = [], []
    if project_id not in (None, ""):
        args.append(int(project_id))
        clauses.append(f"project_id = ${len(args)}")
    if status:
        args.append(status)
        clauses.append(f"status = ${len(args)}")

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = await fetch(
        f"SELECT * FROM domain_model_drafts {where} ORDER BY updated_at DESC",
        *args,
    )
    return [_row_to_wire(r) for r in rows]


async def get_draft(draft_id: int | str) -> dict | None:
    await _ensure_drafts_table()
    row = await fetchrow("SELECT * FROM domain_model_drafts WHERE id = $1", int(draft_id))
    return _row_to_wire(row) if row else None


async def delete_draft(draft_id: int | str) -> dict:
    await _ensure_drafts_table()
    row = await fetchrow(
        "DELETE FROM domain_model_drafts WHERE id = $1 RETURNING id", int(draft_id)
    )
    if not row:
        return {"status": "error", "message": f"Draft {draft_id} not found"}
    return {"status": "success", "draft_id": str(draft_id)}


# ── submit — the ONLY place a draft turns into real tables ────────

async def submit_draft(draft_id: int | str) -> dict:
    """
    Replay every create-request stored on the draft through the normal
    datastore path, then mark the draft submitted.

    Tables are created in exactly the order the draft recorded them
    (main domain → any related domains → junction tables), matching the
    sequence the non-draft path already uses. FK columns are plain
    columns with no database-level constraint, so no table here depends
    on another existing first.

    If any table fails, the draft is left in 'draft' status so it can be
    fixed and resubmitted — a half-applied submit never silently counts
    as done.
    """
    await _ensure_drafts_table()

    draft = await get_draft(draft_id)
    if not draft:
        return {"status": "error", "message": f"Draft {draft_id} not found"}
    if draft["status"] == "submitted":
        return {"status": "error", "message": f"Draft {draft_id} was already submitted"}

    tables = (draft.get("payload") or {}).get("tables") or []
    if not tables:
        return {"status": "error", "message": "Draft has no tables to create"}

    # Imported lazily and through the facade so the active backend
    # (postgresql / dynamodb) switch still applies to submitted tables,
    # exactly as it does for a direct POST /datastore/create.
    from ..datastore_repo import create_table_from_schema, save_schema

    project_id = draft.get("project_id")
    results: list[dict] = []

    for spec in tables:
        table_name = spec.get("table_name")
        schema     = spec.get("schema") or []
        if not table_name:
            continue
        try:
            created = await create_table_from_schema(table_name, schema)
            await save_schema(table_name, schema, spec.get("project_id", project_id))
            results.append({
                "table_name": table_name,
                "created":    bool(created.get("created")),
                "status":     "success",
            })
        except Exception as exc:   # noqa: BLE001 — surfaced to the caller below
            results.append({
                "table_name": table_name,
                "status":     "error",
                "message":    str(exc),
            })

    failed = [r for r in results if r["status"] == "error"]
    if failed:
        return {
            "status":   "error",
            "draft_id": str(draft_id),
            "message":  f"{len(failed)} of {len(results)} table(s) failed — draft left open for retry",
            "results":  results,
        }

    now = datetime.now(timezone.utc).isoformat()
    await execute(
        "UPDATE domain_model_drafts SET status = 'submitted', submitted_at = $1, updated_at = $1 "
        "WHERE id = $2",
        now, int(draft_id),
    )

    return {
        "status":       "success",
        "draft_id":     str(draft_id),
        "domain_name":  draft["domain_name"],
        "submitted_at": now,
        "results":      results,
        "message":      f"Draft submitted — {len(results)} table(s) generated.",
    }


__all__ = [
    "save_draft",
    "list_drafts",
    "get_draft",
    "delete_draft",
    "submit_draft",
]