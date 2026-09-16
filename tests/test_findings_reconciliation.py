"""
tests/test_findings_reconciliation.py

Deterministic tests for the Submission Package Alignment findings-layer
remediation: chunk-local observations are reconciled against package-
level truth before ever reaching the user. No live LLM calls --
analyst._call() is mocked everywhere a full audit runs one; several
tests exercise the pure, no-LLM helper functions directly.

Covers:
  * TestFindingReconciliation -- an existence/absence claim about a
    requirement is suppressed once package-wide evidence confirms the
    artifact exists (Fully OR Partially Addressed), while a genuine
    content-quality gap about the SAME requirement is preserved. A
    finding tied to a Cannot-Assess requirement is redirected to
    unresolved_items, never left in `findings`.
  * TestChunkBoundaryArtifacts -- a chunk-edge "truncated/incomplete"
    claim is suppressed unless a real, source-level extraction failure
    backs it; a generic analysis-engine failure (api_error) elsewhere in
    the package does NOT unlock it.
  * TestFindingThemeAndDedup -- the deterministic finding-theme
    classifier keeps genuinely different gaps on the same requirement
    separate, while consolidating repeated same-theme observations.
  * TestPriorityActions -- bounded at 10, established mandatory
    failures first, Proposal-Submission-stage findings only.
  * TestPartialAuditSummary -- deterministic, distinguishes confirmed
    coverage counts from genuine unknowns, correct headline, no LLM call.
  * TestChunkFailureDiagnostics -- safe, closed-vocabulary failure
    categories with filename/section, never prompt/text content.
  * TestChunkPacking -- the greedy bin-pack reduces chunk count for
    adjacent medium-sized sections without losing any text.
  * TestPdfAndUiReconciledRendering -- the PDF renders the new sections
    (Audit Findings w/ severity counts, Priority Actions, Needs
    Verification, Partial Audit Summary) and contains no stale
    contradictory finding.
"""
import json
import unittest
from unittest.mock import patch

import fitz

import analyst
import pdf_alignment


def _req(req_id, category="Rated", description="desc", weight=None):
    return {"req_id": req_id, "category": category, "description": description, "weight": weight}


def _pf(file_id, filename, text, file_type="txt"):
    return {
        "file_id": file_id, "filename": filename, "package_path": filename, "file_type": file_type,
        "text": text, "analyzable": True, "unusable_reason": None, "extraction_meta": {},
    }


def _synthesis_response():
    return json.dumps({"executive_summary": "ok", "strengths": [], "next_steps": []})


def _fake_call_with_findings(assertions_by_marker=None, findings_by_marker=None):
    """Builds a fake analyst._call(): for a chunk prompt containing a
    given marker, injects the corresponding requirement_assertions
    and/or chunk_findings. Never touches synthesis calls."""
    assertions_by_marker = assertions_by_marker or {}
    findings_by_marker = findings_by_marker or {}

    def fake_call(system, user, max_tokens=2048):
        if "requirement_assertions" not in user:
            return _synthesis_response()
        assertions, findings = [], []
        for marker, a in assertions_by_marker.items():
            if marker in user:
                assertions.append(a)
        for marker, fs in findings_by_marker.items():
            if marker in user:
                findings.extend(fs if isinstance(fs, list) else [fs])
        return json.dumps({"chunk_findings": findings, "requirement_assertions": assertions})

    return fake_call


