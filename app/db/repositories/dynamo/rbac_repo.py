"""
RBAC repository — DynamoDB implementation.

Same function signatures / return shapes as postgres/rbac_repo.py.
Tables (created by app/db/init_rbac.py):

  rbac_roles             PK id
  rbac_resources         PK id
  rbac_permissions       PK id                       GSI resource-index(resource_id)
  rbac_role_permissions  PK role_id, SK permission_id GSI permission-index(permission_id)
  rbac_user_roles        PK user_id, SK role_id       GSI role-index(role_id)

RBAC data is small (tens of roles/resources), so the list_* functions use
scans; everything on the request hot path (get_user_permissions) uses keyed
queries only.
"""
import uuid
from datetime import datetime, timezone

from boto3.dynamodb.conditions import Key

from ....core.dynamodb import get_dynamodb
from ....core.config import settings
from ..utils import clean, strip_none


def _id() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _tbl(name):
    return await get_dynamodb().Table(name)


async def _scan_all(tbl, **kwargs) -> list[dict]:
    items, start = [], None
    while True:
        if start:
            kwargs["ExclusiveStartKey"] = start
        resp = await tbl.scan(**kwargs)
        items.extend(resp.get("Items", []))
        start = resp.get("LastEvaluatedKey")
        if not start:
            return [clean(i) for i in items]


async def _query_all(tbl, **kwargs) -> list[dict]:
    items, start = [], None
    while True:
        if start:
            kwargs["ExclusiveStartKey"] = start
        resp = await tbl.query(**kwargs)
        items.extend(resp.get("Items", []))
        start = resp.get("LastEvaluatedKey")
        if not start:
            return [clean(i) for i in items]


def _role(i) -> dict:
    return {"id": i["id"], "name": i["name"], "description": i.get("description"),
            "created_at": i.get("created_at")}


def _resource(i, permissions=None) -> dict:
    return {"id": i["id"], "name": i["name"], "description": i.get("description"),
            "created_at": i.get("created_at"), "permissions": permissions or []}


def _perm(i) -> dict:
    return {"id": i["id"], "resource_id": i["resource_id"], "action": i["action"],
            "description": i.get("description")}


def _by_name(items):
    return sorted(items, key=lambda x: x["name"].lower())


# ── Roles ─────────────────────────────────────────────────────────────────────

async def list_roles():
    return [_role(i) for i in _by_name(await _scan_all(await _tbl(settings.TABLE_RBAC_ROLES)))]


async def get_role(role_id):
    resp = await (await _tbl(settings.TABLE_RBAC_ROLES)).get_item(Key={"id": role_id})
    item = resp.get("Item")
    return _role(clean(item)) if item else None


async def get_role_by_name(name):
    for r in await list_roles():
        if r["name"].lower() == name.lower():
            return r
    return None


async def create_role(name, description=None):
    item = strip_none({"id": _id(), "name": name, "description": description, "created_at": _now()})
    await (await _tbl(settings.TABLE_RBAC_ROLES)).put_item(Item=item)
    return _role(item)


async def delete_role(role_id):
    rp_tbl = await _tbl(settings.TABLE_RBAC_ROLE_PERMISSIONS)
    ur_tbl = await _tbl(settings.TABLE_RBAC_USER_ROLES)
    for item in await _query_all(rp_tbl, KeyConditionExpression=Key("role_id").eq(role_id)):
        await rp_tbl.delete_item(Key={"role_id": role_id, "permission_id": item["permission_id"]})
    for item in await _query_all(ur_tbl, IndexName="role-index", KeyConditionExpression=Key("role_id").eq(role_id)):
        await ur_tbl.delete_item(Key={"user_id": item["user_id"], "role_id": role_id})
    await (await _tbl(settings.TABLE_RBAC_ROLES)).delete_item(Key={"id": role_id})


# ── Resources ─────────────────────────────────────────────────────────────────

