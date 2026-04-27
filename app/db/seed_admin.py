"""
Insert the initial admin user into DynamoDB users table.

Usage:
    python -m app.db.seed_admin
"""
import asyncio
import uuid
from datetime import datetime, timezone

import aioboto3
from ..core.config import settings
from ..utils.password import hash_password


ADMIN_EMAIL    = "admin@skiode.com"
ADMIN_USERNAME = "admin@skiode.com"
ADMIN_PASSWORD = "Skiode@123"


async def seed():
    kwargs = {"region_name": settings.AWS_REGION}
    if settings.AWS_ACCESS_KEY_ID:
        kwargs["aws_access_key_id"] = settings.AWS_ACCESS_KEY_ID
    if settings.AWS_SECRET_ACCESS_KEY:
        kwargs["aws_secret_access_key"] = settings.AWS_SECRET_ACCESS_KEY
    if settings.DYNAMODB_ENDPOINT_URL:
        kwargs["endpoint_url"] = settings.DYNAMODB_ENDPOINT_URL

    hashed = hash_password(ADMIN_PASSWORD)
    now    = datetime.now(timezone.utc).isoformat()
    uid    = str(uuid.uuid4())

    item = {
        "email":              ADMIN_EMAIL,
        "user_id":            uid,
        "username":           ADMIN_USERNAME,
        "password":           hashed,
        "is_superuser":       True,
        "is_staff":           True,
        "is_active":          True,
        "date_joined":        now,
        "user_name":          "admin",
        "user_profile_schema": "",
        "is_lead":            False,
        "created_at":         now,
        "updated_at":         now,
    }

    session = aioboto3.Session()
    async with session.resource("dynamodb", **kwargs) as db:
        table = await db.Table(settings.TABLE_USERS)
        await table.put_item(Item=item)

    print(f"Admin user inserted.")
    print(f"  email   : {ADMIN_EMAIL}")
    print(f"  user_id : {uid}")
    print(f"  password: {ADMIN_PASSWORD}  (stored hashed)")


if __name__ == "__main__":
    asyncio.run(seed())
