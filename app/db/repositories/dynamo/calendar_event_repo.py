import uuid
from datetime import datetime, timezone
from boto3.dynamodb.conditions import Key, Attr
from ....core.dynamodb import get_dynamodb
from ....core.config import settings
from ..utils import clean, strip_none


async def _table():
    db = get_dynamodb()
    return await db.Table(settings.TABLE_CALENDAR_EVENTS)


async def create(created_by_id, title, description, start_datetime, end_datetime, timezone_str, status, event_type):
    tbl = await _table()
    now = datetime.now(timezone.utc).isoformat()
    event_id = str(uuid.uuid4())
    item = strip_none({
        "id": event_id, "created_by_id": str(created_by_id), "title": title,
        "description": description, "start_datetime": start_datetime, "end_datetime": end_datetime,
        "timezone": timezone_str, "status": status, "event_type": event_type,
        "google_event_id": None, "outlook_event_id": None, "created_at": now, "updated_at": now,
    })
    await tbl.put_item(Item=item)
    return {"id": event_id}


async def get_by_id(event_id):
    tbl = await _table()
    resp = await tbl.get_item(Key={"id": event_id})
    item = resp.get("Item")
    return clean(item) if item else None


async def get_events_by_creator(created_by_id):
    tbl = await _table()
    resp = await tbl.query(
        IndexName="creator-index",
        KeyConditionExpression=Key("created_by_id").eq(str(created_by_id)),
        ScanIndexForward=False,
    )
    return [clean(r) for r in resp.get("Items", [])]


async def update_google_event_id(event_id, google_event_id):
    tbl = await _table()
    await tbl.update_item(
        Key={"id": event_id},
        UpdateExpression="SET google_event_id = :g, updated_at = :t",
        ExpressionAttributeValues={":g": google_event_id, ":t": datetime.now(timezone.utc).isoformat()},
    )


async def update_outlook_event_id(event_id, outlook_event_id):
    tbl = await _table()
    await tbl.update_item(
        Key={"id": event_id},
        UpdateExpression="SET outlook_event_id = :o, updated_at = :t",
        ExpressionAttributeValues={":o": outlook_event_id, ":t": datetime.now(timezone.utc).isoformat()},
    )


async def update(event_id, title, description, start_datetime, end_datetime, timezone_str, status):
    tbl = await _table()
    expr_values = {
        ":ti": title, ":sd": start_datetime, ":ed": end_datetime,
        ":tz": timezone_str, ":st": status, ":t": datetime.now(timezone.utc).isoformat(),
    }
    update_expr = "SET title = :ti, start_datetime = :sd, end_datetime = :ed, #tz = :tz, #st = :st, updated_at = :t"
    expr_names = {"#tz": "timezone", "#st": "status"}
    if description is not None:
        update_expr += ", description = :desc"
        expr_values[":desc"] = description
    await tbl.update_item(
        Key={"id": event_id}, UpdateExpression=update_expr,
        ExpressionAttributeNames=expr_names, ExpressionAttributeValues=expr_values,
    )


async def check_conflict(created_by_id, start_dt, end_dt):
    tbl = await _table()
    resp = await tbl.query(
        IndexName="creator-index",
        KeyConditionExpression=Key("created_by_id").eq(str(created_by_id)) & Key("start_datetime").lt(end_dt),
        FilterExpression=Attr("end_datetime").gt(start_dt) & Attr("status").eq("SCHEDULED"),
        Limit=1,
    )
    return len(resp.get("Items", [])) > 0
