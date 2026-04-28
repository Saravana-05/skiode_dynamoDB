"""
Delete all app DynamoDB tables so init_tables.py can recreate them correctly.

Usage:
    python -m app.db.drop_tables
"""
import asyncio
import aioboto3
import os
from dotenv import load_dotenv

_env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env")
load_dotenv(_env_path)

from ..core.config import settings

TABLES = [
    settings.TABLE_CALENDAR_ACCOUNTS,
    settings.TABLE_CALENDAR_EVENTS,
    settings.TABLE_CALENDAR_PARTICIPANTS,
    settings.TABLE_USERS,
    settings.TABLE_ORGANIZATIONS,
    settings.TABLE_ORG_AUTH_CONFIGS,
    settings.TABLE_USERGROUPS,
    settings.TABLE_EMPLOYEE_DETAILS,
    settings.TABLE_SCHEMAS,
    settings.TABLE_EVENT_LOG,
]


async def drop():
    kwargs = {"region_name": settings.AWS_REGION}
    if settings.AWS_ACCESS_KEY_ID:
        kwargs["aws_access_key_id"] = settings.AWS_ACCESS_KEY_ID
    if settings.AWS_SECRET_ACCESS_KEY:
        kwargs["aws_secret_access_key"] = settings.AWS_SECRET_ACCESS_KEY
    if settings.DYNAMODB_ENDPOINT_URL:
        kwargs["endpoint_url"] = settings.DYNAMODB_ENDPOINT_URL

    session = aioboto3.Session()
    async with session.client("dynamodb", **kwargs) as client:
        existing = set((await client.list_tables())["TableNames"])

        for name in TABLES:
            if name not in existing:
                print(f"  skipped (not found): {name}")
                continue
            await client.delete_table(TableName=name)
            print(f"  deleted: {name}")

    print("Done. Now run: python -m app.db.init_tables")


if __name__ == "__main__":
    asyncio.run(drop())
