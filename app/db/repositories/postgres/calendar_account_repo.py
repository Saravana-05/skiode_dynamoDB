from ....core.database import execute, fetch, fetchrow


async def upsert(organization_id, user_id, provider, access_token, refresh_token, token_expiry):
    row = await fetchrow(
        """
        INSERT INTO calendar_accounts (organization_id, user_id, provider, access_token, refresh_token, token_expiry)
        VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT (user_id, provider) DO UPDATE SET
            access_token  = EXCLUDED.access_token,
            refresh_token = EXCLUDED.refresh_token,
            token_expiry  = EXCLUDED.token_expiry,
            is_active     = TRUE,
            updated_at    = CURRENT_TIMESTAMP
        RETURNING id, organization_id, user_id, provider
        """,
        int(organization_id), int(user_id), provider, access_token, refresh_token, token_expiry,
    )
    return dict(row) if row else None


async def get_user_accounts(user_id):
    rows = await fetch(
        "SELECT id, organization_id, user_id, provider, access_token, refresh_token, token_expiry, is_active "
        "FROM calendar_accounts WHERE user_id = $1 AND is_active = true",
        int(user_id),
    )
    return [dict(r) for r in rows]


async def get_provider_account(user_id, provider):
    row = await fetchrow(
        "SELECT * FROM calendar_accounts WHERE user_id = $1 AND provider = $2",
        int(user_id), provider,
    )
    return dict(row) if row else None


async def deactivate(account_id):
    await execute(
        "UPDATE calendar_accounts SET is_active = FALSE, updated_at = NOW() WHERE id = $1",
        int(account_id),
    )


async def update_tokens(account_id, access_token, refresh_token):
    await execute(
        "UPDATE calendar_accounts SET access_token = $1, refresh_token = $2, updated_at = NOW() WHERE id = $3",
        access_token, refresh_token, int(account_id),
    )
