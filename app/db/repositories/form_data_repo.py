from ...core.config import settings

if settings.DB_BACKEND == "dynamodb":
    from .dynamo.form_data_repo import (
        save,
        get_by_id,
        list_all,
        filter_by_name,
        filter_by_name_prefix,
        filter_by_created_after,
        filter_by_field_id,
        filter_by_field_value,
        filter_by_field_type,
    )
else:
    from .postgres.form_data_repo import (
        save,
        get_by_id,
        list_all,
        filter_by_name,
        filter_by_name_prefix,
        filter_by_created_after,
        filter_by_field_id,
        filter_by_field_value,
        filter_by_field_type,
    )

__all__ = [
    "save",
    "get_by_id",
    "list_all",
    "filter_by_name",
    "filter_by_name_prefix",
    "filter_by_created_after",
    "filter_by_field_id",
    "filter_by_field_value",
    "filter_by_field_type",
]
