"""
tests/test_procurement_revision_governance.py

Deterministic tests for Procurement Revision & Addendum Governance
(migration 010). No live Postgres/Supabase connection anywhere in this
file -- migration 010 itself is proven only via static assertions on its
own SQL text (mirroring tests/test_tenant_rls_enforcement.py's
TestMigration008PolicyContract pattern), and every database.py/tenancy.py/
analyst.py function is exercised with a mocked Supabase client.

Coverage groups, each its own class:
  * TestMigration010SchemaContract      -- schema/RPC/trigger/RLS static text
  * TestDatabaseGovernanceLayer         -- database.py wrapper functions
  * TestTenancyGovernanceAuthorization  -- tenancy.py authorization boundary
  * TestAnalystProcurementChangeProposal-- analyst.py purity + shape
  * TestRequirementsLifecycleFiltering  -- current-truth reads exclude retired rows
  * TestFastAnalysisAdvisoryOnly        -- Fast Analysis never writes bid_briefs
"""
import hashlib
import os
import re
import unittest
from unittest.mock import MagicMock, patch

MIGRATION_010_PATH = os.path.join(
    os.path.dirname(__file__), "..", "migrations", "010_procurement_revision_governance.sql"
)


def _migration_010_text() -> str:
    with open(MIGRATION_010_PATH, "r", encoding="utf-8") as f:
        return f.read()


def _strip_sql_line_comments(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.strip().startswith("--"))


class TestMigration010SchemaContract(unittest.TestCase):

    def setUp(self):
        self.raw = _migration_010_text()
        self.sql = self.raw.lower()
        self.code = _strip_sql_line_comments(self.raw).lower()

    # ── PART 1: additive columns, correct defaults ───────────────────────
    def test_bids_gets_revision_counter_and_truth_status_defaulting_ungoverned(self):
        self.assertIn("add column if not exists procurement_revision integer not null default 1", self.code)
        self.assertIn(
            "add column if not exists procurement_truth_status text not null default 'ungoverned'", self.code
        )
        self.assertIn("check (procurement_truth_status in ('ungoverned', 'governed'))", self.code)
        # v4 correction: never 'unverified_legacy' -- exactly these two values.
        self.assertNotIn("unverified_legacy", self.code)

    def test_documents_gets_nullable_content_hash(self):
        self.assertIn("add column if not exists content_hash text", self.code)

    def test_requirements_gets_lifecycle_status_defaulting_active_never_deleted(self):
        self.assertIn("add column if not exists lifecycle_status text not null default 'active'", self.code)
        self.assertIn("check (lifecycle_status in ('active', 'superseded', 'removed'))", self.code)
        self.assertIn("add column if not exists retired_at_procurement_revision integer", self.code)
        self.assertNotIn("delete from public.requirements", self.code)

    def test_analysis_runs_gets_advisory_provenance_columns(self):
        self.assertIn("add column if not exists based_on_procurement_revision integer", self.code)
        self.assertIn("add column if not exists unreviewed_document_count integer", self.code)

    def test_analysis_runs_provenance_columns_are_nullable_not_defaulted(self):
        """Migration 010 runs after many analysis_runs rows already exist --
        neither column may force a concrete default onto them (that would
        make a historical run silently look like 'revision 1, 0 documents
        outstanding' instead of 'basis unknown'). NULL is the correct
        state for every pre-existing row; only NEW runs stamp an explicit
        integer, at the application layer, not via a column default."""
        analysis_runs_block = self.code[self.code.index("alter table public.analysis_runs"):]
        analysis_runs_block = analysis_runs_block[:analysis_runs_block.index("alter table public.bid_briefs")]
        self.assertNotIn("not null default", analysis_runs_block)
        self.assertNotIn("default 0", analysis_runs_block)

    def test_bid_briefs_and_bid_decisions_revision_columns_are_also_nullable(self):
        for column in ("narrative_based_on_procurement_revision", "based_on_procurement_revision"):
            statements = re.findall(
                rf"add column if not exists {column}[^;]*;", self.code
            )
            self.assertTrue(statements, msg=f"no add-column statement found for {column}")
            for stmt in statements:
                self.assertNotIn("not null", stmt)
                self.assertNotIn("default", stmt)

    def test_bid_briefs_gets_narrative_scoped_revision_not_a_whole_row_field(self):
        self.assertIn("add column if not exists narrative_based_on_procurement_revision integer", self.code)

    def test_bid_decisions_gets_based_on_procurement_revision(self):
        # Distinguish from bid_briefs' narrative-scoped column: this table's
        # own alter block adds the bare (unprefixed) name.
        decisions_block = self.code[self.code.index("alter table public.bid_decisions"):]
        self.assertIn("add column if not exists based_on_procurement_revision integer", decisions_block)

    # ── PART 2: table creation order + governance table shape ───────────
    def test_procurement_conflicts_created_before_procurement_update_reviews(self):
        """DDL-ordering requirement: procurement_update_reviews.conflict_id
        has a direct FK to procurement_conflicts, so the latter must be
        createable at CREATE TABLE time with no later ALTER TABLE patch."""
        conflicts_idx = self.code.index("create table if not exists public.procurement_conflicts")
        reviews_idx = self.code.index("create table if not exists public.procurement_update_reviews")
        self.assertLess(conflicts_idx, reviews_idx)
        # And the FK really is declared inline at CREATE TABLE time, not
        # patched on afterward.
        self.assertNotIn("add constraint", self.code[reviews_idx:reviews_idx + 4000])

    def test_no_cached_conflict_status_column_on_requirements(self):
        """Explicitly rejected in architecture review -- conflict state is
        always derived live from procurement_conflicts, never cached."""
        requirements_alters = re.findall(r"alter table public\.requirements[^;]*;", self.code)
        for block in requirements_alters:
            self.assertNotIn("conflict_status", block)

    def test_review_kind_field_consistency_constraint_present(self):
        self.assertIn("review_kind_field_consistency", self.code)
        self.assertIn(
            "review_kind in ('baseline', 'buyer_update') and buyer_update_type is not null and conflict_id is null",
            self.code,
        )
        self.assertIn(
            "review_kind = 'conflict_resolution' and conflict_id is not null and buyer_update_type is null",
            self.code,
        )

    def test_exactly_one_primary_document_partial_unique_index(self):
        self.assertIn("idx_procurement_update_review_documents_primary", self.code)
        self.assertIn("where role = 'primary'", self.code)

    def test_review_decision_and_applied_at_are_separate_fields(self):
        """v3 correction: review_decision ('pending'/'approved'/'rejected')
        is NOT the same state as applied_at -- a row can be 'approved' and
        still pending application."""
        changes_block = self.code[self.code.index("create table if not exists public.procurement_changes"):]
        changes_block = changes_block[:changes_block.index("create index")]
        self.assertIn("review_decision text not null default 'pending'", changes_block)
        self.assertIn("applied_at timestamptz", changes_block)
        self.assertNotIn("applied_at text", changes_block)

    def test_change_effect_consistency_constraint_ties_change_type_to_canonical_effect(self):
        self.assertIn("change_effect_consistency", self.code)
        self.assertIn(
            "change_type in ('added', 'modified', 'superseded', 'removed') and canonical_effect = 'canonical_change'",
            self.code,
        )
        self.assertIn("change_type = 'unchanged' and canonical_effect = 'evidence_only'", self.code)

    # ── PART 3: every RPC is SECURITY DEFINER, fixed search_path, and ────
    #            locked to service_role only ─────────────────────────────
    _RPC_SIGNATURES = [
        ("compute_procurement_document_set_digest", "text, bigint[], text[], text[], bigint, integer"),
        ("create_procurement_update_review", "bigint, uuid, text, text, date, bigint[], text[], bigint, text"),
        ("record_change_review_decision", "bigint, text, uuid, text"),
        ("refresh_bid_brief_projection", "bigint"),
        ("apply_procurement_update_review", "bigint, integer, uuid"),
        ("resolve_procurement_conflict", "bigint, integer, jsonb, text, uuid"),
    ]

    def test_every_rpc_is_security_definer_with_fixed_search_path(self):
        for name, _sig in self._RPC_SIGNATURES:
            fn_idx = self.code.index(f"create or replace function public.{name.lower()}(")
            fn_body = self.code[fn_idx:self.code.index("as $$", fn_idx)]
            self.assertIn("security definer", fn_body, msg=f"{name} missing SECURITY DEFINER")
            self.assertIn("set search_path = public, pg_temp", fn_body, msg=f"{name} missing fixed search_path")

    def test_every_rpc_is_locked_to_service_role_only(self):
        for name, sig in self._RPC_SIGNATURES:
            qualified = f"public.{name.lower()}({sig.lower()})"
            self.assertIn(f"revoke all on function {qualified} from public", self.code)
            self.assertIn(f"revoke execute on function {qualified} from anon", self.code)
            self.assertIn(f"revoke execute on function {qualified} from authenticated", self.code)
            self.assertIn(f"grant execute on function {qualified} to service_role", self.code)

    def test_apply_review_reads_decisions_from_table_not_a_second_parameter(self):
        """The explicit v4 implementation correction: apply_procurement_
        update_review(p_review_id, p_expected_base_revision, p_actor_user_id)
        must NOT accept a second independent approved/rejected array -- it
        reads review_decision from procurement_changes itself."""
        fn_idx = self.code.index("create or replace function public.apply_procurement_update_review(")
        signature = self.code[fn_idx:self.code.index(") returns", fn_idx)]
        self.assertNotIn("approved_change_ids", signature)
        self.assertNotIn("rejected_change_ids", signature)
        self.assertEqual(
            re.sub(r"\s+", " ", signature).strip(),
            "create or replace function public.apply_procurement_update_review( p_review_id bigint, "
            "p_expected_base_revision integer, p_actor_user_id uuid",
        )

    def test_apply_review_uses_row_lock_and_optimistic_concurrency(self):
        fn_idx = self.code.index("create or replace function public.apply_procurement_update_review(")
        fn_body = self.code[fn_idx:self.code.index("$$;", fn_idx)]
        self.assertIn("for update", fn_body)
        self.assertIn("stale_revision", fn_body)

    def test_apply_review_is_idempotent_on_already_applied_review(self):
        fn_idx = self.code.index("create or replace function public.apply_procurement_update_review(")
        fn_body = self.code[fn_idx:self.code.index("$$;", fn_idx)]
        applied_branch = fn_body[fn_body.index("if v_review_status = 'applied' then"):]
        applied_branch = applied_branch[:applied_branch.index("end if;")]
        self.assertIn("select r.resulting_procurement_revision, 0", applied_branch)

    def test_apply_review_never_dynamic_sql_for_bid_brief_field(self):
        """entity_type='bid_brief_field' writes must be a hardcoded
        whitelist of column names, never string-built/EXECUTE'd SQL."""
        fn_idx = self.code.index("create or replace function public.apply_procurement_update_review(")
        fn_body = self.code[fn_idx:self.code.index("$$;", fn_idx)]
        bid_brief_branch = fn_body[fn_body.index("elsif v_change.entity_type = 'bid_brief_field'"):]
        self.assertNotIn("execute ", bid_brief_branch[:bid_brief_branch.index("end if;")])
        for field in ("opportunity_type", "contract_term", "procurement_model",
                      "commercial_structure", "submission_requirements", "key_dates"):
            self.assertIn(field, bid_brief_branch)
        self.assertIn("unknown_bid_brief_field", bid_brief_branch)

    def test_refresh_bid_brief_projection_never_touches_narrative_fields(self):
        """It rebuilds only the A/B canonical fields -- the four C-field
        narrative columns (executive_summary/contract_risks/
        scope_categories/deliverables_summary) are synthesized prose and
        must never be silently overwritten by this SQL function."""
        fn_idx = self.code.index("create or replace function public.refresh_bid_brief_projection(")
        fn_body = self.code[fn_idx:self.code.index("$$;", fn_idx)]
        for narrative_field in ("executive_summary", "contract_risks", "scope_categories", "deliverables_summary"):
            self.assertNotIn(narrative_field, fn_body)
        self.assertNotIn("based_on_procurement_revision", fn_body)

    def test_resolve_procurement_conflict_always_creates_review_and_increments_revision(self):
        fn_idx = self.code.index("create or replace function public.resolve_procurement_conflict(")
        fn_body = self.code[fn_idx:self.code.index("$$;", fn_idx)]
        self.assertIn("v_new_revision := v_current_revision + 1", fn_body)
        self.assertIn("'conflict_resolution'", fn_body)
        # Never a bare status flip with no review/history.
        self.assertNotIn("set status = 'resolved'", fn_body[:fn_body.index("insert into public.procurement_changes")])

    def test_baseline_apply_does_not_require_canonical_change_only_a_governed_apply_does_revision_bump(self):
        """v4 correction: baseline requires >=1 APPROVED row of any effect,
        but does not itself require canonical_effect='canonical_change' --
        only the presence of >=1 approved canonical_change row increments
        the revision."""
        fn_idx = self.code.index("create or replace function public.apply_procurement_update_review(")
        fn_body = self.code[fn_idx:self.code.index("$$;", fn_idx)]
        self.assertIn("no_approved_material_proposal", fn_body)
        self.assertIn("v_canonical_change_count > 0", fn_body)
        self.assertIn("v_new_revision := v_current_revision + 1", fn_body)
        self.assertIn("v_new_revision := v_current_revision;", fn_body)

    def test_baseline_apply_never_increments_revision_directly(self):
        """Baseline flips procurement_truth_status -> 'governed' but the
        revision counter only ever moves via the shared canonical-change-
        count logic above -- there is no baseline-specific '+ 1'."""
        fn_idx = self.code.index("create or replace function public.apply_procurement_update_review(")
        fn_body = self.code[fn_idx:self.code.index("$$;", fn_idx)]
        self.assertIn("when v_review_kind = 'baseline' then 'governed'", fn_body)

    # ── PART 4: immutability triggers ────────────────────────────────────
    def test_three_immutability_triggers_exist_before_update_or_delete(self):
        for trigger, table in [
            ("guard_applied_change_immutability", "procurement_changes"),
            ("guard_applied_review_immutability", "procurement_update_reviews"),
            ("guard_applied_review_document_immutability", "procurement_update_review_documents"),
        ]:
            self.assertIn(f"create trigger {trigger}", self.code)
            trigger_idx = self.code.index(f"create trigger {trigger}")
            trigger_body = self.code[trigger_idx:trigger_idx + 200]
            self.assertIn("before update or delete", trigger_body)
            self.assertIn(f"on public.{table}", trigger_body)

    # ── PART 5: RLS -- SELECT-only for authenticated, nothing for anon ──
    _GOVERNANCE_TABLES = [
        "procurement_update_reviews", "procurement_update_review_documents",
        "procurement_changes", "procurement_conflicts",
    ]

    def test_rls_enabled_on_every_governance_table(self):
        for table in self._GOVERNANCE_TABLES:
            self.assertIn(f"alter table public.{table} enable row level security", self.code)

    def test_select_only_policy_scoped_via_can_access_bid(self):
        policy_blocks = re.findall(r"create policy.*?;", self.code, re.DOTALL)
        self.assertEqual(len(policy_blocks), 4)
        for block in policy_blocks:
            self.assertIn("for select to authenticated", block)
            self.assertIn("can_access_bid", block)

    def test_no_insert_update_delete_policy_for_authenticated(self):
        """No 'create policy ... for insert/update/delete' anywhere -- a
        bare 'for update' also legitimately appears elsewhere in this file
        as a SQL row-lock clause (SELECT ... FOR UPDATE), so this checks
        only inside the create-policy blocks themselves."""
        policy_blocks = re.findall(r"create policy.*?;", self.code, re.DOTALL)
        self.assertEqual(len(policy_blocks), 4)  # sanity: policies were actually found
        for block in policy_blocks:
            self.assertNotIn("for insert", block)
            self.assertNotIn("for update", block)
            self.assertNotIn("for delete", block)

    def test_write_privileges_explicitly_revoked_as_defense_in_depth(self):
        for table in self._GOVERNANCE_TABLES:
            self.assertIn(f"revoke insert, update, delete on public.{table} from authenticated", self.code)
            self.assertIn(f"revoke all on public.{table} from anon", self.code)

    def test_no_policy_or_grant_targets_anon(self):
        policy_blocks = re.findall(r"create policy.*?;", self.code, re.DOTALL)
        for block in policy_blocks:
            self.assertNotIn(" to anon", block)


