"""
Seed the form_data table with 3 sample employee records.
fields is stored as a plain JSON string column.

Usage:
    python -m app.db.seed_form_data
"""
import asyncio
import aioboto3
import json
import os
import uuid
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

# Load .env before importing settings
_env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env")
load_dotenv(_env_path)

from ..core.config import settings


RECORDS = [
    {
        "name": "employee_form",
        "fields": [
            {"meta": {"config": {}, "renderer": "default"},      "type": "text",          "label": "Employee Name",       "value": "Priya",       "field_id": "employee_name"},
            {"meta": {"config": {}, "renderer": "default"},      "type": "number",        "label": "Employee Age",        "value": 29,            "field_id": "employee_age"},
            {"meta": {"config": {"currency": "INR", "locale": "en-IN", "style": "currency", "notation": "standard", "unitDisplay": "long", "compactDisplay": "long", "currencyDisplay": "symbol", "maximumFractionDigits": 2, "minimumFractionDigits": 2}, "renderer": "numberFormat"}, "type": "formattedText", "label": "Employee Salary", "value": 65000, "field_id": "employee_salary"},
            {"meta": {"config": {}, "renderer": "default"},      "type": "text",          "label": "Employee Department", "value": "Engineering", "field_id": "employee_dept"},
            {"meta": {"config": {}, "renderer": "default"},      "type": "number",        "label": "Employee Experience", "value": 5,             "field_id": "employee_experience"},
            {"meta": {"config": {}, "renderer": "default"},      "type": "text",          "label": "Region",              "value": "South",       "field_id": "employee_region"},
        ],
    },
    {
        "name": "contractor_form",
        "fields": [
            {"meta": {"config": {}, "renderer": "default"},      "type": "text",          "label": "Employee Name",       "value": "Arjun",  "field_id": "employee_name"},
            {"meta": {"config": {}, "renderer": "default"},      "type": "number",        "label": "Employee Age",        "value": 34,       "field_id": "employee_age"},
            {"meta": {"config": {"currency": "INR", "locale": "en-IN", "style": "currency", "notation": "standard", "unitDisplay": "long", "compactDisplay": "long", "currencyDisplay": "symbol", "maximumFractionDigits": 2, "minimumFractionDigits": 2}, "renderer": "numberFormat"}, "type": "formattedText", "label": "Employee Salary", "value": 120000, "field_id": "employee_salary"},
            {"meta": {"config": {}, "renderer": "default"},      "type": "text",          "label": "Employee Department", "value": "HR",     "field_id": "employee_dept"},
            {"meta": {"config": {}, "renderer": "default"},      "type": "number",        "label": "Employee Experience", "value": 10,       "field_id": "employee_experience"},
            {"meta": {"config": {}, "renderer": "default"},      "type": "text",          "label": "Region",              "value": "North",  "field_id": "employee_region"},
        ],
    },
    {
        "name": "employee_form",
        "fields": [
            {"meta": {"config": {}, "renderer": "default"},      "type": "text",          "label": "Employee Name",       "value": "Sneha",   "field_id": "employee_name"},
            {"meta": {"config": {}, "renderer": "default"},      "type": "number",        "label": "Employee Age",        "value": 26,        "field_id": "employee_age"},
            {"meta": {"config": {"currency": "INR", "locale": "en-IN", "style": "currency", "notation": "standard", "unitDisplay": "long", "compactDisplay": "long", "currencyDisplay": "symbol", "maximumFractionDigits": 2, "minimumFractionDigits": 2}, "renderer": "numberFormat"}, "type": "formattedText", "label": "Employee Salary", "value": 45000, "field_id": "employee_salary"},
            {"meta": {"config": {}, "renderer": "default"},      "type": "text",          "label": "Employee Department", "value": "Finance", "field_id": "employee_dept"},
            {"meta": {"config": {}, "renderer": "default"},      "type": "number",        "label": "Employee Experience", "value": 2,         "field_id": "employee_experience"},
            {"meta": {"config": {}, "renderer": "default"},      "type": "text",          "label": "Region",              "value": "East",    "field_id": "employee_region"},
        ],
    },
]


async def seed():
    kwargs = {"region_name": settings.AWS_REGION}
    if settings.AWS_ACCESS_KEY_ID:
        kwargs["aws_access_key_id"] = settings.AWS_ACCESS_KEY_ID
    if settings.AWS_SECRET_ACCESS_KEY:
        kwargs["aws_secret_access_key"] = settings.AWS_SECRET_ACCESS_KEY
    if settings.DYNAMODB_ENDPOINT_URL:
        kwargs["endpoint_url"] = settings.DYNAMODB_ENDPOINT_URL

    session = aioboto3.Session()
    async with session.resource("dynamodb", **kwargs) as dynamodb:
        table = await dynamodb.Table(settings.TABLE_EVENT_LOG)
        now_base = datetime.now(timezone.utc)

        for i, rec in enumerate(RECORDS):
            record_id = str(uuid.uuid4())
            created_at = (now_base - timedelta(days=i)).isoformat()

            await table.put_item(Item={
                "id":         record_id,
                "name":       rec["name"],
                "fields":     json.dumps(rec["fields"], ensure_ascii=False),  # ← JSON string
                "created_at": created_at,
            })
            print(f"  inserted [{rec['name']}] id={record_id}  (fields stored as JSON string)")

    print("Done.")


if __name__ == "__main__":
    asyncio.run(seed())
