"""
Dynamic Datastore API — backed by AWS DynamoDB / PostgreSQL

Flow:
  1. POST /datastore/create              → define schema + create a real table
  2. POST /datastore/{table_name}/row    → insert a row — fields mapped from schema, stored as separate columns
  3. GET  /datastore/{table_name}/rows   → list all rows
  4. GET  /datastore/{table_name}/row/{id} → get one row
  5. GET  /datastore/schemas             → list all registered schemas
  6. GET  /datastore/schemas/{table_name} → get schema for one table

Each call to POST /create:
  - Creates a real table (DynamoDB PAY_PER_REQUEST or PostgreSQL CREATE TABLE)
  - If table already exists: schema metadata is updated, table left as-is
  - The datastore_schemas meta-table is auto-created on first use

Domain attributes + multilingual labels:
  10. POST /datastore/domain-attributes                                    → save an attribute's English label
  11. GET  /datastore/domain-attributes/{domain_model_id}                  → list attributes for a domain
  12. POST /datastore/domain-attributes/{domain}/{attribute}/translation   → save one language's label for an attribute
  13. GET  /datastore/domain-attributes/{domain}/translations              → get all translations for a domain, grouped
"""
import re
from typing import Any
from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel

from ..utils.decorators import handle_errors

router = APIRouter(prefix="/datastore", tags=["Datastore - Dynamic Tables"])


# ── Server-side field validator ────────────────────────────────

def _validate_row(schema: list[dict], row_data: dict) -> dict[str, str]:
    """
    Validate row_data against the schema's validation rules.
    Returns a dict of {field_id: error_message} for every failing field.
    Empty dict means all fields are valid.
    """
    errors: dict[str, str] = {}

    for field in schema:
        fid   = field.get("field_id", "")
        ftype = field.get("type", "text")
        label = field.get("label") or fid
        rules = field.get("validations") or []

        raw = row_data.get(fid)
        # Normalise to string for length/pattern checks
        str_val = str(raw).strip() if raw is not None else ""

        # ── built-in type checks ──────────────────────────────
        if ftype == "number" and str_val != "":
            try:
                float(str_val)
            except (ValueError, TypeError):
                errors[fid] = f"{label} must be a valid number"
                continue

        # ── schema-defined rules ──────────────────────────────
        for rule in rules:
            rtype   = rule.get("type", "")
            rvalue  = rule.get("value")
            rmsg    = rule.get("message") or ""

            if rtype == "required":
                if str_val == "":
                    errors[fid] = rmsg or f"{label} is required"
                    break

            elif rtype == "minLength":
                if str_val and len(str_val) < int(rvalue):
                    errors[fid] = rmsg or f"{label} must be at least {rvalue} characters"
                    break

            elif rtype == "maxLength":
                if len(str_val) > int(rvalue):
                    errors[fid] = rmsg or f"{label} must be at most {rvalue} characters"
                    break

            elif rtype == "min":
                try:
                    if str_val and float(str_val) < float(rvalue):
                        errors[fid] = rmsg or f"{label} must be at least {rvalue}"
                        break
                except (ValueError, TypeError):
                    pass

            elif rtype == "max":
                try:
                    if str_val and float(str_val) > float(rvalue):
                        errors[fid] = rmsg or f"{label} must be at most {rvalue}"
                        break
                except (ValueError, TypeError):
                    pass

            elif rtype == "pattern":
                try:
                    if str_val and not re.fullmatch(str(rvalue), str_val):
                        errors[fid] = rmsg or f"{label} format is invalid"
                        break
                except re.error:
                    pass  # ignore malformed regex

    return errors


# ── Pydantic models ────────────────────────────────────────────

class SchemaField(BaseModel):
    field_id: str
    type: str               # text | number | formattedText | boolean | date
    label: str
    value: Any = None       # optional default value

    model_config = {"extra": "allow"}


