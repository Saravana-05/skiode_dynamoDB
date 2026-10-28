"""
RBAC business logic.

Concepts
  resource    something protected (usually a domain model, e.g. "Employee")
  permission  one action on one resource  → ("Employee", "edit")
  role        a named set of permissions  → "Manager"
  user        holds zero or more roles; effective permissions = union

Admin bypass
  Users whose token role is PRODUCT_ADMIN or ORG_ADMIN (i.e. is_superuser)
  pass every permission check, and are the only ones allowed to call the
  /rbac admin API. That also solves bootstrapping: the first admin can set
  everything up before any role exists.
"""
import re

from fastapi import HTTPException

from ..db.repositories import rbac_repo, user_repo
from . import abac_service
from ..utils.password import hash_password

ADMIN_ROLES = ("PRODUCT_ADMIN", "ORG_ADMIN")

_ACTION_RE = re.compile(r"^[a-z][a-z0-9_]{0,49}$")


def is_admin(current_user: dict) -> bool:
    return (current_user or {}).get("role") in ADMIN_ROLES


def _bad(msg: str, code: int = 400):
    raise HTTPException(status_code=code, detail=msg)


def _clean_name(value: str | None, what: str) -> str:
    name = (value or "").strip()
    if not name:
        _bad(f"{what} name is required")
    if len(name) > 100:
        _bad(f"{what} name is too long (max 100 characters)")
    return name


def _ok(data=None, **extra):
    return {"status": "success", "data": data, **extra}


# ═════════════════════════════════════════════════════════════════════════════
#  Permission checks (used by dependencies + login)
# ═════════════════════════════════════════════════════════════════════════════

async def get_auth_context(user_id: str) -> dict:
    """Roles + effective permissions for a user (what login / /auth/me return).

    Effective permissions = RBAC role permissions + grants from the domain
    ABAC rules (Permissions tab), minus anything an ABAC rule denies.
    """
    roles = await rbac_repo.get_user_roles(user_id)
    role_names = [r["name"] for r in roles]
    permissions = list(await rbac_repo.get_user_permissions(user_id))

    try:
        grants, denies = await abac_service.effective_permissions(role_names)
    except Exception:            # ABAC table missing / DynamoDB backend: RBAC only
        grants, denies = [], set()

    permissions = [p for p in permissions
                   if (p["resource"].lower(), p["action"].lower()) not in denies]
    have = {(p["resource"].lower(), p["action"].lower()) for p in permissions}
    for g in grants:
        if (g["resource"].lower(), g["action"]) not in have:
            permissions.append(g)
            have.add((g["resource"].lower(), g["action"]))
    return {"roles": role_names, "permissions": permissions}


async def user_has_permission(current_user: dict, resource: str, action: str) -> bool:
    if is_admin(current_user):
        return True
    user_id = current_user["user_id"]

    # Domain ABAC rules first: deny wins, allow grants, no opinion -> RBAC.
    try:
        role_names = [r["name"] for r in await rbac_repo.get_user_roles(user_id)]
        decision = await abac_service.decide_for(role_names, resource, action)
    except Exception:
        decision = None
    if decision == "deny":
        return False
    if decision == "allow":
        return True

    perms = await rbac_repo.get_user_permissions(user_id)
    r, a = resource.lower(), action.lower()
    return any(p["resource"].lower() == r and p["action"].lower() == a for p in perms)


# ═════════════════════════════════════════════════════════════════════════════
#  Roles
# ═════════════════════════════════════════════════════════════════════════════

async def list_roles():
    return _ok(await rbac_repo.list_roles())


async def create_role(name: str, description: str | None):
    name = _clean_name(name, "Role")
    if await rbac_repo.get_role_by_name(name):
        _bad(f"Role '{name}' already exists", 409)
    return _ok(await rbac_repo.create_role(name, (description or "").strip() or None))


async def get_role(role_id: str):
    role = await rbac_repo.get_role(role_id)
    if not role:
        _bad("Role not found", 404)
    role["permissions"] = await rbac_repo.get_role_permissions(role_id)
    return _ok(role)


async def delete_role(role_id: str):
    if not await rbac_repo.get_role(role_id):
        _bad("Role not found", 404)
    await rbac_repo.delete_role(role_id)
    return {"status": "success", "message": "Role deleted"}


async def set_role_permissions(role_id: str, permission_ids: list[str]):
    if not await rbac_repo.get_role(role_id):
        _bad("Role not found", 404)
    ids = list(dict.fromkeys(permission_ids))  # de-dupe, keep order
    for pid in ids:
        if not await rbac_repo.get_permission(pid):
            _bad(f"Permission not found: {pid}", 400)
    await rbac_repo.set_role_permissions(role_id, ids)
    return _ok(await rbac_repo.get_role_permissions(role_id))


# ═════════════════════════════════════════════════════════════════════════════
#  Resources & permissions
# ═════════════════════════════════════════════════════════════════════════════

