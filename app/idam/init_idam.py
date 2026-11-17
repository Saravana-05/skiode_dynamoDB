"""
Create the idam schema + user table, and copy existing users into it.

    python -m app.idam.init_idam

  1. runs app/idam/schema/idam.sql (idempotent)
  2. backfills idam."user" from auth_user + form_generator_userdata, KEEPING the
     same ids, so JWT user_ids and rbac_user_roles.user_id keep matching
  3. moves the identity sequence past the highest copied id

Safe to run repeatedly. PostgreSQL only (idam is a PostgreSQL schema).
"""
import asyncio
import os

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env"))

from ..core.config import settings  # noqa: E402

SCHEMA_FILE = os.path.join(os.path.dirname(__file__), "schema", "idam.sql")
LINK_FILE = os.path.join(os.path.dirname(__file__), "schema", "idam_rbac_link.sql")

BACKFILL_SQL = """
INSERT INTO idam."user" (
    id, username, email, password, is_superuser, is_staff, is_active, date_joined,
    user_name, profile_pic, user_profile_schema, is_lead, organization_id, usergroup_id
)
SELECT u.id, u.username, COALESCE(ud.mail_id, u.email), u.password, u.is_superuser,
       u.is_staff, u.is_active, u.date_joined,
       ud.user_name, ud.profile_pic, ud.user_profile_schema,
       COALESCE(ud.is_lead, FALSE), ud.organization_id, ud.usergroup_id
FROM auth_user u
LEFT JOIN form_generator_userdata ud ON ud.user_id = u.id
ON CONFLICT DO NOTHING
"""

SYNC_SEQ_SQL = """
SELECT setval(pg_get_serial_sequence('idam."user"', 'id'),
              GREATEST((SELECT COALESCE(MAX(id), 0) FROM idam."user"), 1))
"""


def _split_sql(text: str) -> list[str]:
    lines = [ln for ln in text.splitlines() if not ln.strip().startswith("--")]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]


async def init():
    import asyncpg
    from ..core.database import _build_ssl_context

    if settings.DB_BACKEND != "postgresql":
        print("idam is a PostgreSQL schema; DB_BACKEND is not 'postgresql' - nothing to do.")
        return

    kwargs: dict = dict(host=settings.DB_HOST, port=settings.DB_PORT, user=settings.DB_USER,
                        password=settings.DB_PASSWORD, database=settings.DB_NAME)
    ssl_value = _build_ssl_context()
    if ssl_value is not None:
        kwargs["ssl"] = ssl_value
    conn = await asyncpg.connect(**kwargs)
    try:
        with open(SCHEMA_FILE, encoding="utf-8-sig") as f:
            for stmt in _split_sql(f.read()):
                await conn.execute(stmt)
                print(f"  ok: {stmt.splitlines()[0][:80]}")

        try:
            res = await conn.execute(BACKFILL_SQL)
            print(f"  backfill from auth_user: {res}")
        except asyncpg.UndefinedTableError:
            print("  no legacy auth_user table - skipped backfill")
        await conn.fetchval(SYNC_SEQ_SQL)

        # Link idam.user -> RBAC (FK) and -> projects (membership). Needs rbac tables.
        if await conn.fetchval("SELECT to_regclass('rbac_user_roles')"):
            with open(LINK_FILE, encoding="utf-8-sig") as f:
                for stmt in _split_sql(f.read()):
                    await conn.execute(stmt)
                    print(f"  ok: {stmt.splitlines()[0][:80]}")
            # Per-project user tables (named after the project) for projects that
            # existed before this feature. Users already in idam.user_project are
            # copied in so nothing is lost.
            from ..db.repositories.postgres import project_user_repo
            for r in await conn.fetch("SELECT id FROM projects ORDER BY id"):
                name = await project_user_repo.ensure_table(r["id"])
                await conn.execute(
                    f'INSERT INTO idam."{name}" (user_id) SELECT user_id FROM idam.user_project '
                    f"WHERE project_id = $1 ON CONFLICT DO NOTHING", r["id"],
                )
                print(f"  ok: project {r['id']} -> idam.{name}")
        else:
            print("  rbac_user_roles missing - run `python -m app.db.init_rbac` then re-run this.")
    finally:
        await conn.close()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(init())