"""
Dynamic Datastore API

Flow:
  1. POST /datastore/create              → define schema + create DynamoDB table
  2. POST /datastore/{table_name}/row    → insert a row — fields mapped from schema, stored as separate columns
  3. GET  /datastore/{table_name}/rows   → list all rows
  4. GET  /datastore/{table_name}/row/{id} → get one row
  5. GET  /datastore/schemas             → list all registered schemas
  6. GET  /datastore/schemas/{table_name} → get schema for one table
"""
from typing import Any
from fastapi import APIRouter, Body
from pydantic import BaseModel

router = APIRouter(prefix="/datastore", tags=["Datastore - Dynamic Tables"])


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

@router.post("/create", summary="Create a DynamoDB table from a JSON schema")
async def create_table(body: CreateTableRequest):
    """
    Provide a table_name and a list of schema fields.
    - Saves schema to datastore_schemas table
    - Creates a real DynamoDB table (id as primary key)
    - Each schema field will become its own separate column on row insert
    """
    try:
        from ..db.repositories.datastore_repo import create_table_from_schema, save_schema

        schema = [f.model_dump() for f in body.schema]
        result = await create_table_from_schema(body.table_name, schema)
        await save_schema(body.table_name, schema)

        return {
            "status": "success",
            "table_name": body.table_name,
            "table_created": result["created"],
            "columns": [
                {"field_id": f["field_id"], "label": f["label"], "type": f["type"]}
                for f in schema
            ],
            "total_fields": len(schema),
        }
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
