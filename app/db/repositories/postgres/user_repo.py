from datetime import datetime
from ....core.database import execute, fetch, fetchrow


async def get_by_email(email):
    row = await fetchrow(
        """
        SELECT
            u.id        AS user_id,
            u.username,
            u.password,
            u.is_superuser,
            u.is_active,
            ud.user_name,
            ud.mail_id  AS email,
            ud.profile_pic,
            ud.user_profile_schema,
            ud.is_lead,
            ud.organization_id,
            ud.usergroup_id
        FROM form_generator_userdata ud
        LEFT JOIN auth_user u ON ud.user_id = u.id
        WHERE LOWER(ud.mail_id) = LOWER($1)
        """,
        email,
    )
    if not row:
        return None
    d = dict(row)
    d["user_id"] = str(d["user_id"])
    d["organization_id"] = str(d["organization_id"]) if d.get("organization_id") else None
    d["usergroup_id"] = str(d["usergroup_id"]) if d.get("usergroup_id") else None
    return d


async def get_by_user_id(user_id):
    row = await fetchrow(
        """
        SELECT u.id AS user_id, u.username, u.password, u.is_superuser, u.is_active,
               ud.user_name, ud.mail_id AS email, ud.profile_pic, ud.is_lead,
               ud.organization_id, ud.usergroup_id
        FROM auth_user u
        LEFT JOIN form_generator_userdata ud ON ud.user_id = u.id
        WHERE u.id = $1
        """,
        int(user_id),
    )
    if not row:
        return None
    d = dict(row)
    d["user_id"] = str(d["user_id"])
    return d


async def get_by_username(username):
    row = await fetchrow("SELECT id FROM auth_user WHERE username = $1", username)
    return dict(row) if row else None


async def create(username, email, password, is_superuser, is_staff, is_active,
                 date_joined, user_name, organization_id, usergroup_id=None,
                 profile_pic=None, is_lead=False):
    if isinstance(date_joined, str):
        date_joined = datetime.fromisoformat(date_joined)

    user_row = await fetchrow(
        """
        INSERT INTO auth_user (username, email, password, is_superuser, is_staff, is_active, date_joined, first_name, last_name)
        VALUES ($1,$2,$3,$4,$5,$6,$7,'','')
        RETURNING id
        """,
        username, email, password, is_superuser, is_staff, is_active, date_joined,
    )
    user_id = user_row["id"]

    await execute(
        """
        INSERT INTO form_generator_userdata (user_name, mail_id, password, is_active, organization_id, user_id)
        VALUES ($1,$2,$3,$4,$5,$6)
        """,
        user_name, email, password, is_active, int(organization_id), user_id,
    )
    return {"user_id": str(user_id), "email": email.strip().lower()}


async def update_password(user_id, hashed_password):
    await execute("UPDATE auth_user SET password=$1 WHERE id=$2", hashed_password, int(user_id))
    await execute("UPDATE form_generator_userdata SET password=$1 WHERE user_id=$2", hashed_password, int(user_id))
