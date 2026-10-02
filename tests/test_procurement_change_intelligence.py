"""
tests/test_procurement_change_intelligence.py -- Deterministic test fixtures and
invariant verifications for PCI-A (Procurement Revision Foundation & Change Model).

Covers all Section 19 test fixtures (A-J) and Section 20 required invariants:
A. Original RFP only (Rev 0)
B. Deadline addendum: 22 Oct -> 29 Oct (SUPERSEDES)
C. Evaluation weight addendum: 30% -> 35% (SUPERSEDES)
D. Clarification: Hybrid allowed -> minimum 25% in-person (CLARIFIES / NARROWS)
E. Replacement pricing form (REPLACES / ARTIFACT: old SUPERSEDED, new CURRENT)
F. Duplicate addendum uploaded twice (NO_NEW_REVISION)
G. Addendum uploaded out of chronological order (Addendum 3 before Addendum 2)
H. Addendum correcting an earlier addendum (Addendum 3 corrects Addendum 2)
I. Ambiguous conflicting statement requiring human review (HUMAN_REVIEW_REQUIRED)
J. Unrelated addendum: deadline changes while insurance remains unchanged

Invariants tested:
- previous revisions immutable
- duplicate document does not create effective duplicate revision
- latest authoritative fact is correct
- superseded values remain historically queryable
- unrelated facts survive unchanged
- out-of-order upload does not corrupt chronology
- correction can supersede an earlier addendum fact
- ambiguous precedence does not auto-resolve
- current-state fingerprint changes only for semantic state changes
- tenancy boundaries hold
- revision creation is concurrency safe
"""
from __future__ import annotations

import concurrent.futures
import copy
import hashlib
import unittest
from unittest.mock import MagicMock, patch

import procurement_change_intelligence as pci


