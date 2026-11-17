"""PostgreSQL repository for idam."user" (schema: app/idam/schema/idam.sql)."""
from datetime import datetime, timezone

from ...core.database import fetch, fetchrow
from ..domain.user import IdamUser

_TABLE = 'idam."user"'


def _naive_utc(v):
    """Columns are TIMESTAMP (no tz): asyncpg rejects aware datetimes."""
    if isinstance(v, str):
        v = datetime.fromisoformat(v)
    if v is not None and v.tzinfo is not None:
        v = v.astimezone(timezone.utc).replace(tzinfo=None)
    return v


def _int_or_none(v):
    return int(v) if v not in (None, "") else None


async def get_by_id(user_id) -> IdamUser | None:
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return None
    row = await fetchrow(f"SELECT * FROM {_TABLE} WHERE id = $1", uid)
    return IdamUser.from_row(row) if row else None


async def get_by_email(email) -> IdamUser | None:
    row = await fetchrow(f"SELECT * FROM {_TABLE} WHERE LOWER(email) = LOWER($1)", email)
    return IdamUser.from_row(row) if row else None


async def get_by_username(username) -> IdamUser | None:
    row = await fetchrow(f"SELECT * FROM {_TABLE} WHERE username = $1", username)
    return IdamUser.from_row(row) if row else None


async def list_users(org_id=None) -> list[IdamUser]:
    """org_id=None -> every organization (product admin)."""
    sql, args = f"SELECT * FROM {_TABLE}", []
    if org_id is not None:
        sql += " WHERE organization_id = $1"
        args.append(int(org_id))
    sql += " ORDER BY LOWER(COALESCE(user_name, username))"
    return [IdamUser.from_row(r) for r in await fetch(sql, *args)]


async def create(username, email, password, is_superuser=False, is_staff=False,
                 is_active=True, date_joined=None, user_name=None, organization_id=None,
                 usergroup_id=None, profile_pic=None, is_lead=False, ref_id=None,
                 id=None) -> IdamUser:
    """Insert a user. Pass `id` to keep the same id as the legacy auth_user row."""
    cols = {
        "username": username, "email": email.strip().lower(), "password": password,
        "is_superuser": bool(is_superuser), "is_staff": bool(is_staff),
        "is_active": bool(is_active),
        "date_joined": _naive_utc(date_joined) or datetime.utcnow(),
        "user_name": user_name, "profile_pic": profile_pic, "is_lead": bool(is_lead),
        "organization_id": _int_or_none(organization_id),
        "usergroup_id": _int_or_none(usergroup_id), "ref_id": ref_id,
    }
    if id is not None:
        cols = {"id": int(id), **cols}
    names = ", ".join(cols)
    marks = ", ".join(f"${i}" for i in range(1, len(cols) + 1))
    row = await fetchrow(
        f"INSERT INTO {_TABLE} ({names}) VALUES ({marks}) RETURNING *", *cols.values()
    )
    if id is not None:
        # Explicit ids don't advance the identity sequence; keep it ahead of MAX(id)
        # so later auto-id inserts can't collide with mirrored legacy ids.
        await fetchrow(
            f"SELECT setval(pg_get_serial_sequence('{_TABLE}', 'id'), "
            f"(SELECT MAX(id) FROM {_TABLE}))"
        )
    return IdamUser.from_row(row)


async def update_password(user_id, hashed_password) -> None:
    await fetchrow(
        f"UPDATE {_TABLE} SET password = $1, updated_at = NOW() WHERE id = $2 RETURNING id",
        hashed_password, int(user_id),
    )