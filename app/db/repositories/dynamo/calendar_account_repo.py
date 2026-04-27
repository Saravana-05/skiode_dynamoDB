import uuid
from datetime import datetime, timezone
from boto3.dynamodb.conditions import Key
from ....core.dynamodb import get_dynamodb
from ....core.config import settings
from ..utils import clean, strip_none


async def _table():
    db = get_dynamodb()
    return await db.Table(settings.TABLE_CALENDAR_ACCOUNTS)


async def upsert(organization_id, user_id, provider, access_token, refresh_token, token_expiry):
    tbl = await _table()
    now = datetime.now(timezone.utc).isoformat()
    resp = await tbl.query(
        IndexName="user-provider-index",
        KeyConditionExpression=Key("user_id").eq(str(user_id)) & Key("provider").eq(provider),
        Limit=1,
    )
    items = resp.get("Items", [])
    if items:
        existing = clean(items[0])
        item_id = existing["id"]
        created_at = existing.get("created_at", now)
    else:
        item_id = str(uuid.uuid4())
        created_at = now

    item = strip_none({
        "id": item_id, "user_id": str(user_id), "provider": provider,
        "organization_id": str(organization_id), "access_token": access_token,
        "refresh_token": refresh_token, "token_expiry": token_expiry,
        "is_active": True, "created_at": created_at, "updated_at": now,
    })
    await tbl.put_item(Item=item)
    return {"id": item_id, "organization_id": str(organization_id), "user_id": str(user_id), "provider": provider}


async def get_user_accounts(user_id):
    tbl = await _table()
    resp = await tbl.query(
        IndexName="user-index",
        KeyConditionExpression=Key("user_id").eq(str(user_id)),
        FilterExpression="is_active = :a",
        ExpressionAttributeValues={":a": True},
    )
    return [clean(r) for r in resp.get("Items", [])]


async def get_provider_account(user_id, provider):
    tbl = await _table()
    resp = await tbl.query(
        IndexName="user-provider-index",
        KeyConditionExpression=Key("user_id").eq(str(user_id)) & Key("provider").eq(provider),
        Limit=1,
    )
    items = resp.get("Items", [])
    return clean(items[0]) if items else None


async def deactivate(account_id):
    tbl = await _table()
    await tbl.update_item(
        Key={"id": account_id},
        UpdateExpression="SET is_active = :f, updated_at = :t",
        ExpressionAttributeValues={":f": False, ":t": datetime.now(timezone.utc).isoformat()},
    )


async def update_tokens(account_id, access_token, refresh_token):
    tbl = await _table()
    await tbl.update_item(
        Key={"id": account_id},
        UpdateExpression="SET access_token = :a, refresh_token = :r, updated_at = :t",
        ExpressionAttributeValues={
            ":a": access_token, ":r": refresh_token,
            ":t": datetime.now(timezone.utc).isoformat(),
        },
    )