async def list_resources():
    resources = _by_name(await _scan_all(await _tbl(settings.TABLE_RBAC_RESOURCES)))
    perms = await _scan_all(await _tbl(settings.TABLE_RBAC_PERMISSIONS))
    by_res: dict[str, list] = {}
    for p in sorted(perms, key=lambda x: x["action"]):
        by_res.setdefault(p["resource_id"], []).append(_perm(p))
    return [_resource(r, by_res.get(r["id"], [])) for r in resources]


async def get_resource(resource_id):
    resp = await (await _tbl(settings.TABLE_RBAC_RESOURCES)).get_item(Key={"id": resource_id})
    item = resp.get("Item")
    if not item:
        return None
    perms = await list_permissions(resource_id)
    return _resource(clean(item), perms)


async def get_resource_by_name(name):
    for r in _by_name(await _scan_all(await _tbl(settings.TABLE_RBAC_RESOURCES))):
        if r["name"].lower() == name.lower():
            return _resource(r)
    return None


async def create_resource(name, description=None):
    item = strip_none({"id": _id(), "name": name, "description": description, "created_at": _now()})
    await (await _tbl(settings.TABLE_RBAC_RESOURCES)).put_item(Item=item)
    return _resource(item)


async def delete_resource(resource_id):
    for p in await list_permissions(resource_id):
        await delete_permission(p["id"])
    await (await _tbl(settings.TABLE_RBAC_RESOURCES)).delete_item(Key={"id": resource_id})


# ── Permissions ───────────────────────────────────────────────────────────────

async def list_permissions(resource_id=None):
    tbl = await _tbl(settings.TABLE_RBAC_PERMISSIONS)
    if resource_id:
        items = await _query_all(tbl, IndexName="resource-index",
                                 KeyConditionExpression=Key("resource_id").eq(resource_id))
    else:
        items = await _scan_all(tbl)
    return [_perm(i) for i in sorted(items, key=lambda x: (x["resource_id"], x["action"]))]


async def get_permission(permission_id):
    resp = await (await _tbl(settings.TABLE_RBAC_PERMISSIONS)).get_item(Key={"id": permission_id})
    item = resp.get("Item")
    return _perm(clean(item)) if item else None


async def get_permission_by_key(resource_id, action):
    for p in await list_permissions(resource_id):
        if p["action"] == action:
            return p
    return None


async def create_permission(resource_id, action, description=None):
    item = strip_none({"id": _id(), "resource_id": resource_id, "action": action,
                       "description": description, "created_at": _now()})
    await (await _tbl(settings.TABLE_RBAC_PERMISSIONS)).put_item(Item=item)
    return _perm(item)


async def delete_permission(permission_id):
    rp_tbl = await _tbl(settings.TABLE_RBAC_ROLE_PERMISSIONS)
    for item in await _query_all(rp_tbl, IndexName="permission-index",
                                 KeyConditionExpression=Key("permission_id").eq(permission_id)):
        await rp_tbl.delete_item(Key={"role_id": item["role_id"], "permission_id": permission_id})
    await (await _tbl(settings.TABLE_RBAC_PERMISSIONS)).delete_item(Key={"id": permission_id})


# ── Role ↔ permission ─────────────────────────────────────────────────────────

async def get_role_permissions(role_id):
    rp_tbl = await _tbl(settings.TABLE_RBAC_ROLE_PERMISSIONS)
    links = await _query_all(rp_tbl, KeyConditionExpression=Key("role_id").eq(role_id))
    return await _expand_permissions([l["permission_id"] for l in links], with_id=True)


async def _expand_permissions(permission_ids, with_id=False) -> list[dict]:
    """permission ids → [{id?, resource_id, resource, action}] (sorted)."""
    if not permission_ids:
        return []
    perms = {p["id"]: p for p in await list_permissions()}
    res = {r["id"]: r["name"] for r in await list_resources()}
    out = []
    for pid in permission_ids:
        p = perms.get(pid)
        if not p or p["resource_id"] not in res:
            continue  # dangling link — ignore
        row = {"resource_id": p["resource_id"], "resource": res[p["resource_id"]], "action": p["action"]}
        if with_id:
            row["id"] = pid
        out.append(row)
    return sorted(out, key=lambda x: (x["resource"].lower(), x["action"]))


