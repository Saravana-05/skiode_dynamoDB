"""
User repository — PostgreSQL implementation, backed by idam."user".

The old auth_user / form_generator_userdata tables are no longer read or
written. Function names, arguments and returned dict shapes are unchanged,
so login, password reset, organization creation and RBAC work as before.
Table + domain model live in app/idam.
"""
from ....idam.repositories import user_repo as idam_repo
from ....idam.domain.user import IdamUser


def _s(v):
    return str(v) if v is not None else None


def _login_dict(u: IdamUser) -> dict:
    return {
        "user_id": str(u.id),
        "username": u.username,
        "password": u.password,
        "is_superuser": u.is_superuser,
        "is_active": u.is_active,
        "user_name": u.user_name,
        "email": u.email,
        "profile_pic": u.profile_pic,
        "user_profile_schema": u.user_profile_schema,
        "is_lead": u.is_lead,
        "organization_id": _s(u.organization_id),
        "usergroup_id": _s(u.usergroup_id),
    }


async def get_by_email(email):
    u = await idam_repo.get_by_email(email)
    return _login_dict(u) if u else None


async def get_by_user_id(user_id):
    u = await idam_repo.get_by_id(user_id)
    return _login_dict(u) if u else None


async def get_by_username(username):
    u = await idam_repo.get_by_username(username)
    return {"id": u.id} if u else None


async def create(username, email, password, is_superuser, is_staff, is_active,
                 date_joined, user_name, organization_id, usergroup_id=None,
                 profile_pic=None, is_lead=False):
    u = await idam_repo.create(
        username=username, email=email, password=password,
        is_superuser=is_superuser, is_staff=is_staff, is_active=is_active,
        date_joined=date_joined, user_name=user_name,
        organization_id=organization_id, usergroup_id=usergroup_id,
        profile_pic=profile_pic, is_lead=is_lead,
    )
    return {"user_id": str(u.id), "email": u.email}


async def update_password(user_id, hashed_password):
    await idam_repo.update_password(user_id, hashed_password)