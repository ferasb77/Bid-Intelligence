"""
tests/test_section_drafts_persistence.py

RETIRED: this file exercised PI-3B's "analyze once, draft once, persist,
reuse" orchestration (tenancy.get_or_generate_section_draft on top of
migrations/018_section_drafts.sql's get_or_create_section_draft RPC). Both
were DECOMMISSIONED along with the rest of active AI proposal generation --
Bid Intelligence no longer generates proposal narrative, so there is no
generate-and-persist path left to exercise.

What was reusable in this suite -- fail-closed evidence/claim reconciliation
of an already-structured payload, and round-trip fidelity of that
reconciliation's output -- is covered directly against
section_drafting.reconcile_structured_result / reconcile_material_claims in
tests/test_section_drafting.py (TestMaterialClaimMapping and friends), with
no dependency on a persistence layer or a generation entry point.

What was NOT reusable -- the get-or-create cache-hit/invalidation
orchestration itself, and its `_FakeDraftStore` standing in for the
migration 018 RPC -- has no surviving production code to test, since
get_or_create_section_draft's Python writer (database.py) and its only
caller (tenancy.get_or_generate_section_draft) were both removed. The
underlying `section_drafts` table, its RPC, and every historical row it
already holds are untouched (no destructive migration; see
docs/current/SYSTEM_STATE.md) -- only the ability to WRITE new rows through
this retired path is gone, and there is nothing left here to assert against
without reintroducing a generation call this product no longer makes.

Read-only access to those historical rows is covered by
tests/test_section_drafting_workspace.py (seeded historical-row fixtures
exercising tenancy.get_section_draft_status_for_organization's staleness/
current logic) and tests/test_section_drafting_tenancy.py (brief-assembly
architecture discipline). This file intentionally collects zero tests.
"""
