"""
PostgreSQL implementation of form_data (event_log) repo.
fields column stored as TEXT (JSON string) — same shape as DynamoDB version.
"""
import json
import uuid
from datetime import datetime, timezone
from ....core.database import execute, fetch, fetchrow


def _load(row) -> dict:
    if not row:
        return None
    d = dict(row)
    if isinstance(d.get("fields"), str):
        d["fields"] = json.loads(d["fields"])
    return d


# ── Write ──────────────────────────────────────────────────────

async def save(name: str, fields: list) -> str:
    record_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    await execute(
        """
        INSERT INTO event_log (id, name, fields, created_at)
        VALUES ($1, $2, $3, $4)
        """,
        record_id, name, json.dumps(fields, ensure_ascii=False), now,
    )
    return record_id


# ── Read by ID ─────────────────────────────────────────────────

async def get_by_id(record_id: str) -> dict | None:
    row = await fetchrow("SELECT * FROM event_log WHERE id = $1", record_id)
    return _load(row)


# ── List all ───────────────────────────────────────────────────

async def list_all() -> list[dict]:
    rows = await fetch("SELECT * FROM event_log ORDER BY created_at DESC")
    return [_load(r) for r in rows]


# ── Filter by exact name (indexed) ─────────────────────────────

async def filter_by_name(name: str) -> list[dict]:
    rows = await fetch("SELECT * FROM event_log WHERE name = $1", name)
    return [_load(r) for r in rows]


# ── Filter by name prefix ───────────────────────────────────────

async def filter_by_name_prefix(prefix: str) -> list[dict]:
    rows = await fetch("SELECT * FROM event_log WHERE name LIKE $1", f"{prefix}%")
    return [_load(r) for r in rows]


# ── Filter by created date ──────────────────────────────────────

async def filter_by_created_after(iso_datetime: str) -> list[dict]:
    rows = await fetch(
        "SELECT * FROM event_log WHERE created_at >= $1", iso_datetime
    )
    return [_load(r) for r in rows]


# ── Python-side filters (fields is TEXT/JSON — must parse) ──────

async def _all() -> list[dict]:
    return await list_all()


async def filter_by_field_id(field_id: str) -> list[dict]:
    records = await _all()
    results = []
    for rec in records:
        matched = [f for f in rec.get("fields", []) if f.get("field_id") == field_id]
        if matched:
            results.append({
                "id":            rec["id"],
                "name":          rec.get("name"),
                "created_at":    rec.get("created_at"),
                "matched_field": matched[0],
            })
    return results


async def filter_by_field_value(field_id: str, value) -> list[dict]:
    records = await _all()
    results = []
    for rec in records:
        for field in rec.get("fields", []):
            if field.get("field_id") == field_id and str(field.get("value")) == str(value):
                results.append({
                    "id":            rec["id"],
                    "name":          rec.get("name"),
                    "created_at":    rec.get("created_at"),
                    "matched_field": field,
                })
                break
    return results


async def filter_by_field_type(field_type: str) -> list[dict]:
    records = await _all()
    results = []
    for rec in records:
        matched = [f for f in rec.get("fields", []) if f.get("type") == field_type]
        if matched:
            results.append({
                "id":             rec["id"],
                "name":           rec.get("name"),
                "created_at":     rec.get("created_at"),
                "matched_fields": matched,
            })
    return results
