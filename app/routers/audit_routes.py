from fastapi import APIRouter, Query
from ..utils.decorators import handle_errors

router = APIRouter(prefix="/audit", tags=["Audit"])


# ── Get all audit logs ─────────────────────────────────────────
@router.get("/logs")
@handle_errors
async def get_audit_logs(
    limit: int = Query(50, le=200),
    user_id: str = None,
):
    """
    Query audit_log table.
    Filter by user_id optionally.
    """
    from ..core.database import fetch

    conditions = []
    params = []
    i = 1

    if user_id:
        conditions.append(f"user_id = ${i}")
        params.append(user_id)
        i += 1

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(limit)

    rows = await fetch(
        f"""
        SELECT * FROM audit_log
        {where}
        ORDER BY created_at DESC
        LIMIT ${i}
        """,
        *params
    )
    return {"status": "success", "count": len(rows), "data": [dict(r) for r in rows]}


# ── Get all error logs ─────────────────────────────────────────
@router.get("/errors")
@handle_errors
async def get_error_logs(
    limit: int = Query(50, le=200),
):
    """
    Query error_log table — only shows requests with status >= 400.
    """
    from ..core.database import fetch

    rows = await fetch(
        """
        SELECT * FROM error_log
        ORDER BY created_at DESC
        LIMIT $1
        """,
        limit
    )
    return {"status": "success", "count": len(rows), "data": [dict(r) for r in rows]}


# ── Get logs by request_id ─────────────────────────────────────
@router.get("/logs/{request_id}")
@handle_errors
async def get_log_by_request_id(request_id: str):
    """
    Find a specific request by its request_id.
    Useful when frontend reports an error with X-Request-ID header.
    """
    from ..core.database import fetch
    from fastapi import HTTPException

    rows = await fetch(
        "SELECT * FROM audit_log WHERE request_id = $1",
        request_id
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Request ID not found")
    return {"status": "success", "data": dict(rows[0])}