"""
Domain-model drafts — registry/config data, always PostgreSQL.

Same reasoning as validation_rules in datastore_repo.py: a draft is
builder metadata, not per-domain dynamic table data, so it isn't part of
the dynamodb/postgresql switch and there's no dynamo equivalent. The
tables a draft *generates* on submit still respect the active backend —
submit_draft() goes back through the datastore_repo facade for that.
"""


async def save_draft(
    domain_name: str,
    payload: dict,
    project_id: int | str | None = None,
    created_by: str | None = None,
) -> dict:
    from .postgres.domain_draft_repo import save_draft as _save
    return await _save(domain_name, payload, project_id, created_by)


async def list_drafts(
    project_id: int | str | None = None,
    status: str | None = "draft",
) -> list[dict]:
    from .postgres.domain_draft_repo import list_drafts as _list
    return await _list(project_id, status)


async def get_draft(draft_id: int | str) -> dict | None:
    from .postgres.domain_draft_repo import get_draft as _get
    return await _get(draft_id)


async def delete_draft(draft_id: int | str) -> dict:
    from .postgres.domain_draft_repo import delete_draft as _delete
    return await _delete(draft_id)


async def submit_draft(draft_id: int | str) -> dict:
    from .postgres.domain_draft_repo import submit_draft as _submit
    return await _submit(draft_id)


__all__ = [
    "save_draft",
    "list_drafts",
    "get_draft",
    "delete_draft",
    "submit_draft",
]