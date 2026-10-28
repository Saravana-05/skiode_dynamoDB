"""
Create the RBAC tables for whichever backend DB_BACKEND selects.

    python -m app.db.init_rbac

  * postgresql → runs app/db/schema/rbac.sql (all statements are IF NOT EXISTS)
  * dynamodb   → creates the five rbac_* DynamoDB tables if they are missing

Safe to run repeatedly. Roles are NOT seeded here — create them from the
"RBAC Admin" screens (the Roles page has one-click Admin / Manager / Viewer).
"""
import asyncio
import os

from dotenv import load_dotenv

_env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env")
load_dotenv(_env_path)

from ..core.config import settings  # noqa: E402

SCHEMA_FILE = os.path.join(os.path.dirname(__file__), "schema", "rbac.sql")


def _split_sql(text: str) -> list[str]:
    """Drop comment-only lines, then split on ';' (no ';' inside statements)."""
    lines = [ln for ln in text.splitlines() if not ln.strip().startswith("--")]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]


async def init_postgres():
    import asyncpg
    from ..core.database import _build_ssl_context

    print(f"Connecting to PostgreSQL: {settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}")
    kwargs: dict = dict(
        host=settings.DB_HOST, port=settings.DB_PORT, user=settings.DB_USER,
        password=settings.DB_PASSWORD, database=settings.DB_NAME,
    )
    ssl_value = _build_ssl_context()
    if ssl_value is not None:
        kwargs["ssl"] = ssl_value
    conn = await asyncpg.connect(**kwargs)
    try:
        with open(SCHEMA_FILE, encoding="utf-8") as f:
            statements = _split_sql(f.read())
        for stmt in statements:
            await conn.execute(stmt)
            print(f"  ok: {stmt.splitlines()[0][:80]}")
    finally:
        await conn.close()


def dynamo_table_definitions() -> list[dict]:
    def gsi(name, key):
        return {"IndexName": name, "KeySchema": [{"AttributeName": key, "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"}}

    s = lambda n: {"AttributeName": n, "AttributeType": "S"}  # noqa: E731
    return [
        {"TableName": settings.TABLE_RBAC_ROLES,
         "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
         "AttributeDefinitions": [s("id")], "BillingMode": "PAY_PER_REQUEST"},
        {"TableName": settings.TABLE_RBAC_RESOURCES,
         "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
         "AttributeDefinitions": [s("id")], "BillingMode": "PAY_PER_REQUEST"},
        {"TableName": settings.TABLE_RBAC_PERMISSIONS,
         "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
         "AttributeDefinitions": [s("id"), s("resource_id")],
         "GlobalSecondaryIndexes": [gsi("resource-index", "resource_id")],
         "BillingMode": "PAY_PER_REQUEST"},
        {"TableName": settings.TABLE_RBAC_ROLE_PERMISSIONS,
         "KeySchema": [{"AttributeName": "role_id", "KeyType": "HASH"},
                       {"AttributeName": "permission_id", "KeyType": "RANGE"}],
         "AttributeDefinitions": [s("role_id"), s("permission_id")],
         "GlobalSecondaryIndexes": [gsi("permission-index", "permission_id")],
         "BillingMode": "PAY_PER_REQUEST"},
        {"TableName": settings.TABLE_RBAC_USER_ROLES,
         "KeySchema": [{"AttributeName": "user_id", "KeyType": "HASH"},
                       {"AttributeName": "role_id", "KeyType": "RANGE"}],
         "AttributeDefinitions": [s("user_id"), s("role_id")],
         "GlobalSecondaryIndexes": [gsi("role-index", "role_id")],
         "BillingMode": "PAY_PER_REQUEST"},
    ]


async def init_dynamodb():
    import aioboto3

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
        for defn in dynamo_table_definitions():
            name = defn["TableName"]
            if name in existing:
                print(f"  skipped (exists): {name}")
                continue
            await client.create_table(**defn)
            print(f"  created: {name} — waiting for ACTIVE...", end=" ", flush=True)
            while True:
                desc = await client.describe_table(TableName=name)
                if desc["Table"]["TableStatus"] == "ACTIVE":
                    print("ok")
                    break
                await asyncio.sleep(2)


async def init():
    print(f"RBAC init [backend: {settings.DB_BACKEND}]")
    if settings.DB_BACKEND == "dynamodb":
        await init_dynamodb()
    else:
        await init_postgres()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(init())