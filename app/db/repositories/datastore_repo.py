from ...core.config import settings

# Runtime-switchable backend — starts from the env var, can be changed via API.
_backend: str = settings.DB_BACKEND


def get_backend() -> str:
    return _backend


def set_backend(backend: str) -> None:
    global _backend
    _backend = backend


def _repo():
    """Return the correct repo module for the active backend."""
    if _backend == "dynamodb":
        from .dynamo import datastore_repo as r
    else:
        from .postgres import datastore_repo as r
    return r


async def save_schema(table_name: str, schema: list) -> None:
    return await _repo().save_schema(table_name, schema)


async def get_schema(table_name: str) -> list | None:
    return await _repo().get_schema(table_name)


async def list_schemas() -> list[dict]:
    return await _repo().list_schemas()


async def create_table_from_schema(table_name: str, schema: list) -> dict:
    return await _repo().create_table_from_schema(table_name, schema)


async def insert_row(table_name: str, schema: list, row_data: dict) -> str:
    return await _repo().insert_row(table_name, schema, row_data)


async def list_rows(table_name: str) -> list[dict]:
    return await _repo().list_rows(table_name)


async def get_row(table_name: str, record_id: str) -> dict | None:
    return await _repo().get_row(table_name, record_id)


__all__ = [
    "get_backend",
    "set_backend",
    "save_schema",
    "get_schema",
    "list_schemas",
    "create_table_from_schema",
    "insert_row",
    "list_rows",
    "get_row",
]
