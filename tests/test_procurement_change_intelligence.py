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
        rfp_docs = [{"name": "City_of_Calgary_RFP_26_1610.pdf", "content_hash": "hash_rfp_main", "document_id": 100}]
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

        addendum_doc = [{"name": "Addendum 1.pdf", "content_hash": "hash_addendum_1", "document_id": 101}]
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

        addendum_doc = [{"name": "Addendum 1 - Criteria Update.pdf", "content_hash": "hash_addendum_criteria", "document_id": 102}]
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

        qa_doc = [{"name": "Clarification Q&A #1.pdf", "content_hash": "hash_qa_1", "document_id": 103}]
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

        replace_doc = [{"name": "Addendum 2 - Replacement Appendix D.xlsx", "content_hash": "hash_pricing_v2", "document_id": 104}]
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

        addendum_doc = [{"name": "Addendum 1.pdf", "content_hash": "hash_addendum_1", "document_id": 101}]
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
        doc3 = [{"name": "Addendum 3.pdf", "content_hash": "hash_add_3", "document_id": 107}]
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
        doc2 = [{"name": "Addendum 2.pdf", "content_hash": "hash_add_2", "document_id": 106}]
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
        doc1 = [{"name": "Addendum 1.pdf", "content_hash": "hash_add1", "document_id": 108}]
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
        doc2 = [{"name": "Addendum 2.pdf", "content_hash": "hash_add2", "document_id": 109}]
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

        notice_doc = [{"name": "Informal Q&A Notice.pdf", "content_hash": "hash_informal_qa", "document_id": 110}]
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

        doc = [{"name": "Addendum 1 - Schedule Only.pdf", "content_hash": "hash_sched_only", "document_id": 111}]
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
        doc = [{"name": "Addendum 1.pdf", "content_hash": "hash_add_x", "document_id": 112}]
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

        doc1 = [{"name": "Addendum 1.pdf", "content_hash": "hash_concur_1", "document_id": 113}]
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
        doc2 = [{"name": "Addendum 2.pdf", "content_hash": "hash_concur_2", "document_id": 114}]
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
        rfp_docs = [{"name": "RFP.pdf", "content_hash": "hash_rfp", "document_id": 200}]
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
            doc = [{"name": f"Addendum_{thread_id}.pdf", "content_hash": f"hash_worker_{thread_id}", "document_id": 200 + thread_id}]
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
        docs = [{"name": "RFP_Main.pdf", "content_hash": "hash_rfp_main_001", "document_id": 300}]
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

        doc1 = [{"name": "Addendum 1.pdf", "content_hash": "hash_add_001", "document_id": 301}]
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

        doc1 = [{"name": "Addendum 1.pdf", "content_hash": "hash_add_001", "document_id": 301}]
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

        doc2 = [{"name": "Addendum 2.pdf", "content_hash": "hash_add_002", "document_id": 302}]
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

        doc1 = [{"name": "Addendum 1.pdf", "content_hash": "hash_dup_check_001", "document_id": 303}]
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

        doc1 = [{"name": "Addendum 1.pdf", "content_hash": "hash_add_001", "document_id": 301}]
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

        doc1 = [{"name": "Ambiguous Notice.pdf", "content_hash": "hash_ambig_001", "document_id": 305}]
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

        doc1 = [{"name": "Pricing_Form_v2.xlsx", "content_hash": "hash_pricing_v2", "document_id": 306}]
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
        doc3 = [{"name": "Addendum 3.pdf", "content_hash": "hash_add_003", "document_id": 308}]
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
        doc2 = [{"name": "Addendum 2.pdf", "content_hash": "hash_add_002", "document_id": 302}]
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
        self.assertEqual([r.revision_number for r in revs], [0, 2, 1])
        self.assertEqual([r.buyer_chronology_index for r in revs], [0, 2, 3])

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
        doc_info = [{"name": "Notice to Bidders.pdf", "content_hash": "hash_notice_001", "document_id": 309}]
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
        self.assertEqual(mgr.current_revision_number, 0)
        self.assertEqual(res["current_revision"], 0)
        self.assertEqual(len(mgr.get_all_revisions()), 2)

        state_rev1 = mgr.get_current_state()
        fp1 = state_rev1.state_fingerprint
        self.assertEqual(fp0, fp1)

    # 10. Revision fingerprint changes on no-op revision
    def test_durability_revision_fingerprint_changes_on_noop_revision(self):
        mgr = pci.ProcurementRevisionManager(self.bid_id, self.org_id, storage=self.storage)
        self._make_baseline(mgr)
        rev0 = mgr.get_revision(0)

        doc_info = [{"name": "Notice to Bidders.pdf", "content_hash": "hash_notice_001", "document_id": 309}]
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
        all_revs = mgr.get_all_revisions()
        self.assertEqual(len(all_revs), 2)
        rev0_again = all_revs[0]
        rev1 = all_revs[1]

        self.assertNotEqual(rev0.revision_fingerprint, rev1.revision_fingerprint)
        self.assertTrue(rev1.no_canonical_change)

    # 11. Missing content_hash fails closed
    def test_durability_missing_content_hash_fails_closed(self):
        mgr = pci.ProcurementRevisionManager(self.bid_id, self.org_id, storage=self.storage)
        bad_docs = [{"name": "Missing_Hash.pdf", "document_id": 311}]
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
        good_docs = [{"name": "Good.pdf", "content_hash": "good_hash", "document_id": 311}]
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

        doc_a = [{"name": "Addendum A.pdf", "content_hash": "hash_a", "document_id": 312}]
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
        doc_b = [{"name": "Addendum B.pdf", "content_hash": "hash_b", "document_id": 313}]
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
        rfp_docs = [{"name": "RFP.pdf", "content_hash": "hash_rfp_c", "document_id": 320}]
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
            doc = [{"name": f"Addendum_{worker_id}.pdf", "content_hash": f"hash_worker_{worker_id}", "document_id": 320 + worker_id}]
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
        rfp_docs = [{"name": "RFP.pdf", "content_hash": "hash_m010_rfp", "document_id": 400}]
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
        self.assertEqual(chg["entity_type"], "other")
        self.assertEqual(chg["new_value"]["fact_type"], "DEADLINE")
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


