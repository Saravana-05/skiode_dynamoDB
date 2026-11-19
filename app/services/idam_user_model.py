"""
Per-project "IDAM" module with a "User" domain model that is linked to login.

When a project is created it gets:

    Project  ->  Module "IDAM"  ->  Domain model "User"
                                    (first_name, last_name, email, password)

stored like any other domain model (<project_schema>."User", with its definition
in <project_schema>.datastore_schemas).

LINK TO LOGIN
-------------
Login (auth_service.login_user) reads idam."user" and checks a bcrypt hash, then
checks project membership (idam.user_project). So saving a row in this model also
maintains that real login user:

  insert row   -> creates idam."user" (bcrypt hash, password policy enforced),
                  adds the user to the project (idam.user_project + the project's
                  member table). A duplicate e-mail is rejected (409).
  update row   -> e-mail / name / password changes are applied to the login user.
  delete row   -> the login user is deactivated (login says "User inactive").
  restore row  -> the login user is re-activated.

The domain table NEVER keeps the real password: it is replaced by MASK before the
row is written, so list/get APIs can't leak it. The only copy is the bcrypt hash
in idam."user". Sending MASK back on an update means "password unchanged".

The model is recognised by: module named "IDAM" + model named "User" + fields
"email" and "password". Everything here is PostgreSQL-only and a no-op otherwise.
"""
import re

from fastapi import HTTPException

from ..core.config import settings
from ..core.database import execute, fetchrow

MODULE_NAME = "IDAM"
MODEL_NAME = "User"
MASK = "********"

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _field(field_id: str, label: str) -> dict:
    return {
        "field_id": field_id,
        "type": "text",
        "label": label,
        "validations": [{"type": "required", "message": f"{label} is required"}],
    }


SCHEMA = [
    _field("first_name", "First Name"),
    _field("last_name", "Last Name"),
    _field("email", "Email"),
    _field("password", "Password"),
]


def _bad(msg: str, code: int = 400):
    raise HTTPException(status_code=code, detail=msg)


def _enabled() -> bool:
    return settings.DB_BACKEND == "postgresql"


# ════════════════════════════════════════════════════════════════════════
#  Creating the module + model for a project
# ════════════════════════════════════════════════════════════════════════

async def ensure_idam_user_model(project_id) -> dict:
    """Create (idempotently) the IDAM module and its User model for a project.

    Returns {"status": "created" | "exists" | "skipped", ...}. "skipped" means the
    project already has a different domain model called "User" - it is left alone.
    """
    if not _enabled():
        return {"status": "skipped", "reason": "not PostgreSQL"}
    from ..db.repositories import datastore_repo
    from ..db.repositories.postgres import module_repo

    pid = int(project_id)
    module = await module_repo.get_module_by_name(pid, MODULE_NAME)
    if not module:
        module = await module_repo.create_module(
            pid, MODULE_NAME, "Users and login for this project")

    resolved = await datastore_repo.resolve_for_save(MODEL_NAME, pid, False)
    if resolved.get("conflict"):
        return {"status": "skipped", "reason": resolved["conflict"]}
    key, dname = resolved["key"], resolved["domain_name"]

    if resolved["exists"]:
        current = await datastore_repo.get_schema(key) or {}
        if str(current.get("module_id")) != str(module["id"]):
            return {"status": "skipped", "table_name": key,
                    "reason": f"A '{MODEL_NAME}' domain model already exists in this project "
                              f"outside the {MODULE_NAME} module."}
        # ours: make sure the physical table has every column, keep edits to the definition
        await datastore_repo.create_table_from_schema(key, SCHEMA, pid, dname)
        return {"status": "exists", "table_name": key, "module_id": module["id"]}

    await datastore_repo.create_table_from_schema(key, SCHEMA, pid, dname)
    await datastore_repo.save_schema(key, SCHEMA, pid, module["id"], MODEL_NAME, dname)
    return {"status": "created", "table_name": key, "module_id": module["id"]}


# ════════════════════════════════════════════════════════════════════════
#  Is this table the project's IDAM User model?
# ════════════════════════════════════════════════════════════════════════

async def _model_info(table_name: str) -> dict | None:
    """{"project_id", "module_id"} when `table_name` is an IDAM User model, else None."""
    if not _enabled():
        return None
    from ..db.repositories import datastore_repo
    from ..db.repositories.postgres import module_repo
    info = await datastore_repo.get_schema(table_name)
    if not isinstance(info, dict) or not info.get("project_id") or not info.get("module_id"):
        return None
    if (info.get("domain_name") or "").lower() != MODEL_NAME.lower():
        return None
    if not {"email", "password"} <= {f.get("field_id") for f in info.get("schema") or []}:
        return None
    module = await module_repo.get_module(info["module_id"])
    if not module or (module["name"] or "").lower() != MODULE_NAME.lower():
        return None
    return {"project_id": info["project_id"], "module_id": info["module_id"]}


# ════════════════════════════════════════════════════════════════════════
#  helpers on idam."user"
# ════════════════════════════════════════════════════════════════════════

def _full_name(first, last, email: str) -> str:
    return (f"{(first or '').strip()} {(last or '').strip()}").strip() or email.split("@")[0]


