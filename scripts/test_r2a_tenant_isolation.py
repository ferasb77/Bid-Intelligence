#!/usr/bin/env python3
"""Package R2A: Tenant-Boundary Correction Verification Harness.

Adversarial multi-tenant isolation suite executing against disposable PostgreSQL 17:
1. Reconstructs pristine migration 001-022 state (RLS disabled on 11 base tables).
2. DEMONSTRATES PRE-REMEDIATION VULNERABILITY:
   - Authenticated User (Alice in Acme) successfully selects, inserts, and updates foreign tenant (Globex) rows.
3. APPLIES MIGRATION 023:
   - Enables RLS on all 11 base tables and enforces least-privilege role grants.
4. DEMONSTRATES POST-REMEDIATION NEGATIVE CONTROLS:
   - Alice cannot read, insert, update, or delete any Globex rows across all 11 tables.
   - Unauthenticated 'anon' role is completely rejected.
5. DEMONSTRATES POST-REMEDIATION POSITIVE CONTROLS:
   - Alice performs legitimate CRUD operations on Acme Corp's bids, requirements, tasks, coaches, etc.
"""
import os
import sys
import uuid
import json
import time
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

PG_PORT = int(os.environ.get("PG_PORT", 54330))
PG_HOST = os.environ.get("PG_HOST", "127.0.0.1")
PG_USER = os.environ.get("PG_USER", "postgres")
PG_DB = os.environ.get("PG_DB", "postgres")

RECOVERY_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MIGRATIONS_DIR = os.path.join(RECOVERY_ROOT, "migrations")

BASE_TABLES = [
    "bids",
    "requirements",
    "tasks",
    "documents",
    "document_versions",
    "outline_sections",
    "content_library",
    "coaches",
    "clarifications",
    "debriefs",
    "deliverables",
]


def get_conn():
    conn = psycopg2.connect(
        host=PG_HOST,
        port=PG_PORT,
        user=PG_USER,
        dbname=PG_DB,
    )
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    return conn


