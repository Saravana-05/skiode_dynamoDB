from typing import Any, Optional
from fastapi import APIRouter, Query
from pydantic import BaseModel

router = APIRouter(prefix="/test", tags=["Test - JSON / DB"])


# ── Pydantic models ────────────────────────────────────────────

class FieldMeta(BaseModel):
    config: dict = {}
    renderer: str = "default"


class FormField(BaseModel):
    meta: FieldMeta
    type: str
    label: str
    value: Any
    field_id: str


class SaveFormRequest(BaseModel):
    name: str = "employee_form"
    fields: list[FormField]

    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "employee_form",
                "fields": [
                    {"meta": {"config": {}, "renderer": "default"},      "type": "text",          "label": "Employee Name",       "value": "Vikram", "field_id": "employee_name"},
                    {"meta": {"config": {}, "renderer": "default"},      "type": "number",        "label": "Employee Age",        "value": 38,       "field_id": "employee_age"},
                    {"meta": {"config": {"currency": "INR", "locale": "en-IN", "style": "currency", "notation": "standard", "unitDisplay": "long", "compactDisplay": "long", "currencyDisplay": "symbol", "maximumFractionDigits": 2, "minimumFractionDigits": 2}, "renderer": "numberFormat"}, "type": "formattedText", "label": "Employee Salary", "value": 80000, "field_id": "employee_salary"},
                    {"meta": {"config": {}, "renderer": "default"},      "type": "text",          "label": "Employee Department", "value": "HR",     "field_id": "employee_dept"},
                    {"meta": {"config": {}, "renderer": "default"},      "type": "number",        "label": "Employee Experience", "value": 15,       "field_id": "employee_experience"},
                    {"meta": {"config": {}, "renderer": "default"},      "type": "text",          "label": "Region",              "value": "West",   "field_id": "employee_region"},
                ],
            }
        }
    }


# ── WRITE ──────────────────────────────────────────────────────

@router.post("/form-data", summary="Save form fields — event_log (JSON) + employee_details (columns)")
async def save_form_data(body: SaveFormRequest):
    try:
        from ..db.repositories.form_data_repo import save as save_event_log
        from ..db.repositories.employee_details_repo import save as save_employee_details

        fields = [f.model_dump() for f in body.fields]

        event_log_id        = await save_event_log(body.name, fields)
        employee_details_id = await save_employee_details(body.name, fields, event_log_id)

        return {
            "status": "success",
            "event_log_id": event_log_id,
            "employee_details_id": employee_details_id,
            "fields_saved": len(body.fields),
            "stored_in": ["event_log (JSON string)", "employee_details (separate columns)"],
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ── READ ───────────────────────────────────────────────────────

@router.get("/form-data", summary="List all event_log records")
async def list_form_data():
    try:
        from ..db.repositories.form_data_repo import list_all
        records = await list_all()
        return {"status": "success", "count": len(records), "data": records}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/form-data/{record_id}", summary="Get one event_log record by ID")
async def get_form_data(record_id: str):
    try:
        from ..db.repositories.form_data_repo import get_by_id
        record = await get_by_id(record_id)
        if not record:
            return {"status": "error", "message": "Record not found"}
        return {"status": "success", "data": record}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ── FILTER — event_log ─────────────────────────────────────────

@router.get("/form-data/filter/by-name", summary="Filter by exact form name")
async def filter_by_name(name: str = Query(..., example="employee_form")):
    try:
        from ..db.repositories.form_data_repo import filter_by_name
        results = await filter_by_name(name)
        return {"status": "success", "count": len(results), "data": results}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/form-data/filter/by-name-prefix", summary="Filter by name prefix")
async def filter_by_name_prefix(prefix: str = Query(..., example="employee")):
    try:
        from ..db.repositories.form_data_repo import filter_by_name_prefix
        results = await filter_by_name_prefix(prefix)
        return {"status": "success", "count": len(results), "data": results}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/form-data/filter/by-created-after", summary="Filter by created date")
async def filter_by_created_after(after: str = Query(..., example="2025-01-01T00:00:00")):
    try:
        from ..db.repositories.form_data_repo import filter_by_created_after
        results = await filter_by_created_after(after)
        return {"status": "success", "count": len(results), "data": results}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/form-data/filter/by-field-id", summary="Filter by field_id inside fields")
async def filter_by_field_id(field_id: str = Query(..., example="employee_dept")):
    try:
        from ..db.repositories.form_data_repo import filter_by_field_id
        results = await filter_by_field_id(field_id)
        return {"status": "success", "count": len(results), "data": results}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/form-data/filter/by-field-value", summary="Filter where field_id = value")
async def filter_by_field_value(
    field_id: str = Query(..., example="employee_dept"),
    value: str    = Query(..., example="HR"),
):
    try:
        from ..db.repositories.form_data_repo import filter_by_field_value
        results = await filter_by_field_value(field_id, value)
        return {"status": "success", "count": len(results), "data": results}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/form-data/filter/by-field-type", summary="Filter by field type")
async def filter_by_field_type(field_type: str = Query(..., example="number")):
    try:
        from ..db.repositories.form_data_repo import filter_by_field_type
        results = await filter_by_field_type(field_type)
        return {"status": "success", "count": len(results), "data": results}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ── Employee Details routes ─────────────────────────────────────

@router.get("/employee-details", summary="List all employee_details records (separate columns)")
async def list_employee_details():
    try:
        from ..db.repositories.employee_details_repo import list_all
        records = await list_all()
        return {"status": "success", "count": len(records), "data": records}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/employee-details/{record_id}", summary="Get one employee_details record by ID")
async def get_employee_detail(record_id: str):
    try:
        from ..db.repositories.employee_details_repo import get_by_id
        record = await get_by_id(record_id)
        if not record:
            return {"status": "error", "message": "Record not found"}
        return {"status": "success", "data": record}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/employee-details/filter/by-dept", summary="Filter employee_details by department")
async def filter_employee_by_dept(dept: str = Query(..., example="HR")):
    try:
        from ..db.repositories.employee_details_repo import filter_by_dept
        results = await filter_by_dept(dept)
        return {"status": "success", "count": len(results), "data": results}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/employee-details/filter/by-region", summary="Filter employee_details by region")
async def filter_employee_by_region(region: str = Query(..., example="West")):
    try:
        from ..db.repositories.employee_details_repo import filter_by_region
        results = await filter_by_region(region)
        return {"status": "success", "count": len(results), "data": results}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/employee-details/filter/by-salary", summary="Filter employee_details by salary range")
async def filter_employee_by_salary(
    min_sal: int = Query(..., example=50000),
    max_sal: int = Query(..., example=100000),
):
    try:
        from ..db.repositories.employee_details_repo import filter_by_salary_range
        results = await filter_by_salary_range(min_sal, max_sal)
        return {"status": "success", "count": len(results), "data": results}
    except Exception as e:
        return {"status": "error", "message": str(e)}
