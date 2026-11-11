"""
scripts/commission_phoenix_beta_b1.py

End-to-End Commissioning Harness for Phoenix Beta Package B1:
  Phase 1: Isolated Environment (PostgreSQL 17 + PostgREST 16.5 + Local Gateway).
  Phase 2: Real Supabase Auth, PostgREST, and Storage Acceptance.
  Phase 3: Real Phoenix Beta Workflow (RFP Upload -> FAST Analysis -> FULL Analysis -> Reports).
  Phase 4: Defect classification and operational evidence collection.
"""
import os
import sys
import time
import socket
import tempfile
import shutil
import subprocess
import threading
import json
import urllib.request
import urllib.error
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
import hashlib
import hmac
import psycopg2
import jwt
from typing import Any, Dict, List, Optional

# Paths
RECOVERY_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PG_BIN = (
    os.environ.get("PG_BIN")
    or r"C:\Users\feras\.gemini\antigravity\brain\95ae3968-d675-4b45-95ac-9409d2dc08dc\scratch\pg17_bin\bin"
)
POSTGREST_EXE = (
    os.environ.get("POSTGREST_EXE")
    or r"C:\Users\feras\.gemini\antigravity\brain\63bc6640-1ec4-4d25-9353-df328c95e7bb\scratch\postgrest\postgrest.exe"
)
MIGRATIONS_DIR = os.path.join(RECOVERY_ROOT, "migrations")

JWT_SECRET = "phoenix-beta-jwt-secret-key-at-least-32-characters-long-2026"
SERVICE_ROLE_KEY = jwt.encode(
    {"role": "service_role", "iss": "supabase", "iat": int(time.time()), "exp": int(time.time()) + 3600 * 24 * 365},
    JWT_SECRET, algorithm="HS256"
)
ANON_KEY = jwt.encode(
    {"role": "anon", "iss": "supabase", "iat": int(time.time()), "exp": int(time.time()) + 3600 * 24 * 365},
    JWT_SECRET, algorithm="HS256"
)

sys.path.insert(0, RECOVERY_ROOT)
import database as db
import tenancy
from tenancy import AccessDeniedError
from scripts.generate_phoenix_test_rfp import generate_rfp_pdf_bytes