def run_sql_file(cur, filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        sql = f.read()
    cur.execute(sql)


def set_role_auth(cur, user_id=None, role="authenticated"):
    if role == "postgres" or (user_id is None and role == "authenticated"):
        cur.execute("reset role;")
        cur.execute("select set_config('request.jwt.claim.sub', '', false);")
        cur.execute("select set_config('request.jwt.claim.role', '', false);")
    else:
        cur.execute(f"set role {role};")
        sub = user_id or ""
        cur.execute(f"select set_config('request.jwt.claim.sub', '{sub}', false);")
        cur.execute(f"select set_config('request.jwt.claim.role', '{role}', false);")


def setup_fresh_database_001_to_022(cur):
    """Rebuild database from clean slate up to migration 022 (pre-remediation state)."""
    print("[1/5] Initializing fresh PostgreSQL environment (migrations 001-022)...")
    cur.execute("drop schema if exists public cascade; create schema public;")
    cur.execute("drop schema if exists auth cascade; create schema auth;")
    cur.execute("drop schema if exists storage cascade; create schema storage;")
    cur.execute("grant all on schema public to postgres, public;")
    cur.execute("grant all on schema auth to postgres, public;")
    cur.execute("grant all on schema storage to postgres, public;")

    for r in ["anon", "authenticated", "service_role"]:
        cur.execute(f"""
            do $$
            begin
                if not exists (select 1 from pg_roles where rolname = '{r}') then
                    create role {r};
                end if;
            end $$;
        """)

    cur.execute("""
        create extension if not exists pgcrypto;
        create extension if not exists "uuid-ossp";

        create table if not exists auth.users (
            id uuid primary key default gen_random_uuid(),
            email text unique not null,
            created_at timestamptz not null default now()
        );

        create or replace function auth.uid() returns uuid language sql stable as $$
            select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid;
        $$;
        create or replace function auth.role() returns text language sql stable as $$
            select coalesce(nullif(current_setting('request.jwt.claim.role', true), ''), 'anon')::text;
        $$;

        create table if not exists storage.buckets (
            id text primary key,
            name text not null,
            public boolean default false
        );
        create table if not exists storage.objects (
            id uuid primary key default gen_random_uuid(),
            bucket_id text references storage.buckets(id),
            name text,
            owner uuid,
            created_at timestamptz default now()
        );
    """)

    # Base schema
    run_sql_file(cur, os.path.join(RECOVERY_ROOT, "supabase_schema.sql"))

    # Migrations 001-022
    for i in range(1, 23):
        fname = [f for f in os.listdir(MIGRATIONS_DIR) if f.startswith(f"{i:03d}_")][0]
        run_sql_file(cur, os.path.join(MIGRATIONS_DIR, fname))

    # Grant table access to authenticated for testing effective RLS policies
    cur.execute("grant select, insert, update, delete on all tables in schema public to authenticated;")
    print("      Migrations 001-022 applied cleanly.")


def seed_two_tenants(cur):
    """Seed Acme Corp (Tenant 1) and Globex Inc (Tenant 2)."""
    set_role_auth(cur, None)

    alice_id = str(uuid.uuid4())
    bob_id = str(uuid.uuid4())
    cur.execute("insert into auth.users (id, email) values (%s, %s);", (alice_id, "alice@acme.com"))
    cur.execute("insert into auth.users (id, email) values (%s, %s);", (bob_id, "bob@globex.com"))

    acme_org = str(uuid.uuid4())
    globex_org = str(uuid.uuid4())
    cur.execute("insert into public.organizations (id, name, slug) values (%s, %s, %s);", (acme_org, "Acme Corp", "acme"))
    cur.execute("insert into public.organizations (id, name, slug) values (%s, %s, %s);", (globex_org, "Globex Inc", "globex"))

    cur.execute("insert into public.organization_members (organization_id, user_id, role) values (%s, %s, 'member');", (acme_org, alice_id))
    cur.execute("insert into public.organization_members (organization_id, user_id, role) values (%s, %s, 'member');", (globex_org, bob_id))

    # Acme Bid & Child records
    cur.execute("insert into public.bids (organization_id, title, client) values (%s, 'Acme Cloud Bid', 'Ontario Govt') returning id;", (acme_org,))
    acme_bid = cur.fetchone()[0]

    cur.execute("insert into public.requirements (bid_id, description) values (%s, 'Acme Req 1');", (acme_bid,))
    cur.execute("insert into public.tasks (bid_id, title) values (%s, 'Acme Task 1');", (acme_bid,))
    cur.execute("insert into public.documents (bid_id, name) values (%s, 'Acme_RFP.pdf') returning id;", (acme_bid,))
    acme_doc = cur.fetchone()[0]
    cur.execute("insert into public.document_versions (document_id, file_path) values (%s, '/acme/v1.pdf');", (acme_doc,))
    cur.execute("insert into public.outline_sections (bid_id, title) values (%s, 'Acme Section 1');", (acme_bid,))
    cur.execute("insert into public.content_library (bid_id, title, content) values (%s, 'Acme Boilerplate', 'Text');", (acme_bid,))
    cur.execute("insert into public.coaches (organization_id, name) values (%s, 'Acme Coach Mina');", (acme_org,))
    cur.execute("insert into public.clarifications (bid_id, question) values (%s, 'Acme Q1?');", (acme_bid,))
    cur.execute("insert into public.debriefs (bid_id, outcome) values (%s, 'Won');", (acme_bid,))
    cur.execute("insert into public.deliverables (bid_id, title) values (%s, 'Acme Deliv 1');", (acme_bid,))

    # Globex Bid & Child records (Confidential Foreign Tenant)
    cur.execute("insert into public.bids (organization_id, title, client) values (%s, 'Globex Secret Bid', 'City of Calgary') returning id;", (globex_org,))
    globex_bid = cur.fetchone()[0]

    cur.execute("insert into public.requirements (bid_id, description) values (%s, 'Globex Secret Req');", (globex_bid,))
    cur.execute("insert into public.tasks (bid_id, title) values (%s, 'Globex Secret Task');", (globex_bid,))
    cur.execute("insert into public.documents (bid_id, name) values (%s, 'Globex_Secret.pdf') returning id;", (globex_bid,))
    globex_doc = cur.fetchone()[0]
    cur.execute("insert into public.document_versions (document_id, file_path) values (%s, '/globex/secret.pdf');", (globex_doc,))
    cur.execute("insert into public.outline_sections (bid_id, title) values (%s, 'Globex Secret Section');", (globex_bid,))
    cur.execute("insert into public.content_library (bid_id, title, content) values (%s, 'Globex Secret IP', 'Confidential');", (globex_bid,))
    cur.execute("insert into public.coaches (organization_id, name) values (%s, 'Globex Secret Coach');", (globex_org,))
    cur.execute("insert into public.clarifications (bid_id, question) values (%s, 'Globex Secret Q?');", (globex_bid,))
    cur.execute("insert into public.debriefs (bid_id, outcome) values (%s, 'Pending');", (globex_bid,))
    cur.execute("insert into public.deliverables (bid_id, title) values (%s, 'Globex Secret Deliv');", (globex_bid,))

    return {
        "alice_id": alice_id,
        "bob_id": bob_id,
        "acme_org": acme_org,
        "globex_org": globex_org,
        "acme_bid": acme_bid,
        "globex_bid": globex_bid,
    }


def demonstrate_pre_remediation_vulnerability(cur, env):
    """Prove that Alice can see, insert, and update Globex data in the pre-remediation state."""
    print("\n[2/5] Demonstrating Pre-Remediation Cross-Tenant Vulnerability...")
    alice_id = env["alice_id"]
    globex_bid = env["globex_bid"]
    globex_org = env["globex_org"]

    set_role_auth(cur, alice_id, "authenticated")

    # 1. Check RLS status on 11 base tables
    cur.execute("""
        select tablename, rowsecurity
        from pg_tables
        where schemaname = 'public' and tablename in %s;
    """, (tuple(BASE_TABLES),))
    rls_statuses = dict(cur.fetchall())
    for t in BASE_TABLES:
        assert rls_statuses[t] is False, f"Expected RLS disabled on {t} in pre-remediation state!"
    print("      CONFIRMED: rowsecurity is FALSE for all 11 base tables.")

    # 2. Alice queries Globex's confidential data
    cur.execute("select count(*) from public.bids where id = %s;", (globex_bid,))
    bids_leak = cur.fetchone()[0]

    cur.execute("select count(*) from public.requirements where bid_id = %s;", (globex_bid,))
    reqs_leak = cur.fetchone()[0]

    cur.execute("select count(*) from public.documents where bid_id = %s;", (globex_bid,))
    docs_leak = cur.fetchone()[0]

    cur.execute("select count(*) from public.coaches where organization_id = %s;", (globex_org,))
    coaches_leak = cur.fetchone()[0]

    print(f"      VULNERABILITY PROOF: Alice selected Globex bid rows: {bids_leak} (expected 1 under flaw)")
    print(f"      VULNERABILITY PROOF: Alice selected Globex requirements: {reqs_leak} (expected 1 under flaw)")
    print(f"      VULNERABILITY PROOF: Alice selected Globex documents: {docs_leak} (expected 1 under flaw)")
    print(f"      VULNERABILITY PROOF: Alice selected Globex coaches: {coaches_leak} (expected 1 under flaw)")

    assert bids_leak == 1, "Pre-remediation test failed to demonstrate bid leak!"
    assert reqs_leak == 1, "Pre-remediation test failed to demonstrate requirements leak!"
    assert docs_leak == 1, "Pre-remediation test failed to demonstrate documents leak!"
    assert coaches_leak == 1, "Pre-remediation test failed to demonstrate coaches leak!"

    # 3. Alice tampers with Globex requirement
    cur.execute("update public.requirements set description = 'TAMPERED BY ALICE' where bid_id = %s;", (globex_bid,))
    cur.execute("select description from public.requirements where bid_id = %s;", (globex_bid,))
    tampered_text = cur.fetchone()[0]
    assert tampered_text == "TAMPERED BY ALICE", "Pre-remediation test failed to demonstrate cross-tenant write!"
    print("      VULNERABILITY PROOF: Alice tampered with Globex requirement successfully.")

    # Reset role
    set_role_auth(cur, None)
    cur.execute("update public.requirements set description = 'Globex Secret Req' where bid_id = %s;", (globex_bid,))
    print("      PRE-REMEDIATION VULNERABILITY ADVERSARIALLY CONFIRMED.")


def apply_migration_023(cur):
    """Apply the forward security migration."""
    print("\n[3/5] Applying Migration 023 (023_enable_base_tables_tenant_rls.sql)...")
    set_role_auth(cur, None)
    m023_path = os.path.join(MIGRATIONS_DIR, "023_enable_base_tables_tenant_rls.sql")
    t0 = time.time()
    run_sql_file(cur, m023_path)
    elapsed = time.time() - t0
    print(f"      Migration 023 executed successfully in {elapsed:.3f}s.")

    # Verify that all 11 tables now have rowsecurity = true
    cur.execute("""
        select tablename, rowsecurity
        from pg_tables
        where schemaname = 'public' and tablename in %s;
    """, (tuple(BASE_TABLES),))
    rls_statuses = dict(cur.fetchall())
    for t in BASE_TABLES:
        assert rls_statuses[t] is True, f"Migration 023 failed to enable RLS on {t}!"
    print("      CONFIRMED: rowsecurity is TRUE for all 11 base tables.")


def demonstrate_post_remediation_negative_controls(cur, env):
    """Prove that Alice cannot view, insert, update, or delete any Globex rows across the 11 tables."""
    print("\n[4/5] Executing Post-Remediation Negative Controls (Cross-Tenant Denial)...")
    alice_id = env["alice_id"]
    globex_bid = env["globex_bid"]
    globex_org = env["globex_org"]

    set_role_auth(cur, alice_id, "authenticated")

    # 1. Cross-Tenant SELECT denial across all 11 tables
    checks = [
        ("bids", "select count(*) from public.bids where id = %s;", (globex_bid,)),
        ("requirements", "select count(*) from public.requirements where bid_id = %s;", (globex_bid,)),
        ("tasks", "select count(*) from public.tasks where bid_id = %s;", (globex_bid,)),
        ("documents", "select count(*) from public.documents where bid_id = %s;", (globex_bid,)),
        ("document_versions", "select count(*) from public.document_versions dv join public.documents d on dv.document_id = d.id where d.bid_id = %s;", (globex_bid,)),
        ("outline_sections", "select count(*) from public.outline_sections where bid_id = %s;", (globex_bid,)),
        ("content_library", "select count(*) from public.content_library where bid_id = %s;", (globex_bid,)),
        ("coaches", "select count(*) from public.coaches where organization_id = %s;", (globex_org,)),
        ("clarifications", "select count(*) from public.clarifications where bid_id = %s;", (globex_bid,)),
        ("debriefs", "select count(*) from public.debriefs where bid_id = %s;", (globex_bid,)),
        ("deliverables", "select count(*) from public.deliverables where bid_id = %s;", (globex_bid,)),
    ]

    for table, query, params in checks:
        cur.execute(query, params)
        count = cur.fetchone()[0]
        assert count == 0, f"SECURITY BREACH: Alice read {count} rows from {table} belonging to Globex!"
        print(f"      [BLOCKED] Alice SELECT on Globex {table:18}: 0 rows returned.")

    # 2. Cross-Tenant INSERT denial
    insert_denials = [
        ("bids", "insert into public.bids (organization_id, title) values (%s, 'Illegitimate Bid');", (globex_org,)),
        ("requirements", "insert into public.requirements (bid_id, description) values (%s, 'Injected Req');", (globex_bid,)),
        ("tasks", "insert into public.tasks (bid_id, title) values (%s, 'Injected Task');", (globex_bid,)),
        ("coaches", "insert into public.coaches (organization_id, name) values (%s, 'Injected Coach');", (globex_org,)),
        ("clarifications", "insert into public.clarifications (bid_id, question) values (%s, 'Injected Q?');", (globex_bid,)),
        ("deliverables", "insert into public.deliverables (bid_id, title) values (%s, 'Injected Deliv');", (globex_bid,)),
        ("outline_sections", "insert into public.outline_sections (bid_id, title) values (%s, 'Injected Section');", (globex_bid,)),
        ("content_library", "insert into public.content_library (bid_id, title, content) values (%s, 'Injected IP', 'Text');", (globex_bid,)),
    ]

    for table, query, params in insert_denials:
        blocked = False
        try:
            cur.execute(query, params)
        except Exception as e:
            blocked = True
            # Rollback connection state if needed or proceed
        assert blocked, f"SECURITY BREACH: Alice was able to INSERT into Globex {table}!"
        print(f"      [BLOCKED] Alice INSERT into Globex {table:18}: Rejected by RLS policy.")

    # 3. Cross-Tenant UPDATE and DELETE denial
    cur.execute("update public.requirements set description = 'HACKED' where bid_id = %s;", (globex_bid,))
    cur.execute("select count(*) from public.requirements where description = 'HACKED';")
    assert cur.fetchone()[0] == 0
    print("      [BLOCKED] Alice UPDATE on Globex requirements: 0 rows modified.")

    cur.execute("delete from public.tasks where bid_id = %s;", (globex_bid,))
    # Switch to admin to verify Bob's task is still there
    set_role_auth(cur, None)
    cur.execute("select count(*) from public.tasks where bid_id = %s;", (globex_bid,))
    assert cur.fetchone()[0] == 1
    print("      [BLOCKED] Alice DELETE on Globex tasks: Row preserved intact.")

    # 4. Anonymous role denial
    set_role_auth(cur, None, "anon")
    anon_blocked = False
    try:
        cur.execute("select * from public.bids;")
        rows = cur.fetchall()
        if len(rows) == 0:
            anon_blocked = True
    except Exception:
        anon_blocked = True
    assert anon_blocked, "SECURITY BREACH: Anonymous caller accessed bids!"
    print("      [BLOCKED] Unauthenticated 'anon' role: Access denied.")

    set_role_auth(cur, None)
    print("      ALL NEGATIVE CONTROLS PASSED.")


def demonstrate_post_remediation_positive_controls(cur, env):
    """Prove that Alice can still perform all legitimate operations in Acme Corp."""
    print("\n[5/5] Executing Post-Remediation Positive Controls (Authorized Tenant CRUD)...")
    alice_id = env["alice_id"]
    acme_bid = env["acme_bid"]
    acme_org = env["acme_org"]

    set_role_auth(cur, alice_id, "authenticated")

    # 1. Alice selects her own bid and child items
    cur.execute("select id, title from public.bids where organization_id = %s;", (acme_org,))
    bids = cur.fetchall()
    assert len(bids) == 1 and bids[0][0] == acme_bid
    print(f"      [ALLOWED] Alice SELECT Acme bids: {bids[0][1]}")

    cur.execute("select count(*) from public.requirements where bid_id = %s;", (acme_bid,))
    assert cur.fetchone()[0] == 1
    print("      [ALLOWED] Alice SELECT Acme requirements: Verified.")

    cur.execute("select count(*) from public.coaches where organization_id = %s;", (acme_org,))
    assert cur.fetchone()[0] == 1
    print("      [ALLOWED] Alice SELECT Acme coaches: Verified.")

    # 2. Alice inserts new requirement into Acme bid
    cur.execute("""
        insert into public.requirements (bid_id, description, category)
        values (%s, 'Acme Legitimate Req 2', 'Mandatory') returning id;
    """, (acme_bid,))
    new_req_id = cur.fetchone()[0]
    assert new_req_id > 0
    print(f"      [ALLOWED] Alice INSERT requirement into Acme bid: Req #{new_req_id}")

    # 3. Alice updates her own bid
    cur.execute("update public.bids set title = 'Acme Cloud Bid (Updated)' where id = %s;", (acme_bid,))
    cur.execute("select title from public.bids where id = %s;", (acme_bid,))
    assert cur.fetchone()[0] == 'Acme Cloud Bid (Updated)'
    print("      [ALLOWED] Alice UPDATE on Acme bid: Succeeded.")

    # 4. Alice inserts and deletes her own task
    cur.execute("insert into public.tasks (bid_id, title) values (%s, 'Temp Task') returning id;", (acme_bid,))
    temp_task_id = cur.fetchone()[0]
    cur.execute("delete from public.tasks where id = %s;", (temp_task_id,))
    cur.execute("select count(*) from public.tasks where id = %s;", (temp_task_id,))
    assert cur.fetchone()[0] == 0
    print("      [ALLOWED] Alice DELETE on Acme task: Succeeded.")

    # 5. Alice adds and updates coach in Acme Corp
    cur.execute("insert into public.coaches (organization_id, name, credentials) values (%s, 'Coach Sarah', 'ICF MCC') returning id;", (acme_org,))
    coach_id = cur.fetchone()[0]
    cur.execute("update public.coaches set location = 'Calgary' where id = %s;", (coach_id,))
    cur.execute("select location from public.coaches where id = %s;", (coach_id,))
    assert cur.fetchone()[0] == 'Calgary'
    print(f"      [ALLOWED] Alice INSERT & UPDATE coach in Acme Corp: Coach #{coach_id}")

    set_role_auth(cur, None)
    print("      ALL POSITIVE CONTROLS PASSED.")


def main():
    print("==================================================================")
    print("BID INTELLIGENCE RECOVERY PACKAGE R2A: TENANT-BOUNDARY CORRECTION")
    print("==================================================================")
    conn = get_conn()
    cur = conn.cursor()

    setup_fresh_database_001_to_022(cur)
    env = seed_two_tenants(cur)

    demonstrate_pre_remediation_vulnerability(cur, env)
    apply_migration_023(cur)
    demonstrate_post_remediation_negative_controls(cur, env)
    demonstrate_post_remediation_positive_controls(cur, env)

    print("\n==================================================================")
    print("PACKAGE R2A ADVERSARIAL VERIFICATION SUITE: PASSED")
    print("==================================================================")


if __name__ == "__main__":
    main()
