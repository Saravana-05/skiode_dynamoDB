from typing import Any, Optional


def success_response(data: Any = None):
    return {
        "status": "success",
        "data": data if data is not None else []
    }


def error_response(message: str, status_code: int = 400, errors: Optional[list] = None):
    res = {
        "status": "error",
        "message": message,
        "status_code": status_code
    }
    if errors is not None:
        res["errors"] = errors
    return res
