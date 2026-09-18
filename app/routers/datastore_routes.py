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

Projects (PostgreSQL only):
  POST /datastore/create accepts an optional `project_id` to scope the
  new domain model to a project (see /projects routes). Physical table
  names are still globally unique in Postgres, so `project_id` is a
  grouping/ownership tag, not a namespace for the table name itself.
  GET /datastore/schemas?project_id=... lists only that project's
  domain models; omit it to list everything (unchanged, backward compatible).

Drafts (PostgreSQL only):
  A draft is a domain model saved to the database but NOT yet turned
  into real tables. POST /datastore/drafts persists it and issues no
  DDL at all; the physical tables are generated only by
  POST /datastore/drafts/{draft_id}/submit. Drafts live in their own
  domain_model_drafts table and are deliberately kept out of
  datastore_schemas, so GET /datastore/schemas (and everything reading
  it) still only ever sees submitted domain models.
  16. POST   /datastore/drafts                    → save (upsert) a draft, no tables created
  17. GET    /datastore/drafts                    → list drafts (filter by project_id / status)
  18. GET    /datastore/drafts/{draft_id}         → get one draft
  19. DELETE /datastore/drafts/{draft_id}         → discard a draft
  20. POST   /datastore/drafts/{draft_id}/submit  → generate the domain model tables

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
    project_id: str | int | None = None   # optional — scopes this domain model to a project
    # Safety net for callers that already POST here: with is_draft=true
    # this endpoint saves a draft instead of creating anything. Nothing
    # existing sets it, so the default keeps the old behaviour exactly.
    is_draft: bool = False

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


class DraftTableSpec(BaseModel):
    """One table the draft will generate when it's submitted — the exact
    same shape POST /datastore/create takes, just stored instead of
    executed."""
    table_name: str
    schema: list[SchemaField]
    db_backend: str | None = None
    versioned: bool = False
    project_id: str | int | None = None

    model_config = {"extra": "allow"}


class SaveDraftRequest(BaseModel):
    domain_name: str
    project_id: str | int | None = None
    # Tables to create on submit, in the order they should be applied
    # (main domain, then related domains, then junction tables).
    tables: list[DraftTableSpec] = []
    # Opaque builder state the frontend round-trips so an unfinished
    # domain can be reopened and edited exactly as it was left.
    fields: dict[str, Any] | None = None
    payload: dict[str, Any] | None = None
    db_backend: str | None = None
    versioned: bool = False

    model_config = {"extra": "allow"}


class DomainAttributeRequest(BaseModel):
    domain_model_id: str
    attribute_name: str
    label: str | None = None
    field_type: str | None = None


class AttributeTranslationRequest(BaseModel):
    lang_code: str   # 'en' | 'ta' | 'ar'
    label: str


class ValidationRuleRequest(BaseModel):
    tag: str
    version: str | None = None
    description: str | None = None
    category: str | None = None

    # new kind-based shape
    kind: str | None = None
    expression: str | None = None
    min: float | None = None
    max: float | None = None
    validations: list[Any] | None = None

    # legacy flat shape
    type: str | None = None
    value: Any = None
    message: str | None = None


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

    # 0. Draft — persist it and stop. No DDL, no datastore_schemas row.
    #    The tables get generated by POST /datastore/drafts/{id}/submit.
    if body.is_draft:
        from ..db.repositories.domain_draft_repo import save_draft as _save_draft
        saved = await _save_draft(
            body.table_name,
            {
                "domain_name": body.table_name,
                "tables": [{
                    "table_name": body.table_name,
                    "schema":     schema,
                    "project_id": body.project_id,
                }],
            },
            body.project_id,
            _current_user(request),
        )
        return {
            **saved,
            "table_name":    body.table_name,
            "table_created": False,
            "is_draft":      True,
            "project_id":    body.project_id,
        }

    # 1. Create / update the physical table
    result = await create_table_from_schema(body.table_name, schema)

    # 2. Save / update schema metadata
    await save_schema(body.table_name, schema, body.project_id)

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
        "project_id":    body.project_id,
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


# ── Drafts ─────────────────────────────────────────────────────
# Registered before the dynamic /{table_name}/... routes below so a
# literal "drafts" path segment is never swallowed by table_name.

def _current_user(request: Request) -> str | None:
    """Best-effort creator stamp from the bearer token. A missing or
    malformed token just means an unattributed draft — it must never
    block saving one."""
    try:
        auth = request.headers.get("Authorization", "")
        if not auth.lower().startswith("bearer "):
            return None
        from ..core.security import verify_token
        payload = verify_token(auth.split(" ", 1)[1]) or {}
        user = payload.get("email") or payload.get("user_id")
        return str(user) if user is not None else None
    except Exception:
        return None


