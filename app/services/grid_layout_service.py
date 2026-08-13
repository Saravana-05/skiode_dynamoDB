from ..utils.query_loader import load_queries
from ..core.database import fetch, fetchrow, execute
from ..utils.json_serializers import to_jsonb, from_jsonb

queries = load_queries()

gl_q = queries["grid_layout"]


# Grid Layout Crud bgn
class GridLayoutService:
    """
    Stores the react-grid-layout JSON only ({ lg: [{ i, x, y, w, h }, ...] }).
    Kept separate from UserInteractionService (page_data / component tree)
    on purpose — see grid_layout table comment.
    """

    async def list_layouts(self, page_name: str | None = None):
        if page_name:
            rows = await fetch(gl_q["get_grid_layouts_by_page_name"], page_name)
        else:
            rows = await fetch(gl_q["get_all_grid_layouts"])
        result = []
        for row in rows:
            d = dict(row)
            d["layout_data"] = from_jsonb(d.get("layout_data"))
            result.append(d)
        return result

    async def get_layout(self, layout_id: int):
        row = await fetchrow(gl_q["get_grid_layout_by_id"], layout_id)
        if not row:
            return None
        result = dict(row)
        result["layout_data"] = from_jsonb(result.get("layout_data"))
        return result

    async def create_layout(self, data: dict) -> dict:
        row = await fetchrow(
            gl_q["insert_grid_layout"],
            data.get("page_name", ""),
            data.get("label") or "Untitled Layout",
            to_jsonb(data.get("layout_data")),
            data.get("created_by", ""),
        )
        result = dict(row)
        result["layout_data"] = from_jsonb(result.get("layout_data"))
        return result

    async def update_layout(self, layout_id: int, data: dict) -> dict:
        row = await fetchrow(
            gl_q["update_grid_layout"],
            layout_id,
            to_jsonb(data.get("layout_data")),
            data.get("label") or "Untitled Layout",
        )
        if not row:
            return None

        result = dict(row)
        result["layout_data"] = from_jsonb(result.get("layout_data"))

        return result

    async def delete_layout(self, layout_id: int):
        await execute(gl_q["delete_grid_layout"], layout_id)
        return True
# Grid Layout Crud end