class MockRpcQuery:
    def __init__(self, client, fn_name: str, params: dict):
        self.client = client
        self.fn_name = fn_name
        self.params = params

    def execute(self):
        res = MagicMock()
        res.data = self.client.execute_rpc(self.fn_name, self.params)
        return res


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
        if self._update_data is not None:
            if self.table_name == "bids":
                bid_id = self._filters.get("id")
                bid = self.client.bids.get(bid_id)
                if not bid:
                    res.data = []
                    return res
                for col, expected_val in self._filters.items():
                    if col == "id":
                        continue
                    if bid.get(col) != expected_val:
                        res.data = []
                        return res
                bid.update(self._update_data)
                res.data = [dict(bid)]
                return res
            elif self.table_name == "procurement_update_reviews":
                rid = self._filters.get("id")
                matching = [r for r in self.client.reviews if rid is None or r.get("id") == rid]
                for r in matching:
                    r.update(self._update_data)
                res.data = matching
                return res
            elif self.table_name == "procurement_changes":
                rid = self._filters.get("review_id")
                cid = self._filters.get("id")
                matching = [
                    c for c in self.client.changes
                    if (rid is None or c.get("review_id") == rid)
                    and (cid is None or c.get("id") == cid)
                ]
                for c in matching:
                    c.update(self._update_data)
                res.data = matching
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
                for item in self._inserts:
                    item_id = len(self.client.changes) + 1
                    item_with_id = dict(item, id=item_id)
                    self.client.changes.append(item_with_id)
                res.data = list(self.client.changes[-len(self._inserts):])
                return res
            elif self.table_name == "documents":
                for item in self._inserts:
                    item_id = item.get("id") or (len(self.client.documents) + 1)
                    item_with_id = dict(item, id=item_id)
                    self.client.documents.append(item_with_id)
                res.data = list(self.client.documents[-len(self._inserts):])
                return res

        elif self.table_name == "bids":
            bid_id = self._filters.get("id")
            bid = self.client.bids.get(bid_id)
            res.data = [dict(bid)] if bid else []
            return res
        elif self.table_name == "documents":
            if "id" in self._in_filters:
                req_ids = set(self._in_filters["id"])
                res.data = [d for d in self.client.documents if d.get("id") in req_ids]
            elif "id" in self._filters:
                req_id = self._filters["id"]
                res.data = [d for d in self.client.documents if d.get("id") == req_id]
            else:
                res.data = list(self.client.documents)
            return res
        elif self.table_name == "procurement_update_reviews":
            bid_id = self._filters.get("bid_id")
            rid = self._filters.get("id")
            matching = [
                r for r in self.client.reviews
                if (bid_id is None or r.get("bid_id") == bid_id)
                and (rid is None or r.get("id") == rid)
            ]
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
            cid = self._filters.get("id")
            matching = [
                c for c in self.client.changes
                if (rid is None or c.get("review_id") == rid)
                and (cid is None or c.get("id") == cid)
            ]
            res.data = matching
            return res

        res.data = []
        return res


