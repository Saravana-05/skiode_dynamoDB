"""
Query Builder API — relational queries across domain objects.

Flow:
  1. POST /query-builder/relationships        → define a join edge between two domain objects
  2. GET  /query-builder/relationships         → list all edges (for the relationship graph UI)
  3. GET  /query-builder/relationships/{dmo}   → edges touching one domain object (for "show related objects")
  4. POST /query-builder/preview               → resolve joins + generate SQL only (no execution, no save)
  5. POST /query-builder/execute               → resolve + generate + persist + run, returns rows
  6. GET  /query-builder/definitions           → list saved query definitions
  7. GET  /query-builder/definitions/{id}      → load one saved query definition (its query_json)

Postgres-only for now — relational joins don't map onto the DynamoDB
backend the same way, so these routes require settings.DB_BACKEND == "postgresql".
"""
from typing import Any, Literal
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..utils.decorators import handle_errors
from ..core.config import settings

from ..db.repositories.postgres.relationship_repo import get_query_definition, run_select

router = APIRouter(prefix="/query-builder", tags=["Query Builder - Relational Queries"])


def _require_postgres() -> None:
    if settings.DB_BACKEND != "postgresql":
        raise HTTPException(
            status_code=400,
            detail="Query Builder relational joins require DB_BACKEND=postgresql.",
        )


# ── Pydantic models ────────────────────────────────────────────

class RelationshipRequest(BaseModel):
    from_dmo: str
    to_dmo: str
    from_field: str
    to_field: str
    cardinality: Literal["OneToOne", "OneToMany", "ManyToOne", "ManyToMany"]
    label: str | None = None


class QueryField(BaseModel):
    dmo: str
    field: str
    aggregation: str | None = None
    alias: str | None = None


class QueryFilter(BaseModel):
    dmo: str
    field: str
    operator: str = "="
    value: Any = None


# ── Nested AND/OR filter tree (additive; coexists with flat `filters`) ──
#
# A FilterNode is either:
#   - a leaf condition:  {"dmo", "field", "operator", "value"}
#   - a group:           {"operator": "AND"|"OR", "children": [FilterNode, ...]}
#
# Precedence rule (enforced in _resolve_and_generate): if `filter_tree` is
# present, it is used and `filters` is ignored. `filters` remains supported
# on its own for old clients / saved query definitions that predate this.

class FilterConditionNode(BaseModel):
    type: Literal["condition"] = "condition"
    dmo: str
    field: str
    operator: str = "="
    value: Any = None


class FilterGroupNode(BaseModel):
    type: Literal["group"] = "group"
    operator: Literal["AND", "OR"] = "AND"
    children: list["FilterNode"] = []


FilterNode = FilterConditionNode | FilterGroupNode
FilterGroupNode.model_rebuild()


class QueryGroupBy(BaseModel):
    dmo: str
    field: str


class QueryHaving(BaseModel):
    dmo: str
    field: str
    aggregation: str | None = None
    operator: str = ">"
    value: Any = None


class QuerySort(BaseModel):
    dmo: str | None = None
    field: str | None = None
    alias: str | None = None
    direction: Literal["ASC", "DESC"] = "ASC"


class QueryDefinitionRequest(BaseModel):
    name: str | None = None
    objects: list[str]
    fields: list[QueryField]
    filters: list[QueryFilter] = []
    filter_tree: FilterNode | None = None  # NEW: nested AND/OR; wins over `filters` if set
    groupBy: list[QueryGroupBy] = []
    having: list[QueryHaving] = []
    sort: list[QuerySort] = []

    def to_json(self) -> dict:
        return self.model_dump()


# ── 1/2/3. Relationship CRUD ────────────────────────────────────

@router.post("/relationships", summary="Define a join edge between two domain objects")
@handle_errors
async def create_relationship(body: RelationshipRequest, request: Request):
    _require_postgres()
    from ..db.repositories.postgres.relationship_repo import save_relationship
    result = await save_relationship(
        body.from_dmo, body.to_dmo, body.from_field, body.to_field,
        body.cardinality, body.label,
    )
    return {"status": "success", **result}


@router.get("/relationships", summary="List all relationships (the full join graph)")
@handle_errors
async def get_relationships(request: Request):
    _require_postgres()
    from ..db.repositories.postgres.relationship_repo import list_relationships
    rows = await list_relationships()
    return {"status": "success", "count": len(rows), "data": rows}


@router.get(
    "/relationships/{dmo}",
    summary="List relationships touching one domain object (for 'show related objects')",
)
@handle_errors
async def get_relationships_for(dmo: str, request: Request):
    _require_postgres()
    from ..db.repositories.postgres.relationship_repo import list_relationships_for
    rows = await list_relationships_for(dmo)
    return {"status": "success", "dmo": dmo, "count": len(rows), "data": rows}


