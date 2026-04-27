import asyncio
import jwt
import re

from ..core.config import settings
from ..db.repositories import user_repo, organization_repo
from ..utils.password import verify_password, hash_password
from ..utils.jwt import create_tokens
from ..utils.okta import decode_okta_token

import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)


async def login_user(payload):
    try:
        mail_id = payload.get("mail_id")
        password = payload.get("password")
        id_token = payload.get("id_token") or None
        if id_token and len(id_token.split(".")) != 3:
            id_token = None  # ignore non-JWT placeholder values

        logger.info(f"Incoming login request | mail_id: {mail_id} | has_id_token: {bool(id_token)}")

        if not mail_id and not id_token:
            return {"status": "error", "message": "Email or id_token required"}

        if id_token:
            try:
                unverified = jwt.get_unverified_claims(id_token)
                mail_id = unverified.get("email") or unverified.get("sub")
            except Exception:
                return {"status": "error", "message": "Invalid id_token"}

        mail_id = mail_id.strip().lower()
        logger.info(f"Normalized mail_id: {mail_id}")

        # Fetch user from DynamoDB
        user = await user_repo.get_by_email(mail_id)

        if not user:
            logger.warning(f"User not found: {mail_id}")
            return {"status": "error", "message": "User not found"}

        logger.info(f"User found | user_id: {user.get('user_id')}")

        if not user.get("is_active"):
            return {"status": "error", "message": "User inactive"}

        # Fetch org, auth config, usergroup in parallel
        org_id = user.get("organization_id")
        usergroup_id = user.get("usergroup_id")

        org, auth_config, usergroup = await asyncio.gather(
            organization_repo.get_by_id(org_id) if org_id else _none(),
            organization_repo.get_auth_config(org_id) if org_id else _none(),
            organization_repo.get_usergroup(usergroup_id) if usergroup_id else _none(),
        )

        # Auth type decision
        auth_type = "LOCAL"

        if auth_config and auth_config.get("is_enabled") and auth_config.get("auth_type") == "OKTA":
            auth_type = "OKTA"
            logger.info("Auth type: OKTA")

            if not id_token:
                return {"status": "error", "message": "This organization uses Okta", "auth_type": "OKTA"}

            try:
                claims = decode_okta_token(id_token, auth_config["okta_issuer"], auth_config["okta_client_id"])
                logger.info("Okta token validated")
            except Exception as e:
                logger.error(f"Okta validation failed: {str(e)}")
                return {"status": "error", "message": str(e)}

            if claims.get("email") and claims.get("email").lower() != mail_id:
                return {"status": "error", "message": "Email mismatch"}

        else:
            logger.info("Auth type: LOCAL")
            if not password:
                return {"status": "error", "message": "Password required"}

            try:
                is_valid = verify_password(password, user["password"])
            except Exception as e:
                logger.error(f"Password verification error: {str(e)}")
                return {"status": "error", "message": "Password verification failed"}

            if not is_valid:
                return {"status": "error", "message": "Invalid credentials"}

        # Determine role
        is_superuser = user.get("is_superuser", False)
        resolved_org_id = org.get("id") if org else None

        if is_superuser and not resolved_org_id:
            role = "PRODUCT_ADMIN"
        elif is_superuser and resolved_org_id:
            role = "ORG_ADMIN"
        else:
            role = "USER"

        tokens = create_tokens({
            "user_id": user["user_id"],
            "org_id": resolved_org_id,
            "auth_type": auth_type,
            "role": role,
        })

        usergroup_name = usergroup.get("group_name") if usergroup else "is_superuser"

        return {
            "status": "success",
            "data": {
                "access": tokens["access"],
                "refresh": tokens["refresh"],
                "user_id": user["user_id"],
                "login_user": user["user_id"],
                "user_name": user.get("user_name"),
                "mail_id": mail_id,
                "usergroup_id": usergroup_id,
                "usergroup_name": usergroup_name,
                "usergroup_ref_id": usergroup.get("ref_id") if usergroup else None,
                "organization_id": resolved_org_id,
                "organization_code": org.get("org_code") if org else None,
                "user_profile_pic": user.get("profile_pic"),
                "user_profile_schema": user.get("user_profile_schema") or "",
                "is_lead": user.get("is_lead"),
                "auth_type": auth_type,
                "role": role,
            },
        }

    except Exception as e:
        logger.exception(f"Unexpected error in login: {str(e)}")
        return {"status": "error", "message": "Internal server error"}


async def reset_password(user_id: str, token: str, new_password: str):
    try:
        if len(new_password) < 8:
            return {"status": "error", "message": "Password must be at least 8 characters"}
        if not re.search(r"[A-Z]", new_password):
            return {"status": "error", "message": "Must contain uppercase letter"}
        if not re.search(r"[0-9]", new_password):
            return {"status": "error", "message": "Must contain number"}
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", new_password):
            return {"status": "error", "message": "Must contain a special character"}
        if " " in new_password:
            return {"status": "error", "message": "Password should not contain spaces"}

        payload = jwt.decode(token, settings.DJANGO_SECRET_KEY, algorithms=["HS256"])

        if payload.get("user_id") != user_id:
            return {"status": "error", "message": "Invalid token"}

        if payload.get("type") != "reset":
            return {"status": "error", "message": "Invalid token type"}

        hashed_password = hash_password(new_password)
        await user_repo.update_password(user_id, hashed_password)

        return {"status": "success", "message": "Password reset successful. Please login."}

    except jwt.ExpiredSignatureError:
        return {"status": "error", "message": "Token expired"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


async def _none():
    return None
