"""
Run this script once to create all DynamoDB tables (dev/staging).
Production tables should be managed via CloudFormation/CDK.

Usage:
    python -m app.db.init_tables
"""
import asyncio
import aioboto3
import os
from dotenv import load_dotenv

_env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env")
load_dotenv(_env_path)

from ..core.config import settings


TABLE_DEFINITIONS = [
    {
        "TableName": settings.TABLE_CALENDAR_ACCOUNTS,
        "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
        "AttributeDefinitions": [
            {"AttributeName": "id", "AttributeType": "S"},
            {"AttributeName": "user_id", "AttributeType": "S"},
            {"AttributeName": "provider", "AttributeType": "S"},
        ],
        "GlobalSecondaryIndexes": [
            {
                "IndexName": "user-index",
                "KeySchema": [{"AttributeName": "user_id", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
            },
            {
                "IndexName": "user-provider-index",
                "KeySchema": [
                    {"AttributeName": "user_id", "KeyType": "HASH"},
                    {"AttributeName": "provider", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
        "BillingMode": "PAY_PER_REQUEST",
    },
    {
        "TableName": settings.TABLE_CALENDAR_EVENTS,
        "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
        "AttributeDefinitions": [
            {"AttributeName": "id", "AttributeType": "S"},
            {"AttributeName": "created_by_id", "AttributeType": "S"},
            {"AttributeName": "start_datetime", "AttributeType": "S"},
        ],
        "GlobalSecondaryIndexes": [
            {
                "IndexName": "creator-index",
                "KeySchema": [
                    {"AttributeName": "created_by_id", "KeyType": "HASH"},
                    {"AttributeName": "start_datetime", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
        "BillingMode": "PAY_PER_REQUEST",
    },
    {
        "TableName": settings.TABLE_CALENDAR_PARTICIPANTS,
        "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
        "AttributeDefinitions": [
            {"AttributeName": "id", "AttributeType": "S"},
            {"AttributeName": "event_id", "AttributeType": "S"},
            {"AttributeName": "email", "AttributeType": "S"},
            {"AttributeName": "created_at", "AttributeType": "S"},
        ],
        "GlobalSecondaryIndexes": [
            {
                "IndexName": "event-index",
                "KeySchema": [
                    {"AttributeName": "event_id", "KeyType": "HASH"},
                    {"AttributeName": "id", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
            {
                "IndexName": "email-index",
                "KeySchema": [
                    {"AttributeName": "email", "KeyType": "HASH"},
                    {"AttributeName": "created_at", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
        "BillingMode": "PAY_PER_REQUEST",
    },
    {
        "TableName": settings.TABLE_USERS,
        "KeySchema": [{"AttributeName": "email", "KeyType": "HASH"}],
        "AttributeDefinitions": [
            {"AttributeName": "email", "AttributeType": "S"},
            {"AttributeName": "user_id", "AttributeType": "S"},
            {"AttributeName": "username", "AttributeType": "S"},
        ],
        "GlobalSecondaryIndexes": [
            {
                "IndexName": "user-id-index",
                "KeySchema": [{"AttributeName": "user_id", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
            },
            {
                "IndexName": "username-index",
                "KeySchema": [{"AttributeName": "username", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
        "BillingMode": "PAY_PER_REQUEST",
    },
    {
        "TableName": settings.TABLE_ORGANIZATIONS,
        "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
        "AttributeDefinitions": [
            {"AttributeName": "id", "AttributeType": "S"},
            {"AttributeName": "org_code", "AttributeType": "S"},
        ],
        "GlobalSecondaryIndexes": [
            {
                "IndexName": "code-index",
                "KeySchema": [{"AttributeName": "org_code", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
        "BillingMode": "PAY_PER_REQUEST",
    },
    {
        "TableName": settings.TABLE_ORG_AUTH_CONFIGS,
        "KeySchema": [{"AttributeName": "organization_id", "KeyType": "HASH"}],
        "AttributeDefinitions": [{"AttributeName": "organization_id", "AttributeType": "S"}],
        "BillingMode": "PAY_PER_REQUEST",
    },
    {
        "TableName": settings.TABLE_USERGROUPS,
        "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
        "AttributeDefinitions": [{"AttributeName": "id", "AttributeType": "S"}],
        "BillingMode": "PAY_PER_REQUEST",
    },
    # ── Employees table ───────────────────────────────────────
    {
        "TableName": settings.TABLE_EMPLOYEES,
        "KeySchema": [{"AttributeName": "employee_id", "KeyType": "HASH"}],
        "AttributeDefinitions": [
            {"AttributeName": "employee_id", "AttributeType": "S"},
            {"AttributeName": "entity_type", "AttributeType": "S"},
            {"AttributeName": "skills_count", "AttributeType": "N"},
        ],
        "GlobalSecondaryIndexes": [
            {
                "IndexName": "skills-count-index",
                "KeySchema": [
                    {"AttributeName": "entity_type", "KeyType": "HASH"},
                    {"AttributeName": "skills_count", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
        "BillingMode": "PAY_PER_REQUEST",
    },
    # ── employee_details table ────────────────────────────────
    {
        "TableName": settings.TABLE_EMPLOYEE_DETAILS,
        "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
        "AttributeDefinitions": [
            {"AttributeName": "id",              "AttributeType": "S"},
            {"AttributeName": "employee_dept",   "AttributeType": "S"},
            {"AttributeName": "employee_region", "AttributeType": "S"},
        ],
        "GlobalSecondaryIndexes": [
            {
                "IndexName": "dept-index",
                "KeySchema": [{"AttributeName": "employee_dept", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
            },
            {
                "IndexName": "region-index",
                "KeySchema": [{"AttributeName": "employee_region", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
        "BillingMode": "PAY_PER_REQUEST",
    },
    # ── event_log table ───────────────────────────────────────
    {
        "TableName": settings.TABLE_EVENT_LOG,
        "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
        "AttributeDefinitions": [
            {"AttributeName": "id",   "AttributeType": "S"},
            {"AttributeName": "name", "AttributeType": "S"},
        ],
        "GlobalSecondaryIndexes": [
            {
                "IndexName": "name-index",
                "KeySchema": [{"AttributeName": "name", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
        "BillingMode": "PAY_PER_REQUEST",
    },
    # ── datastore_schemas table ───────────────────────────────
    {
        "TableName": settings.TABLE_SCHEMAS,
        "KeySchema": [{"AttributeName": "table_name", "KeyType": "HASH"}],
        "AttributeDefinitions": [
            {"AttributeName": "table_name", "AttributeType": "S"},
        ],
        "BillingMode": "PAY_PER_REQUEST",
    },
]


async def init_tables():
    kwargs = {"region_name": settings.AWS_REGION}
    if settings.AWS_ACCESS_KEY_ID:
        kwargs["aws_access_key_id"] = settings.AWS_ACCESS_KEY_ID
    if settings.AWS_SECRET_ACCESS_KEY:
        kwargs["aws_secret_access_key"] = settings.AWS_SECRET_ACCESS_KEY
    if settings.DYNAMODB_ENDPOINT_URL:
        kwargs["endpoint_url"] = settings.DYNAMODB_ENDPOINT_URL

    session = aioboto3.Session()
    async with session.client("dynamodb", **kwargs) as client:
        existing = {t for t in (await client.list_tables())["TableNames"]}

        for defn in TABLE_DEFINITIONS:
            name = defn["TableName"]
            if name in existing:
                print(f"  skipped (exists): {name}")
                continue

            await client.create_table(**defn)
            print(f"  created: {name} — waiting for ACTIVE...", end=" ", flush=True)

            # Poll until the table status is ACTIVE (usually 5-15 seconds)
            while True:
                desc = await client.describe_table(TableName=name)
                status = desc["Table"]["TableStatus"]
                if status == "ACTIVE":
                    print("ACTIVE ok")
                    break
                await asyncio.sleep(2)

    print("Done.")


if __name__ == "__main__":
    asyncio.run(init_tables())