class TestPCIFixturesAndInvariants(unittest.TestCase):
    def setUp(self):
        self.bid_id = 1417
        self.org_id = "4326b564-8cc5-4463-9304-9a589f08cc91"
        self.storage = pci.InMemoryPCIStorage(
            initial_bids={self.bid_id: {"id": self.bid_id, "organization_id": self.org_id, "procurement_revision": 0}}
        )
        self.manager = pci.ProcurementRevisionManager(self.bid_id, self.org_id, storage=self.storage)

    # ── Fixture A: Original RFP Only ──────────────────────────────────────────
    def test_fixture_a_original_rfp_only(self):
        """Revision 0 established with baseline facts."""
        rfp_docs = [{"name": "City_of_Calgary_RFP_26_1610.pdf", "content_hash": "hash_rfp_main"}]
        baseline_facts = [
            pci.FactChange(
                change_type=pci.CHANGE_ADDS,
                fact_type="DEADLINE",
                entity_id="deadline.submission",
                before_value=None,
                after_value="2026-10-22T16:00:00",
                source_document="City_of_Calgary_RFP_26_1610.pdf",
                source_hash="hash_rfp_main",
            ),
            pci.FactChange(
                change_type=pci.CHANGE_ADDS,
                fact_type="WEIGHT",
                entity_id="eval.firm_experience",
                before_value=None,
                after_value=30,
                source_document="City_of_Calgary_RFP_26_1610.pdf",
                source_hash="hash_rfp_main",
            ),
            pci.FactChange(
                change_type=pci.CHANGE_ADDS,
                fact_type="COMMERCIAL",
                entity_id="insurance.general_liability",
                before_value=None,
                after_value="5,000,000 CAD",
                source_document="City_of_Calgary_RFP_26_1610.pdf",
                source_hash="hash_rfp_main",
            ),
            pci.FactChange(
                change_type=pci.CHANGE_ADDS,
                fact_type="SCOPE",
                entity_id="scope.delivery_model",
                before_value=None,
                after_value="Hybrid delivery permitted",
                source_document="City_of_Calgary_RFP_26_1610.pdf",
                source_hash="hash_rfp_main",
            ),
            pci.FactChange(
                change_type=pci.CHANGE_ADDS,
                fact_type="ARTIFACT",
                entity_id="artifact.pricing_form",
                before_value=None,
                after_value={"name": "Appendix D - Pricing Form.xlsx", "content_hash": "hash_pricing_v1"},
                source_document="City_of_Calgary_RFP_26_1610.pdf",
                source_hash="hash_rfp_main",
            ),
        ]
        rev0 = self.manager.create_baseline_revision(rfp_docs, baseline_facts, buyer_issued_date="2026-10-01")
        self.assertEqual(rev0.revision_number, 0)
        self.assertTrue(rev0.is_current)

        state = self.manager.get_current_state()
        self.assertEqual(state.current_revision, 0)
        self.assertEqual(len(state.authoritative_facts), 5)
        self.assertEqual(state.authoritative_facts["deadline.submission"].after_value, "2026-10-22T16:00:00")
        self.assertEqual(state.superseded_facts, [])
        self.assertEqual(state.pending_conflicts, [])
        self.assertIn("artifact.pricing_form", state.active_artifacts)
        self.assertEqual(state.active_artifacts["artifact.pricing_form"].status, pci.AUTHORITY_CURRENT)

    # ── Fixture B: Deadline Addendum (22 Oct -> 29 Oct) ────────────────────────
    def test_fixture_b_deadline_addendum(self):
        """Addendum 1 supersedes deadline while leaving other facts unchanged."""
        self.test_fixture_a_original_rfp_only()

        addendum_doc = [{"name": "Addendum 1.pdf", "content_hash": "hash_addendum_1"}]
        changes = [
            pci.FactChange(
                change_type=pci.CHANGE_SUPERSEDES,
                fact_type="DEADLINE",
                entity_id="deadline.submission",
                before_value="2026-10-22T16:00:00",
                after_value="2026-10-29T16:00:00",
                source_document="Addendum 1.pdf",
                source_hash="hash_addendum_1",
            )
        ]
        res = self.manager.add_buyer_update_revision(addendum_doc, changes, buyer_issued_date="2026-10-05")
        self.assertEqual(res["outcome"], pci.OUTCOME_REVISION_CREATED)
        self.assertEqual(res["current_revision"], 1)

        state = self.manager.get_current_state()
        self.assertEqual(state.current_revision, 1)
        self.assertEqual(state.authoritative_facts["deadline.submission"].after_value, "2026-10-29T16:00:00")
        # Invariant: superseded value is historically recorded
        self.assertEqual(len(state.superseded_facts), 1)
        self.assertEqual(state.superseded_facts[0].entity_id, "deadline.submission")
        self.assertEqual(state.superseded_facts[0].after_value, "2026-10-22T16:00:00")
        self.assertEqual(state.superseded_facts[0].authority_status, pci.AUTHORITY_SUPERSEDED)
        # Invariant: unrelated facts survive unchanged
        self.assertEqual(state.authoritative_facts["insurance.general_liability"].after_value, "5,000,000 CAD")
        self.assertEqual(state.authoritative_facts["eval.firm_experience"].after_value, 30)

    # ── Fixture C: Evaluation Weight Addendum (30% -> 35%) ─────────────────────
    def test_fixture_c_evaluation_weight_addendum(self):
        """Addendum updating evaluation weight from 30% to 35%."""
        self.test_fixture_a_original_rfp_only()

        addendum_doc = [{"name": "Addendum 1 - Criteria Update.pdf", "content_hash": "hash_addendum_criteria"}]
        changes = [
            pci.FactChange(
                change_type=pci.CHANGE_SUPERSEDES,
                fact_type="WEIGHT",
                entity_id="eval.firm_experience",
                before_value=30,
                after_value=35,
                source_document="Addendum 1 - Criteria Update.pdf",
                source_hash="hash_addendum_criteria",
            )
        ]
        res = self.manager.add_buyer_update_revision(addendum_doc, changes, buyer_issued_date="2026-10-06")
        self.assertEqual(res["outcome"], pci.OUTCOME_REVISION_CREATED)

        state = self.manager.get_current_state()
        self.assertEqual(state.authoritative_facts["eval.firm_experience"].after_value, 35)
        # Superseded record retained
        self.assertEqual(state.superseded_facts[0].after_value, 30)

    # ── Fixture D: Clarification (Hybrid -> minimum 25% in-person) ────────────
    def test_fixture_d_clarification_narrows(self):
        """Clarification/Q&A narrows hybrid delivery to require minimum 25% in-person."""
        self.test_fixture_a_original_rfp_only()

        qa_doc = [{"name": "Clarification Q&A #1.pdf", "content_hash": "hash_qa_1"}]
        changes = [
            pci.FactChange(
                change_type=pci.CHANGE_NARROWS,
                fact_type="SCOPE",
                entity_id="scope.delivery_model",
                before_value="Hybrid delivery permitted",
                after_value="Hybrid delivery permitted with minimum 25% on-site presence",
                source_document="Clarification Q&A #1.pdf",
                source_hash="hash_qa_1",
            )
        ]
        res = self.manager.add_buyer_update_revision(qa_doc, changes, buyer_issued_date="2026-10-07")
        self.assertEqual(res["outcome"], pci.OUTCOME_REVISION_CREATED)

        state = self.manager.get_current_state()
        fact = state.authoritative_facts["scope.delivery_model"]
        self.assertEqual(fact.change_type, pci.CHANGE_NARROWS)
        self.assertIn("minimum 25%", fact.after_value)
        self.assertEqual(fact.metadata.get("clarifies_prior_value"), "Hybrid delivery permitted")

    # ── Fixture E: Replacement Pricing Form ────────────────────────────────────
    def test_fixture_e_replacement_pricing_form(self):
        """Replacement file supersedes original artifact; old becomes SUPERSEDED, new CURRENT."""
        self.test_fixture_a_original_rfp_only()

        replace_doc = [{"name": "Addendum 2 - Replacement Appendix D.xlsx", "content_hash": "hash_pricing_v2"}]
        changes = [
            pci.FactChange(
                change_type=pci.CHANGE_REPLACES,
                fact_type="ARTIFACT",
                entity_id="artifact.pricing_form",
                before_value={"name": "Appendix D - Pricing Form.xlsx", "content_hash": "hash_pricing_v1"},
                after_value={"name": "Appendix D - Pricing Form (Rev 1).xlsx", "content_hash": "hash_pricing_v2"},
                source_document="Addendum 2 - Replacement Appendix D.xlsx",
                source_hash="hash_pricing_v2",
            )
        ]
        res = self.manager.add_buyer_update_revision(replace_doc, changes, buyer_issued_date="2026-10-08")
        self.assertEqual(res["outcome"], pci.OUTCOME_REVISION_CREATED)

        state = self.manager.get_current_state()
        artifact = state.active_artifacts["artifact.pricing_form"]
        self.assertEqual(artifact.status, pci.AUTHORITY_CURRENT)
        self.assertEqual(artifact.name, "Appendix D - Pricing Form (Rev 1).xlsx")
        self.assertEqual(artifact.content_hash, "hash_pricing_v2")
        self.assertEqual(artifact.replaces_artifact_id, "artifact.pricing_form")

        # Historical revision 0 still reflects original form
        rev0 = self.manager.get_revision(0)
        self.assertFalse(rev0.is_current)
        self.assertEqual(
            rev0.change_set.changes[4].after_value["name"],
            "Appendix D - Pricing Form.xlsx"
        )

    # ── Fixture F: Duplicate Addendum Uploaded Twice (Idempotency) ────────────
    def test_fixture_f_duplicate_addendum_idempotency(self):
        """Uploading identical buyer document twice does not create a new revision."""
        self.test_fixture_a_original_rfp_only()

        addendum_doc = [{"name": "Addendum 1.pdf", "content_hash": "hash_addendum_1"}]
        changes = [
            pci.FactChange(
                change_type=pci.CHANGE_SUPERSEDES,
                fact_type="DEADLINE",
                entity_id="deadline.submission",
                before_value="2026-10-22T16:00:00",
                after_value="2026-10-29T16:00:00",
                source_document="Addendum 1.pdf",
                source_hash="hash_addendum_1",
            )
        ]
        # First upload
        res1 = self.manager.add_buyer_update_revision(addendum_doc, changes, buyer_issued_date="2026-10-05")
        self.assertEqual(res1["outcome"], pci.OUTCOME_REVISION_CREATED)
        self.assertEqual(res1["current_revision"], 1)

        # Duplicate upload of same document
        res2 = self.manager.add_buyer_update_revision(addendum_doc, changes, buyer_issued_date="2026-10-05")
        self.assertEqual(res2["outcome"], pci.OUTCOME_NO_NEW_REVISION)
        self.assertEqual(res2["current_revision"], 1)
        self.assertEqual(self.manager.current_revision_number, 1)
        # Exactly 2 revisions exist (Rev 0 and Rev 1)
        self.assertEqual(len(self.manager.get_all_revisions()), 2)

    # ── Fixture G: Addenda Uploaded Out of Chronological Order ─────────────────
    def test_fixture_g_out_of_order_upload_chronology(self):
        """Upload Addendum 3 before Addendum 2. Chronological replay ensures
        Addendum 3 authority outranks Addendum 2 facts, not upload order."""
        self.test_fixture_a_original_rfp_only()

        # Step 1: Upload Addendum 3 first (deadline moved to 2026-11-10)
        doc3 = [{"name": "Addendum 3.pdf", "content_hash": "hash_add_3"}]
        changes3 = [
            pci.FactChange(
                change_type=pci.CHANGE_SUPERSEDES,
                fact_type="DEADLINE",
                entity_id="deadline.submission",
                before_value="2026-10-22T16:00:00",
                after_value="2026-11-10T16:00:00",
                source_document="Addendum 3.pdf",
                source_hash="hash_add_3",
            )
        ]
        res3 = self.manager.add_buyer_update_revision(
            doc3, changes3, buyer_issued_date="2026-10-15", force_chronology_index=3
        )
        self.assertEqual(res3["outcome"], pci.OUTCOME_REVISION_CREATED)

        # Step 2: Upload Addendum 2 later (which had earlier set deadline to 2026-11-03)
        doc2 = [{"name": "Addendum 2.pdf", "content_hash": "hash_add_2"}]
        changes2 = [
            pci.FactChange(
                change_type=pci.CHANGE_SUPERSEDES,
                fact_type="DEADLINE",
                entity_id="deadline.submission",
                before_value="2026-10-22T16:00:00",
                after_value="2026-11-03T16:00:00",
                source_document="Addendum 2.pdf",
                source_hash="hash_add_2",
            )
        ]
        res2 = self.manager.add_buyer_update_revision(
            doc2, changes2, buyer_issued_date="2026-10-10", force_chronology_index=2
        )
        self.assertEqual(res2["outcome"], pci.OUTCOME_REVISION_CREATED)

        # Invariant: Chronological replay orders Rev 0 -> Addendum 2 (chrono 2) -> Addendum 3 (chrono 3).
        # The latest authoritative buyer fact is 2026-11-10 (from Addendum 3), NOT 2026-11-03 (Addendum 2).
        state = self.manager.get_current_state()
        self.assertEqual(state.authoritative_facts["deadline.submission"].after_value, "2026-11-10T16:00:00")
        self.assertEqual(state.authoritative_facts["deadline.submission"].source_document, "Addendum 3.pdf")

    # ── Fixture H: Addendum Correcting an Earlier Addendum ─────────────────────
    def test_fixture_h_addendum_correcting_earlier_addendum(self):
        """Addendum 3 corrects a mistake in Addendum 2 (not just modifying Rev 0)."""
        self.test_fixture_a_original_rfp_only()

        # Addendum 1 introduces requirement R_CYBER
        doc1 = [{"name": "Addendum 1.pdf", "content_hash": "hash_add1"}]
        c1 = [
            pci.FactChange(
                change_type=pci.CHANGE_ADDS,
                fact_type="REQUIREMENT",
                entity_id="req.cyber_cert",
                before_value=None,
                after_value="ISO 27001 required within 30 days of award",
                source_document="Addendum 1.pdf",
                source_hash="hash_add1",
            )
        ]
        self.manager.add_buyer_update_revision(doc1, c1, buyer_issued_date="2026-10-05")

        # Addendum 2 corrects R_CYBER to SOC 2 Type II
        doc2 = [{"name": "Addendum 2.pdf", "content_hash": "hash_add2"}]
        c2 = [
            pci.FactChange(
                change_type=pci.CHANGE_CORRECTS,
                fact_type="REQUIREMENT",
                entity_id="req.cyber_cert",
                before_value="ISO 27001 required within 30 days of award",
                after_value="Correction: SOC 2 Type II required at bid submission time",
                source_document="Addendum 2.pdf",
                source_hash="hash_add2",
            )
        ]
        self.manager.add_buyer_update_revision(doc2, c2, buyer_issued_date="2026-10-08")

        state = self.manager.get_current_state()
        active_fact = state.authoritative_facts["req.cyber_cert"]
        self.assertEqual(active_fact.change_type, pci.CHANGE_CORRECTS)
        self.assertIn("SOC 2 Type II", active_fact.after_value)

        # Check fact history
        history = self.manager.get_fact_history("req.cyber_cert")
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["revision"], 1)
        self.assertEqual(history[1]["revision"], 2)
        self.assertEqual(history[1]["change_type"], pci.CHANGE_CORRECTS)

    # ── Fixture I: Ambiguous Conflicting Statement Requiring Human Review ───────
    def test_fixture_i_ambiguous_precedence_human_review(self):
        """Ambiguous conflicting statement flags HUMAN_REVIEW_REQUIRED and does NOT
        silently overwrite canonical buyer truth."""
        self.test_fixture_a_original_rfp_only()

        notice_doc = [{"name": "Informal Q&A Notice.pdf", "content_hash": "hash_informal_qa"}]
        changes = [
            pci.FactChange(
                change_type=pci.CHANGE_CONFLICTS_WITH,
                fact_type="DEADLINE",
                entity_id="deadline.submission",
                before_value="2026-10-22T16:00:00",
                after_value="Closing date might be extended to Nov 5 per verbal discussion",
                source_document="Informal Q&A Notice.pdf",
                source_hash="hash_informal_qa",
                authority_status=pci.AUTHORITY_AMBIGUOUS,
                review_status=pci.REVIEW_STATUS_HUMAN_REVIEW_REQUIRED,
            )
        ]
        res = self.manager.add_buyer_update_revision(notice_doc, changes, buyer_issued_date="2026-10-09")
        self.assertEqual(res["outcome"], pci.OUTCOME_REVISION_CREATED)

        state = self.manager.get_current_state()
        # Authoritative fact remains the authoritative Rev 0 value! Not silently overwritten!
        self.assertEqual(state.authoritative_facts["deadline.submission"].after_value, "2026-10-22T16:00:00")
        # Conflict is placed in pending_conflicts
        self.assertEqual(len(state.pending_conflicts), 1)
        conflict = state.pending_conflicts[0]
        self.assertEqual(conflict.entity_id, "deadline.submission")
        self.assertEqual(conflict.review_status, pci.REVIEW_STATUS_HUMAN_REVIEW_REQUIRED)
        self.assertEqual(conflict.authority_status, pci.AUTHORITY_AMBIGUOUS)

    # ── Fixture J: Unrelated Addendum (Deadline changes, Insurance survives) ───
    def test_fixture_j_unrelated_facts_survive_unchanged(self):
        """Field-level precedence: updating deadline does not modify or wipe insurance."""
        self.test_fixture_a_original_rfp_only()

        doc = [{"name": "Addendum 1 - Schedule Only.pdf", "content_hash": "hash_sched_only"}]
        changes = [
            pci.FactChange(
                change_type=pci.CHANGE_SUPERSEDES,
                fact_type="DEADLINE",
                entity_id="deadline.submission",
                before_value="2026-10-22T16:00:00",
                after_value="2026-10-31T12:00:00",
                source_document="Addendum 1 - Schedule Only.pdf",
                source_hash="hash_sched_only",
            )
        ]
        self.manager.add_buyer_update_revision(doc, changes, buyer_issued_date="2026-10-06")

        state = self.manager.get_current_state()
        # Insurance fact was NEVER touched and survived completely unchanged
        self.assertIn("insurance.general_liability", state.authoritative_facts)
        self.assertEqual(state.authoritative_facts["insurance.general_liability"].after_value, "5,000,000 CAD")
        self.assertEqual(state.authoritative_facts["eval.firm_experience"].after_value, 30)

    # ── Required Invariant: Immutability of Past Revisions ─────────────────────
    def test_invariant_previous_revisions_immutable(self):
        """Once Revision 0 is established and Rev 1 is added, Rev 0 cannot be altered."""
        self.test_fixture_b_deadline_addendum()
        rev0 = self.manager.get_revision(0)
        self.assertEqual(rev0.revision_number, 0)
        self.assertFalse(rev0.is_current)
        self.assertEqual(rev0.change_set.changes[0].after_value, "2026-10-22T16:00:00")

    # ── Required Invariant: Fingerprints Change Only on Semantic Shifts ────────
    def test_invariant_state_fingerprint_stability(self):
        """Semantic fingerprints must remain completely stable if no facts change,
        and change deterministically when a fact is updated."""
        self.test_fixture_a_original_rfp_only()
        state1 = self.manager.get_current_state()
        state2 = self.manager.get_current_state()
        self.assertEqual(state1.state_fingerprint, state2.state_fingerprint)

        # Apply a change
        doc = [{"name": "Addendum 1.pdf", "content_hash": "hash_add_x"}]
        c = [
            pci.FactChange(
                change_type=pci.CHANGE_SUPERSEDES,
                fact_type="DEADLINE",
                entity_id="deadline.submission",
                before_value="2026-10-22T16:00:00",
                after_value="2026-11-01T00:00:00",
                source_document="Addendum 1.pdf",
                source_hash="hash_add_x",
            )
        ]
        self.manager.add_buyer_update_revision(doc, c)
        state3 = self.manager.get_current_state()
        self.assertNotEqual(state1.state_fingerprint, state3.state_fingerprint)

    # ── Required Invariant: Tenancy Enforcement ───────────────────────────────
    def test_invariant_tenancy_enforcement(self):
        """Manager refuses operations spanning different bid or organization IDs."""
        with self.assertRaises(pci.TenancyViolationError):
            pci.ProcurementRevisionManager(0, self.org_id, storage=self.storage)

        with self.assertRaises(pci.TenancyViolationError):
            pci.ProcurementRevisionManager(self.bid_id, "", storage=self.storage)

        with self.assertRaises(pci.TenancyViolationError):
            self.manager._verify_tenancy(9999, self.org_id)

        with self.assertRaises(pci.TenancyViolationError):
            self.manager._verify_tenancy(self.bid_id, "foreign-org-id")

    # ── Required Invariant: Optimistic Concurrency Safety ─────────────────────
    def test_invariant_concurrency_optimistic_locking(self):
        """Prevent Revision 4 and Revision 5 both assuming Revision 3 is parent."""
        self.test_fixture_a_original_rfp_only()  # current revision is 0

        doc1 = [{"name": "Addendum 1.pdf", "content_hash": "hash_concur_1"}]
        changes1 = [
            pci.FactChange(
                change_type=pci.CHANGE_SUPERSEDES,
                fact_type="DEADLINE",
                entity_id="deadline.submission",
                before_value="2026-10-22T16:00:00",
                after_value="2026-10-25T00:00:00",
                source_document="Addendum 1.pdf",
                source_hash="hash_concur_1",
            )
        ]

        # Valid add with expected_base_revision=0
        self.manager.add_buyer_update_revision(doc1, changes1, expected_base_revision=0)
        self.assertEqual(self.manager.current_revision_number, 1)

        # Stale attempt: another client also expected base revision 0
        doc2 = [{"name": "Addendum 2.pdf", "content_hash": "hash_concur_2"}]
        changes2 = [
            pci.FactChange(
                change_type=pci.CHANGE_SUPERSEDES,
                fact_type="DEADLINE",
                entity_id="deadline.submission",
                before_value="2026-10-22T16:00:00",
                after_value="2026-10-30T00:00:00",
                source_document="Addendum 2.pdf",
                source_hash="hash_concur_2",
            )
        ]
        with self.assertRaises(pci.StaleRevisionError):
            self.manager.add_buyer_update_revision(doc2, changes2, expected_base_revision=0)


