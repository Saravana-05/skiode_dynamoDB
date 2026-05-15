"""
asyncpg connection pool for PostgreSQL / CockroachDB.

SSL handling:
  sslmode=disable      → no SSL
  sslmode=require      → SSL on, certificate NOT verified (CockroachDB Cloud safe)
  sslmode=verify-full  → SSL on, certificate verified via system CA store
  sslmode=verify-ca    → same as verify-full here

asyncpg does not honour the ?sslmode= DSN param reliably for all modes,
so we build an explicit ssl.SSLContext and pass it as a kwarg instead.
"""
import ssl
import asyncpg
from .config import settings

_pool = None


def _build_ssl_context() -> "ssl.SSLContext | bool | None":
    """Return the right SSL value for asyncpg based on DB_SSLMODE."""
    sslmode = (settings.DB_SSLMODE or "").lower()

    if sslmode == "disable":
        return False                          # no SSL at all

    if sslmode == "require":
        # Encrypted, but skip certificate verification.
        # Safe for CockroachDB Cloud / managed Postgres — the transport is
        # still encrypted, we just don't pin the server cert.
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode    = ssl.CERT_NONE
        return ctx

    if sslmode in ("verify-ca", "verify-full"):
        # Use the system trust store (Python's certifi / OS bundle).
        # CockroachDB Cloud's cert is signed by a public CA so this works
        # without downloading any extra root cert.
        ctx = ssl.create_default_context()
        # check_hostname requires verify-full semantics; keep it on.
        return ctx

    # prefer / allow / anything else → let asyncpg decide
    return None


async def _ensure_database_exists(ssl_value) -> None:
    """
    Try to create the target database if it does not exist yet.
    Works for CockroachDB Cloud and plain PostgreSQL.
    On AWS RDS / managed Postgres the DB is usually pre-created, so failures
    here are silently ignored and we fall through to the normal pool connect.
    """
    target_db = settings.DB_NAME

    # Try bootstrap databases in order; give up gracefully if none work
    for fallback_db in ("postgres", "defaultdb"):
        try:
            conn_kwargs: dict = dict(
                host     = settings.DB_HOST,
                port     = settings.DB_PORT,
                user     = settings.DB_USER,
                password = settings.DB_PASSWORD,
                database = fallback_db,
            )
            if ssl_value is not None:
                conn_kwargs["ssl"] = ssl_value

            conn = await asyncpg.connect(**conn_kwargs)
            try:
                exists = await conn.fetchval(
                    "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_database WHERE datname = $1)",
                    target_db,
                )
                if not exists:
                    # CREATE DATABASE cannot run inside a transaction block
                    await conn.execute(f'CREATE DATABASE "{target_db}"')
                    print(f"[db] Database '{target_db}' created.")
                else:
                    print(f"[db] Database '{target_db}' already exists.")
            finally:
                await conn.close()
            return   # success
        except Exception:
            continue  # try next bootstrap db or give up

    # Could not verify / create (e.g. AWS RDS with no 'postgres' bootstrap access) — proceed anyway
    print(f"[db] Could not verify database '{target_db}' existence — assuming it already exists.")


async def init_pool():
    global _pool
    if _pool is None:
        ssl_value = _build_ssl_context()

        # Auto-create the target database if it doesn't exist yet
        await _ensure_database_exists(ssl_value)

        connect_kwargs: dict = dict(
            host     = settings.DB_HOST,
            port     = settings.DB_PORT,
            user     = settings.DB_USER,
            password = settings.DB_PASSWORD,
            database = settings.DB_NAME,
            min_size = 1,
            max_size = 10,
        )
        if ssl_value is not None:
            connect_kwargs["ssl"] = ssl_value

        _pool = await asyncpg.create_pool(**connect_kwargs)
        print(
            f"[db] PostgreSQL pool connected "
            f"[host={settings.DB_HOST} db={settings.DB_NAME} ssl={settings.DB_SSLMODE}]"
        )


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("PostgreSQL pool not initialized — call init_pool() first.")
    return _pool


async def ensure_pool() -> asyncpg.Pool:
    """Lazily initialize the pool if it hasn't been set up yet. Safe to call multiple times."""
    if _pool is None:
        await init_pool()
    return _pool


async def close_pool():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        print("[db] PostgreSQL pool closed.")


# ── Convenience wrappers ────────────────────────────────────────

async def execute(query: str, *args):
    pool = await ensure_pool()
    async with pool.acquire() as conn:
        return await conn.execute(query, *args)


async def fetch(query: str, *args):
    pool = await ensure_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(query, *args)


async def fetchrow(query: str, *args):
    pool = await ensure_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(query, *args)