class CreateTableRequest(BaseModel):
    table_name: str
    schema: list[SchemaField]

    model_config = {
        "json_schema_extra": {
            "example": {
                "table_name": "my_employees",
                "schema": [
                    {"field_id": "employee_name",   "type": "text",   "label": "Employee Name"},
                    {"field_id": "employee_age",    "type": "number", "label": "Employee Age"},
                    {"field_id": "employee_dept",   "type": "text",   "label": "Department"},
                    {"field_id": "employee_salary", "type": "number", "label": "Salary"},
                    {"field_id": "employee_region", "type": "text",   "label": "Region"},
                ]
            }
        }
    }


class DomainAttributeRequest(BaseModel):
    domain_model_id: str
    attribute_name: str
    label: str | None = None
    field_type: str | None = None


class AttributeTranslationRequest(BaseModel):
    lang_code: str   # 'en' | 'ta' | 'ar'
    label: str


# ── Helper: safely extract schema list from repo result ────────

def _extract_schema_list(schema_result: Any) -> list[dict]:
    """
    get_schema() returns {"schema": [...], "db_backend": "..."}
    This helper safely extracts just the list regardless of shape.
    """
    if schema_result is None:
        return []
    if isinstance(schema_result, list):
        return schema_result
    if isinstance(schema_result, dict):
        inner = schema_result.get("schema", [])
        if isinstance(inner, list):
            return inner
        if isinstance(inner, str):
            import json
            try:
                return json.loads(inner)
            except Exception:
                return []
    return []


# ── 1. Create table from schema ────────────────────────────────

@router.post("/create", summary="Create a database table from a JSON schema (DynamoDB or PostgreSQL)")
@handle_errors
async def create_table(body: CreateTableRequest, request: Request):
    from ..db.repositories.datastore_repo import create_table_from_schema, save_schema
    from ..core.config import settings

    schema = [f.model_dump() for f in body.schema]
    is_dynamo = settings.DB_BACKEND == "dynamodb"

    # 1. Create / update the physical table
    result = await create_table_from_schema(body.table_name, schema)

    # 2. Save / update schema metadata
    await save_schema(body.table_name, schema)

    action = "created" if result["created"] else "already existed"

    # Build backend-specific fields for the response
    if is_dynamo:
        backend_info = {"aws_region": settings.AWS_REGION}
        location_str = f"in AWS DynamoDB region {settings.AWS_REGION}"
    else:
        backend_info = {"pg_host": settings.DB_HOST, "pg_db": settings.DB_NAME}
        location_str = f"in PostgreSQL ({settings.DB_HOST}/{settings.DB_NAME})"

    return {
        "status":        "success",
        "table_name":    body.table_name,
        "table_created": result["created"],
        "action":        action,
        "db_backend":    settings.DB_BACKEND,
        **backend_info,
        "columns": [
            {"field_id": f["field_id"], "label": f["label"], "type": f["type"]}
            for f in schema
        ],
        "total_fields": len(schema),
        "message": (
            f"Table '{body.table_name}' {action} {location_str} "
            f"with {len(schema)} field(s). Primary key: id."
        ),
    }


# ── 2. Insert a row ────────────────────────────────────────────

@router.post("/{table_name}/row", summary="Insert a row — each field stored as a separate column")
@handle_errors
async def insert_row(table_name: str, request: Request, body: dict[str, Any] = Body(...)):
    from ..db.repositories.datastore_repo import get_schema, insert_row as _insert

    schema_result = await get_schema(table_name)
    if not schema_result:
        raise HTTPException(
            status_code=404,
            detail=f"No schema found for table '{table_name}'. Create it first via POST /datastore/create"
        )

    schema = _extract_schema_list(schema_result)
    if not schema:
        raise HTTPException(
            status_code=404,
            detail=f"Schema for '{table_name}' is empty or unreadable."
        )

    # ── Server-side validation ────────────────────────────
    validation_errors = _validate_row(schema, body)
    if validation_errors:
        raise HTTPException(
            status_code=422,
            detail={"message": "Validation failed", "errors": validation_errors}
        )

    # Show the mapping: schema field → input value → stored type
    mapping = []
    for field in schema:
        fid   = field["field_id"]
        ftype = field.get("type", "text")
        val   = body.get(fid)
        mapping.append({
            "field_id":       fid,
            "label":          field.get("label"),
            "schema_type":    ftype,
            "value_received": val,
            "stored_as":      "Number (N)" if ftype == "number" else
                              "Boolean (BOOL)" if ftype == "boolean" else
                              "String (S)",
        })

    record_id = await _insert(table_name, schema, body)

    return {
        "status":        "success",
        "table_name":    table_name,
        "record_id":     record_id,
        "field_mapping": mapping,
    }


