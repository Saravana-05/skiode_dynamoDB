"""
RBAC repository — PostgreSQL implementation.

Tables are defined in app/db/schema/rbac.sql. Every function returns plain
dicts with string ids so the service layer is identical for DynamoDB.
"""
import uuid

from ....core.database import ensure_pool, fetch, fetchrow, execute


def _id() -> str:
    return str(uuid.uuid4())


def _ts(v):
    if v is None:
        return None
    return v.isoformat() if hasattr(v, "isoformat") else str(v)


def _role(r) -> dict:
    return {"id": r["id"], "name": r["name"], "description": r["description"],
            "created_at": _ts(r["created_at"])}


# ── Roles ─────────────────────────────────────────────────────────────────────

async def list_roles():
    rows = await fetch("SELECT * FROM rbac_roles ORDER BY LOWER(name)")
    return [_role(r) for r in rows]


async def get_role(role_id):
    r = await fetchrow("SELECT * FROM rbac_roles WHERE id = $1", role_id)
    return _role(r) if r else None


async def get_role_by_name(name):
    r = await fetchrow("SELECT * FROM rbac_roles WHERE LOWER(name) = LOWER($1)", name)
    return _role(r) if r else None


async def create_role(name, description=None):
    rid = _id()
    r = await fetchrow(
        "INSERT INTO rbac_roles (id, name, description) VALUES ($1,$2,$3) RETURNING *",
        rid, name, description,
    )
    return _role(r)


async def delete_role(role_id):
    # role_permissions / user_roles rows go with it (ON DELETE CASCADE)
    await execute("DELETE FROM rbac_roles WHERE id = $1", role_id)


# ── Resources ─────────────────────────────────────────────────────────────────

def _resource(r, permissions=None) -> dict:
    return {"id": r["id"], "name": r["name"], "description": r["description"],
            "created_at": _ts(r["created_at"]), "permissions": permissions or []}


def _perm(r) -> dict:
    return {"id": r["id"], "resource_id": r["resource_id"], "action": r["action"],
            "description": r["description"]}


async def list_resources():
    res_rows = await fetch("SELECT * FROM rbac_resources ORDER BY LOWER(name)")
    perm_rows = await fetch("SELECT * FROM rbac_permissions ORDER BY action")
    by_res: dict[str, list] = {}
    for p in perm_rows:
        by_res.setdefault(p["resource_id"], []).append(_perm(p))
    return [_resource(r, by_res.get(r["id"], [])) for r in res_rows]


async def get_resource(resource_id):
    r = await fetchrow("SELECT * FROM rbac_resources WHERE id = $1", resource_id)
    if not r:
        return None
    perms = await fetch("SELECT * FROM rbac_permissions WHERE resource_id = $1 ORDER BY action", resource_id)
    return _resource(r, [_perm(p) for p in perms])


async def get_resource_by_name(name):
    r = await fetchrow("SELECT * FROM rbac_resources WHERE LOWER(name) = LOWER($1)", name)
    return _resource(r) if r else None


async def create_resource(name, description=None):
    r = await fetchrow(
        "INSERT INTO rbac_resources (id, name, description) VALUES ($1,$2,$3) RETURNING *",
        _id(), name, description,
    )
    return _resource(r)


async def delete_resource(resource_id):
    # permissions → role_permissions cascade
    await execute("DELETE FROM rbac_resources WHERE id = $1", resource_id)


# ── Permissions ───────────────────────────────────────────────────────────────

async def list_permissions(resource_id=None):
    if resource_id:
        rows = await fetch("SELECT * FROM rbac_permissions WHERE resource_id = $1 ORDER BY action", resource_id)
    else:
        rows = await fetch("SELECT * FROM rbac_permissions ORDER BY resource_id, action")
    return [_perm(r) for r in rows]


async def get_permission(permission_id):
    r = await fetchrow("SELECT * FROM rbac_permissions WHERE id = $1", permission_id)
    return _perm(r) if r else None


async def get_permission_by_key(resource_id, action):
    r = await fetchrow(
        "SELECT * FROM rbac_permissions WHERE resource_id = $1 AND action = $2", resource_id, action,
    )
    return _perm(r) if r else None


async def create_permission(resource_id, action, description=None):
    r = await fetchrow(
        "INSERT INTO rbac_permissions (id, resource_id, action, description) VALUES ($1,$2,$3,$4) RETURNING *",
        _id(), resource_id, action, description,
    )
    return _perm(r)


async def delete_permission(permission_id):
    await execute("DELETE FROM rbac_permissions WHERE id = $1", permission_id)


# ── Role ↔ permission ─────────────────────────────────────────────────────────

