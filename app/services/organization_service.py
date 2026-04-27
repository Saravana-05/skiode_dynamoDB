from datetime import datetime, timezone

from ..db.repositories import user_repo, organization_repo
from ..core.config import settings
from ..utils.mail import send_email
from ..utils.auth_utils import create_reset_token


async def create_organization(payload: dict, current_user: dict):
    try:
        email = payload.get("email")
        if not email:
            return {"status": "error", "message": "Email is required"}

        email = email.strip().lower()

        # Duplicate checks
        existing_user = await user_repo.get_by_email(email)
        if existing_user:
            return {"status": "error", "message": f"User with email '{email}' already exists"}

        # Create organization
        org = await organization_repo.create_org(
            org_name=payload.get("org_name"),
            org_code=payload.get("org_code"),
            email=email,
            org_description=payload.get("org_description"),
            large_logo_url=payload.get("large_logo_url"),
            small_logo_url=payload.get("small_logo_url"),
            primary_color=payload.get("primary_color"),
            secondary_color=payload.get("secondary_color"),
            accent1_color=payload.get("accent1_color"),
            accent2_color=payload.get("accent2_color"),
            accent3_color=payload.get("accent3_color"),
            bot_id=payload.get("bot_id") or None,
            admin_set_password=payload.get("admin_set_password") or False,
        )

        org_id = org["id"]

        # Auth config
        existing_auth = await organization_repo.get_auth_config(org_id)
        if not existing_auth:
            await organization_repo.create_auth_config(org_id, "LOCAL", None, None, False)

        # Unique username generation
        base_username = email.split("@")[0]
        username = email
        counter = 1

        while True:
            exists = await user_repo.get_by_username(username)
            if not exists:
                break
            username = f"{base_username}{counter}"
            counter += 1

        # Create user
        result = await user_repo.create(
            username=username,
            email=email,
            password="!",
            is_superuser=True,
            is_staff=True,
            is_active=True,
            date_joined=datetime.now(timezone.utc).isoformat(),
            user_name=base_username,
            organization_id=org_id,
        )

        user_id = result["user_id"]

        # Reset token + email
        reset_token = create_reset_token(user_id)
        reset_link = f"{settings.SITE_URL}/reset-password/{user_id}/{reset_token}"
        print("reset_link--", reset_link)

        try:
            await send_email(
                to=email,
                subject="Password Reset",
                body=f"Here is your password reset link: {reset_link}",
            )
        except Exception as e:
            print("EMAIL FAILED:", str(e))

        return {"status": "success", "data": org}

    except Exception as e:
        return {"status": "error", "message": str(e)}
