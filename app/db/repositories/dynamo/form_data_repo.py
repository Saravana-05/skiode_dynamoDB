import uuid
from datetime import datetime, timezone
from decimal import Decimal
from boto3.dynamodb.conditions import Key, Attr
from ....core.dynamodb import get_dynamodb
from ..utils import clean


# ── Helpers ────────────────────────────────────────────────────

def _to_dynamo(obj):
    """float → Decimal (DynamoDB rejects plain float)."""
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _to_dynamo(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_dynamo(i) for i in obj]
    return obj


async def _table():
    db = get_dynamodb()
    return await db.Table("form_data")


# ── Write ──────────────────────────────────────────────────────

async def save(name: str, fields: list) -> str:
    tbl = await _table()
    record_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    await tbl.put_item(Item={
        "id":         record_id,
        "name":       name,
        "fields":     _to_dynamo(fields),
        "created_at": now,
    })
    return record_id


# ── Read by ID ─────────────────────────────────────────────────

async def get_by_id(record_id: str) -> dict | None:
    tbl = await _table()
    resp = await tbl.get_item(Key={"id": record_id})
    item = resp.get("Item")
    return clean(item) if item else None


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
    return [clean(i) for i in resp.get("Items", [])]


# ── APPROACH 2: DynamoDB FilterExpression (mid — top-level scan) ──

async def filter_by_created_after(iso_datetime: str) -> list[dict]:
    """
    FilterExpression on a top-level attribute.
    DynamoDB scans all items but filters server-side before returning.
    Still reads all items — use GSI for performance on large tables.
    """
    tbl = await _table()
    resp = await tbl.scan(
        FilterExpression=Attr("created_at").gte(iso_datetime)
    )
    return [clean(i) for i in resp.get("Items", [])]


async def filter_by_name_prefix(prefix: str) -> list[dict]:
    """
    FilterExpression begins_with on top-level 'name'.
    No GSI needed but scans full table.
    """
    tbl = await _table()
    resp = await tbl.scan(
        FilterExpression=Attr("name").begins_with(prefix)
    )
    return [clean(i) for i in resp.get("Items", [])]


# ── APPROACH 3: Python-side filter (nested List/Map values) ────

async def _scan_all() -> list[dict]:
    tbl = await _table()
    resp = await tbl.scan()
    return [clean(i) for i in resp.get("Items", [])]


async def filter_by_field_id(field_id: str) -> list[dict]:
    """
    Find all records that contain a field with the given field_id.
    DynamoDB cannot index inside a List — we scan then filter in Python.
    Returns matching records with only the matched field extracted.
    """
    records = await _scan_all()
    results = []
    for rec in records:
        matched = [f for f in rec.get("fields", []) if f.get("field_id") == field_id]
        if matched:
            results.append({
                "id":         rec["id"],
                "name":       rec.get("name"),
                "created_at": rec.get("created_at"),
                "matched_field": matched[0],
            })
    return results


async def filter_by_field_value(field_id: str, value) -> list[dict]:
    """
    Find records where a specific field_id has a specific value.
    Scan + Python filter — necessary for nested List lookups.
    """
    records = await _scan_all()
    results = []
    for rec in records:
        for field in rec.get("fields", []):
            if field.get("field_id") == field_id and str(field.get("value")) == str(value):
                results.append({
                    "id":          rec["id"],
                    "name":        rec.get("name"),
                    "created_at":  rec.get("created_at"),
                    "matched_field": field,
                })
                break
    return results


async def filter_by_field_type(field_type: str) -> list[dict]:
    """
    Find all records that have at least one field of the given type
    (e.g. 'number', 'text', 'formattedText').
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


async def list_all() -> list[dict]:
    return await _scan_all()
