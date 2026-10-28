"""
PostgreSQL repo for domain-level ABAC rules.

Table: domain_abac_rules  (created by you — columns used here)
    id, project_id, module_id, domain_name, name, effect,
    roles TEXT[], actions TEXT[], fields TEXT[], conditions JSONB,
    created_at, updated_at

Rules for one domain are always saved as a whole list ("replace"), inside
one transaction, so a failed save never leaves a half-written rule set.
"""
import json
from datetime import datetime, timedelta, timezone

from ....core.database import ensure_pool, fetch


def _load_conditions(value) -> list:
    """asyncpg returns JSONB as a str unless a codec is registered; handle both."""
    if value is None:
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return []
    return value if isinstance(value, list) else []


def _to_wire(r) -> dict:
    """Shape the frontend's DomainPermissionRule expects."""
    return {
        "id":         str(r["id"]),
        "name":       r["name"],
        "effect":     r["effect"],
        "roles":      list(r["roles"] or []),
        "actions":    list(r["actions"] or []),
        "conditions": _load_conditions(r["conditions"]),
    }


async def list_rules(domain_name: str) -> list[dict]:
    rows = await fetch(
        """
        SELECT id, name, effect, roles, actions, conditions
          FROM domain_abac_rules
         WHERE domain_name = $1
         ORDER BY created_at, id
        """,
        domain_name,
    )
    return [_to_wire(r) for r in rows]


async def list_all_rules() -> list[dict]:
    """Every rule of every domain (used to build a user's effective permissions)."""
    rows = await fetch(
        """
        SELECT id, domain_name, name, effect, roles, actions, conditions
          FROM domain_abac_rules
         ORDER BY domain_name, created_at, id
        """
    )
    return [{**_to_wire(r), "domain_name": r["domain_name"]} for r in rows]


async def replace_rules(
    domain_name: str,
    rules: list[dict],
    project_id: str | None = None,
    module_id: str | None = None,
) -> list[dict]:
    """Delete the domain's rules and insert the new list atomically."""
    pool = await ensure_pool()
    base = datetime.now(timezone.utc)
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM domain_abac_rules WHERE domain_name = $1", domain_name)
            for i, r in enumerate(rules):
                # Spread created_at by a microsecond each so the list keeps its order.
                ts = base + timedelta(microseconds=i)
                await conn.execute(
                    """
                    INSERT INTO domain_abac_rules
                        (project_id, module_id, domain_name, name, effect,
                         roles, actions, conditions, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9, $9)
                    """,
                    project_id, module_id, domain_name,
                    r["name"], r["effect"], r["roles"], r["actions"],
                    json.dumps(r.get("conditions") or []), ts,
                )
    return await list_rules(domain_name)


async def delete_rules(domain_name: str) -> int:
    pool = await ensure_pool()
    async with pool.acquire() as conn:
        res = await conn.execute("DELETE FROM domain_abac_rules WHERE domain_name = $1", domain_name)
    return int(res.split()[-1])  # "DELETE n"


async def rename_domain(old_name: str, new_name: str) -> int:
    """Keep rules attached to a domain model that was renamed."""
    pool = await ensure_pool()
    async with pool.acquire() as conn:
        res = await conn.execute(
            "UPDATE domain_abac_rules SET domain_name = $2, updated_at = now() WHERE domain_name = $1",
            old_name, new_name,
        )
    return int(res.split()[-1])  # "UPDATE n"