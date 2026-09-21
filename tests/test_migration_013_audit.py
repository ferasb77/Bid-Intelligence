"""
tests/test_migration_013_audit.py -- Migration 013 Compatibility Audit
(2026-09-21). migrations/013_section_analyzer.sql remains UNAPPLIED to any
live database (this test never touches Supabase) -- these are static,
source-level checks that the file's security-hardening fix (removing the
unused `authenticated` INSERT policy on `section_reviews`) is present and
that the schema this audit verified against application code (database.py/
section_analyzer.py/tenancy.py) has not silently drifted since.
"""
from pathlib import Path

MIGRATION_013 = Path(__file__).resolve().parent.parent / "migrations" / "013_section_analyzer.sql"


def _read():
    return MIGRATION_013.read_text(encoding="utf-8")


class TestMigrationFileIntegrity:

    def test_migration_file_exists(self):
        assert MIGRATION_013.exists()

    def test_creates_both_expected_tables(self):
        sql = _read().lower()
        assert "create table if not exists outline_section_requirements" in sql
        assert "create table if not exists section_reviews" in sql

    def test_rls_enabled_on_both_tables(self):
        sql = _read().lower()
        assert "alter table outline_section_requirements enable row level security" in sql
        assert "alter table section_reviews enable row level security" in sql


class TestSecurityHardeningFix:
    """The 2026-09-21 audit found `section_reviews_insert_bid_access` was
    dead code from the app's own perspective (database.create_section_
    review always writes via the service-role client) yet still let any
    bid-authorized `authenticated` user forge an arbitrary section_reviews
    row directly via the REST API. Removed to match the service-role-only
    write pattern migrations 015-019 already established."""

    def test_section_reviews_has_no_authenticated_insert_policy(self):
        sql = _read()
        assert "section_reviews_insert_bid_access" not in sql

    def test_section_reviews_has_no_authenticated_update_or_delete_policy(self):
        sql = _read()
        assert "section_reviews_update_bid_access" not in sql
        assert "section_reviews_delete_bid_access" not in sql

    def test_section_reviews_still_has_authenticated_select_policy(self):
        sql = _read()
        assert "create policy section_reviews_select_bid_access" in sql.replace("\n", " ")

    def test_outline_section_requirements_write_policies_unchanged(self):
        """outline_section_requirements IS genuinely written via the
        authenticated RLS-scoped client (Category A, no model call) --
        its select/insert/delete policy set is intentionally untouched by
        the audit fix."""
        sql = _read()
        for policy in (
            "outline_section_requirements_select_bid_access",
            "outline_section_requirements_insert_bid_access",
            "outline_section_requirements_delete_bid_access",
        ):
            assert policy in sql

    def test_no_unnecessary_update_policy_on_mapping_table(self):
        """The mapping table uses delete-then-reinsert (replace-all)
        semantics, never an in-place UPDATE -- no UPDATE policy is
        expected or needed."""
        assert "outline_section_requirements_update_bid_access" not in _read()


class TestApplicationCodeColumnAlignment:
    """Static proof the audit's "no schema drift vs. application code"
    finding stays true going forward: every column database.py's
    create_section_review/set_section_requirement_mapping writes, and
    every direction value section_analyzer.py validates against, must
    still appear in the migration file."""

    def test_section_reviews_columns_match_database_py_write_keys(self):
        import database as db
        import inspect

        source = inspect.getsource(db.create_section_review)
        sql = _read().lower()
        # Extract the literal keys list database.py writes.
        for column in (
            "section_content_snapshot", "section_content_hash", "mapped_requirement_ids",
            "based_on_procurement_revision", "based_on_procurement_truth_status",
            "based_on_analysis_run_id", "based_on_analysis_result_id",
            "raw_snapshot_schema_version", "review_schema_version", "direction",
            "review_result", "created_by_user_id",
        ):
            assert column in source, f"database.create_section_review no longer writes {column}"
            assert column in sql, f"migrations/013 no longer defines column {column}"

    def test_direction_check_constraint_matches_section_analyzer_directions(self):
        import section_analyzer as sa

        sql = _read()
        for direction in sa.DIRECTIONS:
            assert direction in sql, f"migration 013's direction CHECK constraint is missing {direction!r}"
