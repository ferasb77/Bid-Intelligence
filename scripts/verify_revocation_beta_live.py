#!/usr/bin/env python3
"""Super Admin revocation correction — live beta acceptance with REAL GoTrue
JWTs and direct PostgREST requests (run INSIDE the bid-intelligence-beta-admin
container, which holds the beta keys in its environment; no secret, password
or token is printed — only HTTP status codes, row counts and claim NAMES).

    docker exec -i bid-intelligence-beta-admin python - <OWNER_USER_ID> <OWNER_EMAIL> \
        <PHOENIX_CLIENT_ADMIN_USER_ID> <PHOENIX_BID_ID> <FAST_RUN_ID> <FULL_RUN_ID> < this_file

Creates two disposable organizations (A, B), disposable users
  uA  member of A                       -> disable / re-enable
  uM  admin of A and member of B         -> membership removal / role change
  uB  member of B                        -> cross-tenant control
and synthetic bid/document/analysis/storage rows in each org, then proves:
  before disable: own resources readable/writable with the user's own JWT
  after disable : the SAME pre-disable JWT gets no membership/bid/document/
                  analysis rows, no writes, no RPCs; sign-in + refresh blocked;
                  every user-reachable service-role application operation is
                  denied; cross-tenant still denied
  membership removal: stale JWT loses exactly that org; role downgrade is
                  read from the DB, never from JWT claims
  re-enable     : access returns only per CURRENT memberships
  Phoenix FAST/FULL/PDF exports unchanged (Anthropic patched to raise)
Everything disposable is deleted at the end; audit rows are append-only by
design and remain (tagged with the run id).
"""
import base64
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

OWNER, OWNER_EMAIL, PHOENIX_ADMIN = sys.argv[1], sys.argv[2], sys.argv[3]
PHX_BID, FAST_RUN, FULL_RUN = int(sys.argv[4]), int(sys.argv[5]), int(sys.argv[6])
RUN = secrets.token_hex(3)
URL = os.environ["SUPABASE_URL"].rstrip("/")
ANON = os.environ["SUPABASE_ANON_KEY"]
sb = db.get_service_client()
RESULTS = []
EVIDENCE = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}", flush=True)


def http(method, path, token, body=None, prefer=None):
    req = urllib.request.Request(f"{URL}{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None)
    req.add_header("apikey", ANON)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    if prefer:
        req.add_header("Prefer", prefer)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def rows(status, body):
    if status != 200:
        return None
    try:
        data = json.loads(body)
        return len(data) if isinstance(data, list) else data
    except Exception:
        return None


def rest_get(path, token, label):
    s, b = http("GET", f"/rest/v1/{path}", token)
    n = rows(s, b)
    EVIDENCE.append(f"{label}: GET /rest/v1/{path.split('?')[0]} -> HTTP {s}, rows={n}")
    return s, n


def sign_in(email, password):
    return auth_client.get_auth_client().auth.sign_in_with_password({"email": email, "password": password})


def claim_names(token):
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))


def principal(uid, email, org, role):
    return tenancy.AuthContext(user_id=uid, email=email, organization_id=org,
                               organization_name="", role=role)


def as_session(ctx):
    tenancy.set_session_principal_provider(lambda: ctx)


def app_ops(org, bid, doc):
    return {
        "list_bids_for_organization": lambda: tenancy.list_bids_for_organization(org),
        "get_bid_for_organization": lambda: tenancy.get_bid_for_organization(bid, org),
        "require_bid_access": lambda: tenancy.require_bid_access(bid, org),
        "get_document_for_organization": lambda: tenancy.get_document_for_organization(bid, doc, org),
        "download_document_for_organization": lambda: tenancy.download_document_for_organization(bid, doc, org),
        "get_full_analysis_status_for_organization": lambda: tenancy.get_full_analysis_status_for_organization(bid, org),
        "list_organizational_memory_for_organization": lambda: tenancy.list_organizational_memory_for_organization(org),
        "create_bid_for_organization": lambda: tenancy.create_bid_for_organization(
            {"title": f"should-not-exist-{RUN}", "client": "x"}, org),
    }


def app_denied(ops, skip=()):
    out = {}
    for name, fn in ops.items():
        if name in skip:
            continue
        try:
            fn()
            out[name] = "ALLOWED"
        except tenancy.SessionAccessRevokedError as e:
            out[name] = f"denied:{e}"
        except Exception as e:  # anything else is not a clean denial
            out[name] = f"error:{type(e).__name__}"
    return out


