"""
tests/test_proposal_intelligence.py

Proposal Intelligence PI-1: the durable domain foundation
(proposal_intelligence.py's adapter, staleness helpers, and package
digest). No provider/model call anywhere in this file -- every fixture is
a hand-built analyzer-result-shaped dict, never a real or mocked
Anthropic client invocation of any kind.
"""
import proposal_intelligence as pi


def _file(file_id, content_hash, included=True, role="primary", **extra):
    return {"file_id": file_id, "content_hash": content_hash, "included": included,
           "role": role, "filename": f"{file_id}.pdf", "package_path": f"{file_id}.pdf",
           "file_type": "pdf", "text": "irrelevant text", **extra}


class TestPackageDigestDeterminism:

    def test_same_inputs_produce_same_digest(self):
        files = [_file("a", "hash-a"), _file("b", "hash-b")]
        assert pi.compute_package_digest(files) == pi.compute_package_digest(list(files))

    def test_digest_is_independent_of_input_order(self):
        a = _file("a", "hash-a")
        b = _file("b", "hash-b")
        assert pi.compute_package_digest([a, b]) == pi.compute_package_digest([b, a])

    def test_changed_file_bytes_changes_digest(self):
        original = pi.compute_package_digest([_file("a", "hash-a")])
        changed = pi.compute_package_digest([_file("a", "hash-a-DIFFERENT")])
        assert original != changed

    def test_changed_inclusion_changes_digest(self):
        original = pi.compute_package_digest([_file("a", "hash-a", included=True)])
        changed = pi.compute_package_digest([_file("a", "hash-a", included=False)])
        assert original != changed

    def test_changed_role_changes_digest(self):
        original = pi.compute_package_digest([_file("a", "hash-a", role="primary")])
        changed = pi.compute_package_digest([_file("a", "hash-a", role="supporting")])
        assert original != changed

    def test_transient_ui_fields_do_not_affect_digest(self):
        """Fields like extraction_meta/lifecycle_status/char_count are
        diagnostic, not analysis-input identity -- must not change the
        digest, or every re-extraction would silently create a new
        package identity even though nothing analysis-relevant changed."""
        a = _file("a", "hash-a", extraction_meta={"pages": 3}, lifecycle_status="extracted", char_count=500)
        b = _file("a", "hash-a", extraction_meta={"pages": 99}, lifecycle_status="failed", char_count=1)
        assert pi.compute_package_digest([a]) == pi.compute_package_digest([b])

    def test_digest_never_embeds_raw_text(self):
        files = [_file("a", "hash-a", text="CONFIDENTIAL PROPOSAL TEXT " * 20)]
        digest = pi.compute_package_digest(files)
        assert "CONFIDENTIAL" not in digest
        assert len(digest) == 64  # sha256 hex


class TestPackageDigestOrderSemantics:
    """PI-1.2: compute_package_digest's own sort-by-file_id makes the
    digest COMPUTATION insensitive to the order files are passed in this
    call (test_digest_is_independent_of_input_order above), but file_id
    itself is occurrence-derived upstream in
    extractor.build_alignment_submission_package. Package upload/
    discovery order is analysis-relevant (analyst.py's
    _allocate_package_chunk_budget assigns chunk index/total by package
    order and its ceiling-exceeded/largest-remainder branches can pick
    different files depending on order, including via file_id tie-
    breaks), so a real reorder that produces different file_ids must
    produce a different package identity -- these tests exercise that
    contract at this module's boundary (the file_id values themselves,
    as an upstream re-upload in a different order would produce them)."""

    def test_same_file_ids_reordered_at_this_boundary_give_same_digest(self):
        """Restating test_digest_is_independent_of_input_order's contract
        explicitly under the PI-1.2 order-semantics decision: GIVEN the
        same file_id values (i.e. the same occurrence positions), the
        order they're passed to compute_package_digest itself doesn't
        matter -- the sort inside the function is what does the work."""
        a = _file("occ0", "hash-a")
        b = _file("occ1", "hash-b")
        assert pi.compute_package_digest([a, b]) == pi.compute_package_digest([b, a])

    def test_different_occurrence_derived_file_ids_give_different_digest(self):
        """A real re-upload of the identical bytes in a different order
        changes file_id (occurrence_index is part of its derivation), so
        even though content_hash is unchanged, the resulting package
        identity must differ -- this is the intentional consequence of
        Option A (order is analysis-relevant)."""
        first_upload_order = [
            _file("occ0-fileA", "hash-a"),
            _file("occ1-fileB", "hash-b"),
        ]
        second_upload_order_same_bytes = [
            _file("occ0-fileB", "hash-b"),
            _file("occ1-fileA", "hash-a"),
        ]
        assert pi.compute_package_digest(first_upload_order) != pi.compute_package_digest(
            second_upload_order_same_bytes
        )


