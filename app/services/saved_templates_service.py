from ..utils.query_loader import load_queries
from ..core.database import fetch, fetchrow, execute
from ..utils.json_serializers import to_jsonb, from_jsonb

queries = load_queries()
st_q = queries["saved_templates"]


class SavedTemplatesService:
    """
    Stores reusable Page/Block/Component snapshots for the View Builder's
    "Save as reusable" feature. Drag a saved template into any other page
    or block and the frontend clones it with fresh ids — see
    src/sky-view-builder/core/templateStore.ts for the consumer side.
    """

    async def list_templates(self):
        rows = await fetch(st_q["get_all_saved_templates"])
        result = []
        for row in rows:
            d = dict(row)
            d["instance"] = from_jsonb(d.get("instance"))
            result.append(d)
        return result

    async def get_template(self, template_id: int):
        row = await fetchrow(st_q["get_saved_template_by_id"], template_id)
        if not row:
            return None
        d = dict(row)
        d["instance"] = from_jsonb(d.get("instance"))
        return d

    async def create_template(self, data: dict) -> dict:
        row = await fetchrow(
            st_q["insert_saved_template"],
            data.get("name") or "Untitled",
            data.get("plugin_id") or "",
            to_jsonb(data.get("instance")),
            data.get("created_by"),
        )
        result = dict(row)
        result["instance"] = from_jsonb(result.get("instance"))
        return result

    async def delete_template(self, template_id: int):
        await execute(st_q["delete_saved_template"], template_id)
        return True