"""Super Admin MVP — focused positive/negative authorization tests for
platform_admin.py and tenancy.revalidate_session_access, against an
in-memory fake of the service-role Supabase client (tables + auth.admin)."""
import os
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import platform_admin as pa  # noqa: E402
import tenancy  # noqa: E402


# ── In-memory fake ───────────────────────────────────────────────────────

class _Query:
    def __init__(self, db, table):
        self.db, self.table, self.op, self.payload = db, table, "select", None
        self.filters, self.order_key, self.desc, self.limit_n = [], None, False, None

    def select(self, *_a, **_k):
        self.op = "select"; return self

    def insert(self, payload):
        self.op, self.payload = "insert", payload; return self

    def update(self, payload):
        self.op, self.payload = "update", payload; return self

    def delete(self):
        self.op = "delete"; return self

    def eq(self, k, v):
        self.filters.append((k, v)); return self

    def order(self, k, desc=False):
        self.order_key, self.desc = k, desc; return self

    def limit(self, n):
        self.limit_n = n; return self

    def _match(self, row):
        return all(str(row.get(k)) == str(v) for k, v in self.filters)

    def execute(self):
        rows = self.db.tables.setdefault(self.table, [])
        if self.table in self.db.fail_on and self.op in self.db.fail_on[self.table]:
            raise RuntimeError("simulated backend failure")
        if self.op == "insert":
            row = dict(self.payload)
            if self.table == "organizations":
                row.setdefault("id", str(uuid.uuid4()))
                row.setdefault("created_at", "2026-11-12T00:00:00Z")
            if self.table == "organization_members":
                if any(r["organization_id"] == row["organization_id"] and r["user_id"] == row["user_id"] for r in rows):
                    raise RuntimeError("duplicate key")
            if self.table == "platform_admin_audit_log":
                row["id"] = len(rows) + 1
                row["occurred_at"] = datetime.now(timezone.utc).isoformat()
            rows.append(row)
            return SimpleNamespace(data=[row])
        matched = [r for r in rows if self._match(r)]
        if self.op == "update":
            if self.table == "platform_admin_audit_log":
                raise RuntimeError("append-only")
            for r in matched:
                r.update(self.payload)
            return SimpleNamespace(data=matched)
        if self.op == "delete":
            if self.table == "platform_admin_audit_log":
                raise RuntimeError("append-only")
            self.db.tables[self.table] = [r for r in rows if not self._match(r)]
            return SimpleNamespace(data=matched)
        out = list(matched)
        if self.order_key:
            out.sort(key=lambda r: str(r.get(self.order_key)), reverse=self.desc)
        if self.limit_n:
            out = out[: self.limit_n]
        return SimpleNamespace(data=[dict(r) for r in out])


class _Admin:
    def __init__(self, db):
        self.db = db

    def _user(self, uid):
        u = self.db.users.get(uid)
        if u is None:
            raise RuntimeError("User not found")
        return u

    def get_user_by_id(self, uid):
        return SimpleNamespace(user=self._user(uid))

    def list_users(self, page=None, per_page=None):
        users = sorted(self.db.users.values(), key=lambda u: u.email)
        start = ((page or 1) - 1) * (per_page or 50)
        return users[start: start + (per_page or 50)]

    def create_user(self, attrs):
        assert set(attrs) <= {"email", "email_confirm"}, "console must not set role/metadata/password"
        if any(u.email == attrs["email"] for u in self.db.users.values()):
            raise RuntimeError("already registered")
        u = SimpleNamespace(id=str(uuid.uuid4()), email=attrs["email"], banned_until=None,
                            created_at="2026-11-12T00:00:00Z", last_sign_in_at=None)
        self.db.users[u.id] = u
        return SimpleNamespace(user=u)

    def delete_user(self, uid):
        self.db.users.pop(uid, None)

    def update_user_by_id(self, uid, attrs):
        assert set(attrs) == {"ban_duration"}
        u = self._user(uid)
        if attrs["ban_duration"] == "none":
            u.banned_until = None
        else:
            u.banned_until = (datetime.now(timezone.utc) + timedelta(days=36500)).isoformat()
        return SimpleNamespace(user=u)

    def generate_link(self, params):
        assert params == {"type": "recovery", "email": params["email"]}
        self.db.links.append(params["email"])
        return SimpleNamespace(properties=SimpleNamespace(hashed_token="hash/abc+=", action_link="internal"))


