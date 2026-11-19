"""
Move the physical tables of EXISTING project domain models out of "public"
into their project's own PostgreSQL schema (new domain models already go
there automatically).

Usage:
    python -m app.db.migrate_domains_to_project_schemas --dry-run   # just print
    python -m app.db.migrate_domains_to_project_schemas             # do it

Two phases:
  1. physical tables still in "public" move into their project's schema
     (ALTER TABLE ... SET SCHEMA; data, ids and indexes move with them);
  2. each project's domain-model rows move out of the global
     public.datastore_schemas into <project_schema>.datastore_schemas, and the
     public.datastore_registry directory is updated so the API keeps finding them.

Unassigned domain models (no project) stay in "public". Safe to re-run.
"""
import asyncio
import sys

from ..core.database import ensure_pool, fetch, fetchrow, execute
from .repositories.postgres import datastore_repo as repo


async def migrate(dry_run: bool) -> None:
    await ensure_pool()
    await repo._ensure_datastore_schemas_table()
    await repo._ensure_registry()
    if not dry_run:      # every existing project gets its own (possibly empty) datastore_schemas
        for p in await fetch("SELECT id FROM projects"):
            print(f"project {p['id']}: datastore_schemas in schema '{await repo.ensure_project_meta(p['id'])}'")
    rows = await fetch(
        "SELECT table_name, COALESCE(domain_name, table_name) AS physical, project_id FROM datastore_schemas "
        "WHERE project_id IS NOT NULL AND pg_schema = 'public' ORDER BY project_id, table_name"
    )
    if not rows:
        print("No physical tables to move.")
        await _move_meta_rows(dry_run)
        return
    names: dict[int, str] = {}      # project_id -> schema it will get (dry-run preview)
    taken: set[str] = set()
    for r in rows:
        key, name, pid = r["table_name"], r["physical"], r["project_id"]
        if dry_run:
            if pid not in names:
                proj = await fetchrow("SELECT name, pg_schema FROM projects WHERE id = $1", pid)
                if not proj:
                    names[pid] = "(project not found - will be skipped)"
                elif proj["pg_schema"]:
                    names[pid] = proj["pg_schema"]
                else:
                    cand = await repo._pick_schema_name(pid, proj["name"])
                    if cand in taken:          # two projects with the same name
                        cand = f"{cand}_{pid}"
                    names[pid] = cand
                taken.add(names[pid])
                print(f'--- project {pid} "{proj["name"] if proj else "?"}" -> schema {names[pid]}')
            print(f'    public."{name}" -> {names[pid]}."{name}"')
            continue
        target = await repo.ensure_project_schema(pid)
        if target == "public":
            print(f"skip {name}: project {pid} not found")
            continue
        await execute(f'ALTER TABLE IF EXISTS "public"."{name}" SET SCHEMA "{target}"')
        await execute("UPDATE datastore_schemas SET pg_schema = $1 WHERE table_name = $2", target, key)
        print(f"moved {name} -> {target}.\"{name}\"")
    await _move_meta_rows(dry_run)


async def _move_meta_rows(dry_run: bool) -> None:
    """Phase 2: public.datastore_schemas rows of project models -> <project schema>.datastore_schemas."""
    await repo.backfill_registry()      # pick up rows written to public after the registry was created
    rows = await fetch(
        "SELECT r.table_name, r.pg_schema, r.project_id FROM datastore_registry r "
        "WHERE r.meta_schema = 'public' AND r.pg_schema <> 'public' ORDER BY r.pg_schema, r.table_name"
    )
    if not rows:
        print("No datastore_schemas rows to move.")
        return
    for r in rows:
        if dry_run:
            print(f'    datastore_schemas row "{r["table_name"]}" -> {r["pg_schema"]}.datastore_schemas')
            continue
        moved = await repo.move_meta_row(r["table_name"], r["pg_schema"])
        print(f'{"moved" if moved else "skip "} datastore_schemas row "{r["table_name"]}" -> {r["pg_schema"]}.datastore_schemas')


if __name__ == "__main__":
    asyncio.run(migrate("--dry-run" in sys.argv))