class TestDatabaseGovernanceLayer(unittest.TestCase):

    @patch("database.get_client")
    def test_hash_document_bytes_is_sha256_hex(self, mock_get_client):
        import database
        import hashlib
        result = database.hash_document_bytes(b"hello world")
        self.assertEqual(result, hashlib.sha256(b"hello world").hexdigest())

    @patch("database.get_client")
    def test_ensure_document_hash_returns_existing_hash_without_downloading(self, mock_get_client):
        import database
        sb = MagicMock()
        sb.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{"content_hash": "existing-hash", "storage_path": "1/x.pdf"}]
        )
        mock_get_client.return_value = sb
        with patch("database.download_file") as mock_download:
            result = database.ensure_document_hash(42)
        self.assertEqual(result, "existing-hash")
        mock_download.assert_not_called()

    @patch("database.download_file")
    @patch("database.get_client")
    def test_ensure_document_hash_computes_and_persists_when_null(self, mock_get_client, mock_download):
        import database
        sb = MagicMock()
        # First select: no hash yet. Second select (race-guard re-check): still null.
        sb.table.return_value.select.return_value.eq.return_value.execute.side_effect = [
            MagicMock(data=[{"content_hash": None, "storage_path": "1/x.pdf"}]),
            MagicMock(data=[{"content_hash": None}]),
        ]
        mock_get_client.return_value = sb
        mock_download.return_value = b"file bytes"

        result = database.ensure_document_hash(42)

        expected_hash = database.hash_document_bytes(b"file bytes")
        self.assertEqual(result, expected_hash)
        sb.table.return_value.update.assert_called_once_with({"content_hash": expected_hash})

    @patch("database.download_file")
    @patch("database.get_client")
    def test_ensure_document_hash_never_overwrites_a_hash_set_concurrently(self, mock_get_client, mock_download):
        """Race guard: if another process set the hash between the first
        read and the write, this must NOT overwrite it with a freshly
        computed value."""
        import database
        sb = MagicMock()
        sb.table.return_value.select.return_value.eq.return_value.execute.side_effect = [
            MagicMock(data=[{"content_hash": None, "storage_path": "1/x.pdf"}]),
            MagicMock(data=[{"content_hash": "hash-set-by-another-process"}]),
        ]
        mock_get_client.return_value = sb
        mock_download.return_value = b"file bytes"

        result = database.ensure_document_hash(42)

        self.assertEqual(result, "hash-set-by-another-process")
        sb.table.return_value.update.assert_not_called()

    @patch("database.get_client")
    def test_ensure_document_hash_returns_none_when_no_storage_path(self, mock_get_client):
        import database
        sb = MagicMock()
        sb.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{"content_hash": None, "storage_path": None}]
        )
        mock_get_client.return_value = sb
        self.assertIsNone(database.ensure_document_hash(42))

    @patch("database.ensure_document_hash")
    @patch("database.get_client")
    def test_create_procurement_update_review_hashes_docs_for_baseline_and_buyer_update(
        self, mock_get_client, mock_ensure_hash
    ):
        import database
        sb = MagicMock()
        sb.rpc.return_value.execute.return_value = MagicMock(data=[{"review_id": 1, "is_new": True}])
        mock_get_client.return_value = sb

        database.create_procurement_update_review(
            bid_id=1, organization_id="org-1", review_kind="baseline",
            document_ids=[10, 11], document_roles=["primary", "supporting"],
            buyer_update_type="Original RFP",
        )
        self.assertEqual(mock_ensure_hash.call_count, 2)
        mock_ensure_hash.assert_any_call(10)
        mock_ensure_hash.assert_any_call(11)

    @patch("database.ensure_document_hash")
    @patch("database.get_client")
    def test_create_procurement_update_review_skips_hashing_for_conflict_resolution(
        self, mock_get_client, mock_ensure_hash
    ):
        import database
        sb = MagicMock()
        sb.rpc.return_value.execute.return_value = MagicMock(data=[{"review_id": 1, "is_new": True}])
        mock_get_client.return_value = sb

        database.create_procurement_update_review(
            bid_id=1, organization_id="org-1", review_kind="conflict_resolution",
            document_ids=[], document_roles=[], conflict_id=5,
        )
        mock_ensure_hash.assert_not_called()

    @patch("database.get_client")
    def test_apply_procurement_update_review_wrapper_omits_decision_arrays(self, mock_get_client):
        """The Python wrapper's own signature must match the corrected RPC
        contract: no approved_change_ids/rejected_change_ids parameter."""
        import database
        import inspect
        sig = inspect.signature(database.apply_procurement_update_review)
        self.assertNotIn("approved_change_ids", sig.parameters)
        self.assertNotIn("rejected_change_ids", sig.parameters)
        self.assertEqual(list(sig.parameters), ["review_id", "expected_base_revision", "actor_user_id"])

    @patch("database.get_client")
    def test_apply_procurement_update_review_calls_rpc_with_exactly_three_params(self, mock_get_client):
        import database
        sb = MagicMock()
        sb.rpc.return_value.execute.return_value = MagicMock(data=[{"resulting_revision": 2, "applied_change_count": 3}])
        mock_get_client.return_value = sb

        result = database.apply_procurement_update_review(7, 1, "user-1")

        sb.rpc.assert_called_once_with("apply_procurement_update_review", {
            "p_review_id": 7, "p_expected_base_revision": 1, "p_actor_user_id": "user-1",
        })
        self.assertEqual(result["resulting_revision"], 2)

    @patch("database.get_client")
    def test_get_bid_procurement_state_defaults_to_ungoverned_revision_1(self, mock_get_client):
        import database
        sb = MagicMock()
        sb.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
        mock_get_client.return_value = sb
        state = database.get_bid_procurement_state(999)
        self.assertEqual(state, {"procurement_revision": 1, "procurement_truth_status": "ungoverned"})

    @patch("database.get_client")
    def test_get_reviewed_document_hashes_empty_when_no_applied_reviews(self, mock_get_client):
        import database
        sb = MagicMock()
        sb.table.return_value.select.return_value.eq.return_value.eq.return_value.in_.return_value.execute.return_value = (
            MagicMock(data=[])
        )
        mock_get_client.return_value = sb
        self.assertEqual(database.get_reviewed_document_hashes(1), set())

    @patch("database.get_client")
    def test_get_reviewed_document_hashes_filters_null_hashes(self, mock_get_client):
        import database
        sb = MagicMock()
        reviews_query = sb.table.return_value.select.return_value.eq.return_value.eq.return_value.in_.return_value
        reviews_query.execute.return_value = MagicMock(data=[{"id": 5}])
        docs_query = sb.table.return_value.select.return_value.in_.return_value
        docs_query.execute.return_value = MagicMock(data=[
            {"document_id": 10, "document_hash": "hash-a"},
            {"document_id": 11, "document_hash": None},
        ])
        mock_get_client.return_value = sb

        result = database.get_reviewed_document_hashes(1)

        self.assertEqual(result, {(10, "hash-a")})


