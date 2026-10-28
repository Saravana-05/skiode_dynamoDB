"""
Business logic for domain-level ABAC rules (who can do what on a domain model).

A rule = who (roles) + effect (allow/deny) + which fields + optional CONDITIONS.
Conditions are matched against the record (record.<field>) and, when the caller
passes them in, against the signed-in user (user.<attribute>). All conditions of
a rule must match (AND). A rule without conditions applies to every row.

Condition shapes accepted on save (both are normalised to the internal form):

  internal : {"source": "record", "attribute": "libraryName", "operator": "equals",
              "valueKind": "literal", "value": "Trichy library"}
  compact  : {"attribute": "libraryId.city", "operator": "equals",
              "value_from": "user.residenceCity"}

`attribute` may be a path through a relation ("libraryId.city"): the first part is
a foreign-key field on the row, the rest is read from the related record. Resolving
a path needs a `relation_loader` (see filter_rows).
"""
import uuid
from typing import Awaitable, Callable

from ..db.repositories.postgres import abac_repo

_EFFECTS = {"allow", "deny"}
_ACTIONS = ["read", "create", "update", "delete"]
_DEFAULT_ACTIONS = ["read"]          # used when a rule lists no actions
_OPERATORS = {"equals", "notEquals", "in", "notIn", "contains", "greaterThan", "lessThan"}
_SOURCES = {"user", "record"}
_VALUE_KINDS = {"literal", "userAttr", "recordField"}


def _unique(items) -> list[str]:
    seen, out = set(), []
    for x in items or []:
        x = str(x).strip()
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _err(code: int, message: str) -> dict:
    return {"status": "error", "code": code, "message": message}


def _clean_conditions(raw_list, rule_name: str) -> tuple[list[dict] | None, str | None]:
    """Validate/normalise the conditions of one rule (keeps them instead of dropping them)."""
    out = []
    for c in raw_list or []:
        if not isinstance(c, dict):
            continue
        attribute = str(c.get("attribute") or "").strip()
        source, kind, value = c.get("source"), c.get("valueKind"), c.get("value")

        # compact form: "value_from": "user.residenceCity" / "record.city"
        value_from = str(c.get("value_from") or "").strip()
        if value_from:
            prefix, _, rest = value_from.partition(".")
            if prefix == "user" and rest:
                kind, value = "userAttr", rest
            elif prefix == "record" and rest:
                kind, value = "recordField", rest
            else:
                return None, f"Rule '{rule_name}': value_from must look like 'user.<attribute>' or 'record.<field>'"

        value = str(value if value is not None else "").strip()
        if not attribute or not value:
            return None, f"Rule '{rule_name}': every condition needs an attribute and a value"
        out.append({
            "id": str(c.get("id") or uuid.uuid4()),
            "source": source if source in _SOURCES else "record",
            "attribute": attribute,
            "operator": c.get("operator") if c.get("operator") in _OPERATORS else "equals",
            "valueKind": kind if kind in _VALUE_KINDS else "literal",
            "value": value,
        })
    return out, None


def _clean_rule(raw: dict, index: int) -> tuple[dict | None, str | None]:
    name = (raw.get("name") or "").strip()
    if not name:
        return None, f"Rule #{index + 1}: name is required"
    if len(name) > 200:
        return None, f"Rule #{index + 1}: name is too long (max 200 characters)"

    effect = (raw.get("effect") or "").lower()
    if effect not in _EFFECTS:
        return None, f"Rule '{name}': effect must be 'allow' or 'deny'"

    requested = _unique(raw.get("actions"))
    if requested:
        actions = [a for a in requested if a in _ACTIONS]
        if not actions:
            return None, f"Rule '{name}': unknown action(s); use {', '.join(_ACTIONS)}"
    else:
        actions = list(_DEFAULT_ACTIONS)   # no actions given -> read only

    conditions, problem = _clean_conditions(raw.get("conditions"), name)
    if problem:
        return None, problem

    return {
        "name": name,
        "effect": effect,
        "roles": _unique(raw.get("roles")),    # empty = any role
        "actions": actions,
        "conditions": conditions,              # empty = applies to every row/user
    }, None


async def get_rules(domain_name: str) -> dict:
    rules = await abac_repo.list_rules(domain_name)
    return {"status": "success", "domain": domain_name, "count": len(rules), "data": rules}


async def save_rules(domain_name: str, payload: dict) -> dict:
    cleaned = []
    for i, raw in enumerate(payload.get("rules") or []):
        rule, problem = _clean_rule(raw, i)
        if problem:
            return _err(400, problem)
        cleaned.append(rule)

    rules = await abac_repo.replace_rules(
        domain_name, cleaned, payload.get("project_id"), payload.get("module_id"),
    )
    return {"status": "success", "domain": domain_name, "count": len(rules), "data": rules}


