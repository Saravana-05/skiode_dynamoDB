import uuid
from datetime import datetime, timezone
from boto3.dynamodb.conditions import Key, Attr
from ....core.dynamodb import get_dynamodb
from ....core.config import settings
from ..utils import clean, strip_none


async def _table():
    return await get_dynamodb().Table(settings.TABLE_EMPLOYEES)


async def create(name: str, skills: list[str]) -> dict:
    tbl = await _table()
    employee_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    item = strip_none({
        "employee_id": employee_id,
        "name": name,
        "skills": set(skills) if skills else None,
        "skills_count": len(skills),
        "entity_type": "EMPLOYEE",
        "created_at": now,
    })
    await tbl.put_item(Item=item)
    return clean(item)


async def get_by_id(employee_id: str) -> dict | None:
    tbl = await _table()
    resp = await tbl.get_item(Key={"employee_id": employee_id})
    item = resp.get("Item")
    return clean(item) if item else None


async def list_all() -> list[dict]:
    tbl = await _table()
    resp = await tbl.scan()
    return [clean(i) for i in resp.get("Items", [])]


async def filter_by_skill(skill: str) -> list[dict]:
    tbl = await _table()
    resp = await tbl.scan(
        FilterExpression=Attr("skills").contains(skill)
    )
    return [clean(i) for i in resp.get("Items", [])]


async def filter_by_skills_count(count: int, operator: str = "eq") -> list[dict]:
    attr = Attr("skills_count")
    condition_map = {
        "eq":  attr.eq(count),
        "gt":  attr.gt(count),
        "lt":  attr.lt(count),
        "gte": attr.gte(count),
        "lte": attr.lte(count),
    }
    condition = condition_map.get(operator)
    if condition is None:
        raise ValueError(f"Invalid operator '{operator}'. Use: eq, gt, lt, gte, lte")

    tbl = await _table()
    resp = await tbl.scan(FilterExpression=condition)
    return [clean(i) for i in resp.get("Items", [])]