async def set_role_permissions(role_id, permission_ids):
    """Replace the role's permission set (diff-based so unchanged links are untouched)."""
    rp_tbl = await _tbl(settings.TABLE_RBAC_ROLE_PERMISSIONS)
    current = {l["permission_id"] for l in
               await _query_all(rp_tbl, KeyConditionExpression=Key("role_id").eq(role_id))}
    wanted = set(permission_ids)
    for pid in current - wanted:
        await rp_tbl.delete_item(Key={"role_id": role_id, "permission_id": pid})
    for pid in wanted - current:
        await rp_tbl.put_item(Item={"role_id": role_id, "permission_id": pid})


# ── User ↔ role ───────────────────────────────────────────────────────────────

async def get_user_roles(user_id):
    ur_tbl = await _tbl(settings.TABLE_RBAC_USER_ROLES)
    links = await _query_all(ur_tbl, KeyConditionExpression=Key("user_id").eq(str(user_id)))
    roles = {r["id"]: r for r in await list_roles()}
    out = [roles[l["role_id"]] for l in links if l["role_id"] in roles]
    return [{"id": r["id"], "name": r["name"], "description": r["description"]} for r in _by_name(out)]


async def set_user_roles(user_id, role_ids):
    user_id = str(user_id)
    ur_tbl = await _tbl(settings.TABLE_RBAC_USER_ROLES)
    current = {l["role_id"] for l in
               await _query_all(ur_tbl, KeyConditionExpression=Key("user_id").eq(user_id))}
    wanted = set(role_ids)
    for rid in current - wanted:
        await ur_tbl.delete_item(Key={"user_id": user_id, "role_id": rid})
    for rid in wanted - current:
        await ur_tbl.put_item(Item={"user_id": user_id, "role_id": rid, "created_at": _now()})


async def get_user_permissions(user_id):
    ur_tbl = await _tbl(settings.TABLE_RBAC_USER_ROLES)
    rp_tbl = await _tbl(settings.TABLE_RBAC_ROLE_PERMISSIONS)
    role_ids = [l["role_id"] for l in
                await _query_all(ur_tbl, KeyConditionExpression=Key("user_id").eq(str(user_id)))]
    perm_ids: set[str] = set()
    for rid in role_ids:
        for l in await _query_all(rp_tbl, KeyConditionExpression=Key("role_id").eq(rid)):
            perm_ids.add(l["permission_id"])
    rows = await _expand_permissions(sorted(perm_ids))
    return [{"resource": r["resource"], "action": r["action"]} for r in rows]


# ── Users (for the "User Roles" screen) ───────────────────────────────────────

async def list_users(org_id=None):
    users = await _scan_all(await _tbl(settings.TABLE_USERS))
    ur_items = await _scan_all(await _tbl(settings.TABLE_RBAC_USER_ROLES))
    roles = {r["id"]: r for r in await list_roles()}
    roles_by_user: dict[str, list] = {}
    for l in ur_items:
        r = roles.get(l["role_id"])
        if r:
            roles_by_user.setdefault(l["user_id"], []).append({"id": r["id"], "name": r["name"]})

    out = []
    for u in users:
        if org_id is not None and str(u.get("organization_id")) != str(org_id):
            continue
        out.append({
            "user_id": u["user_id"],
            "user_name": u.get("user_name"),
            "email": u.get("email"),
            "is_superuser": bool(u.get("is_superuser")),
            "is_active": bool(u.get("is_active", True)),
            "organization_id": str(u["organization_id"]) if u.get("organization_id") else None,
            "roles": sorted(roles_by_user.get(u["user_id"], []), key=lambda x: x["name"].lower()),
        })
    return sorted(out, key=lambda x: (x["user_name"] or x["email"] or "").lower())