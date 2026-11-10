"""
tests/test_migration_023_base_rls.py

Static contract tests for Migration 023 (Package R2A: Enable Base Tables Tenant RLS).
Verifies:
- All 11 base tables explicitly have ENABLE ROW LEVEL SECURITY.
- All 11 base tables revoke privileges from the 'anon' role.
- All 11 base tables grant standard CRUD to 'authenticated'.
- Sequences grant USAGE, SELECT to 'authenticated' and are revoked from 'anon'.
- No unconditional or dangerous syntax introduced.
"""
import os
import unittest

MIGRATION_023_PATH = os.path.join(
    os.path.dirname(__file__), "..", "migrations", "023_enable_base_tables_tenant_rls.sql"
)

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


def _migration_023_text() -> str:
    with open(MIGRATION_023_PATH, "r", encoding="utf-8") as f:
        return f.read()


def _strip_sql_line_comments(text: str) -> str:
    return "\n".join(
        line for line in text.splitlines()
        if not line.strip().startswith("--")
    )


class TestMigration023SchemaContract(unittest.TestCase):

    def setUp(self):
        import re
        self.raw = _migration_023_text()
        self.code = re.sub(r'\s+', ' ', _strip_sql_line_comments(self.raw).lower())

    def test_file_exists_and_non_empty(self):
        self.assertTrue(os.path.exists(MIGRATION_023_PATH))
        self.assertGreater(len(self.raw), 500)

    def test_every_base_table_has_enable_row_level_security(self):
        for table in BASE_TABLES:
            pattern = f"alter table public.{table} enable row level security;"
            self.assertIn(
                pattern, self.code,
                msg=f"Migration 023 missing ENABLE ROW LEVEL SECURITY for {table}"
            )

    def test_every_base_table_revokes_from_anon(self):
        for table in BASE_TABLES:
            pattern = f"revoke all on table public.{table} from anon;"
            self.assertIn(
                pattern, self.code,
                msg=f"Migration 023 missing REVOKE ALL ON TABLE public.{table} FROM anon;"
            )

    def test_every_base_table_grants_to_authenticated(self):
        for table in BASE_TABLES:
            pattern = f"grant select, insert, update, delete on table public.{table} to authenticated;"
            self.assertIn(
                pattern, self.code,
                msg=f"Migration 023 missing standard CRUD GRANT for {table} to authenticated;"
            )

    def test_sequences_granted_to_authenticated_and_revoked_from_anon(self):
        self.assertIn("grant usage, select on all sequences in schema public to authenticated;", self.code)
        self.assertIn("grant usage, select on all sequences in schema public to service_role;", self.code)
        self.assertIn("revoke all on all sequences in schema public from anon;", self.code)

    def test_no_dangerous_unconditional_policies_added(self):
        self.assertNotIn("create policy", self.code)
        self.assertNotIn("using (true)", self.code)
        self.assertNotIn("with check (true)", self.code)