class TestDocumentClassification(unittest.TestCase):
    def test_document_classification_types(self):
        self.assertEqual(
            pci.classify_document_change_type("Addendum #1.pdf"),
            pci.DOC_CHANGE_ADDENDUM
        )
        self.assertEqual(
            pci.classify_document_change_type("Amendment 02 - Scope.docx"),
            pci.DOC_CHANGE_AMENDMENT
        )
        self.assertEqual(
            pci.classify_document_change_type("Questions and Answers - Round 1.pdf"),
            pci.DOC_CHANGE_Q_AND_A
        )
        self.assertEqual(
            pci.classify_document_change_type("Clarifications on Delivery Schedule.pdf"),
            pci.DOC_CHANGE_CLARIFICATION
        )
        self.assertEqual(
            pci.classify_document_change_type("Revised Pricing Form Appendix D.xlsx"),
            pci.DOC_CHANGE_REVISED_FORM
        )
        self.assertEqual(
            pci.classify_document_change_type("Replacement Schedule B.docx"),
            pci.DOC_CHANGE_REPLACEMENT_DOCUMENT
        )
        self.assertEqual(
            pci.classify_document_change_type("City_of_Calgary_RFP_26_1610.pdf"),
            pci.DOC_CHANGE_ORIGINAL_RFP
        )

    def test_chronology_extraction(self):
        meta = pci.extract_chronology_metadata("Addendum 03 - October 15, 2026.pdf")
        self.assertEqual(meta["sequence_number"], 3)
        self.assertEqual(meta["issued_date"], "2026-10-15")
        self.assertEqual(meta["confidence"], "high")