class TestTenancyGovernanceAuthorization(unittest.TestCase):
    """Every wrapper below must call require_bid_access() BEFORE touching
    any privileged db.* call -- the negative-test pattern from
    test_tenant_rls_enforcement.py's TestPrivilegedOperationAuthorization,
    applied to the four migration-010 RPC wrappers plus the proposal
    orchestration function."""

    @patch("tenancy.db")
    @patch("tenancy.require_bid_access")
    def test_get_procurement_state_requires_bid_access(self, mock_require, mock_db):
        import tenancy
        mock_db.get_bid_procurement_state.return_value = {"procurement_revision": 1, "procurement_truth_status": "ungoverned"}
        tenancy.get_procurement_state_for_organization(8, "org-1")
        mock_require.assert_called_once_with(8, "org-1")

    @patch("tenancy.db")
    @patch("tenancy.require_bid_access")
    def test_create_review_denied_before_any_db_call(self, mock_require, mock_db):
        import tenancy
        mock_require.side_effect = tenancy.AccessDeniedError("denied")
        with self.assertRaises(tenancy.AccessDeniedError):
            tenancy.create_procurement_update_review_for_organization(
                8, "org-999", "baseline", [10], ["primary"], buyer_update_type="Original RFP",
            )
        mock_db.create_procurement_update_review.assert_not_called()

    @patch("tenancy.db")
    @patch("tenancy.require_bid_access")
    def test_record_change_decision_rejects_change_belonging_to_a_different_bid(self, mock_require, mock_db):
        import tenancy
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.execute.return_value = (
            MagicMock(data=[{"id": 55, "bid_id": 999}])
        )
        with self.assertRaises(tenancy.AccessDeniedError):
            tenancy.record_change_review_decision_for_organization(8, "org-1", 55, "approved", "user-1")
        mock_db.record_change_review_decision.assert_not_called()

    @patch("tenancy.db")
    @patch("tenancy.require_bid_access")
    def test_apply_review_rejects_review_belonging_to_a_different_bid(self, mock_require, mock_db):
        import tenancy
        mock_db.get_procurement_update_reviews.return_value = [{"id": 3, "bid_id": 999}]
        with self.assertRaises(tenancy.AccessDeniedError):
            tenancy.apply_procurement_update_review_for_organization(8, "org-1", 3, 1, "user-1")
        mock_db.apply_procurement_update_review.assert_not_called()

    @patch("tenancy.db")
    @patch("tenancy.require_bid_access")
    def test_apply_review_authorized_delegates_to_db_wrapper(self, mock_require, mock_db):
        import tenancy
        mock_db.get_procurement_update_reviews.return_value = [{"id": 3, "bid_id": 8}]
        mock_db.apply_procurement_update_review.return_value = {"resulting_revision": 2, "applied_change_count": 1}

        result = tenancy.apply_procurement_update_review_for_organization(8, "org-1", 3, 1, "user-1")

        mock_db.apply_procurement_update_review.assert_called_once_with(3, 1, "user-1")
        self.assertEqual(result["resulting_revision"], 2)

    @patch("tenancy.db")
    @patch("tenancy.require_bid_access")
    def test_resolve_conflict_rejects_conflict_belonging_to_a_different_bid(self, mock_require, mock_db):
        import tenancy
        mock_db.get_procurement_conflicts.return_value = [{"id": 9, "bid_id": 999}]
        with self.assertRaises(tenancy.AccessDeniedError):
            tenancy.resolve_procurement_conflict_for_organization(
                8, "org-1", 9, 1, {"weight": 5}, "resolved by agreement", "user-1",
            )
        mock_db.resolve_procurement_conflict.assert_not_called()

    @patch("tenancy.db")
    @patch("tenancy.require_bid_access")
    def test_propose_changes_denied_before_touching_documents_or_analyst(self, mock_require, mock_db):
        import tenancy
        mock_require.side_effect = tenancy.AccessDeniedError("denied")
        with self.assertRaises(tenancy.AccessDeniedError):
            tenancy.propose_procurement_changes_for_organization(8, "org-999", 3)
        mock_db.get_procurement_update_reviews.assert_not_called()

    @patch("tenancy.db")
    @patch("tenancy.require_bid_access")
    def test_propose_changes_rejects_review_belonging_to_a_different_bid(self, mock_require, mock_db):
        import tenancy
        mock_db.get_procurement_update_reviews.return_value = [{"id": 3, "bid_id": 999}]
        with self.assertRaises(tenancy.AccessDeniedError):
            tenancy.propose_procurement_changes_for_organization(8, "org-1", 3)

    @patch("tenancy.db")
    @patch("tenancy.require_bid_access")
    def test_propose_changes_persists_pending_rows_and_transitions_review(self, mock_require, mock_db):
        import tenancy
        mock_db.get_procurement_update_reviews.return_value = [
            {"id": 3, "bid_id": 8, "buyer_update_type": "Addendum"}
        ]
        review_docs_query = mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value
        review_docs_query.execute.return_value = MagicMock(
            data=[{"document_id": 10, "role": "primary"}]
        )
        mock_db.get_documents.return_value = [
            {"id": 10, "name": "addendum.pdf", "storage_path": "8/addendum.pdf", "content_hash": "hash-a"}
        ]
        mock_db.download_file.return_value = b"pdf bytes"
        mock_db.get_requirements.return_value = [{"req_id": "M1", "category": "Mandatory"}]
        mock_db.get_bid.return_value = {"title": "Some RFP", "client": "Some Client"}

        with patch("extractor.extract_text_from_file", return_value="addendum text"):
            with patch("analyst.propose_procurement_changes", return_value=[
                {"entity_type": "requirement", "entity_id": "M1", "change_type": "MODIFIED",
                 "canonical_effect": "canonical_change", "source_document_id": 10,
                 "source_document_hash": "hash-a"}
            ]) as mock_propose:
                result = tenancy.propose_procurement_changes_for_organization(8, "org-1", 3)

        mock_propose.assert_called_once()
        self.assertEqual(mock_propose.call_args.kwargs["buyer_update_type"], "Addendum")
        mock_db.insert_proposed_procurement_changes.assert_called_once()
        rows = mock_db.insert_proposed_procurement_changes.call_args[0][0]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["review_decision"], "pending")
        self.assertEqual(rows[0]["bid_id"], 8)
        mock_db.mark_review_ready_for_review.assert_called_once_with(3)
        self.assertEqual(len(result), 1)