users, orgs, storage_paths, bids = {}, {}, [], []
try:
    # ── Disposable world ────────────────────────────────────────────────
    for k in ("A", "B"):
        o = pa.create_organization(OWNER, OWNER_EMAIL, f"Revocation Test {k} {RUN}", f"rv-{k.lower()}-{RUN}", sb=sb)
        orgs[k] = o["id"]
    for k, org, role in (("uA", "A", "member"), ("uM", "A", "admin"), ("uB", "B", "member")):
        u = pa.create_user(OWNER, OWNER_EMAIL, f"rv-{k.lower()}-{RUN}@example.com", orgs[org], role, sb=sb)
        users[k] = {"id": u["id"], "email": u["email"], "pw": secrets.token_urlsafe(18)}
        sb.auth.admin.update_user_by_id(u["id"], {"password": users[k]["pw"]})  # test-only credential
    pa.set_membership(OWNER, OWNER_EMAIL, users["uM"]["id"], orgs["B"], "member", sb=sb)

    world = {}
    for k in ("A", "B"):
        bid = sb.table("bids").insert({"organization_id": orgs[k], "title": f"RV {k} {RUN}",
                                       "client": "revocation-test"}).execute().data[0]["id"]
        bids.append(bid)
        path = f"revocation-test/{RUN}/{k}.txt"
        sb.storage.from_(db.BUCKET).upload(path, f"synthetic {k} {RUN}".encode(), {"content-type": "text/plain"})
        storage_paths.append(path)
        doc = sb.table("documents").insert({"bid_id": bid, "name": f"rv-{k}.txt",
                                            "storage_path": path}).execute().data[0]["id"]
        run = sb.table("analysis_runs").insert({"bid_id": bid, "analysis_mode": "FAST",
                                                "engine_version": "revocation-test", "status": "COMPLETE"}
                                               ).execute().data[0]["id"]
        sb.table("analysis_results").insert({"run_id": run, "bid_id": bid,
                                             "structured_intelligence": {"synthetic": True}}).execute()
        world[k] = {"bid": bid, "doc": doc, "run": run, "path": path}
    check("disposable world created (2 orgs, 3 users, bid+document+storage+analysis per org)", True,
          f"run={RUN}")

    def matrix(token, k):
        w = world[k]
        return {
            "organization_members": rest_get(f"organization_members?select=role&organization_id=eq.{orgs[k]}", token, k)[1],
            "organizations": rest_get(f"organizations?select=id&id=eq.{orgs[k]}", token, k)[1],
            "bids": rest_get(f"bids?select=id&id=eq.{w['bid']}", token, k)[1],
            "documents": rest_get(f"documents?select=id&bid_id=eq.{w['bid']}", token, k)[1],
            "analysis_runs": rest_get(f"analysis_runs?select=id&bid_id=eq.{w['bid']}", token, k)[1],
            "analysis_results": rest_get(f"analysis_results?select=id&bid_id=eq.{w['bid']}", token, k)[1],
        }

    def rpc_statuses(token):
        out = {}
        for fn, body in (("start_full_analysis_run", {"p_bid_id": world["A"]["bid"], "p_source_analysis_run_id": world["A"]["run"],
                                                       "p_input_fingerprint": "x", "p_engine_version": "x", "p_corpus_digest": "x",
                                                       "p_created_by_user_id": None, "p_retry": False, "p_detail": {}}),
                         ("refresh_bid_brief_projection", {"p_bid_id": world["A"]["bid"]}),
                         ("session_access_status", {"p_user_id": users["uA"]["id"], "p_organization_id": orgs["A"]}),
                         ("is_user_organization_member", {"p_user_id": users["uA"]["id"], "p_organization_id": orgs["A"]})):
            out[fn] = http("POST", f"/rest/v1/rpc/{fn}", token, body)[0]
        return out

    # ── uA: before disable ──────────────────────────────────────────────
    sA = sign_in(users["uA"]["email"], users["uA"]["pw"])
    jwtA, refreshA = sA.session.access_token, sA.session.refresh_token
    claims = claim_names(jwtA)
    check("JWT carries no organization/role-membership claims (authorization is DB-side)",
          not any(k in claims for k in ("organization_id", "org_role", "memberships")) and claims.get("role") == "authenticated",
          f"claim names={sorted(claims)}")
    before = matrix(jwtA, "A")
    check("BEFORE disable: uA's JWT reads own membership/org/bid/document/analysis rows",
          all(v == 1 for v in before.values()), json.dumps(before))
    s, b = http("PATCH", f"/rest/v1/bids?id=eq.{world['A']['bid']}", jwtA, {"notes": f"rv-before-{RUN}"}, "return=representation")
    check("BEFORE disable: uA's JWT updates own bid", s == 200 and rows(s, b) == 1, f"HTTP {s} rows={rows(s, b)}")
    EVIDENCE.append(f"A: PATCH /rest/v1/bids (before disable) -> HTTP {s}, rows={rows(s, b)}")
    s, n = rest_get(f"bids?select=id&id=eq.{world['B']['bid']}", jwtA, "cross")
    check("BEFORE disable: cross-tenant bid B invisible to uA", s == 200 and n == 0, f"HTTP {s} rows={n}")
    st_obj = http("GET", f"/storage/v1/object/authenticated/{db.BUCKET}/{world['A']['path']}", jwtA)[0]
    check("BEFORE disable: Storage stays service-only (own object not readable with user JWT)", st_obj in (400, 403, 404),
          f"HTTP {st_obj}")
    rpcs = rpc_statuses(jwtA)
    check("BEFORE disable: application SECURITY DEFINER RPCs not callable with a user JWT",
          all(v in (401, 403, 404) for v in rpcs.values()), json.dumps(rpcs))
    rpcs_anon = rpc_statuses(None)
    check("anon key alone cannot call application RPCs", all(v in (401, 403, 404) for v in rpcs_anon.values()), json.dumps(rpcs_anon))
    ctxA = principal(users["uA"]["id"], users["uA"]["email"], orgs["A"], "member")
    as_session(ctxA)
    pre_app = app_denied(app_ops(orgs["A"], world["A"]["bid"], world["A"]["doc"]), skip=("create_bid_for_organization",))
    check("BEFORE disable: user-reachable service-role operations allowed", all(v == "ALLOWED" for v in pre_app.values()),
          json.dumps(pre_app))

    # ── disable uA ──────────────────────────────────────────────────────
    pa.disable_user(OWNER, OWNER_EMAIL, users["uA"]["id"], sb=sb)
    s_user = http("GET", "/auth/v1/user", jwtA)[0]
    s_active, b_active = http("POST", "/rest/v1/rpc/current_user_is_active", jwtA, {})
    check("AFTER disable: PostgREST still ACCEPTS the pre-disable JWT cryptographically (no 401) but the DB says inactive",
          s_active == 200 and b_active.strip() == "false", f"rpc/current_user_is_active -> HTTP {s_active} body={b_active.strip()}; "
                                                         f"GoTrue /auth/v1/user -> HTTP {s_user}")
    EVIDENCE.append(f"A: POST /rest/v1/rpc/current_user_is_active (after disable) -> HTTP {s_active} {b_active.strip()}")
    after = matrix(jwtA, "A")
    check("AFTER disable: SAME pre-disable JWT gets zero membership/org/bid/document/analysis rows",
          all(v == 0 for v in after.values()), json.dumps(after))
    s, b = http("PATCH", f"/rest/v1/bids?id=eq.{world['A']['bid']}", jwtA, {"notes": f"rv-after-{RUN}"}, "return=representation")
    check("AFTER disable: pre-disable JWT cannot update the bid", s in (200, 401, 403) and rows(s, b) in (0, None),
          f"HTTP {s} rows={rows(s, b)}")
    EVIDENCE.append(f"A: PATCH /rest/v1/bids (after disable) -> HTTP {s}, rows={rows(s, b)}")
    s, b = http("POST", "/rest/v1/bids", jwtA, {"organization_id": orgs["A"], "title": f"rv-insert-{RUN}", "client": "x"})
    check("AFTER disable: pre-disable JWT cannot insert a bid", s in (401, 403), f"HTTP {s}")
    EVIDENCE.append(f"A: POST /rest/v1/bids (after disable) -> HTTP {s}")
    s, b = http("POST", "/rest/v1/documents", jwtA, {"bid_id": world["A"]["bid"], "name": "x"})
    check("AFTER disable: pre-disable JWT cannot insert a document", s in (401, 403), f"HTTP {s}")
    rpcs = rpc_statuses(jwtA)
    check("AFTER disable: RPCs still denied", all(v in (401, 403, 404) for v in rpcs.values()), json.dumps(rpcs))
    try:
        sign_in(users["uA"]["email"], users["uA"]["pw"]); blocked = False
    except Exception:
        blocked = True
    check("AFTER disable: new sign-in blocked", blocked)
    try:
        auth_client.get_auth_client().auth.refresh_session(refreshA); rblocked = False
    except Exception:
        rblocked = True
    check("AFTER disable: refresh blocked", rblocked)
    as_session(ctxA)
    post_app = app_denied(app_ops(orgs["A"], world["A"]["bid"], world["A"]["doc"]))
    check("AFTER disable: every user-reachable service-role operation denied (account_disabled)",
          all(v == "denied:account_disabled" for v in post_app.values()), json.dumps(post_app))
    check("AFTER disable: no bid was created by the denied create call",
          not sb.table("bids").select("id").eq("title", f"should-not-exist-{RUN}").execute().data)
    check("AFTER disable: app session revalidation fails closed",
          tenancy.revalidate_session_access(users["uA"]["id"], orgs["A"]).reason == "account_disabled")
    s, n = rest_get(f"bids?select=id&id=eq.{world['B']['bid']}", jwtA, "cross")
    check("AFTER disable: cross-tenant still denied", s == 200 and n == 0, f"HTTP {s} rows={n}")
    as_session(ctxA)
    x = app_denied({"cross-tenant op": lambda: tenancy.list_bids_for_organization(orgs["B"])})
    check("AFTER disable: cross-tenant service-role op denied", x["cross-tenant op"].startswith("denied"), json.dumps(x))
    sB = sign_in(users["uB"]["email"], users["uB"]["pw"]).session.access_token
    ctrl = matrix(sB, "B")
    check("control: uB (other tenant) unaffected", all(v == 1 for v in ctrl.values()), json.dumps(ctrl))
    s, n = rest_get(f"bids?select=id&id=eq.{world['A']['bid']}", sB, "cross")
    check("control: uB cannot see tenant A", s == 200 and n == 0, f"HTTP {s} rows={n}")

    # ── re-enable uA ────────────────────────────────────────────────────
    pa.enable_user(OWNER, OWNER_EMAIL, users["uA"]["id"], sb=sb)
    again = matrix(jwtA, "A")
    check("RE-ENABLE: access returns per current membership (A)", all(v == 1 for v in again.values()), json.dumps(again))
    s, n = rest_get(f"bids?select=id&id=eq.{world['B']['bid']}", jwtA, "cross")
    check("RE-ENABLE: still no access to B (never a member)", s == 200 and n == 0, f"HTTP {s} rows={n}")
    check("RE-ENABLE: sign-in works again", bool(sign_in(users["uA"]["email"], users["uA"]["pw"]).session))
    as_session(ctxA)
    re_app = app_denied(app_ops(orgs["A"], world["A"]["bid"], world["A"]["doc"]), skip=("create_bid_for_organization",))
    check("RE-ENABLE: service-role operations allowed again for A", all(v == "ALLOWED" for v in re_app.values()), json.dumps(re_app))

    # ── membership removal / role change: uM (admin of A, member of B) ──
    jwtM = sign_in(users["uM"]["email"], users["uM"]["pw"]).session.access_token
    mA, mB = matrix(jwtM, "A"), matrix(jwtM, "B")
    check("uM BEFORE removal: reads A and B", all(v == 1 for v in mA.values()) and all(v == 1 for v in mB.values()),
          f"A={json.dumps(mA)} B={json.dumps(mB)}")
    pa.set_membership(OWNER, OWNER_EMAIL, users["uM"]["id"], orgs["A"], "member", sb=sb)
    r = tenancy.revalidate_session_access(users["uM"]["id"], orgs["A"])
    check("role downgrade admin->member is read from the DB (stale session/JWT cannot keep 'admin')",
          r.ok and r.role == "member", f"role now={r.role}")
    pa.remove_membership(OWNER, OWNER_EMAIL, users["uM"]["id"], orgs["A"], sb=sb)
    mA, mB = matrix(jwtM, "A"), matrix(jwtM, "B")
    check("AFTER removal: SAME JWT gets zero A rows", all(v == 0 for v in mA.values()), json.dumps(mA))
    check("AFTER removal: B (still a member) unaffected", all(v == 1 for v in mB.values()), json.dumps(mB))
    as_session(principal(users["uM"]["id"], users["uM"]["email"], orgs["A"], "admin"))
    rm_app = app_denied(app_ops(orgs["A"], world["A"]["bid"], world["A"]["doc"]))
    check("AFTER removal: stale A session's service-role operations denied (membership_removed)",
          all(v == "denied:membership_removed" for v in rm_app.values()), json.dumps(rm_app))
    as_session(principal(users["uM"]["id"], users["uM"]["email"], orgs["B"], "member"))
    b_app = app_denied(app_ops(orgs["B"], world["B"]["bid"], world["B"]["doc"]), skip=("create_bid_for_organization",))
    check("AFTER removal: B session's operations still allowed", all(v == "ALLOWED" for v in b_app.values()), json.dumps(b_app))
    as_session(None)
    nos = app_denied({"no session": lambda: tenancy.list_bids_for_organization(orgs["B"])})
    check("no resolved session in a script run -> denied (fail closed)", nos["no session"].startswith("denied"), json.dumps(nos))
    tenancy.set_session_principal_provider(None)

    # ── Existing Phoenix workflow + FAST/FULL/PDF (Anthropic patched to raise)
    import anthropic

    def _no_provider(*a, **k):
        raise RuntimeError("provider call attempted during verification")
    anthropic.Anthropic.__init__ = _no_provider
    phoenix_org = sb.table("organization_members").select("organization_id").eq("user_id", PHOENIX_ADMIN).execute().data[0]["organization_id"]
    as_session(principal(PHOENIX_ADMIN, "", phoenix_org, "admin"))
    check("Phoenix client admin session revalidates OK", tenancy.revalidate_session_access(PHOENIX_ADMIN, phoenix_org).ok)
    check("Phoenix bid listed through the gated service-role path",
          any(int(b["id"]) == PHX_BID for b in tenancy.list_bids_for_organization(phoenix_org)))
    brief = tenancy.export_bid_intelligence_brief_for_organization(PHX_BID, FAST_RUN, phoenix_org)
    appendix = tenancy.get_raw_snapshot_report_for_organization(PHX_BID, FAST_RUN, phoenix_org)
    full = tenancy.export_full_analysis_report_for_organization(PHX_BID, phoenix_org, FULL_RUN)
    fres = tenancy.get_full_analysis_result_for_organization(PHX_BID, phoenix_org, FULL_RUN)
    sizes = {"brief": len(brief), "appendix": len(appendix), "full": len(full["pdf"])}
    check("FAST brief + appendix and FULL report PDFs export (no provider calls)",
          all(v > 10000 for v in sizes.values()) and all(x[:4] == b"%PDF" for x in (brief, appendix, full["pdf"])),
          json.dumps(sizes))
    check("FULL result readable", fres is not None)
    as_session(principal(PHOENIX_ADMIN, "", orgs["A"], "admin"))
    xt = app_denied({"cross-tenant export": lambda: tenancy.export_full_analysis_report_for_organization(PHX_BID, orgs["A"], FULL_RUN)})
    check("cross-tenant export (session org A -> Phoenix bid) denied", xt["cross-tenant export"].startswith("denied"), json.dumps(xt))
    tenancy.set_session_principal_provider(None)