async def list_resources():
    return _ok(await rbac_repo.list_resources())


async def create_resource(name: str, description: str | None):
    name = _clean_name(name, "Resource")
    if await rbac_repo.get_resource_by_name(name):
        _bad(f"Resource '{name}' already exists", 409)
    return _ok(await rbac_repo.create_resource(name, (description or "").strip() or None))


async def delete_resource(resource_id: str):
    if not await rbac_repo.get_resource(resource_id):
        _bad("Resource not found", 404)
    await rbac_repo.delete_resource(resource_id)
    return {"status": "success", "message": "Resource deleted"}


async def list_permissions(resource_id: str | None):
    return _ok(await rbac_repo.list_permissions(resource_id))


async def create_permission(resource_id: str, action: str, description: str | None):
    action = (action or "").strip().lower()
    if not _ACTION_RE.match(action):
        _bad("Action must be lowercase letters/numbers/underscores, starting with a letter (e.g. 'view')")
    if not await rbac_repo.get_resource(resource_id):
        _bad("Resource not found", 404)
    # Idempotent: syncing a domain model twice must not fail or duplicate.
    existing = await rbac_repo.get_permission_by_key(resource_id, action)
    if existing:
        return _ok(existing)
    return _ok(await rbac_repo.create_permission(resource_id, action, (description or "").strip() or None))


async def delete_permission(permission_id: str):
    if not await rbac_repo.get_permission(permission_id):
        _bad("Permission not found", 404)
    await rbac_repo.delete_permission(permission_id)
    return {"status": "success", "message": "Permission deleted"}


# ═════════════════════════════════════════════════════════════════════════════
#  Users
# ═════════════════════════════════════════════════════════════════════════════

def _org_scope(caller: dict):
    """PRODUCT_ADMIN sees everything; an ORG_ADMIN only their own organization."""
    return None if caller.get("role") == "PRODUCT_ADMIN" else caller.get("org_id")


async def _assert_user_in_scope(caller: dict, user_id: str) -> dict:
    user = await user_repo.get_by_user_id(user_id)
    if not user:
        _bad("User not found", 404)
    scope = _org_scope(caller)
    if scope is not None and str(user.get("organization_id")) != str(scope):
        _bad("User not found", 404)  # don't reveal users of other organizations
    return user


async def list_users(caller: dict):
    scope = _org_scope(caller)
    if scope is None and caller.get("role") != "PRODUCT_ADMIN":
        return _ok([])  # org admin with no org: nothing to show
    return _ok(await rbac_repo.list_users(scope))


def _check_password_policy(pw: str):
    if len(pw) < 8:
        _bad("Password must be at least 8 characters")
    if not re.search(r"[A-Z]", pw):
        _bad("Password must contain an uppercase letter")
    if not re.search(r"[0-9]", pw):
        _bad("Password must contain a number")
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", pw):
        _bad("Password must contain a special character")
    if " " in pw:
        _bad("Password should not contain spaces")


async def create_user(caller: dict, user_name: str, email: str, password: str, is_superuser: bool):
    from datetime import datetime, timezone

    # Organization is optional: an org admin's new users join their org;
    # a product admin (no org) can create users with no organization.
    org_id = caller.get("org_id") or None

    user_name = _clean_name(user_name, "User")
    email = (email or "").strip().lower()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        _bad("A valid email is required")
    _check_password_policy(password or "")

    if await user_repo.get_by_email(email):
        _bad(f"User with email '{email}' already exists", 409)

    username, counter, base = email, 1, email.split("@")[0]
    while await user_repo.get_by_username(username):
        username = f"{base}{counter}"
        counter += 1

    created = await user_repo.create(
        username=username,
        email=email,
        password=hash_password(password),
        is_superuser=bool(is_superuser),
        is_staff=bool(is_superuser),
        is_active=True,
        date_joined=datetime.now(timezone.utc).isoformat(),
        user_name=user_name,
        organization_id=org_id,
    )
    return _ok({
        "user_id": created["user_id"], "user_name": user_name, "email": email,
        "is_superuser": bool(is_superuser), "roles": [],
    })


async def get_user_roles(caller: dict, user_id: str):
    await _assert_user_in_scope(caller, user_id)
    return _ok(await rbac_repo.get_user_roles(user_id))


async def set_user_roles(caller: dict, user_id: str, role_ids: list[str]):
    await _assert_user_in_scope(caller, user_id)
    ids = list(dict.fromkeys(role_ids))
    for rid in ids:
        if not await rbac_repo.get_role(rid):
            _bad(f"Role not found: {rid}", 400)
    await rbac_repo.set_user_roles(user_id, ids)
    return _ok(await rbac_repo.get_user_roles(user_id))


async def get_user_permissions(caller: dict, user_id: str):
    await _assert_user_in_scope(caller, user_id)
    return _ok(await rbac_repo.get_user_permissions(user_id))