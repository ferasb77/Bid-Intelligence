#!/usr/bin/env python3
"""Super Admin MVP: verify migration 024 on a fresh, disposable PostgreSQL 17
cluster (reuses the R2A.1 harness). Applies supabase_schema.sql + 001-023 +
024, then checks the live catalog and effective behaviour:

  * RLS enabled and ZERO policies on platform_admins / platform_admin_audit_log
  * anon / authenticated hold no table or sequence privilege on either table
  * authenticated (with a JWT-like sub claim, including an org 'admin') is
    rejected for SELECT/INSERT on both tables and for INSERT/UPDATE on
    organization_members (no self-elevation path)
  * service_role (BYPASSRLS, as in Supabase) can read platform_admins and
    append audit rows, but UPDATE/DELETE/TRUNCATE of the audit log is rejected,
    including for the superuser (append-only trigger)
  * re-applying 024 is idempotent

No network; the cluster is removed on exit.
"""
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(__file__))
import test_r2a_tenant_isolation as h  # noqa: E402
import psycopg2  # noqa: E402

M024 = os.path.join(h.MIGRATIONS_DIR, "024_platform_super_admin.sql")
TABLES = ("platform_admins", "platform_admin_audit_log")
RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")


def expect_denied(cur, sql, params=None):
    cur.execute("savepoint s")
    try:
        cur.execute(sql, params)
        rows = cur.rowcount
        cur.execute("release savepoint s")
        return False, f"succeeded (rowcount={rows})"
    except psycopg2.Error as e:
        cur.execute("rollback to savepoint s")
        return True, type(e).__name__ + ": " + str(e).splitlines()[0]


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
        # Supabase default privileges grant new public tables to API roles;
        # emulate that so 024's explicit revokes are actually exercised.
        cur.execute("alter default privileges in schema public grant all on tables to anon, authenticated, service_role")
        cur.execute("alter default privileges in schema public grant all on sequences to anon, authenticated, service_role")
        cur.execute("alter role service_role bypassrls")
        h.run_sql_file(cur, M024)
        h.run_sql_file(cur, M024)  # idempotent re-apply
        check("024 applies cleanly twice (idempotent)", True)
        conn.commit()

        # ── catalog
        for t in TABLES:
            cur.execute("select relrowsecurity from pg_class where oid = %s::regclass", (f"public.{t}",))
            check(f"{t}: RLS enabled", cur.fetchone()[0] is True)
            cur.execute("select count(*) from pg_policy where polrelid = %s::regclass", (f"public.{t}",))
            check(f"{t}: zero policies", cur.fetchone()[0] == 0)
            for role in ("anon", "authenticated"):
                for priv in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE"):
                    cur.execute("select has_table_privilege(%s, %s, %s)", (role, f"public.{t}", priv))
                    if cur.fetchone()[0]:
                        check(f"{t}: {role} lacks {priv}", False)
            check(f"{t}: anon/authenticated hold no table privileges", True)
        for role in ("anon", "authenticated"):
            cur.execute("select has_sequence_privilege(%s, 'public.platform_admin_audit_log_id_seq', 'USAGE')", (role,))
            check(f"audit sequence: {role} lacks USAGE", not cur.fetchone()[0])
        for priv, expected in (("SELECT", True), ("INSERT", True), ("UPDATE", True), ("DELETE", True)):
            cur.execute("select has_table_privilege('service_role', 'public.platform_admin_audit_log', %s)", (priv,))
            # UPDATE/DELETE may be granted by default privileges; the trigger still rejects them (checked below)
            if priv in ("SELECT", "INSERT"):
                check(f"audit log: service_role has {priv}", cur.fetchone()[0] is expected)
            else:
                cur.fetchone()

        # ── seed: owner (platform admin) + Phoenix org with client admin and member
        owner, ca, member = (str(uuid.uuid4()) for _ in range(3))
        org = str(uuid.uuid4())
        for uid, email in ((owner, "owner@example.com"), (ca, "ca@phoenix.example"), (member, "m@phoenix.example")):
            cur.execute("insert into auth.users (id, email) values (%s, %s)", (uid, email))
        cur.execute("insert into public.organizations (id, name, slug) values (%s, 'Phoenix', 'phoenix')", (org,))
        cur.execute("insert into public.organization_members values (%s, %s, 'admin'), (%s, %s, 'member')",
                    (org, ca, org, member))
        cur.execute("insert into public.platform_admins (user_id, granted_by) values (%s, 'bootstrap-test')", (owner,))
        conn.commit()

        # ── authenticated callers (client admin, member) — no read/write, no self-elevation
        for label, uid in (("client admin", ca), ("member", member)):
            h.set_role_auth(cur, uid, "authenticated")
            for t in TABLES:
                ok, d = expect_denied(cur, f"select * from public.{t}")
                check(f"{label}: SELECT {t} denied", ok, d)
            ok, d = expect_denied(cur, "insert into public.platform_admins (user_id, granted_by) values (%s, 'self')", (uid,))
            check(f"{label}: self-insert into platform_admins denied", ok, d)
            ok, d = expect_denied(cur, "insert into public.platform_admin_audit_log (action, outcome) values ('forge','success')")
            check(f"{label}: forging audit row denied", ok, d)
            ok, d = expect_denied(cur, "insert into public.organization_members values (%s, %s, 'owner')", (org, uid))
            check(f"{label}: membership insert denied", ok, d)
            cur.execute("savepoint s")
            try:
                cur.execute("update public.organization_members set role = 'owner' where user_id = %s", (uid,))
                changed = cur.rowcount
                cur.execute("release savepoint s")
                check(f"{label}: role self-elevation changes 0 rows", changed == 0, f"rowcount={changed}")
            except psycopg2.Error as e:
                cur.execute("rollback to savepoint s")
                check(f"{label}: role self-elevation rejected", True, type(e).__name__)
            h.set_role_auth(cur, None)
        conn.commit()

        cur.execute("select role from public.organization_members where user_id = %s", (ca,))
        check("client admin role unchanged after attempts", cur.fetchone()[0] == "admin")
        cur.execute("select count(*) from public.platform_admins")
        check("platform_admins still exactly 1 row", cur.fetchone()[0] == 1)

        # anon
        h.set_role_auth(cur, None, "anon")
        for t in TABLES:
            ok, d = expect_denied(cur, f"select * from public.{t}")
            check(f"anon: SELECT {t} denied", ok, d)
        h.set_role_auth(cur, None)
        conn.commit()

        # ── service_role: read + append; audit log immutable
        cur.execute("set role service_role")
        cur.execute("select user_id from public.platform_admins")
        check("service_role reads platform_admins", [str(r[0]) for r in cur.fetchall()] == [owner])
        cur.execute("insert into public.platform_admin_audit_log (actor_user_id, action, outcome, details) "
                    "values (%s, 'create_user', 'success', '{\"role\":\"member\"}') returning id", (owner,))
        audit_id = cur.fetchone()[0]
        check("service_role appends audit row", audit_id is not None)
        for sql in ("update public.platform_admin_audit_log set outcome = 'denied'",
                    "delete from public.platform_admin_audit_log",
                    "truncate public.platform_admin_audit_log"):
            ok, d = expect_denied(cur, sql)
            check(f"service_role: {sql.split()[0].upper()} audit log rejected", ok, d)
        cur.execute("reset role")
        for sql in ("update public.platform_admin_audit_log set outcome = 'denied'",
                    "delete from public.platform_admin_audit_log"):
            ok, d = expect_denied(cur, sql)
            check(f"superuser: {sql.split()[0].upper()} audit log rejected (trigger)", ok, d)
        cur.execute("select count(*) from public.platform_admin_audit_log")
        check("audit row intact", cur.fetchone()[0] == 1)

        # cascade: deleting an auth user removes platform authority
        cur.execute("delete from auth.users where id = %s", (owner,))
        cur.execute("select count(*) from public.platform_admins")
        check("platform_admins row cascades with auth.users delete", cur.fetchone()[0] == 0)
        conn.rollback()
        conn.close()

    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed; cluster removed.")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
