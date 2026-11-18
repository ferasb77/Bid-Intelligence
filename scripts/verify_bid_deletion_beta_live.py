#!/usr/bin/env python3
"""Admin bid deletion -- live Phoenix Beta acceptance on DISPOSABLE data
(migration 026 + tenancy.delete_bid_for_organization). Run inside a
bid-intelligence-beta image container with the beta env file; prints only
statuses, counts and ids (no secrets, passwords or tokens).

    docker run --rm --env-file app.env -w /app <image> python - <SOURCE_BID_ID> < this_file

SOURCE_BID_ID is an existing bid with completed FAST and FULL runs. It is only
READ: its rows and Storage objects are COPIED into a disposable bid, so the
deletion is exercised on realistic analysis data without any model call.

Creates two disposable organizations (A, B) and users ownerA, adminA,
memberA (org A) and adminB (org B), then proves the authorization matrix,
complete removal of the deleted bid's rows and Storage objects, that other
bids and organization records are untouched, refusal while an analysis is
running, atomic rollback on a database failure, recorded/retried Storage
failures and that a late background write cannot recreate a deleted bid's
objects. Disposable users can be kept for the UI check with KEEP_UI_WORLD=1
(then removed by running this script with CLEANUP_ONLY=<run id>).
"""
import json
import os
import secrets
import sys
import urllib.error
import urllib.request
from unittest import mock

sys.path.insert(0, "/work") if os.path.isdir("/work") else None
sys.path.insert(1, "/app")
import auth_client  # noqa: E402
import database as db  # noqa: E402
import tenancy  # noqa: E402

URL = os.environ["SUPABASE_URL"].rstrip("/")
ANON = os.environ["SUPABASE_ANON_KEY"]
sb = db.get_service_client()
RESULTS = []
BUCKET = db.BUCKET

BID_TABLES = ["analysis_results", "analysis_runs", "bid_briefs", "bid_decisions", "check_adjudication_evidence",
              "check_adjudications", "check_run_events", "check_semantic_batches", "clarifications", "debriefs",
              "deliverables", "documents", "full_analysis_events", "full_analysis_specialist_results",
              "outline_section_requirements", "outline_sections", "procurement_changes", "procurement_conflicts",
              "procurement_update_reviews", "proposal_intelligence_findings", "proposal_intelligence_runs",
              "proposal_package_snapshots", "proposal_requirement_assessments", "requirement_evidence_enrichments",
              "requirements", "section_drafts", "section_reviews", "submission_documents",
              "submission_evidence_items", "tasks"]


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}", flush=True)