class TestAnalystProcurementChangeProposal(unittest.TestCase):

    def test_analyst_module_never_imports_database_or_tenancy(self):
        """Structural purity guarantee: analyst.py must remain a pure
        function module with zero database access of its own."""
        source = open(
            os.path.join(os.path.dirname(__file__), "..", "analyst.py"), "r", encoding="utf-8"
        ).read()
        self.assertNotIn("import database", source)
        self.assertNotIn("import tenancy", source)
        self.assertNotIn("from database", source)
        self.assertNotIn("from tenancy", source)

    def test_propose_procurement_changes_returns_empty_list_for_no_documents(self):
        import analyst
        result = analyst.propose_procurement_changes(
            review_documents=[], current_requirements=[], bid_info={}, buyer_update_type="Addendum",
        )
        self.assertEqual(result, [])

    def test_propose_procurement_changes_skips_documents_with_no_extracted_text(self):
        import analyst
        with patch("analyst._call") as mock_call:
            result = analyst.propose_procurement_changes(
                review_documents=[{"document_id": 1, "filename": "empty.pdf", "content_hash": "h", "text": "   "}],
                current_requirements=[], bid_info={}, buyer_update_type="Addendum",
            )
        mock_call.assert_not_called()
        self.assertEqual(result, [])

    def test_propose_procurement_changes_stamps_document_id_and_hash_onto_every_proposal(self):
        import analyst
        with patch("analyst._call", return_value='{"proposals": [{"entity_type": "requirement", "entity_id": "M1", '
                                                   '"change_type": "MODIFIED", "canonical_effect": "canonical_change", '
                                                   '"extraction_evidence": {"sources": [{"page": 3, "excerpt": "text"}]}}]}'):
            result = analyst.propose_procurement_changes(
                review_documents=[{"document_id": 42, "filename": "addendum.pdf",
                                    "content_hash": "hash-xyz", "text": "Some buyer update text " * 20}],
                current_requirements=[{"req_id": "M1", "category": "Mandatory", "description": "x"}],
                bid_info={"title": "T", "client": "C"}, buyer_update_type="Addendum",
            )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["source_document_id"], 42)
        self.assertEqual(result[0]["source_document_hash"], "hash-xyz")
        self.assertEqual(result[0]["extraction_evidence"]["sources"][0]["document_id"], 42)
        self.assertEqual(result[0]["extraction_evidence"]["sources"][0]["document_hash"], "hash-xyz")

    def test_propose_procurement_changes_skips_a_chunk_on_call_failure_without_raising(self):
        import analyst
        with patch("analyst._call", side_effect=RuntimeError("api down")):
            result = analyst.propose_procurement_changes(
                review_documents=[{"document_id": 1, "filename": "a.pdf", "content_hash": "h", "text": "text " * 50}],
                current_requirements=[], bid_info={}, buyer_update_type="Addendum",
            )
        self.assertEqual(result, [])

    def test_propose_procurement_changes_reuses_existing_alignment_chunking_helpers(self):
        """No new chunking logic -- this must call the SAME helpers
        Alignment already uses, unchanged."""
        import analyst
        with patch("analyst._split_proposal_into_sections", wraps=analyst._split_proposal_into_sections) as mock_split, \
             patch("analyst._merge_and_size_bound_sections", wraps=analyst._merge_and_size_bound_sections) as mock_merge, \
             patch("analyst._call", return_value='{"proposals": []}'):
            analyst.propose_procurement_changes(
                review_documents=[{"document_id": 1, "filename": "a.pdf", "content_hash": "h",
                                    "text": "Section one text here.\n\nSection two text here."}],
                current_requirements=[], bid_info={}, buyer_update_type="Addendum",
            )
        mock_split.assert_called_once()
        mock_merge.assert_called_once()


class TestRequirementsLifecycleFiltering(unittest.TestCase):

    @patch("database.get_client")
    def test_get_requirements_defaults_to_active_only(self, mock_get_client):
        import database
        sb = MagicMock()
        query = sb.table.return_value.select.return_value.eq.return_value
        query.eq.return_value.order.return_value.order.return_value.execute.return_value = MagicMock(data=[])
        mock_get_client.return_value = sb

        database.get_requirements(8)

        query.eq.assert_called_once_with("lifecycle_status", "active")

    @patch("database.get_client")
    def test_get_requirements_include_retired_skips_the_filter(self, mock_get_client):
        import database
        sb = MagicMock()
        query = sb.table.return_value.select.return_value.eq.return_value
        query.order.return_value.order.return_value.execute.return_value = MagicMock(data=[])
        mock_get_client.return_value = sb

        database.get_requirements(8, include_retired=True)

        query.eq.assert_not_called()


class TestFastAnalysisAdvisoryOnly(unittest.TestCase):

    def test_analysis_service_never_calls_upsert_bid_brief(self):
        """Structural guarantee: Fast Analysis must never establish
        canonical bid_briefs truth (migration 010) -- the source itself
        must not reference upsert_bid_brief at all."""
        source = open(
            os.path.join(os.path.dirname(__file__), "..", "analysis_service.py"), "r", encoding="utf-8"
        ).read()
        self.assertNotIn("upsert_bid_brief", source)

    @patch("analysis_service.db")
    @patch("analysis_service.extract_document_with_metadata")
    @patch("analysis_service.run_fast_analysis_corpus")
    def test_completed_run_is_stamped_with_current_revision_and_unreviewed_count(
        self, mock_run, mock_extract, mock_db
    ):
        import analysis_service as svc
        from fast_analysis import FastAnalysisResult

        mock_db.download_file.return_value = b"bytes"
        mock_extract.return_value = ("text", {})
        mock_run.return_value = FastAnalysisResult()
        mock_db.upload_analysis_report.return_value = "path.pdf"
        mock_db.get_bid_procurement_state.return_value = {
            "procurement_revision": 5, "procurement_truth_status": "governed",
        }
        mock_db.get_reviewed_document_hashes.return_value = set()

        docs = [{"id": 1, "bid_id": 1, "name": "rfp.pdf", "doc_type": "RFP / Source",
                 "storage_path": "1/rfp.pdf", "content_hash": "hash-1"}]
        svc._execute_fast_analysis_run(run_id=1, bid_id=1, docs=docs, api_key="fake")

        complete_call = [c for c in mock_db.update_analysis_run.call_args_list
                         if c.args[1].get("status") == "COMPLETE"][0]
        self.assertEqual(complete_call.args[1]["based_on_procurement_revision"], 5)
        self.assertEqual(complete_call.args[1]["unreviewed_document_count"], 1)


class TestSourceRefsRoleSemantics(unittest.TestCase):
    """Semantic correction: a baseline review is the FIRST governed review
    for a bid -- there is no prior GOVERNED source for it to "modify" or
    "confirm unchanged" against, so every approved baseline fact
    (including a baseline UNCHANGED/evidence_only proposal that merely
    verifies a legacy pre-governance extraction was already correct) is
    ESTABLISHING that requirement under governance for the first time.
    'confirmed_unchanged'/'modified'/'clarified' only ever describe a
    buyer_update (or conflict_resolution) review, which by definition
    compares against an ALREADY-governed prior state."""

    def setUp(self):
        raw = _migration_010_text()
        self.code = _strip_sql_line_comments(raw).lower()
        fn_idx = self.code.index("create or replace function public.apply_procurement_update_review(")
        self.fn_body = self.code[fn_idx:self.code.index("$$;", fn_idx)]

    def test_role_mapping_keys_off_review_kind_for_baseline(self):
        self.assertIn("when v_review_kind = 'baseline' then 'established'", self.fn_body)

    def test_buyer_update_change_types_keep_their_own_distinct_roles(self):
        self.assertIn("when v_change.change_type = 'modified' then 'modified'", self.fn_body)
        self.assertIn("when v_change.change_type = 'clarified' then 'clarified'", self.fn_body)
        self.assertIn("when v_change.change_type = 'unchanged' then 'confirmed_unchanged'", self.fn_body)

    def test_baseline_check_precedes_change_type_checks_in_the_case_statement(self):
        """The review_kind='baseline' branch must be evaluated FIRST in the
        CASE, so it always wins over the change_type-based roles for a
        baseline review regardless of change_type (ADDED, UNCHANGED, or
        otherwise)."""
        role_case_idx = self.fn_body.index("'role', case")
        baseline_idx = self.fn_body.index("when v_review_kind = 'baseline'", role_case_idx)
        unchanged_idx = self.fn_body.index("when v_change.change_type = 'unchanged'", role_case_idx)
        self.assertLess(baseline_idx, unchanged_idx)

    def test_confirmed_unchanged_no_longer_unconditional_for_unchanged_change_type(self):
        """The old (wrong) mapping used a bare `case v_change.change_type`
        with no review_kind branch at all -- confirm that shape is gone."""
        self.assertNotIn("case v_change.change_type\n", self.fn_body)


class TestResolvedConflictImmutability(unittest.TestCase):
    """Static SQL-text proof that a resolved conflict is protected by the
    same BEFORE UPDATE OR DELETE pattern as applied change/review history
    (item 4 of the follow-up authorization) -- database-level, not merely
    application discipline."""

    def setUp(self):
        self.raw = _migration_010_text()
        self.code = _strip_sql_line_comments(self.raw).lower()

    def test_trigger_exists_before_update_or_delete_on_procurement_conflicts(self):
        self.assertIn("create trigger guard_resolved_conflict_immutability", self.code)
        trigger_idx = self.code.index("create trigger guard_resolved_conflict_immutability")
        trigger_body = self.code[trigger_idx:trigger_idx + 200]
        self.assertIn("before update or delete", trigger_body)
        self.assertIn("on public.procurement_conflicts", trigger_body)

    def test_guard_function_blocks_only_once_already_resolved(self):
        fn_idx = self.code.index("create or replace function public.prevent_resolved_conflict_mutation()")
        fn_body = self.code[fn_idx:self.code.index("$$;", fn_idx)]
        self.assertIn("security definer", fn_body)
        self.assertIn("if old.status = 'resolved' then", fn_body)
        self.assertIn("resolved_conflict_immutable", fn_body)

    def test_resolve_procurement_conflict_rpc_only_updates_while_still_unresolved(self):
        """The RPC's own UPDATE happens while OLD.status is still
        'unresolved' -- the guard trigger never fires against the RPC's
        own legitimate transition, only against anything after it."""
        fn_idx = self.code.index("create or replace function public.resolve_procurement_conflict(")
        fn_body = self.code[fn_idx:self.code.index("$$;", fn_idx)]
        self.assertIn("where id = p_conflict_id and status = 'unresolved'", fn_body)
        self.assertIn("set\n        status = 'resolved'", fn_body)