class MockPostgresDatabaseClient:
    """Emulates PostgreSQL Migration 010 schema and RPC behavior for PostgREST."""
    def __init__(self, initial_bids: dict, initial_documents: list[dict] | None = None):
        self.bids = copy.deepcopy(initial_bids)
        self.documents = list(initial_documents or [])
        self.reviews: list[dict] = []
        self.review_documents: list[dict] = []
        self.changes: list[dict] = []

    def table(self, name: str):
        return MockTableQuery(self, name)

    def rpc(self, fn_name: str, params: dict):
        return MockRpcQuery(self, fn_name, params)

    def execute_rpc(self, fn_name: str, params: dict) -> list[dict]:
        if fn_name == "create_procurement_update_review":
            bid_id = params.get("p_bid_id")
            org_id = params.get("p_organization_id")
            review_kind = params.get("p_review_kind")
            buyer_update_type = params.get("p_buyer_update_type")
            buyer_issued_date = params.get("p_buyer_issued_date")
            doc_ids = params.get("p_document_ids") or []
            doc_roles = params.get("p_document_roles") or []
            idempotency_key = params.get("p_idempotency_key")

            if idempotency_key:
                for r in self.reviews:
                    if r.get("idempotency_key") == idempotency_key and r.get("status") != "failed":
                        return [{"review_id": r["id"], "is_new": False}]

            bid = self.bids.get(bid_id, {})
            current_rev = bid.get("procurement_revision", 0)
            rid = len(self.reviews) + 1
            review = {
                "id": rid,
                "bid_id": bid_id,
                "organization_id": org_id,
                "review_kind": review_kind,
                "buyer_update_type": buyer_update_type,
                "buyer_issued_date": buyer_issued_date,
                "status": "analyzing",
                "base_procurement_revision": current_rev,
                "resulting_procurement_revision": None,
                "no_canonical_change": False,
                "document_set_digest": f"digest_{rid}",
                "idempotency_key": idempotency_key,
            }
            self.reviews.append(review)

            for did, role in zip(doc_ids, doc_roles):
                doc_obj = next((d for d in self.documents if d.get("id") == did), None)
                dhash = doc_obj.get("content_hash") if doc_obj else f"hash_{did}"
                self.review_documents.append({
                    "review_id": rid,
                    "document_id": did,
                    "role": role,
                    "document_hash": dhash,
                    "organization_id": org_id,
                })
            return [{"review_id": rid, "is_new": True}]

        elif fn_name == "record_change_review_decision":
            change_id = params.get("p_change_id")
            decision = params.get("p_decision")
            actor = params.get("p_actor_user_id")
            note = params.get("p_review_note")

            change = next((c for c in self.changes if c.get("id") == change_id), None)
            if not change:
                raise Exception(f"change_not_found: {change_id}")
            if change.get("applied_at"):
                raise Exception("change_already_applied")

            change["review_decision"] = decision
            change["decided_by_user_id"] = actor
            change["review_note"] = note
            return [{"change_id": change_id, "review_decision": decision}]

        elif fn_name == "apply_procurement_update_review":
            review_id = params.get("p_review_id")
            expected_base = params.get("p_expected_base_revision")
            actor = params.get("p_actor_user_id")

            review = next((r for r in self.reviews if r.get("id") == review_id), None)
            if not review:
                raise Exception("review_not_found")

            bid_id = review.get("bid_id")
            bid = self.bids.get(bid_id)
            if not bid:
                raise Exception(f"bid_not_found: {bid_id}")

            current_rev = bid.get("procurement_revision", 0)
            truth_status = bid.get("procurement_truth_status", "ungoverned")

            if expected_base is not None and expected_base != current_rev:
                raise Exception("stale_revision: current revision does not match expected_base_revision")

            if review.get("status") == "applied":
                return [{"resulting_revision": review.get("resulting_procurement_revision"), "applied_change_count": 0}]

            if review.get("status") not in ("ready_for_review", "reviewed"):
                raise Exception(f"review_not_reviewable: status is {review.get('status')}")

            if review.get("review_kind") == "baseline" and truth_status == "governed":
                raise Exception("baseline_already_governed")
            if review.get("review_kind") == "buyer_update" and truth_status != "governed":
                raise Exception("baseline_not_governed")

            pending_count = sum(1 for c in self.changes if c.get("review_id") == review_id and c.get("review_decision") == "pending")
            if pending_count > 0:
                raise Exception("incomplete_review_decisions")

            canonical_count = sum(1 for c in self.changes if c.get("review_id") == review_id and c.get("review_decision") == "approved" and c.get("canonical_effect") == "canonical_change")
            if canonical_count > 0:
                new_rev = current_rev + 1
                no_canonical = False
            else:
                new_rev = current_rev
                no_canonical = True

            bid["procurement_revision"] = new_rev
            if review.get("review_kind") == "baseline":
                bid["procurement_truth_status"] = "governed"

            review["status"] = "applied"
            review["resulting_procurement_revision"] = new_rev
            review["no_canonical_change"] = no_canonical

            applied_count = 0
            for c in self.changes:
                if c.get("review_id") == review_id and c.get("review_decision") == "approved":
                    c["applied_at"] = "2026-10-02T12:00:00Z"
                    c["procurement_revision"] = new_rev
                    applied_count += 1

            return [{"resulting_revision": new_rev, "applied_change_count": applied_count}]

        raise NotImplementedError(f"Mock RPC {fn_name} not implemented")