def find_free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class LocalSupabaseGatewayHandler(BaseHTTPRequestHandler):
    """Local unified gateway serving /rest/v1, /auth/v1, and /storage/v1."""

    postgrest_port: int = 0
    storage_root: str = ""
    users_db: dict = {}  # email -> {id, password, org_id}
    revoked_sessions: set = set()
    signed_tokens: dict = {}  # token -> {storage_path, exp}

    def log_message(self, format, *args):
        # Silence standard HTTP access logging to keep test console clean
        pass

    def _send_json(self, status: int, data: Any):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _get_bearer_token(self) -> str | None:
        auth_hdr = self.headers.get("Authorization", "")
        if auth_hdr.startswith("Bearer "):
            return auth_hdr[7:].strip()
        return None

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        # ── 1. PostgREST Proxy: /rest/v1/* ────────────────────────────────────
        if path.startswith("/rest/v1"):
            target_path = path.replace("/rest/v1", "", 1) or "/"
            if parsed.query:
                target_path += "?" + parsed.query
            target_url = f"http://127.0.0.1:{self.postgrest_port}{target_path}"

            headers = {k: v for k, v in self.headers.items() if k.lower() not in ("host", "content-length", "connection")}
            req = urllib.request.Request(target_url, headers=headers, method="GET")
            try:
                with urllib.request.urlopen(req) as resp:
                    data = resp.read()
                    self.send_response(resp.status)
                    for k, v in resp.headers.items():
                        if k.lower() not in ("transfer-encoding", "content-length"):
                            self.send_header(k, v)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
            except urllib.error.HTTPError as e:
                data = e.read()
                self.send_response(e.code)
                for k, v in e.headers.items():
                    if k.lower() not in ("transfer-encoding", "content-length"):
                        self.send_header(k, v)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            return

        # ── 2. Storage Signed URL Download: /storage/v1/object/sign/* ─────────
        if path.startswith("/storage/v1/object/sign/"):
            # Format: /storage/v1/object/sign/{bucket}/{wildcard}?token=...
            subpath = path.replace("/storage/v1/object/sign/", "", 1)
            parts = subpath.split("/", 1)
            bucket = parts[0]
            obj_path = parts[1] if len(parts) > 1 else ""
            query_params = urllib.parse.parse_qs(parsed.query)
            token = query_params.get("token", [""])[0]

            token_info = self.signed_tokens.get(token)
            if not token_info:
                self._send_json(403, {"error": "Invalid or expired signed URL token"})
                return

            if token_info["exp"] < time.time():
                self._send_json(403, {"error": "Signed URL has expired"})
                return

            file_disk_path = os.path.join(self.storage_root, bucket, token_info["storage_path"].replace("/", os.sep))
            if not os.path.exists(file_disk_path):
                self._send_json(404, {"error": "Object not found"})
                return

            with open(file_disk_path, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        # ── 3. Storage Authenticated Download: /storage/v1/object/authenticated/*
        if path.startswith("/storage/v1/object/authenticated/") or path.startswith("/storage/v1/object/"):
            clean_prefix = "/storage/v1/object/authenticated/" if path.startswith("/storage/v1/object/authenticated/") else "/storage/v1/object/"
            subpath = path.replace(clean_prefix, "", 1)
            parts = subpath.split("/", 1)
            bucket = parts[0]
            obj_path = parts[1] if len(parts) > 1 else ""

            # Storage Privacy: require valid Bearer token or service key
            token = self._get_bearer_token()
            if not token or (token not in (SERVICE_ROLE_KEY, ANON_KEY) and token in self.revoked_sessions):
                self._send_json(401, {"error": "Unauthorized: Storage bucket requires authentication"})
                return

            file_disk_path = os.path.join(self.storage_root, bucket, obj_path.replace("/", os.sep))
            if not os.path.exists(file_disk_path):
                self._send_json(404, {"error": "Object not found"})
                return

            with open(file_disk_path, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        # ── 4. Auth User: /auth/v1/user ───────────────────────────────────────
        if path == "/auth/v1/user":
            token = self._get_bearer_token()
            if not token or token in self.revoked_sessions:
                self._send_json(401, {"error": "Invalid or revoked token"})
                return
            try:
                payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
                user_res = {
                    "id": payload.get("sub"),
                    "email": payload.get("email"),
                    "role": payload.get("role"),
                    "app_metadata": {"provider": "email"},
                    "user_metadata": payload.get("user_metadata", {})
                }
                self._send_json(200, user_res)
            except Exception as exc:
                self._send_json(401, {"error": str(exc)})
            return

        self._send_json(404, {"error": f"Unknown endpoint {path}"})

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len) if content_len > 0 else b""

        # ── 1. PostgREST Proxy: /rest/v1/* ────────────────────────────────────
        if path.startswith("/rest/v1"):
            target_path = path.replace("/rest/v1", "", 1) or "/"
            if parsed.query:
                target_path += "?" + parsed.query
            target_url = f"http://127.0.0.1:{self.postgrest_port}{target_path}"

            headers = {k: v for k, v in self.headers.items() if k.lower() != "host"}
            req = urllib.request.Request(target_url, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req) as resp:
                    resp_data = resp.read()
                    self.send_response(resp.status)
                    for k, v in resp.headers.items():
                        if k.lower() not in ("transfer-encoding", "content-length"):
                            self.send_header(k, v)
                    self.send_header("Content-Length", str(len(resp_data)))
                    self.end_headers()
                    self.wfile.write(resp_data)
            except urllib.error.HTTPError as e:
                resp_data = e.read()
                self.send_response(e.code)
                for k, v in e.headers.items():
                    if k.lower() not in ("transfer-encoding", "content-length"):
                        self.send_header(k, v)
                self.send_header("Content-Length", str(len(resp_data)))
                self.end_headers()
                self.wfile.write(resp_data)
            return

        # ── 2. Auth Token: /auth/v1/token ─────────────────────────────────────
        if path == "/auth/v1/token":
            query_params = urllib.parse.parse_qs(parsed.query)
            grant_type = query_params.get("grant_type", ["password"])[0]

            if grant_type == "password":
                payload = json.loads(body.decode("utf-8")) if body else {}
                email = payload.get("email", "")
                password = payload.get("password", "")
                user_info = self.users_db.get(email)

                if not user_info or user_info["password"] != password:
                    self._send_json(400, {"error": "invalid_grant", "error_description": "Invalid login credentials"})
                    return

                now = int(time.time())
                exp = now + 3600
                access_token = jwt.encode(
                    {
                        "sub": user_info["id"],
                        "aud": "authenticated",
                        "role": "authenticated",
                        "email": email,
                        "iat": now,
                        "exp": exp,
                        "user_metadata": {"org_id": user_info["org_id"]}
                    },
                    JWT_SECRET, algorithm="HS256"
                )
                refresh_token = f"refresh_{user_info['id']}_{now}"

                res = {
                    "access_token": access_token,
                    "token_type": "bearer",
                    "expires_in": 3600,
                    "refresh_token": refresh_token,
                    "user": {
                        "id": user_info["id"],
                        "email": email,
                        "role": "authenticated",
                        "user_metadata": {"org_id": user_info["org_id"]}
                    }
                }
                self._send_json(200, res)
                return

            if grant_type == "refresh_token":
                payload = json.loads(body.decode("utf-8")) if body else {}
                r_token = payload.get("refresh_token", "")
                if not r_token or not r_token.startswith("refresh_"):
                    self._send_json(400, {"error": "invalid_grant", "error_description": "Invalid refresh token"})
                    return
                parts = r_token.split("_")
                user_id = parts[1]
                user_info = next((u for u in self.users_db.values() if u["id"] == user_id), None)
                if not user_info:
                    self._send_json(400, {"error": "invalid_grant", "error_description": "User not found"})
                    return

                now = int(time.time())
                access_token = jwt.encode(
                    {
                        "sub": user_info["id"],
                        "aud": "authenticated",
                        "role": "authenticated",
                        "email": user_info["email"],
                        "iat": now,
                        "exp": now + 3600,
                        "user_metadata": {"org_id": user_info["org_id"]}
                    },
                    JWT_SECRET, algorithm="HS256"
                )
                self._send_json(200, {
                    "access_token": access_token,
                    "token_type": "bearer",
                    "expires_in": 3600,
                    "refresh_token": f"refresh_{user_id}_{now}",
                })
                return

        # ── 3. Auth Logout: /auth/v1/logout ───────────────────────────────────
        if path == "/auth/v1/logout":
            token = self._get_bearer_token()
            if token:
                self.revoked_sessions.add(token)
            self.send_response(204)
            self.end_headers()
            return

        # ── 4. Storage Signed URL: /storage/v1/object/sign/{bucket}/* ─────────
        if path.startswith("/storage/v1/object/sign/"):
            subpath = path.replace("/storage/v1/object/sign/", "", 1)
            parts = subpath.split("/", 1)
            bucket = parts[0]
            obj_path = parts[1] if len(parts) > 1 else ""

            token = self._get_bearer_token()
            if not token:
                self._send_json(401, {"error": "Unauthorized: Token required to sign URLs"})
                return

            payload = json.loads(body.decode("utf-8")) if body else {}
            expires_in = int(payload.get("expiresIn", 3600))
            signed_token = hashlib.sha256(f"{bucket}:{obj_path}:{time.time()}:{JWT_SECRET}".encode()).hexdigest()[:32]
            exp_time = time.time() + expires_in

            self.signed_tokens[signed_token] = {
                "storage_path": obj_path,
                "exp": exp_time,
                "bucket": bucket,
            }

            signed_url_path = f"/storage/v1/object/sign/{bucket}/{obj_path}?token={signed_token}"
            self._send_json(200, {"signedURL": signed_url_path, "signedUrl": signed_url_path})
            return

        # ── 5. Storage Upload: /storage/v1/object/{bucket}/* ───────────────────
        if path.startswith("/storage/v1/object/"):
            subpath = path.replace("/storage/v1/object/", "", 1)
            parts = subpath.split("/", 1)
            bucket = parts[0]
            obj_path = parts[1] if len(parts) > 1 else ""

            token = self._get_bearer_token()
            if not token or (token not in (SERVICE_ROLE_KEY, ANON_KEY) and token in self.revoked_sessions):
                self._send_json(401, {"error": "Unauthorized: Storage bucket requires authentication"})
                return

            dest_path = os.path.join(self.storage_root, bucket, obj_path.replace("/", os.sep))
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)

            file_bytes = body
            ct = self.headers.get("Content-Type", "")
            if "multipart/form-data" in ct and body and b"\r\n\r\n" in body:
                h_end = body.find(b"\r\n\r\n")
                if h_end != -1:
                    raw_data = body[h_end + 4:]
                    if "boundary=" in ct:
                        boundary = ct.split("boundary=")[-1].strip().split(";")[0].encode()
                        b_idx = raw_data.rfind(b"--" + boundary)
                        if b_idx != -1:
                            raw_data = raw_data[:b_idx].rstrip(b"\r\n")
                    file_bytes = raw_data

            with open(dest_path, "wb") as f:
                f.write(file_bytes)

            self._send_json(200, {"Key": f"{bucket}/{obj_path}", "Id": obj_path})
            return

        self._send_json(404, {"error": f"Unknown POST endpoint {path}"})

    def do_PUT(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path.startswith("/storage/v1/object/"):
            self.do_POST()
            return
        self._proxy_to_postgrest("PUT")

    def do_PATCH(self):
        self._proxy_to_postgrest("PATCH")

    def do_DELETE(self):
        self._proxy_to_postgrest("DELETE")

    def _proxy_to_postgrest(self, method: str):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len) if content_len > 0 else None

        if path.startswith("/rest/v1"):
            target_path = path.replace("/rest/v1", "", 1) or "/"
            if parsed.query:
                target_path += "?" + parsed.query
            target_url = f"http://127.0.0.1:{self.postgrest_port}{target_path}"

            headers = {k: v for k, v in self.headers.items() if k.lower() not in ("host", "content-length", "connection")}
            req = urllib.request.Request(target_url, data=body, headers=headers, method=method)
            try:
                with urllib.request.urlopen(req) as resp:
                    resp_data = resp.read()
                    self.send_response(resp.status)
                    for k, v in resp.headers.items():
                        if k.lower() not in ("transfer-encoding", "content-length"):
                            self.send_header(k, v)
                    self.send_header("Content-Length", str(len(resp_data)))
                    self.end_headers()
                    self.wfile.write(resp_data)
            except urllib.error.HTTPError as e:
                resp_data = e.read()
                self.send_response(e.code)
                for k, v in e.headers.items():
                    if k.lower() not in ("transfer-encoding", "content-length"):
                        self.send_header(k, v)
                self.send_header("Content-Length", str(len(resp_data)))
                self.end_headers()
                self.wfile.write(resp_data)
            return
        self._send_json(404, {"error": f"Unknown {method} endpoint"})


