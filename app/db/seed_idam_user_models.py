"""
Give EXISTING projects the IDAM module + "User" domain model that new projects get
automatically (see app/services/idam_user_model.py).

    python -m app.db.seed_idam_user_models --dry-run    # just list what would happen
    python -m app.db.seed_idam_user_models              # create them

A project that already has a different domain model called "User" is skipped
(nothing is touched). Safe to re-run.
"""
import asyncio
import sys

from ..core.database import ensure_pool, fetch
from ..services import idam_user_model


async def main(dry_run: bool) -> None:
    await ensure_pool()
    projects = await fetch("SELECT id, name FROM projects ORDER BY id")
    for p in projects:
        if dry_run:
            print(f'project {p["id"]} "{p["name"]}": would ensure IDAM > User')
            continue
        r = await idam_user_model.ensure_idam_user_model(p["id"])
        extra = r.get("reason") or r.get("table_name") or ""
        print(f'project {p["id"]} "{p["name"]}": {r["status"]} {extra}')


if __name__ == "__main__":
    asyncio.run(main("--dry-run" in sys.argv))