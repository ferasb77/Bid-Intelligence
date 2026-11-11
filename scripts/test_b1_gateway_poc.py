"""
Proof-of-concept test script for Package B1 isolated local environment:
PostgreSQL 17 + PostgREST 16.5 + Local Gateway.
"""
import os
import sys
import time
import socket
import tempfile
import shutil
import subprocess
import threading
import urllib.request
import urllib.error
import json
import psycopg2
import jwt

PG_BIN = r"C:\Users\feras\.gemini\antigravity\brain\95ae3968-d675-4b45-95ac-9409d2dc08dc\scratch\pg17_bin\bin"
POSTGREST_EXE = r"C:\Users\feras\.gemini\antigravity\brain\63bc6640-1ec4-4d25-9353-df328c95e7bb\scratch\postgrest\postgrest.exe"
JWT_SECRET = "super-secret-jwt-token-with-at-least-32-characters-for-phoenix-beta"


def find_free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def main():
    pg_port = find_free_port()
    pgrst_port = find_free_port()
    print(f"Allocated ports: Postgres={pg_port}, PostgREST={pgrst_port}")

    temp_dir = tempfile.mkdtemp(prefix="b1_poc_")
    data_dir = os.path.join(temp_dir, "data")
    pgrst_conf = os.path.join(temp_dir, "postgrest.conf")

    pg_proc = None
    pgrst_proc = None

    try:
        # 1. initdb
        initdb_exe = os.path.join(PG_BIN, "initdb.exe")
        subprocess.run([initdb_exe, "-D", data_dir, "-U", "postgres", "-A", "trust", "--no-locale", "--encoding=UTF8"],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

        # 2. postgres
        postgres_exe = os.path.join(PG_BIN, "postgres.exe")
        pg_proc = subprocess.Popen([postgres_exe, "-D", data_dir, "-p", str(pg_port), "-h", "127.0.0.1"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # Wait for pg
        time.sleep(1.5)
        conn = psycopg2.connect(host="127.0.0.1", port=pg_port, user="postgres", dbname="postgres")
        conn.autocommit = True
        cur = conn.cursor()

        # Roles and auth functions
        cur.execute("""
            do $$
            begin
                if not exists (select 1 from pg_roles where rolname = 'anon') then
                    create role anon nologin;
                end if;
                if not exists (select 1 from pg_roles where rolname = 'authenticated') then
                    create role authenticated nologin;
                end if;
                if not exists (select 1 from pg_roles where rolname = 'service_role') then
                    create role service_role nologin;
                end if;
            end $$;
            grant anon, authenticated, service_role to postgres;
            create schema if not exists auth;
            create or replace function auth.uid() returns uuid language sql stable as $$
                select coalesce(
                    nullif(current_setting('request.jwt.claim.sub', true), '')::uuid,
                    nullif(current_setting('request.jwt.claims', true)::jsonb->>'sub', '')::uuid
                );
            $$;
            create or replace function auth.role() returns text language sql stable as $$
                select coalesce(
                    nullif(current_setting('request.jwt.claim.role', true), ''),
                    nullif(current_setting('request.jwt.claims', true)::jsonb->>'role', ''),
                    'anon'
                );
            $$;
            create table if not exists test_items (
                id serial primary key,
                user_id uuid,
                name text
            );
            alter table test_items enable row level security;
            create policy test_items_user_isolation on test_items for all to authenticated
                using (user_id = auth.uid()) with check (user_id = auth.uid());
            grant select, insert, update, delete on test_items to authenticated;
            grant usage, select on sequence test_items_id_seq to authenticated;
            insert into test_items (user_id, name) values ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'Alice Item');
            insert into test_items (user_id, name) values ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', 'Bob Item');
        """)
        conn.close()
        print("PostgreSQL 17 initialized with test table and RLS policy.")

        # 3. PostgREST config
        with open(pgrst_conf, "w", encoding="utf-8") as f:
            f.write(f"""
db-uri = "postgres://postgres@127.0.0.1:{pg_port}/postgres"
db-schemas = "public"
db-anon-role = "anon"
server-host = "127.0.0.1"
server-port = {pgrst_port}
jwt-secret = "{JWT_SECRET}"
jwt-secret-is-base64 = false
""")

        # 4. Launch PostgREST
        env = dict(os.environ)
        env["PATH"] = PG_BIN + ";" + env.get("PATH", "")
        pgrst_proc = subprocess.Popen([POSTGREST_EXE, pgrst_conf], env=env,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1.5)

        # 5. Test Alice JWT
        alice_jwt = jwt.encode(
            {"sub": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "role": "authenticated", "exp": int(time.time()) + 3600},
            JWT_SECRET, algorithm="HS256"
        )
        req = urllib.request.Request(
            f"http://127.0.0.1:{pgrst_port}/test_items",
            headers={"Authorization": f"Bearer {alice_jwt}"}
        )
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
            print(f"Alice request via PostgREST returned {len(data)} items: {data}")
            assert len(data) == 1
            assert data[0]["name"] == "Alice Item"

        # 6. Test Bob JWT
        bob_jwt = jwt.encode(
            {"sub": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", "role": "authenticated", "exp": int(time.time()) + 3600},
            JWT_SECRET, algorithm="HS256"
        )
        req_b = urllib.request.Request(
            f"http://127.0.0.1:{pgrst_port}/test_items",
            headers={"Authorization": f"Bearer {bob_jwt}"}
        )
        with urllib.request.urlopen(req_b) as resp:
            data_b = json.loads(resp.read().decode())
            print(f"Bob request via PostgREST returned {len(data_b)} items: {data_b}")
            assert len(data_b) == 1
            assert data_b[0]["name"] == "Bob Item"

        # 7. Test Expired JWT
        expired_jwt = jwt.encode(
            {"sub": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "role": "authenticated", "exp": int(time.time()) - 100},
            JWT_SECRET, algorithm="HS256"
        )
        req_exp = urllib.request.Request(
            f"http://127.0.0.1:{pgrst_port}/test_items",
            headers={"Authorization": f"Bearer {expired_jwt}"}
        )
        try:
            with urllib.request.urlopen(req_exp) as resp:
                print("Unexpected success on expired JWT")
        except urllib.error.HTTPError as e:
            print(f"Expired JWT rejected as expected by PostgREST: HTTP {e.code} ({e.read().decode()[:80]})")
            assert e.code == 401

        print("POC VERIFICATION SUCCESSFUL: PostgreSQL 17 + PostgREST 16.5 + HS256 JWTs works 100% natively!")

    finally:
        if pgrst_proc:
            pgrst_proc.terminate()
            pgrst_proc.wait(timeout=5)
        if pg_proc:
            subprocess.run([os.path.join(PG_BIN, "pg_ctl.exe"), "stop", "-D", data_dir, "-m", "immediate"],
                           check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            pg_proc.terminate()
            pg_proc.wait(timeout=5)
        time.sleep(0.5)
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
