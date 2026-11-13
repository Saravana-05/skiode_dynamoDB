"""Build and persist combined junction tables for multi-domain links."""
import re

from fastapi import HTTPException

from ..db.repositories import datastore_repo
from ..db.repositories.postgres.relationship_repo import ensure_relationship

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_identifier(value: str, what: str) -> str:
    if not _IDENTIFIER_RE.fullmatch(value or ""):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {what} '{value}'. Use letters, digits, and underscores only.",
        )
    if len(value) > 63:
        raise HTTPException(status_code=400, detail=f"{what.capitalize()} cannot exceed 63 characters.")
    return value


def _reference_field_name(domain_name: str) -> str:
    words = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", domain_name)
    words = re.sub(r"[^A-Za-z0-9]+", "_", words)
    return re.sub(r"_+", "_", words).strip("_").lower() + "_id"


def build_link_plan(
    domain_name: str,
    linked_domains: list[dict],
    junction_table_name: str | None = None,
) -> dict:
    """Create one tuple table spec and its pairwise relationship metadata."""
    if len(linked_domains) < 2:
        raise HTTPException(
            status_code=400,
            detail="A combined junction table requires at least two linked domains.",
        )

    domain_name = _validate_identifier(domain_name, "domain name")
    all_domains = [{"domain_name": domain_name, "field_id": None}, *linked_domains]
    seen_domains: set[str] = set()
    seen_fields: set[str] = set()

    for domain in all_domains:
        name = _validate_identifier(domain["domain_name"], "linked domain name")
        key = name.casefold()
        if key in seen_domains:
            raise HTTPException(status_code=400, detail=f"Domain '{name}' is linked more than once.")
        seen_domains.add(key)

        field_id = domain.get("field_id")
        if field_id is None:
            field_id = _reference_field_name(name)
        field_id = _validate_identifier(field_id, "junction field name")
        domain["field_id"] = field_id
        if field_id.casefold() in seen_fields:
            raise HTTPException(status_code=400, detail=f"Duplicate junction field '{field_id}'.")
        seen_fields.add(field_id.casefold())

    generated_name = "_".join(domain["domain_name"] for domain in all_domains).upper()
    table_name = _validate_identifier(junction_table_name or generated_name, "junction table name")
    if table_name.casefold() in seen_domains:
        raise HTTPException(status_code=400, detail="Junction table name must differ from linked domains.")

    schema = [
        {
            "field_id": domain["field_id"],
            "type": "number",
            "label": domain["domain_name"],
            "is_reference": True,
            "target_domain": domain["domain_name"],
        }
        for domain in all_domains
    ]
    relationships = [
        {
            "from_dmo": domain["domain_name"],
            "to_dmo": table_name,
            "from_field": "id",
            "to_field": domain["field_id"],
            "cardinality": "OneToMany",
            "label": f"{domain['domain_name']} linked through {table_name}",
        }
        for domain in all_domains
    ]
    return {
        "table": {
            "table_name": table_name,
            "label": table_name.replace("_", " ").title(),
            "schema": schema,
        },
        "relationships": relationships,
    }


async def validate_junction_table(plan: dict) -> None:
    """Prevent reusing an existing domain table for unrelated junction data."""
    table = plan["table"]
    existing = await datastore_repo.get_schema(table["table_name"])
    if not existing:
        return
    existing_schema = existing.get("schema", []) if isinstance(existing, dict) else existing
    expected = {
        (field["field_id"], field["target_domain"])
        for field in table["schema"]
    }
    actual = {
        (field.get("field_id"), field.get("target_domain"))
        for field in existing_schema
        if field.get("is_reference")
    }
    if actual != expected:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Table '{table['table_name']}' already exists and is not the matching "
                "combined-link table."
            ),
        )


async def validate_linked_domains(
    relationships: list[dict],
    tables_in_request: set[str] | None = None,
) -> None:
    """Ensure every relationship endpoint is an existing or requested domain."""
    requested = set(tables_in_request or set())
    for relationship in relationships:
        for domain_name in (relationship["from_dmo"], relationship["to_dmo"]):
            if domain_name in requested:
                continue
            if not await datastore_repo.get_schema(domain_name):
                raise HTTPException(
                    status_code=404,
                    detail=f"Linked domain '{domain_name}' was not found.",
                )


async def save_relationships(relationships: list[dict]) -> None:
    for relationship in relationships:
        await ensure_relationship(**relationship)
