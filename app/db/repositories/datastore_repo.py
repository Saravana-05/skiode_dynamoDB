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


async def save_schema(table_name: str, schema: list, project_id: int | str | None = None) -> None:
    # project_id (Projects feature) is currently PostgreSQL-only.
    if _backend == "dynamodb":
        return await _repo().save_schema(table_name, schema)
    return await _repo().save_schema(table_name, schema, project_id)


async def get_schema(table_name: str) -> list | None:
    return await _repo().get_schema(table_name)


async def list_schemas(project_id: int | str | None = None) -> list[dict]:
    # project_id (Projects feature) is currently PostgreSQL-only.
    if _backend == "dynamodb":
        return await _repo().list_schemas()
    return await _repo().list_schemas(project_id)


async def create_table_from_schema(table_name: str, schema: list) -> dict:
    return await _repo().create_table_from_schema(table_name, schema)


async def insert_row(table_name: str, schema: list, row_data: dict) -> str:
    return await _repo().insert_row(table_name, schema, row_data)


async def list_rows(table_name: str) -> list[dict]:
    return await _repo().list_rows(table_name)


async def list_archived_rows(table_name: str) -> list[dict]:
    return await _repo().list_archived_rows(table_name)


async def get_row(table_name: str, record_id: str) -> dict | None:
    return await _repo().get_row(table_name, record_id)


async def update_row(table_name: str, record_id: str, row_data: dict) -> dict:
    return await _repo().update_row(table_name, record_id, row_data)


async def delete_row(table_name: str, record_id: str) -> dict:
    return await _repo().delete_row(table_name, record_id)


async def save_domain_attribute(
    domain_model_id: str,
    attribute_name: str,
    label: str | None = None,
    field_type: str | None = None,
) -> dict:
    return await _repo().save_domain_attribute(
        domain_model_id, attribute_name, label, field_type
    )


async def list_domain_attributes(domain_model_id: str) -> list[dict]:
    return await _repo().list_domain_attributes(domain_model_id)


# ── Translation helpers — linked table (attribute_translations) ───────

async def save_attribute_translation(
    domain_model_id: str,
    attribute_name: str,
    lang_code: str,
    label: str,
) -> dict:
    return await _repo().save_attribute_translation(
        domain_model_id, attribute_name, lang_code, label
    )


async def get_domain_translations(domain_model_id: str) -> dict:
    return await _repo().get_domain_translations(domain_model_id)


# ── validation_rules — registry/config data, always PostgreSQL ─────────
# Not part of the dynamodb/postgresql switch above: these are named
# validation rules (the Schema Inspector's "Create new rule" flow), not
# per-domain dynamic table data, so they always go straight to the
# PostgreSQL implementation regardless of the active _backend setting —
# there's no dynamo equivalent (mirrors how attribute_translations was
# also only ever added to the postgres repo, not the dynamo one).

async def list_validation_rules() -> list[dict]:
    from .postgres.datastore_repo import list_validation_rules as _list
    return await _list()


async def save_validation_rule(tag: str, rule: dict) -> dict:
    from .postgres.datastore_repo import save_validation_rule as _save
    return await _save(tag, rule)



__all__ = [
    "get_backend",
    "set_backend",
    "save_schema",
    "get_schema",
    "list_schemas",
    "create_table_from_schema",
    "insert_row",
    "list_rows",
    "list_archived_rows",
    "get_row",
    "update_row",
    "delete_row",
    "save_domain_attribute",
    "list_domain_attributes",
    "save_attribute_translation",
    "get_domain_translations",
    "list_validation_rules",
    "save_validation_rule",
]