class TestMultithreadedConcurrency(unittest.TestCase):
    def test_concurrent_revision_additions_are_race_free(self):
        """Simulate two threads attempting to add revisions simultaneously from the same base."""
        storage = pci.InMemoryPCIStorage(
            initial_bids={2026: {"id": 2026, "organization_id": "org-concurrent-test", "procurement_revision": 0}}
        )
        manager = pci.ProcurementRevisionManager(2026, "org-concurrent-test", storage=storage)
        rfp_docs = [{"name": "RFP.pdf", "content_hash": "hash_rfp"}]
        baseline_facts = [
            pci.FactChange(
                change_type=pci.CHANGE_ADDS,
                fact_type="DEADLINE",
                entity_id="deadline.submission",
                before_value=None,
                after_value="2026-10-22",
                source_document="RFP.pdf",
                source_hash="hash_rfp",
            )
        ]
        manager.create_baseline_revision(rfp_docs, baseline_facts)

        results = []
        errors = []

        def worker(thread_id: int):
            doc = [{"name": f"Addendum_{thread_id}.pdf", "content_hash": f"hash_worker_{thread_id}"}]
            changes = [
                pci.FactChange(
                    change_type=pci.CHANGE_SUPERSEDES,
                    fact_type="DEADLINE",
                    entity_id="deadline.submission",
                    before_value="2026-10-22",
                    after_value=f"2026-10-2{thread_id}",
                    source_document=f"Addendum_{thread_id}.pdf",
                    source_hash=f"hash_worker_{thread_id}",
                )
            ]
            try:
                # Both threads expect base revision 0
                res = manager.add_buyer_update_revision(doc, changes, expected_base_revision=0)
                results.append(res)
            except pci.StaleRevisionError as e:
                errors.append(e)

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            f1 = executor.submit(worker, 1)
            f2 = executor.submit(worker, 2)
            concurrent.futures.wait([f1, f2])

        # Invariant: exactly one thread succeeded in creating revision 1;
        # the other thread caught StaleRevisionError (fail-closed, no corrupt branch).
        self.assertEqual(len(results), 1)
        self.assertEqual(len(errors), 1)
        self.assertEqual(manager.current_revision_number, 1)


class TestSchemaMappingContract(unittest.TestCase):
    def test_change_structures_map_to_migration_010_columns(self):
        """Verify that FactChange fields map 1:1 to public.procurement_changes columns:
        review_decision, change_type, entity_type, entity_id, previous_value, new_value,
        source_document_hash, physical_source_ref, etc."""
        fact = pci.FactChange(
            change_type=pci.CHANGE_SUPERSEDES,
            fact_type="DEADLINE",
            entity_id="deadline.submission",
            before_value="2026-10-22",
            after_value="2026-10-29",
            source_document="Addendum 1.pdf",
            source_hash="hash_123",
            authority_status=pci.AUTHORITY_CURRENT,
            review_status=pci.REVIEW_STATUS_APPROVED,
        )
        as_dict = fact.to_dict()
        # Columns in procurement_changes
        self.assertIn("change_type", as_dict)
        self.assertIn("entity_id", as_dict)
        self.assertIn("before_value", as_dict)
        self.assertIn("after_value", as_dict)
        self.assertIn("source_hash", as_dict)
        self.assertIn("review_status", as_dict)


