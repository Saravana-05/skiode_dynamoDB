import json
from typing import Any


def to_jsonb(value: Any) -> str:
    """
    Converts Python dict/list into JSON string for PostgreSQL JSONB fields.
    - If already string → returns as-is
    - If dict/list → converts to JSON string
    """
    if value is None:
        return None

    if isinstance(value, (dict, list)):
        return json.dumps(value)

    if isinstance(value, str):
        return value

    # fallback safety
    return json.dumps(value)


def from_jsonb(value: Any) -> Any:
    """
    Parses JSON string into Python dict/list.
    - If already dict/list → returns as-is
    - If string → parses and returns object
    """
    if value is None:
        return None

    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return value

    return value


def parse_json(value: Any, default: Any):
    """
    PROCESS ENGINE(using this)
    Safely parse JSON string into Python object.
    Returns default if parsing fails or value is empty.
    """
    if value is None or value == "":
        return default

    # Already parsed (dict/list)
    if isinstance(value, (dict, list)):
        return value

    # Try parsing string
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return default

    return default
