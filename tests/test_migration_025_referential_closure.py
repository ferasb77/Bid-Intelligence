"""
tests/test_migration_025_referential_closure.py

Deterministic tests for Migration 025: Bid Purge Referential Closure & Cascade Immutability.

Proves:
1. Migration 025 SQL schema contract:
   - trigger function prevent_applied_review_document_mutation() defined with search_path safety
   - trigger guard_applied_review_document_immutability defined BEFORE UPDATE OR DELETE
   - foreign keys with ON DELETE CASCADE and ON DELETE SET NULL properly specified
   - bid cascade existence check present in review document mutation guard
2. Direct-Delete immutability preservation:
   - UPDATE of applied review documents remains strictly prohibited
   - Direct DELETE of applied review documents with live bid remains prohibited
   - Direct DELETE of source document referenced by applied review with live bid remains prohibited
   - Direct DELETE of applied changes and resolved conflicts remains prohibited
3. Whole-bid purge referential closure:
   - Parent bid deletion cascades cleanly through documents, reviews, review_documents,
     changes (source_document_id, target_requirement_id), and conflicts (target_requirement_id).
"""
import re
import subprocess
import unittest
from pathlib import Path

MIGRATION_025_PATH = (
    Path(__file__).resolve().parent.parent
    / "migrations"
    / "025_bid_purge_referential_closure.sql"
)


def _strip_sql_line_comments(text: str) -> str:
    return "\n".join(
        line for line in text.splitlines() if not line.strip().startswith("--")
    )


class TestMigration025SchemaContract(unittest.TestCase):
    """Static SQL contract assertions for Migration 025."""

    def setUp(self):
        self.raw = MIGRATION_025_PATH.read_text(encoding="utf-8")
        self.code = _strip_sql_line_comments(self.raw).lower()

    def test_migration_file_exists(self):
        self.assertTrue(MIGRATION_025_PATH.exists())

    def test_prevent_applied_review_document_mutation_defined(self):
        self.assertIn(
            "create or replace function public.prevent_applied_review_document_mutation()",
            self.code,
        )

    def test_trigger_remains_before_update_or_delete(self):
        self.assertIn("create trigger guard_applied_review_document_immutability", self.code)
        idx = self.code.index("create trigger guard_applied_review_document_immutability")
        block = self.code[idx : idx + 250]
        self.assertIn(
            "before update or delete",
            block,
            "Trigger guard_applied_review_document_immutability must be BEFORE UPDATE OR DELETE",
        )
        self.assertIn("on public.procurement_update_review_documents", block)

    def test_cascade_checks_parent_bid_existence_on_delete(self):
        """Must check if parent bid still exists when handling DELETE."""
        normalized = re.sub(r"\s+", " ", self.code)
        self.assertIn("select 1 from public.bids where id = v_bid_id", normalized)

    def test_applied_review_document_immutable_exception_preserved(self):
        self.assertIn("applied_review_document_immutable", self.code)

    def test_procurement_update_review_documents_fk_cascade(self):
        normalized = re.sub(r"\s+", " ", self.code)
        self.assertIn(
            "alter table public.procurement_update_review_documents add constraint procurement_update_review_documents_document_id_fkey foreign key (document_id) references public.documents(id) on delete cascade",
            normalized,
        )

    def test_procurement_changes_source_document_fk_cascade(self):
        normalized = re.sub(r"\s+", " ", self.code)
        self.assertIn(
            "alter table public.procurement_changes add constraint procurement_changes_source_document_id_fkey foreign key (source_document_id) references public.documents(id) on delete cascade",
            normalized,
        )

    def test_procurement_conflicts_target_requirement_fk_set_null(self):
        normalized = re.sub(r"\s+", " ", self.code)
        self.assertIn(
            "alter table public.procurement_conflicts add constraint procurement_conflicts_target_requirement_id_fkey foreign key (target_requirement_id) references public.requirements(id) on delete set null",
            normalized,
        )

    def test_procurement_changes_target_requirement_fk_set_null(self):
        normalized = re.sub(r"\s+", " ", self.code)
        self.assertIn(
            "alter table public.procurement_changes add constraint procurement_changes_target_requirement_id_fkey foreign key (target_requirement_id) references public.requirements(id) on delete set null",
            normalized,
        )


class TestMigration025RealPostgresExecution(unittest.TestCase):
    """Executes the full 15-step matrix (A through O) in a real PostgreSQL engine."""

    def test_real_postgresql_cascade_matrix(self):
        script_path = (
            Path(__file__).resolve().parent.parent
            / "scripts"
            / "test_postgres_cascade_matrix.js"
        )
        self.assertTrue(script_path.exists())

        res = subprocess.run(
            ["node", str(script_path)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            res.returncode,
            0,
            f"Real PostgreSQL test matrix failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}",
        )
        self.assertIn(
            "ALL 15 TESTS (A THROUGH O) PASSED ON REAL POSTGRESQL ENGINE!",
            res.stdout,
        )