class TestFindingReconciliation(unittest.TestCase):
    def test_partially_addressed_with_evidence_elsewhere_suppresses_local_missing_claim(self):
        """M2 Partially Addressed, Schedule A exists elsewhere -> the
        local 'Schedule A missing' finding is suppressed even though
        overall M2 coverage is only Partially Addressed."""
        primary = _pf("p1", "Technical Proposal.txt", "PRIMARY_MARKER: general narrative with no schedule mention.")
        schedule = _pf("s1", "Schedule A.pdf", "SCHEDULE_MARKER: Schedule A safeguards described here.")
        fake_call = _fake_call_with_findings(
            assertions_by_marker={
                "SCHEDULE_MARKER": {"req_id": "M2", "coverage": "Partially Addressed", "confidence": "Medium",
                                     "evidence": "Schedule A present but safeguards limited"},
            },
            findings_by_marker={
                "PRIMARY_MARKER": [{"severity": "High", "stage": "Proposal Submission", "category": "Mandatory",
                                     "req_id": "M2", "title": "Schedule A absent",
                                     "issue": "Schedule A is missing from this section of the proposal.",
                                     "recommendation": "Attach Schedule A.", "effort": "Minor edit"}],
            },
        )
        with patch("analyst._call", side_effect=fake_call):
            result = analyst.analyze_proposal_alignment_package(
                package_files=[primary, schedule], requirements=[_req("M2", category="Mandatory")],
                rfp_text="context", bid_info={"title": "T", "client": "C"},
            )
        m2_row = next(r for r in result["requirement_coverage"] if r["req_id"] == "M2")
        self.assertEqual(m2_row["coverage"], "Partially Addressed")
        self.assertFalse(any(f.get("req_id") == "M2" for f in result["findings"]),
                          f"the false 'missing' claim survived reconciliation: {result['findings']}")

    def test_quality_gap_finding_survives_reconciliation_on_partially_addressed(self):
        """M2 remains Partially Addressed because safeguards are weak --
        a genuine content-quality finding is NOT an existence claim and
        must be preserved."""
        schedule = _pf("s1", "Schedule A.pdf", "SCHEDULE_MARKER: Schedule A present with described safeguards.")
        fake_call = _fake_call_with_findings(
            assertions_by_marker={
                "SCHEDULE_MARKER": {"req_id": "M2", "coverage": "Partially Addressed", "confidence": "Medium",
                                     "evidence": "Schedule A present"},
            },
            findings_by_marker={
                "SCHEDULE_MARKER": [{"severity": "Medium", "stage": "Proposal Submission", "category": "Mandatory",
                                      "req_id": "M2", "title": "Weak safeguards",
                                      "issue": "Safeguards described for Schedule A are insufficient and lack detail.",
                                      "recommendation": "Strengthen safeguards.", "effort": "Moderate rewrite"}],
            },
        )
        with patch("analyst._call", side_effect=fake_call):
            result = analyst.analyze_proposal_alignment_package(
                package_files=[schedule], requirements=[_req("M2", category="Mandatory")],
                rfp_text="context", bid_info={"title": "T", "client": "C"},
            )
        self.assertTrue(any(
            f.get("req_id") == "M2" and "insufficient" in f.get("issue", "").lower() for f in result["findings"]
        ))

    def test_fully_addressed_removes_contradictory_absence_finding(self):
        schedule = _pf("s1", "Schedule A.pdf", "SCHEDULE_MARKER: Schedule A fully addressed here.")
        fake_call = _fake_call_with_findings(
            assertions_by_marker={
                "SCHEDULE_MARKER": {"req_id": "M2", "coverage": "Fully Addressed", "confidence": "High",
                                     "evidence": "Schedule A fully present"},
            },
            findings_by_marker={
                "SCHEDULE_MARKER": [{"severity": "High", "stage": "Proposal Submission", "category": "Mandatory",
                                      "req_id": "M2", "title": "Schedule A not provided",
                                      "issue": "Schedule A was not provided anywhere in this section.",
                                      "recommendation": "Attach Schedule A.", "effort": "Minor edit"}],
            },
        )
        with patch("analyst._call", side_effect=fake_call):
            result = analyst.analyze_proposal_alignment_package(
                package_files=[schedule], requirements=[_req("M2", category="Mandatory")],
                rfp_text="context", bid_info={"title": "T", "client": "C"},
            )
        m2_row = next(r for r in result["requirement_coverage"] if r["req_id"] == "M2")
        self.assertEqual(m2_row["coverage"], "Fully Addressed")
        self.assertFalse(any(f.get("req_id") == "M2" for f in result["findings"]))

    def test_cannot_assess_absence_claim_moves_to_unresolved_items(self):
        good = _pf("g1", "Technical Proposal.txt", "GOOD_MARKER: general narrative padding content here. " * 5)
        failed = {
            "file_id": "f1", "filename": "Corrupt.xlsx", "package_path": "Corrupt.xlsx", "file_type": "xlsx",
            "text": "", "analyzable": False, "unusable_reason": "unreadable spreadsheet", "extraction_meta": {},
        }
        fake_call = _fake_call_with_findings(
            findings_by_marker={
                "GOOD_MARKER": [{"severity": "High", "stage": "Proposal Submission", "category": "Mandatory",
                                  "req_id": "M5", "title": "Insurance missing",
                                  "issue": "Insurance declaration is missing from the proposal.",
                                  "recommendation": "Add insurance declaration.", "effort": "Minor edit"}],
            },
        )
        with patch("analyst._call", side_effect=fake_call):
            result = analyst.analyze_proposal_alignment_package(
                package_files=[good, failed],
                requirements=[_req("M5", category="Mandatory", description="Insurance declaration")],
                rfp_text="context", bid_info={"title": "T", "client": "C"},
            )
        self.assertEqual(result["status"], "incomplete")
        self.assertFalse(any(f.get("req_id") == "M5" for f in result["findings"]),
                          "a Cannot-Assess-tied finding must never remain in the normal findings list")
        self.assertTrue(any(u.get("req_id") == "M5" for u in result["unresolved_items"]))
        m5_item = next(u for u in result["unresolved_items"] if u["req_id"] == "M5")
        self.assertIn("could not be assessed", m5_item["reason"].lower())
        self.assertNotIn("is missing", m5_item["reason"].lower())

    # ── Evidence-aware Partially-Addressed suppression (pre-commit hardening) ──
    # 'Partially Addressed' alone never proves the SPECIFIC artifact a
    # finding names actually exists -- only a real keyword-level match
    # between the finding's claimed-missing artifact and the coverage
    # row's OWN evidence text counts as a contradiction.

    def test_partially_addressed_evidence_specifically_names_the_artifact_suppresses_claim(self):
        """M2 Partially Addressed, and the coverage row's own evidence
        specifically names Schedule A (by filename and in the aggregated
        evidence text) -- the 'Schedule A missing' claim is a real,
        evidence-contradicted false claim and must be suppressed."""
        schedule = _pf("s1", "AI Disclosure_Schedule A - Safeguards.docx",
                        "SCHEDULE_MARKER: Schedule A safeguards described here, though limited in scope.")
        fake_call = _fake_call_with_findings(
            assertions_by_marker={
                "SCHEDULE_MARKER": {"req_id": "M2", "coverage": "Partially Addressed", "confidence": "Medium",
                                     "evidence": "Schedule A is present but safeguards described are limited"},
            },
            findings_by_marker={
                "SCHEDULE_MARKER": [{"severity": "High", "stage": "Proposal Submission", "category": "Mandatory",
                                      "req_id": "M2", "title": "Schedule A absent",
                                      "issue": "Schedule A is missing from this section of the proposal.",
                                      "recommendation": "Attach Schedule A.", "effort": "Minor edit"}],
            },
        )
        with patch("analyst._call", side_effect=fake_call):
            result = analyst.analyze_proposal_alignment_package(
                package_files=[schedule], requirements=[_req("M2", category="Mandatory")],
                rfp_text="context", bid_info={"title": "T", "client": "C"},
            )
        m2_row = next(r for r in result["requirement_coverage"] if r["req_id"] == "M2")
        self.assertEqual(m2_row["coverage"], "Partially Addressed")
        self.assertFalse(any(f.get("req_id") == "M2" for f in result["findings"]),
                          "evidence specifically names Schedule A -- the false 'missing' claim must be suppressed")

    def test_partially_addressed_form_exists_but_signature_absent_survives(self):
        """M1 Partially Addressed because the declaration FORM exists but
        is unsigned -- the coverage row's evidence only proves the form
        exists, never that it is signed, so 'signature missing' must
        survive reconciliation."""
        declaration = _pf("d1", "Declaration Form.pdf",
                           "FORM_MARKER: Declaration form submitted as part of the package, unsigned.")
        fake_call = _fake_call_with_findings(
            assertions_by_marker={
                "FORM_MARKER": {"req_id": "M1", "coverage": "Partially Addressed", "confidence": "Medium",
                                 "evidence": "Declaration form is present in the submission"},
            },
            findings_by_marker={
                "FORM_MARKER": [{"severity": "High", "stage": "Proposal Submission", "category": "Mandatory",
                                  "req_id": "M1", "title": "Signature missing",
                                  "issue": "The signature is missing from the declaration form.",
                                  "recommendation": "Obtain a signed copy.", "effort": "Minor edit"}],
            },
        )
        with patch("analyst._call", side_effect=fake_call):
            result = analyst.analyze_proposal_alignment_package(
                package_files=[declaration], requirements=[_req("M1", category="Mandatory")],
                rfp_text="context", bid_info={"title": "T", "client": "C"},
            )
        m1_row = next(r for r in result["requirement_coverage"] if r["req_id"] == "M1")
        self.assertEqual(m1_row["coverage"], "Partially Addressed")
        self.assertTrue(any(f.get("req_id") == "M1" and "signature" in f.get("issue", "").lower()
                             for f in result["findings"]),
                         "evidence only proves the FORM exists, not that it is SIGNED -- the signature "
                         "finding must survive")

    def test_partially_addressed_pricing_exists_but_schedule_absent_survives(self):
        """F1 Partially Addressed because some pricing exists, but the
        required pricing SCHEDULE is genuinely absent -- coverage
        evidence only names a cost breakdown, never the schedule, so the
        missing-schedule finding must survive."""
        pricing = _pf("p1", "Cost Breakdown.xlsx",
                       "COST_MARKER: General cost breakdown for the engagement provided here.")
        fake_call = _fake_call_with_findings(
            assertions_by_marker={
                "COST_MARKER": {"req_id": "F1", "coverage": "Partially Addressed", "confidence": "Medium",
                                 "evidence": "Cost breakdown present in the submission"},
            },
            findings_by_marker={
                "COST_MARKER": [{"severity": "High", "stage": "Proposal Submission", "category": "Financial",
                                  "req_id": "F1", "title": "Pricing schedule absent",
                                  "issue": "The required pricing schedule is missing from the submission.",
                                  "recommendation": "Attach the pricing schedule.", "effort": "Minor edit"}],
            },
        )
        with patch("analyst._call", side_effect=fake_call):
            result = analyst.analyze_proposal_alignment_package(
                package_files=[pricing], requirements=[_req("F1", category="Financial")],
                rfp_text="context", bid_info={"title": "T", "client": "C"},
            )
        f1_row = next(r for r in result["requirement_coverage"] if r["req_id"] == "F1")
        self.assertEqual(f1_row["coverage"], "Partially Addressed")
        self.assertTrue(any(f.get("req_id") == "F1" and "schedule" in f.get("issue", "").lower()
                             for f in result["findings"]),
                         "evidence never names the pricing SCHEDULE specifically -- the missing-schedule "
                         "finding must survive, not be suppressed merely because F1 is Partially Addressed")

    def test_partially_addressed_pricing_schedule_named_in_evidence_is_suppressed(self):
        """Symmetric counterpart: when the coverage row's evidence DOES
        specifically name the pricing schedule, the same finding is a
        real contradiction and must be suppressed."""
        pricing = _pf("p1", "Pricing Schedule C.xlsx",
                       "SCHED_MARKER: Pricing schedule C included with full line-item detail.")
        fake_call = _fake_call_with_findings(
            assertions_by_marker={
                "SCHED_MARKER": {"req_id": "F1", "coverage": "Partially Addressed", "confidence": "Medium",
                                  "evidence": "Pricing schedule is present with line-item detail"},
            },
            findings_by_marker={
                "SCHED_MARKER": [{"severity": "High", "stage": "Proposal Submission", "category": "Financial",
                                   "req_id": "F1", "title": "Pricing schedule absent",
                                   "issue": "The required pricing schedule is missing from the submission.",
                                   "recommendation": "Attach the pricing schedule.", "effort": "Minor edit"}],
            },
        )
        with patch("analyst._call", side_effect=fake_call):
            result = analyst.analyze_proposal_alignment_package(
                package_files=[pricing], requirements=[_req("F1", category="Financial")],
                rfp_text="context", bid_info={"title": "T", "client": "C"},
            )
        self.assertFalse(any(f.get("req_id") == "F1" for f in result["findings"]))

    def test_evidence_aware_contradiction_check_unit(self):
        finding = {"title": "Schedule A absent", "issue": "Schedule A is missing from this section."}
        contradicting_row = {"evidence_location": "AI Disclosure_Schedule A.docx",
                              "notes": "Schedule A is present in the AI Disclosure document"}
        non_contradicting_row = {"evidence_location": "Declaration Form.pdf",
                                  "notes": "Declaration form is present in the submission"}
        self.assertTrue(analyst._package_evidence_contradicts_absence_claim(finding, contradicting_row))
        self.assertFalse(analyst._package_evidence_contradicts_absence_claim(finding, non_contradicting_row))

    def test_semantic_qualification_gate_appears_in_unresolved_mandatory_qualification_items(self):
        """Pre-commit hardening item 3 regression: a requirement that is
        NOT category=='Mandatory' but IS semantically a supplier
        qualification/eligibility gate (per the same governed cue-
        detector -- requirement_semantics.has_supplier_qualification_
        evidence -- already used for scoring exclusion) must still
        appear in unresolved_mandatory_qualification_items when Cannot
        Assess. Must never regress to a bare category=='Mandatory' test."""
        good = _pf("g1", "Technical Proposal.txt", "GOOD_MARKER: general narrative padding content here. " * 5)
        failed = {
            "file_id": "f1", "filename": "Corrupt.xlsx", "package_path": "Corrupt.xlsx", "file_type": "xlsx",
            "text": "", "analyzable": False, "unusable_reason": "unreadable spreadsheet", "extraction_meta": {},
        }
        qual_req = _req(
            "Q1", category="Supporting",
            description="Bidder must be eligible to participate under the minimum qualification criteria.",
        )
        from requirement_semantics import has_supplier_qualification_evidence
        self.assertTrue(has_supplier_qualification_evidence(qual_req),
                         "test fixture must actually trip the semantic qualification-gate cue detector")

        fake_call = _fake_call_with_findings()
        with patch("analyst._call", side_effect=fake_call):
            result = analyst.analyze_proposal_alignment_package(
                package_files=[good, failed], requirements=[qual_req],
                rfp_text="context", bid_info={"title": "T", "client": "C"},
            )
        self.assertEqual(result["status"], "incomplete")
        q1_row = next(r for r in result["requirement_coverage"] if r["req_id"] == "Q1")
        self.assertEqual(q1_row["coverage"], "Cannot Assess")
        self.assertNotEqual(q1_row.get("category"), "Mandatory")

        unresolved_mq = result["partial_summary"]["unresolved_mandatory_qualification_items"]
        self.assertTrue(
            any(u["req_id"] == "Q1" for u in unresolved_mq),
            f"non-Mandatory semantic qualification gate must appear in "
            f"unresolved_mandatory_qualification_items: {unresolved_mq}",
        )


