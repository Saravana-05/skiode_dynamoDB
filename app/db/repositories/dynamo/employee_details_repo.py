import uuid
from datetime import datetime, timezone
from decimal import Decimal
from boto3.dynamodb.conditions import Key, Attr
from ....core.dynamodb import get_dynamodb
from ....core.config import settings
from ..utils import clean, strip_none


async def _table():
    db = get_dynamodb()
    return await db.Table(settings.TABLE_EMPLOYEE_DETAILS)


def _extract_fields(fields: list) -> dict:
    """
    Pull each field_id out of the fields list and map it to its value.
    e.g. [{"field_id": "employee_name", "value": "Rahul", ...}]
      -> {"employee_name": "Rahul", "employee_age": 31, ...}
    """
    return {f["field_id"]: f["value"] for f in fields if "field_id" in f and "value" in f}


def _to_decimal(v):
    """Convert int/float to Decimal for DynamoDB Number type."""
    if isinstance(v, float):
        return Decimal(str(v))
    if isinstance(v, int):
        return Decimal(v)
    return v


# ── Write ──────────────────────────────────────────────────────

async def save(form_name: str, fields: list, event_log_id: str) -> str:
    """
    Extract each field as a separate column and store in employee_details.
    Numbers are stored as DynamoDB Number (N), strings as String (S).
    """
    tbl = await _table()
    record_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    # Extract field values as separate columns
    extracted = _extract_fields(fields)

    item = strip_none({
        "id":                  record_id,
        "form_name":           form_name,
        "event_log_id":      event_log_id,       # link back to event_log table
        "employee_name":       extracted.get("employee_name"),
        "employee_age":        _to_decimal(extracted.get("employee_age")),
        "employee_salary":     _to_decimal(extracted.get("employee_salary")),
        "employee_dept":       extracted.get("employee_dept"),
        "employee_experience": _to_decimal(extracted.get("employee_experience")),
        "employee_region":     extracted.get("employee_region"),
        "created_at":          now,
    })

    await tbl.put_item(Item=item)
    return record_id


# ── Read all ───────────────────────────────────────────────────

async def list_all() -> list[dict]:
    tbl = await _table()
    resp = await tbl.scan()
    return [clean(i) for i in resp.get("Items", [])]


# ── Read by ID ─────────────────────────────────────────────────

async def get_by_id(record_id: str) -> dict | None:
    tbl = await _table()
    resp = await tbl.get_item(Key={"id": record_id})
    item = resp.get("Item")
    return clean(item) if item else None


# ── Filter by department (GSI) ─────────────────────────────────

async def filter_by_dept(dept: str) -> list[dict]:
    tbl = await _table()
    resp = await tbl.query(
        IndexName="dept-index",
        KeyConditionExpression=Key("employee_dept").eq(dept),
    )
    return [clean(i) for i in resp.get("Items", [])]


# ── Filter by region (GSI) ─────────────────────────────────────

async def filter_by_region(region: str) -> list[dict]:
    tbl = await _table()
    resp = await tbl.query(
        IndexName="region-index",
        KeyConditionExpression=Key("employee_region").eq(region),
    )
    return [clean(i) for i in resp.get("Items", [])]


# ── Filter by salary range (scan + FilterExpression) ───────────

async def filter_by_salary_range(min_sal: int, max_sal: int) -> list[dict]:
    tbl = await _table()
    resp = await tbl.scan(
        FilterExpression=Attr("employee_salary").between(
            Decimal(str(min_sal)), Decimal(str(max_sal))
        )
    )
    return [clean(i) for i in resp.get("Items", [])]