class FakeSupabase:
    def __init__(self):
        self.tables, self.users, self.links, self.fail_on = {}, {}, [], {}
        self.auth = SimpleNamespace(admin=_Admin(self))

    def table(self, name):
        return _Query(self, name)

    # helpers
    def add_user(self, email, banned=False):
        u = SimpleNamespace(id=str(uuid.uuid4()), email=email, created_at="2026-11-01T00:00:00Z",
                            last_sign_in_at=None,
                            banned_until=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat() if banned else None)
        self.users[u.id] = u
        return u.id

    def audit(self):
        return self.tables.get("platform_admin_audit_log", [])


def _world():
    sb = FakeSupabase()
    owner = sb.add_user("owner@example.com")
    sb.tables["platform_admins"] = [{"user_id": owner}]
    phoenix = str(uuid.uuid4())
    other = str(uuid.uuid4())
    sb.tables["organizations"] = [
        {"id": phoenix, "name": "Phoenix Consulting", "slug": "phoenix"},
        {"id": other, "name": "Adversary Corp", "slug": "adversary"},
    ]
    client_admin = sb.add_user("client-admin@phoenix.example")
    member = sb.add_user("member@phoenix.example")
    sb.tables["organization_members"] = [
        {"organization_id": phoenix, "user_id": client_admin, "role": "admin"},
        {"organization_id": phoenix, "user_id": member, "role": "member"},
    ]
    return SimpleNamespace(sb=sb, owner=owner, phoenix=phoenix, other=other,
                           client_admin=client_admin, member=member)


OWNER_EMAIL = "owner@example.com"
BASE = "https://phoenix-beta.enablemygrowth.com"


# ── Authority: who may act ───────────────────────────────────────────────

