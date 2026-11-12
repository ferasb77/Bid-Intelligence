#!/usr/bin/env python3
"""Super Admin MVP — live beta authorization matrix (run INSIDE the
bid-intelligence-beta-admin container, which holds the beta service key in
its environment; nothing secret is printed).

    docker exec -i bid-intelligence-beta-admin python - <OWNER_USER_ID> <PHOENIX_CLIENT_ADMIN_USER_ID> <OWNER_EMAIL> < this_file

Creates a disposable organization and disposable users, exercises every
platform_admin operation as the platform owner (positive), as an existing
Phoenix client admin and as a disposable client admin/member (negative, both
through the service layer and through PostgREST with the users' own JWTs),
proves disable/enable takes effect on sign-in, token refresh and live session
revalidation, then deletes every disposable user/membership/org. Audit rows
are append-only by design and remain, tagged with the run id.
No provider (Anthropic) calls are made.
"""
import json
import os
import secrets
import sys
import urllib.error
import urllib.request

sys.path.insert(0, "/app")
import auth_client  # noqa: E402
import database as db  # noqa: E402
import platform_admin as pa  # noqa: E402
import tenancy  # noqa: E402

OWNER, PHOENIX_ADMIN, OWNER_EMAIL = sys.argv[1], sys.argv[2], sys.argv[3]  # no identities hard-coded
RUN = secrets.token_hex(3)
URL = os.environ["SUPABASE_URL"].rstrip("/")
ANON = os.environ["SUPABASE_ANON_KEY"]
sb = db.get_service_client()
RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}", flush=True)


def denied(fn):
    try:
        fn()
        return False
    except pa.PlatformAdminDenied:
        return True


