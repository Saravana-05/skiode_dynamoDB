import os
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, field_validator

from ..core.security import verify_token
from ..services.pages_service import PagesService
from ..utils.responses import success_response, error_response

router = APIRouter(prefix="/pages", tags=["Pages"])

# Auth for the builder-side routes.
#   PAGES_REQUIRE_AUTH=false (default): same as /user-interaction and /grid-layout.
#       A valid Bearer token is used to record who saved the page, but a
#       missing / expired token does NOT block saving.
#   PAGES_REQUIRE_AUTH=true: a valid token is mandatory (401/403 otherwise).
# GET /pages/{slug}/published is always public.
PAGES_REQUIRE_AUTH = os.getenv("PAGES_REQUIRE_AUTH", "false").lower() == "true"
_bearer = HTTPBearer(auto_error=False)


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(_bearer)) -> dict:
    if credentials is None:
        if PAGES_REQUIRE_AUTH:
            from fastapi import HTTPException
            raise HTTPException(status_code=401, detail="Not authenticated")
        return {}
    try:
        return verify_token(credentials.credentials)
    except Exception:
        if PAGES_REQUIRE_AUTH:
            raise
        return {}  # stale token: still allowed, just anonymous


pages_service = PagesService()

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,99}$")


class PageDocument(BaseModel):
    """
    The full, renderable page. Stored as-is in page_versions.document.

      schemaVersion  int, bump when the format changes
      instances      builder ComponentInstance tree (pluginId, configs, query, ...)
      layouts        react-grid-layout object, e.g. {"lg": [{i,x,y,w,h}, ...]}
      templates      saved templates referenced by tpl:<id> links, inlined so the
                     client never needs /saved-templates
    """
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 1
    instances: List[Dict[str, Any]]
    layouts: Dict[str, Any] = {}
    templates: Dict[str, Any] = {}


class PageAccess(BaseModel):
    """Who may view the published page."""
    visibility: str = "authenticated"      # public | authenticated | restricted
    allowed_emails: List[str] = []         # used when restricted
    allowed_roles: List[str] = []          # RBAC role names, used when restricted

    @field_validator("visibility")
    @classmethod
    def _vis(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in ("public", "authenticated", "restricted"):
            raise ValueError("visibility must be public, authenticated or restricted")
        return v


class SaveDraftRequest(BaseModel):
    title: str = "Untitled Page"
    document: PageDocument
    label: Optional[str] = None
    access: Optional[PageAccess] = None    # omit to leave the page's access unchanged
    project_id: Optional[int] = None       # project this page belongs to (omit = unchanged)


class PublishRequest(BaseModel):
    version: Optional[int] = None  # omit = latest draft; older number = rollback


def get_optional_user(credentials: HTTPAuthorizationCredentials = Depends(_bearer)) -> Optional[dict]:
    """Viewer for the public route: a valid token identifies them, anything else = anonymous."""
    if credentials is None:
        return None
    try:
        return verify_token(credentials.credentials)
    except Exception:
        return None


def _bad_slug(slug: str):
    if not SLUG_RE.match(slug):
        return JSONResponse(
            content=error_response("Slug must be lowercase letters, numbers, - or _"),
            status_code=400,
        )
    return None


def _not_found(what: str):
    return JSONResponse(content=error_response(f"{what} not found"), status_code=404)


def _err(e: Exception):
    return JSONResponse(content=error_response(str(e)), status_code=400)


@router.get("/")
async def list_pages(current_user: dict = Depends(get_current_user)):
    try:
        return success_response(await pages_service.list_pages())
    except Exception as e:
        return _err(e)


# Public: used by the client renderer app (read-only, published pages only).
# Access rules (public / signed-in / selected users+roles) are enforced here:
# 401 = sign in first, 403 = signed in but not allowed to see this page.
@router.get("/{slug}/published")
async def get_published(slug: str, viewer: Optional[dict] = Depends(get_optional_user)):
    try:
        status, result = await pages_service.get_published(slug, viewer)
        if status == "ok":
            return success_response(result)
        if status == "login":
            return JSONResponse(content=error_response("Please sign in to view this page", 401), status_code=401)
        if status == "forbidden":
            return JSONResponse(content=error_response("You do not have access to this page", 403), status_code=403)
        return _not_found("Published page")
    except Exception as e:
        return _err(e)


@router.get("/{slug}/draft")
async def get_editable(slug: str, current_user: dict = Depends(get_current_user)):
    try:
        result = await pages_service.get_editable(slug)
        return success_response(result) if result else _not_found("Page")
    except Exception as e:
        return _err(e)


@router.put("/{slug}/draft")
async def save_draft(slug: str, payload: SaveDraftRequest,
                     current_user: dict = Depends(get_current_user)):
    if (bad := _bad_slug(slug)):
        return bad
    try:
        result = await pages_service.save_draft(
            slug, payload.title, payload.document.model_dump(),
            payload.label, (str(current_user["user_id"]) if current_user.get("user_id") else None),
            payload.access.model_dump() if payload.access else None,
            payload.project_id,
        )
        return success_response(result)
    except Exception as e:
        return _err(e)


@router.post("/{slug}/publish")
async def publish(slug: str, payload: PublishRequest = PublishRequest(),
                  current_user: dict = Depends(get_current_user)):
    try:
        result = await pages_service.publish(slug, payload.version)
        return success_response(result) if result else _not_found("Version")
    except Exception as e:
        return _err(e)


@router.get("/{slug}/versions")
async def list_versions(slug: str, current_user: dict = Depends(get_current_user)):
    try:
        result = await pages_service.list_versions(slug)
        return success_response(result) if result is not None else _not_found("Page")
    except Exception as e:
        return _err(e)


@router.delete("/{slug}")
async def delete_page(slug: str, current_user: dict = Depends(get_current_user)):
    try:
        await pages_service.delete_page(slug)
        return success_response({"message": "Page deleted"})
    except Exception as e:
        return _err(e)