class TestStaleness:

    def _run(self, procurement_revision=3, snapshot_id=10, analysis_version=None):
        return {
            "based_on_procurement_revision": procurement_revision,
            "proposal_package_snapshot_id": snapshot_id,
            "analysis_version": analysis_version or pi.PROPOSAL_INTELLIGENCE_ANALYSIS_VERSION,
        }

    def test_current_run_has_no_staleness_reasons(self):
        run = self._run()
        reasons = pi.staleness_reasons(run, current_procurement_revision=3, current_package_snapshot_id=10)
        assert reasons == []
        assert pi.is_current(run, current_procurement_revision=3, current_package_snapshot_id=10)

    def test_procurement_revision_change_is_reported_distinctly(self):
        run = self._run(procurement_revision=3)
        reasons = pi.staleness_reasons(run, current_procurement_revision=4, current_package_snapshot_id=10)
        assert reasons == [pi.STALE_PROCUREMENT_CHANGED]

    def test_package_change_is_reported_distinctly(self):
        run = self._run(snapshot_id=10)
        reasons = pi.staleness_reasons(run, current_procurement_revision=3, current_package_snapshot_id=11)
        assert reasons == [pi.STALE_PROPOSAL_CHANGED]

    def test_analysis_version_change_is_reported_distinctly(self):
        run = self._run(analysis_version="proposal-intelligence-v0")
        reasons = pi.staleness_reasons(run, current_procurement_revision=3, current_package_snapshot_id=10)
        assert reasons == [pi.STALE_ANALYSIS_VERSION_CHANGED]

    def test_multiple_reasons_never_collapsed_into_one_boolean(self):
        run = self._run(procurement_revision=1, snapshot_id=1, analysis_version="old")
        reasons = pi.staleness_reasons(run, current_procurement_revision=99, current_package_snapshot_id=99)
        assert set(reasons) == {pi.STALE_PROCUREMENT_CHANGED, pi.STALE_PROPOSAL_CHANGED,
                                pi.STALE_ANALYSIS_VERSION_CHANGED}
        assert not pi.is_current(run, current_procurement_revision=99, current_package_snapshot_id=99)


