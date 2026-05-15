"""
Create all fixed PostgreSQL tables needed by the FastAPI service.
Run once before starting the server with DB_BACKEND=postgresql.

Usage:
    python -m app.db.init_pg_tables
"""
import asyncio
import os
from dotenv import load_dotenv

_env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env")
load_dotenv(_env_path)

from ..core.config import settings


SQL = """
-- ── event_log ──────────────────────────────────────────────────
-- Stores form submissions with fields as a JSON string (TEXT)
CREATE TABLE IF NOT EXISTS event_log (
    id          VARCHAR PRIMARY KEY,
    name        VARCHAR NOT NULL,
    fields      TEXT,
    created_at  VARCHAR
);
CREATE INDEX IF NOT EXISTS idx_event_log_name       ON event_log (name);
CREATE INDEX IF NOT EXISTS idx_event_log_created_at ON event_log (created_at);

-- ── employee_details ───────────────────────────────────────────
-- Each employee field stored as its own column
CREATE TABLE IF NOT EXISTS employee_details (
    id                  VARCHAR PRIMARY KEY,
    form_name           VARCHAR,
    event_log_id        VARCHAR,
    employee_name       VARCHAR,
    employee_age        NUMERIC,
    employee_salary     NUMERIC,
    employee_dept       VARCHAR,
    employee_experience NUMERIC,
    employee_region     VARCHAR,
    created_at          VARCHAR
);
CREATE INDEX IF NOT EXISTS idx_emp_dept   ON employee_details (employee_dept);
CREATE INDEX IF NOT EXISTS idx_emp_region ON employee_details (employee_region);

-- ── datastore_schemas ──────────────────────────────────────────
-- Stores user-defined schemas for the dynamic datastore
CREATE TABLE IF NOT EXISTS datastore_schemas (
    table_name  VARCHAR PRIMARY KEY,
    schema      TEXT NOT NULL,
    created_at  VARCHAR
);
"""


async def init():
    import asyncpg
    print(f"Connecting to PostgreSQL: {settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}")
    conn = await asyncpg.connect(dsn=settings.DATABASE_URL)
    try:
        # Execute each statement separately (asyncpg doesn't run multi-statement strings)
        statements = [s.strip() for s in SQL.split(";") if s.strip()]
        for stmt in statements:
            try:
                await conn.execute(stmt)
                # Print the table/index name from the statement
                first_line = stmt.splitlines()[0]
                print(f"  ok: {first_line[:80]}")
            except Exception as e:
                print(f"  warn: {e}")
    finally:
        await conn.close()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(init())