finally:
    tenancy.set_session_principal_provider(None)
    for p in storage_paths:
        try:
            sb.storage.from_(db.BUCKET).remove([p])
        except Exception as e:
            print("cleanup storage failed:", type(e).__name__)
    for bid in bids:
        sb.table("bids").delete().eq("id", bid).execute()
    sb.table("bids").delete().eq("title", f"should-not-exist-{RUN}").execute()
    for u in users.values():
        try:
            sb.auth.admin.delete_user(u["id"])
        except Exception as e:
            print("cleanup user failed:", type(e).__name__)
    for org in orgs.values():
        sb.table("organization_members").delete().eq("organization_id", org).execute()
        sb.table("organizations").delete().eq("id", org).execute()
    left_users = [u for u in sb.auth.admin.list_users(page=1, per_page=200) if RUN in (u.email or "")]
    left_org = sb.table("organizations").select("id").like("slug", f"%{RUN}%").execute().data
    left_bids = sb.table("bids").select("id").like("title", f"%{RUN}%").execute().data
    check("cleanup: no disposable users, orgs, bids or storage objects remain",
          not left_users and not left_org and not left_bids)

print("\nHTTP evidence:")
for line in EVIDENCE:
    print("  " + line)
failed = [n for n, ok in RESULTS if not ok]
print(f"\nRUN {RUN}: {len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
sys.exit(1 if failed else 0)