class TestPlatformAuthority(unittest.TestCase):
    def setUp(self):
        self.w = _world()

    def test_platform_admin_is_recognised(self):
        self.assertTrue(pa.is_platform_admin(self.w.owner, self.w.sb))

    def test_org_admin_membership_is_not_platform_authority(self):
        self.assertFalse(pa.is_platform_admin(self.w.client_admin, self.w.sb))

    def test_invalid_or_missing_actor_ids_are_not_admins(self):
        for bad in (None, "", "not-a-uuid", "' or 1=1 --"):
            self.assertFalse(pa.is_platform_admin(bad, self.w.sb))

    def test_every_operation_denies_client_admin_and_member_and_audits_denial(self):
        w = self.w
        ops = [
            lambda a: pa.list_organizations(a, "x", sb=w.sb),
            lambda a: pa.create_organization(a, "x", "Evil", "evil", sb=w.sb),
            lambda a: pa.list_users(a, "x", sb=w.sb),
            lambda a: pa.create_user(a, "x", "new@example.com", w.phoenix, "admin", sb=w.sb),
            lambda a: pa.set_membership(a, "x", a, w.other, "admin", sb=w.sb),
            lambda a: pa.remove_membership(a, "x", w.member, w.phoenix, sb=w.sb),
            lambda a: pa.issue_password_setup_link(a, "x", w.member, BASE, sb=w.sb),
            lambda a: pa.disable_user(a, "x", w.member, sb=w.sb),
            lambda a: pa.enable_user(a, "x", w.member, sb=w.sb),
            lambda a: pa.list_audit_log(a, "x", sb=w.sb),
        ]
        for actor in (w.client_admin, w.member, str(uuid.uuid4())):
            for op in ops:
                with self.assertRaises(pa.PlatformAdminDenied):
                    op(actor)
        denied = [r for r in w.sb.audit() if r["outcome"] == "denied"]
        self.assertEqual(len(denied), len(ops) * 3)
        # Nothing changed
        self.assertEqual(len(w.sb.tables["organizations"]), 2)
        self.assertEqual(len(w.sb.users), 3)
        self.assertEqual(w.sb.links, [])

    def test_client_admin_cannot_self_elevate_role_or_org(self):
        w = self.w
        with self.assertRaises(pa.PlatformAdminDenied):
            pa.set_membership(w.client_admin, "ca", w.client_admin, w.other, "admin", sb=w.sb)
        roles = [(m["organization_id"], m["role"]) for m in w.sb.tables["organization_members"]
                 if m["user_id"] == w.client_admin]
        self.assertEqual(roles, [(w.phoenix, "admin")])

    def test_authority_revoked_mid_session_takes_effect_on_next_action(self):
        w = self.w
        pa.list_users(w.owner, OWNER_EMAIL, sb=w.sb)
        w.sb.tables["platform_admins"] = []
        with self.assertRaises(pa.PlatformAdminDenied):
            pa.list_users(w.owner, OWNER_EMAIL, sb=w.sb)

    def test_module_never_writes_platform_admins(self):
        src = open(os.path.join(os.path.dirname(__file__), "..", "platform_admin.py"), encoding="utf-8").read()
        self.assertNotIn('table("platform_admins").insert', src)
        self.assertNotIn('table("platform_admins").update', src)
        self.assertNotIn('table("platform_admins").delete', src)
        console = open(os.path.join(os.path.dirname(__file__), "..", "admin_console.py"), encoding="utf-8").read()
        self.assertNotIn('table("platform_admins")', console)
        self.assertNotIn(".table(", console)


# ── Positive owner workflows ─────────────────────────────────────────────