class TestChunkBoundaryArtifacts(unittest.TestCase):
    def test_boundary_artifact_finding_suppressed_without_source_evidence(self):
        pf = _pf("p1", "Doc.txt", "MARK: content here.")
        fake_call = _fake_call_with_findings(
            findings_by_marker={
                "MARK": [{"severity": "Low", "stage": "Proposal Submission", "category": "Other", "req_id": None,
                          "title": "Possible truncation",
                          "issue": "The document appears truncated and ends abruptly at this point.",
                          "recommendation": "Review.", "effort": "Minor edit"}],
            },
        )
        with patch("analyst._call", side_effect=fake_call):
            result = analyst.analyze_proposal_alignment_package(
                package_files=[pf], requirements=[], rfp_text="context", bid_info={"title": "T", "client": "C"},
            )
        self.assertEqual(result["findings"], [])

    def test_engine_failure_does_not_enable_boundary_artifact_findings_elsewhere(self):
        """A failed chunk (api_error) in one file must not be treated as
        evidence that a DIFFERENT file's content is truncated -- engine
        failure and source-document corruption are different things."""
        failing = _pf("f1", "Failing.txt", "FAIL_MARK: some content that will fail to analyze.")
        boundary = _pf("b1", "Boundary.txt", "BOUND_MARK: some content near a boundary.")

        def fake_call(system, user, max_tokens=2048):
            if "FAIL_MARK" in user:
                raise RuntimeError("simulated api failure")
            if "requirement_assertions" not in user:
                return _synthesis_response()
            if "BOUND_MARK" in user:
                return json.dumps({
                    "chunk_findings": [{"severity": "Low", "stage": "Proposal Submission", "category": "Other",
                                         "req_id": None, "title": "Doc ends",
                                         "issue": "This section ends abruptly and the response appears incomplete.",
                                         "recommendation": "Review.", "effort": "Minor edit"}],
                    "requirement_assertions": [],
                })
            return json.dumps({"chunk_findings": [], "requirement_assertions": []})

        with patch("analyst._call", side_effect=fake_call):
            result = analyst.analyze_proposal_alignment_package(
                package_files=[failing, boundary], requirements=[],
                rfp_text="context", bid_info={"title": "T", "client": "C"},
            )
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["findings"], [])
        diag = result["coverage_metadata"]["failed_chunk_diagnostics"]
        self.assertTrue(any(d["category"] == "api_error" for d in diag))

    def test_source_level_truncation_evidence_permits_boundary_finding_for_that_file(self):
        uf = [{"filename": "Corrupt.pdf", "reason": "PDF parsing failed: file appears truncated/corrupt."}]
        finding = {"title": "Doc truncated", "issue": "The document appears truncated near the end.",
                   "proposal_location": "Corrupt.pdf — Section 1"}
        self.assertTrue(analyst._has_source_level_truncation_evidence("Corrupt.pdf", uf))
        reconciled = analyst._reconcile_findings_with_package_evidence([finding], [], uf)
        self.assertEqual(len(reconciled), 1)

    def test_unsupported_format_reason_does_not_count_as_truncation_evidence(self):
        uf = [{"filename": "Deck.pptx", "reason": "PPTX is unsupported in this version."}]
        finding = {"title": "Doc truncated", "issue": "The document appears truncated near the end.",
                   "proposal_location": "Deck.pptx — Section 1"}
        self.assertFalse(analyst._has_source_level_truncation_evidence("Deck.pptx", uf))
        reconciled = analyst._reconcile_findings_with_package_evidence([finding], [], uf)
        self.assertEqual(reconciled, [])


