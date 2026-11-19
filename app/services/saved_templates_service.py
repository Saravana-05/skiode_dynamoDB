from ..utils.query_loader import load_queries
from ..core.database import fetch, fetchrow, execute
from ..utils.json_serializers import to_jsonb, from_jsonb

queries = load_queries()
st_q = queries["saved_templates"]

_schema_ready = False


async def _ensure_schema() -> None:
    """Every saved template can belong to a project. Adds the column on first use
    (idempotent), so no separate migration step is needed. Templates saved before
    this have project_id NULL = "no project"."""
    global _schema_ready
    if _schema_ready:
        return
    await execute(
        "ALTER TABLE saved_templates "
        "ADD COLUMN IF NOT EXISTS project_id INTEGER REFERENCES projects (id) ON DELETE SET NULL"
    )
    await execute("CREATE INDEX IF NOT EXISTS idx_saved_templates_project ON saved_templates (project_id)")
    _schema_ready = True


def _project_id_or_none(value):
    """None / "" -> None (no project); otherwise a positive int, else ValueError."""
    if value in (None, ""):
        return None
    try:
        pid = int(value)
    except (TypeError, ValueError):
        raise ValueError("project_id must be a number")
    if pid <= 0:
        raise ValueError("project_id must be a positive number")
    return pid


async def _check_project(pid):
    if pid is not None and not await fetchrow("SELECT 1 FROM projects WHERE id = $1", pid):
        raise ValueError(f"Project {pid} not found")


class SavedTemplatesService:
    """
    Stores reusable Page/Block/Component snapshots for the View Builder's
    "Save as reusable" feature. Drag a saved template into any other page
    or block and the frontend clones it with fresh ids — see
    src/sky-view-builder/core/templateStore.ts for the consumer side.
    """

    async def list_templates(self, project_id=None):
        """All templates, newest first; `project_id` limits it to one project."""
        await _ensure_schema()
        pid = _project_id_or_none(project_id)
        if pid is None:
            rows = await fetch(st_q["get_all_saved_templates"])
        else:
            rows = await fetch(st_q["get_saved_templates_by_project"], pid)
        result = []
        for row in rows:
            d = dict(row)
            d["instance"] = from_jsonb(d.get("instance"))
            result.append(d)
        return result

    async def get_template(self, template_id: int):
        await _ensure_schema()
        row = await fetchrow(st_q["get_saved_template_by_id"], template_id)
        if not row:
            return None
        d = dict(row)
        d["instance"] = from_jsonb(d.get("instance"))
        return d

    async def create_template(self, data: dict) -> dict:
        await _ensure_schema()
        pid = _project_id_or_none(data.get("project_id"))
        await _check_project(pid)
        row = await fetchrow(
            st_q["insert_saved_template"],
            data.get("name") or "Untitled",
            data.get("plugin_id") or "",
            to_jsonb(data.get("instance")),
            data.get("created_by"),
            pid,
        )
        result = dict(row)
        result["instance"] = from_jsonb(result.get("instance"))
        return result

    async def delete_template(self, template_id: int):
        await _ensure_schema()
        await execute(st_q["delete_saved_template"], template_id)
        return True

    async def update_template(self, template_id: int, data: dict):
        """Overwrite an existing template in place (same id, same row) so the
        Saved Blocks list shows the edited version instead of a duplicate.
        Returns None when the id doesn't exist.

        The project is changed only when "project_id" is present in `data`
        (null clears it); an edit that doesn't mention it keeps the current one."""
        await _ensure_schema()
        instance = data.get("instance")
        set_project = "project_id" in data
        pid = _project_id_or_none(data.get("project_id")) if set_project else None
        if set_project:
            await _check_project(pid)
        row = await fetchrow(
            st_q["update_saved_template"],
            template_id,
            data.get("name"),
            data.get("plugin_id"),
            to_jsonb(instance) if instance is not None else None,
            pid,
            set_project,
        )
        if not row:
            return None
        result = dict(row)
        result["instance"] = from_jsonb(result.get("instance"))
        return result