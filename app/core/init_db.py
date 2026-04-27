import os
import asyncio
from ..core.database import init_pool, get_pool


BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

SCHEMA_PATH = os.path.join(BASE_DIR, "app", "db", "schema")


# Order matters (FK dependency)
SQL_FILES_ORDER = [
    "calendar_account.sql",
    "calendar_event.sql",
]


async def init_db():
    print("Initializing database schema...")

    await init_pool()
    pool = get_pool()

    async with pool.acquire() as conn:
        for file in SQL_FILES_ORDER:
            path = os.path.join(SCHEMA_PATH, file)

            if not os.path.exists(path):
                print(f"File not found: {file}")
                continue

            print(f"📄 Executing: {file}")

            with open(path, "r", encoding="utf-8") as f:
                sql = f.read()

            try:
                await conn.execute(sql)
            except Exception as e:
                print(f"Error in {file}: {e}")
                raise

    print("Database schema created successfully.")


if __name__ == "__main__":
    asyncio.run(init_db())
