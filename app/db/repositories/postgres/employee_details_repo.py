"""
PostgreSQL implementation of employee_details repo.
Each field is a separate column — same shape as DynamoDB version.
"""
import uuid
from datetime import datetime, timezone
from ....core.database import execute, fetch, fetchrow


def _row(row) -> dict | None:
    return dict(row) if row else None


# ── Write ──────────────────────────────────────────────────────

async def save(form_name: str, fields: list, event_log_id: str) -> str:
    record_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    data = {f["field_id"]: f["value"] for f in fields if "field_id" in f and "value" in f}

    await execute(
        """
        INSERT INTO employee_details
            (id, form_name, event_log_id,
             employee_name, employee_age, employee_salary,
             employee_dept, employee_experience, employee_region,
             created_at)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
        """,
        record_id,
        form_name,
        event_log_id,
        data.get("employee_name"),
        data.get("employee_age"),
        data.get("employee_salary"),
        data.get("employee_dept"),
        data.get("employee_experience"),
        data.get("employee_region"),
        now,
    )
    return record_id


# ── Read all ───────────────────────────────────────────────────

async def list_all() -> list[dict]:
    rows = await fetch("SELECT * FROM employee_details ORDER BY created_at DESC")
    return [_row(r) for r in rows]


# ── Read by ID ─────────────────────────────────────────────────

async def get_by_id(record_id: str) -> dict | None:
    row = await fetchrow("SELECT * FROM employee_details WHERE id = $1", record_id)
    return _row(row)


# ── Filter by department (indexed) ─────────────────────────────

async def filter_by_dept(dept: str) -> list[dict]:
    rows = await fetch(
        "SELECT * FROM employee_details WHERE employee_dept = $1", dept
    )
    return [_row(r) for r in rows]


# ── Filter by region (indexed) ─────────────────────────────────

async def filter_by_region(region: str) -> list[dict]:
    rows = await fetch(
        "SELECT * FROM employee_details WHERE employee_region = $1", region
    )
    return [_row(r) for r in rows]


# ── Filter by salary range ──────────────────────────────────────

async def filter_by_salary_range(min_sal: int, max_sal: int) -> list[dict]:
    rows = await fetch(
        "SELECT * FROM employee_details WHERE employee_salary BETWEEN $1 AND $2",
        min_sal, max_sal,
    )
    return [_row(r) for r in rows]
