"""
tests/test_pi2a1_dedup_provenance.py

PI-2A.1: provenance-preserving dedup hardening. ZERO provider/Anthropic
calls in this file -- every fixture is a hand-built dict exercising the
deterministic post-response aggregation code in analyst.py and the
pass-through in proposal_intelligence.adapt_findings(), never a real or
mocked model call.
"""
import analyst
import proposal_intelligence as pi


def _finding(req_id="R1", category="Pricing", finding_type="Incomplete content",
             deficiency_type="WEAK_EVIDENCE", issue="The pricing schedule lacks detail",
             severity="Medium", proposal_location="Tech.pdf — Pricing", refs=None):
    return {
        "req_id": req_id, "category": category, "finding_type": finding_type,
        "deficiency_type": deficiency_type, "issue": issue, "title": "Weak pricing evidence",
        "severity": severity, "proposal_location": proposal_location,
        "proposal_source_refs": refs if refs is not None else [],
    }


def _ref(file_id="f1", content_hash="h1", filename="Tech.pdf", section="Pricing",
         char_start=0, char_end=100, excerpt="ex"):
    return {
        "file_id": file_id, "content_hash": content_hash, "filename": filename,
        "package_path": filename, "file_type": "pdf", "section": section,
        "char_start": char_start, "char_end": char_end, "excerpt": excerpt,
    }


class TestFindingDedupDeficiencyType:

    def test_A_same_everything_same_deficiency_type_dedupes(self):
        findings = [_finding(deficiency_type="WEAK_EVIDENCE"), _finding(deficiency_type="WEAK_EVIDENCE")]
        out = analyst._deduplicate_findings(findings)
        assert len(out) == 1

    def test_B_same_everything_different_deficiency_type_stays_two(self):
        findings = [_finding(deficiency_type="WEAK_EVIDENCE"), _finding(deficiency_type="UNSUPPORTED_CLAIM")]
        out = analyst._deduplicate_findings(findings)
        assert len(out) == 2

    def test_C_duplicate_with_two_refs_preserves_both(self):
        ref1 = _ref(file_id="f1", excerpt="e1")
        ref2 = _ref(file_id="f2", excerpt="e2")
        findings = [
            _finding(refs=[ref1], proposal_location="Tech.pdf — Pricing"),
            _finding(refs=[ref2], proposal_location="Tech2.pdf — Pricing"),
        ]
        out = analyst._deduplicate_findings(findings)
        assert len(out) == 1
        refs_out = out[0]["proposal_source_refs"]
        assert ref1 in refs_out and ref2 in refs_out
        assert len(refs_out) == 2

    def test_D_exact_duplicate_ref_appears_once(self):
        ref1 = _ref()
        findings = [_finding(refs=[ref1]), _finding(refs=[dict(ref1)])]
        out = analyst._deduplicate_findings(findings)
        assert len(out) == 1
        assert out[0]["proposal_source_refs"] == [ref1]

    def test_E_legacy_location_only_findings_still_combine(self):
        findings = [
            _finding(proposal_location="A.pdf — Sec1", refs=[]),
            _finding(proposal_location="B.pdf — Sec2", refs=[]),
        ]
        out = analyst._deduplicate_findings(findings)
        assert len(out) == 1
        assert "A.pdf — Sec1" in out[0]["proposal_location"]
        assert "B.pdf — Sec2" in out[0]["proposal_location"]
        assert out[0]["proposal_source_refs"] == []

    def test_legacy_none_deficiency_type_only_equals_none(self):
        findings = [_finding(deficiency_type=None), _finding(deficiency_type="OTHER")]
        out = analyst._deduplicate_findings(findings)
        assert len(out) == 2
        findings2 = [_finding(deficiency_type=None), _finding(deficiency_type=None)]
        out2 = analyst._deduplicate_findings(findings2)
        assert len(out2) == 1


def _observation(obs_type="DELIVERY_COMMITMENT", req_id="R1", statement="We will deliver in 30 days",
                  implication="Tight schedule risk", confidence="Medium", title="Delivery commitment",
                  ref=None, chunk_label="Tech.pdf — Delivery"):
    o = {
        "observation_type": obs_type, "req_id": req_id, "title": title,
        "statement": statement, "implication": implication, "confidence": confidence,
        "proposal_location": chunk_label,
    }
    if ref is not None:
        o["_source_ref"] = ref
    return o