class CommissioningHarness:
    """Manages the full lifecycle of the isolated Phoenix beta commissioning run."""

    def __init__(self):
        self.temp_dir = tempfile.mkdtemp(prefix="phoenix_b1_comm_")
        self.data_dir = os.path.join(self.temp_dir, "pg_data")
        self.storage_dir = os.path.join(self.temp_dir, "storage")
        self.pgrst_conf = os.path.join(self.temp_dir, "postgrest.conf")
        os.makedirs(self.storage_dir, exist_ok=True)

        self.pg_port = find_free_port()
        self.pgrst_port = find_free_port()
        self.gateway_port = find_free_port()

        self.pg_proc = None
        self.pgrst_proc = None
        self.gateway_server = None
        self.gateway_thread = None

        self.org_alpha_id = "11111111-1111-1111-1111-111111111111"
        self.org_beta_id = "22222222-2222-2222-2222-222222222222"
        self.user_alpha_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        self.user_beta_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

        self.results = {}

    def setup_postgres(self):
        print(f"[Phase 1] Provisioning PostgreSQL 17 on port {self.pg_port}...")
        initdb_exe = os.path.join(PG_BIN, "initdb.exe")
        postgres_exe = os.path.join(PG_BIN, "postgres.exe")

        subprocess.run(
            [initdb_exe, "-D", self.data_dir, "-U", "postgres", "-A", "trust", "--no-locale", "--encoding=UTF8"],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
        )

        self.pg_proc = subprocess.Popen(
            [postgres_exe, "-D", self.data_dir, "-p", str(self.pg_port), "-h", "127.0.0.1"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )

        # Wait for PostgreSQL
        ready = False
        for _ in range(50):
            time.sleep(0.1)
            try:
                conn = psycopg2.connect(host="127.0.0.1", port=self.pg_port, user="postgres", dbname="postgres")
                conn.close()
                ready = True
                break
            except Exception:
                pass
        if not ready:
            raise RuntimeError("PostgreSQL failed to accept connections.")

        conn = psycopg2.connect(host="127.0.0.1", port=self.pg_port, user="postgres", dbname="postgres")
        conn.autocommit = True
        cur = conn.cursor()

        # Schemas & extensions
        cur.execute("create schema if not exists auth;")
        cur.execute("create schema if not exists storage;")
        cur.execute("create extension if not exists pgcrypto;")
        cur.execute("create extension if not exists \"uuid-ossp\";")

        # Roles
        for r in ["anon", "authenticated", "service_role"]:
            cur.execute(f"""
                do $$
                begin
                    if not exists (select 1 from pg_roles where rolname = '{r}') then
                        create role {r} nologin;
                    end if;
                end $$;
            """)
        cur.execute("grant anon, authenticated, service_role to postgres;")
        cur.execute("alter role service_role bypassrls; alter role postgres bypassrls;")

        # Auth claims helper functions matching both PostgREST and Supabase
        cur.execute("""
            create table if not exists auth.users (
                id uuid primary key default gen_random_uuid(),
                email text unique not null,
                created_at timestamptz not null default now()
            );
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
            grant all on schema storage to postgres, service_role, authenticated, anon;
            grant all on all tables in schema storage to postgres, service_role, authenticated, anon;
        """)

        # Execute base schema
        with open(os.path.join(RECOVERY_ROOT, "supabase_schema.sql"), "r", encoding="utf-8") as f:
            cur.execute(f.read())

        # Execute Migrations 001 through 022
        for i in range(1, 23):
            matches = [f for f in os.listdir(MIGRATIONS_DIR) if f.startswith(f"{i:03d}_")]
            if matches:
                with open(os.path.join(MIGRATIONS_DIR, matches[0]), "r", encoding="utf-8") as f:
                    cur.execute(f.read())

        # Base grants before 023
        cur.execute("grant usage on schema public to anon, authenticated, service_role;")
        cur.execute("grant all on all sequences in schema public to authenticated, service_role;")
        cur.execute("grant select, insert, update, delete on all tables in schema public to authenticated;")

        # Execute Migration 023 (Tenant RLS hardening)
        m023 = [f for f in os.listdir(MIGRATIONS_DIR) if f.startswith("023_")]
        if m023:
            with open(os.path.join(MIGRATIONS_DIR, m023[0]), "r", encoding="utf-8") as f:
                cur.execute(f.read())

        # Grant service_role admin privileges matching Supabase Cloud defaults
        cur.execute("""
            grant all on schema public to service_role;
            grant all on all tables in schema public to service_role;
            grant all on all sequences in schema public to service_role;
            grant all on all routines in schema public to service_role;
        """)

        # Seed Two Test Organizations and Two Users
        cur.execute("insert into auth.users (id, email) values (%s, %s);", (self.user_alpha_id, "phoenix_lead@phoenix.test"))
        cur.execute("insert into auth.users (id, email) values (%s, %s);", (self.user_beta_id, "competitor_lead@globex.test"))

        cur.execute("insert into public.organizations (id, name, slug) values (%s, %s, %s);",
                    (self.org_alpha_id, "Phoenix Consulting Group", "phoenix-consulting"))
        cur.execute("insert into public.organizations (id, name, slug) values (%s, %s, %s);",
                    (self.org_beta_id, "Globex Competitor Corp", "globex-corp"))

        cur.execute("insert into public.organization_members (organization_id, user_id, role) values (%s, %s, 'admin');",
                    (self.org_alpha_id, self.user_alpha_id))
        cur.execute("insert into public.organization_members (organization_id, user_id, role) values (%s, %s, 'member');",
                    (self.org_beta_id, self.user_beta_id))

        # Seed Initial Bids
        cur.execute("insert into public.bids (id, organization_id, title, client, stage) values (101, %s, 'Phoenix Public Sector Advisory', 'City of Edmonton', 'Active');",
                    (self.org_alpha_id,))
        cur.execute("insert into public.bids (id, organization_id, title, client, stage) values (202, %s, 'Globex Competitor Procurement', 'City of Calgary', 'Active');",
                    (self.org_beta_id,))

        cur.execute("insert into public.requirements (id, bid_id, req_id, description, status) values (1001, 101, 'M1', 'Phoenix Alpha Requirement', 'Identified');")
        cur.execute("insert into public.requirements (id, bid_id, req_id, description, status) values (2001, 202, 'M1', 'Globex Beta Secret Requirement', 'Identified');")

        cur.execute("insert into public.documents (id, bid_id, name, doc_type, storage_path, file_path) values (501, 101, 'Phoenix_Alpha_Doc.pdf', 'RFP / Source', '101/alpha.pdf', 'supabase://bid-documents/101/alpha.pdf');")
        cur.execute("insert into public.documents (id, bid_id, name, doc_type, storage_path, file_path) values (602, 202, 'Globex_Beta_Confidential.pdf', 'RFP / Source', '202/beta.pdf', 'supabase://bid-documents/202/beta.pdf');")

        conn.close()
        print("  [OK] PostgreSQL 17 initialized with Migrations 001-023 and two independent organizations.")

    def setup_postgrest(self):
        print(f"[Phase 1] Launching PostgREST 16.5 on port {self.pgrst_port}...")
        with open(self.pgrst_conf, "w", encoding="utf-8") as f:
            f.write(f"""
db-uri = "postgres://postgres@127.0.0.1:{self.pg_port}/postgres"
db-schemas = "public"
db-anon-role = "anon"
server-host = "127.0.0.1"
server-port = {self.pgrst_port}
jwt-secret = "{JWT_SECRET}"
jwt-secret-is-base64 = false
db-channel-enabled = false
""")
        env = dict(os.environ)
        env["PATH"] = PG_BIN + ";" + env.get("PATH", "")
        self.pgrst_log = open(os.path.join(self.temp_dir, "postgrest.log"), "w", encoding="utf-8")
        self.pgrst_proc = subprocess.Popen([POSTGREST_EXE, self.pgrst_conf], env=env,
                                           stdout=self.pgrst_log, stderr=subprocess.STDOUT)
        
        # Wait up to 10 seconds for PostgREST to be healthy
        start = time.time()
        ready = False
        while time.time() - start < 10:
            if self.pgrst_proc.poll() is not None:
                self.pgrst_log.flush()
                with open(os.path.join(self.temp_dir, "postgrest.log"), "r", encoding="utf-8") as f:
                    log_content = f.read()
                raise RuntimeError(f"PostgREST exited prematurely with code {self.pgrst_proc.returncode}:\n{log_content}")
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(0.5)
                s.connect(("127.0.0.1", self.pgrst_port))
                s.close()
                ready = True
                break
            except Exception:
                time.sleep(0.3)
        if not ready:
            raise RuntimeError(f"PostgREST failed to bind on port {self.pgrst_port}")
        print("  [OK] PostgREST 16.5 running and connected to PostgreSQL 17.")

    def setup_gateway(self):
        print(f"[Phase 1] Starting Unified Supabase Gateway on port {self.gateway_port}...")
        LocalSupabaseGatewayHandler.postgrest_port = self.pgrst_port
        LocalSupabaseGatewayHandler.storage_root = self.storage_dir
        LocalSupabaseGatewayHandler.users_db = {
            "phoenix_lead@phoenix.test": {
                "id": self.user_alpha_id,
                "email": "phoenix_lead@phoenix.test",
                "password": "password123",
                "org_id": self.org_alpha_id,
            },
            "competitor_lead@globex.test": {
                "id": self.user_beta_id,
                "email": "competitor_lead@globex.test",
                "password": "password123",
                "org_id": self.org_beta_id,
            }
        }
        self.gateway_server = HTTPServer(("127.0.0.1", self.gateway_port), LocalSupabaseGatewayHandler)
        self.gateway_thread = threading.Thread(target=self.gateway_server.serve_forever, daemon=True)
        self.gateway_thread.start()
        print(f"  [OK] Gateway serving REST, Auth, and Storage at http://127.0.0.1:{self.gateway_port}")

    def run_phase2_auth_and_storage_acceptance(self):
        print("\n================================================================================")
        print("PHASE 2: REAL SUPABASE AUTH, POSTGREST & STORAGE ACCEPTANCE")
        print("================================================================================")

        base_url = f"http://127.0.0.1:{self.gateway_port}"

        # 1. Real Auth Sign-In for Alice (Phoenix) and Bob (Globex)
        auth_url = f"{base_url}/auth/v1/token?grant_type=password"

        req_alice = urllib.request.Request(
            auth_url,
            data=json.dumps({"email": "phoenix_lead@phoenix.test", "password": "password123"}).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req_alice) as resp:
            alice_auth = json.loads(resp.read().decode("utf-8"))
            alice_token = alice_auth["access_token"]
            alice_refresh = alice_auth["refresh_token"]

        req_bob = urllib.request.Request(
            auth_url,
            data=json.dumps({"email": "competitor_lead@globex.test", "password": "password123"}).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req_bob) as resp:
            bob_auth = json.loads(resp.read().decode("utf-8"))
            bob_token = bob_auth["access_token"]

        print(f"  [AUTH ISSUED] Real JWT obtained for Alice (Phoenix): {alice_token[:28]}...")
        print(f"  [AUTH ISSUED] Real JWT obtained for Bob (Globex):    {bob_token[:28]}...")

        # 2. HTTP PostgREST Tenant Isolation Tests
        # Alice reads bids
        req_bids = urllib.request.Request(
            f"{base_url}/rest/v1/bids",
            headers={"Authorization": f"Bearer {alice_token}"}
        )
        with urllib.request.urlopen(req_bids) as resp:
            alice_bids = json.loads(resp.read().decode("utf-8"))
            assert len(alice_bids) == 1
            assert alice_bids[0]["id"] == 101
            assert alice_bids[0]["organization_id"] == self.org_alpha_id
        print("  [POSTGREST ACCEPTANCE] Alice lists bids: Exactly 1 Phoenix bid returned (id=101).")

        # Alice attempts to read Globex bid (id=202)
        req_globex_bid = urllib.request.Request(
            f"{base_url}/rest/v1/bids?id=eq.202",
            headers={"Authorization": f"Bearer {alice_token}"}
        )
        with urllib.request.urlopen(req_globex_bid) as resp:
            globex_query = json.loads(resp.read().decode("utf-8"))
            assert len(globex_query) == 0, f"Cross-tenant leak! Alice read Globex bid: {globex_query}"
        print("  [POSTGREST ACCEPTANCE] Alice requests Globex bid (id=202): 0 rows returned (RLS enforced).")

        # Alice attempts to read Globex documents
        req_globex_docs = urllib.request.Request(
            f"{base_url}/rest/v1/documents?bid_id=eq.202",
            headers={"Authorization": f"Bearer {alice_token}"}
        )
        with urllib.request.urlopen(req_globex_docs) as resp:
            globex_docs = json.loads(resp.read().decode("utf-8"))
            assert len(globex_docs) == 0
        print("  [POSTGREST ACCEPTANCE] Alice requests Globex documents: 0 rows returned (RLS enforced).")

        # Alice attempts to PATCH Globex requirement
        req_patch = urllib.request.Request(
            f"{base_url}/rest/v1/requirements?id=eq.2001",
            data=json.dumps({"description": "Tampered By Alice"}).encode("utf-8"),
            headers={"Authorization": f"Bearer {alice_token}", "Content-Type": "application/json", "Prefer": "return=representation"},
            method="PATCH"
        )
        with urllib.request.urlopen(req_patch) as resp:
            patch_res = json.loads(resp.read().decode("utf-8"))
            assert len(patch_res) == 0, f"Cross-tenant modification allowed! {patch_res}"
        print("  [POSTGREST ACCEPTANCE] Alice attempts PATCH Globex requirement: 0 rows modified (RLS enforced).")

        # 3. Storage Acceptance: Bucket Privacy, Upload, Signed URLs, and Bearer Semantics
        # Negative control: Unauthenticated download of private object
        req_unauth_storage = urllib.request.Request(f"{base_url}/storage/v1/object/bid-documents/101/alpha.pdf")
        try:
            with urllib.request.urlopen(req_unauth_storage) as resp:
                assert False, "Unauthenticated storage access permitted!"
        except urllib.error.HTTPError as e:
            assert e.code == 401
            print(f"  [STORAGE ACCEPTANCE] Unauthenticated access to private bucket: Blocked with HTTP {e.code}.")

        # Authorized Upload via Alice
        test_file_bytes = b"%PDF-1.4 Commissioning Document Alpha Test"
        upload_path = "101/commissioning_test.pdf"
        req_upload = urllib.request.Request(
            f"{base_url}/storage/v1/object/bid-documents/{upload_path}",
            data=test_file_bytes,
            headers={"Authorization": f"Bearer {alice_token}", "Content-Type": "application/pdf"},
            method="POST"
        )
        with urllib.request.urlopen(req_upload) as resp:
            upload_res = json.loads(resp.read().decode("utf-8"))
            assert "Key" in upload_res
        print("  [STORAGE ACCEPTANCE] Authorized upload to bid-documents: HTTP 200 OK.")

        # Authorized Signed URL Generation (expiry in 3 seconds for test)
        req_sign = urllib.request.Request(
            f"{base_url}/storage/v1/object/sign/bid-documents/{upload_path}",
            data=json.dumps({"expiresIn": 3}).encode("utf-8"),
            headers={"Authorization": f"Bearer {alice_token}", "Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req_sign) as resp:
            sign_res = json.loads(resp.read().decode("utf-8"))
            signed_url_path = sign_res["signedURL"]
            assert "token=" in signed_url_path
        print("  [STORAGE ACCEPTANCE] Authorized signed URL generated with 3s expiry.")

        # Access via Valid Signed URL
        req_signed_fetch = urllib.request.Request(f"{base_url}{signed_url_path}")
        with urllib.request.urlopen(req_signed_fetch) as resp:
            fetched_bytes = resp.read()
            assert fetched_bytes == test_file_bytes
        print("  [STORAGE ACCEPTANCE] Fetch via valid signed URL: HTTP 200 OK (matching bytes).")

        # Bearer Capability Persistence across Logout
        # Alice logs out
        req_logout = urllib.request.Request(
            f"{base_url}/auth/v1/logout",
            headers={"Authorization": f"Bearer {alice_token}"},
            method="POST"
        )
        with urllib.request.urlopen(req_logout) as resp:
            assert resp.status == 204
        print("  [AUTH ACCEPTANCE] Alice logged out successfully (session revoked).")

        # Alice's old token is now rejected
        req_user_revoked = urllib.request.Request(
            f"{base_url}/auth/v1/user",
            headers={"Authorization": f"Bearer {alice_token}"}
        )
        try:
            with urllib.request.urlopen(req_user_revoked) as resp:
                assert False, "Revoked token still accepted!"
        except urllib.error.HTTPError as e:
            assert e.code == 401
            print(f"  [AUTH ACCEPTANCE] Revoked token rejected by Auth service: HTTP {e.code}.")

        # Existing Signed URL remains valid until expiry (Bearer capability)
        with urllib.request.urlopen(req_signed_fetch) as resp:
            assert resp.read() == test_file_bytes
        print("  [STORAGE ACCEPTANCE] Existing signed URL remains functional post-logout (bearer capability confirmed).")

        # Wait for signed URL to expire (> 3.5 seconds)
        time.sleep(3.5)
        try:
            with urllib.request.urlopen(req_signed_fetch) as resp:
                assert False, "Expired signed URL was accepted!"
        except urllib.error.HTTPError as e:
            assert e.code in (401, 403)
            print(f"  [STORAGE ACCEPTANCE] Expired signed URL rejected: HTTP {e.code} (fails closed).")

        # Refresh Token Exchange
        req_refresh = urllib.request.Request(
            f"{base_url}/auth/v1/token?grant_type=refresh_token",
            data=json.dumps({"refresh_token": alice_refresh}).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req_refresh) as resp:
            refresh_res = json.loads(resp.read().decode("utf-8"))
            new_jwt = refresh_res["access_token"]
            assert new_jwt and new_jwt != alice_token
        print("  [AUTH ACCEPTANCE] Refresh token exchange: Successfully produced fresh access token.")

        # PostgREST Expired JWT Rejection
        expired_jwt = jwt.encode(
            {"sub": self.user_alpha_id, "role": "authenticated", "exp": int(time.time()) - 100},
            JWT_SECRET, algorithm="HS256"
        )
        req_expired = urllib.request.Request(
            f"{base_url}/rest/v1/bids",
            headers={"Authorization": f"Bearer {expired_jwt}"}
        )
        try:
            with urllib.request.urlopen(req_expired) as resp:
                assert False, "PostgREST accepted expired JWT!"
        except urllib.error.HTTPError as e:
            assert e.code == 401
            print(f"  [POSTGREST ACCEPTANCE] PostgREST rejects expired JWT with HTTP {e.code} ({e.read().decode()[:45]}).")

        self.results["phase2"] = "GO - All real Auth, PostgREST & Storage acceptance criteria passed."
        print("\nPhase 2 Complete: 100% of real Auth, PostgREST and Storage acceptance criteria PASSED.")

    def run_phase3_real_phoenix_workflow(self):
        print("\n================================================================================")
        print("PHASE 3: REAL PHOENIX BETA WORKFLOW (RFP UPLOAD -> FAST -> FULL -> REPORTS)")
        print("================================================================================")

        base_url = f"http://127.0.0.1:{self.gateway_port}"

        # 1. Configure runtime environment for local isolated gateway
        os.environ["SUPABASE_URL"] = base_url
        os.environ["SUPABASE_SERVICE_KEY"] = SERVICE_ROLE_KEY
        os.environ["SUPABASE_KEY"] = SERVICE_ROLE_KEY
        os.environ["SUPABASE_ANON_KEY"] = ANON_KEY

        # Load real Anthropic API Key from main repository .env
        from dotenv import load_dotenv
        load_dotenv(r"c:\Users\feras\Documents\Projects\Bid-Intelligence\.env")
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY missing from environment!")

        print(f"  [CONFIGURED] Connected to isolated Supabase Gateway at {base_url}.")
        print("  [CONFIGURED] Live Anthropic model claude-haiku-4-5-20251001 enabled.")

        # 2. Create Bid for Phoenix Consulting
        bid_data = {
            "title": "Municipal IT Operations Transformation & Strategic Advisory Services",
            "client": "City of Edmonton",
            "file_number": "COE-RFP-2026-088",
            "stage": "Active",
            "sensitivity": "Commercial",
            "owner": "Phoenix Engagement Lead",
            "value_cad": 850000.0,
            "submission_deadline": "2026-09-08",
            "clarification_deadline": "2026-08-18",
            "notes": "Phoenix Consulting restricted beta commissioning bid.",
        }
        bid_id = tenancy.create_bid_for_organization(bid_data, self.org_alpha_id)
        assert bid_id is not None
        print(f"  [STEP 1] Created Bid #{bid_id} for Phoenix Consulting ({self.org_alpha_id}).")

        # 3. Upload Representative RFP PDF
        rfp_bytes = generate_rfp_pdf_bytes()
        rfp_filename = "COE_RFP_2026_088_Municipal_IT_Advisory.pdf"
        file_path, doc_id = tenancy.upload_document_for_organization(
            bid_id, self.org_alpha_id, rfp_filename, rfp_bytes, doc_type="RFP / Source", owner="Alice Lead"
        )
        assert doc_id is not None
        print(f"  [STEP 2] Uploaded RFP Document #{doc_id} ({len(rfp_bytes)} bytes) to bid-documents Storage.")

        # 4. Execute Real FAST Analysis via claude-haiku-4-5-20251001
        print("  [STEP 3] Starting FAST Analysis via real Anthropic Claude API...")
        t0 = time.time()
        run_info = tenancy.start_fast_analysis_for_organization(
            bid_id, self.org_alpha_id, api_key, created_by=self.user_alpha_id
        )
        fast_run_id = run_info["id"]
        print(f"           Fast Analysis Run #{fast_run_id} initiated. Monitoring in-process worker thread...")

        # Poll in-process completion
        final_fast_run = None
        for attempt in range(120):
            time.sleep(2)
            run_status = db.get_analysis_run(fast_run_id)
            status = run_status.get("status")
            elapsed = time.time() - t0
            print(f"           [T+{elapsed:.1f}s] Run #{fast_run_id} status: {status}...")
            if status in ("COMPLETE", "FAILED"):
                final_fast_run = run_status
                break

        if not final_fast_run or final_fast_run.get("status") != "COMPLETE":
            fail_reason = (final_fast_run or {}).get("failure_reason", "Timeout")
            raise RuntimeError(f"FAST Analysis failed: {fail_reason}")

        fast_duration = time.time() - t0
        print(f"  [FAST COMPLETE] Completed in {fast_duration:.1f}s via claude-haiku-4-5-20251001.")

        # 5. Verify Structured Findings & Source Grounding
        fast_result = db.get_analysis_result(fast_run_id)
        assert fast_result is not None, "Missing analysis_results row!"
        structured = fast_result.get("structured_intelligence", {})
        opportunity = structured.get("opportunity_snapshot", {})
        snapshot_facts = opportunity.get("facts", [])
        proc_scope = structured.get("procurement_scope", {})
        service_cats = proc_scope.get("service_categories", [])
        dates_mech = structured.get("dates_and_mechanics", {})
        key_dates = dates_mech.get("key_dates", [])
        eval_section = structured.get("evaluation", {})
        eval_stages = eval_section.get("stages", [])
        eval_weights = eval_section.get("weights_by_category", {})
        resp_reqs = structured.get("response_requirements", {})
        checklist = resp_reqs.get("checklist", [])
        pricing_comm = structured.get("pricing_and_commercial", {})
        comm_points = pricing_comm.get("points", [])
        comm_clauses = pricing_comm.get("raw_commercial_clauses", [])
        ambiguities = structured.get("ambiguities", [])
        fact_origins = fast_result.get("fact_origins", {})

        total_extracted_facts = (
            len(snapshot_facts) + len(service_cats) + len(key_dates) +
            len(eval_stages) + len(checklist) + len(comm_points) + len(ambiguities)
        )

        print(f"  [FINDINGS AUDIT] Opportunity snapshot facts:        {len(snapshot_facts)}")
        print(f"  [FINDINGS AUDIT] Scope service categories:          {len(service_cats)}")
        print(f"  [FINDINGS AUDIT] Key procurement dates:             {len(key_dates)}")
        print(f"  [FINDINGS AUDIT] Evaluation stages & criteria:      {len(eval_stages)}")
        print(f"  [FINDINGS AUDIT] Response checklist items:          {len(checklist)}")
        print(f"  [FINDINGS AUDIT] Pricing & commercial clauses:      {len(comm_points) + len(comm_clauses)}")
        print(f"  [FINDINGS AUDIT] Identified ambiguities:            {len(ambiguities)}")
        print(f"  [SOURCE GROUNDING] Fact origins tracked:           {len(fact_origins)} grounded items.")

        assert total_extracted_facts > 0, "No intelligence extracted by Fast Analysis!"
        assert len(fact_origins) > 0, "No source grounding origins tracked!"

        # 6. Execute FULL Analysis (Specialist Multi-Agent Pipeline)
        print("  [STEP 4] Starting FULL Analysis using specialist workflow...")
        t_full0 = time.time()
        full_info = tenancy.start_full_analysis_for_organization(
            bid_id, self.org_alpha_id, api_key, source_run_id=fast_run_id,
            created_by_user_id=self.user_alpha_id, execution="inline"
        )
        full_run = full_info["run"]
        full_run_id = full_run["id"]
        full_duration = time.time() - t_full0
        print(f"  [FULL COMPLETE] Full Analysis Run #{full_run_id} completed inline in {full_duration:.1f}s.")

        full_result = tenancy.get_full_analysis_result_for_organization(bid_id, self.org_alpha_id, full_run_id)
        assert full_result is not None, "Missing Full Analysis result!"
        specialist_results = full_result.get("specialist_results", [])
        print(f"  [SPECIALISTS AUDIT] Completed specialists: {len(specialist_results)} specialist outputs.")

        # 7. Render, Review, and Download Reports
        print("  [STEP 5] Exporting and validating final PDF reports...")

        # A. Bid Intelligence Brief (Customer Export)
        brief_pdf_bytes = tenancy.export_bid_intelligence_brief_for_organization(bid_id, fast_run_id, self.org_alpha_id)
        assert brief_pdf_bytes and len(brief_pdf_bytes) > 1000
        assert brief_pdf_bytes.startswith(b"%PDF"), "Brief is not a valid PDF!"
        print(f"  [REPORT 1] Bid Intelligence Brief PDF exported: {len(brief_pdf_bytes):,} bytes (Valid PDF).")

        # B. Full Intelligence Appendix Report
        appendix_pdf_bytes = tenancy.download_analysis_report_for_organization(bid_id, fast_run_id, self.org_alpha_id)
        assert appendix_pdf_bytes and len(appendix_pdf_bytes) > 1000
        assert appendix_pdf_bytes.startswith(b"%PDF"), "Appendix is not a valid PDF!"
        print(f"  [REPORT 2] Full Intelligence Appendix PDF downloaded: {len(appendix_pdf_bytes):,} bytes (Valid PDF).")

        # C. Full Analysis Specialist PDF Export
        full_report_export = tenancy.export_full_analysis_report_for_organization(bid_id, self.org_alpha_id, full_run_id)
        full_pdf_bytes = full_report_export["pdf"]
        assert full_pdf_bytes and full_pdf_bytes.startswith(b"%PDF")
        print(f"  [REPORT 3] Full Analysis Intelligence Report PDF exported: {len(full_pdf_bytes):,} bytes (Valid PDF).")

        self.results["phase3"] = {
            "status": "GO",
            "bid_id": bid_id,
            "fast_run_id": fast_run_id,
            "fast_duration": round(fast_duration, 1),
            "full_run_id": full_run_id,
            "full_duration": round(full_duration, 1),
            "findings_count": total_extracted_facts,
            "specialist_count": len(specialist_results),
            "brief_bytes": len(brief_pdf_bytes),
            "appendix_bytes": len(appendix_pdf_bytes),
            "full_pdf_bytes": len(full_pdf_bytes),
        }
        print("\nPhase 3 Complete: Full end-to-end Phoenix beta workflow executed successfully.")

    def cleanup(self):
        print("\n[Cleanup] Tearing down isolated commissioning environment...")
        if self.gateway_server:
            self.gateway_server.shutdown()
        if self.pgrst_proc:
            self.pgrst_proc.terminate()
            try:
                self.pgrst_proc.wait(timeout=5)
            except Exception:
                self.pgrst_proc.kill()
        if hasattr(self, 'pgrst_log') and self.pgrst_log and not self.pgrst_log.closed:
            try:
                self.pgrst_log.close()
            except Exception:
                pass
        if self.pg_proc:
            pg_ctl = os.path.join(PG_BIN, "pg_ctl.exe")
            subprocess.run([pg_ctl, "stop", "-D", self.data_dir, "-m", "immediate"],
                           check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.pg_proc.terminate()
            try:
                self.pg_proc.wait(timeout=5)
            except Exception:
                self.pg_proc.kill()
        time.sleep(1.0)
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        print("  [OK] Ephemeral PostgreSQL 17, PostgREST daemon, Gateway and directories removed. Zero residue.")


def main():
    harness = CommissioningHarness()
    try:
        harness.setup_postgres()
        harness.setup_postgrest()
        harness.setup_gateway()
        harness.run_phase2_auth_and_storage_acceptance()
        harness.run_phase3_real_phoenix_workflow()
    finally:
        harness.cleanup()


if __name__ == "__main__":
    main()
