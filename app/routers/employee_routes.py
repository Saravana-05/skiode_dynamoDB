import re
from typing import Any, Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from ..utils.decorators import handle_errors   # ← add this import

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
@handle_errors                         # ← add
async def add_employee(body: AddEmployeeRequest):
    repo = _repo()
    employee = await repo.create(name=body.name, skills=body.skills)
    return {"status": "success", "data": employee}


@router.get("")
@handle_errors                         # ← add
async def list_employees():
    repo = _repo()
    employees = await repo.list_all()
    return {"status": "success", "data": employees}


@router.get("/filter/skill/{skill}")
@handle_errors                         # ← add
async def filter_by_skill(skill: str):
    repo = _repo()
    employees = await repo.filter_by_skill(skill)
    return {"status": "success", "skill": skill, "count": len(employees), "data": employees}


@router.get("/filter/skills-count")
@handle_errors                         # ← add
async def filter_by_skills_count(
    count: int,
    operator: Literal["eq", "gt", "lt", "gte", "lte"] = "eq",
):
    repo = _repo()
    employees = await repo.filter_by_skills_count(count=count, operator=operator)
    return {"status": "success", "filter": f"skills_count {operator} {count}", "count": len(employees), "data": employees}


@router.get("/{employee_id}")
@handle_errors                         # ← add
async def get_employee(employee_id: str):
    repo = _repo()
    employee = await repo.get_by_id(employee_id)
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    return {"status": "success", "data": employee}