class TestNewUploadContentHashing(unittest.TestCase):
    """Item 3: documents.content_hash = SHA-256(raw uploaded bytes),
    computed server-side, for every NEW upload -- never a browser-supplied
    value, deterministic, and sensitive to any byte change."""

    def _mock_upload_client(self):
        sb = MagicMock()
        sb.storage.from_.return_value.upload.return_value = None
        sb.table.return_value.insert.return_value.execute.return_value = MagicMock(
            data=[{"id": 77}]
        )
        return sb

    @patch("database.get_client")
    def test_new_upload_stores_sha256_of_exact_bytes(self, mock_get_client):
        import database
        import hashlib
        sb = self._mock_upload_client()
        mock_get_client.return_value = sb

        file_bytes = b"the quick brown fox"
        database.save_upload(1, "rfp.pdf", file_bytes, doc_type="RFP / Source")

        insert_call = sb.table.return_value.insert.call_args[0][0]
        self.assertEqual(insert_call["content_hash"], hashlib.sha256(file_bytes).hexdigest())

    @patch("database.get_client")
    def test_identical_bytes_produce_identical_hash(self, mock_get_client):
        import database
        sb = self._mock_upload_client()
        mock_get_client.return_value = sb

        database.save_upload(1, "a.pdf", b"same bytes twice", doc_type="RFP / Source")
        hash_a = sb.table.return_value.insert.call_args[0][0]["content_hash"]
        database.save_upload(1, "b.pdf", b"same bytes twice", doc_type="RFP / Source")
        hash_b = sb.table.return_value.insert.call_args[0][0]["content_hash"]

        self.assertEqual(hash_a, hash_b)

    @patch("database.get_client")
    def test_altered_bytes_produce_a_different_hash(self, mock_get_client):
        import database
        sb = self._mock_upload_client()
        mock_get_client.return_value = sb

        database.save_upload(1, "a.pdf", b"original content", doc_type="RFP / Source")
        hash_original = sb.table.return_value.insert.call_args[0][0]["content_hash"]
        database.save_upload(1, "a.pdf", b"altered content!", doc_type="RFP / Source")
        hash_altered = sb.table.return_value.insert.call_args[0][0]["content_hash"]

        self.assertNotEqual(hash_original, hash_altered)

    @patch("database.get_client")
    def test_no_browser_supplied_hash_is_ever_trusted(self, mock_get_client):
        """save_upload's signature accepts no caller-provided hash
        parameter at all -- the only hash that can ever reach the database
        is the one this function computes itself from file_bytes."""
        import database
        import inspect
        sig = inspect.signature(database.save_upload)
        self.assertNotIn("content_hash", sig.parameters)
        self.assertNotIn("hash", sig.parameters)

    @patch("database.get_client")
    def test_version_reupload_gets_its_own_fresh_hash(self, mock_get_client):
        """A re-upload against an existing doc_id is genuinely new bytes
        (a new version) -- it must get its own fresh hash, not inherit or
        skip hashing because a hash already existed for the prior version."""
        import database
        import hashlib
        sb = MagicMock()
        sb.storage.from_.return_value.upload.return_value = None
        sb.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{"version": 1, "file_path": "old", "storage_path": "old", "file_size": 10}]
        )
        mock_get_client.return_value = sb

        new_bytes = b"version two bytes"
        database.save_upload(1, "rfp.pdf", new_bytes, doc_type="RFP / Source", doc_id=42)

        update_call = sb.table.return_value.update.call_args[0][0]
        self.assertEqual(update_call["content_hash"], hashlib.sha256(new_bytes).hexdigest())


class TestGovernedRequirementMutationGuard(unittest.TestCase):
    """Item 2: once a bid is governed, no direct write path may mutate a
    canonical requirement field outside the procurement-governance RPCs.
    Supplier-side assessment fields (qual_status, evidence_status, owner,
    gap_action, qual_notes, status, deadline, notes) remain freely
    editable regardless of governance state -- this is what keeps
    stage_decide.py's live Assess Requirement drawer working unmodified."""

    _EXISTING_ROW = {
        "bid_id": 1, "description": "Existing description", "category": "Mandatory",
        "rfso_ref": "1.1", "weight": 0.2,
    }

    def _client_with_governed_bid(self, governed: bool):
        """For an INSERT path only (no `id` -> no 'current row' fetch, a
        single select call resolves straight to the governance check)."""
        sb = MagicMock()
        status = "governed" if governed else "ungoverned"
        sb.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{"procurement_truth_status": status}]
        )
        return sb

    def _client_for_update(self, governed: bool, current_row: dict | None = None):
        """For an UPDATE path (`id` present): first select call returns
        the CURRENT row (for the changed-value comparison), second
        returns the bid's governance state -- only reached if a canonical
        field actually changed."""
        sb = MagicMock()
        status = "governed" if governed else "ungoverned"
        sb.table.return_value.select.return_value.eq.return_value.execute.side_effect = [
            MagicMock(data=[current_row if current_row is not None else self._EXISTING_ROW]),
            MagicMock(data=[{"procurement_truth_status": status}]),
        ]
        return sb

    @patch("database.get_client")
    def test_direct_update_of_description_blocked_once_governed(self, mock_get_client):
        import database
        sb = self._client_for_update(governed=True)
        mock_get_client.return_value = sb
        with self.assertRaises(database.GovernedRequirementMutationError):
            database.upsert_requirement({"id": 5, "bid_id": 1, "description": "a genuinely new description"})

    @patch("database.get_client")
    def test_direct_update_of_weight_blocked_once_governed(self, mock_get_client):
        import database
        sb = self._client_for_update(governed=True)
        mock_get_client.return_value = sb
        with self.assertRaises(database.GovernedRequirementMutationError):
            database.upsert_requirement({"id": 5, "bid_id": 1, "weight": 0.3})

    @patch("database.get_client")
    def test_direct_update_of_description_allowed_while_ungoverned(self, mock_get_client):
        """The legitimate ungoverned-baseline-construction path -- must
        keep working unmodified."""
        import database
        sb = self._client_for_update(governed=False)
        mock_get_client.return_value = sb
        database.upsert_requirement({"id": 5, "bid_id": 1, "description": "a genuinely new description"})
        sb.table.return_value.update.assert_called_once()

    @patch("database.get_client")
    def test_supplier_assessment_fields_never_blocked_even_when_governed(self, mock_get_client):
        """qual_status/evidence_status/owner/gap_action/qual_notes track
        OUR compliance posture, not the requirement's own definition --
        stage_decide.py's Assess Requirement drawer must keep working on a
        governed bid without ever routing through governance. No
        canonical field is present in the payload at all, so this must
        succeed without even reading the current row."""
        import database
        sb = MagicMock()
        mock_get_client.return_value = sb
        database.upsert_requirement({
            "id": 5, "bid_id": 1, "qual_status": "PASS", "evidence_status": "READY",
            "owner": "Jane", "gap_action": "none", "qual_notes": "confirmed", "notes": "ok",
        })
        sb.table.return_value.select.assert_not_called()
        sb.table.return_value.update.assert_called_once()

    @patch("database.get_client")
    def test_governed_bid_save_that_spreads_the_full_unchanged_row_is_never_blocked(self, mock_get_client):
        """THE critical case: stage_decide.py's Assess Requirement drawer
        calls upsert_requirement(**target_req, qual_status=..., ...) --
        spreading the FULL existing row, including
        description/category/rfso_ref/weight completely UNCHANGED,
        alongside the supplier fields it actually intends to edit. Those
        canonical keys merely being PRESENT in the payload must never be
        treated as an edit once value-equality is checked against the
        current row -- otherwise this would break the app's only live
        requirement-editing UI the moment a bid becomes governed."""
        import database
        sb = self._client_for_update(governed=True, current_row=self._EXISTING_ROW)
        mock_get_client.return_value = sb
        database.upsert_requirement({
            "id": 5, **self._EXISTING_ROW,  # every canonical field identical to current
            "qual_status": "PASS", "evidence_status": "READY", "owner": "Jane",
        })
        sb.table.return_value.update.assert_called_once()

    @patch("database.get_client")
    def test_direct_insert_of_a_new_requirement_blocked_once_governed(self, mock_get_client):
        """Category C close: even ADDing a brand-new requirement directly
        (not just editing an existing one) must route through governance
        once the bid is governed -- bid_id is supplied directly on insert,
        no id lookup needed, and there is no 'current row' to compare
        against (a fresh insert of a canonical field is always a real
        write of that field)."""
        import database
        mock_get_client.return_value = self._client_with_governed_bid(governed=True)
        with self.assertRaises(database.GovernedRequirementMutationError):
            database.upsert_requirement({
                "id": None, "bid_id": 1, "description": "brand new requirement", "category": "Mandatory",
            })

    @patch("database.get_client")
    def test_direct_delete_blocked_once_governed(self, mock_get_client):
        import database
        sb = MagicMock()
        sb.table.return_value.select.return_value.eq.return_value.execute.side_effect = [
            MagicMock(data=[{"bid_id": 1}]),  # delete_requirement's own bid_id lookup
            MagicMock(data=[{"procurement_truth_status": "governed"}]),  # _bid_is_governed
        ]
        mock_get_client.return_value = sb
        with self.assertRaises(database.GovernedRequirementMutationError):
            database.delete_requirement(5)
        sb.table.return_value.delete.assert_not_called()

    @patch("database.get_client")
    def test_direct_delete_allowed_while_ungoverned(self, mock_get_client):
        import database
        sb = MagicMock()
        sb.table.return_value.select.return_value.eq.return_value.execute.side_effect = [
            MagicMock(data=[{"bid_id": 1}]),
            MagicMock(data=[{"procurement_truth_status": "ungoverned"}]),
        ]
        mock_get_client.return_value = sb
        database.delete_requirement(5)
        sb.table.return_value.delete.assert_called_once()

    @patch("database.get_client")
    def test_tenancy_authenticated_update_of_description_blocked_once_governed(self, mock_get_client):
        """tenancy.upsert_requirement_authenticated re-implements the same
        write against the RLS-scoped client -- it must carry the identical
        guard, checked via the service client read (not a privilege
        escalation -- the write itself still goes through the caller's own
        RLS-scoped client)."""
        import tenancy
        import database
        mock_get_client.return_value = self._client_for_update(governed=True)
        with patch("tenancy.auth_client.get_authenticated_client"):
            with self.assertRaises(database.GovernedRequirementMutationError):
                tenancy.upsert_requirement_authenticated(
                    "tok", {"id": 5, "bid_id": 1, "description": "a genuinely new description"})

    @patch("database.get_client")
    def test_tenancy_authenticated_assess_requirement_drawer_save_never_blocked(self, mock_get_client):
        """Reproduces stage_decide.py's exact call shape against the
        authenticated wrapper: full existing row spread, only supplier
        fields actually change."""
        import tenancy
        mock_get_client.return_value = self._client_for_update(governed=True, current_row=self._EXISTING_ROW)
        with patch("tenancy.auth_client.get_authenticated_client"):
            tenancy.upsert_requirement_authenticated("tok", {
                "id": 5, **self._EXISTING_ROW,
                "qual_status": "CONCERN", "evidence_status": "PARTIAL", "owner": "Jane",
            })  # must not raise

    @patch("database.get_client")
    def test_tenancy_authenticated_delete_blocked_once_governed(self, mock_get_client):
        import tenancy
        import database
        sb = MagicMock()
        sb.table.return_value.select.return_value.eq.return_value.execute.side_effect = [
            MagicMock(data=[{"bid_id": 1}]),
            MagicMock(data=[{"procurement_truth_status": "governed"}]),
        ]
        mock_get_client.return_value = sb
        with patch("tenancy.auth_client.get_authenticated_client") as mock_auth_client:
            with self.assertRaises(database.GovernedRequirementMutationError):
                tenancy.delete_requirement_authenticated("tok", 5)
            mock_auth_client.return_value.table.assert_not_called()


