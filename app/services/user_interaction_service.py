from ..utils.query_loader import load_queries
from ..core.database import fetch, fetchrow, execute
from ..utils.json_serializers import to_jsonb, from_jsonb

queries = load_queries()

ui_q = queries["user_interaction"]


# User Interaction Crud bgn
class UserInteractionService:
    """
    """

    async def list_pages(self):
        rows = await fetch(ui_q["get_all_user_interactions"])
        result = []
        for row in rows:
            d = dict(row)
            d["page_data"] = from_jsonb(d.get("page_data"))
            result.append(d)
        return result

    async def get_page(self, interaction_id: int):
        row = await fetchrow(ui_q["get_user_interaction_by_id"], interaction_id)
        if not row:
            return None
        result = dict(row)
        result["page_data"] = from_jsonb(result.get("page_data"))
        return result

    async def create_page(self, data: dict) -> dict:
        row = await fetchrow(
            ui_q["insert_user_interaction"],
            data.get("page_name", ""),
            to_jsonb(data.get("page_data")),
            data.get("created_by", ""),
        )
        result = dict(row)
        result["page_data"] = from_jsonb(result.get("page_data"))
        return result

    async def update_page(self, interaction_id: int, data: dict) -> dict:
        row = await fetchrow(
            ui_q["update_user_interaction"],
            interaction_id,
            to_jsonb(data.get("page_data")),
        )
        if not row:
            return None

        result = dict(row)
        result["page_data"] = from_jsonb(result.get("page_data"))

        return result

    async def delete_page(self, interaction_id: int):
        await execute(ui_q["soft_delete_user_interaction"], interaction_id)
        return True
# User Interaction Crud end