class TestOwnerWorkflows(unittest.TestCase):
    def setUp(self):
        self.w = _world()

    def test_create_and_list_organization(self):
        org = pa.create_organization(self.w.owner, OWNER_EMAIL, "Acme Advisory", "acme-advisory", sb=self.w.sb)
        names = [o["name"] for o in pa.list_organizations(self.w.owner, OWNER_EMAIL, sb=self.w.sb)]
        self.assertIn("Acme Advisory", names)
        last = self.w.sb.audit()[-1]
        self.assertEqual((last["action"], last["outcome"]), ("create_organization", "success"))
        self.assertEqual(last["actor_user_id"], self.w.owner)
        self.assertTrue(org["id"])

    def test_organization_validation(self):
        for name, slug in (("", "ok"), ("Ok", "Bad Slug"), ("Ok", "-bad"), ("Ok", "phoenix")):
            with self.assertRaises(pa.PlatformAdminError):
                pa.create_organization(self.w.owner, OWNER_EMAIL, name, slug, sb=self.w.sb)
        self.assertTrue(all(r["outcome"] == "error" for r in self.w.sb.audit()))

    def test_create_user_without_password_and_with_one_membership(self):
        w = self.w
        u = pa.create_user(w.owner, OWNER_EMAIL, "  New.Consultant@Phoenix.example ", w.phoenix, "member", sb=w.sb)
        self.assertEqual(u["email"], "new.consultant@phoenix.example")
        ms = [m for m in w.sb.tables["organization_members"] if m["user_id"] == u["id"]]
        self.assertEqual(ms, [{"organization_id": w.phoenix, "user_id": u["id"], "role": "member"}])
        last = w.sb.audit()[-1]
        self.assertEqual((last["action"], last["outcome"], last["target_user_id"]), ("create_user", "success", u["id"]))

    def test_create_user_rejects_owner_role_bad_email_unknown_org(self):
        w = self.w
        for email, org, role in (("a@b.co", w.phoenix, "owner"), ("not-an-email", w.phoenix, "member"),
                                 ("a@b.co", str(uuid.uuid4()), "member"), ("a@b.co", "x", "member")):
            with self.assertRaises(pa.PlatformAdminError):
                pa.create_user(w.owner, OWNER_EMAIL, email, org, role, sb=w.sb)
        self.assertEqual(len(w.sb.users), 3)

    def test_duplicate_email_rejected(self):
        with self.assertRaises(pa.PlatformAdminError):
            pa.create_user(self.w.owner, OWNER_EMAIL, "member@phoenix.example", self.w.phoenix, "member", sb=self.w.sb)

    def test_membership_failure_removes_new_account(self):
        w = self.w
        w.sb.fail_on["organization_members"] = {"insert"}
        with self.assertRaises(pa.PlatformAdminError):
            pa.create_user(w.owner, OWNER_EMAIL, "orphan@example.com", w.phoenix, "member", sb=w.sb)
        self.assertFalse(any(u.email == "orphan@example.com" for u in w.sb.users.values()))
        self.assertEqual(w.sb.audit()[-1]["outcome"], "error")

    def test_set_change_and_remove_membership(self):
        w = self.w
        pa.set_membership(w.owner, OWNER_EMAIL, w.member, w.phoenix, "admin", sb=w.sb)
        role = next(m["role"] for m in w.sb.tables["organization_members"]
                    if m["user_id"] == w.member and m["organization_id"] == w.phoenix)
        self.assertEqual(role, "admin")
        pa.set_membership(w.owner, OWNER_EMAIL, w.member, w.other, "member", sb=w.sb)
        pa.remove_membership(w.owner, OWNER_EMAIL, w.member, w.other, sb=w.sb)
        self.assertFalse(any(m["user_id"] == w.member and m["organization_id"] == w.other
                             for m in w.sb.tables["organization_members"]))
        with self.assertRaises(pa.PlatformAdminError):
            pa.set_membership(w.owner, OWNER_EMAIL, w.member, w.phoenix, "owner", sb=w.sb)

    def test_legacy_owner_membership_untouched(self):
        w = self.w
        w.sb.tables["organization_members"].append({"organization_id": w.other, "user_id": w.member, "role": "owner"})
        with self.assertRaises(pa.PlatformAdminError):
            pa.set_membership(w.owner, OWNER_EMAIL, w.member, w.other, "member", sb=w.sb)
        with self.assertRaises(pa.PlatformAdminError):
            pa.remove_membership(w.owner, OWNER_EMAIL, w.member, w.other, sb=w.sb)

    def test_list_users_reports_status_and_memberships(self):
        w = self.w
        w.sb.users[w.member].banned_until = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        users = {u["email"]: u for u in pa.list_users(w.owner, OWNER_EMAIL, sb=w.sb)}
        self.assertTrue(users["member@phoenix.example"]["disabled"])
        self.assertFalse(users["client-admin@phoenix.example"]["disabled"])
        self.assertTrue(users["owner@example.com"]["is_platform_admin"])
        self.assertEqual(users["client-admin@phoenix.example"]["memberships"][0]["role"], "admin")

    def test_expired_ban_counts_as_active(self):
        u = SimpleNamespace(banned_until=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat())
        self.assertFalse(pa.user_is_disabled(u))
        self.assertFalse(pa.user_is_disabled(SimpleNamespace(banned_until=None)))
        self.assertTrue(pa.user_is_disabled(SimpleNamespace(banned_until="2999-01-01T00:00:00Z")))


# ── Setup links ──────────────────────────────────────────────────────────