class TestRequirementAssessmentAdapter:

    def _requirements(self):
        return [{"id": 101, "req_id": "R1", "category": "Technical"},
               {"id": 102, "req_id": "R2", "category": "Commercial"}]

    def test_uses_existing_coverage_vocabulary_unchanged(self):
        alignment_result = {"requirement_coverage": [
            {"req_id": "R1", "coverage": "Fully Addressed", "confidence": "High",
             "evidence_location": "Tech.pdf — Approach", "notes": "We will deliver on time."},
        ]}
        rows = pi.adapt_requirement_assessments(alignment_result, self._requirements())
        assert rows[0]["assessment_status"] == "Fully Addressed"
        assert rows[0]["assessment_status"] in pi.ASSESSMENT_STATUSES

    def test_requirement_id_populated_when_available(self):
        alignment_result = {"requirement_coverage": [
            {"req_id": "R1", "coverage": "Fully Addressed", "confidence": "High",
             "evidence_location": "Tech.pdf — Approach", "notes": "text"},
        ]}
        rows = pi.adapt_requirement_assessments(alignment_result, self._requirements())
        assert rows[0]["requirement_id"] == 101

    def test_requirement_id_absent_when_not_resolvable(self):
        alignment_result = {"requirement_coverage": [
            {"req_id": "R999", "coverage": "Fully Addressed", "confidence": "High",
             "evidence_location": "x", "notes": "y"},
        ]}
        rows = pi.adapt_requirement_assessments(alignment_result, self._requirements())
        assert rows[0]["requirement_id"] is None
        assert rows[0]["req_id"] == "R999"  # the label is preserved even when unresolvable

    def test_proposal_provenance_preserved_when_evidence_exists(self):
        alignment_result = {"requirement_coverage": [
            {"req_id": "R1", "coverage": "Fully Addressed", "confidence": "High",
             "evidence_location": "Schedule C.txt — Pricing", "notes": "fixed price is $500,000"},
        ]}
        rows = pi.adapt_requirement_assessments(alignment_result, self._requirements())
        refs = rows[0]["proposal_source_refs"]
        assert refs == [{"evidence_location": "Schedule C.txt — Pricing", "excerpt": "fixed price is $500,000"}]

    def test_absence_does_not_fabricate_a_proposal_source_ref(self):
        alignment_result = {"requirement_coverage": [
            {"req_id": "R1", "coverage": "Not Addressed", "confidence": "High",
             "evidence_location": "", "notes": "No supporting evidence found anywhere in the analyzed proposal."},
        ]}
        rows = pi.adapt_requirement_assessments(alignment_result, self._requirements())
        assert rows[0]["proposal_source_refs"] == []

    def test_cannot_assess_absence_also_has_no_fabricated_ref(self):
        alignment_result = {"requirement_coverage": [
            {"req_id": "R1", "coverage": "Cannot Assess", "confidence": "Low",
             "evidence_location": "", "notes": "Proposal coverage is incomplete -- absence cannot be confirmed."},
        ]}
        rows = pi.adapt_requirement_assessments(alignment_result, self._requirements())
        assert rows[0]["proposal_source_refs"] == []
        assert rows[0]["assessment_status"] == "Cannot Assess"

    def test_never_fabricates_a_page_sheet_or_section(self):
        """The evidence_location free-text label is preserved verbatim,
        never decomposed into page/sheet/section fields the analyzer
        never actually asserted."""
        alignment_result = {"requirement_coverage": [
            {"req_id": "R1", "coverage": "Fully Addressed", "confidence": "High",
             "evidence_location": "Budget.xlsx — Sheet: Rates", "notes": "hourly rate is $150"},
        ]}
        rows = pi.adapt_requirement_assessments(alignment_result, self._requirements())
        ref = rows[0]["proposal_source_refs"][0]
        assert set(ref.keys()) == {"evidence_location", "excerpt"}
        assert "page" not in ref and "sheet" not in ref and "section" not in ref

    def test_empty_coverage_list_produces_no_rows(self):
        rows = pi.adapt_requirement_assessments({"requirement_coverage": []}, self._requirements())
        assert rows == []

    def test_missing_coverage_key_produces_no_rows_not_an_error(self):
        rows = pi.adapt_requirement_assessments({"status": "incomplete"}, self._requirements())
        assert rows == []


