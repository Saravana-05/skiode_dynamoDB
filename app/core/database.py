"""
asyncpg connection pool for PostgreSQL / CockroachDB.

SSL handling:
  sslmode=disable      → no SSL
  sslmode=require      → SSL on, certificate NOT verified
  sslmode=verify-full  → SSL on, certificate verified via system CA store
"""
import ssl
import asyncpg
from .config import settings

_pool = None


def _build_ssl_context() -> "ssl.SSLContext | bool | None":
    sslmode = (settings.DB_SSLMODE or "").lower()
    if sslmode == "disable":
        return False
    if sslmode == "require":
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    if sslmode in ("verify-ca", "verify-full"):
        return ssl.create_default_context()
    return None


async def _ensure_database_exists(ssl_value) -> None:
    target_db = settings.DB_NAME
    for fallback_db in ("postgres", "defaultdb"):
        try:
            conn_kwargs: dict = dict(
                host=settings.DB_HOST,
                port=settings.DB_PORT,
                user=settings.DB_USER,
                password=settings.DB_PASSWORD,
                database=fallback_db,
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
                    await conn.execute(f'CREATE DATABASE "{target_db}"')
                    print(f"[db] Database '{target_db}' created.")
                else:
                    print(f"[db] Database '{target_db}' already exists.")
            finally:
                await conn.close()
            return
        except Exception:
            continue
    print(f"[db] Could not verify database '{target_db}' — assuming it already exists.")


async def init_pool():
    global _pool
    if _pool is None:
        ssl_value = _build_ssl_context()
        await _ensure_database_exists(ssl_value)
        connect_kwargs: dict = dict(
            host=settings.DB_HOST,
            port=settings.DB_PORT,
            user=settings.DB_USER,
            password=settings.DB_PASSWORD,
            database=settings.DB_NAME,
            min_size=1,
            max_size=10,
        )
        if ssl_value is not None:
            connect_kwargs["ssl"] = ssl_value
        _pool = await asyncpg.create_pool(**connect_kwargs)
        print(f"[db] PostgreSQL pool connected [host={settings.DB_HOST} db={settings.DB_NAME} ssl={settings.DB_SSLMODE}]")


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("PostgreSQL pool not initialized — call init_pool() first.")
    return _pool


async def ensure_pool() -> asyncpg.Pool:
    if _pool is None:
        await init_pool()
    return _pool


async def close_pool():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        print("[db] PostgreSQL pool closed.")


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