class TestAtomicOptimisticConcurrency(unittest.TestCase):
    """Proof 2: Atomic optimistic concurrency proof at persistence layer.
    Uses TWO independent PCIDatabaseStorage instances against the same
    persisted database state, without relying on threading.Lock."""

    def test_two_independent_database_instances_atomic_concurrency(self):
        mock_db = MockPostgresDatabaseClient(
            initial_bids={101: {"id": 101, "organization_id": "org-atomic", "procurement_revision": 0, "procurement_truth_status": "governed"}},
            initial_documents=[{"id": 501, "name": "Addendum 1.pdf", "content_hash": "hash_add1"}]
        )
        storage_a = pci.PCIDatabaseStorage(client=mock_db)
        storage_b = pci.PCIDatabaseStorage(client=mock_db)

        # Worker A and Worker B both read revision 0
        state_a = storage_a.get_procurement_state(101)
        state_b = storage_b.get_procurement_state(101)
        self.assertEqual(state_a["procurement_revision"], 0)
        self.assertEqual(state_b["procurement_revision"], 0)

        # Build revision 1 update
        doc = [{"name": "Addendum 1.pdf", "content_hash": "hash_add1", "document_id": 501}]
        c = [pci.FactChange(
            change_type=pci.CHANGE_SUPERSEDES,
            fact_type="DEADLINE",
            entity_id="deadline.submission",
            before_value="2026-10-22",
            after_value="2026-10-29",
            source_document="Addendum 1.pdf",
            source_hash="hash_add1",
            source_document_id=501,
        )]
        changeset = pci.ProcurementChangeSet(1, 0, doc, c)
        rev1_a = pci.ProcurementRevision(1, "bid-101-rev-1-worker-a", "bid-101-rev-0", 1, "2026-10-05", doc, changeset, "fp_1a", True)
        rev1_b = pci.ProcurementRevision(1, "bid-101-rev-1-worker-b", "bid-101-rev-0", 1, "2026-10-05", doc, changeset, "fp_1b", True)

        # Worker A applies with expected_base_revision=0 -> succeeds
        storage_a.persist_revision(101, "org-atomic", rev1_a, expected_base_revision=0)
        self.assertEqual(mock_db.bids[101]["procurement_revision"], 1)

        # Worker B attempts to apply with expected_base_revision=0 -> fails atomically at DB layer via apply RPC
        with self.assertRaises(pci.StaleRevisionError):
            storage_b.persist_revision(101, "org-atomic", rev1_b, expected_base_revision=0)

        # Invariant: final procurement revision incremented exactly once (0 -> 1)
        self.assertEqual(mock_db.bids[101]["procurement_revision"], 1)
        # Invariant: only Worker A's review and changes were applied
        applied_reviews = [r for r in mock_db.reviews if r.get("status") == "applied"]
        applied_changes = [ch for ch in mock_db.changes if ch.get("applied_at") is not None]
        self.assertEqual(len(applied_reviews), 1)
        self.assertEqual(len(applied_changes), 1)