async def delete_rules(domain_name: str) -> dict:
    n = await abac_repo.delete_rules(domain_name)
    return {"status": "success", "domain": domain_name, "deleted": n}


async def rename_domain(old_name: str, new_name: str) -> int:
    return await abac_repo.rename_domain(old_name, new_name)

# ═════════════════════════════════════════════════════════════════════════════
#  Enforcement: turn saved rules into allow / deny decisions
# ═════════════════════════════════════════════════════════════════════════════

# RBAC uses view/create/edit/delete, the ABAC panel uses read/create/update/delete.
RBAC_TO_ABAC = {"view": "read", "read": "read", "create": "create",
                "edit": "update", "update": "update", "delete": "delete"}
ABAC_TO_RBAC = {"read": "view", "create": "create", "update": "edit", "delete": "delete"}


def _role_match(rule: dict, roles_lc: set[str]) -> bool:
    rule_roles = {r.lower() for r in rule.get("roles") or []}
    return not rule_roles or bool(rule_roles & roles_lc)      # empty = any role


def decide(rules: list[dict], role_names: list[str], action: str) -> str | None:
    """
    Table-level decision for one domain: "deny" | "allow" | None (no opinion).
    Deny wins. Conditions are row-level, so they are NOT evaluated here
    (see filter_rows).
    """
    a = RBAC_TO_ABAC.get((action or "").lower())
    if not a:
        return None
    roles_lc = {r.lower() for r in role_names}
    hits = [r for r in rules if a in (r.get("actions") or []) and _role_match(r, roles_lc)]
    # a deny that has conditions only blocks matching rows, not the whole action
    if any(r["effect"] == "deny" and not r.get("conditions") for r in hits):
        return "deny"
    if any(r["effect"] == "allow" for r in hits):
        return "allow"
    return None


async def decide_for(role_names: list[str], domain_name: str, action: str) -> str | None:
    return decide(await abac_repo.list_rules(domain_name), role_names, action)


async def effective_permissions(role_names: list[str]) -> tuple[list[dict], set[tuple[str, str]]]:
    """
    For /auth/me and login. Returns (grants, denies):
      grants  [{"resource": "Tasks", "action": "view"}, ...]
      denies  {("tasks", "view"), ...}  - to strip from the RBAC permissions
    """
    by_domain: dict[str, list[dict]] = {}
    for r in await abac_repo.list_all_rules():
        by_domain.setdefault(r["domain_name"], []).append(r)

    grants, denies = [], set()
    for domain, rules in by_domain.items():
        for abac_action, rbac_action in ABAC_TO_RBAC.items():
            d = decide(rules, role_names, abac_action)
            if d == "allow":
                grants.append({"resource": domain, "action": rbac_action})
            elif d == "deny":
                denies.add((domain.lower(), rbac_action))
    return grants, denies


# ═════════════════════════════════════════════════════════════════════════════
#  Row-level conditions
# ═════════════════════════════════════════════════════════════════════════════

# Loads related records for a foreign-key field, in ONE call per field:
#   loader(table_name, fk_field, ids) -> {id (as str): related record dict}
# Supply it to filter_rows to enable path attributes such as "libraryId.city".
RelationLoader = Callable[[str, str, list], Awaitable[dict]]


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _compare(op: str, left, right) -> bool:
    """left = the attribute's actual value, right = the value it is compared with."""
    if left is None:
        return op in ("notEquals", "notIn")
    ls, rs = str(left).strip(), str(right).strip()
    if op == "equals":
        return ls.lower() == rs.lower()
    if op == "notEquals":
        return ls.lower() != rs.lower()
    if op in ("in", "notIn"):
        items = {p.strip().lower() for p in rs.split(",") if p.strip()}
        return (ls.lower() in items) == (op == "in")
    if op == "contains":
        return rs.lower() in ls.lower()
    if op in ("greaterThan", "lessThan"):
        ln, rn = _num(ls), _num(rs)
        if ln is None or rn is None:
            return False
        return ln > rn if op == "greaterThan" else ln < rn
    return False


def _condition_matches(cond: dict, row: dict, user_attrs: dict) -> bool:
    source = cond.get("source", "record")
    attr = cond.get("attribute")
    left = (user_attrs or {}).get(attr) if source == "user" else row.get(attr)

    kind = cond.get("valueKind", "literal")
    value = cond.get("value")
    if kind == "userAttr":
        right = (user_attrs or {}).get(value)
    elif kind == "recordField":
        right = row.get(value)
    else:
        right = value
    if right is None:                       # the thing we compare with is unknown → no match
        return False
    return _compare(cond.get("operator", "equals"), left, right)


