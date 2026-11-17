from ..utils.query_loader import load_queries
from ..core.database import fetch, fetchrow, execute, ensure_pool
from ..utils.json_serializers import to_jsonb, from_jsonb
from ..utils.page_access import normalize_access, decide_access
from ..core.config import settings
from . import rbac_service

PAGE_RESOURCE_PREFIX = "page:"
PAGE_ACTION = "view"


def page_resource(slug: str) -> str:
    """The RBAC resource name of a published page, e.g. page:riyadha."""
    return f"{PAGE_RESOURCE_PREFIX}{slug}"

queries = load_queries()
pg_q = queries["pages"]


def _row(row) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    if "document" in d:
        d["document"] = from_jsonb(d.get("document"))
    return d


def _access_of(page) -> dict:
    """The page's access settings as plain lists (JSONB may come back as str)."""
    d = dict(page)
    return {
        "visibility": d.get("visibility") or "authenticated",
        "allowed_emails": from_jsonb(d.get("allowed_emails")) or [],
        "allowed_roles": from_jsonb(d.get("allowed_roles")) or [],
    }


class PagesService:
    """
    Stores View Builder pages for the client renderer.

    pages          -> one row per slug
    page_versions  -> every saved document (draft / published / archived)

    Builder flow : save_draft -> publish
    Client flow  : get_published (public, read-only)
    """

    async def list_pages(self):
        rows = await fetch(pg_q["list_pages"])
        out = []
        for r in rows:
            d = dict(r)
            d["allowed_emails"] = from_jsonb(d.get("allowed_emails")) or []
            d["allowed_roles"] = from_jsonb(d.get("allowed_roles")) or []
            out.append(d)
        return out

    async def _ensure_rbac_resource(self, slug: str, title: str) -> None:
        """
        Makes the page show up in the RBAC screens: resource "page:<slug>" with a
        "view" permission. Idempotent. If the RBAC tables do not exist yet it is
        skipped silently (the page is then simply not grantable until they do).
        """
        try:
            from ..db.repositories import rbac_repo
            name = page_resource(slug)
            res = await rbac_repo.get_resource_by_name(name)
            if not res:
                res = await rbac_repo.create_resource(name, f"Published page: {title}")
            if not await rbac_repo.get_permission_by_key(res["id"], PAGE_ACTION):
                await rbac_repo.create_permission(res["id"], PAGE_ACTION, f"View the published page {slug}")
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Could not register RBAC resource for page %s", slug)

    async def _page(self, slug: str):
        return await fetchrow(pg_q["get_page_by_slug"], slug)

    async def save_draft(self, slug: str, title: str, document: dict,
                         label: str | None, created_by: str | None,
                         access: dict | None = None,
                         project_id: int | None = None) -> dict:
        """Create the page if needed, then overwrite the open draft or start a new one."""
        page = await fetchrow(pg_q["upsert_page"], slug, title, created_by)
        await self._ensure_rbac_resource(slug, title)
        if project_id is not None:
            # Link the page to its project: only that project's members (and admins) may open it.
            page = await fetchrow(pg_q["set_project"], page["id"], int(project_id))
        if access is not None:
            a = normalize_access(access.get("visibility"), access.get("allowed_emails"), access.get("allowed_roles"))
            page = await fetchrow(
                pg_q["set_access"], page["id"], a["visibility"],
                to_jsonb(a["allowed_emails"]), to_jsonb(a["allowed_roles"]),
            )
        draft = await fetchrow(pg_q["get_latest_draft"], page["id"])
        if draft:
            row = await fetchrow(pg_q["update_draft"], draft["id"], to_jsonb(document), label)
        else:
            nxt = await fetchrow(pg_q["next_version"], page["id"])
            row = await fetchrow(
                pg_q["insert_version"], page["id"], nxt["version"], label,
                to_jsonb(document), created_by,
            )
        out = _row(row)
        out["slug"] = slug
        out["title"] = page["title"]
        out["access"] = _access_of(page)
        return out

    async def get_editable(self, slug: str):
        """What the builder opens: the latest draft, else the published version."""
        page = await self._page(slug)
        if not page:
            return None
        row = await fetchrow(pg_q["get_latest_draft"], page["id"])
        if not row:
            row = await fetchrow(pg_q["get_published_version"], page["id"])
        if not row:
            return None
        out = _row(row)
        out["slug"] = slug
        out["title"] = page["title"]
        out["access"] = _access_of(page)
        return out

    async def _viewer(self, user: dict | None) -> dict:
        """Who is asking: signed in?, admin?, email, RBAC role names."""
        if not user or not user.get("user_id"):
            return {"signed_in": False}
        from ..db.repositories import user_repo, rbac_repo
        email, roles = None, []
        try:
            u = await user_repo.get_by_user_id(user["user_id"])
            email = (u or {}).get("email")
        except Exception:
            pass
        try:
            roles = [r["name"] for r in await rbac_repo.get_user_roles(user["user_id"], all_projects=True)]
        except Exception:
            pass
        return {
            "signed_in": True,
            "is_admin": rbac_service.is_admin(user),
            "email": email,
            "roles": roles,
        }

    async def get_published(self, slug: str, user: dict | None = None):
        """
        What the client renderer loads. Returns (status, data):
          ('ok', page) | ('missing', None) | ('login', None) | ('forbidden', None)
        The access check happens here, before any page content is returned.
        """
        page = await self._page(slug)
        if not page or page["published_version"] is None:
            return "missing", None
        a = _access_of(page)
        viewer = await self._viewer(user)
        if a["visibility"] == "rbac":
            if not settings.RBAC_ENFORCE:
                a["visibility"] = "authenticated"   # RBAC switched off: any signed-in user
            elif viewer.get("signed_in"):
                viewer["has_permission"] = await rbac_service.user_has_permission(
                    user, page_resource(slug), PAGE_ACTION, all_projects=True
                )
        verdict = decide_access(
            a["visibility"], a["allowed_emails"], a["allowed_roles"],
            **viewer,
        )
        if verdict != "allow":
            return verdict, None
        # Project gate: a page that belongs to a project is only for that project's
        # users (admins always pass). Public pages stay public.
        page_project = dict(page).get("project_id")
        if (page_project is not None and a["visibility"] != "public"
                and not viewer.get("is_admin") and rbac_service.settings_project_isolation()):
            from ..idam.repositories import project_member_repo
            if not await project_member_repo.is_member(user["user_id"], page_project):
                return "forbidden", None
        row = await fetchrow(pg_q["get_version"], page["id"], page["published_version"])
        if not row:
            return "missing", None
        out = _row(row)
        return "ok", {
            "slug": slug,
            "title": page["title"],
            "version": out["version"],
            "published_at": out["published_at"],
            "document": out["document"],
        }

    async def list_versions(self, slug: str):
        page = await self._page(slug)
        if not page:
            return None
        rows = await fetch(pg_q["list_versions"], page["id"])
        return [dict(r) for r in rows]

    async def publish(self, slug: str, version: int | None = None):
        """
        Publish the given version (default: the latest draft). The previous
        published version becomes 'archived'. Passing an older version number
        is how you roll back.
        """
        page = await self._page(slug)
        if not page:
            return None
        await self._ensure_rbac_resource(slug, page["title"])
        if version is None:
            target = await fetchrow(pg_q["get_latest_draft"], page["id"])
        else:
            target = await fetchrow(pg_q["get_version"], page["id"], version)
        if not target:
            return None

        pool = await ensure_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(pg_q["archive_published"], page["id"])
                # Use fetch() (not fetchrow()) inside this transaction. fetchrow()
                # runs the statement with a row limit of 1, which leaves a suspended
                # portal open on the connection; CockroachDB then rejects the next
                # statement ("cannot perform operation sql.PrepareStmt while a
                # different portal is open"). fetch() runs it to completion.
                rows = await conn.fetch(pg_q["mark_published"], target["id"])
                if not rows:
                    # Raising rolls the transaction back, so the old published
                    # version is not archived by mistake.
                    raise RuntimeError("Could not mark the version as published")
                row = rows[0]
                await conn.execute(pg_q["set_published_version"], page["id"], row["version"])
        out = _row(row)
        out["slug"] = slug
        return out

    async def delete_page(self, slug: str):
        await execute(pg_q["soft_delete_page"], slug)
        return True