class TestFindingsAdapter:

    def test_mandatory_failure_maps_to_missing_requirement(self):
        alignment_result = {"mandatory_failures": [
            {"req_id": "M1", "description": "ISO certification required", "reason": "No certificate found"},
        ]}
        findings = pi.adapt_findings(alignment_result)
        assert len(findings) == 1
        assert findings[0]["finding_type"] == pi.FINDING_TYPE_MISSING_REQUIREMENT
        assert findings[0]["related_req_id"] == "M1"
        assert findings[0]["message"] == "No certificate found"

    def test_unusable_file_maps_to_submission_artifact_gap(self):
        alignment_result = {"coverage_metadata": {"unusable_files": [
            {"filename": "Corrupt.xlsx", "reason": "unreadable spreadsheet"},
        ]}}
        findings = pi.adapt_findings(alignment_result)
        assert len(findings) == 1
        assert findings[0]["finding_type"] == pi.FINDING_TYPE_SUBMISSION_ARTIFACT_GAP
        assert "Corrupt.xlsx" in findings[0]["title"]

    def test_generic_finding_maps_to_other_never_a_guessed_type(self):
        alignment_result = {"findings": [
            {"severity": "High", "stage": "Proposal Submission", "req_id": "R1",
             "title": "Unsupported claim", "issue": "Claims 24/7 support with no evidence",
             "proposal_location": "Tech.pdf — Support", "recommendation": "Add evidence", "effort": "Low"},
        ]}
        findings = pi.adapt_findings(alignment_result)
        assert len(findings) == 1
        assert findings[0]["finding_type"] == pi.FINDING_TYPE_OTHER
        assert findings[0]["proposal_source_refs"] == [{"evidence_location": "Tech.pdf — Support"}]

    def test_all_emitted_types_are_in_the_bounded_taxonomy(self):
        alignment_result = {
            "mandatory_failures": [{"req_id": "M1", "description": "x", "reason": "y"}],
            "coverage_metadata": {"unusable_files": [{"filename": "f.pdf", "reason": "r"}]},
            "findings": [{"severity": "Low", "title": "t", "issue": "i"}],
        }
        findings = pi.adapt_findings(alignment_result)
        assert all(f["finding_type"] in pi.FINDING_TYPES for f in findings)

    def test_empty_result_produces_no_findings(self):
        assert pi.adapt_findings({}) == []

    def test_findings_are_plain_dicts_ready_for_bulk_insert_never_mutated_in_place(self):
        alignment_result = {"findings": [{"severity": "Low", "title": "t", "issue": "i"}]}
        original = dict(alignment_result["findings"][0])
        pi.adapt_findings(alignment_result)
        assert alignment_result["findings"][0] == original


class TestRunPayload:

    def test_complete_status_maps_correctly(self):
        payload = pi.build_run_payload(
            {"status": "complete", "overall_score": 82.0, "recommendation": "SUBMIT"},
            procurement_state={"procurement_revision": 3, "procurement_truth_status": "governed"})
        assert payload["status"] == "COMPLETE"
        assert payload["analysis_version"] == pi.PROPOSAL_INTELLIGENCE_ANALYSIS_VERSION

    def test_incomplete_status_maps_correctly(self):
        payload = pi.build_run_payload(
            {"status": "incomplete", "reason": "file unreadable"},
            procurement_state={"procurement_revision": 3, "procurement_truth_status": "governed"})
        assert payload["status"] == "INCOMPLETE"

    def test_governed_basis_recorded_explicitly(self):
        payload = pi.build_run_payload(
            {"status": "complete"},
            procurement_state={"procurement_revision": 5, "procurement_truth_status": "governed"})
        assert payload["based_on_procurement_revision"] == 5
        assert payload["based_on_procurement_truth_status"] == "governed"

    def test_ungoverned_basis_recorded_explicitly_never_equivalent_to_governed(self):
        payload = pi.build_run_payload(
            {"status": "complete"},
            procurement_state={"procurement_revision": 1, "procurement_truth_status": "ungoverned"})
        assert payload["based_on_procurement_truth_status"] == "ungoverned"
        assert payload["based_on_procurement_truth_status"] != "governed"

    def test_legacy_result_preserves_score_and_recommendation_without_making_them_canonical(self):
        alignment_result = {"status": "complete", "overall_score": 91.5, "recommendation": "SUBMIT",
                            "executive_summary": "Strong proposal.", "strengths": ["Clear pricing"]}
        payload = pi.build_run_payload(
            alignment_result, procurement_state={"procurement_revision": 1, "procurement_truth_status": "ungoverned"})
        assert payload["legacy_result"]["overall_score"] == 91.5
        assert payload["legacy_result"]["recommendation"] == "SUBMIT"
        # Not promoted to a top-level canonical PI field:
        assert "overall_score" not in payload or list(payload.keys()).count("overall_score") == 0

    def test_failed_run_payload_has_no_coverage_or_legacy_result(self):
        payload = pi.build_failed_run_payload(
            procurement_state={"procurement_revision": 2, "procurement_truth_status": "governed"},
            failure_reason="RuntimeError: credit balance too low")
        assert payload["status"] == "FAILED"
        assert payload["coverage_metadata"] is None
        assert payload["legacy_result"] is None
        assert "credit balance" in payload["failure_reason"]

    def test_incomplete_coverage_is_never_transformed_into_complete_absence(self):
        """An INCOMPLETE run's requirement_coverage may contain Cannot
        Assess rows -- build_run_payload must not upgrade its status to
        COMPLETE nor synthesize a score."""
        alignment_result = {
            "status": "incomplete", "reason": "one file failed extraction",
            "requirement_coverage": [{"req_id": "R1", "coverage": "Cannot Assess", "confidence": "Low",
                                      "evidence_location": "", "notes": "incomplete"}],
        }
        payload = pi.build_run_payload(
            alignment_result, procurement_state={"procurement_revision": 1, "procurement_truth_status": "ungoverned"})
        assert payload["status"] == "INCOMPLETE"
        assert payload["legacy_result"].get("overall_score") is None