def _rule_matches_row(rule: dict, row: dict, user_attrs: dict) -> bool:
    """All conditions must match; no conditions = every row."""
    return all(_condition_matches(c, row, user_attrs) for c in rule.get("conditions") or [])


def _visible_mask(rules: list[dict], role_names: list[str], rows: list[dict],
                  user_attrs: dict) -> list[bool] | None:
    """
    Row-level read decision, one bool per row (None = no applicable allow rule,
    i.e. plain RBAC, keep everything):
      - A row is visible when at least one allow rule matches it (no conditions = matches all).
      - A deny rule WITH conditions hides the rows it matches.
    """
    roles_lc = {r.lower() for r in role_names}
    hits = [r for r in rules if "read" in (r.get("actions") or []) and _role_match(r, roles_lc)]
    allows = [r for r in hits if r["effect"] == "allow"]
    if not allows:
        return None
    denies = [r for r in hits if r["effect"] == "deny" and r.get("conditions")]
    return [
        any(_rule_matches_row(a, row, user_attrs) for a in allows)
        and not any(_rule_matches_row(d, row, user_attrs) for d in denies)
        for row in rows
    ]


def _paths_used(rules: list[dict], role_names: list[str]) -> set[str]:
    """Dotted record attributes ("libraryId.city") used by the rules that apply to these roles."""
    roles_lc = {r.lower() for r in role_names}
    paths = set()
    for r in rules:
        if "read" not in (r.get("actions") or []) or not _role_match(r, roles_lc):
            continue
        for c in r.get("conditions") or []:
            if c.get("source", "record") == "record" and "." in (c.get("attribute") or ""):
                paths.add(c["attribute"])
            if c.get("valueKind") == "recordField" and "." in (c.get("value") or ""):
                paths.add(c["value"])
    return paths


def _walk(record, parts: list[str]):
    for p in parts:
        if not isinstance(record, dict):
            return None
        record = record.get(p)
    return record


async def _with_resolved_paths(table_name: str, rows: list[dict], paths: set[str],
                               loader: RelationLoader | None) -> list[dict]:
    """
    Copy of the rows with each path ("libraryId.city") added as a plain key, so the
    condition matcher can read it. Without a loader, paths stay unresolved (→ no match).
    """
    if not paths or loader is None:
        return rows
    enriched = [dict(r) for r in rows]
    by_fk: dict[str, set[str]] = {}
    for path in paths:
        by_fk.setdefault(path.split(".", 1)[0], set()).add(path)

    for fk_field, field_paths in by_fk.items():
        ids = sorted({str(r[fk_field]) for r in rows if r.get(fk_field) is not None})
        related = await loader(table_name, fk_field, ids) if ids else {}
        for row in enriched:
            rec = related.get(str(row.get(fk_field))) if row.get(fk_field) is not None else None
            for path in field_paths:
                row[path] = _walk(rec, path.split(".")[1:]) if rec is not None else None
    return enriched


_SYSTEM_COLS = {"id", "created_at", "updated_at", "deleted_at", "is_deleted", "version"}


async def filter_rows(role_names: list[str], table_name: str, rows: list[dict],
                      user_attrs: dict | None = None,
                      relation_loader: RelationLoader | None = None) -> list[dict]:
    """
    Drop the rows (conditions) a role may not read.
    No applicable ABAC rule = unchanged.

    `user_attrs` (optional) are the signed-in user's properties, e.g.
    {"userId": "...", "residenceCity": "Chennai"}; needed only for conditions
    that compare with user.<attribute>.

    `relation_loader` (optional) resolves path attributes such as "libraryId.city";
    see RelationLoader. Existing callers need no change.
    """
    if not rows:
        return rows
    rules = await abac_repo.list_rules(table_name)
    if not rules:
        return rows

    # 1) rows — evaluated on the full row (plus resolved relation paths), before columns are removed
    paths = _paths_used(rules, role_names)
    evaluated = await _with_resolved_paths(table_name, rows, paths, relation_loader)
    mask = _visible_mask(rules, role_names, evaluated, user_attrs or {})
    if mask is not None:
        rows = [row for row, ok in zip(rows, mask) if ok]   # original rows, no helper keys
    return rows


# Rules no longer carry per-field restrictions, so schemas are returned unchanged.
# These stay so existing callers keep working.
async def filter_schema(role_names: list[str], table_name: str, schema: list[dict]) -> list[dict]:
    """Schema of one domain model (unchanged: rules have no field restrictions)."""
    return schema


async def filter_schemas(role_names: list[str], schemas: list[dict]) -> list[dict]:
    """Schema list (unchanged: rules have no field restrictions)."""
    return schemas