class TestPCIDurabilityAndInvariants(unittest.TestCase):
    """PCI-A.1 Durability and Invariant Closure tests (13 core invariant tests)."""

    def setUp(self):
        self.bid_id = 9901
        self.org_id = "org-test-durability"
        self.storage = pci.InMemoryPCIStorage()

    def _make_baseline(self, mgr: pci.ProcurementRevisionManager) -> pci.ProcurementRevision:
        docs = [{"name": "RFP_Main.pdf", "content_hash": "hash_rfp_main_001"}]
        facts = [
            pci.FactChange(
                change_type=pci.CHANGE_ADDS,
                fact_type="DEADLINE",
                entity_id="deadline.submission",
                before_value=None,
                after_value="2026-11-01T17:00:00",
                source_document="RFP_Main.pdf",
                source_hash="hash_rfp_main_001",
            ),
            pci.FactChange(
                change_type=pci.CHANGE_ADDS,
                fact_type="COMMERCIAL",
                entity_id="insurance.general_liability",
                before_value=None,
                after_value="2,000,000 CAD",
                source_document="RFP_Main.pdf",
                source_hash="hash_rfp_main_001",
            ),
            pci.FactChange(
                change_type=pci.CHANGE_ADDS,
                fact_type="ARTIFACT",
                entity_id="artifact.pricing_form",
                before_value=None,
                after_value={"name": "Pricing_Form_v1.xlsx", "content_hash": "hash_pricing_v1"},
                source_document="RFP_Main.pdf",
                source_hash="hash_rfp_main_001",
            ),
        ]
        return mgr.create_baseline_revision(docs, facts, buyer_issued_date="2026-10-01")

    # 1. Revision 0 survives manager/service recreation
    def test_durability_rev0_survives_manager_recreation(self):
        mgr1 = pci.ProcurementRevisionManager(self.bid_id, self.org_id, storage=self.storage)
        self._make_baseline(mgr1)

        # Recreate manager from same storage
        mgr2 = pci.ProcurementRevisionManager(self.bid_id, self.org_id, storage=self.storage)
        self.assertEqual(mgr2.current_revision_number, 0)
        rev0 = mgr2.get_revision(0)
        self.assertIsNotNone(rev0)
        self.assertEqual(rev0.revision_number, 0)
        self.assertEqual(len(rev0.change_set.changes), 3)
        self.assertTrue(rev0.is_current)

    # 2. Revision 1 survives manager/service recreation
    def test_durability_rev1_survives_manager_recreation(self):
        mgr1 = pci.ProcurementRevisionManager(self.bid_id, self.org_id, storage=self.storage)
        self._make_baseline(mgr1)

        doc1 = [{"name": "Addendum 1.pdf", "content_hash": "hash_add_001"}]
        c1 = [
            pci.FactChange(
                change_type=pci.CHANGE_SUPERSEDES,
                fact_type="DEADLINE",
                entity_id="deadline.submission",
                before_value="2026-11-01T17:00:00",
                after_value="2026-11-15T17:00:00",
                source_document="Addendum 1.pdf",
                source_hash="hash_add_001",
            )
        ]
        mgr1.add_buyer_update_revision(doc1, c1, buyer_issued_date="2026-10-10")

        # Recreate manager
        mgr2 = pci.ProcurementRevisionManager(self.bid_id, self.org_id, storage=self.storage)
        self.assertEqual(mgr2.current_revision_number, 1)
        rev1 = mgr2.get_revision(1)
        self.assertEqual(rev1.revision_number, 1)
        self.assertTrue(rev1.is_current)
        self.assertEqual(mgr2.get_current_state().authoritative_facts["deadline.submission"].after_value, "2026-11-15T17:00:00")

    # 3. Complete history rehydrates correctly
    def test_durability_complete_history_rehydrates_correctly(self):
        mgr1 = pci.ProcurementRevisionManager(self.bid_id, self.org_id, storage=self.storage)
        self._make_baseline(mgr1)

        doc1 = [{"name": "Addendum 1.pdf", "content_hash": "hash_add_001"}]
        c1 = [
            pci.FactChange(
                change_type=pci.CHANGE_SUPERSEDES,
                fact_type="DEADLINE",
                entity_id="deadline.submission",
                before_value="2026-11-01T17:00:00",
                after_value="2026-11-15T17:00:00",
                source_document="Addendum 1.pdf",
                source_hash="hash_add_001",
            )
        ]
        mgr1.add_buyer_update_revision(doc1, c1, buyer_issued_date="2026-10-10")

        doc2 = [{"name": "Addendum 2.pdf", "content_hash": "hash_add_002"}]
        c2 = [
            pci.FactChange(
                change_type=pci.CHANGE_SUPERSEDES,
                fact_type="COMMERCIAL",
                entity_id="insurance.general_liability",
                before_value="2,000,000 CAD",
                after_value="5,000,000 CAD",
                source_document="Addendum 2.pdf",
                source_hash="hash_add_002",
            )
        ]
        mgr1.add_buyer_update_revision(doc2, c2, buyer_issued_date="2026-10-15")

        # Test both top-level functions and manager rehydration
        history = pci.load_revision_history(self.bid_id, self.org_id, storage=self.storage)
        self.assertEqual(len(history), 3)
        self.assertEqual([r.revision_number for r in history], [0, 1, 2])

        state = pci.load_current_authoritative_state(self.bid_id, self.org_id, storage=self.storage)
        self.assertEqual(state.current_revision, 2)
        self.assertEqual(state.authoritative_facts["deadline.submission"].after_value, "2026-11-15T17:00:00")
        self.assertEqual(state.authoritative_facts["insurance.general_liability"].after_value, "5,000,000 CAD")

    # 4. Duplicate detection survives recreation
    def test_durability_duplicate_detection_survives_recreation(self):
        mgr1 = pci.ProcurementRevisionManager(self.bid_id, self.org_id, storage=self.storage)
        self._make_baseline(mgr1)

        doc1 = [{"name": "Addendum 1.pdf", "content_hash": "hash_dup_check_001"}]
        c1 = [
            pci.FactChange(
                change_type=pci.CHANGE_SUPERSEDES,
                fact_type="DEADLINE",
                entity_id="deadline.submission",
                before_value="2026-11-01T17:00:00",
                after_value="2026-11-20T17:00:00",
                source_document="Addendum 1.pdf",
                source_hash="hash_dup_check_001",
            )
        ]
        res1 = mgr1.add_buyer_update_revision(doc1, c1)
        self.assertEqual(res1["outcome"], pci.OUTCOME_REVISION_CREATED)

        # Recreate manager in fresh process/instance
        mgr2 = pci.ProcurementRevisionManager(self.bid_id, self.org_id, storage=self.storage)
        res2 = mgr2.add_buyer_update_revision(doc1, c1)
        self.assertEqual(res2["outcome"], pci.OUTCOME_NO_NEW_REVISION)
        self.assertEqual(mgr2.current_revision_number, 1)
        self.assertEqual(len(mgr2.get_all_revisions()), 2)

    # 5. Superseded facts rehydrate correctly
    def test_durability_superseded_facts_rehydrate_correctly(self):
        mgr1 = pci.ProcurementRevisionManager(self.bid_id, self.org_id, storage=self.storage)
        self._make_baseline(mgr1)

        doc1 = [{"name": "Addendum 1.pdf", "content_hash": "hash_add_001"}]
        c1 = [
            pci.FactChange(
                change_type=pci.CHANGE_SUPERSEDES,
                fact_type="DEADLINE",
                entity_id="deadline.submission",
                before_value="2026-11-01T17:00:00",
                after_value="2026-11-20T17:00:00",
                source_document="Addendum 1.pdf",
                source_hash="hash_add_001",
            )
        ]
        mgr1.add_buyer_update_revision(doc1, c1)

        mgr2 = pci.ProcurementRevisionManager(self.bid_id, self.org_id, storage=self.storage)
        state = mgr2.get_current_state()
        self.assertEqual(len(state.superseded_facts), 1)
        sup = state.superseded_facts[0]
        self.assertEqual(sup.entity_id, "deadline.submission")
        self.assertEqual(sup.after_value, "2026-11-01T17:00:00")
        self.assertEqual(sup.authority_status, pci.AUTHORITY_SUPERSEDED)

    # 6. Conflicts rehydrate correctly
    def test_durability_conflicts_rehydrate_correctly(self):
        mgr1 = pci.ProcurementRevisionManager(self.bid_id, self.org_id, storage=self.storage)
        self._make_baseline(mgr1)

        doc1 = [{"name": "Ambiguous Notice.pdf", "content_hash": "hash_ambig_001"}]
        c1 = [
            pci.FactChange(
                change_type=pci.CHANGE_CONFLICTS_WITH,
                fact_type="DEADLINE",
                entity_id="deadline.submission",
                before_value="2026-11-01T17:00:00",
                after_value="Oral statement indicates Nov 30 deadline",
                source_document="Ambiguous Notice.pdf",
                source_hash="hash_ambig_001",
                authority_status=pci.AUTHORITY_AMBIGUOUS,
                review_status=pci.REVIEW_STATUS_HUMAN_REVIEW_REQUIRED,
            )
        ]
        mgr1.add_buyer_update_revision(doc1, c1)

        mgr2 = pci.ProcurementRevisionManager(self.bid_id, self.org_id, storage=self.storage)
        state = mgr2.get_current_state()
        self.assertEqual(len(state.pending_conflicts), 1)
        conf = state.pending_conflicts[0]
        self.assertEqual(conf.entity_id, "deadline.submission")
        self.assertEqual(conf.review_status, pci.REVIEW_STATUS_HUMAN_REVIEW_REQUIRED)

    # 7. Replacement artifacts rehydrate correctly
    def test_durability_replacement_artifacts_rehydrate_correctly(self):
        mgr1 = pci.ProcurementRevisionManager(self.bid_id, self.org_id, storage=self.storage)
        self._make_baseline(mgr1)

        doc1 = [{"name": "Pricing_Form_v2.xlsx", "content_hash": "hash_pricing_v2"}]
        c1 = [
            pci.FactChange(
                change_type=pci.CHANGE_REPLACES,
                fact_type="ARTIFACT",
                entity_id="artifact.pricing_form",
                before_value={"name": "Pricing_Form_v1.xlsx", "content_hash": "hash_pricing_v1"},
                after_value={"name": "Pricing_Form_v2.xlsx", "content_hash": "hash_pricing_v2"},
                source_document="Pricing_Form_v2.xlsx",
                source_hash="hash_pricing_v2",
            )
        ]
        mgr1.add_buyer_update_revision(doc1, c1)

        mgr2 = pci.ProcurementRevisionManager(self.bid_id, self.org_id, storage=self.storage)
        state = mgr2.get_current_state()
        self.assertIn("artifact.pricing_form", state.active_artifacts)
        artifact = state.active_artifacts["artifact.pricing_form"]
        self.assertEqual(artifact.name, "Pricing_Form_v2.xlsx")
        self.assertEqual(artifact.status, pci.AUTHORITY_CURRENT)
        self.assertEqual(artifact.replaces_artifact_id, "artifact.pricing_form")

    # 8. System revision and buyer chronology remain distinct
    def test_durability_system_revision_and_buyer_chronology_remain_distinct(self):
        mgr1 = pci.ProcurementRevisionManager(self.bid_id, self.org_id, storage=self.storage)
        self._make_baseline(mgr1)

        # Upload Addendum 3 first
        doc3 = [{"name": "Addendum 3.pdf", "content_hash": "hash_add_003"}]
        c3 = [
            pci.FactChange(
                change_type=pci.CHANGE_SUPERSEDES,
                fact_type="DEADLINE",
                entity_id="deadline.submission",
                before_value="2026-11-01T17:00:00",
                after_value="2026-11-30T17:00:00",
                source_document="Addendum 3.pdf",
                source_hash="hash_add_003",
            )
        ]
        mgr1.add_buyer_update_revision(doc3, c3, force_chronology_index=3)

        # Upload Addendum 2 later
        doc2 = [{"name": "Addendum 2.pdf", "content_hash": "hash_add_002"}]
        c2 = [
            pci.FactChange(
                change_type=pci.CHANGE_SUPERSEDES,
                fact_type="DEADLINE",
                entity_id="deadline.submission",
                before_value="2026-11-01T17:00:00",
                after_value="2026-11-20T17:00:00",
                source_document="Addendum 2.pdf",
                source_hash="hash_add_002",
            )
        ]
        mgr1.add_buyer_update_revision(doc2, c2, force_chronology_index=2)

        # Recreate manager from storage
        mgr2 = pci.ProcurementRevisionManager(self.bid_id, self.org_id, storage=self.storage)
        revs = mgr2.get_all_revisions()
        self.assertEqual([r.revision_number for r in revs], [0, 1, 2])
        self.assertEqual([r.buyer_chronology_index for r in revs], [0, 3, 2])

        # Authoritative state evaluated via chronological replay
        state = mgr2.get_current_state()
        self.assertEqual(state.authoritative_facts["deadline.submission"].after_value, "2026-11-30T17:00:00")
        self.assertEqual(state.authoritative_facts["deadline.submission"].source_document, "Addendum 3.pdf")

    # 9. Semantic fingerprint survives no-op revision
    def test_durability_semantic_fingerprint_survives_noop_revision(self):
        mgr = pci.ProcurementRevisionManager(self.bid_id, self.org_id, storage=self.storage)
        self._make_baseline(mgr)
        state_rev0 = mgr.get_current_state()
        fp0 = state_rev0.state_fingerprint

        # Informational addendum with UNCHANGED fact
        doc_info = [{"name": "Notice to Bidders.pdf", "content_hash": "hash_notice_001"}]
        c_info = [
            pci.FactChange(
                change_type=pci.CHANGE_UNCHANGED,
                fact_type="DEADLINE",
                entity_id="deadline.submission",
                before_value="2026-11-01T17:00:00",
                after_value="2026-11-01T17:00:00",
                source_document="Notice to Bidders.pdf",
                source_hash="hash_notice_001",
            )
        ]
        res = mgr.add_buyer_update_revision(doc_info, c_info)
        self.assertEqual(res["outcome"], pci.OUTCOME_NEW_REVISION_NO_SEMANTIC_CHANGE)
        self.assertEqual(mgr.current_revision_number, 1)

        state_rev1 = mgr.get_current_state()
        fp1 = state_rev1.state_fingerprint
        self.assertEqual(fp0, fp1)

    # 10. Revision fingerprint changes on no-op revision
    def test_durability_revision_fingerprint_changes_on_noop_revision(self):
        mgr = pci.ProcurementRevisionManager(self.bid_id, self.org_id, storage=self.storage)
        self._make_baseline(mgr)
        rev0 = mgr.get_revision(0)

        doc_info = [{"name": "Notice to Bidders.pdf", "content_hash": "hash_notice_001"}]
        c_info = [
            pci.FactChange(
                change_type=pci.CHANGE_UNCHANGED,
                fact_type="DEADLINE",
                entity_id="deadline.submission",
                before_value="2026-11-01T17:00:00",
                after_value="2026-11-01T17:00:00",
                source_document="Notice to Bidders.pdf",
                source_hash="hash_notice_001",
            )
        ]
        mgr.add_buyer_update_revision(doc_info, c_info)
        rev1 = mgr.get_revision(1)

        self.assertNotEqual(rev0.revision_fingerprint, rev1.revision_fingerprint)

    # 11. Missing content_hash fails closed
    def test_durability_missing_content_hash_fails_closed(self):
        mgr = pci.ProcurementRevisionManager(self.bid_id, self.org_id, storage=self.storage)
        bad_docs = [{"name": "Missing_Hash.pdf"}]
        facts = [
            pci.FactChange(
                change_type=pci.CHANGE_ADDS,
                fact_type="DEADLINE",
                entity_id="deadline.submission",
                before_value=None,
                after_value="2026-11-01",
                source_document="Missing_Hash.pdf",
                source_hash="valid_hash",
            )
        ]
        with self.assertRaises(ValueError):
            mgr.create_baseline_revision(bad_docs, facts)

        # Fact missing source_hash
        bad_facts = [
            pci.FactChange(
                change_type=pci.CHANGE_ADDS,
                fact_type="DEADLINE",
                entity_id="deadline.submission",
                before_value=None,
                after_value="2026-11-01",
                source_document="Missing_Hash.pdf",
                source_hash="",
            )
        ]
        good_docs = [{"name": "Good.pdf", "content_hash": "good_hash"}]
        with self.assertRaises(ValueError):
            mgr.create_baseline_revision(good_docs, bad_facts)

    # 12. Foreign organization cannot read/write revision history
    def test_durability_foreign_organization_cannot_read_or_write(self):
        mgr = pci.ProcurementRevisionManager(self.bid_id, self.org_id, storage=self.storage)
        self._make_baseline(mgr)

        # Different organization accessing same bid_id
        with self.assertRaises(pci.TenancyViolationError):
            pci.ProcurementRevisionManager(self.bid_id, "foreign-org-456", storage=self.storage)

        with self.assertRaises(pci.TenancyViolationError):
            pci.load_revision_history(self.bid_id, "foreign-org-456", storage=self.storage)

        with self.assertRaises(pci.TenancyViolationError):
            pci.load_current_authoritative_state(self.bid_id, "foreign-org-456", storage=self.storage)

    # 13. Stale expected_base_revision fails across independent service instances
    def test_durability_stale_expected_base_revision_fails_across_instances(self):
        mgr_init = pci.ProcurementRevisionManager(self.bid_id, self.org_id, storage=self.storage)
        self._make_baseline(mgr_init)

        # Two independent instances sharing storage
        instance_a = pci.ProcurementRevisionManager(self.bid_id, self.org_id, storage=self.storage)
        instance_b = pci.ProcurementRevisionManager(self.bid_id, self.org_id, storage=self.storage)

        doc_a = [{"name": "Addendum A.pdf", "content_hash": "hash_a"}]
        c_a = [
            pci.FactChange(
                change_type=pci.CHANGE_SUPERSEDES,
                fact_type="DEADLINE",
                entity_id="deadline.submission",
                before_value="2026-11-01T17:00:00",
                after_value="2026-11-20T17:00:00",
                source_document="Addendum A.pdf",
                source_hash="hash_a",
            )
        ]
        # Instance A commits revision 1 expecting base 0
        instance_a.add_buyer_update_revision(doc_a, c_a, expected_base_revision=0)

        # Instance B attempts to commit revision expecting base 0
        doc_b = [{"name": "Addendum B.pdf", "content_hash": "hash_b"}]
        c_b = [
            pci.FactChange(
                change_type=pci.CHANGE_SUPERSEDES,
                fact_type="DEADLINE",
                entity_id="deadline.submission",
                before_value="2026-11-01T17:00:00",
                after_value="2026-11-25T17:00:00",
                source_document="Addendum B.pdf",
                source_hash="hash_b",
            )
        ]
        with self.assertRaises(pci.StaleRevisionError):
            instance_b.add_buyer_update_revision(doc_b, c_b, expected_base_revision=0)


