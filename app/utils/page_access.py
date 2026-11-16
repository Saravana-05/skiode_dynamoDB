"""Who may view a published page. Pure functions (no DB) so they are easy to test.

visibility
  rbac           (default) signed in AND allowed by the DMOC RBAC: the user (through
                 their roles) holds the "view" permission on the resource "page:<slug>".
                 Admins always pass. Managed in the RBAC screens, not per page.
  public         anyone, no login (only the layout; data tables still need a login)
  authenticated  any signed-in user
  restricted     signed-in AND (admin OR email in allowed_emails OR has a role in allowed_roles)
"""
from typing import Iterable, List, Optional

VISIBILITIES = ("rbac", "public", "authenticated", "restricted")
DEFAULT_VISIBILITY = "rbac"


def _clean_list(values: Optional[Iterable[str]], lower: bool) -> List[str]:
    out: List[str] = []
    for v in values or []:
        s = str(v).strip()
        if not s:
            continue
        s = s.lower() if lower else s
        if s not in out:
            out.append(s)
    return out


def normalize_access(visibility: Optional[str], emails: Optional[Iterable[str]], roles: Optional[Iterable[str]]) -> dict:
    vis = (visibility or DEFAULT_VISIBILITY).strip().lower()
    if vis not in VISIBILITIES:
        raise ValueError(f"visibility must be one of {', '.join(VISIBILITIES)}")
    return {
        "visibility": vis,
        "allowed_emails": _clean_list(emails, lower=True),
        "allowed_roles": _clean_list(roles, lower=False),
    }


def decide_access(
    visibility: Optional[str],
    allowed_emails: Optional[Iterable[str]],
    allowed_roles: Optional[Iterable[str]],
    *,
    signed_in: bool,
    is_admin: bool = False,
    email: Optional[str] = None,
    roles: Optional[Iterable[str]] = None,
    has_permission: Optional[bool] = None,
) -> str:
    """Returns 'allow', 'login' (sign in first) or 'forbidden' (signed in but not permitted)."""
    vis = (visibility or DEFAULT_VISIBILITY).lower()
    if vis == "public":
        return "allow"
    if not signed_in:
        return "login"
    if vis == "authenticated":
        return "allow"
    if vis == "rbac":
        # has_permission = result of the RBAC check "view page:<slug>" (done by the caller)
        return "allow" if (is_admin or has_permission) else "forbidden"
    # restricted
    if is_admin:
        return "allow"
    emails = {e.lower() for e in _clean_list(allowed_emails, lower=True)}
    if email and email.strip().lower() in emails:
        return "allow"
    wanted = {r.lower() for r in _clean_list(allowed_roles, lower=False)}
    have = {str(r).strip().lower() for r in (roles or [])}
    if wanted & have:
        return "allow"
    return "forbidden"