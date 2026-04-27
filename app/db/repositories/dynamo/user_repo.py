import uuid
from datetime import datetime, timezone
from boto3.dynamodb.conditions import Key
from ....core.dynamodb import get_dynamodb
from ....core.config import settings
from ..utils import clean, strip_none


async def _table():
    db = get_dynamodb()
    return await db.Table(settings.TABLE_USERS)


async def get_by_email(email):
    tbl = await _table()
    resp = await tbl.get_item(Key={"email": email.strip().lower()})
    item = resp.get("Item")
    return clean(item) if item else None


async def get_by_user_id(user_id):
    tbl = await _table()
    resp = await tbl.query(
        IndexName="user-id-index",
        KeyConditionExpression=Key("user_id").eq(str(user_id)),
        Limit=1,
    )
    items = resp.get("Items", [])
    return clean(items[0]) if items else None


async def get_by_username(username):
    tbl = await _table()
    resp = await tbl.query(
        IndexName="username-index",
        KeyConditionExpression=Key("username").eq(username),
        Limit=1,
    )
    items = resp.get("Items", [])
    return clean(items[0]) if items else None


async def create(username, email, password, is_superuser, is_staff, is_active,
                 date_joined, user_name, organization_id, usergroup_id=None,
                 profile_pic=None, is_lead=False):
    tbl = await _table()
    now = datetime.now(timezone.utc).isoformat()
    user_id = str(uuid.uuid4())
    norm_email = email.strip().lower()
    item = strip_none({
        "email": norm_email, "user_id": user_id, "username": username,
        "password": password, "is_superuser": is_superuser, "is_staff": is_staff,
        "is_active": is_active, "date_joined": date_joined, "user_name": user_name,
        "profile_pic": profile_pic, "user_profile_schema": "", "is_lead": is_lead,
        "organization_id": str(organization_id),
        "usergroup_id": str(usergroup_id) if usergroup_id else None,
        "created_at": now, "updated_at": now,
    })
    await tbl.put_item(Item=item)
    return {"user_id": user_id, "email": norm_email}


async def update_password(user_id, hashed_password):
    tbl = await _table()
    user = await get_by_user_id(user_id)
    if not user:
        raise ValueError(f"User not found: {user_id}")
    await tbl.update_item(
        Key={"email": user["email"]},
        UpdateExpression="SET password = :p, updated_at = :t",
        ExpressionAttributeValues={
            ":p": hashed_password, ":t": datetime.now(timezone.utc).isoformat(),
        },
    )