def _clean_email(value) -> str:
    email = (value or "").strip().lower()
    if not _EMAIL_RE.match(email):
        _bad("A valid email is required")
    return email


def _check_password(pw) -> str:
    from . import rbac_service
    pw = pw or ""
    if pw in ("", MASK):
        _bad("Password is required")
    rbac_service._check_password_policy(pw)
    return pw


async def _login_user_by_email(email: str):
    from ..db.repositories import user_repo
    return await user_repo.get_by_email((email or "").strip().lower()) if email else None


async def _create_login_user(project_id, first, last, email: str, password: str) -> str:
    """idam.user + membership of the project. Returns the new user id."""
    from . import rbac_service
    from ..db.repositories.postgres import project_user_repo

    created = await rbac_service.create_user(
        {"org_id": None}, _full_name(first, last, email), email, password, False)
    uid = created["data"]["user_id"]
    try:
        await project_user_repo.add_user(project_id, uid, None)
    except Exception:
        await _discard_login_user(project_id, uid)
        raise
    return str(uid)


async def _discard_login_user(project_id, user_id) -> None:
    from ..db.repositories.postgres import project_user_repo
    try:
        await project_user_repo.remove_user(project_id, user_id)
    except Exception as exc:                                    # noqa: BLE001
        print(f"[idam-user] could not remove membership of {user_id}: {exc}")
    await execute('DELETE FROM idam."user" WHERE id = $1', int(user_id))


async def _set_login_active(table_name: str, record_id, active: bool) -> None:
    from ..db.repositories.datastore_repo import get_row
    row = await get_row(table_name, record_id)
    user = await _login_user_by_email((row or {}).get("email"))
    if user:
        await execute('UPDATE idam."user" SET is_active = $2, updated_at = NOW() WHERE id = $1',
                      int(user["user_id"]), bool(active))


# ════════════════════════════════════════════════════════════════════════
#  Hooks called by the datastore row routes
# ════════════════════════════════════════════════════════════════════════

async def before_insert(table_name: str, body: dict) -> dict | None:
    """Create the login user BEFORE the domain row is written. Masks body['password'].
    Returns a context for rollback_insert(), or None if this isn't the IDAM User model."""
    info = await _model_info(table_name)
    if not info:
        return None
    email = _clean_email(body.get("email"))
    password = _check_password(body.get("password"))
    uid = await _create_login_user(info["project_id"], body.get("first_name"),
                                   body.get("last_name"), email, password)
    body["email"] = email
    body["password"] = MASK
    return {"user_id": uid, "project_id": info["project_id"]}


async def rollback_insert(ctx: dict | None) -> None:
    """The domain insert failed after the login user was created: undo that."""
    if ctx:
        await _discard_login_user(ctx["project_id"], ctx["user_id"])


async def before_update(table_name: str, record_id, body: dict) -> dict | None:
    """Validate + prepare login changes for an update; masks body['password'].
    Pass the returned context to after_update() once the domain row is saved."""
    info = await _model_info(table_name)
    if not info:
        return None
    from ..db.repositories.datastore_repo import get_row
    from . import rbac_service

    old = await get_row(table_name, record_id) or {}
    old_email = (old.get("email") or "").strip().lower()
    login = await _login_user_by_email(old_email)

    new_email = old_email
    if "email" in body:
        new_email = _clean_email(body.get("email"))
        if new_email != old_email:
            other = await _login_user_by_email(new_email)
            if other and (not login or str(other["user_id"]) != str(login["user_id"])):
                _bad(f"A login with email '{new_email}' already exists", 409)
        body["email"] = new_email

    first = body.get("first_name", old.get("first_name"))
    last = body.get("last_name", old.get("last_name"))

    new_password = None
    if "password" in body:
        pw = body.get("password")
        if pw not in (None, "", MASK):
            rbac_service._check_password_policy(pw)
            new_password = pw
        body["password"] = MASK          # the real one never reaches the domain table

    return {"project_id": info["project_id"], "user_id": str(login["user_id"]) if login else None,
            "email": new_email, "first": first, "last": last, "password": new_password}


async def after_update(ctx: dict | None) -> None:
    if not ctx:
        return
    from ..utils.password import hash_password
    if ctx["user_id"]:
        sets, args = ["email = $2", "user_name = $3", "updated_at = NOW()"], [
            int(ctx["user_id"]), ctx["email"], _full_name(ctx["first"], ctx["last"], ctx["email"])]
        if ctx["password"]:
            args.append(hash_password(ctx["password"]))
            sets.append(f"password = ${len(args)}")
        await execute(f'UPDATE idam."user" SET {", ".join(sets)} WHERE id = $1', *args)
    elif ctx["password"] and ctx["email"]:
        # a row that had no login yet (e.g. created before this feature): give it one now
        await _create_login_user(ctx["project_id"], ctx["first"], ctx["last"],
                                 ctx["email"], ctx["password"])


async def after_delete(table_name: str, record_id) -> None:
    """Row archived -> the login user can no longer sign in."""
    if await _model_info(table_name):
        await _set_login_active(table_name, record_id, False)


async def after_restore(table_name: str, record_id) -> None:
    if await _model_info(table_name):
        await _set_login_active(table_name, record_id, True)