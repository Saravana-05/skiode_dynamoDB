from ....core.database import execute, fetchrow


async def get_by_code(org_code):
    row = await fetchrow("SELECT id, org_code, org_name FROM custom_components_organization WHERE org_code = $1", org_code)
    if not row:
        return None
    d = dict(row)
    d["id"] = str(d["id"])
    return d


async def get_by_id(org_id):
    row = await fetchrow("SELECT * FROM custom_components_organization WHERE id = $1", int(org_id))
    if not row:
        return None
    d = dict(row)
    d["id"] = str(d["id"])
    return d


async def create_org(org_name, org_code, email, org_description=None, large_logo_url=None,
                     small_logo_url=None, primary_color=None, secondary_color=None,
                     accent1_color=None, accent2_color=None, accent3_color=None,
                     bot_id=None, admin_set_password=False):
    row = await fetchrow(
        """
        INSERT INTO custom_components_organization
            (org_name, org_code, email, org_description, large_logo_url, small_logo_url,
             primary_color, secondary_color, accent1_color, accent2_color, accent3_color,
             bot_id, admin_set_password)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
        RETURNING *
        """,
        org_name, org_code, email, org_description, large_logo_url, small_logo_url,
        primary_color, secondary_color, accent1_color, accent2_color, accent3_color,
        bot_id, admin_set_password,
    )
    d = dict(row)
    d["id"] = str(d["id"])
    return d


async def get_auth_config(organization_id):
    row = await fetchrow(
        "SELECT * FROM custom_components_organizationauthconfig WHERE organization_id = $1",
        int(organization_id),
    )
    if not row:
        return None
    d = dict(row)
    d["organization_id"] = str(d["organization_id"])
    return d


async def create_auth_config(organization_id, auth_type="LOCAL", okta_issuer=None, okta_client_id=None, is_enabled=False):
    await execute(
        """
        INSERT INTO custom_components_organizationauthconfig
            (organization_id, auth_type, okta_issuer, okta_client_id, is_enabled)
        VALUES ($1,$2,$3,$4,$5)
        """,
        int(organization_id), auth_type, okta_issuer, okta_client_id, is_enabled,
    )


async def get_usergroup(group_id):
    row = await fetchrow(
        "SELECT id, group_name, ref_id FROM custom_components_usergroup WHERE id = $1",
        int(group_id),
    )
    if not row:
        return None
    d = dict(row)
    d["id"] = str(d["id"])
    return d