class TestFindingThemeAndDedup(unittest.TestCase):
    def test_different_themes_for_same_requirement_remain_separate(self):
        raw = [
            {"req_id": "F1", "category": "Financial", "severity": "High", "title": "Incomplete pricing",
             "issue": "The pricing schedule is incomplete and missing several line items.",
             "proposal_location": "A.xlsx — Sheet 1"},
            {"req_id": "F1", "category": "Financial", "severity": "Medium", "title": "Unclear assumptions",
             "issue": "The expense assumptions underlying the pricing are unclear and ambiguous.",
             "proposal_location": "A.xlsx — Sheet 1"},
            {"req_id": "F1", "category": "Financial", "severity": "Low", "title": "Unsigned declaration",
             "issue": "The subcontractor declaration form is unsigned.", "proposal_location": "A.xlsx — Sheet 1"},
        ]
        for f in raw:
            f["finding_type"] = analyst._classify_finding_theme(f)
        themes = {f["finding_type"] for f in raw}
        self.assertEqual(len(themes), 3, f"expected 3 distinct themes, got {themes}")
        deduped = analyst._deduplicate_findings(raw)
        self.assertEqual(len(deduped), 3)

    def test_duplicate_same_theme_findings_consolidate(self):
        f1 = {"req_id": "M2", "category": "Mandatory", "severity": "High", "title": "Schedule A not referenced",
              "issue": "Schedule A not referenced in this section of the proposal.", "proposal_location": "Chunk1"}
        f2 = {"req_id": "M2", "category": "Mandatory", "severity": "Medium", "title": "Schedule A not referenced",
              "issue": "Schedule A not referenced in this section of the document.", "proposal_location": "Chunk2"}
        for f in (f1, f2):
            f["finding_type"] = analyst._classify_finding_theme(f)
        deduped = analyst._deduplicate_findings([f1, f2])
        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0]["severity"], "High")
        self.assertIn("Chunk1", deduped[0]["proposal_location"])
        self.assertIn("Chunk2", deduped[0]["proposal_location"])

    def test_merged_finding_strips_internal_chunk_language(self):
        f = {"req_id": "R1", "category": "Rated", "severity": "Medium", "title": "x",
             "issue": "Within this chunk, the requirement appears unaddressed in the first 9,000 characters.",
             "proposal_location": "Loc"}
        f["finding_type"] = analyst._classify_finding_theme(f)
        deduped = analyst._deduplicate_findings([f])
        self.assertNotIn("this chunk", deduped[0]["issue"].lower())
        self.assertNotIn("9,000 characters", deduped[0]["issue"])

    def test_many_locations_capped_with_plus_n_more(self):
        findings = []
        for i in range(6):
            f = {"req_id": "M2", "category": "Mandatory", "severity": "Medium", "title": "Gap",
                 "issue": "Schedule A not referenced in this section.", "proposal_location": f"Loc{i}"}
            f["finding_type"] = analyst._classify_finding_theme(f)
            findings.append(f)
        deduped = analyst._deduplicate_findings(findings)
        self.assertEqual(len(deduped), 1)
        self.assertIn("more", deduped[0]["proposal_location"])


