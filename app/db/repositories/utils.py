from decimal import Decimal


def clean(item: dict) -> dict:
    """Recursively convert DynamoDB Decimal types to int/float."""
    result = {}
    for k, v in item.items():
        if isinstance(v, Decimal):
            result[k] = int(v) if v == int(v) else float(v)
        elif isinstance(v, dict):
            result[k] = clean(v)
        elif isinstance(v, list):
            result[k] = [clean(i) if isinstance(i, dict) else i for i in v]
        else:
            result[k] = v
    return result


def strip_none(item: dict) -> dict:
    """Remove keys with None values (DynamoDB rejects null attribute values)."""
    return {k: v for k, v in item.items() if v is not None}