# ── 3. List all rows ───────────────────────────────────────────

@router.get("/{table_name}/rows", summary="List all rows in a dynamic table")
@handle_errors
async def list_rows(table_name: str, request: Request):
    from ..db.repositories.datastore_repo import list_rows as _list
    rows = await _list(table_name)
    return {"status": "success", "table_name": table_name, "count": len(rows), "data": rows}


# ── 4. Get one row ─────────────────────────────────────────────

@router.get("/{table_name}/row/{record_id}", summary="Get one row by ID")
@handle_errors
async def get_row(table_name: str, record_id: str, request: Request):
    from ..db.repositories.datastore_repo import get_row as _get
    row = await _get(table_name, record_id)
    if not row:
        raise HTTPException(status_code=404, detail="Row not found")
    return {"status": "success", "table_name": table_name, "data": row}


# ── Config: get / switch active DB backend ────────────────────

@router.get("/config", summary="Get the active DB backend")
@handle_errors
async def get_config(request: Request):
    from ..db.repositories.datastore_repo import get_backend
    return {"status": "success", "db_backend": get_backend()}


@router.post("/config", summary="Switch the active DB backend (dynamodb | postgresql)")
@handle_errors
async def update_config(request: Request, body: dict[str, Any] = Body(...)):
    backend = body.get("db_backend", "")
    if backend not in ("dynamodb", "postgresql"):
        raise HTTPException(
            status_code=400,
            detail="db_backend must be 'dynamodb' or 'postgresql'"
        )
    from ..db.repositories.datastore_repo import set_backend
    set_backend(backend)
    return {"status": "success", "db_backend": backend}


# ── 5. List all schemas ────────────────────────────────────────

@router.get("/schemas", summary="List all registered schemas")
@handle_errors
async def list_schemas(request: Request):
    from ..db.repositories.datastore_repo import list_schemas as _list
    schemas = await _list()
    return {"status": "success", "count": len(schemas), "schemas": schemas}


# ── 6. Get schema for one table ────────────────────────────────

@router.get("/schemas/{table_name}", summary="Get schema definition for a table")
@handle_errors
async def get_schema_route(table_name: str, request: Request):
    from ..db.repositories.datastore_repo import get_schema as _get
    schema_result = await _get(table_name)
    if not schema_result:
        raise HTTPException(
            status_code=404,
            detail=f"Schema not found for '{table_name}'"
        )

    schema_list = _extract_schema_list(schema_result)
    db_backend  = schema_result.get("db_backend", "postgresql") if isinstance(schema_result, dict) else "postgresql"

    return {
        "status":     "success",
        "table_name": table_name,
        "schema":     schema_list,
        "db_backend": db_backend,
    }


# ── 7. Update a row ────────────────────────────────────────────

@router.put("/{table_name}/row/{record_id}", summary="Update a row by ID")
@handle_errors
async def update_row(table_name: str, record_id: str, request: Request, body: dict[str, Any] = Body(...)):
    from ..db.repositories.datastore_repo import update_row as _update
    result = await _update(table_name, record_id, body)
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("message", "Update failed"))
    return {"status": "success", "record_id": record_id}