class TestPriorityActions(unittest.TestCase):
    def test_bounded_at_ten(self):
        findings = [
            {"req_id": f"R{i}", "category": "Rated", "severity": "Critical", "stage": "Proposal Submission",
             "title": f"Issue {i}", "issue": f"desc {i}", "recommendation": "fix"}
            for i in range(15)
        ]
        actions = analyst._select_priority_actions([], findings, max_n=10)
        self.assertEqual(len(actions), 10)

    def test_excludes_non_submission_stage_and_cannot_assess(self):
        findings = [
            {"req_id": "R1", "severity": "Critical", "stage": "Proposal Submission", "title": "Sub issue",
             "issue": "x", "recommendation": "y"},
            {"req_id": "R2", "severity": "Critical", "stage": "Negotiation / Shortlist", "title": "Neg issue",
             "issue": "x", "recommendation": "y"},
            {"req_id": "R3", "severity": "Critical", "stage": "Contract Execution", "title": "Exec issue",
             "issue": "x", "recommendation": "y"},
            {"req_id": "R4", "severity": "Critical", "stage": "Contractual Obligation", "title": "Contract issue",
             "issue": "x", "recommendation": "y"},
        ]
        actions = analyst._select_priority_actions([], findings)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["req_id"], "R1")

    def test_mandatory_failures_come_first_and_are_critical(self):
        mandatory_failures = [{"req_id": "M1", "category": "Mandatory", "description": "x", "reason": "not addressed"}]
        findings = [{"req_id": "R1", "severity": "Critical", "stage": "Proposal Submission",
                     "title": "Sub issue", "issue": "x", "recommendation": "y"}]
        actions = analyst._select_priority_actions(mandatory_failures, findings)
        self.assertEqual(actions[0]["source"], "mandatory_failure")
        self.assertEqual(actions[0]["severity"], "Critical")
        self.assertEqual(actions[1]["req_id"], "R1")

    def test_severity_priority_order_critical_then_high_then_medium(self):
        findings = [
            {"req_id": "R3", "severity": "Medium", "stage": "Proposal Submission", "title": "M", "issue": "x", "recommendation": "y"},
            {"req_id": "R1", "severity": "Critical", "stage": "Proposal Submission", "title": "C", "issue": "x", "recommendation": "y"},
            {"req_id": "R2", "severity": "High", "stage": "Proposal Submission", "title": "H", "issue": "x", "recommendation": "y"},
        ]
        actions = analyst._select_priority_actions([], findings)
        self.assertEqual([a["req_id"] for a in actions], ["R1", "R2", "R3"])


