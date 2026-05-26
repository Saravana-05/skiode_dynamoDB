"""
Dynamic Datastore API — backed by AWS DynamoDB

Flow:
  1. POST /datastore/create              → define schema + create a real DynamoDB table
  2. POST /datastore/{table_name}/row    → insert a row — fields mapped from schema, stored as separate columns
  3. GET  /datastore/{table_name}/rows   → list all rows
  4. GET  /datastore/{table_name}/row/{id} → get one row
  5. GET  /datastore/schemas             → list all registered schemas
  6. GET  /datastore/schemas/{table_name} → get schema for one table

Each call to POST /create:
  - Creates a real AWS DynamoDB table (PAY_PER_REQUEST, id as PK)
  - Saves the full schema JSON to the datastore_schemas meta-table
  - The datastore_schemas meta-table is auto-created on first use
"""
import re
from typing import Any
from fastapi import APIRouter, Body
from pydantic import BaseModel

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


# ── 1. Create table from schema ────────────────────────────────

@router.post("/create", summary="Create a database table from a JSON schema (DynamoDB or PostgreSQL)")
async def create_table(body: CreateTableRequest):
    """
    Provide a table_name and a list of schema fields.

    Behaviour depends on DB_BACKEND setting:

    DynamoDB:
      - Creates a real AWS DynamoDB table (PAY_PER_REQUEST, id as HASH key)
      - Waits until table status == ACTIVE
      - If table already exists: schema metadata is updated, table left as-is

    PostgreSQL:
      - Runs CREATE TABLE with typed columns (VARCHAR / NUMERIC / BOOLEAN)
      - If table already exists: runs ALTER TABLE ADD COLUMN for any new fields
      - datastore_schemas meta-table is auto-created on first use

    In both cases the schema JSON is saved to datastore_schemas.
    """
    try:
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
    except TimeoutError as e:
        return {"status": "error", "message": f"Table creation timed out: {e}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ── 2. Insert a row ────────────────────────────────────────────

@router.post("/{table_name}/row", summary="Insert a row — each field stored as a separate column")
async def insert_row(table_name: str, body: dict[str, Any] = Body(...)):
    """
    Send the row data as a flat JSON object.
    Keys must match the field_id values from the schema.

    Example body for table created with employee schema:
    {
        "employee_name":   "Karthik",
        "employee_age":    28,
        "employee_dept":   "Engineering",
        "employee_salary": 72000,
        "employee_region": "South"
    }

    How it works:
    1. Loads schema from datastore_schemas table
    2. Maps each key in body → matching field_id in schema
    3. Casts value to correct DynamoDB type (text→String, number→Number)
    4. Stores each field as its own separate column — NOT as JSON
    """
    try:
        from ..db.repositories.datastore_repo import get_schema, insert_row as _insert

        schema = await get_schema(table_name)
        if not schema:
            return {
                "status": "error",
                "message": f"No schema found for table '{table_name}'. Create it first via POST /datastore/create"
            }

        # ── Server-side validation ────────────────────────────
        validation_errors = _validate_row(schema, body)
        if validation_errors:
            return {
                "status": "validation_error",
                "message": "Validation failed",
                "errors": validation_errors,   # {field_id: error_message}
            }

        # Show the mapping: schema field → input value → stored type
        mapping = []
        for field in schema:
            fid   = field["field_id"]
            ftype = field.get("type", "text")
            val   = body.get(fid)
            mapping.append({
                "field_id":    fid,
                "label":       field.get("label"),
                "schema_type": ftype,
                "value_received": val,
                "stored_as":   "Number (N)" if ftype == "number" else
                               "Boolean (BOOL)" if ftype == "boolean" else
                               "String (S)",
            })

        record_id = await _insert(table_name, schema, body)

        return {
            "status": "success",
            "table_name": table_name,
            "record_id": record_id,
            "field_mapping": mapping,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ── 3. List all rows ───────────────────────────────────────────

@router.get("/{table_name}/rows", summary="List all rows in a dynamic table")
async def list_rows(table_name: str):
    try:
        from ..db.repositories.datastore_repo import list_rows as _list
        rows = await _list(table_name)
        return {"status": "success", "table_name": table_name, "count": len(rows), "data": rows}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ── 4. Get one row ─────────────────────────────────────────────

@router.get("/{table_name}/row/{record_id}", summary="Get one row by ID")
async def get_row(table_name: str, record_id: str):
    try:
        from ..db.repositories.datastore_repo import get_row as _get
        row = await _get(table_name, record_id)
        if not row:
            return {"status": "error", "message": "Row not found"}
        return {"status": "success", "table_name": table_name, "data": row}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ── Config: get / switch active DB backend ────────────────────

@router.get("/config", summary="Get the active DB backend")
async def get_config():
    from ..db.repositories.datastore_repo import get_backend
    return {"status": "success", "db_backend": get_backend()}


@router.post("/config", summary="Switch the active DB backend (dynamodb | postgresql)")
async def update_config(body: dict[str, Any] = Body(...)):
    backend = body.get("db_backend", "")
    if backend not in ("dynamodb", "postgresql"):
        return {"status": "error", "message": "db_backend must be 'dynamodb' or 'postgresql'"}
    from ..db.repositories.datastore_repo import set_backend
    set_backend(backend)
    return {"status": "success", "db_backend": backend}


# ── 5. List all schemas ────────────────────────────────────────

@router.get("/schemas", summary="List all registered schemas")
async def list_schemas():
    try:
        from ..db.repositories.datastore_repo import list_schemas as _list
        schemas = await _list()
        return {"status": "success", "count": len(schemas), "schemas": schemas}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ── 6. Get schema for one table ────────────────────────────────

@router.get("/schemas/{table_name}", summary="Get schema definition for a table")
async def get_schema(table_name: str):
    try:
        from ..db.repositories.datastore_repo import get_schema as _get
        schema = await _get(table_name)
        if not schema:
            return {"status": "error", "message": f"Schema not found for '{table_name}'"}
        return {"status": "success", "table_name": table_name, "schema": schema}
    except Exception as e:
        return {"status": "error", "message": str(e)}
