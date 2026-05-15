"""
Dynamic datastore — create DynamoDB tables from a JSON schema,
then insert / query rows against those tables.

Schema field types supported:
    text          → DynamoDB S (String)
    number        → DynamoDB N (Number / Decimal)
    formattedText → DynamoDB S (String)
    boolean       → DynamoDB BOOL
    date          → DynamoDB S (ISO string)

Self-initializing: the datastore_schemas meta-table is created
automatically on first use if it doesn't exist yet.
"""
import asyncio
import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import aioboto3

from ....core.dynamodb import get_dynamodb
from ....core.config import settings
from ..utils import clean, strip_none


# ── type helpers ────────────────────────────────────────────────

_DYNAMO_TYPE = {
    "text":          "S",
    "formattedText": "S",
    "date":          "S",
    "number":        "N",
    "boolean":       "BOOL",
}


def _cast(value, field_type: str):
    """Cast a Python value to the correct DynamoDB-compatible type."""
    if field_type == "number":
        if value is None:
            return None
        return Decimal(str(value))
    if field_type == "boolean":
        return bool(value)
    return str(value) if value is not None else None


# ── AWS client kwargs ────────────────────────────────────────────

def _aws_kwargs() -> dict:
    kwargs = {"region_name": settings.AWS_REGION}
    if settings.AWS_ACCESS_KEY_ID:
        kwargs["aws_access_key_id"] = settings.AWS_ACCESS_KEY_ID
    if settings.AWS_SECRET_ACCESS_KEY:
        kwargs["aws_secret_access_key"] = settings.AWS_SECRET_ACCESS_KEY
    if settings.DYNAMODB_ENDPOINT_URL:
        kwargs["endpoint_url"] = settings.DYNAMODB_ENDPOINT_URL
    return kwargs


# ── Wait for table to become ACTIVE ─────────────────────────────

async def _wait_active(client, table_name: str, timeout_seconds: int = 60) -> None:
    """
    Poll until the DynamoDB table reaches ACTIVE status.
    Raises TimeoutError if the table is not ACTIVE within `timeout_seconds`.
    """
    deadline = asyncio.get_event_loop().time() + timeout_seconds
    while True:
        desc = await client.describe_table(TableName=table_name)
        status = desc["Table"]["TableStatus"]
        if status == "ACTIVE":
            return
        if asyncio.get_event_loop().time() > deadline:
            raise TimeoutError(
                f"Table '{table_name}' did not become ACTIVE within {timeout_seconds}s "
                f"(current status: {status})"
            )
        await asyncio.sleep(2)


# ── Auto-create the datastore_schemas meta-table ─────────────────

_schemas_table_ready = False   # module-level flag — checked once per process