class TestPartialAuditSummary(unittest.TestCase):
    def test_distinguishes_confirmed_from_unknown(self):
        req_cov = [
            {"req_id": "R1", "coverage": "Fully Addressed", "category": "Rated", "description": "x"},
            {"req_id": "R2", "coverage": "Partially Addressed", "category": "Rated", "description": "y"},
            {"req_id": "M1", "coverage": "Cannot Assess", "category": "Mandatory", "description": "Insurance declaration"},
        ]
        unresolved = analyst._build_unresolved_items(req_cov)
        cov_meta = {"percentage_covered": 55.0, "successful_chunks": 5, "chunk_count": 9}
        summary = analyst._build_partial_audit_summary(
            req_cov, unresolved, cov_meta, [], failed_chunks_count=2, ceiling_skipped_count=2,
        )
        self.assertEqual(summary["headline"], analyst._PARTIAL_AUDIT_HEADLINE)
        self.assertIn("partial audit", summary["headline"].lower())
        self.assertIn("no reliable overall alignment score", summary["headline"].lower())
        self.assertEqual(summary["requirements_fully_addressed"], 1)
        self.assertEqual(summary["requirements_partially_addressed"], 1)
        self.assertEqual(summary["requirements_cannot_assess"], 1)
        self.assertEqual(summary["established_mandatory_qualification_failures"], [])
        self.assertEqual(len(summary["unresolved_mandatory_qualification_items"]), 1)
        self.assertEqual(summary["sections_failed"], 2)
        self.assertEqual(summary["sections_ceiling_skipped"], 2)

    def test_unresolved_item_example_format(self):
        req_cov = [{"req_id": "M5", "coverage": "Cannot Assess", "category": "Mandatory",
                     "description": "Insurance declaration"}]
        items = analyst._build_unresolved_items(req_cov)
        self.assertEqual(len(items), 1)
        self.assertIn("M5", items[0]["reason"])
        self.assertIn("Insurance declaration", items[0]["reason"])
        self.assertIn("could not be assessed", items[0]["reason"])
        self.assertNotIn("is missing", items[0]["reason"].lower())