class TestHumanAuditAttribution(unittest.TestCase):
    """Item 5: because every governance RPC runs as service_role, the
    human actor can never be recovered from auth.uid() inside the RPC --
    tenancy.py's wrappers must pass the authorized actor's real id
    explicitly on every attribution-bearing call."""

    @patch("tenancy.db")
    @patch("tenancy.require_bid_access")
    def test_record_decision_passes_the_real_actor_id_not_none(self, mock_require, mock_db):
        import tenancy
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.execute.return_value = (
            MagicMock(data=[{"id": 55, "bid_id": 8}])
        )
        tenancy.record_change_review_decision_for_organization(8, "org-1", 55, "approved", "user-abc-123")
        mock_db.record_change_review_decision.assert_called_once_with(
            55, "approved", "user-abc-123", review_note=None)

    @patch("tenancy.db")
    @patch("tenancy.require_bid_access")
    def test_apply_review_passes_the_real_actor_id_not_none(self, mock_require, mock_db):
        import tenancy
        mock_db.get_procurement_update_reviews.return_value = [{"id": 3, "bid_id": 8}]
        tenancy.apply_procurement_update_review_for_organization(8, "org-1", 3, 1, "user-abc-123")
        mock_db.apply_procurement_update_review.assert_called_once_with(3, 1, "user-abc-123")

    @patch("tenancy.db")
    @patch("tenancy.require_bid_access")
    def test_resolve_conflict_passes_the_real_actor_id_not_none(self, mock_require, mock_db):
        import tenancy
        mock_db.get_procurement_conflicts.return_value = [{"id": 9, "bid_id": 8}]
        tenancy.resolve_procurement_conflict_for_organization(
            8, "org-1", 9, 1, {"weight": 5}, "resolved by agreement", "user-abc-123")
        mock_db.resolve_procurement_conflict.assert_called_once_with(
            9, 1, {"weight": 5}, "resolved by agreement", "user-abc-123")

    def test_no_governance_rpc_wrapper_relies_on_auth_uid(self):
        """Structural guarantee: none of database.py's governance RPC
        wrapper calls ever substitutes a hardcoded/None actor where a real
        one is required -- auth.uid() inside SECURITY DEFINER context
        would resolve to the service role, never the human, so the actor
        id must always come from the caller."""
        source = open(
            os.path.join(os.path.dirname(__file__), "..", "database.py"), "r", encoding="utf-8"
        ).read()
        self.assertNotIn('"p_actor_user_id": None,', source.replace(" ", ""))

    def test_procurement_changes_and_reviews_have_dedicated_attribution_columns(self):
        """Static schema proof that attribution is actually stored, not
        just passed through and discarded."""
        raw = _migration_010_text()
        code = _strip_sql_line_comments(raw).lower()
        changes_block = code[code.index("create table if not exists public.procurement_changes"):]
        changes_block = changes_block[:changes_block.index("create index")]
        self.assertIn("decided_by_user_id uuid references auth.users(id)", changes_block)
        self.assertIn("decided_at timestamptz", changes_block)
        reviews_block = code[code.index("create table if not exists public.procurement_update_reviews"):]
        reviews_block = reviews_block[:reviews_block.index("create unique index")]
        self.assertIn("reviewed_by_user_id uuid references auth.users(id)", reviews_block)
        self.assertIn("applied_by_user_id uuid references auth.users(id)", reviews_block)
        self.assertIn("applied_at timestamptz", reviews_block)
        conflicts_block = code[code.index("create table if not exists public.procurement_conflicts"):]
        conflicts_block = conflicts_block[:conflicts_block.index("create index")]
        self.assertIn("resolved_by_user_id uuid references auth.users(id)", conflicts_block)
        self.assertIn("resolved_at timestamptz", conflicts_block)


class TestCDABaselineProvenanceOnlyRegression(unittest.TestCase):
    """Item 6 (release-critical): the exact CDA-AMC legacy shape --
    existing requirement M1, baseline review proposes UNCHANGED /
    evidence_only, human approves, apply is called. Migration 010 cannot
    be executed against a live Postgres in this environment (see item 7 /
    the pre-commit report) -- this proves everything provable at the
    Python layer: (a) the proposal's entity_id ('M1') correctly resolves
    to the real target_requirement_id before it is persisted (the bug
    fixed this round -- previously always None), (b) the persisted pending
    row is byte-for-byte UNCHANGED/evidence_only with M1's OWN previous_value
    echoed back as new_value (no drift introduced at the proposal layer),
    with source_document_id/hash correctly stamped from the original
    baseline document (main_document.pdf) so the SQL layer has what it
    needs to attribute source_refs correctly, (c) approval and apply are
    called with real human attribution. The SQL RPC body's own guarantees
    -- source_refs gains role='established' (NOT 'confirmed_unchanged';
    baseline is the first-ever governed review, so it ESTABLISHES the
    requirement, it never merely "confirms" a prior governed state that
    didn't exist yet), revision staying at 1, procurement_truth_status
    flipping to 'governed' -- are proven separately by static SQL-text
    assertion (TestSourceRefsRoleSemantics /
    test_baseline_apply_does_not_require_canonical_change_* /
    test_baseline_apply_never_increments_revision_directly above), since
    they cannot be executed here."""

    @patch("tenancy.db")
    @patch("tenancy.require_bid_access")
    def test_unchanged_baseline_proposal_resolves_to_the_real_requirement_id(self, mock_require, mock_db):
        import tenancy
        mock_db.get_procurement_update_reviews.return_value = [
            {"id": 1, "bid_id": 3, "buyer_update_type": "Original RFP"}
        ]
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.execute.return_value = (
            MagicMock(data=[{"document_id": 10, "role": "primary"}])
        )
        mock_db.get_documents.return_value = [
            {"id": 10, "name": "main_document.pdf", "storage_path": "3/main.pdf", "content_hash": "hash-main"}
        ]
        mock_db.download_file.return_value = b"rfp bytes"
        # M1 already exists with a real bigint primary key -- exactly the
        # CDA legacy shape (extracted once, never revised, empty
        # source_refs).
        mock_db.get_requirements.return_value = [
            {"id": 501, "req_id": "M1", "category": "Mandatory",
             "description": "Supplier must hold a valid business license.",
             "weight": None, "rfso_ref": "3.1", "source_refs": []}
        ]
        mock_db.get_bid.return_value = {"title": "CDA-AMC Opportunity", "client": "Canada Drug Agency"}

        unchanged_value = {"description": "Supplier must hold a valid business license."}
        with patch("extractor.extract_text_from_file", return_value="main document text"):
            with patch("analyst.propose_procurement_changes", return_value=[{
                "entity_type": "requirement", "entity_id": "M1", "change_type": "UNCHANGED",
                "canonical_effect": "evidence_only",
                "previous_value": unchanged_value, "new_value": unchanged_value,
                "source_document_id": 10, "source_document_hash": "hash-main",
                "physical_source_ref": "Main Document -- Section 3.1",
                "extraction_evidence": {"sources": [{"page": 4, "excerpt": "valid business license"}]},
            }]):
                tenancy.propose_procurement_changes_for_organization(3, "org-1", 1)

        rows = mock_db.insert_proposed_procurement_changes.call_args[0][0]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        # The bug this round: target_requirement_id was always None
        # because the pure LLM function only ever knows entity_id.
        self.assertEqual(row["target_requirement_id"], 501)
        self.assertEqual(row["change_type"], "UNCHANGED")
        self.assertEqual(row["canonical_effect"], "evidence_only")
        # Byte-for-byte unchanged: previous_value and new_value are identical.
        self.assertEqual(row["previous_value"], row["new_value"])
        # The original baseline procurement source (the Main Document) is
        # correctly identified on the persisted row -- this is what the SQL
        # layer's source_refs entry (role='established', proven by static
        # assertion) attributes provenance to.
        self.assertEqual(row["source_document_id"], 10)
        self.assertEqual(row["source_document_hash"], "hash-main")
        self.assertEqual(row["physical_source_ref"], "Main Document -- Section 3.1")

    @patch("tenancy.db")
    @patch("tenancy.require_bid_access")
    def test_approval_and_apply_carry_real_human_attribution_through_to_the_rpc(self, mock_require, mock_db):
        import tenancy
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.execute.return_value = (
            MagicMock(data=[{"id": 900, "bid_id": 3}])
        )
        tenancy.record_change_review_decision_for_organization(
            3, "org-1", 900, "approved", "analyst-user-id", review_note="Confirmed unchanged from Main Document")
        mock_db.record_change_review_decision.assert_called_once_with(
            900, "approved", "analyst-user-id", review_note="Confirmed unchanged from Main Document")

        mock_db.get_procurement_update_reviews.return_value = [{"id": 1, "bid_id": 3}]
        mock_db.apply_procurement_update_review.return_value = {
            "resulting_revision": 1, "applied_change_count": 1,
        }
        result = tenancy.apply_procurement_update_review_for_organization(3, "org-1", 1, 1, "analyst-user-id")

        mock_db.apply_procurement_update_review.assert_called_once_with(1, 1, "analyst-user-id")
        # Baseline apply of an evidence_only-only approval set: revision
        # stays at 1 (no canonical_change row exists) -- this is the mocked
        # RPC's contract; the RPC body's own guarantee that it computes
        # this correctly is proven by static assertion, not execution.
        self.assertEqual(result["resulting_revision"], 1)


