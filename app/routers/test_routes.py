from typing import Any, Optional
from fastapi import APIRouter, Query
from pydantic import BaseModel

router = APIRouter(prefix="/test", tags=["Test - JSON / DynamoDB"])


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

@router.post("/form-data", summary="Save form fields — stores in event_log (JSON) + employee_details (columns)")
async def save_form_data(body: SaveFormRequest):
    try:
        from ..db.repositories.dynamo.form_data_repo import save as save_event_log
        from ..db.repositories.dynamo.employee_details_repo import save as save_employee_details

        fields = [f.model_dump() for f in body.fields]

        # Save to event_log (fields as JSON string)
        event_log_id = await save_event_log(body.name, fields)

        # Save to employee_details (each field as a separate column)
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

@router.get("/form-data", summary="📋 List all records (dev only)")
async def list_form_data():
    try:
        from ..db.repositories.dynamo.form_data_repo import list_all
        records = await list_all()
        return {"status": "success", "count": len(records), "data": records}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/form-data/{record_id}", summary="🔍 Get one record by ID")
async def get_form_data(record_id: str):
    try:
        from ..db.repositories.dynamo.form_data_repo import get_by_id
        record = await get_by_id(record_id)
        if not record:
            return {"status": "error", "message": "Record not found"}
        return {"status": "success", "data": record}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ── FILTER — Approach 1: GSI (fast, top-level) ─────────────────

@router.get("/form-data/filter/by-name", summary="⚡ [GSI] Filter by exact form name (fast)")
async def filter_by_name(name: str = Query(..., example="employee_form")):
    """
    Uses the 'name-index' GSI — fastest option.
    Works only on top-level attributes that have a GSI.
    """
    try:
        from ..db.repositories.dynamo.form_data_repo import filter_by_name
        results = await filter_by_name(name)
        return {"status": "success", "approach": "GSI query", "count": len(results), "data": results}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ── FILTER — Approach 2: FilterExpression (DynamoDB server-side) ──

@router.get("/form-data/filter/by-name-prefix", summary="🔎 [FilterExpression] Filter by name prefix")
async def filter_by_name_prefix(prefix: str = Query(..., example="employee")):
    """
    DynamoDB begins_with FilterExpression on 'name'.
    Scans the table but filters server-side before data is returned.
    """
    try:
        from ..db.repositories.dynamo.form_data_repo import filter_by_name_prefix
        results = await filter_by_name_prefix(prefix)
        return {"status": "success", "approach": "FilterExpression (begins_with)", "count": len(results), "data": results}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/form-data/filter/by-created-after", summary="🔎 [FilterExpression] Filter by created date")
async def filter_by_created_after(after: str = Query(..., example="2025-01-01T00:00:00")):
    """
    FilterExpression on top-level 'created_at' (ISO datetime string comparison).
    """
    try:
        from ..db.repositories.dynamo.form_data_repo import filter_by_created_after
        results = await filter_by_created_after(after)
        return {"status": "success", "approach": "FilterExpression (gte)", "count": len(results), "data": results}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ── FILTER — Approach 3: Python-side (nested List/Map values) ──

@router.get("/form-data/filter/by-field-id", summary="🐍 [Python filter] Find records containing a field_id")
async def filter_by_field_id(field_id: str = Query(..., example="employee_dept")):
    """
    Scans all records, then filters in Python.
    Required for filtering inside a nested List — DynamoDB cannot index list items.
    """
    try:
        from ..db.repositories.dynamo.form_data_repo import filter_by_field_id
        results = await filter_by_field_id(field_id)
        return {"status": "success", "approach": "Python filter (nested list)", "count": len(results), "data": results}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/form-data/filter/by-field-value", summary="🐍 [Python filter] Find records where field_id = value")
async def filter_by_field_value(
    field_id: str = Query(..., example="employee_dept"),
    value: str  = Query(..., example="HR"),
):
    """
    Scans all records, finds those where the named field has the given value.
    Works on any nested field regardless of type.
    """
    try:
        from ..db.repositories.dynamo.form_data_repo import filter_by_field_value
        results = await filter_by_field_value(field_id, value)
        return {"status": "success", "approach": "Python filter (field_id + value)", "count": len(results), "data": results}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/form-data/filter/by-field-type", summary="[Python filter] Find records by field type")
async def filter_by_field_type(field_type: str = Query(..., example="number")):
    """
    Returns all records that contain at least one field of the given type.
    e.g. type = 'number' | 'text' | 'formattedText'
    """
    try:
        from ..db.repositories.dynamo.form_data_repo import filter_by_field_type
        results = await filter_by_field_type(field_type)
        return {"status": "success", "approach": "Python filter (field type)", "count": len(results), "data": results}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ── Employee Details routes ─────────────────────────────────────

@router.get("/employee-details", summary="List all employee_details records (separate columns)")
async def list_employee_details():
    try:
        from ..db.repositories.dynamo.employee_details_repo import list_all
        records = await list_all()
        return {"status": "success", "count": len(records), "data": records}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/employee-details/{record_id}", summary="Get one employee_details record by ID")
async def get_employee_detail(record_id: str):
    try:
        from ..db.repositories.dynamo.employee_details_repo import get_by_id
        record = await get_by_id(record_id)
        if not record:
            return {"status": "error", "message": "Record not found"}
        return {"status": "success", "data": record}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/employee-details/filter/by-dept", summary="[GSI] Filter employee_details by department")
async def filter_employee_by_dept(dept: str = Query(..., example="HR")):
    try:
        from ..db.repositories.dynamo.employee_details_repo import filter_by_dept
        results = await filter_by_dept(dept)
        return {"status": "success", "count": len(results), "data": results}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/employee-details/filter/by-region", summary="[GSI] Filter employee_details by region")
async def filter_employee_by_region(region: str = Query(..., example="West")):
    try:
        from ..db.repositories.dynamo.employee_details_repo import filter_by_region
        results = await filter_by_region(region)
        return {"status": "success", "count": len(results), "data": results}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/employee-details/filter/by-salary", summary="[FilterExpression] Filter employee_details by salary range")
async def filter_employee_by_salary(
    min_sal: int = Query(..., example=50000),
    max_sal: int = Query(..., example=100000),
):
    try:
        from ..db.repositories.dynamo.employee_details_repo import filter_by_salary_range
        results = await filter_by_salary_range(min_sal, max_sal)
        return {"status": "success", "count": len(results), "data": results}
    except Exception as e:
        return {"status": "error", "message": str(e)}