class TestChunkFailureDiagnostics(unittest.TestCase):
    def test_diagnostics_contain_filename_section_category_no_content(self):
        pf = _pf("p1", "Doc.txt", "MARK: content here " * 50)

        def fake_call(system, user, max_tokens=2048):
            raise RuntimeError("simulated failure referencing SENSITIVE_PROMPT_DATA")

        with patch("analyst._call", side_effect=fake_call):
            result = analyst.analyze_proposal_alignment_package(
                package_files=[pf], requirements=[], rfp_text="context", bid_info={"title": "T", "client": "C"},
            )
        diag = result["coverage_metadata"]["failed_chunk_diagnostics"]
        self.assertGreaterEqual(len(diag), 1)
        for d in diag:
            self.assertIn("filename", d)
            self.assertIn("section", d)
            self.assertIn("category", d)
            self.assertNotIn("SENSITIVE_PROMPT_DATA", json.dumps(d))
        self.assertTrue(all(d["category"] == "api_error" for d in diag))

    def test_malformed_response_category(self):
        result_holder = {}

        def fake_call(system, user, max_tokens=2048):
            if "requirement_assertions" not in user:
                return _synthesis_response()
            return json.dumps({"not_the_right_keys": True})

        pf = _pf("p1", "Doc.txt", "content " * 50)
        with patch("analyst._call", side_effect=fake_call):
            result = analyst.analyze_proposal_alignment_package(
                package_files=[pf], requirements=[], rfp_text="context", bid_info={"title": "T", "client": "C"},
            )
        diag = result["coverage_metadata"]["failed_chunk_diagnostics"]
        self.assertTrue(any(d["category"] == "malformed_response" for d in diag))

    def test_beyond_ceiling_category_distinct_from_engine_failure(self):
        files = [_pf(f"f{i}", f"File{i}.txt", f"UNIQUE_{i}: tiny content.") for i in range(30)]

        def fake_call(system, user, max_tokens=2048):
            if "requirement_assertions" not in user:
                return _synthesis_response()
            return json.dumps({"chunk_findings": [], "requirement_assertions": []})

        with patch("analyst._call", side_effect=fake_call):
            result = analyst.analyze_proposal_alignment_package(
                package_files=files, requirements=[], rfp_text="context", bid_info={"title": "T", "client": "C"},
            )
        diag = result["coverage_metadata"]["failed_chunk_diagnostics"]
        self.assertTrue(any(d["category"] == "beyond_analysis_ceiling" for d in diag))


class TestChunkPacking(unittest.TestCase):
    def test_greedy_packing_reduces_chunk_count_without_losing_text(self):
        raw_sections = []
        pos = 0
        for i in range(6):
            text = f"Section {i} content. " * 150  # ~3000 chars each
            raw_sections.append({"start": pos, "end": pos + len(text), "heading": f"Section {i}", "text": text})
            pos += len(text)
        bounded = analyst._merge_and_size_bound_sections(raw_sections)
        self.assertLess(len(bounded), 6, "adjacent medium sections should pack into fewer chunks")
        total_text = "".join(c["text"] for c in bounded)
        self.assertEqual(len(total_text), sum(len(s["text"]) for s in raw_sections))
        for c in bounded:
            self.assertLessEqual(len(c["text"]), analyst._ALIGN_TARGET_CHUNK_CHARS)

    def test_never_merges_across_the_ceiling_when_a_single_section_is_oversized(self):
        raw_sections = [
            {"start": 0, "end": 20000, "heading": "Huge", "text": "x" * 20000},
        ]
        bounded = analyst._merge_and_size_bound_sections(raw_sections)
        for c in bounded:
            self.assertLessEqual(len(c["text"]), analyst._ALIGN_TARGET_CHUNK_CHARS)

    def test_provenance_heading_preserved_for_merged_chunk(self):
        raw_sections = [
            {"start": 0, "end": 100, "heading": "Intro", "text": "a" * 100},
            {"start": 100, "end": 200, "heading": "Scope", "text": "b" * 100},
        ]
        bounded = analyst._merge_and_size_bound_sections(raw_sections)
        self.assertEqual(len(bounded), 1)
        self.assertIn("Intro", bounded[0]["heading"])
        self.assertIn("Scope", bounded[0]["heading"])


