"""
Create the idam schema + user table, and copy existing users into it.

    python -m app.idam.init_idam

  1. runs app/idam/schema/idam.sql (idempotent)
  2. backfills idam."user" from auth_user + form_generator_userdata, KEEPING the
     same ids, so JWT user_ids and rbac_user_roles.user_id keep matching
  3. moves the identity sequence past the highest copied id
  4. migrates rbac_user_roles (CockroachDB-safe, rerunnable):
       - user_id VARCHAR -> INT8 via a helper column (ALTER COLUMN TYPE is not
         allowed on indexed columns in CockroachDB)
       - primary key moved to a surrogate id so a user can hold the same role
         in several projects

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

USER_ID_TYPE_SQL = (
    "SELECT data_type FROM information_schema.columns "
    "WHERE table_schema='public' AND table_name='rbac_user_roles' AND column_name='user_id'"
)

PK_COLUMNS_SQL = (
    "SELECT column_name FROM information_schema.key_column_usage "
    "WHERE table_schema='public' AND table_name='rbac_user_roles' "
    "AND constraint_name='rbac_user_roles_pkey' ORDER BY ordinal_position"
)

# Statements in idam_rbac_link.sql that are handled in Python instead, because
# CockroachDB rejects them on an indexed column / primary key.
SKIP_LINK_STMTS = (
    "ALTER COLUMN user_id TYPE BIGINT",
    "DROP CONSTRAINT IF EXISTS rbac_user_roles_pkey",
)


def _split_sql(text: str) -> list[str]:
    lines = [ln for ln in text.splitlines() if not ln.strip().startswith("--")]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]


async def _run(conn, statements: list[str]) -> None:
    # one statement per execute: CockroachDB schema changes dislike multi-statement batches
    for s in statements:
        await conn.execute(s)


async def migrate_rbac_user_roles(conn) -> None:
    """Make rbac_user_roles.user_id INT8 and give the table a surrogate PK. Rerunnable."""
    # --- 1. user_id VARCHAR/TEXT -> INT8 -------------------------------------
    col_type = await conn.fetchval(USER_ID_TYPE_SQL)
    if col_type in ("character varying", "text", "string"):
        await _run(conn, [
            "ALTER TABLE rbac_user_roles ADD COLUMN IF NOT EXISTS user_id_new INT8",
            "UPDATE rbac_user_roles SET user_id_new = user_id::INT8 WHERE user_id ~ '^[0-9]+$'",
            "DELETE FROM rbac_user_roles WHERE user_id_new IS NULL",
            "ALTER TABLE rbac_user_roles ALTER COLUMN user_id_new SET NOT NULL",
            "ALTER TABLE rbac_user_roles ALTER PRIMARY KEY USING COLUMNS (user_id_new, role_id)",
            "DROP INDEX IF EXISTS rbac_user_roles@rbac_user_roles_user_id_role_id_key CASCADE",
            "ALTER TABLE rbac_user_roles DROP COLUMN user_id",
            "ALTER TABLE rbac_user_roles RENAME COLUMN user_id_new TO user_id",
        ])
        print("  ok: rbac_user_roles.user_id converted to INT8")
    else:
        print(f"  skip: rbac_user_roles.user_id already {col_type}")

    # --- 2. surrogate primary key --------------------------------------------
    pk_cols = [r["column_name"] for r in await conn.fetch(PK_COLUMNS_SQL)]
    if pk_cols != ["id"]:
        await _run(conn, [
            "ALTER TABLE rbac_user_roles ADD COLUMN IF NOT EXISTS id UUID NOT NULL DEFAULT gen_random_uuid()",
            "ALTER TABLE rbac_user_roles ALTER PRIMARY KEY USING COLUMNS (id)",
            # plain index first so a user_id FK always has an index to use
            "CREATE INDEX IF NOT EXISTS idx_rbac_user_roles_user ON rbac_user_roles (user_id)",
            # old PK became a unique secondary index; it would block the same
            # (user, role) in a second project, so remove it
            "DROP INDEX IF EXISTS rbac_user_roles@rbac_user_roles_user_id_role_id_key",
        ])
        print("  ok: rbac_user_roles primary key moved to surrogate id")
    else:
        print("  skip: rbac_user_roles already has surrogate primary key")


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
            await migrate_rbac_user_roles(conn)

            with open(LINK_FILE, encoding="utf-8-sig") as f:
                for stmt in _split_sql(f.read()):
                    if any(marker in stmt for marker in SKIP_LINK_STMTS):
                        continue  # handled by migrate_rbac_user_roles()
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