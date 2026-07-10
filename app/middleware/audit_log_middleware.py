import json
import logging
import time
import uuid
from typing import Callable, Optional, Union

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from jose import jwt, JWTError

from ..core.config import settings

audit_logger = logging.getLogger("audit")
audit_logger.setLevel(logging.INFO)


def _extract_user_id(request: Request) -> Optional[Union[int, str]]:
    """Extract user_id from JWT bearer token."""
    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        return None
    token = auth_header.split(" ", 1)[1]
    try:
        payload = jwt.decode(
            token,
            settings.DJANGO_SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            options={"verify_exp": False},
        )
        return payload.get("user_id")
    except JWTError:
        return None


def _safe_json(data) -> Optional[str]:
    """Safely convert payload to JSON string for JSONB column."""
    if data is None:
        return None
    try:
        return json.dumps(data, default=str)
    except Exception:
        return None


# ── Save to audit_log table ────────────────────────────────────
async def _save_audit_log(entry: dict) -> None:
    """
    Saves every request to audit_log table.
    Columns: request_id, user_id, event, payload
    """
    try:
        from ..core.database import execute
        await execute(
            """
            INSERT INTO audit_log (request_id, user_id, event, payload)
            VALUES ($1, $2, $3, $4)
            """,
            entry["request_id"],
            str(entry["user_id"]) if entry["user_id"] is not None else None,
            entry.get("event"),    # route function name e.g. "get_row"
            entry.get("payload"),  # request body as JSON string
        )
    except Exception as e:
        audit_logger.error(f"Failed to save audit log to DB: {e}")


# ── Save to error_log table ────────────────────────────────────
async def _save_error_log(entry: dict) -> None:
    """
    Saves only failed requests (status >= 400) to error_log table.
    Columns: request_id, user_id, event, payload
    """
    try:
        from ..core.database import execute
        await execute(
            """
            INSERT INTO error_log (request_id, user_id, event, payload)
            VALUES ($1, $2, $3, $4)
            """,
            entry["request_id"],
            str(entry["user_id"]) if entry["user_id"] is not None else None,
            entry.get("event"),    # which route failed e.g. "insert_row"
            entry.get("payload"),  # payload that caused the error
        )
    except Exception as e:
        audit_logger.error(f"Failed to save error log to DB: {e}")


class AuditLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # ── setup ──────────────────────────────────────────────
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id  # decorator reads this
        request.state.event      = None         # filled by decorator
        request.state.payload    = None         # filled by decorator

        start        = time.perf_counter()
        status_code  = 500
        error_detail = None

        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id  # send to frontend
            return response

        except Exception as e:
            error_detail = str(e)
            status_code  = 500
            return JSONResponse(
                status_code=500,
                content={"detail": "Internal server error", "request_id": request_id}
            )

        finally:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)

            # ── read what decorator stored ─────────────────────
            event   = getattr(request.state, "event", None)
            payload = _safe_json(getattr(request.state, "payload", None))

            entry = {
                "request_id":  request_id,
                "user_id":     _extract_user_id(request),
                "event":       event,    # "get_row" | "list_rows" | "insert_row"
                "payload":     payload,  # JSON string of request body
                "status_code": status_code,
                "error":       error_detail,
            }

            # 1. write to audit.log file (always)
            audit_logger.info(json.dumps({
                **entry,
                "method":      request.method,
                "path":        request.url.path,
                "duration_ms": duration_ms,
                "client_ip":   request.client.host if request.client else None,
            }))

            # 2. save to audit_log table (every request)
            await _save_audit_log(entry)

            # 3. save to error_log table (only status >= 400)
            if status_code >= 400:
                await _save_error_log(entry)