class TestReconstructLegacyAlignResult:
    """The inverse mapping CHECK uses on reload -- proves a persisted run
    can be re-rendered without calling the analyzer again."""

    def test_reconstructs_complete_status_and_score(self):
        run = {"status": "COMPLETE", "legacy_result": {"overall_score": 88.0, "recommendation": "SUBMIT",
                                                        "executive_summary": "Strong.", "strengths": ["Clear pricing"]},
              "coverage_metadata": {"percentage_covered": 100},
              "based_on_procurement_revision": 3, "based_on_procurement_truth_status": "governed"}
        result = pi.reconstruct_legacy_align_result(run, assessments=[], findings=[])
        assert result["status"] == "complete"
        assert result["overall_score"] == 88.0
        assert result["recommendation"] == "SUBMIT"
        assert result["coverage_metadata"] == {"percentage_covered": 100}

    def test_reconstructs_requirement_coverage_with_evidence(self):
        run = {"status": "COMPLETE", "legacy_result": {}}
        assessments = [{"req_id": "R1", "category": "Technical", "description": "Deliver on time",
                        "assessment_status": "Fully Addressed", "confidence": "High",
                        "proposal_source_refs": [{"evidence_location": "Tech.pdf — Approach",
                                                  "excerpt": "on time delivery"}]}]
        result = pi.reconstruct_legacy_align_result(run, assessments, findings=[])
        row = result["requirement_coverage"][0]
        assert row["coverage"] == "Fully Addressed"
        assert row["evidence_location"] == "Tech.pdf — Approach"
        assert row["notes"] == "on time delivery"

    def test_reconstructs_absence_without_fabricating_evidence(self):
        run = {"status": "COMPLETE", "legacy_result": {}}
        assessments = [{"req_id": "R2", "category": "Technical", "description": "x",
                        "assessment_status": "Not Addressed", "confidence": "High",
                        "proposal_source_refs": []}]
        result = pi.reconstruct_legacy_align_result(run, assessments, findings=[])
        row = result["requirement_coverage"][0]
        assert row["evidence_location"] == ""
        assert "No supporting evidence" in row["notes"]

    def test_reconstructs_mandatory_failures_losslessly_via_payload(self):
        run = {"status": "COMPLETE", "legacy_result": {}}
        original_mf = {"req_id": "M1", "description": "ISO cert required", "reason": "no certificate found"}
        findings = [{"finding_type": pi.FINDING_TYPE_MISSING_REQUIREMENT, "payload": original_mf}]
        result = pi.reconstruct_legacy_align_result(run, assessments=[], findings=findings)
        assert result["mandatory_failures"] == [original_mf]

    def test_reconstructs_generic_findings_losslessly_via_payload(self):
        run = {"status": "COMPLETE", "legacy_result": {}}
        original_finding = {"severity": "High", "title": "Unsupported claim", "issue": "no evidence"}
        findings = [{"finding_type": pi.FINDING_TYPE_OTHER, "payload": original_finding}]
        result = pi.reconstruct_legacy_align_result(run, assessments=[], findings=findings)
        assert result["findings"] == [original_finding]

    def test_submission_artifact_gap_findings_not_mixed_into_generic_findings(self):
        run = {"status": "COMPLETE", "legacy_result": {}}
        findings = [{"finding_type": pi.FINDING_TYPE_SUBMISSION_ARTIFACT_GAP,
                    "payload": {"filename": "Corrupt.xlsx", "reason": "unreadable"}}]
        result = pi.reconstruct_legacy_align_result(run, assessments=[], findings=findings)
        assert result["findings"] == []
        assert result["mandatory_failures"] == []

    def test_incomplete_run_reconstructs_incomplete_status(self):
        run = {"status": "INCOMPLETE", "legacy_result": {"reason": "one file failed"}}
        result = pi.reconstruct_legacy_align_result(run, assessments=[], findings=[])
        assert result["status"] == "incomplete"
        assert result["reason"] == "one file failed"