class TestPCIA2GovernedApplyAndDurableChronology(unittest.TestCase):
    """PCI-A.2 Regression tests verifying:
    1. Governed apply atomic failure protection (bids.procurement_revision never touched if RPC fails)
    2. Real integer document_id fail-closed enforcement
    3. Multi-document buyer update (primary and replacement) persisted with valid roles
    4. Out-of-order rehydration preserves buyer chronology
    5. Unresolved chronology routes changes to human review (REVIEW_STATUS_HUMAN_REVIEW_REQUIRED)
    """

    def test_governed_apply_atomic_failure_leaves_revision_untouched(self):
        """Failure before or during apply_procurement_update_review leaves bids.procurement_revision untouched."""
        mock_db = MockPostgresDatabaseClient(
            initial_bids={701: {"id": 701, "organization_id": "org-pcia2", "procurement_revision": 2, "procurement_truth_status": "governed"}},
            initial_documents=[{"id": 801, "name": "Addendum 3.pdf", "content_hash": "hash_add3"}]
        )
        storage = pci.PCIDatabaseStorage(client=mock_db)

        doc = [{"name": "Addendum 3.pdf", "content_hash": "hash_add3", "document_id": 801}]
        changes = [pci.FactChange(
            change_type=pci.CHANGE_SUPERSEDES,
            fact_type="DEADLINE",
            entity_id="deadline.submission",
            before_value="2026-11-01",
            after_value="2026-11-15",
            source_document="Addendum 3.pdf",
            source_hash="hash_add3",
            source_document_id=801,
        )]
        changeset = pci.ProcurementChangeSet(3, 2, doc, changes)
        rev3 = pci.ProcurementRevision(3, "bid-701-rev-3", "bid-701-rev-2", 3, "2026-10-15", doc, changeset, "fp_3", True)

        # Force failure during apply_procurement_update_review
        orig_rpc = mock_db.execute_rpc
        def failing_rpc(fn_name, params):
            if fn_name == "apply_procurement_update_review":
                raise Exception("simulated_db_apply_failure")
            return orig_rpc(fn_name, params)

        mock_db.execute_rpc = failing_rpc

        with self.assertRaises(pci.PCIEngineError) as ctx:
            storage.persist_revision(701, "org-pcia2", rev3, expected_base_revision=2)
        self.assertIn("Governed apply failed", str(ctx.exception))

        # Proof: bids.procurement_revision remained untouched at 2!
        self.assertEqual(mock_db.bids[701]["procurement_revision"], 2)
        # Staged review was never applied
        applied_reviews = [r for r in mock_db.reviews if r.get("status") == "applied"]
        self.assertEqual(len(applied_reviews), 0)

    def test_real_document_id_required_fails_closed(self):
        """Missing or non-int document_id raises ValueError immediately."""
        storage = pci.InMemoryPCIStorage()
        mgr = pci.ProcurementRevisionManager(801, "org-test", storage=storage)

        # Baseline with missing document_id
        missing_id_docs = [{"name": "RFP.pdf", "content_hash": "hash_rfp"}]
        facts = [pci.FactChange(
            change_type=pci.CHANGE_ADDS,
            fact_type="DEADLINE",
            entity_id="deadline.submission",
            before_value=None,
            after_value="2026-10-22",
            source_document="RFP.pdf",
            source_hash="hash_rfp",
        )]
        with self.assertRaises(ValueError) as ctx:
            mgr.create_baseline_revision(missing_id_docs, facts)
        self.assertIn("Missing required integer document_id", str(ctx.exception))

        # Baseline with string document_id
        string_id_docs = [{"name": "RFP.pdf", "content_hash": "hash_rfp", "document_id": "123"}]
        with self.assertRaises(ValueError) as ctx:
            mgr.create_baseline_revision(string_id_docs, facts)
        self.assertIn("Missing required integer document_id", str(ctx.exception))

    def test_multi_document_buyer_update_primary_and_replacement(self):
        """Addendum update spanning primary letter and replacement pricing form preserves distinct roles."""
        mock_db = MockPostgresDatabaseClient(
            initial_bids={901: {"id": 901, "organization_id": "org-multi", "procurement_revision": 0, "procurement_truth_status": "governed"}},
            initial_documents=[
                {"id": 91, "name": "Addendum 2.pdf", "content_hash": "hash_add2"},
                {"id": 92, "name": "Replacement Pricing Form.xlsx", "content_hash": "hash_price_v2"},
            ]
        )
        storage = pci.PCIDatabaseStorage(client=mock_db)

        docs = [
            {"document_id": 91, "name": "Addendum 2.pdf", "content_hash": "hash_add2", "role": "primary"},
            {"document_id": 92, "name": "Replacement Pricing Form.xlsx", "content_hash": "hash_price_v2", "role": "replacement"},
        ]
        changes = [
            pci.FactChange(
                change_type=pci.CHANGE_REPLACES,
                fact_type="ARTIFACT",
                entity_id="artifact.pricing_form",
                before_value={"name": "Pricing_Form_v1.xlsx", "content_hash": "hash_price_v1"},
                after_value={"name": "Replacement Pricing Form.xlsx", "content_hash": "hash_price_v2"},
                source_document="Replacement Pricing Form.xlsx",
                source_hash="hash_price_v2",
                source_document_id=92,
            )
        ]
        changeset = pci.ProcurementChangeSet(1, 0, docs, changes)
        rev1 = pci.ProcurementRevision(1, "bid-901-rev-1", "bid-901-rev-0", 2, "2026-10-12", docs, changeset, "fp_multi", True)

        storage.persist_revision(901, "org-multi", rev1, expected_base_revision=0)

        # Verify review documents persisted with correct roles
        self.assertEqual(len(mock_db.review_documents), 2)
        doc_roles = {d["document_id"]: d["role"] for d in mock_db.review_documents}
        self.assertEqual(doc_roles[91], "primary")
        self.assertEqual(doc_roles[92], "replacement")

        # Invariant: cannot persist if zero or multiple primaries
        bad_docs = [
            {"document_id": 91, "name": "Addendum 2.pdf", "content_hash": "hash_add2", "role": "primary"},
            {"document_id": 92, "name": "Replacement Pricing Form.xlsx", "content_hash": "hash_price_v2", "role": "primary"},
        ]
        bad_rev = pci.ProcurementRevision(2, "bid-901-rev-2", "bid-901-rev-1", 3, "2026-10-13", bad_docs, changeset, "fp_bad", True)
        with self.assertRaises(ValueError) as ctx:
            storage.persist_revision(901, "org-multi", bad_rev, expected_base_revision=1)
        self.assertIn("Review requires exactly one primary document", str(ctx.exception))

    def test_out_of_order_rehydration_preserves_buyer_chronology(self):
        """Addendum 3 uploaded before Addendum 2; rehydrated from storage strictly in buyer chronology order."""
        mock_db = MockPostgresDatabaseClient(
            initial_bids={902: {"id": 902, "organization_id": "org-chrono", "procurement_revision": 0, "procurement_truth_status": "ungoverned"}},
            initial_documents=[
                {"id": 801, "name": "RFP.pdf", "content_hash": "hash_rfp"},
                {"id": 802, "name": "Addendum 03 - Schedule.pdf", "content_hash": "hash_add3"},
                {"id": 803, "name": "Addendum 02 - Schedule.pdf", "content_hash": "hash_add2"},
            ]
        )
        storage = pci.PCIDatabaseStorage(client=mock_db)
        mgr = pci.ProcurementRevisionManager(902, "org-chrono", storage=storage)

        # Baseline
        rfp = [{"document_id": 801, "name": "RFP.pdf", "content_hash": "hash_rfp"}]
        c0 = [pci.FactChange(
            change_type=pci.CHANGE_ADDS,
            fact_type="DEADLINE",
            entity_id="deadline.submission",
            before_value=None,
            after_value="2026-10-22",
            source_document="RFP.pdf",
            source_hash="hash_rfp",
            source_document_id=801,
        )]
        mgr.create_baseline_revision(rfp, c0, buyer_issued_date="2026-10-01")

        # Upload Addendum 3 first (resulting revision 1, but buyer sequence 3)
        add3 = [{"document_id": 802, "name": "Addendum 03 - Schedule.pdf", "content_hash": "hash_add3"}]
        c3 = [pci.FactChange(
            change_type=pci.CHANGE_SUPERSEDES,
            fact_type="DEADLINE",
            entity_id="deadline.submission",
            before_value="2026-10-22",
            after_value="2026-11-20",
            source_document="Addendum 03 - Schedule.pdf",
            source_hash="hash_add3",
            source_document_id=802,
        )]
        mgr.add_buyer_update_revision(add3, c3, buyer_issued_date="2026-10-20")

        # Upload Addendum 2 later (resulting revision 2, but buyer sequence 2)
        add2 = [{"document_id": 803, "name": "Addendum 02 - Schedule.pdf", "content_hash": "hash_add2"}]
        c2 = [pci.FactChange(
            change_type=pci.CHANGE_SUPERSEDES,
            fact_type="DEADLINE",
            entity_id="deadline.submission",
            before_value="2026-10-22",
            after_value="2026-11-10",
            source_document="Addendum 02 - Schedule.pdf",
            source_hash="hash_add2",
            source_document_id=803,
        )]
        mgr.add_buyer_update_revision(add2, c2, buyer_issued_date="2026-10-10")

        # Restart process / recreate manager from persistent storage
        rehydrated_mgr = pci.ProcurementRevisionManager(902, "org-chrono", storage=storage)
        rehydrated_revs = rehydrated_mgr.get_all_revisions()

        # Invariant: Rehydrated revisions are ordered by buyer chronology: Rev 0 (seq 0) -> Addendum 2 (seq 2) -> Addendum 3 (seq 3)
        self.assertEqual([r.buyer_chronology_index for r in rehydrated_revs], [0, 2, 3])
        # Authoritative current state reflects Addendum 3 (Nov 20), not upload order
        curr_state = rehydrated_mgr.get_current_state()
        self.assertEqual(curr_state.authoritative_facts["deadline.submission"].after_value, "2026-11-20")
        self.assertEqual(curr_state.authoritative_facts["deadline.submission"].source_document, "Addendum 03 - Schedule.pdf")

    def test_unresolved_chronology_routes_to_human_review(self):
        """Ambiguous document without clear sequence flags chronology_unresolved and routes to human review."""
        mock_db = MockPostgresDatabaseClient(
            initial_bids={903: {"id": 903, "organization_id": "org-ambig", "procurement_revision": 0, "procurement_truth_status": "ungoverned"}},
            initial_documents=[
                {"id": 701, "name": "RFP.pdf", "content_hash": "hash_rfp"},
                {"id": 702, "name": "Miscellaneous_Notes.pdf", "content_hash": "hash_misc"},
            ]
        )
        storage = pci.PCIDatabaseStorage(client=mock_db)
        mgr = pci.ProcurementRevisionManager(903, "org-ambig", storage=storage)

        # Baseline
        rfp = [{"document_id": 701, "name": "RFP.pdf", "content_hash": "hash_rfp"}]
        c0 = [pci.FactChange(
            change_type=pci.CHANGE_ADDS,
            fact_type="DEADLINE",
            entity_id="deadline.submission",
            before_value=None,
            after_value="2026-10-22",
            source_document="RFP.pdf",
            source_hash="hash_rfp",
            source_document_id=701,
        )]
        mgr.create_baseline_revision(rfp, c0, buyer_issued_date="2026-10-01")

        # Ambiguous document without addendum number or date
        misc_doc = [{"document_id": 702, "name": "Miscellaneous_Notes.pdf", "content_hash": "hash_misc"}]
        c_ambig = [pci.FactChange(
            change_type=pci.CHANGE_SUPERSEDES,
            fact_type="DEADLINE",
            entity_id="deadline.submission",
            before_value="2026-10-22",
            after_value="2026-11-30",
            source_document="Miscellaneous_Notes.pdf",
            source_hash="hash_misc",
            source_document_id=702,
        )]
        res = mgr.add_buyer_update_revision(misc_doc, c_ambig)
        self.assertTrue(res["chronology_unresolved"])

        # Rehydrate and verify human review routing
        rehydrated_mgr = pci.ProcurementRevisionManager(903, "org-ambig", storage=storage)
        revs = rehydrated_mgr.get_all_revisions()
        self.assertTrue(revs[-1].chronology_unresolved)

        state = rehydrated_mgr.get_current_state()
        # Original authoritative fact remains active
        self.assertEqual(state.authoritative_facts["deadline.submission"].after_value, "2026-10-22")
        # Unresolved change routed to pending_conflicts with HUMAN_REVIEW_REQUIRED
        self.assertEqual(len(state.pending_conflicts), 1)
        conflict = state.pending_conflicts[0]
        self.assertEqual(conflict.entity_id, "deadline.submission")
        self.assertEqual(conflict.review_status, pci.REVIEW_STATUS_HUMAN_REVIEW_REQUIRED)


if __name__ == "__main__":
    unittest.main()
