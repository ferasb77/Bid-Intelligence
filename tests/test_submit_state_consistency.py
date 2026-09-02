"""
tests/test_submit_state_consistency.py

Focused deterministic unit tests for evaluate_submission_state() and
Stage 5 SUBMIT state consistency.
All tests are offline: no Anthropic API, no network, no Streamlit rendering.
"""
import unittest
from unittest.mock import MagicMock, patch

from evaluator import (
    evaluate_submission_state,
    READY_DOC_STATUSES,
    ATTESTATION_KEYS,
)


def _all_attestations_true() -> dict[str, bool]:
    """Helper returning all 4 attestations checked."""
    return {k: True for k in ATTESTATION_KEYS}


class TestSubmissionStateEvaluator(unittest.TestCase):
    """
    Test matrix A through M as specified in the directive.
    """

    # A. Mandatory PASS, required docs ready, all attestations true -> READY_TO_SUBMIT, can_submit=True
    def test_A_mandatory_pass_docs_ready_attestations_true(self):
        reqs = [{"category": "Mandatory", "qual_status": "PASS"}]
        docs = [{"doc_type": "Submission", "mandatory": 1, "status": "Uploaded"}]
        atts = _all_attestations_true()

        res = evaluate_submission_state(reqs, docs, atts)
        self.assertEqual(res["status"], "READY_TO_SUBMIT")
        self.assertTrue(res["can_submit"])
        self.assertEqual(len(res["blockers"]), 0)
        self.assertEqual(res["counts"]["mandatory_pass"], 1)
        self.assertEqual(res["counts"]["required_documents_ready"], 1)
        self.assertEqual(res["counts"]["unchecked_attestations"], 0)

    # B. Mandatory FAIL -> NOT_READY, can_submit=False
    def test_B_mandatory_fail_blocks_submission(self):
        reqs = [{"category": "Mandatory", "qual_status": "FAIL"}]
        docs = [{"doc_type": "Submission", "mandatory": 1, "status": "Uploaded"}]
        atts = _all_attestations_true()

        res = evaluate_submission_state(reqs, docs, atts)
        self.assertEqual(res["status"], "NOT_READY")
        self.assertFalse(res["can_submit"])
        self.assertTrue(any("FAIL" in b for b in res["blockers"]))
        self.assertEqual(res["counts"]["mandatory_fail"], 1)

    # C. Mandatory UNKNOWN -> NOT_READY, can_submit=False
    def test_C_mandatory_unknown_blocks_submission(self):
        reqs = [{"category": "Mandatory", "qual_status": "UNKNOWN"}]
        docs = [{"doc_type": "Submission", "mandatory": 1, "status": "Uploaded"}]
        atts = _all_attestations_true()

        res = evaluate_submission_state(reqs, docs, atts)
        self.assertEqual(res["status"], "NOT_READY")
        self.assertFalse(res["can_submit"])
        self.assertTrue(any("UNKNOWN" in b for b in res["blockers"]))
        self.assertEqual(res["counts"]["mandatory_unknown"], 1)

    # D. Mandatory qual_status missing / None -> NOT_READY
    def test_D_mandatory_qual_status_missing_blocks_submission(self):
        reqs = [{"category": "Mandatory"}]  # qual_status missing
        docs = [{"doc_type": "Submission", "mandatory": 1, "status": "Uploaded"}]
        atts = _all_attestations_true()

        res = evaluate_submission_state(reqs, docs, atts)
        self.assertEqual(res["status"], "NOT_READY")
        self.assertFalse(res["can_submit"])
        self.assertTrue(any("UNKNOWN" in b for b in res["blockers"]))
        self.assertEqual(res["counts"]["mandatory_unknown"], 1)

    # E. Required document Expected (not in READY_DOC_STATUSES) -> NOT_READY
    def test_E_required_document_expected_blocks_submission(self):
        reqs = [{"category": "Mandatory", "qual_status": "PASS"}]
        docs = [{"doc_type": "Submission", "mandatory": 1, "status": "Expected"}]
        atts = _all_attestations_true()

        res = evaluate_submission_state(reqs, docs, atts)
        self.assertEqual(res["status"], "NOT_READY")
        self.assertFalse(res["can_submit"])
        self.assertTrue(any("Required Submission Document" in b for b in res["blockers"]))
        self.assertEqual(res["counts"]["required_documents_missing"], 1)

    # F. Required document Uploaded -> no document blocker
    def test_F_required_document_uploaded_clears_doc_blocker(self):
        for status in ("Uploaded", "Approved", "Complete", "Submitted"):
            reqs = [{"category": "Mandatory", "qual_status": "PASS"}]
            docs = [{"doc_type": "Submission", "mandatory": 1, "status": status}]
            atts = _all_attestations_true()

            res = evaluate_submission_state(reqs, docs, atts)
            self.assertEqual(res["status"], "READY_TO_SUBMIT", f"Failed for status: {status}")
            self.assertTrue(res["can_submit"])
            self.assertEqual(res["counts"]["required_documents_missing"], 0)

    # G. Document mandatory=None -> NOT_READY
    def test_G_document_mandatory_none_blocks_submission(self):
        reqs = [{"category": "Mandatory", "qual_status": "PASS"}]
        docs = [{"doc_type": "Submission", "mandatory": None, "status": "Uploaded"}]
        atts = _all_attestations_true()

        res = evaluate_submission_state(reqs, docs, atts)
        self.assertEqual(res["status"], "NOT_READY")
        self.assertFalse(res["can_submit"])
        self.assertTrue(any("UNKNOWN mandatory status" in b for b in res["blockers"]))
        self.assertEqual(res["counts"]["unknown_document_mandatory"], 1)

    # H. Optional document missing/not uploaded -> does NOT block
    def test_H_optional_document_missing_does_not_block(self):
        reqs = [{"category": "Mandatory", "qual_status": "PASS"}]
        docs = [
            {"doc_type": "Submission", "mandatory": 1, "status": "Uploaded"},
            {"doc_type": "Submission", "mandatory": 0, "status": "Expected"},  # optional & missing
        ]
        atts = _all_attestations_true()

        res = evaluate_submission_state(reqs, docs, atts)
        self.assertEqual(res["status"], "READY_TO_SUBMIT")
        self.assertTrue(res["can_submit"])
        self.assertEqual(len(res["blockers"]), 0)

    # I. All evidence ready but one attestation false -> NOT_READY
    def test_I_unchecked_attestation_blocks_submission(self):
        for key in ATTESTATION_KEYS:
            reqs = [{"category": "Mandatory", "qual_status": "PASS"}]
            docs = [{"doc_type": "Submission", "mandatory": 1, "status": "Uploaded"}]
            atts = _all_attestations_true()
            atts[key] = False  # uncheck one

            res = evaluate_submission_state(reqs, docs, atts)
            self.assertEqual(res["status"], "NOT_READY", f"Failed for unchecked attestation: {key}")
            self.assertFalse(res["can_submit"])
            self.assertEqual(res["counts"]["unchecked_attestations"], 1)

    # J. Invariants:
    # No READY_TO_SUBMIT with can_submit=False
    # No READY_WITH_WARNINGS with can_submit=False
    def test_J_status_invariants(self):
        # Case 1: with blockers
        res_blocked = evaluate_submission_state(
            requirements=[{"category": "Mandatory", "qual_status": "FAIL"}],
            documents=[],
            attestations=_all_attestations_true(),
        )
        self.assertEqual(res_blocked["status"], "NOT_READY")
        self.assertFalse(res_blocked["can_submit"])

        # Case 2: with warning only
        res_warn = evaluate_submission_state(
            requirements=[{"category": "Mandatory", "qual_status": "PASS"}],
            documents=[],
            attestations=_all_attestations_true(),
            warnings=["Advisory warning"],
        )
        self.assertEqual(res_warn["status"], "READY_WITH_WARNINGS")
        self.assertTrue(res_warn["can_submit"])

        # Case 3: clean ready
        res_ready = evaluate_submission_state(
            requirements=[{"category": "Mandatory", "qual_status": "PASS"}],
            documents=[],
            attestations=_all_attestations_true(),
        )
        self.assertEqual(res_ready["status"], "READY_TO_SUBMIT")
        self.assertTrue(res_ready["can_submit"])

    # K. No blockers + one explicit synthetic non-blocking warning -> READY_WITH_WARNINGS, can_submit=True
    def test_K_non_blocking_warning_yields_ready_with_warnings(self):
        reqs = [{"category": "Mandatory", "qual_status": "PASS"}]
        docs = [{"doc_type": "Submission", "mandatory": 1, "status": "Uploaded"}]
        atts = _all_attestations_true()
        warns = ["Consider adding executive summary polish."]

        res = evaluate_submission_state(reqs, docs, atts, warnings=warns)
        self.assertEqual(res["status"], "READY_WITH_WARNINGS")
        self.assertTrue(res["can_submit"])
        self.assertEqual(len(res["blockers"]), 0)
        self.assertEqual(res["warnings"], warns)

    # L. Document mandatory resolution:
    # None -> user selects Required -> persisted 1
    # None -> user selects Optional -> persisted 0
    def test_L_document_mandatory_resolution_persistence(self):
        with patch("database.get_client") as mock_get_client:
            mock_sb = MagicMock()
            mock_get_client.return_value = mock_sb
            from database import upsert_document

            # 1. Resolve to Required (1)
            upsert_document({"id": 42, "mandatory": 1})
            mock_sb.table("documents").update.assert_called_with({"mandatory": 1})

            # 2. Resolve to Optional (0)
            mock_sb.reset_mock()
            upsert_document({"id": 42, "mandatory": 0})
            mock_sb.table("documents").update.assert_called_with({"mandatory": 0})

    # M. No submission documents, all mandatory PASS, attestations true -> must not invent document blocker
    def test_M_empty_submission_documents_does_not_invent_blocker(self):
        reqs = [{"category": "Mandatory", "qual_status": "PASS"}]
        docs = []  # No submission documents
        atts = _all_attestations_true()

        res = evaluate_submission_state(reqs, docs, atts)
        self.assertEqual(res["status"], "READY_TO_SUBMIT")
        self.assertTrue(res["can_submit"])
        self.assertEqual(len(res["blockers"]), 0)
        self.assertEqual(res["counts"]["required_documents"], 0)
        self.assertEqual(res["counts"]["required_documents_missing"], 0)

    # ── CONCERN Semantics Tests (Section 5 A-D) ──────────────────────────────
    # A. Mandatory CONCERN, all docs ready, all attestations true:
    #    NOT_READY, can_submit=False, mandatory_concern==1, mandatory_unknown==0
    def test_concern_A_mandatory_concern_blocks_submission(self):
        reqs = [{"category": "Mandatory", "qual_status": "CONCERN"}]
        docs = [{"doc_type": "Submission", "mandatory": 1, "status": "Uploaded"}]
        atts = _all_attestations_true()

        res = evaluate_submission_state(reqs, docs, atts)
        self.assertEqual(res["status"], "NOT_READY")
        self.assertFalse(res["can_submit"])
        self.assertEqual(res["counts"]["mandatory_concern"], 1)
        self.assertEqual(res["counts"]["mandatory_unknown"], 0)

    # B. Mandatory CONCERN blocker text contains CONCERN and does not contain UNKNOWN for that requirement
    def test_concern_B_blocker_text_contains_concern_not_unknown(self):
        reqs = [{"category": "Mandatory", "qual_status": "CONCERN"}]
        docs = [{"doc_type": "Submission", "mandatory": 1, "status": "Uploaded"}]
        atts = _all_attestations_true()

        res = evaluate_submission_state(reqs, docs, atts)
        self.assertEqual(len(res["blockers"]), 1)
        self.assertIn("CONCERN", res["blockers"][0])
        self.assertNotIn("UNKNOWN", res["blockers"][0])

    # C. Mixed mandatory states: PASS, CONCERN, FAIL, UNKNOWN
    def test_concern_C_mixed_mandatory_states_counts(self):
        reqs = [
            {"category": "Mandatory", "qual_status": "PASS"},
            {"category": "Mandatory", "qual_status": "CONCERN"},
            {"category": "Mandatory", "qual_status": "FAIL"},
            {"category": "Mandatory", "qual_status": "UNKNOWN"},
        ]
        docs = [{"doc_type": "Submission", "mandatory": 1, "status": "Uploaded"}]
        atts = _all_attestations_true()

        res = evaluate_submission_state(reqs, docs, atts)
        counts = res["counts"]
        self.assertEqual(counts["mandatory_requirements"], 4)
        self.assertEqual(counts["mandatory_pass"], 1)
        self.assertEqual(counts["mandatory_concern"], 1)
        self.assertEqual(counts["mandatory_fail"], 1)
        self.assertEqual(counts["mandatory_unknown"], 1)

    # D. Count invariant: pass + concern + fail + unknown == mandatory_requirements
    def test_concern_D_count_invariant(self):
        reqs = [
            {"category": "Mandatory", "qual_status": "PASS"},
            {"category": "Mandatory", "qual_status": "PASS"},
            {"category": "Mandatory", "qual_status": "CONCERN"},
            {"category": "Mandatory", "qual_status": "FAIL"},
            {"category": "Mandatory", "qual_status": "UNKNOWN"},
            {"category": "Mandatory"},  # missing qual_status -> counts as UNKNOWN
            {"category": "Rated", "qual_status": "CONCERN"},  # Non-mandatory must not count
        ]
        res = evaluate_submission_state(reqs, [], _all_attestations_true())
        counts = res["counts"]
        mand_sum = (
            counts["mandatory_pass"]
            + counts["mandatory_concern"]
            + counts["mandatory_fail"]
            + counts["mandatory_unknown"]
        )
        self.assertEqual(mand_sum, counts["mandatory_requirements"])
        self.assertEqual(counts["mandatory_requirements"], 6)


if __name__ == "__main__":
    unittest.main()
