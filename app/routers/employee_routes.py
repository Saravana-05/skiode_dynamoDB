from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/employees", tags=["Employees"])


class AddEmployeeRequest(BaseModel):
    name: str
    skills: list[str]

    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "Alice",
                "skills": ["a", "b"]
            }
        }
    }


def _repo():
    from ..db.repositories.dynamo import employee_repo
    return employee_repo


@router.post("")
async def add_employee(body: AddEmployeeRequest):
    repo = _repo()
    employee = await repo.create(name=body.name, skills=body.skills)
    return {"status": "success", "data": employee}


@router.get("")
async def list_employees():
    repo = _repo()
    employees = await repo.list_all()
    return {"status": "success", "data": employees}


@router.get("/filter/skill/{skill}")
async def filter_by_skill(skill: str):
    """Return all employees who have the given skill."""
    repo = _repo()
    employees = await repo.filter_by_skill(skill)
    return {"status": "success", "skill": skill, "count": len(employees), "data": employees}


@router.get("/filter/skills-count")
async def filter_by_skills_count(
    count: int,
    operator: Literal["eq", "gt", "lt", "gte", "lte"] = "eq",
):
    """
    Filter employees by number of skills.

    - **count**: the number to compare against
    - **operator**: eq | gt | lt | gte | lte  (default: eq)

    Examples:
    - `?count=1&operator=eq`  → employees with exactly 1 skill
    - `?count=1&operator=gt`  → employees with more than 1 skill
    """
    repo = _repo()
    try:
        employees = await repo.filter_by_skills_count(count=count, operator=operator)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "success", "filter": f"skills_count {operator} {count}", "count": len(employees), "data": employees}


@router.get("/{employee_id}")
async def get_employee(employee_id: str):
    repo = _repo()
    employee = await repo.get_by_id(employee_id)
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    return {"status": "success", "data": employee}