class TestStorageConcurrency(unittest.TestCase):
    """Section 18: Concurrency across separate manager instances sharing storage."""

    def test_concurrent_manager_instances_race_free(self):
        storage = pci.InMemoryPCIStorage()
        bid_id = 9902
        org_id = "org-concur-storage"

        init_mgr = pci.ProcurementRevisionManager(bid_id, org_id, storage=storage)
        rfp_docs = [{"name": "RFP.pdf", "content_hash": "hash_rfp_c"}]
        baseline_facts = [
            pci.FactChange(
                change_type=pci.CHANGE_ADDS,
                fact_type="DEADLINE",
                entity_id="deadline.submission",
                before_value=None,
                after_value="2026-10-22",
                source_document="RFP.pdf",
                source_hash="hash_rfp_c",
            )
        ]
        init_mgr.create_baseline_revision(rfp_docs, baseline_facts)

        results = []
        errors = []

        def worker(worker_id: int):
            mgr = pci.ProcurementRevisionManager(bid_id, org_id, storage=storage)
            doc = [{"name": f"Addendum_{worker_id}.pdf", "content_hash": f"hash_worker_{worker_id}"}]
            changes = [
                pci.FactChange(
                    change_type=pci.CHANGE_SUPERSEDES,
                    fact_type="DEADLINE",
                    entity_id="deadline.submission",
                    before_value="2026-10-22",
                    after_value=f"2026-10-2{worker_id}",
                    source_document=f"Addendum_{worker_id}.pdf",
                    source_hash=f"hash_worker_{worker_id}",
                )
            ]
            try:
                res = mgr.add_buyer_update_revision(doc, changes, expected_base_revision=0)
                results.append(res)
            except pci.StaleRevisionError as e:
                errors.append(e)

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            f1 = executor.submit(worker, 1)
            f2 = executor.submit(worker, 2)
            concurrent.futures.wait([f1, f2])

        self.assertEqual(len(results), 1)
        self.assertEqual(len(errors), 1)
        # Check storage consistency
        final_mgr = pci.ProcurementRevisionManager(bid_id, org_id, storage=storage)
        self.assertEqual(final_mgr.current_revision_number, 1)