# ── 8. Delete a row ────────────────────────────────────────────

@router.delete("/{table_name}/row/{record_id}", summary="Delete a row by ID")
@handle_errors
async def delete_row(table_name: str, record_id: str, request: Request):
    from ..db.repositories.datastore_repo import delete_row as _delete
    result = await _delete(table_name, record_id)
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("message", "Delete failed"))
    return {"status": "success", "record_id": record_id}


# ── 9. List archived rows ──────────────────────────────────────

@router.get("/{table_name}/archived", summary="List soft-deleted (archived) rows")
@handle_errors
async def list_archived_rows(table_name: str, request: Request):
    from ..db.repositories.datastore_repo import list_archived_rows as _list_archived
    rows = await _list_archived(table_name)
    return {"status": "success", "table_name": table_name, "count": len(rows), "data": rows}


# ── 10. Save domain attribute ──────────────────────────────────

@router.post("/domain-attributes", summary="Save an attribute (field) belonging to a domain model")
@handle_errors
async def save_domain_attribute(body: DomainAttributeRequest, request: Request):
    from ..db.repositories.datastore_repo import save_domain_attribute as _save
    result = await _save(body.domain_model_id, body.attribute_name, body.label, body.field_type)
    return result


# ── 11. List attributes for a domain ──────────────────────────

@router.get("/domain-attributes/{domain_model_id}", summary="List all attributes for a domain model")
@handle_errors
async def list_domain_attributes(domain_model_id: str, request: Request):
    from ..db.repositories.datastore_repo import list_domain_attributes as _list
    attributes = await _list(domain_model_id)
    return {
        "status":          "success",
        "domain_model_id": domain_model_id,
        "count":           len(attributes),
        "data":            attributes,
    }


# ── 12. Save one language's label for one attribute ───────────

@router.post(
    "/domain-attributes/{domain_model_id}/{attribute_name}/translation",
    summary="Save one language's translated label for an attribute",
)
@handle_errors
async def save_attribute_translation(
    domain_model_id: str,
    attribute_name: str,
    body: AttributeTranslationRequest,
    request: Request,
):
    """
    Body:
        { "lang_code": "ta", "label": "கிளினிக் பெயர்" }

    Upserts ONE row in attribute_translations (linked via FK to the
    domain_attributes row for this domain + attribute). The attribute
    must already exist (saved via POST /domain-attributes) before its
    translations can be saved.
    """
    from ..db.repositories.datastore_repo import save_attribute_translation as _save

    if body.lang_code not in ("en", "ta", "ar"):
        raise HTTPException(status_code=400, detail="lang_code must be 'en', 'ta', or 'ar'")
    if not body.label.strip():
        raise HTTPException(status_code=400, detail="label cannot be empty")

    result = await _save(domain_model_id, attribute_name, body.lang_code, body.label.strip())
    if result.get("status") == "error":
        raise HTTPException(status_code=404, detail=result.get("message", "Could not save translation"))
    return result


# ── 13. Get all attributes + translations for a domain, as nested JSON ─

@router.get(
    "/domain-attributes/{domain_model_id}/translations",
    summary="Get all attribute translations for a domain, grouped by attribute",
)
@handle_errors
async def get_domain_translations(domain_model_id: str, request: Request):
    """
    Returns translations grouped by attribute_name — ready for the
    frontend's resolveLabel() to consume directly:

        {
          "status": "success",
          "domain_model_id": "clinic",
          "data": {
            "clinic_name": { "en": "Clinic Name", "ta": "கிளினிக் பெயர்", "ar": "اسم العيادة" },
            "ph_no":       { "en": "Phone Number", "ta": "தொலைபேசி எண்", "ar": "رقم الهاتف" }
          }
        }
    """
    from ..db.repositories.datastore_repo import get_domain_translations as _get

    grouped = await _get(domain_model_id)
    return {
        "status":          "success",
        "domain_model_id": domain_model_id,
        "data":            grouped,
    }