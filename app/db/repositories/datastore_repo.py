from ...core.config import settings

if settings.DB_BACKEND == "dynamodb":
    from .dynamo.datastore_repo import (
        save_schema,
        get_schema,
        list_schemas,
        create_table_from_schema,
        insert_row,
        list_rows,
        get_row,
    )
else:
    from .postgres.datastore_repo import (
        save_schema,
        get_schema,
        list_schemas,
        create_table_from_schema,
        insert_row,
        list_rows,
        get_row,
    )

__all__ = [
    "save_schema",
    "get_schema",
    "list_schemas",
    "create_table_from_schema",
    "insert_row",
    "list_rows",
    "get_row",
]