class TestMigration010StorageMapping(unittest.TestCase):
    """Section 19: Storage mapping test proving exact mapping to Migration 010 columns."""

    def test_persisted_storage_matches_migration_010_schema(self):
        storage = pci.InMemoryPCIStorage()
        bid_id = 9903
        org_id = "org-m010-mapping"

        mgr = pci.ProcurementRevisionManager(bid_id, org_id, storage=storage)
        rfp_docs = [{"name": "RFP.pdf", "content_hash": "hash_m010_rfp"}]
        baseline_facts = [
            pci.FactChange(
                change_type=pci.CHANGE_ADDS,
                fact_type="DEADLINE",
                entity_id="deadline.submission",
                before_value=None,
                after_value="2026-10-22",
                source_document="RFP.pdf",
                source_hash="hash_m010_rfp",
            )
        ]
        mgr.create_baseline_revision(rfp_docs, baseline_facts, buyer_issued_date="2026-10-01")

        # 1. Check bids record
        bid_record = storage.bids[bid_id]
        self.assertIn("procurement_revision", bid_record)
        self.assertIn("procurement_truth_status", bid_record)
        self.assertEqual(bid_record["procurement_revision"], 0)
        self.assertEqual(bid_record["procurement_truth_status"], "governed")

        # 2. Check procurement_update_reviews record
        self.assertIn(bid_id, storage.reviews)
        self.assertEqual(len(storage.reviews[bid_id]), 1)
        review = storage.reviews[bid_id][0]
        self.assertEqual(review["bid_id"], bid_id)
        self.assertEqual(review["organization_id"], org_id)
        self.assertEqual(review["review_kind"], "baseline")
        self.assertEqual(review["status"], "applied")
        self.assertEqual(review["base_procurement_revision"], 0)
        self.assertEqual(review["resulting_procurement_revision"], 0)
        self.assertIn("document_set_digest", review)
        self.assertIn("idempotency_key", review)
        self.assertFalse(review["no_canonical_change"])

        # 3. Check procurement_update_review_documents record
        rid = review["id"]
        self.assertIn(rid, storage.review_documents)
        rev_docs = storage.review_documents[rid]
        self.assertEqual(len(rev_docs), 1)
        rev_doc = rev_docs[0]
        self.assertEqual(rev_doc["review_id"], rid)
        self.assertEqual(rev_doc["role"], "primary")
        self.assertEqual(rev_doc["document_hash"], "hash_m010_rfp")

        # 4. Check procurement_changes record
        self.assertIn(rid, storage.changes)
        changes = storage.changes[rid]
        self.assertEqual(len(changes), 1)
        chg = changes[0]
        self.assertEqual(chg["review_id"], rid)
        self.assertEqual(chg["change_type"], "ADDED")
        self.assertEqual(chg["canonical_effect"], "canonical_change")
        self.assertEqual(chg["entity_type"], "DEADLINE")
        self.assertEqual(chg["entity_id"], "deadline.submission")
        self.assertIsNone(chg["previous_value"]["value"])
        self.assertEqual(chg["new_value"]["pci_change_type"], "ADDS")
        self.assertEqual(chg["new_value"]["value"], "2026-10-22")
        self.assertEqual(chg["source_document_hash"], "hash_m010_rfp")
        self.assertEqual(chg["physical_source_ref"], "RFP.pdf")