def http(method, path, token, body=None, prefer=None):
    req = urllib.request.Request(f"{URL}{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None)
    req.add_header("apikey", ANON)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    if prefer:
        req.add_header("Prefer", prefer)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def count(table, bid):
    return len(sb.table(table).select("bid_id").eq("bid_id", bid).execute().data or [])


def objects(prefix):
    return sorted(o["name"] for o in (sb.storage.from_(BUCKET).list(prefix) or []) if o.get("id")) + sorted(
        f"analysis_reports/{o['name']}" for o in (sb.storage.from_(BUCKET).list(f"{prefix}/analysis_reports") or [])
        if o.get("id")) + sorted(
        f"buyer_research/{o['name']}" for o in (sb.storage.from_(BUCKET).list(f"{prefix}/buyer_research") or [])
        if o.get("id"))


def principal(uid, org, role):
    return tenancy.AuthContext(user_id=uid, email="", organization_id=org, organization_name="", role=role)


def as_session(uid, org, role):
    ctx = principal(uid, org, role)
    tenancy.set_session_principal_provider(lambda: ctx)


def attempt(uid, org, role, bid):
    as_session(uid, org, role)
    try:
        tenancy.delete_bid_for_organization(bid, org, uid)
        return "DELETED"
    except tenancy.BidDeletionError as e:
        return f"refused:{e.reason}"
    except tenancy.SessionAccessRevokedError as e:
        return f"denied:{e}"
    finally:
        tenancy.set_session_principal_provider(None)


def cleanup(run):
    """Delete this run's disposable bids through the deletion RPC (as an
    owner/admin of their organization), their Storage objects, then the
    disposable memberships, organizations and users."""
    for o in sb.table("organizations").select("id").like("slug", f"del-{run}-%").execute().data or []:
        admins = sb.table("organization_members").select("user_id").eq("organization_id", o["id"])             .in_("role", ["owner", "admin"]).execute().data or []
        for b in sb.table("bids").select("id").eq("organization_id", o["id"]).execute().data or []:
            for r in sb.table("analysis_runs").select("id,status").eq("bid_id", b["id"]).execute().data or []:
                if r["status"] not in ("COMPLETE", "PARTIAL", "FAILED"):
                    sb.table("analysis_runs").update({"status": "FAILED"}).eq("id", r["id"]).execute()
            sb.rpc("delete_bid_as_organization_admin", {"p_bid_id": b["id"], "p_organization_id": o["id"],
                                                         "p_actor_user_id": admins[0]["user_id"]}).execute()
        tenancy.process_bid_storage_cleanup(o["id"])
        sb.table("organization_members").delete().eq("organization_id", o["id"]).execute()
        sb.table("organizations").delete().eq("id", o["id"]).execute()
    for u in sb.auth.admin.list_users(page=1, per_page=200):
        if f"del-{run}" in (u.email or ""):
            sb.auth.admin.delete_user(u.id)
    left = (sb.table("organizations").select("id").like("slug", f"del-{run}-%").execute().data
            or sb.table("bids").select("id").like("title", f"DEL-TEST {run}%").execute().data
            or sb.table("bid_storage_cleanup").select("id").in_("organization_id", []).execute().data
            or [u for u in sb.auth.admin.list_users(page=1, per_page=200) if f"del-{run}" in (u.email or "")])
    return not left


if os.environ.get("CLEANUP_ONLY"):
    print("cleanup", "complete" if cleanup(os.environ["CLEANUP_ONLY"]) else "INCOMPLETE")
    sys.exit(0)

SOURCE = int(sys.argv[1])
RUN = secrets.token_hex(3)
KEEP = os.environ.get("KEEP_UI_WORLD") == "1"
print("run", RUN)


def copy_bid_into(bid):
    """Copy SOURCE's documents, runs, results, FULL events/specialists and
    Storage objects into disposable `bid` (read-only on SOURCE)."""
    run_map = {}
    for d in sb.table("documents").select("*").eq("bid_id", SOURCE).execute().data or []:
        row = {k: v for k, v in d.items() if k != "id"}
        row["bid_id"] = bid
        if d.get("storage_path"):
            data = sb.storage.from_(BUCKET).download(d["storage_path"])
            new = f"{bid}/{d['storage_path'].split('/', 1)[1]}"
            sb.storage.from_(BUCKET).upload(new, data, {"content-type": "application/octet-stream"})
            row["storage_path"] = new
            row["file_path"] = f"supabase://{BUCKET}/{new}"
        sb.table("documents").insert(row).execute()
    runs = sorted(sb.table("analysis_runs").select("*").eq("bid_id", SOURCE).execute().data or [],
                  key=lambda r: r["id"])
    for r in runs:
        row = {k: v for k, v in r.items() if k not in ("id",)}
        row["bid_id"] = bid
        row["source_analysis_run_id"] = run_map.get(r.get("source_analysis_run_id"))
        row["report_storage_path"] = None
        row["created_by_user_id"] = None
        new_id = sb.table("analysis_runs").insert(row).execute().data[0]["id"]
        run_map[r["id"]] = new_id
        if r.get("report_storage_path"):
            data = sb.storage.from_(BUCKET).download(r["report_storage_path"])
            path = f"{bid}/analysis_reports/{new_id}.pdf"
            sb.storage.from_(BUCKET).upload(path, data, {"content-type": "application/pdf"})
        try:
            data = sb.storage.from_(BUCKET).download(f"{SOURCE}/buyer_research/{r['id']}.json")
            sb.storage.from_(BUCKET).upload(f"{bid}/buyer_research/{new_id}.json", data,
                                            {"content-type": "application/json"})
        except Exception:
            pass
    for table in ("analysis_results", "full_analysis_events", "full_analysis_specialist_results"):
        for x in sb.table(table).select("*").eq("bid_id", SOURCE).execute().data or []:
            row = {k: v for k, v in x.items() if k != "id"}
            row["bid_id"], row["run_id"] = bid, run_map[x["run_id"]]
            sb.table(table).insert(row).execute()
    sb.table("requirements").insert({"bid_id": bid, "description": f"Disposable requirement {RUN}",
                                     "category": "Mandatory"}).execute()
    return run_map


users, orgs, bids = {}, {}, {}
try:
    for k in ("A", "B"):
        orgs[k] = sb.table("organizations").insert({"name": f"Deletion Test {k} {RUN}",
                                                    "slug": f"del-{RUN}-{k.lower()}"}).execute().data[0]["id"]
    for k, org, role in (("ownerA", "A", "owner"), ("adminA", "A", "admin"), ("memberA", "A", "member"),
                         ("adminB", "B", "admin")):
        pw = secrets.token_urlsafe(18)
        u = sb.auth.admin.create_user({"email": f"{k.lower()}.del-{RUN}@example.com", "password": pw,
                                       "email_confirm": True})
        users[k] = {"id": u.user.id, "email": u.user.email, "pw": pw, "org": orgs[org], "role": role}
        sb.table("organization_members").insert({"organization_id": orgs[org], "user_id": u.user.id,
                                                 "role": role}).execute()
    for k, org in (("full", "A"), ("owner", "A"), ("keep", "A"), ("orgB", "B"), ("atomic", "A"),
                   ("storagefail", "A"), ("ui1", "A"), ("ui2", "A")):
        bids[k] = sb.table("bids").insert({"organization_id": orgs[org], "title": f"DEL-TEST {RUN} {k}",
                                           "client": "Deletion Test Client", "file_number": f"DT-{RUN}-{k}",
                                           "stage": "Qualifying"}).execute().data[0]["id"]
    run_map = copy_bid_into(bids["full"])
    for k in ("owner", "keep", "orgB", "atomic", "storagefail", "ui1"):
        p = f"{bids[k]}/{RUN}-{k}.txt"
        sb.storage.from_(BUCKET).upload(p, f"synthetic {k}".encode(), {"content-type": "text/plain"})
        sb.table("documents").insert({"bid_id": bids[k], "name": f"{k}.txt", "doc_type": "RFP / Source",
                                      "storage_path": p}).execute()
    full_counts = {t: count(t, bids["full"]) for t in BID_TABLES if count(t, bids["full"])}
    check("disposable world: 2 orgs, 4 users, 8 bids; FAST+FULL rows and Storage copied from the source bid",
          full_counts.get("full_analysis_events", 0) > 0 and full_counts.get("analysis_results", 0) >= 2,
          json.dumps({"rows": full_counts, "objects": len(objects(str(bids["full"])))}))

    # shared/other data that must survive
    def others():
        return {
            "bids_outside_test_orgs": len(sb.table("bids").select("id").not_.in_(
                "organization_id", list(orgs.values())).execute().data or []),
            "source_rows": {t: count(t, SOURCE) for t in ("analysis_runs", "analysis_results", "documents",
                                                            "full_analysis_events")},
            "source_objects": len(objects(str(SOURCE))),
            "organizations": len(sb.table("organizations").select("id").execute().data or []),
            "memberships": len(sb.table("organization_members").select("user_id").execute().data or []),
            "keep_bid": count("documents", bids["keep"]),
        }
    before = others()

    # ── authorization matrix ─────────────────────────────────────────
    r = attempt(users["memberA"]["id"], orgs["A"], "member", bids["full"])
    check("member of the owning organization cannot delete", r == "refused:not_authorized", r)
    r = attempt(users["adminB"]["id"], orgs["B"], "admin", bids["full"])
    check("admin of another organization cannot delete (reported as not found)", r == "refused:not_found", r)
    as_session(users["adminB"]["id"], orgs["B"], "admin")
    try:
        tenancy.delete_bid_for_organization(bids["full"], orgs["A"], users["adminB"]["id"])
        r = "DELETED"
    except tenancy.SessionAccessRevokedError as e:
        r = f"denied:{e}"
    except tenancy.BidDeletionError as e:
        r = f"refused:{e.reason}"
    tenancy.set_session_principal_provider(None)
    check("org-B session naming org A is denied before any database call", r.startswith("denied:"), r)
    res = sb.rpc("delete_bid_as_organization_admin", {"p_bid_id": bids["full"], "p_organization_id": orgs["A"],
                                                       "p_actor_user_id": users["adminB"]["id"]}).execute().data
    check("database itself refuses a non-member actor even via the service role", res.get("reason") == "not_authorized",
          json.dumps(res))
    tokens = {k: auth_client.get_auth_client().auth.sign_in_with_password(
        {"email": u["email"], "password": u["pw"]}).session.access_token for k, u in users.items()}
    s1, b1 = http("POST", "/rest/v1/rpc/delete_bid_as_organization_admin", tokens["adminA"],
                  {"p_bid_id": bids["full"], "p_organization_id": orgs["A"], "p_actor_user_id": users["adminA"]["id"]})
    s2, b2 = http("DELETE", f"/rest/v1/bids?id=eq.{bids['full']}", tokens["adminA"], prefer="return=representation")
    s3, b3 = http("DELETE", f"/rest/v1/bids?id=eq.{bids['full']}", tokens["memberA"], prefer="return=representation")
    s4, b4 = http("GET", "/rest/v1/bid_storage_cleanup?select=id", tokens["adminA"])
    check("direct API requests cannot bypass the application (RPC not executable; table DELETE affects 0 rows)",
          s1 in (401, 403, 404) and s2 in (200, 204) and b2.strip() in ("[]", "") and s3 in (200, 204)
          and b3.strip() in ("[]", "") and count("documents", bids["full"]) > 0,
          f"rpc={s1} admin_delete={s2}:{b2.strip()[:20]} member_delete={s3}:{b3.strip()[:20]} cleanup_read={s4}")
    check("cleanup queue not readable with a user token", s4 in (401, 403, 404) or b4.strip() == "[]", str(s4))

    # ── running analysis blocks deletion ─────────────────────────────
    q = sb.table("analysis_runs").insert({"bid_id": bids["owner"], "analysis_mode": "FAST",
                                          "engine_version": "deletion-test", "status": "ANALYZING"}).execute().data[0]
    r = attempt(users["ownerA"]["id"], orgs["A"], "owner", bids["owner"])
    check("deletion refused while an analysis is running; nothing removed",
          r == "refused:analysis_in_progress" and count("documents", bids["owner"]) == 1
          and len(objects(str(bids["owner"]))) == 1, r)
    sb.table("analysis_runs").update({"status": "FAILED"}).eq("id", q["id"]).execute()

    # ── atomic rollback on a database failure ────────────────────────
    a_run = sb.table("analysis_runs").insert({"bid_id": bids["atomic"], "analysis_mode": "FAST",
                                              "engine_version": "deletion-test", "status": "COMPLETE"}).execute().data[0]
    x_run = sb.table("analysis_runs").insert({"bid_id": bids["keep"], "analysis_mode": "DEEP_VERIFY",
                                              "engine_version": "deletion-test", "status": "COMPLETE",
                                              "source_analysis_run_id": a_run["id"]}).execute().data[0]
    r = attempt(users["adminA"]["id"], orgs["A"], "admin", bids["atomic"])
    queued = sb.table("bid_storage_cleanup").select("id").eq("bid_id", bids["atomic"]).execute().data or []
    check("a database failure mid-deletion rolls everything back (bid, runs, documents, queue)",
          r == "refused:failed" and sb.table("bids").select("id").eq("id", bids["atomic"]).execute().data
          and count("analysis_runs", bids["atomic"]) == 1 and count("documents", bids["atomic"]) == 1
          and not queued and len(objects(str(bids["atomic"]))) == 1, r)
    sb.table("analysis_runs").delete().eq("id", x_run["id"]).execute()

    # ── admin deletes the bid with completed FAST + FULL analyses ────
    objs = objects(str(bids["full"]))
    r = attempt(users["adminA"]["id"], orgs["A"], "admin", bids["full"])
    left = {t: count(t, bids["full"]) for t in BID_TABLES}
    check("admin deletes a bid with completed FAST and FULL analyses", r == "DELETED", r)
    check("every bid-owned row is gone", not any(left.values()) and not sb.table("bids").select("id").eq(
        "id", bids["full"]).execute().data, json.dumps({k: v for k, v in left.items() if v}))
    check("its Storage objects are removed and the cleanup queue is empty",
          objs and not objects(str(bids["full"]))
          and not sb.table("bid_storage_cleanup").select("id").eq("bid_id", bids["full"]).execute().data,
          f"{len(objs)} objects")
    old_runs = list(run_map.values())
    check("no document versions / results of the deleted runs remain",
          not sb.table("analysis_results").select("id").in_("run_id", old_runs).execute().data)

    # ── owner deletes ────────────────────────────────────────────────
    r = attempt(users["ownerA"]["id"], orgs["A"], "owner", bids["owner"])
    check("owner deletes a bid", r == "DELETED" and not objects(str(bids["owner"])), r)

    # ── Storage failure is recorded, reported and retried ────────────
    real = db.get_service_client()

    class FailingStorage:
        def from_(self, bucket):
            return self

        def remove(self, names):
            raise RuntimeError("simulated storage outage")

    class Proxy:
        storage = FailingStorage()

        def __getattr__(self, name):
            return getattr(real, name)

    as_session(users["adminA"]["id"], orgs["A"], "admin")
    with mock.patch.object(tenancy.db, "get_service_client", return_value=Proxy()):
        out = tenancy.delete_bid_for_organization(bids["storagefail"], orgs["A"], users["adminA"]["id"])
    tenancy.set_session_principal_provider(None)
    pend = sb.table("bid_storage_cleanup").select("*").eq("bid_id", bids["storagefail"]).execute().data or []
    check("Storage outage: bid deleted, failure reported to the caller and recorded for retry",
          out["storage_pending"] == 1 and len(pend) == 1 and pend[0]["attempts"] >= 1
          and "simulated storage outage" in (pend[0]["last_error"] or "")
          and len(objects(str(bids["storagefail"]))) == 1, json.dumps({k: out[k] for k in ("storage_pending",)}))
    rr = tenancy.process_bid_storage_cleanup(orgs["A"])
    check("retry removes the leftover object and clears the queue",
          rr["removed"] >= 1 and rr["pending"] == 0 and not objects(str(bids["storagefail"]))
          and not sb.table("bid_storage_cleanup").select("id").eq("bid_id", bids["storagefail"]).execute().data,
          json.dumps(rr))

    # ── a late background write cannot recreate a deleted bid's objects
    try:
        db.upload_analysis_report(bids["full"], 999999, b"%PDF late")
        late = "WRITTEN"
    except LookupError:
        late = "refused"
    try:
        db.upload_json_object(f"{bids['full']}/buyer_research/999999.json", {"status": "COMPLETE"})
        late2 = "WRITTEN"
    except LookupError:
        late2 = "refused"
    check("late report / research writes for a deleted bid are refused, nothing recreated",
          late == late2 == "refused" and not objects(str(bids["full"])), f"{late}/{late2}")

    # ── nothing else changed ─────────────────────────────────────────
    after = others()
    check("other bids, the source bid and organization records are unchanged", after == before,
          json.dumps({"before": before, "after": after}))
    check("remaining disposable bids intact", count("documents", bids["keep"]) == 1
          and count("documents", bids["orgB"]) == 1)
finally:
    tenancy.set_session_principal_provider(None)
    if KEEP:
        print("UI world kept:", json.dumps({"run": RUN, "orgA": orgs.get("A"), "bids": {k: bids.get(k) for k in (
            "keep", "ui1", "ui2", "orgB")}}))
        with open("/out/ui_users.json", "w") as f:
            json.dump({k: {"email": u["email"], "pw": u["pw"], "role": u["role"]} for k, u in users.items()}, f)
    else:
        check("cleanup: no disposable users, organizations, bids or objects remain", cleanup(RUN))

failed = [n for n, ok in RESULTS if not ok]
print(f"\nRUN {RUN}: {len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
sys.exit(1 if failed else 0)