@router.post("/drafts", summary="Save a domain model as a DRAFT — stored in the DB, no tables created")
@handle_errors
async def save_draft_route(body: SaveDraftRequest, request: Request):
    """
    Persists the whole in-progress domain model (its fields, UI hints,
    relations, junction tables — everything) as one row in
    domain_model_drafts. Nothing is created in the schema: no
    CREATE TABLE, no ALTER TABLE, no datastore_schemas entry. The
    domain model only becomes real tables when the draft is submitted
    via POST /datastore/drafts/{draft_id}/submit.

    Upserts on (domain_name, project_id), so repeatedly saving the same
    domain updates the one draft rather than piling up copies.
    """
    from ..db.repositories.domain_draft_repo import save_draft as _save

    if not body.domain_name.strip():
        raise HTTPException(status_code=400, detail="domain_name is required")

    payload = body.model_dump()
    result = await _save(
        body.domain_name.strip(),
        payload,
        body.project_id,
        _current_user(request),
    )
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("message", "Could not save draft"))
    return result


@router.get("/drafts", summary="List saved drafts (optionally filtered by project_id / status)")
@handle_errors
async def list_drafts_route(
    request: Request,
    project_id: str | None = None,
    status: str | None = "draft",
):
    from ..db.repositories.domain_draft_repo import list_drafts as _list
    # status=all → include already-submitted ones too (history view).
    drafts = await _list(project_id, None if status in (None, "", "all") else status)
    return {
        "status":     "success",
        "count":      len(drafts),
        "project_id": project_id,
        "drafts":     drafts,
    }


@router.get("/drafts/{draft_id}", summary="Get one draft by id")
@handle_errors
async def get_draft_route(draft_id: str, request: Request):
    from ..db.repositories.domain_draft_repo import get_draft as _get
    draft = await _get(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail=f"Draft '{draft_id}' not found")
    return {"status": "success", "draft": draft}


@router.delete("/drafts/{draft_id}", summary="Discard a draft")
@handle_errors
async def delete_draft_route(draft_id: str, request: Request):
    from ..db.repositories.domain_draft_repo import delete_draft as _delete
    result = await _delete(draft_id)
    if result.get("status") == "error":
        raise HTTPException(status_code=404, detail=result.get("message", "Draft not found"))
    return result


@router.post("/drafts/{draft_id}/submit", summary="Submit a draft — generates the domain model tables")
@handle_errors
async def submit_draft_route(draft_id: str, request: Request):
    """
    The single point where a draft turns into real tables: each stored
    table spec goes through the same create_table_from_schema +
    save_schema path a direct POST /datastore/create would take, in the
    order the draft recorded (main domain → related domains → junction
    tables). On any failure the draft stays open so it can be fixed and
    resubmitted — a partial submit is never marked done.
    """
    from ..db.repositories.domain_draft_repo import submit_draft as _submit
    result = await _submit(draft_id)
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result)
    return result


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

@router.get("/schemas", summary="List all registered schemas (optionally filtered by project_id)")
@handle_errors
async def list_schemas(request: Request, project_id: str | None = None):
    from ..db.repositories.datastore_repo import list_schemas as _list
    schemas = await _list(project_id)
    return {"status": "success", "count": len(schemas), "schemas": schemas, "project_id": project_id}


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


# ── 14. List all validation rules ──────────────────────────────

@router.get("/validation-rules", summary="List every named validation rule in the registry")
@handle_errors
async def list_validation_rules_route(request: Request):
    from ..db.repositories.datastore_repo import list_validation_rules as _list
    rules = await _list()
    return {"status": "success", "count": len(rules), "rules": rules}


# ── 15. Create or update a validation rule ─────────────────────

@router.post("/validation-rules", summary="Create or update (upsert, keyed by tag) a named validation rule")
@handle_errors
async def save_validation_rule_route(body: ValidationRuleRequest, request: Request):
    """
    Upserts one row in validation_rules, keyed by `tag`. Backs the
    "Create new rule" flow in the Schema Inspector's field builder — see
    apiSaveValidationRule() in the frontend's datastoreApi.ts.
    """
    from ..db.repositories.datastore_repo import save_validation_rule as _save

    if not body.tag.strip():
        raise HTTPException(status_code=400, detail="tag is required")

    rule = body.model_dump(exclude={"tag"}, exclude_none=True)
    result = await _save(body.tag.strip(), rule)
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("message", "Could not save validation rule"))
    return result

@router.delete("/validation-rules/{tag}")
async def delete_validation_rule_endpoint(tag: str):
    from app.db.repositories.postgres.datastore_repo import delete_validation_rule
    result = await delete_validation_rule(tag)
    if result.get("status") != "success":
        raise HTTPException(status_code=500, detail=result.get("message"))
    return result