from ...core.config import settings

if settings.DB_BACKEND == "dynamodb":
    from .dynamo.employee_details_repo import (
        save,
        list_all,
        get_by_id,
        filter_by_dept,
        filter_by_region,
        filter_by_salary_range,
    )
else:
    from .postgres.employee_details_repo import (
        save,
        list_all,
        get_by_id,
        filter_by_dept,
        filter_by_region,
        filter_by_salary_range,
    )

__all__ = [
    "save",
    "list_all",
    "get_by_id",
    "filter_by_dept",
    "filter_by_region",
    "filter_by_salary_range",
]