def rest(method, path, token, body=None, prefer=None):
    req = urllib.request.Request(f"{URL}/rest/v1/{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None)
    req.add_header("apikey", ANON)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    if prefer:
        req.add_header("Prefer", prefer)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def sign_in(email, password):
    c = auth_client.get_auth_client()
    return c.auth.sign_in_with_password({"email": email, "password": password})


def counts():
    return {t: len(sb.table(t).select("*").execute().data or [])
            for t in ("organizations", "organization_members", "platform_admins")}


created_users, created_org = [], None
try:
    # ── Preconditions
    check("owner is platform admin (DB)", pa.is_platform_admin(OWNER, sb))
    check("existing Phoenix client admin is NOT platform admin", not pa.is_platform_admin(PHOENIX_ADMIN, sb))
    phoenix_role = [m["role"] for m in sb.table("organization_members").select("role").eq("user_id", PHOENIX_ADMIN).execute().data]
    check("existing Phoenix identity holds org role 'admin' (the case being tested)", phoenix_role == ["admin"])

    # ── Positive: owner workflows
    orgs = pa.list_organizations(OWNER, OWNER_EMAIL, sb=sb)
    check("owner lists organizations", any(o["name"] == "Phoenix Consulting" for o in orgs))
    org = pa.create_organization(OWNER, OWNER_EMAIL, f"Super Admin Test {RUN}", f"sa-test-{RUN}", sb=sb)
    created_org = org["id"]
    check("owner creates organization", bool(created_org))
    ca = pa.create_user(OWNER, OWNER_EMAIL, f"sa-test-ca-{RUN}@example.com", created_org, "admin", sb=sb)
    mem = pa.create_user(OWNER, OWNER_EMAIL, f"sa-test-m-{RUN}@example.com", created_org, "member", sb=sb)
    created_users += [ca["id"], mem["id"]]
    users = {u["email"]: u for u in pa.list_users(OWNER, OWNER_EMAIL, sb=sb)}
    check("owner creates users with one membership each",
          users[ca["email"]]["memberships"][0]["role"] == "admin" and users[mem["email"]]["memberships"][0]["role"] == "member")
    pa.set_membership(OWNER, OWNER_EMAIL, mem["id"], created_org, "admin", sb=sb)
    pa.set_membership(OWNER, OWNER_EMAIL, mem["id"], created_org, "member", sb=sb)
    check("owner changes role admin<->member", sb.table("organization_members").select("role")
          .eq("user_id", mem["id"]).execute().data[0]["role"] == "member")

    link = pa.issue_password_setup_link(OWNER, OWNER_EMAIL, mem["id"], "https://phoenix-beta.enablemygrowth.com", sb=sb)
    check("setup link targets the Access-protected client app with type=recovery",
          link.startswith("https://phoenix-beta.enablemygrowth.com/?token_hash=") and link.endswith("&type=recovery"))
    token_hash = link.split("token_hash=")[1].split("&")[0]
    vr = auth_client.get_auth_client().auth.verify_otp({"token_hash": token_hash, "type": "recovery"})
    check("setup token is accepted by real GoTrue (recovery session issued)", bool(vr.session and vr.user and vr.user.id == mem["id"]))
    try:
        auth_client.get_auth_client().auth.verify_otp({"token_hash": token_hash, "type": "recovery"})
        check("setup token is single-use", False)
    except Exception:
        check("setup token is single-use", True)

    # Give disposable users passwords so their own JWTs can be tested (test harness only).
    pw = {u: secrets.token_urlsafe(18) for u in (ca["id"], mem["id"])}
    for u in pw:
        sb.auth.admin.update_user_by_id(u, {"password": pw[u]})

    # ── Negative: service layer as Phoenix client admin and disposable client admin/member
    before = counts()
    for label, actor in (("Phoenix client admin", PHOENIX_ADMIN), ("disposable client admin", ca["id"]),
                         ("disposable member", mem["id"])):
        ops = {
            "list_organizations": lambda a=actor: pa.list_organizations(a, "x", sb=sb),
            "list_users": lambda a=actor: pa.list_users(a, "x", sb=sb),
            "create_organization": lambda a=actor: pa.create_organization(a, "x", "Evil", f"evil-{RUN}", sb=sb),
            "create_user": lambda a=actor: pa.create_user(a, "x", f"evil-{RUN}@example.com", created_org, "admin", sb=sb),
            "self-elevate set_membership": lambda a=actor: pa.set_membership(a, "x", a, created_org, "admin", sb=sb),
            "issue link": lambda a=actor: pa.issue_password_setup_link(a, "x", mem["id"], "https://phoenix-beta.enablemygrowth.com", sb=sb),
            "disable": lambda a=actor: pa.disable_user(a, "x", mem["id"], sb=sb),
            "audit log": lambda a=actor: pa.list_audit_log(a, "x", sb=sb),
        }
        check(f"{label}: all {len(ops)} admin operations denied", all(denied(f) for f in ops.values()))
    check("negative attempts changed nothing", counts() == before)

    # ── Negative: PostgREST with users' own JWTs (direct backend endpoints)
    for label, uid, email in (("disposable client admin", ca["id"], ca["email"]), ("disposable member", mem["id"], mem["email"])):
        tok = sign_in(email, pw[uid]).session.access_token
        s1, _ = rest("GET", "platform_admins?select=*", tok)
        s2, _ = rest("POST", "platform_admins", tok, {"user_id": uid, "granted_by": "self"})
        s3, _ = rest("GET", "platform_admin_audit_log?select=*", tok)
        s4, _ = rest("POST", "platform_admin_audit_log", tok, {"action": "forge", "outcome": "success"})
        check(f"{label} JWT: platform tables unreadable/unwritable via PostgREST", all(s in (401, 403) for s in (s1, s2, s3, s4)),
              f"GET pa={s1} POST pa={s2} GET audit={s3} POST audit={s4}")
        s5, b5 = rest("PATCH", f"organization_members?user_id=eq.{uid}", tok, {"role": "owner"}, prefer="return=representation")
        s6, _ = rest("POST", "organization_members", tok, {"organization_id": created_org, "user_id": uid, "role": "owner"})
        role_now = sb.table("organization_members").select("role").eq("user_id", uid).execute().data[0]["role"]
        check(f"{label} JWT: cannot change own role or add membership",
              s5 in (401, 403) or b5.strip() in ("[]", ""), f"PATCH={s5} body={b5[:40]!r} POST={s6} role_now={role_now}")
        check(f"{label} JWT: membership insert rejected", s6 in (401, 403), f"POST={s6}")
        check(f"{label}: role unchanged in DB", role_now == ("admin" if uid == ca["id"] else "member"))
    check("platform_admins unchanged", counts()["platform_admins"] == before["platform_admins"])

    # ── Disable / enable effect
    s = sign_in(mem["email"], pw[mem["id"]])
    refresh = s.session.refresh_token
    check("member signs in while active; live session revalidates OK",
          tenancy.revalidate_session_access(mem["id"], created_org).ok)
    pa.disable_user(OWNER, OWNER_EMAIL, mem["id"], sb=sb)
    try:
        sign_in(mem["email"], pw[mem["id"]]); blocked = False
    except Exception:
        blocked = True
    check("disabled user cannot sign in", blocked)
    try:
        auth_client.get_auth_client().auth.refresh_session(refresh); refresh_blocked = False
    except Exception:
        refresh_blocked = True
    check("disabled user cannot refresh an existing session", refresh_blocked)
    r = tenancy.revalidate_session_access(mem["id"], created_org)
    check("existing app session is revoked on next revalidation", (r.ok, r.reason) == (False, "account_disabled"))
    try:
        pa.issue_password_setup_link(OWNER, OWNER_EMAIL, mem["id"], "https://phoenix-beta.enablemygrowth.com", sb=sb)
        check("no setup link for a disabled user", False)
    except pa.PlatformAdminError:
        check("no setup link for a disabled user", True)
    pa.enable_user(OWNER, OWNER_EMAIL, mem["id"], sb=sb)
    check("re-enabled user signs in again", bool(sign_in(mem["email"], pw[mem["id"]]).session))
    pa.remove_membership(OWNER, OWNER_EMAIL, mem["id"], created_org, sb=sb)
    check("removed membership revokes live session", tenancy.revalidate_session_access(mem["id"], created_org).reason == "membership_removed")
    for label, fn in (("owner cannot disable self", lambda: pa.disable_user(OWNER, OWNER_EMAIL, OWNER, sb=sb)),
                      ("no setup link for platform admin", lambda: pa.issue_password_setup_link(OWNER, OWNER_EMAIL, OWNER, "https://phoenix-beta.enablemygrowth.com", sb=sb))):
        try:
            fn(); check(label, False)
        except pa.PlatformAdminError:
            check(label, True)

    # ── Audit trail
    rows = pa.list_audit_log(OWNER, OWNER_EMAIL, limit=500, sb=sb)
    mine = [r for r in rows if RUN in json.dumps(r)]
    acts = {(r["action"], r["outcome"]) for r in rows}
    check("audit has success rows for create_org/create_user/membership/link/disable/enable",
          {("create_organization", "success"), ("create_user", "success"), ("set_membership", "success"),
           ("issue_password_setup_link", "success"), ("disable_user", "success"), ("enable_user", "success")} <= acts)
    check("audit records denied attempts by non-admins",
          any(r["outcome"] == "denied" and r["actor_user_id"] == PHOENIX_ADMIN for r in rows))
    check("audit never contains the setup token", token_hash not in json.dumps(rows))
    try:
        sb.table("platform_admin_audit_log").delete().eq("id", rows[0]["id"]).execute()
        check("audit log rejects delete via service role", False)
    except Exception:
        check("audit log rejects delete via service role", True)

    # ── Existing Phoenix workflow still readable (no provider calls)
    phoenix_org = next(o["id"] for o in orgs if o["name"] == "Phoenix Consulting")
    bids = tenancy.list_bids_for_organization(phoenix_org)
    check("Phoenix org bids still listed", any(b["id"] == 4 for b in bids))
    check("Phoenix client admin session still revalidates OK", tenancy.revalidate_session_access(PHOENIX_ADMIN, phoenix_org).ok)
finally:
    for uid in created_users:
        try:
            sb.auth.admin.delete_user(uid)
        except Exception as e:
            print("cleanup user failed:", type(e).__name__)
    if created_org:
        sb.table("organization_members").delete().eq("organization_id", created_org).execute()
        sb.table("organizations").delete().eq("id", created_org).execute()
    left_users = [u for u in sb.auth.admin.list_users(page=1, per_page=200) if RUN in (u.email or "")]
    left_org = sb.table("organizations").select("id").like("slug", f"%{RUN}%").execute().data
    check("cleanup: no disposable users or org remain", not left_users and not left_org)

failed = [n for n, ok in RESULTS if not ok]
print(f"\nRUN {RUN}: {len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
sys.exit(1 if failed else 0)
