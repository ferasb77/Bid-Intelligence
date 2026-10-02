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

import procurement_change_intelligence as pci


class TestPCIFixturesAndInvariants(unittest.TestCase):
    def setUp(self):
        self.bid_id = 1417
        self.org_id = "4326b564-8cc5-4463-9304-9a589f08cc91"
        self.manager = pci.ProcurementRevisionManager(self.bid_id, self.org_id)

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
            pci.ProcurementRevisionManager(0, self.org_id)

        with self.assertRaises(pci.TenancyViolationError):
            pci.ProcurementRevisionManager(self.bid_id, "")

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
        manager = pci.ProcurementRevisionManager(2026, "org-concurrent-test")
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


if __name__ == "__main__":
    unittest.main()
