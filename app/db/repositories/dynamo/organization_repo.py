import uuid
from datetime import datetime, timezone
from boto3.dynamodb.conditions import Key
from ....core.dynamodb import get_dynamodb
from ....core.config import settings
from ..utils import clean, strip_none


async def _orgs_table():
    return await (get_dynamodb()).Table(settings.TABLE_ORGANIZATIONS)

async def _auth_config_table():
    return await (get_dynamodb()).Table(settings.TABLE_ORG_AUTH_CONFIGS)

async def _usergroups_table():
    return await (get_dynamodb()).Table(settings.TABLE_USERGROUPS)


async def get_by_code(org_code):
    tbl = await _orgs_table()
    resp = await tbl.query(IndexName="code-index", KeyConditionExpression=Key("org_code").eq(org_code), Limit=1)
    items = resp.get("Items", [])
    return clean(items[0]) if items else None


async def get_by_id(org_id):
    tbl = await _orgs_table()
    resp = await tbl.get_item(Key={"id": org_id})
    item = resp.get("Item")
    return clean(item) if item else None


async def create_org(org_name, org_code, email, org_description=None, large_logo_url=None,
                     small_logo_url=None, primary_color=None, secondary_color=None,
                     accent1_color=None, accent2_color=None, accent3_color=None,
                     bot_id=None, admin_set_password=False):
    tbl = await _orgs_table()
    now = datetime.now(timezone.utc).isoformat()
    org_id = str(uuid.uuid4())
    item = strip_none({
        "id": org_id, "org_name": org_name, "org_code": org_code, "email": email,
        "org_description": org_description, "large_logo_url": large_logo_url,
        "small_logo_url": small_logo_url, "primary_color": primary_color,
        "secondary_color": secondary_color, "accent1_color": accent1_color,
        "accent2_color": accent2_color, "accent3_color": accent3_color,
        "bot_id": bot_id, "admin_set_password": admin_set_password,
        "created_at": now, "updated_at": now,
    })
    await tbl.put_item(Item=item)
    return clean(item)


async def get_auth_config(organization_id):
    tbl = await _auth_config_table()
    resp = await tbl.get_item(Key={"organization_id": str(organization_id)})
    item = resp.get("Item")
    return clean(item) if item else None


async def create_auth_config(organization_id, auth_type="LOCAL", okta_issuer=None, okta_client_id=None, is_enabled=False):
    tbl = await _auth_config_table()
    now = datetime.now(timezone.utc).isoformat()
    item = strip_none({
        "organization_id": str(organization_id), "id": str(uuid.uuid4()),
        "auth_type": auth_type, "okta_issuer": okta_issuer, "okta_client_id": okta_client_id,
        "is_enabled": is_enabled, "created_at": now, "updated_at": now,
    })
    await tbl.put_item(Item=item)


async def get_usergroup(group_id):
    tbl = await _usergroups_table()
    resp = await tbl.get_item(Key={"id": str(group_id)})
    item = resp.get("Item")
    return clean(item) if item else None
