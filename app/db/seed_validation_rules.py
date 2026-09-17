"""
Seed the validation_rules table with the rules already hardcoded in the
frontend's src/validations/index.ts, so they show up via
GET /datastore/validation-rules instead of only ever coming from that
static file.

Safe to re-run — save_validation_rule() upserts (keyed by tag), so running
this again just re-writes the same 21 rows rather than duplicating them.

Usage (same way you'd run db/seed_admin.py — adjust the module path prefix
to match how that one is invoked in this project, e.g.):
    python -m app.db.seed_validation_rules
"""
import asyncio

from ..core.database import init_pool, close_pool


# Mirrors src/validations/index.ts exactly — same 21 tags, same category,
# same legacy {type, value, message} shape. Keep these two files in sync
# if the frontend's static defaults ever change.
RULES: dict[str, dict] = {

    # ── Presence ─────────────────────────────────────────────────────────
    "required":            {"type": "required",  "message": "This field is required",       "category": "common"},
    "required-name":       {"type": "required",  "message": "Name is required",             "category": "common"},
    "required-email":      {"type": "required",  "message": "Email is required",            "category": "common"},
    "required-country":    {"type": "required",  "message": "Country is required",          "category": "common"},
    "required-quantity":   {"type": "required",  "message": "Quantity is required",         "category": "common"},

    # ── String length ────────────────────────────────────────────────────
    "min-length-2":        {"type": "minLength", "value": 2,   "message": "At least 2 characters",   "category": "common"},
    "min-length-3":        {"type": "minLength", "value": 3,   "message": "At least 3 characters",   "category": "common"},
    "min-length-8":        {"type": "minLength", "value": 8,   "message": "At least 8 characters",   "category": "common"},
    "max-length-50":       {"type": "maxLength", "value": 50,  "message": "Maximum 50 characters",   "category": "common"},
    "max-length-255":      {"type": "maxLength", "value": 255, "message": "Maximum 255 characters",  "category": "common"},

    # ── Numeric range ────────────────────────────────────────────────────
    "min-1":               {"type": "min", "value": 1,    "message": "Minimum value is 1",      "category": "common"},
    "min-0":               {"type": "min", "value": 0,    "message": "Value cannot be negative", "category": "common"},
    "max-100":             {"type": "max", "value": 100,  "message": "Maximum value is 100",     "category": "common"},
    "max-1000":            {"type": "max", "value": 1000, "message": "Maximum value is 1000",    "category": "common"},

    # ── Format patterns ──────────────────────────────────────────────────
    "email-format":        {"type": "pattern", "value": r"^[^@\s]+@[^@\s]+\.[^@\s]+$",  "message": "Enter a valid email address",      "category": "common"},
    "phone-format":        {"type": "pattern", "value": r"^[+]?[0-9]{7,15}$",           "message": "Enter a valid phone number",       "category": "common"},
    "url-format":          {"type": "pattern", "value": r"^https?:\/\/.+",              "message": "Enter a valid URL (https://...)", "category": "common"},
    "alphanumeric":        {"type": "pattern", "value": r"^[a-zA-Z0-9]+$",              "message": "Only letters and numbers allowed", "category": "common"},
    "no-spaces":           {"type": "pattern", "value": r"^\S+$",                       "message": "No spaces allowed",               "category": "common"},

    # ── Custom / business rules ──────────────────────────────────────────
    "must-be-positive":    {"type": "custom", "value": "value > 0",     "message": "Value must be greater than zero", "category": "common"},
    "must-be-future-date": {"type": "custom", "value": "value > today", "message": "Date must be in the future",      "category": "common"},
}


async def seed():
    await init_pool()
    from .repositories.postgres.datastore_repo import save_validation_rule

    saved, failed = 0, 0
    for tag, rule in RULES.items():
        result = await save_validation_rule(tag, rule)
        if result.get("status") == "success":
            saved += 1
            print(f"  ✓ {tag}")
        else:
            failed += 1
            print(f"  ✗ {tag}: {result.get('message')}")

    await close_pool()
    print(f"\nDone — {saved} rule(s) saved, {failed} failed.")


if __name__ == "__main__":
    asyncio.run(seed())