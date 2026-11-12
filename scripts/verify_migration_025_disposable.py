#!/usr/bin/env python3
"""Super Admin revocation correction: verify migration 025 on a fresh,
disposable PostgreSQL 17 cluster (reuses the R2A.1 harness).

Applies supabase_schema.sql + 001-024, emulates the Supabase/GoTrue pieces
025 depends on (auth.users.banned_until / deleted_at, default EXECUTE grants
on new functions to anon/authenticated -- the drift observed on the beta),
applies 025 twice, then exercises the effective behaviour with simulated
JWT principals (request.jwt.claim.sub + SET ROLE authenticated):

  * an active member reads/writes own-tenant rows; a disabled (banned) or
    soft-deleted user's still-"valid" principal is denied on membership,
    organizations, bids, documents, document_versions, requirements,
    analysis_runs/analysis_results and writes; an expired ban is active
  * a removed membership denies immediately; re-adding restores only that org
  * cross-tenant access stays denied throughout
  * every application SECURITY DEFINER RPC is service_role-only after 025
  * session_access_status returns the authoritative reason codes
  * every public RLS policy routes through the active-aware helpers

No network; the cluster is removed on exit.
"""
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(__file__))
import test_r2a_tenant_isolation as h  # noqa: E402
import psycopg2  # noqa: E402

M024 = os.path.join(h.MIGRATIONS_DIR, "024_platform_super_admin.sql")
M025 = os.path.join(h.MIGRATIONS_DIR, "025_active_account_authorization.sql")
RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")


def attempt(cur, sql, params=None):
    """(ok, rows_or_rowcount, error) without aborting the transaction."""
    cur.execute("savepoint s")
    try:
        cur.execute(sql, params)
        out = cur.fetchall() if cur.description else cur.rowcount
        cur.execute("release savepoint s")
        return True, out, None
    except psycopg2.Error as e:
        cur.execute("rollback to savepoint s")
        return False, None, type(e).__name__


def visible(cur, uid, table, col, value):
    h.set_role_auth(cur, uid, "authenticated")
    ok, rows, err = attempt(cur, f"select 1 from public.{table} where {col} = %s", (value,))
    h.set_role_auth(cur, None)
    return ok and bool(rows)