class TestPdfAndUiReconciledRendering(unittest.TestCase):
    def _pdf_text(self, pdf_bytes):
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        return "\n".join(page.get_text() for page in doc)

    def test_pdf_renders_new_sections_and_no_stale_finding(self):
        align_result = {
            "status": "complete", "overall_score": 78.0, "score_basis": "Buyer-weighted evaluation criteria",
            "score_rationale": "78/100.", "recommendation": "REVISE BEFORE SUBMITTING",
            "executive_summary": "Solid overall.",
            "strengths": [], "findings": [
                {"severity": "High", "stage": "Proposal Submission", "req_id": "M2", "category": "Mandatory",
                 "title": "Weak safeguards", "issue": "Safeguards described are insufficient.",
                 "recommendation": "Strengthen safeguards.", "effort": "Moderate rewrite",
                 "proposal_location": "Schedule A.pdf — Sheet 1"},
            ],
            "unresolved_items": [
                {"req_id": "M5", "category": "Mandatory", "description": "Insurance declaration",
                 "reason": "M5 — Insurance declaration could not be assessed because relevant package "
                           "sections were not successfully analyzed.", "is_mandatory_or_qualification": True},
            ],
            "priority_actions": [
                {"source": "finding", "severity": "High", "req_id": "M2", "title": "Weak safeguards",
                 "detail": "Safeguards described are insufficient.", "recommendation": "Strengthen safeguards."},
            ],
            "mandatory_failures": [],
            "requirement_coverage": [
                {"req_id": "M2", "category": "Mandatory", "coverage": "Partially Addressed", "confidence": "Medium",
                 "evidence_location": "Schedule A.pdf — Sheet 1", "notes": "Schedule A present but limited"},
            ],
            "next_steps": [],
            "coverage_metadata": {"chars_total": 1000, "chars_processed": 1000, "percentage_covered": 100.0,
                                   "chunk_count": 1, "successful_chunks": 1, "failed_or_skipped_chunks": 0},
        }
        pdf_bytes = pdf_alignment.generate_alignment_audit_pdf(
            {"client": "Test Client", "title": "Test Opp"}, align_result,
        )
        text = self._pdf_text(pdf_bytes)
        self.assertIn("AUDIT FINDINGS", text)
        self.assertNotIn("CRITICAL FINDINGS", text)
        self.assertIn("PRIORITY ACTIONS BEFORE SUBMISSION", text)
        self.assertIn("NEEDS VERIFICATION", text)
        self.assertIn("Insurance declaration", text)
        # No stale contradictory "Schedule A is missing"-style claim --
        # only the genuine quality-gap finding should appear.
        self.assertNotIn("is missing", text.lower())
        self.assertIn("insufficient", text.lower())

    def test_pdf_renders_partial_audit_summary_for_incomplete(self):
        align_result = {
            "status": "incomplete", "message": "x", "reason": "coverage below threshold",
            "overall_score": None, "recommendation": None, "executive_summary": None,
            "strengths": [], "next_steps": [], "mandatory_failures": [],
            "findings": [], "unresolved_items": [], "priority_actions": [],
            "requirement_coverage": [],
            "partial_summary": {
                "headline": analyst._PARTIAL_AUDIT_HEADLINE,
                "coverage_percentage": 40.0, "sections_analyzed": "2/5", "sections_failed": 2,
                "sections_ceiling_skipped": 1, "requirements_fully_addressed": 1,
                "requirements_partially_addressed": 1, "requirements_cannot_assess": 3,
                "established_mandatory_qualification_failures": [], "unresolved_mandatory_qualification_items": [],
                "priority_actions": [],
            },
            "coverage_metadata": {"percentage_covered": 40.0, "chunk_count": 5, "successful_chunks": 2},
        }
        pdf_bytes = pdf_alignment.generate_alignment_audit_pdf(
            {"client": "Test Client", "title": "Test Opp"}, align_result,
        )
        text = self._pdf_text(pdf_bytes)
        self.assertIn("partial audit", text.lower())
        self.assertIn("no reliable overall alignment score", text.lower())


if __name__ == "__main__":
    unittest.main()
