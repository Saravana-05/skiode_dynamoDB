import json
import logging
from functools import wraps
from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)


def handle_errors(func):
    """
    1. Captures event name (function name) → request.state.event
    2. Captures request payload            → request.state.payload
    3. Converts exceptions to proper HTTP responses
    4. Falls back to path-based event name if request not found
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):

        # ── find Request from args OR kwargs ──────────────────
        request: Request = None

        # check kwargs first
        if "request" in kwargs:
            request = kwargs["request"]
        else:
            # check all positional args
            for a in args:
                if isinstance(a, Request):
                    request = a
                    break

        # ── set event name ─────────────────────────────────────
        if request:
            request.state.event = func.__name__  # e.g. "get_row", "list_rows"

        # ── capture payload from kwargs ────────────────────────
        if request:
            try:
                payload = {}
                for k, v in kwargs.items():
                    if k == "request":
                        continue
                    if hasattr(v, "model_dump"):
                        payload[k] = v.model_dump()  # pydantic model → dict
                    elif isinstance(v, dict):
                        payload[k] = v               # raw dict body
                    else:
                        payload[k] = str(v)          # path params, query params
                request.state.payload = payload if payload else None
            except Exception:
                request.state.payload = None

        try:
            return await func(*args, **kwargs)

        except HTTPException:
            # 404, 401, 422 → pass through as-is to middleware
            # event + payload already set on request.state above
            raise

        except ValueError as e:
            logger.error(f"[{func.__name__}] ValueError: {e}")
            raise HTTPException(status_code=400, detail=str(e))

        except Exception as e:
            logger.error(f"[{func.__name__}] Unhandled error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    return wrapper