def main():
    pg_bin = h.find_pg_bin()
    with h.DisposablePostgresCluster(pg_bin) as cluster:
        conn = cluster.get_connection()
        conn.autocommit = False
        cur = conn.cursor()
        cur.execute("select version()")
        print("Server:", cur.fetchone()[0])
        h.setup_fresh_database_001_to_022(cur)
        h.run_sql_file(cur, os.path.join(h.MIGRATIONS_DIR, "023_enable_base_tables_tenant_rls.sql"))
        cur.execute("alter default privileges in schema public grant all on tables to anon, authenticated, service_role")
        cur.execute("alter default privileges in schema public grant all on sequences to anon, authenticated, service_role")
        cur.execute("alter role service_role bypassrls")
        h.run_sql_file(cur, M024)
        # GoTrue columns 025 reads (present on every real Supabase auth.users)
        cur.execute("alter table auth.users add column if not exists banned_until timestamptz, "
                    "add column if not exists deleted_at timestamptz")
        # Reproduce the beta drift: API roles hold EXECUTE on every function
        cur.execute("grant execute on all functions in schema public to anon, authenticated")
        cur.execute("alter default privileges in schema public grant execute on functions to anon, authenticated, service_role")
        conn.commit()

        # Pre-025 baseline: the defect -- a banned user is still authorized
        seed = h.seed_two_tenants(cur)
        alice, bob = seed["alice_id"], seed["bob_id"]
        acme_org, globex_org = seed["acme_org"], seed["globex_org"]
        acme_bid, globex_bid = seed["acme_bid"], seed["globex_bid"]
        acme_doc = seed["acme_records"]["documents"]
        acme_ver = seed["acme_records"]["document_versions"]
        cur.execute("update auth.users set banned_until = now() + interval '100 years' where id = %s", (alice,))
        pre_bid = visible(cur, alice, "bids", "id", acme_bid)
        pre_mem = visible(cur, alice, "organization_members", "user_id", alice)
        check("baseline (pre-025): banned user's principal still reads bids + membership (defect reproduced)",
              pre_bid and pre_mem, f"bids={pre_bid} membership={pre_mem}")
        cur.execute("update auth.users set banned_until = null where id = %s", (alice,))
        conn.commit()

        h.run_sql_file(cur, M025)
        h.run_sql_file(cur, M025)
        conn.commit()
        check("025 applies cleanly twice (idempotent), self-check passed", True)

        # analysis rows for the acme bid
        cur.execute("insert into public.analysis_runs (bid_id, analysis_mode, engine_version, status) "
                    "values (%s, 'FAST', 'verify-025', 'COMPLETE') returning id", (acme_bid,))
        run_id = cur.fetchone()[0]
        ok, _, err = attempt(cur, "insert into public.analysis_results (bid_id, run_id, structured_intelligence) "
                                  "values (%s, %s, '{}'::jsonb) returning id", (acme_bid, run_id))
        has_results = ok
        conn.commit()

        protected = [("organization_members", "user_id", alice), ("organizations", "id", acme_org),
                     ("bids", "id", acme_bid), ("documents", "id", acme_doc),
                     ("document_versions", "id", acme_ver),
                     ("requirements", "id", seed["acme_records"]["requirements"]),
                     ("analysis_runs", "id", run_id)]
        if has_results:
            protected.append(("analysis_results", "run_id", run_id))

        def matrix(label, uid, expect):
            for t, c, v in protected:
                got = visible(cur, uid, t, c, v)
                check(f"{label}: {t} {'visible' if expect else 'denied'}", got == expect)

        # ── active member
        matrix("active member", alice, True)
        h.set_role_auth(cur, alice, "authenticated")
        ok, n, err = attempt(cur, "update public.bids set title = title where id = %s", (acme_bid,))
        check("active member: UPDATE own bid succeeds", ok and n == 1, f"rowcount={n}")
        h.set_role_auth(cur, None)
        conn.commit()

        # ── disabled (banned) with the same principal
        cur.execute("update auth.users set banned_until = now() + interval '100 years' where id = %s", (alice,))
        conn.commit()
        matrix("banned user (stale principal)", alice, False)
        h.set_role_auth(cur, alice, "authenticated")
        ok, n, err = attempt(cur, "update public.bids set title = 'pwned' where id = %s", (acme_bid,))
        check("banned user: UPDATE bid changes 0 rows", (ok and n == 0) or not ok, f"ok={ok} n={n} {err or ''}")
        ok, n, err = attempt(cur, "insert into public.bids (organization_id, title) values (%s, 'x')", (acme_org,))
        check("banned user: INSERT bid rejected", not ok, err or "")
        ok, rows, err = attempt(cur, "select public.is_organization_member(%s), public.can_access_bid(%s), "
                                     "public.current_user_is_active()", (acme_org, acme_bid))
        check("banned user: helpers all false", ok and rows[0] == (False, False, False), str(rows))
        h.set_role_auth(cur, None)
        conn.commit()

        # expired ban counts as active again
        cur.execute("update auth.users set banned_until = now() - interval '1 minute' where id = %s", (alice,))
        conn.commit()
        check("expired ban: member access restored", visible(cur, alice, "bids", "id", acme_bid))

        # soft-deleted
        cur.execute("update auth.users set banned_until = null, deleted_at = now() where id = %s", (alice,))
        conn.commit()
        matrix("soft-deleted user", alice, False)
        cur.execute("update auth.users set deleted_at = null where id = %s", (alice,))
        conn.commit()

        # principal with no auth.users row
        ghost = str(uuid.uuid4())
        check("unknown principal: no bid access", not visible(cur, ghost, "bids", "id", acme_bid))

        # ── membership removal / re-add
        cur.execute("delete from public.organization_members where user_id = %s and organization_id = %s", (alice, acme_org))
        conn.commit()
        matrix("removed membership (stale principal)", alice, False)
        cur.execute("insert into public.organization_members (organization_id, user_id, role) values (%s, %s, 'member')",
                    (acme_org, alice))
        conn.commit()
        matrix("membership re-added", alice, True)

        # ── cross-tenant stays denied (active and disabled)
        for label in ("active", "banned"):
            if label == "banned":
                cur.execute("update auth.users set banned_until = now() + interval '1 day' where id = %s", (alice,))
                conn.commit()
            check(f"cross-tenant ({label}): globex bid denied", not visible(cur, alice, "bids", "id", globex_bid))
            check(f"cross-tenant ({label}): globex membership rows denied",
                  not visible(cur, alice, "organization_members", "organization_id", globex_org))
        cur.execute("update auth.users set banned_until = null where id = %s", (alice,))
        conn.commit()
        check("re-enabled: own tenant visible", visible(cur, alice, "bids", "id", acme_bid))
        check("re-enabled: other tenant still denied", not visible(cur, alice, "bids", "id", globex_bid))
        check("bob unaffected throughout", visible(cur, bob, "bids", "id", globex_bid))

        # ── RPC surface
        cur.execute("""select p.oid::regprocedure::text, has_function_privilege('anon', p.oid, 'EXECUTE'),
                              has_function_privilege('authenticated', p.oid, 'EXECUTE'),
                              has_function_privilege('service_role', p.oid, 'EXECUTE'), p.proname
                       from pg_proc p join pg_namespace n on n.oid = p.pronamespace
                       where n.nspname = 'public' and p.prosecdef order by 1""")
        allowed_auth = {"is_organization_member", "can_access_bid", "current_user_is_active"}
        rows = cur.fetchall()
        bad = [r[0] for r in rows if r[1] or (r[2] and r[4] not in allowed_auth)]
        check(f"all {len(rows)} SECURITY DEFINER functions: no anon EXECUTE; authenticated only on the 3 helpers",
              not bad, ", ".join(bad))
        trig = {"prevent_applied_change_mutation", "prevent_applied_review_document_mutation",
                "prevent_applied_review_mutation", "prevent_resolved_conflict_mutation"}
        missing = [r[0] for r in rows if not r[3] and r[4] not in trig]
        check("service_role keeps EXECUTE on every application RPC", not missing, ", ".join(missing))
        h.set_role_auth(cur, alice, "authenticated")
        ok, _, err = attempt(cur, "select public.refresh_bid_brief_projection(%s)", (acme_bid,))
        check("authenticated: refresh_bid_brief_projection RPC denied", not ok, err or "")
        ok, _, err = attempt(cur, "select public.session_access_status(%s, %s)", (alice, acme_org))
        check("authenticated: session_access_status denied", not ok, err or "")
        ok, _, err = attempt(cur, "select public.user_account_is_active(%s)", (bob,))
        check("authenticated: user_account_is_active (probe others) denied", not ok, err or "")
        h.set_role_auth(cur, None)
        conn.commit()

        # ── session_access_status (service_role)
        cur.execute("set role service_role")

        def status(uid, org):
            cur.execute("select public.session_access_status(%s, %s)", (uid, org))
            return cur.fetchone()[0]
        s = status(alice, acme_org)
        check("status: active member ok with role", s == {"ok": True, "reason": "", "role": "member"}, str(s))
        check("status: wrong org -> membership_removed", status(alice, globex_org)["reason"] == "membership_removed")
        check("status: unknown user -> account_not_found", status(ghost, acme_org)["reason"] == "account_not_found")
        check("status: null user -> account_not_found", status(None, acme_org)["reason"] == "account_not_found")
        cur.execute("reset role")
        cur.execute("update auth.users set banned_until = now() + interval '1 day' where id = %s", (alice,))
        cur.execute("set role service_role")
        check("status: banned -> account_disabled", status(alice, acme_org)["reason"] == "account_disabled")
        cur.execute("reset role")
        cur.execute("update auth.users set banned_until = null, deleted_at = now() where id = %s", (alice,))
        cur.execute("set role service_role")
        check("status: soft-deleted -> account_not_found", status(alice, acme_org)["reason"] == "account_not_found")
        cur.execute("reset role")
        conn.rollback()

        # ── every policy routes through the active-aware path
        cur.execute("""select tablename, policyname from pg_policies where schemaname = 'public'
                       and coalesce(qual, '') || coalesce(with_check, '') !~ '(can_access_bid|is_organization_member|current_user_is_active)'""")
        stray = cur.fetchall()
        check("every public policy uses an active-aware helper", not stray, str(stray))
        cur.execute("select count(*) from pg_policies where schemaname = 'public'")
        print(f"  (public policies: {cur.fetchone()[0]})")
        conn.close()

    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed; cluster removed.")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