class TestProductionStorageWiring(unittest.TestCase):
    """Proof 1: Production storage wiring.
    Proves that production execution strictly wires to PCIDatabaseStorage
    and never silently defaults to InMemoryPCIStorage."""

    def test_production_wiring_defaults_to_pcidatabasestorage(self):
        with patch.object(pci.PCIDatabaseStorage, "verify_tenancy", return_value=None), \
             patch.object(pci.PCIDatabaseStorage, "load_revisions", return_value=[]):
            # 1. Direct manager construction without storage defaults to PCIDatabaseStorage
            mgr = pci.ProcurementRevisionManager(1417, "org-prod")
            self.assertIsInstance(mgr.storage, pci.PCIDatabaseStorage)
            self.assertNotIsInstance(mgr.storage, pci.InMemoryPCIStorage)

            # 2. Canonical production entrypoint defaults to PCIDatabaseStorage
            prod_mgr = pci.get_pci_manager(1417, "org-prod")
            self.assertIsInstance(prod_mgr.storage, pci.PCIDatabaseStorage)
            self.assertNotIsInstance(prod_mgr.storage, pci.InMemoryPCIStorage)


class MockTableQuery:
    def __init__(self, client, table_name: str):
        self.client = client
        self.table_name = table_name
        self._update_data = None
        self._filters: dict[str, Any] = {}
        self._in_filters: dict[str, list] = {}
        self._inserts = []

    def update(self, data: dict):
        self._update_data = data
        return self

    def insert(self, data):
        self._inserts = [data] if isinstance(data, dict) else list(data)
        return self

    def eq(self, col: str, val: Any):
        self._filters[col] = val
        return self

    def in_(self, col: str, vals: list):
        self._in_filters[col] = vals
        return self

    def select(self, *cols):
        return self

    def order(self, *args, **kwargs):
        return self

    def execute(self):
        res = MagicMock()
        if self._update_data is not None and self.table_name == "bids":
            bid_id = self._filters.get("id")
            bid = self.client.bids.get(bid_id)
            if not bid:
                res.data = []
                return res
            # Check conditional filters (e.g. procurement_revision)
            for col, expected_val in self._filters.items():
                if col == "id":
                    continue
                if bid.get(col) != expected_val:
                    # Atomic conflict: row does not match expected_base_revision! 0 rows updated.
                    res.data = []
                    return res
            # Atomically update
            bid.update(self._update_data)
            res.data = [dict(bid)]
            return res
        elif self._inserts:
            if self.table_name == "procurement_update_reviews":
                for item in self._inserts:
                    item_id = len(self.client.reviews) + 1
                    item_with_id = dict(item, id=item_id)
                    self.client.reviews.append(item_with_id)
                res.data = list(self.client.reviews[-len(self._inserts):])
                return res
            elif self.table_name == "procurement_update_review_documents":
                self.client.review_documents.extend(self._inserts)
                res.data = list(self._inserts)
                return res
            elif self.table_name == "procurement_changes":
                self.client.changes.extend(self._inserts)
                res.data = list(self._inserts)
                return res
        elif self.table_name == "bids":
            bid_id = self._filters.get("id")
            bid = self.client.bids.get(bid_id)
            res.data = [dict(bid)] if bid else []
            return res
        elif self.table_name == "procurement_update_reviews":
            bid_id = self._filters.get("bid_id")
            matching = [r for r in self.client.reviews if bid_id is None or r.get("bid_id") == bid_id]
            res.data = matching
            return res
        elif self.table_name == "procurement_update_review_documents":
            if "review_id" in self._filters:
                rid = self._filters["review_id"]
                res.data = [d for d in self.client.review_documents if d.get("review_id") == rid]
            elif "review_id" in self._in_filters:
                rids = set(self._in_filters["review_id"])
                res.data = [d for d in self.client.review_documents if d.get("review_id") in rids]
            else:
                res.data = list(self.client.review_documents)
            return res
        elif self.table_name == "procurement_changes":
            rid = self._filters.get("review_id")
            res.data = [c for c in self.client.changes if rid is None or c.get("review_id") == rid]
            return res
        res.data = []
        return res


class MockPostgresDatabaseClient:
    """Emulates PostgreSQL row-level atomic conditional UPDATE behavior for PostgREST."""
    def __init__(self, initial_bids: dict):
        self.bids = copy.deepcopy(initial_bids)
        self.reviews: list[dict] = []
        self.review_documents: list[dict] = []
        self.changes: list[dict] = []

    def table(self, name: str):
        return MockTableQuery(self, name)


class TestAtomicOptimisticConcurrency(unittest.TestCase):
    """Proof 2: Atomic optimistic concurrency proof at persistence layer.
    Uses TWO independent PCIDatabaseStorage instances against the same
    persisted database state, without relying on threading.Lock."""

    def test_two_independent_database_instances_atomic_concurrency(self):
        mock_db = MockPostgresDatabaseClient(
            initial_bids={101: {"id": 101, "organization_id": "org-atomic", "procurement_revision": 0, "procurement_truth_status": "governed"}}
        )
        storage_a = pci.PCIDatabaseStorage(client=mock_db)
        storage_b = pci.PCIDatabaseStorage(client=mock_db)

        # Worker A and Worker B both read revision 0
        state_a = storage_a.get_procurement_state(101)
        state_b = storage_b.get_procurement_state(101)
        self.assertEqual(state_a["procurement_revision"], 0)
        self.assertEqual(state_b["procurement_revision"], 0)

        # Build revision 1 update
        doc = [{"name": "Addendum 1.pdf", "content_hash": "hash_add1"}]
        c = [pci.FactChange(
            change_type=pci.CHANGE_SUPERSEDES,
            fact_type="DEADLINE",
            entity_id="deadline.submission",
            before_value="2026-10-22",
            after_value="2026-10-29",
            source_document="Addendum 1.pdf",
            source_hash="hash_add1",
        )]
        changeset = pci.ProcurementChangeSet(1, 0, doc, c)
        rev1 = pci.ProcurementRevision(1, "bid-101-rev-1", "bid-101-rev-0", 1, "2026-10-05", doc, changeset, "fp_1", True)

        # Worker A applies with expected_base_revision=0 -> succeeds
        storage_a.persist_revision(101, "org-atomic", rev1, expected_base_revision=0)
        self.assertEqual(mock_db.bids[101]["procurement_revision"], 1)

        # Worker B attempts to apply with expected_base_revision=0 -> fails atomically at DB layer
        with self.assertRaises(pci.StaleRevisionError):
            storage_b.persist_revision(101, "org-atomic", rev1, expected_base_revision=0)

        # Invariant: final procurement revision incremented exactly once (0 -> 1)
        self.assertEqual(mock_db.bids[101]["procurement_revision"], 1)
        # Invariant: only Worker A's review and changes were persisted
        self.assertEqual(len(mock_db.reviews), 1)
        self.assertEqual(len(mock_db.changes), 1)


if __name__ == "__main__":
    unittest.main()
