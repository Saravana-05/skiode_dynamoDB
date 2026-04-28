import json
import uuid
from datetime import datetime, timezone
from boto3.dynamodb.conditions import Key, Attr
from ....core.dynamodb import get_dynamodb


async def _table():
    db = get_dynamodb()
    from ....core.config import settings
    return await db.Table(settings.TABLE_EVENT_LOG)


# ── Helpers ────────────────────────────────────────────────────

def _dump(fields: list) -> str:
    """Serialize fields list to a JSON string for storage."""
    return json.dumps(fields, ensure_ascii=False)


def _load(item: dict) -> dict:
    """Parse the 'fields' column back from JSON string to Python list."""
    if item and isinstance(item.get("fields"), str):
        item = dict(item)
        item["fields"] = json.loads(item["fields"])
    return item


# ── Write ──────────────────────────────────────────────────────

async def save(name: str, fields: list) -> str:
    tbl = await _table()
    record_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    await tbl.put_item(Item={
        "id":         record_id,
        "name":       name,
        "fields":     _dump(fields),      # ← stored as plain JSON string
        "created_at": now,
    })
    return record_id


# ── Read by ID ─────────────────────────────────────────────────

async def get_by_id(record_id: str) -> dict | None:
    tbl = await _table()
    resp = await tbl.get_item(Key={"id": record_id})
    item = resp.get("Item")
    return _load(item) if item else None


# ── List all ───────────────────────────────────────────────────

async def _scan_all() -> list[dict]:
    tbl = await _table()
    resp = await tbl.scan()
    return [_load(i) for i in resp.get("Items", [])]


async def list_all() -> list[dict]:
    return await _scan_all()


# ── APPROACH 1: GSI query (fast — top-level attribute) ─────────

async def filter_by_name(name: str) -> list[dict]:
    """
    Uses the 'name-index' GSI — O(1) lookup, no table scan.
    Only works on TOP-LEVEL attributes that have a GSI.
    """
    tbl = await _table()
    resp = await tbl.query(
        IndexName="name-index",
        KeyConditionExpression=Key("name").eq(name),
    )
    return [_load(i) for i in resp.get("Items", [])]


# ── APPROACH 2: DynamoDB FilterExpression (top-level scan) ─────

async def filter_by_created_after(iso_datetime: str) -> list[dict]:
    """
    FilterExpression on top-level 'created_at'.
    DynamoDB filters server-side before returning items.
    """
    tbl = await _table()
    resp = await tbl.scan(
        FilterExpression=Attr("created_at").gte(iso_datetime)
    )
    return [_load(i) for i in resp.get("Items", [])]


async def filter_by_name_prefix(prefix: str) -> list[dict]:
    """
    FilterExpression begins_with on top-level 'name'.
    """
    tbl = await _table()
    resp = await tbl.scan(
        FilterExpression=Attr("name").begins_with(prefix)
    )
    return [_load(i) for i in resp.get("Items", [])]


# ── APPROACH 3: Python-side filter (inside the JSON string) ────
# fields is now a JSON string column — DynamoDB cannot see inside it at all.
# We fetch all rows, _load() parses the JSON, then filter in Python.

async def filter_by_field_id(field_id: str) -> list[dict]:
    """
    Find all records that contain a field with the given field_id.
    Parses the JSON string column and filters in Python.
    """
    records = await _scan_all()
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
    """
    Find records where a specific field_id has a specific value.
    Parses the JSON string column and filters in Python.
    """
    records = await _scan_all()
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
    """
    Returns all records that contain at least one field of the given type.
    Parses the JSON string column and filters in Python.
    """
    records = await _scan_all()
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