class TestSetupLinks(unittest.TestCase):
    def setUp(self):
        self.w = _world()

    def test_link_points_at_app_with_encoded_hashed_token_and_is_not_audited(self):
        w = self.w
        link = pa.issue_password_setup_link(w.owner, OWNER_EMAIL, w.member, BASE + "/", sb=w.sb)
        self.assertEqual(link, BASE + "/?token_hash=hash%2Fabc%2B%3D&type=recovery")
        self.assertNotIn("internal", link)  # GoTrue's own action_link is never used
        audit_blob = repr(w.sb.audit())
        self.assertNotIn("hash", audit_blob.replace("hashed", ""))
        self.assertNotIn("token_hash", audit_blob)
        self.assertEqual(w.sb.audit()[-1]["outcome"], "success")

    def test_link_refused_for_disabled_user_platform_admin_and_bad_base_url(self):
        w = self.w
        pa.disable_user(w.owner, OWNER_EMAIL, w.member, sb=w.sb)
        with self.assertRaises(pa.PlatformAdminError):
            pa.issue_password_setup_link(w.owner, OWNER_EMAIL, w.member, BASE, sb=w.sb)
        with self.assertRaises(pa.PlatformAdminError):
            pa.issue_password_setup_link(w.owner, OWNER_EMAIL, w.owner, BASE, sb=w.sb)
        for bad in ("", "http://phoenix-beta.enablemygrowth.com", "javascript:alert(1)",
                    "https://x.example/?a=b", "https://"):
            with self.assertRaises(pa.PlatformAdminError):
                pa.issue_password_setup_link(w.owner, OWNER_EMAIL, w.client_admin, bad, sb=w.sb)
        self.assertEqual(w.sb.links, [])

    def test_loopback_base_url_allowed_for_ssh_testing(self):
        link = pa.issue_password_setup_link(self.w.owner, OWNER_EMAIL, self.w.member,
                                            "http://127.0.0.1:18502", sb=self.w.sb)
        self.assertTrue(link.startswith("http://127.0.0.1:18502/?token_hash="))


# ── Disable / enable and effective app access ────────────────────────────

class TestDisableEnable(unittest.TestCase):
    def setUp(self):
        self.w = _world()

    def test_disable_and_enable_round_trip(self):
        w = self.w
        pa.disable_user(w.owner, OWNER_EMAIL, w.member, sb=w.sb)
        self.assertTrue(pa.user_is_disabled(w.sb.users[w.member]))
        pa.enable_user(w.owner, OWNER_EMAIL, w.member, sb=w.sb)
        self.assertFalse(pa.user_is_disabled(w.sb.users[w.member]))
        actions = [(r["action"], r["outcome"]) for r in w.sb.audit()]
        self.assertEqual(actions, [("disable_user", "success"), ("enable_user", "success")])

    def test_cannot_disable_self_or_another_platform_admin(self):
        w = self.w
        with self.assertRaises(pa.PlatformAdminError):
            pa.disable_user(w.owner, OWNER_EMAIL, w.owner, sb=w.sb)
        second = w.sb.add_user("second-admin@example.com")
        w.sb.tables["platform_admins"].append({"user_id": second})
        with self.assertRaises(pa.PlatformAdminError):
            pa.disable_user(w.owner, OWNER_EMAIL, second, sb=w.sb)

    def _revalidate(self, user_id, org_id):
        with patch.object(tenancy.db, "get_service_client", return_value=self.w.sb):
            return tenancy.revalidate_session_access(user_id, org_id)

    def test_disabled_user_loses_effective_application_access(self):
        w = self.w
        self.assertTrue(self._revalidate(w.member, w.phoenix).ok)
        pa.disable_user(w.owner, OWNER_EMAIL, w.member, sb=w.sb)
        r = self._revalidate(w.member, w.phoenix)
        self.assertEqual((r.ok, r.reason), (False, "account_disabled"))
        self.assertFalse(self._revalidate(w.member, None).ok)
        pa.enable_user(w.owner, OWNER_EMAIL, w.member, sb=w.sb)
        self.assertTrue(self._revalidate(w.member, w.phoenix).ok)

    def test_removed_membership_and_deleted_account_lose_access(self):
        w = self.w
        pa.remove_membership(w.owner, OWNER_EMAIL, w.member, w.phoenix, sb=w.sb)
        self.assertEqual(self._revalidate(w.member, w.phoenix).reason, "membership_removed")
        w.sb.users.pop(w.client_admin)
        self.assertFalse(self._revalidate(w.client_admin, w.phoenix).ok)

    def test_role_change_is_reported_for_live_session_refresh(self):
        w = self.w
        pa.set_membership(w.owner, OWNER_EMAIL, w.client_admin, w.phoenix, "member", sb=w.sb)
        self.assertEqual(self._revalidate(w.client_admin, w.phoenix).role, "member")

    def test_revalidation_fails_closed_on_backend_error(self):
        with patch.object(tenancy.db, "get_service_client", side_effect=RuntimeError("down")):
            r = tenancy.revalidate_session_access(self.w.member, self.w.phoenix)
        self.assertEqual((r.ok, r.reason), (False, "access_check_failed"))


