"""IdamUser — domain object for a row of idam."user".

Replicates app/domain/user_domain.py (User + UserData) as one flat object whose
fields match the table columns, the same way the rbac_* tables map to dicts.
"""
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional


@dataclass
class IdamUser:
    id: Optional[int] = None
    username: str = ""
    email: str = ""
    password: str = "!"
    is_superuser: bool = False
    is_staff: bool = False
    is_active: bool = True
    date_joined: Optional[datetime] = None
    # ── UserData ──
    user_name: Optional[str] = None
    profile_pic: Optional[str] = None
    user_profile_schema: Optional[str] = None
    is_lead: bool = False
    organization_id: Optional[int] = None
    usergroup_id: Optional[int] = None
    ref_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @classmethod
    def from_row(cls, row) -> "IdamUser":
        return cls(**{k: row[k] for k in cls.__dataclass_fields__ if k in row.keys()})

    def to_public_dict(self) -> dict:
        """Safe to return from an API: no password, ids as strings (matches rbac)."""
        d = asdict(self)
        d.pop("password", None)
        for k in ("id", "organization_id", "usergroup_id"):
            d[k] = str(d[k]) if d[k] is not None else None
        for k in ("date_joined", "created_at", "updated_at"):
            d[k] = d[k].isoformat() if d[k] else None
        d["user_id"] = d.pop("id")
        return d