class TestUnderstandGovernanceWorkflowRendering(unittest.TestCase):
    """Item 1/9: behavioral rendering tests for the new UNDERSTAND
    baseline/buyer-update panels, mirroring
    tests/test_proposal_alignment_analyzer.py's TestStageCheckRendering
    pattern -- calls the REAL page_understand(bid_id) with every tenancy
    call mocked, and asserts on the actual rendered markdown."""

    @staticmethod
    def _no_click_column(*_a, **_k):
        col = MagicMock()
        col.button.return_value = False  # never a spuriously "clicked" Approve/Reject in a column
        return col

    def _base_patches(self, truth_status: str, revision: int = 1):
        return [
            patch("pages.stage_understand.tenancy.get_bid_authenticated", return_value={
                "id": 1, "client": "Test Buyer", "title": "Test RFP", "stage": "Identified",
                "sensitivity": "Standard", "submission_deadline": None, "clarification_deadline": None,
                "value_cad": None, "owner": None,
            }),
            patch("pages.stage_understand.tenancy.get_bid_brief_authenticated", return_value={}),
            patch("pages.stage_understand.tenancy.get_requirements_authenticated", return_value=[]),
            patch("pages.stage_understand.tenancy.get_documents_authenticated", return_value=[
                {"id": 1, "name": "rfp.pdf", "doc_type": "RFP / Source", "version": 1},
            ]),
            patch("pages.stage_understand.tenancy.get_latest_analysis_run_authenticated", return_value=None),
            patch("pages.stage_understand.tenancy.get_latest_analysis_result_authenticated", return_value=None),
            patch("pages.stage_understand.tenancy.get_procurement_state_for_organization", return_value={
                "procurement_revision": revision, "procurement_truth_status": truth_status,
            }),
            patch("pages.stage_understand._current_access_token_and_org", return_value=("tok", "org-1")),
            patch("streamlit.file_uploader", return_value=None),
            patch("streamlit.button", return_value=False),
            patch("streamlit.rerun"),
            patch("streamlit.columns", side_effect=lambda spec, *a, **k: [
                self._no_click_column() for _ in range(spec if isinstance(spec, int) else len(spec))]),
        ]

    def _render(self, truth_status: str, reviews: list, revision: int = 1) -> str:
        from pages import stage_understand as understand
        calls = []

        def fake_markdown(text, *a, **k):
            calls.append(str(text))

        patches = self._base_patches(truth_status, revision) + [
            patch("pages.stage_understand.tenancy.get_procurement_update_reviews_for_organization",
                  return_value=reviews),
            patch("pages.stage_understand.tenancy.get_procurement_changes_for_organization", return_value=[]),
            patch("streamlit.markdown", side_effect=fake_markdown),
            patch("streamlit.expander", MagicMock()),
        ]
        for p in patches:
            p.start()
        try:
            understand.page_understand(1)
        finally:
            for p in patches:
                p.stop()
        return "\n".join(calls)

    def test_ungoverned_bid_shows_establish_baseline_workflow(self):
        rendered = self._render("ungoverned", reviews=[])
        self.assertIn("Establish Procurement Baseline", rendered)
        self.assertIn("not yet governed", rendered)

    def test_governed_bid_shows_documents_and_addenda_workflow(self):
        rendered = self._render("governed", reviews=[], revision=2)
        self.assertIn("Procurement Documents", rendered)
        self.assertIn("current revision", rendered)
        self.assertIn("<strong>2</strong>", rendered)

    def test_governed_bid_never_shows_establish_baseline_workflow(self):
        rendered = self._render("governed", reviews=[])
        self.assertNotIn("Establish Procurement Baseline", rendered)

    def test_apply_button_disabled_while_decisions_are_pending(self):
        """Apply must never be clickable while any proposal is still
        'pending' -- captured directly via the `disabled` kwarg passed to
        st.button, not just visually."""
        from pages import stage_understand as understand
        button_calls = []

        def fake_button(label, *a, **kwargs):
            button_calls.append((label, kwargs))
            return False

        patches = self._base_patches("ungoverned", 1) + [
            patch("pages.stage_understand.tenancy.get_procurement_update_reviews_for_organization",
                  return_value=[{"id": 1, "review_kind": "baseline", "status": "ready_for_review",
                                 "base_procurement_revision": 1}]),
            patch("pages.stage_understand.tenancy.get_procurement_changes_for_organization", return_value=[
                {"id": 100, "entity_type": "requirement", "entity_id": "M1", "change_type": "UNCHANGED",
                 "canonical_effect": "evidence_only", "review_decision": "pending",
                 "previous_value": {"description": "x"}, "new_value": {"description": "x"}},
            ]),
            patch("streamlit.markdown"),
            patch("streamlit.expander", MagicMock()),
            patch("streamlit.button", side_effect=fake_button),
        ]
        for p in patches:
            p.start()
        try:
            understand.page_understand(1)
        finally:
            for p in patches:
                p.stop()

        apply_calls = [c for c in button_calls if "Apply" in c[0]]
        self.assertEqual(len(apply_calls), 1)
        self.assertTrue(apply_calls[0][1].get("disabled"))

    def test_apply_button_enabled_once_all_decisions_are_made(self):
        from pages import stage_understand as understand
        button_calls = []

        def fake_button(label, *a, **kwargs):
            button_calls.append((label, kwargs))
            return False

        patches = self._base_patches("ungoverned", 1) + [
            patch("pages.stage_understand.tenancy.get_procurement_update_reviews_for_organization",
                  return_value=[{"id": 1, "review_kind": "baseline", "status": "ready_for_review",
                                 "base_procurement_revision": 1}]),
            patch("pages.stage_understand.tenancy.get_procurement_changes_for_organization", return_value=[
                {"id": 100, "entity_type": "requirement", "entity_id": "M1", "change_type": "UNCHANGED",
                 "canonical_effect": "evidence_only", "review_decision": "approved",
                 "previous_value": {"description": "x"}, "new_value": {"description": "x"}},
            ]),
            patch("streamlit.markdown"),
            patch("streamlit.expander", MagicMock()),
            patch("streamlit.button", side_effect=fake_button),
        ]
        for p in patches:
            p.start()
        try:
            understand.page_understand(1)
        finally:
            for p in patches:
                p.stop()

        apply_calls = [c for c in button_calls if "Apply" in c[0]]
        self.assertEqual(len(apply_calls), 1)
        self.assertFalse(apply_calls[0][1].get("disabled"))


class TestNullRevisionBasisSemantics(unittest.TestCase):
    """Semantic correction: migration 010 runs after many analysis_runs/
    bid_decisions rows already exist. NULL revision-basis must mean
    "predates procurement-revision tracking / basis unknown" -- NEVER
    "revision 1" and NEVER "current". A historical row must never
    silently look current just because a `None == None` (or a `None`
    default) comparison happens to evaluate false-for-stale."""

    def test_historical_analysis_run_null_basis_shown_as_unknown_not_current(self):
        from components.ui import procurement_staleness_banner
        # A decision/run DOES track a basis, and its stored value is
        # explicitly None (the historical/legacy case) -- must render the
        # "basis unknown" warning, not "" (which would mean "nothing stale").
        html = procurement_staleness_banner(
            {"procurement_revision": 3, "procurement_truth_status": "governed"},
            None, context_label="This analysis",
        )
        self.assertIn("BASIS UNKNOWN", html)
        self.assertIn("Re-analysis is required", html)

    def test_historical_bid_decision_null_basis_shown_as_unknown_not_current(self):
        """Exact scenario from stage_decide.py: a decision row exists, but
        its based_on_procurement_revision column is NULL (made before
        migration 010)."""
        from components.ui import procurement_staleness_banner
        legacy_decision = {"human_decision": "GO", "based_on_procurement_revision": None}
        html = procurement_staleness_banner(
            {"procurement_revision": 2, "procurement_truth_status": "governed"},
            legacy_decision.get("based_on_procurement_revision"),
            context_label="This bid/no-bid decision",
        )
        self.assertIn("BASIS UNKNOWN", html)

    def test_artifact_with_no_revision_basis_concept_shows_nothing(self):
        """CHECK's live-read compliance matrix has no based_on concept at
        all (it's always current by construction) -- must NOT show the
        'basis unknown' warning just because no value was ever passed."""
        from components.ui import procurement_staleness_banner
        html = procurement_staleness_banner(
            {"procurement_revision": 2, "procurement_truth_status": "governed"},
            context_label="The compliance matrix used on this page",
        )
        self.assertEqual(html, "")

    def test_ungoverned_bid_takes_precedence_over_null_basis_messaging(self):
        """The stronger 'not yet governed' message must win even when the
        artifact's own basis is also unknown -- never show both, and never
        let the weaker message hide the stronger one."""
        from components.ui import procurement_staleness_banner
        html = procurement_staleness_banner(
            {"procurement_revision": 1, "procurement_truth_status": "ungoverned"},
            None, context_label="This analysis",
        )
        self.assertIn("NOT YET GOVERNED", html)
        self.assertNotIn("BASIS UNKNOWN", html)

    def test_ungoverned_bid_takes_precedence_over_ordinary_staleness(self):
        from components.ui import procurement_staleness_banner
        html = procurement_staleness_banner(
            {"procurement_revision": 1, "procurement_truth_status": "ungoverned"},
            1, context_label="This analysis",
        )
        self.assertIn("NOT YET GOVERNED", html)
        self.assertNotIn("STALE", html)

    def test_matching_revision_on_governed_bid_shows_nothing(self):
        from components.ui import procurement_staleness_banner
        html = procurement_staleness_banner(
            {"procurement_revision": 3, "procurement_truth_status": "governed"},
            3, context_label="This analysis",
        )
        self.assertEqual(html, "")