class TestObservationDedup:

    def test_F_overlapping_chunks_merge_and_preserve_both_refs(self):
        ref1 = _ref(file_id="f1", char_start=0, char_end=100)
        ref2 = _ref(file_id="f1", char_start=50, char_end=150)
        chunk_results = [
            {"proposal_observations": [_observation(ref=ref1)]},
            {"proposal_observations": [_observation(ref=ref2)]},
        ]
        out = analyst._aggregate_proposal_observations(chunk_results)
        assert len(out) == 1
        assert ref1 in out[0]["proposal_source_refs"]
        assert ref2 in out[0]["proposal_source_refs"]

    def test_G_same_commitment_two_different_files_merge_refs(self):
        ref1 = _ref(file_id="f1", filename="Tech.pdf")
        ref2 = _ref(file_id="f2", filename="Tech2.pdf")
        chunk_results = [
            {"proposal_observations": [_observation(ref=ref1)]},
            {"proposal_observations": [_observation(ref=ref2)]},
        ]
        out = analyst._aggregate_proposal_observations(chunk_results)
        assert len(out) == 1
        refs_out = out[0]["proposal_source_refs"]
        assert ref1 in refs_out and ref2 in refs_out

    def test_H_same_statement_different_implication_stays_two(self):
        chunk_results = [
            {"proposal_observations": [_observation(implication="Tight schedule risk", ref=_ref(file_id="f1"))]},
            {"proposal_observations": [_observation(implication="No material risk", ref=_ref(file_id="f2"))]},
        ]
        out = analyst._aggregate_proposal_observations(chunk_results)
        assert len(out) == 2

    def test_I_same_key_differing_confidence_resolves_to_highest(self):
        chunk_results = [
            {"proposal_observations": [_observation(confidence="Low", ref=_ref(file_id="f1"))]},
            {"proposal_observations": [_observation(confidence="High", ref=_ref(file_id="f2"))]},
            {"proposal_observations": [_observation(confidence="Medium", ref=_ref(file_id="f3"))]},
        ]
        out = analyst._aggregate_proposal_observations(chunk_results)
        assert len(out) == 1
        assert out[0]["confidence"] == "High"

    def test_J_exact_duplicate_ref_not_duplicated(self):
        ref1 = _ref()
        chunk_results = [
            {"proposal_observations": [_observation(ref=ref1)]},
            {"proposal_observations": [_observation(ref=dict(ref1))]},
        ]
        out = analyst._aggregate_proposal_observations(chunk_results)
        assert len(out) == 1
        assert out[0]["proposal_source_refs"] == [ref1]


class TestAdapterPassThrough:

    def test_K_multi_ref_finding_survives_adapt_findings(self):
        ref1 = _ref(file_id="f1")
        ref2 = _ref(file_id="f2")
        alignment_result = {
            "mandatory_failures": [],
            "coverage_metadata": {},
            "findings": [_finding(refs=[ref1, ref2])],
            "proposal_observations": [],
        }
        rows = pi.adapt_findings(alignment_result)
        finding_rows = [r for r in rows if r["finding_type"] != pi.FINDING_TYPE_MISSING_REQUIREMENT]
        assert len(finding_rows) == 1
        assert finding_rows[0]["proposal_source_refs"] == [ref1, ref2]

    def test_L_multi_ref_delivery_commitment_observation_survives(self):
        ref1 = _ref(file_id="f1")
        ref2 = _ref(file_id="f2")
        alignment_result = {
            "mandatory_failures": [],
            "coverage_metadata": {},
            "findings": [],
            "proposal_observations": [{
                "observation_type": "DELIVERY_COMMITMENT", "req_id": "R1",
                "title": "Delivery commitment", "statement": "We will deliver in 30 days",
                "implication": "Tight schedule risk", "confidence": "High",
                "proposal_source_refs": [ref1, ref2],
            }],
        }
        rows = pi.adapt_findings(alignment_result)
        assert len(rows) == 1
        assert rows[0]["proposal_source_refs"] == [ref1, ref2]

    def test_M_multi_ref_commercial_exposure_observation_survives(self):
        ref1 = _ref(file_id="f1")
        ref2 = _ref(file_id="f2")
        alignment_result = {
            "mandatory_failures": [],
            "coverage_metadata": {},
            "findings": [],
            "proposal_observations": [{
                "observation_type": "COMMERCIAL_EXPOSURE", "req_id": "R2",
                "title": "Commercial exposure", "statement": "Price is fixed for 12 months",
                "implication": "Inflation exposure beyond year 1", "confidence": "Medium",
                "proposal_source_refs": [ref1, ref2],
            }],
        }
        rows = pi.adapt_findings(alignment_result)
        assert len(rows) == 1
        assert rows[0]["proposal_source_refs"] == [ref1, ref2]