class TestRestorePackageManifestDict:
    """PI-1.1 instruction 8: reload must restore the exact historical
    package manifest CHECK's PDF export and manifest view consume."""

    def test_restores_files_list_from_snapshot_manifest_column(self):
        snapshot = {"id": 55, "manifest": [
            {"file_id": "f1", "filename": "Tech.pdf", "role": "primary", "included": True},
            {"file_id": "f2", "filename": "Excluded.pdf", "role": None, "included": False},
        ]}
        result = pi.restore_package_manifest_dict(snapshot)
        assert result == {"files": snapshot["manifest"]}

    def test_primary_role_survives_reconstruction(self):
        snapshot = {"manifest": [{"file_id": "f1", "filename": "Tech.pdf", "role": "primary"}]}
        result = pi.restore_package_manifest_dict(snapshot)
        primary = [f["filename"] for f in result["files"] if f.get("role") == "primary"]
        assert primary == ["Tech.pdf"]

    def test_excluded_files_are_present_in_the_restored_manifest(self):
        """Instruction 5: the durable manifest -- and therefore the
        restored view -- must retain excluded/duplicate/rejected/
        unsupported files, not just what the analyzer saw."""
        snapshot = {"manifest": [
            {"file_id": "f1", "included": True, "lifecycle_status": "extracted"},
            {"file_id": "f2", "included": False, "lifecycle_status": "extracted"},
            {"file_id": "f3", "included": False, "lifecycle_status": "duplicate"},
        ]}
        result = pi.restore_package_manifest_dict(snapshot)
        assert len(result["files"]) == 3
        statuses = {f["lifecycle_status"] for f in result["files"]}
        assert statuses == {"extracted", "duplicate"}

    def test_missing_manifest_column_returns_empty_files_never_raises(self):
        assert pi.restore_package_manifest_dict({"id": 55}) == {"files": []}


class TestDigestSemanticsExcludedVsNeverSupplied:
    """PI-1.1 instruction 6: an excluded-but-present file must produce a
    DIFFERENT digest than a package that never had that file at all."""

    def test_excluded_file_present_differs_from_file_never_supplied(self):
        with_excluded = [
            {"file_id": "a", "content_hash": "ha", "included": True, "role": "primary"},
            {"file_id": "b", "content_hash": "hb", "included": False, "role": None},
        ]
        without_b_at_all = [
            {"file_id": "a", "content_hash": "ha", "included": True, "role": "primary"},
        ]
        assert pi.compute_package_digest(with_excluded) != pi.compute_package_digest(without_b_at_all)

    def test_full_manifest_digest_differs_from_included_only_digest(self):
        """The digest must be computed over the FULL submitted package,
        not the analyzer's included-only subset -- these two inputs
        represent genuinely different audit scopes and must not collide."""
        full = [
            {"file_id": "a", "content_hash": "ha", "included": True, "role": "primary"},
            {"file_id": "b", "content_hash": "hb", "included": False, "role": None},
        ]
        included_only = [f for f in full if f["included"]]
        assert pi.compute_package_digest(full) != pi.compute_package_digest(included_only)


if __name__ == "__main__":
    import sys
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))