async def get_role_permissions(role_id):
    rows = await fetch(
        """
        SELECT p.id, p.resource_id, p.action, r.name AS resource
        FROM rbac_role_permissions rp
        JOIN rbac_permissions p ON p.id = rp.permission_id
        JOIN rbac_resources  r ON r.id = p.resource_id
        WHERE rp.role_id = $1
        ORDER BY LOWER(r.name), p.action
        """,
        role_id,
    )
    return [dict(r) for r in rows]


async def set_role_permissions(role_id, permission_ids):
    """Replace the role's permission set atomically."""
    pool = await ensure_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM rbac_role_permissions WHERE role_id = $1", role_id)
            if permission_ids:
                await conn.executemany(
                    "INSERT INTO rbac_role_permissions (role_id, permission_id) VALUES ($1,$2) "
                    "ON CONFLICT DO NOTHING",
                    [(role_id, pid) for pid in permission_ids],
                )


# ── User ↔ role ───────────────────────────────────────────────────────────────

# project_id=None means GLOBAL assignments only. With a project_id the result is
# global roles + roles assigned inside that project.
# all_projects=True counts roles from EVERY project too (use for global resources
# that are not tied to one project, e.g. published pages, login/auth-me context).

async def get_user_roles(user_id, project_id=None, all_projects=False):
    rows = await fetch(
        """
        SELECT DISTINCT r.id, r.name, r.description
        FROM rbac_user_roles ur JOIN rbac_roles r ON r.id = ur.role_id
        WHERE ur.user_id = $1
          AND ($3::boolean OR ur.project_id IS NULL OR ur.project_id = $2)
        ORDER BY r.name
        """,
        int(user_id), int(project_id) if project_id is not None else None, bool(all_projects),
    )
    return [dict(r) for r in rows]


async def set_user_roles(user_id, role_ids, project_id=None):
    """Replace the user's roles in ONE scope (global when project_id is None)."""
    uid = int(user_id)
    pid = int(project_id) if project_id is not None else None
    pool = await ensure_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "DELETE FROM rbac_user_roles WHERE user_id = $1 AND project_id IS NOT DISTINCT FROM $2",
                uid, pid,
            )
            if role_ids:
                await conn.executemany(
                    "INSERT INTO rbac_user_roles (user_id, role_id, project_id) VALUES ($1,$2,$3) "
                    "ON CONFLICT DO NOTHING",
                    [(uid, rid, pid) for rid in role_ids],
                )


async def get_user_permissions(user_id, project_id=None, all_projects=False):
    """Effective permissions = union over the user's roles (global + that project)."""
    rows = await fetch(
        """
        SELECT DISTINCT r.name AS resource, p.action
        FROM rbac_user_roles ur
        JOIN rbac_role_permissions rp ON rp.role_id = ur.role_id
        JOIN rbac_permissions p       ON p.id = rp.permission_id
        JOIN rbac_resources  r        ON r.id = p.resource_id
        WHERE ur.user_id = $1
          AND ($3::boolean OR ur.project_id IS NULL OR ur.project_id = $2)
        ORDER BY r.name, p.action
        """,
        int(user_id), int(project_id) if project_id is not None else None, bool(all_projects),
    )
    return [{"resource": r["resource"], "action": r["action"]} for r in rows]


# ── Users (for the "User Roles" screen) — reads idam."user" ───────────────────

async def list_users(org_id=None):
    """Users with their assigned roles. org_id=None → every org (product admin)."""
    sql = """
        SELECT u.id AS user_id, COALESCE(u.user_name, u.username) AS user_name, u.email,
               u.is_superuser, u.is_active, u.organization_id
        FROM idam."user" u
    """
    args = []
    if org_id is not None:
        sql += " WHERE u.organization_id = $1"
        args.append(int(org_id))
    sql += " ORDER BY LOWER(COALESCE(u.user_name, u.username))"
    rows = await fetch(sql, *args)

    role_rows = await fetch(
        "SELECT ur.user_id, r.id, r.name FROM rbac_user_roles ur JOIN rbac_roles r ON r.id = ur.role_id "
        "WHERE ur.project_id IS NULL"
    )
    roles_by_user: dict[str, list] = {}
    for rr in role_rows:
        roles_by_user.setdefault(str(rr["user_id"]), []).append({"id": rr["id"], "name": rr["name"]})

    return [
        {
            "user_id": str(r["user_id"]),
            "user_name": r["user_name"],
            "email": r["email"],
            "is_superuser": bool(r["is_superuser"]),
            "is_active": bool(r["is_active"]),
            "organization_id": str(r["organization_id"]) if r["organization_id"] is not None else None,
            "roles": roles_by_user.get(str(r["user_id"]), []),
        }
        for r in rows
    ]