async def _ensure_schemas_table(client) -> None:
    """
    Create the datastore_schemas meta-table if it does not exist.
    Uses a module-level flag so the check runs at most once per process.
    """
    global _schemas_table_ready
    if _schemas_table_ready:
        return

    existing = set((await client.list_tables())["TableNames"])
    if settings.TABLE_SCHEMAS not in existing:
        print(f"[datastore] Creating meta-table '{settings.TABLE_SCHEMAS}'...")
        await client.create_table(
            TableName=settings.TABLE_SCHEMAS,
            KeySchema=[{"AttributeName": "table_name", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "table_name", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        await _wait_active(client, settings.TABLE_SCHEMAS)
        print(f"[datastore] Meta-table '{settings.TABLE_SCHEMAS}' is ACTIVE.")
    else:
        print(f"[datastore] Meta-table '{settings.TABLE_SCHEMAS}' already exists.")

    _schemas_table_ready = True


# ── schemas meta-table helpers ───────────────────────────────────

async def _schemas_table():
    db = get_dynamodb()
    return await db.Table(settings.TABLE_SCHEMAS)


async def save_schema(table_name: str, schema: list) -> None:
    """Persist the schema definition to the datastore_schemas table."""
    # Ensure the meta-table exists before writing
    session = aioboto3.Session()
    async with session.client("dynamodb", **_aws_kwargs()) as client:
        await _ensure_schemas_table(client)

    tbl = await _schemas_table()
    await tbl.put_item(Item={
        "table_name": table_name,
        "schema":     json.dumps(schema),
        "created_at": datetime.now(timezone.utc).isoformat(),
    })


async def get_schema(table_name: str) -> list | None:
    """Return the schema list for a table, or None if not found."""
    tbl = await _schemas_table()
    resp = await tbl.get_item(Key={"table_name": table_name})
    item = resp.get("Item")
    if not item:
        return None
    return json.loads(item["schema"])


async def list_schemas() -> list[dict]:
    """List all registered schemas."""
    tbl = await _schemas_table()
    resp = await tbl.scan()
    result = []
    for item in resp.get("Items", []):
        result.append({
            "table_name": item["table_name"],
            "schema":     json.loads(item["schema"]),
            "created_at": item.get("created_at"),
        })
    return result


# ── dynamic table creation ───────────────────────────────────────

async def create_table_from_schema(table_name: str, schema: list) -> dict:
    """
    Create a real DynamoDB table named `table_name` in AWS.

    - Primary key: id (S) — HASH key
    - Billing:     PAY_PER_REQUEST (on-demand, no capacity planning needed)
    - Region:      settings.AWS_REGION  (default: ap-south-1)

    DynamoDB is schema-less for non-key attributes; the schema fields
    are stored separately in datastore_schemas (via save_schema).

    Returns:
        {"created": True,  "table_name": ...}   ← new table
        {"created": False, "table_name": ..., "reason": "already exists"}
    """
    session = aioboto3.Session()
    async with session.client("dynamodb", **_aws_kwargs()) as client:

        # Ensure the meta-table exists (idempotent)
        await _ensure_schemas_table(client)

        # Check if the data table already exists
        existing = set((await client.list_tables())["TableNames"])
        if table_name in existing:
            return {
                "created": False,
                "table_name": table_name,
                "reason": "already exists",
            }

        # Create the table — id is the only key attribute
        print(f"[datastore] Creating table '{table_name}' in DynamoDB ({settings.AWS_REGION})...")
        await client.create_table(
            TableName=table_name,
            KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )

        # Wait up to 60 seconds for the table to become ACTIVE
        await _wait_active(client, table_name, timeout_seconds=60)
        print(f"[datastore] Table '{table_name}' is ACTIVE in DynamoDB.")

    return {"created": True, "table_name": table_name}


# ── row insert ───────────────────────────────────────────────────

async def insert_row(table_name: str, schema: list, row_data: dict) -> str:
    """
    Insert one row into a dynamic table.
    Each schema field becomes its own DynamoDB attribute (separate column).
    row_data keys must match field_id values in the schema.
    Returns the generated record_id (UUID string).
    """
    db = get_dynamodb()
    tbl = await db.Table(table_name)

    record_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    item = {"id": record_id, "created_at": now}

    for field in schema:
        field_id   = field["field_id"]
        field_type = field.get("type", "text")
        value      = row_data.get(field_id)

        # Fall back to default from schema if caller didn't supply a value
        if value is None:
            value = field.get("value")

        casted = _cast(value, field_type)
        if casted is not None:
            item[field_id] = casted

    await tbl.put_item(Item=strip_none(item))
    return record_id


# ── row queries ──────────────────────────────────────────────────

async def list_rows(table_name: str) -> list[dict]:
    """Scan all rows from a dynamic table."""
    db = get_dynamodb()
    tbl = await db.Table(table_name)
    resp = await tbl.scan()
    return [clean(i) for i in resp.get("Items", [])]


async def get_row(table_name: str, record_id: str) -> dict | None:
    """Get one row by id."""
    db = get_dynamodb()
    tbl = await db.Table(table_name)
    resp = await tbl.get_item(Key={"id": record_id})
    item = resp.get("Item")
    return clean(item) if item else None