@router.delete("/relationships/{relationship_id}", summary="Delete a relationship by id")
@handle_errors
async def remove_relationship(relationship_id: int, request: Request):
    _require_postgres()
    from ..db.repositories.postgres.relationship_repo import delete_relationship
    result = await delete_relationship(relationship_id)
    if result["status"] == "not_found":
        raise HTTPException(status_code=404, detail="Relationship not found")
    return result


MAX_FILTER_TREE_DEPTH = 6


def _check_filter_tree_depth(node: dict, depth: int = 1) -> None:
    if depth > MAX_FILTER_TREE_DEPTH:
        raise HTTPException(
            status_code=400,
            detail=f"filter_tree exceeds max nesting depth of {MAX_FILTER_TREE_DEPTH}",
        )
    if node.get("type") == "group":
        for child in node.get("children") or []:
            _check_filter_tree_depth(child, depth + 1)


# ── shared: resolve join plan + generate SQL ────────────────────

async def _resolve_and_generate(query_json: dict) -> tuple[str, list]:
    from ..db.repositories.postgres.relationship_repo import list_relationships
    from ..services.relationship_resolver import RelationshipResolver
    from ..services.sql_generator import SqlGenerator, SqlGenerationError

    if query_json.get("filter_tree"):
        _check_filter_tree_depth(query_json["filter_tree"])

    relationships = await list_relationships()
    resolver = RelationshipResolver(relationships)

    try:
        join_plan = resolver.build_join_plan(query_json["objects"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        sql_text, params = SqlGenerator(query_json, join_plan).generate()
    except SqlGenerationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return sql_text, params


# ── 4. Preview SQL only ─────────────────────────────────────────

@router.post("/preview", summary="Resolve joins + generate SQL — does NOT execute or save")
@handle_errors
async def preview_query(body: QueryDefinitionRequest, request: Request):
    _require_postgres()
    query_json = body.to_json()
    sql_text, params = await _resolve_and_generate(query_json)
    return {"status": "success", "sql": sql_text, "params": params}


# ── 5. Execute (generate + persist + run) ───────────────────────

@router.post("/execute", summary="Resolve, generate, save, and run the query")
@handle_errors
async def execute_query(body: QueryDefinitionRequest, request: Request):
    _require_postgres()
    import time
    from ..db.repositories.postgres.relationship_repo import (
        save_query_definition, save_generated_sql, run_select,
    )

    query_json = body.to_json()
    sql_text, params = await _resolve_and_generate(query_json)

    definition = await save_query_definition(body.name, query_json)

    start = time.perf_counter()
    try:
        rows = await run_select(sql_text, params)
        elapsed_ms = (time.perf_counter() - start) * 1000
        await save_generated_sql(
            definition["id"], sql_text,
            execution_status="success", execution_time_ms=elapsed_ms, row_count=len(rows),
        )
        return {
            "status": "success",
            "query_definition_id": definition["id"],
            "sql": sql_text,
            "row_count": len(rows),
            "data": rows,
        }
    except Exception as e:
        elapsed_ms = (time.perf_counter() - start) * 1000
        await save_generated_sql(
            definition["id"], sql_text,
            execution_status="error", execution_time_ms=elapsed_ms, error_message=str(e),
        )
        raise HTTPException(status_code=400, detail=f"Query execution failed: {e}")


# ── 6/7. Saved query definitions ────────────────────────────────

@router.get("/definitions", summary="List saved query definitions")
@handle_errors
async def get_definitions(request: Request):
    _require_postgres()
    from ..db.repositories.postgres.relationship_repo import list_query_definitions
    rows = await list_query_definitions()
    return {"status": "success", "count": len(rows), "data": rows}


@router.get("/definitions/{query_definition_id}", summary="Load one saved query definition")
@handle_errors
async def get_definition(query_definition_id: int, request: Request):
    _require_postgres()
    from ..db.repositories.postgres.relationship_repo import get_query_definition
    definition = await get_query_definition(query_definition_id)
    if not definition:
        raise HTTPException(status_code=404, detail="Query definition not found")
    return {"status": "success", "data": definition}


@router.get("/objects", summary="List all domain objects with their fields")
@handle_errors
async def get_domain_objects(request: Request):
    _require_postgres()
    from ..db.repositories.postgres.relationship_repo import list_domain_objects
    rows = await list_domain_objects()
    return {"status": "success", "data": rows}


# Mohan Dev Begins ---->
@router.post("/definitions/{query_definition_id}/execute", summary="Execute an existing saved query")
@handle_errors
async def execute_saved_query(query_definition_id: int, request: Request):
    """
    Execute query for data provider
    """
    definition = await get_query_definition(query_definition_id)
    if not definition:
        raise HTTPException(status_code=404, detail="Query definition not found")

    query_json = definition["query_json"]
    sql_text, params = await _resolve_and_generate(query_json)

    try:
        rows = await run_select(sql_text, params)
    except Exception as e:
        raise HTTPException(status_code=400,detail=f"Query execution failed: {e}")

    return {
        "status": "success",
        "query_definition_id": query_definition_id,
        "row_count": len(rows),
        "data": rows
    }

# Mohan Dev Ends ---->
0