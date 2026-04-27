import uuid
from datetime import datetime, timezone
from boto3.dynamodb.conditions import Key
from ....core.dynamodb import get_dynamodb
from ....core.config import settings
from ..utils import clean, strip_none


async def _table():
    db = get_dynamodb()
    return await db.Table(settings.TABLE_CALENDAR_PARTICIPANTS)


async def create(event_id, role, name, email, user_id=None, status="pending", extra=None):
    tbl = await _table()
    now = datetime.now(timezone.utc).isoformat()
    participant_id = str(uuid.uuid4())
    item = strip_none({
        "id": participant_id, "event_id": str(event_id),
        "user_id": str(user_id) if user_id else None,
        "role": role, "name": name, "email": email, "status": status,
        "extra": extra or {}, "created_at": now, "updated_at": now,
    })
    await tbl.put_item(Item=item)
    return participant_id


async def get_by_event(event_id):
    tbl = await _table()
    resp = await tbl.query(
        IndexName="event-index",
        KeyConditionExpression=Key("event_id").eq(str(event_id)),
        ScanIndexForward=True,
    )
    return [clean(r) for r in resp.get("Items", [])]


async def get_by_email(email):
    tbl = await _table()
    resp = await tbl.query(
        IndexName="email-index",
        KeyConditionExpression=Key("email").eq(email),
        ScanIndexForward=False,
    )
    return [clean(r) for r in resp.get("Items", [])]


async def get_events_by_email(email, start_dt, end_dt):
    from . import calendar_event_repo
    participants = await get_by_email(email)
    if not participants:
        return []
    event_ids = list({p["event_id"] for p in participants})
    events = []
    for eid in event_ids:
        event = await calendar_event_repo.get_by_id(eid)
        if event and event.get("start_datetime", "") >= start_dt and event.get("end_datetime", "") <= end_dt:
            events.append(event)
    events.sort(key=lambda e: e.get("start_datetime", ""), reverse=True)
    return events


async def update_status(participant_id, status):
    tbl = await _table()
    await tbl.update_item(
        Key={"id": participant_id},
        UpdateExpression="SET #st = :s, updated_at = :t",
        ExpressionAttributeNames={"#st": "status"},
        ExpressionAttributeValues={":s": status, ":t": datetime.now(timezone.utc).isoformat()},
    )
