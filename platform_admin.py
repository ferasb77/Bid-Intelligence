"""
platform_admin.py — Super Admin MVP service layer (server-side only).

Platform-level administration of client organizations and user accounts:
list/create organizations, list/create users, assign memberships
(client-admin = organization role 'admin', or 'member'), issue expiring
password-setup links, disable/re-enable users, and an append-only audit
trail.

Authority model
---------------
* Platform authority comes ONLY from `public.platform_admins`
  (migration 024), re-read from the database on EVERY call. An organization
  'owner'/'admin' membership is tenant-scoped and is never treated as
  platform authority.
* Nothing in this module writes `platform_admins`. Platform authority is
  granted out-of-band by the owner (SQL), so no console path can grant it,
  including to oneself.
* Every privileged operation uses the server-side service-role client
  (`database.get_service_client()`), including Supabase Auth admin calls via
  `client.auth.admin`. No key, token, or setup link is ever logged or written
  to the audit trail. A setup link is returned once to the caller for
  display to the authenticated platform admin.

Caller identity
---------------
`actor_user_id` / `actor_email` must come from a server-verified Supabase Auth
session (auth_session.sign_in in admin_console.py) — never from user input.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import quote, urlparse

import database as db

ASSIGNABLE_ROLES = ("admin", "member")  # 'admin' is the client-admin role
ROLE_LABELS = {"admin": "Client admin", "member": "Member", "owner": "Owner (legacy)"}

# GoTrue ban duration used for "disabled" (~100 years); "none" lifts a ban.
_DISABLE_BAN_DURATION = "876000h"

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


class PlatformAdminDenied(Exception):
    """The caller is not a platform admin, or the action is not permitted."""


class PlatformAdminError(Exception):
    """A validation or backend failure. The message is safe to display."""


@dataclass(frozen=True)
class PlatformAdminActor:
    user_id: str
    email: str


# ── Internals ────────────────────────────────────────────────────────────

def _client(sb=None):
    return sb if sb is not None else db.get_service_client()


def _rows(resp) -> list:
    return list(getattr(resp, "data", None) or [])


def _attr(obj, name, default=None):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _parse_ts(value) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def user_is_disabled(user) -> bool:
    banned_until = _parse_ts(_attr(user, "banned_until"))
    return banned_until is not None and banned_until > datetime.now(timezone.utc)


def _require_uuid(value: str, label: str) -> str:
    if not isinstance(value, str) or not _UUID_RE.match(value):
        raise PlatformAdminError(f"Invalid {label}.")
    return value.lower()


def _audit(sb, actor_user_id, actor_email, action, outcome, *, target_user_id=None,
           target_email=None, organization_id=None, details=None) -> None:
    """Append one audit row. Raises if the audit write fails. A privileged
    action whose audit row cannot be written must not be reported as
    silently successful."""
    def _uuid_or_none(v):
        return str(v).lower() if v and _UUID_RE.match(str(v)) else None

    row = {
        "actor_user_id": _uuid_or_none(actor_user_id),
        "actor_email": actor_email,
        "action": action,
        "outcome": outcome,
        "target_user_id": _uuid_or_none(target_user_id),
        "target_email": target_email,
        "organization_id": _uuid_or_none(organization_id),
        "details": details or {},
    }
    sb.table("platform_admin_audit_log").insert(row).execute()


def is_platform_admin(user_id: str, sb=None) -> bool:
    """Fresh, uncached lookup in public.platform_admins (service role)."""
    if not user_id or not _UUID_RE.match(str(user_id)):
        return False
    sb = _client(sb)
    rows = _rows(sb.table("platform_admins").select("user_id").eq("user_id", str(user_id)).execute())
    return len(rows) == 1


def require_platform_admin(actor_user_id: str, actor_email: str, action: str, sb=None) -> PlatformAdminActor:
    """Gate for every operation. A non-admin attempt is audited as 'denied'
    and raises PlatformAdminDenied."""
    sb = _client(sb)
    if not is_platform_admin(actor_user_id, sb):
        try:
            _audit(sb, actor_user_id, actor_email, action, "denied",
                   details={"reason": "not_platform_admin"})
        except Exception:
            pass  # denial stands even if the audit write fails
        raise PlatformAdminDenied("Platform administrator authority is required.")
    return PlatformAdminActor(user_id=str(actor_user_id), email=actor_email or "")


def _get_auth_user(sb, user_id: str):
    try:
        resp = sb.auth.admin.get_user_by_id(user_id)
    except Exception:
        raise PlatformAdminError("User not found.")
    user = _attr(resp, "user")
    if user is None:
        raise PlatformAdminError("User not found.")
    return user


def _organization_exists(sb, organization_id: str) -> dict:
    rows = _rows(sb.table("organizations").select("id, name").eq("id", organization_id).execute())
    if not rows:
        raise PlatformAdminError("Organization not found.")
    return rows[0]


def _run(sb, actor: PlatformAdminActor, action: str, fn, *, target_user_id=None,
         target_email=None, organization_id=None, details=None, target_from_result=None):
    """Execute a privileged mutation and audit its outcome."""
    try:
        result = fn()
    except PlatformAdminError as e:
        _audit(sb, actor.user_id, actor.email, action, "error", target_user_id=target_user_id,
               target_email=target_email, organization_id=organization_id,
               details={**(details or {}), "error": str(e)})
        raise
    except Exception as e:
        _audit(sb, actor.user_id, actor.email, action, "error", target_user_id=target_user_id,
               target_email=target_email, organization_id=organization_id,
               details={**(details or {}), "error": type(e).__name__})
        raise PlatformAdminError("The operation failed. No partial change was reported as successful.")
    if target_from_result is not None:
        target_user_id = target_from_result(result)
    _audit(sb, actor.user_id, actor.email, action, "success", target_user_id=target_user_id,
           target_email=target_email, organization_id=organization_id, details=details)
    return result


# ── Organizations ────────────────────────────────────────────────────────

def list_organizations(actor_user_id: str, actor_email: str, sb=None) -> list[dict]:
    sb = _client(sb)
    require_platform_admin(actor_user_id, actor_email, "list_organizations", sb)
    orgs = _rows(sb.table("organizations").select("id, name, slug, created_at").order("name").execute())
    members = _rows(sb.table("organization_members").select("organization_id, role").execute())
    counts: dict[str, dict] = {}
    for m in members:
        c = counts.setdefault(m["organization_id"], {"members": 0, "admins": 0})
        c["members"] += 1
        if m.get("role") in ("admin", "owner"):
            c["admins"] += 1
    for o in orgs:
        c = counts.get(o["id"], {"members": 0, "admins": 0})
        o["member_count"] = c["members"]
        o["admin_count"] = c["admins"]
    return orgs


def create_organization(actor_user_id: str, actor_email: str, name: str, slug: str, sb=None) -> dict:
    sb = _client(sb)
    actor = require_platform_admin(actor_user_id, actor_email, "create_organization", sb)
    name = (name or "").strip()
    slug = (slug or "").strip().lower()

    def _do():
        if not name or len(name) > 200:
            raise PlatformAdminError("Organization name is required (max 200 characters).")
        if not _SLUG_RE.match(slug):
            raise PlatformAdminError("Slug must be 1-64 lowercase letters, digits, or hyphens.")
        if _rows(sb.table("organizations").select("id").eq("slug", slug).execute()):
            raise PlatformAdminError("An organization with that slug already exists.")
        rows = _rows(sb.table("organizations").insert({"name": name, "slug": slug}).execute())
        if not rows:
            raise PlatformAdminError("Organization was not created.")
        return rows[0]

    org = _run(sb, actor, "create_organization", _do, details={"name": name, "slug": slug})
    return org


# ── Users ────────────────────────────────────────────────────────────────

def _all_auth_users(sb) -> list:
    users, page, per_page = [], 1, 200
    while True:
        batch = sb.auth.admin.list_users(page=page, per_page=per_page) or []
        users.extend(batch)
        if len(batch) < per_page:
            return users
        page += 1


def list_users(actor_user_id: str, actor_email: str, sb=None) -> list[dict]:
    sb = _client(sb)
    require_platform_admin(actor_user_id, actor_email, "list_users", sb)
    users = _all_auth_users(sb)
    orgs = {o["id"]: o["name"] for o in _rows(sb.table("organizations").select("id, name").execute())}
    memberships = _rows(sb.table("organization_members").select("organization_id, user_id, role").execute())
    admins = {r["user_id"] for r in _rows(sb.table("platform_admins").select("user_id").execute())}
    by_user: dict[str, list] = {}
    for m in memberships:
        by_user.setdefault(m["user_id"], []).append({
            "organization_id": m["organization_id"],
            "organization_name": orgs.get(m["organization_id"], ""),
            "role": m["role"],
        })
    out = []
    for u in users:
        uid = str(_attr(u, "id"))
        out.append({
            "id": uid,
            "email": _attr(u, "email") or "",
            "created_at": _attr(u, "created_at"),
            "last_sign_in_at": _attr(u, "last_sign_in_at"),
            "disabled": user_is_disabled(u),
            "is_platform_admin": uid in admins,
            "memberships": by_user.get(uid, []),
        })
    out.sort(key=lambda r: r["email"])
    return out


def create_user(actor_user_id: str, actor_email: str, email: str, organization_id: str,
                role: str, sb=None) -> dict:
    """Create a confirmed Supabase Auth user with NO password, plus exactly
    one membership. The user sets their own password via a setup link."""
    sb = _client(sb)
    actor = require_platform_admin(actor_user_id, actor_email, "create_user", sb)
    email = (email or "").strip().lower()

    def _do():
        if not _EMAIL_RE.match(email) or len(email) > 254:
            raise PlatformAdminError("A valid email address is required.")
        if role not in ASSIGNABLE_ROLES:
            raise PlatformAdminError("Role must be client admin or member.")
        org_id = _require_uuid(organization_id, "organization")
        _organization_exists(sb, org_id)
        try:
            resp = sb.auth.admin.create_user({"email": email, "email_confirm": True})
        except Exception:
            raise PlatformAdminError("The account could not be created (it may already exist).")
        user = _attr(resp, "user")
        uid = str(_attr(user, "id")) if user is not None else ""
        if not _UUID_RE.match(uid):
            raise PlatformAdminError("The account could not be created.")
        try:
            sb.table("organization_members").insert(
                {"organization_id": org_id, "user_id": uid, "role": role}).execute()
        except Exception:
            try:
                sb.auth.admin.delete_user(uid)  # compensate: no orphan account
            except Exception:
                pass
            raise PlatformAdminError("Membership could not be created; the new account was removed.")
        return {"id": uid, "email": email, "organization_id": org_id, "role": role}

    created = _run(sb, actor, "create_user", _do, target_email=email,
                   organization_id=organization_id if isinstance(organization_id, str) else None,
                   details={"role": role}, target_from_result=lambda r: r["id"])
    return created


def set_membership(actor_user_id: str, actor_email: str, target_user_id: str,
                   organization_id: str, role: str, sb=None) -> None:
    """Add a membership or change its role (client admin / member)."""
    sb = _client(sb)
    actor = require_platform_admin(actor_user_id, actor_email, "set_membership", sb)

    def _do():
        uid = _require_uuid(target_user_id, "user")
        org_id = _require_uuid(organization_id, "organization")
        if role not in ASSIGNABLE_ROLES:
            raise PlatformAdminError("Role must be client admin or member.")
        _get_auth_user(sb, uid)
        _organization_exists(sb, org_id)
        existing = _rows(sb.table("organization_members").select("role")
                         .eq("organization_id", org_id).eq("user_id", uid).execute())
        if existing and existing[0].get("role") == "owner":
            raise PlatformAdminError("Legacy 'owner' memberships are not changed from the console.")
        if existing:
            sb.table("organization_members").update({"role": role}) \
                .eq("organization_id", org_id).eq("user_id", uid).execute()
        else:
            sb.table("organization_members").insert(
                {"organization_id": org_id, "user_id": uid, "role": role}).execute()
        return existing[0].get("role") if existing else None

    _run(sb, actor, "set_membership", _do, target_user_id=target_user_id,
         organization_id=organization_id, details={"role": role})


def remove_membership(actor_user_id: str, actor_email: str, target_user_id: str,
                      organization_id: str, sb=None) -> None:
    sb = _client(sb)
    actor = require_platform_admin(actor_user_id, actor_email, "remove_membership", sb)

    def _do():
        uid = _require_uuid(target_user_id, "user")
        org_id = _require_uuid(organization_id, "organization")
        existing = _rows(sb.table("organization_members").select("role")
                         .eq("organization_id", org_id).eq("user_id", uid).execute())
        if not existing:
            raise PlatformAdminError("Membership not found.")
        if existing[0].get("role") == "owner":
            raise PlatformAdminError("Legacy 'owner' memberships are not changed from the console.")
        sb.table("organization_members").delete() \
            .eq("organization_id", org_id).eq("user_id", uid).execute()

    _run(sb, actor, "remove_membership", _do, target_user_id=target_user_id,
         organization_id=organization_id)


def _validate_base_url(app_base_url: str) -> str:
    base = (app_base_url or "").strip().rstrip("/")
    parsed = urlparse(base)
    local = parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost")
    if not (parsed.scheme == "https" or local) or not parsed.hostname or parsed.query or parsed.fragment:
        raise PlatformAdminError("Application base URL is not configured correctly.")
    return base


def issue_password_setup_link(actor_user_id: str, actor_email: str, target_user_id: str,
                              app_base_url: str, sb=None) -> str:
    """Generate a single-use recovery token (no email is sent) and return an
    application URL the user opens to set their own password. The link is
    returned once and is never stored or audited."""
    sb = _client(sb)
    actor = require_platform_admin(actor_user_id, actor_email, "issue_password_setup_link", sb)
    holder: dict = {}

    def _do():
        uid = _require_uuid(target_user_id, "user")
        base = _validate_base_url(app_base_url)
        if is_platform_admin(uid, sb):
            raise PlatformAdminError("Platform administrators manage their own credentials out-of-band.")
        user = _get_auth_user(sb, uid)
        if user_is_disabled(user):
            raise PlatformAdminError("Re-enable the user before issuing a setup link.")
        email = _attr(user, "email")
        if not email:
            raise PlatformAdminError("User has no email address.")
        holder["email"] = email
        resp = sb.auth.admin.generate_link({"type": "recovery", "email": email})
        props = _attr(resp, "properties")
        hashed = _attr(props, "hashed_token") if props is not None else None
        if not hashed:
            raise PlatformAdminError("A setup link could not be generated.")
        return f"{base}/?token_hash={quote(str(hashed), safe='')}&type=recovery"

    link = _run(sb, actor, "issue_password_setup_link", _do, target_user_id=target_user_id,
                details={"delivery": "displayed_once_to_platform_admin"})
    return link


def _set_disabled(actor: PlatformAdminActor, sb, target_user_id: str, disabled: bool) -> None:
    uid = _require_uuid(target_user_id, "user")
    if uid == actor.user_id.lower():
        raise PlatformAdminError("You cannot change your own access from the console.")
    if is_platform_admin(uid, sb):
        raise PlatformAdminError("Platform administrators cannot be disabled from the console.")
    _get_auth_user(sb, uid)
    sb.auth.admin.update_user_by_id(uid, {"ban_duration": _DISABLE_BAN_DURATION if disabled else "none"})


def disable_user(actor_user_id: str, actor_email: str, target_user_id: str, sb=None) -> None:
    """Ban in Supabase Auth: blocks new sign-in and token refresh. Existing
    application sessions are cut off by tenancy.revalidate_session_access."""
    sb = _client(sb)
    actor = require_platform_admin(actor_user_id, actor_email, "disable_user", sb)
    _run(sb, actor, "disable_user", lambda: _set_disabled(actor, sb, target_user_id, True),
         target_user_id=target_user_id)


def enable_user(actor_user_id: str, actor_email: str, target_user_id: str, sb=None) -> None:
    sb = _client(sb)
    actor = require_platform_admin(actor_user_id, actor_email, "enable_user", sb)
    _run(sb, actor, "enable_user", lambda: _set_disabled(actor, sb, target_user_id, False),
         target_user_id=target_user_id)


# ── Audit trail ──────────────────────────────────────────────────────────

def list_audit_log(actor_user_id: str, actor_email: str, limit: int = 200, sb=None) -> list[dict]:
    sb = _client(sb)
    require_platform_admin(actor_user_id, actor_email, "list_audit_log", sb)
    limit = max(1, min(int(limit), 1000))
    return _rows(sb.table("platform_admin_audit_log").select("*")
                 .order("occurred_at", desc=True).limit(limit).execute())