# ── Audit trail ──────────────────────────────────────────────────────────

class TestAuditTrail(unittest.TestCase):
    def test_failed_audit_write_does_not_report_success(self):
        w = _world()
        w.sb.fail_on["platform_admin_audit_log"] = {"insert"}
        with self.assertRaises(Exception):
            pa.create_organization(w.owner, OWNER_EMAIL, "Acme", "acme", sb=w.sb)

    def test_audit_log_listing_newest_first_and_owner_only(self):
        w = _world()
        pa.create_organization(w.owner, OWNER_EMAIL, "A", "a", sb=w.sb)
        pa.create_organization(w.owner, OWNER_EMAIL, "B", "b", sb=w.sb)
        rows = pa.list_audit_log(w.owner, OWNER_EMAIL, limit=1, sb=w.sb)
        self.assertEqual(len(rows), 1)
        with self.assertRaises(pa.PlatformAdminDenied):
            pa.list_audit_log(w.member, "m", sb=w.sb)


# ── Static boundary checks ───────────────────────────────────────────────

class TestStaticBoundaries(unittest.TestCase):
    ROOT = os.path.join(os.path.dirname(__file__), "..")

    def _read(self, name):
        return open(os.path.join(self.ROOT, name), encoding="utf-8").read()

    def test_client_app_does_not_import_admin_console_or_service_layer(self):
        app = self._read("app.py")
        self.assertNotIn("admin_console", app)
        self.assertNotIn("import platform_admin", app)
        self.assertFalse(os.path.exists(os.path.join(self.ROOT, "pages", "admin_console.py")))

    def test_admin_console_requires_explicit_enable_flag_and_never_reads_keys(self):
        console = self._read("admin_console.py")
        self.assertIn('os.getenv("PLATFORM_ADMIN_CONSOLE_ENABLED") != "1"', console)
        for secret in ("SUPABASE_SERVICE_KEY", "SUPABASE_ANON_KEY", "JWT_SECRET", "service_role"):
            self.assertNotIn(secret, console)

    def test_service_layer_never_sets_auth_role_or_metadata(self):
        src = self._read("platform_admin.py")
        for forbidden in ('"role": "service_role"', "app_metadata", "user_metadata", '"password"'):
            self.assertNotIn(forbidden, src)

    def test_migration_is_fail_closed(self):
        sql = self._read(os.path.join("migrations", "024_platform_super_admin.sql")).lower()
        self.assertIn("alter table public.platform_admins          enable row level security", sql)
        self.assertIn("alter table public.platform_admin_audit_log enable row level security", sql)
        self.assertIn("revoke all on table public.platform_admins          from anon, authenticated", sql)
        self.assertIn("revoke all on table public.platform_admin_audit_log from anon, authenticated", sql)
        self.assertNotIn("create policy", sql)
        self.assertIn("before update or delete on public.platform_admin_audit_log", sql)


if __name__ == "__main__":
    unittest.main()