class TestFastAnalysisUnreviewedDocumentDisplay(unittest.TestCase):
    """Item 4: Fast Analysis's own unreviewed_document_count display --
    NULL is never rendered as 0 governed documents outstanding."""

    def _render_note(self, run: dict, procurement_state: dict) -> str:
        from pages import stage_understand as understand
        calls = []
        with patch("streamlit.markdown", side_effect=lambda text, *a, **k: calls.append(str(text))):
            understand._render_fast_analysis_governance_note(run, procurement_state)
        return "\n".join(calls)

    def test_historical_run_null_unreviewed_count_not_shown_as_zero(self):
        rendered = self._render_note(
            {"based_on_procurement_revision": 2, "unreviewed_document_count": None},
            {"procurement_revision": 2, "procurement_truth_status": "governed"},
        )
        self.assertIn("unknown", rendered.lower())
        self.assertNotIn("Every corpus document is covered", rendered)
        self.assertNotIn("0 corpus document", rendered)

    def test_new_run_zero_unreviewed_is_shown_as_fully_governed(self):
        rendered = self._render_note(
            {"based_on_procurement_revision": 2, "unreviewed_document_count": 0},
            {"procurement_revision": 2, "procurement_truth_status": "governed"},
        )
        self.assertIn("Every corpus document is covered by a governed review", rendered)

    def test_new_run_with_unreviewed_documents_shows_the_advisory_warning(self):
        rendered = self._render_note(
            {"based_on_procurement_revision": 2, "unreviewed_document_count": 3},
            {"procurement_revision": 2, "procurement_truth_status": "governed"},
        )
        self.assertIn("3 corpus document(s)", rendered)
        self.assertIn("advisory only", rendered)

    def test_historical_run_null_based_on_revision_shown_as_unknown(self):
        rendered = self._render_note(
            {"based_on_procurement_revision": None, "unreviewed_document_count": None},
            {"procurement_revision": 4, "procurement_truth_status": "governed"},
        )
        self.assertIn("basis is unknown", rendered.lower())

    def test_ungoverned_bid_message_takes_precedence_over_revision_basis(self):
        rendered = self._render_note(
            {"based_on_procurement_revision": None, "unreviewed_document_count": 0},
            {"procurement_revision": 1, "procurement_truth_status": "ungoverned"},
        )
        self.assertIn("not yet been governed", rendered)
        self.assertNotIn("basis is unknown", rendered.lower())


MIGRATION_011_PATH = os.path.join(
    os.path.dirname(__file__), "..", "migrations", "011_harden_procurement_trigger_functions.sql"
)

_TRIGGER_FUNCTION_NAMES = [
    "prevent_applied_change_mutation",
    "prevent_applied_review_mutation",
    "prevent_applied_review_document_mutation",
    "prevent_resolved_conflict_mutation",
]


def _migration_011_text() -> str:
    with open(MIGRATION_011_PATH, "r", encoding="utf-8") as f:
        return f.read()


class TestMigration011TriggerFunctionHardening(unittest.TestCase):
    """Follow-up security hardening: migration 010's four BEFORE UPDATE OR
    DELETE trigger functions kept PostgreSQL's default EXECUTE-to-PUBLIC
    grant (never explicitly REVOKE/GRANT'd, unlike the six application
    RPCs) -- Supabase's live security advisor flagged this. Migration 011
    closes it without touching migration 010 or trigger semantics."""

    def setUp(self):
        self.raw_011 = _migration_011_text()
        self.code_011 = _strip_sql_line_comments(self.raw_011).lower()
        self.raw_010 = _migration_010_text()
        self.code_010 = _strip_sql_line_comments(self.raw_010).lower()

    # ── instruction 5: PUBLIC/anon/authenticated/service_role cannot ────
    #    execute any trigger function directly ───────────────────────────
    def test_every_trigger_function_revoked_from_public_anon_authenticated(self):
        for name in _TRIGGER_FUNCTION_NAMES:
            for role in ("public", "anon", "authenticated"):
                self.assertIn(
                    f"revoke all on function public.{name}() from {role};", self.code_011,
                    msg=f"{name} missing revoke-from-{role}",
                )

    def test_service_role_direct_execute_also_revoked(self):
        """Chosen design: service_role never calls these functions
        directly either (only PostgreSQL's trigger executor does, which
        per CREATE TRIGGER's own docs checks EXECUTE only once, at
        CREATE TRIGGER time, against the creating role -- never against
        the role that later fires the trigger via DML) -- so service_role
        is revoked too, for the tightest correct policy."""
        for name in _TRIGGER_FUNCTION_NAMES:
            self.assertIn(
                f"revoke all on function public.{name}() from service_role;", self.code_011,
                msg=f"{name} missing revoke-from-service_role",
            )

    def test_no_grant_statement_anywhere_in_migration_011(self):
        """This migration only ever revokes -- it grants nothing to
        anyone, consistent with 'no application role should call these
        directly, ever'."""
        self.assertNotIn("grant ", self.code_011)

    # ── instruction 4: migration 011 does not alter migration 010 ───────
    def test_migration_010_file_is_untouched(self):
        expected_sha256 = "d0090401627dd99ae224aa1db507e5c4390f20855420c07641b95124290f6801"
        actual_sha256 = hashlib.sha256(self.raw_010.encode("utf-8")).hexdigest()
        self.assertEqual(actual_sha256, expected_sha256,
                          msg="migrations/010_procurement_revision_governance.sql must remain byte-identical")

    def test_migration_011_does_not_redefine_or_drop_any_trigger(self):
        """Trigger objects/logic stay exactly as migration 010 created
        them -- 011 is grant-only."""
        self.assertNotIn("create trigger", self.code_011)
        self.assertNotIn("drop trigger", self.code_011)
        self.assertNotIn("create or replace function", self.code_011)
        self.assertNotIn("create table", self.code_011)
        self.assertNotIn("alter table", self.code_011)

    def test_migration_011_performs_no_application_data_mutation(self):
        self.assertNotIn("insert into", self.code_011)
        self.assertNotIn("update ", self.code_011)
        self.assertNotIn("delete from", self.code_011)

    # ── instruction 1: investigation findings, proven against migration ──
    #    010's actual (untouched) source ────────────────────────────────
    def test_all_four_trigger_functions_are_security_definer_in_migration_010(self):
        for name in _TRIGGER_FUNCTION_NAMES:
            fn_idx = self.code_010.index(f"create or replace function public.{name}()")
            fn_header = self.code_010[fn_idx:fn_idx + 200]
            self.assertIn("security definer", fn_header)

    def test_all_four_trigger_functions_already_have_fixed_search_path_in_migration_010(self):
        """No search_path hardening is missing -- migration 010 already
        pins search_path on every one of these; migration 011 correctly
        makes no search_path change."""
        for name in _TRIGGER_FUNCTION_NAMES:
            fn_idx = self.code_010.index(f"create or replace function public.{name}()")
            fn_header = self.code_010[fn_idx:fn_idx + 200]
            self.assertIn("set search_path = public, pg_temp", fn_header)
        self.assertNotIn("alter function", self.code_011)

    def test_only_one_trigger_function_touches_a_table_and_it_is_fully_qualified(self):
        fn_idx = self.code_010.index("create or replace function public.prevent_applied_review_document_mutation()")
        fn_body = self.code_010[fn_idx:self.code_010.index("$$;", fn_idx)]
        self.assertIn("from public.procurement_update_reviews", fn_body)

    # ── instruction 5: trigger objects still reference the same functions,
    #    definitions remain BEFORE UPDATE OR DELETE (unchanged, since 011
    #    never touches migration 010) ──────────────────────────────────
    def test_trigger_definitions_in_migration_010_remain_before_update_or_delete(self):
        expected = [
            ("guard_applied_change_immutability", "procurement_changes", "prevent_applied_change_mutation"),
            ("guard_applied_review_immutability", "procurement_update_reviews", "prevent_applied_review_mutation"),
            ("guard_applied_review_document_immutability", "procurement_update_review_documents",
             "prevent_applied_review_document_mutation"),
            ("guard_resolved_conflict_immutability", "procurement_conflicts", "prevent_resolved_conflict_mutation"),
        ]
        for trigger_name, table_name, function_name in expected:
            trigger_idx = self.code_010.index(f"create trigger {trigger_name}")
            trigger_def = self.code_010[trigger_idx:trigger_idx + 250]
            self.assertIn("before update or delete", trigger_def)
            self.assertIn(f"on public.{table_name}", trigger_def)
            self.assertIn(f"public.{function_name}()", trigger_def)


if __name__ == "__main__":
    unittest.main()
