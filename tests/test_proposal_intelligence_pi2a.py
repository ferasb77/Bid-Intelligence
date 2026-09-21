"""
tests/test_proposal_intelligence_pi2a.py

Proposal Intelligence PI-2A: richer evidence/provenance/observation depth
on top of PI-1's durable foundation, with ZERO new model call and ZERO
provider/model invocation of any kind in this file. Every fixture below is
a hand-built, analyzer-result-shaped dict (or a `analyst._call` MagicMock
patch returning a hand-built JSON string) -- never a real or mocked
network call to Anthropic. Mirrors the existing style of
tests/test_proposal_intelligence.py and tests/test_proposal_alignment_analyzer.py.
"""
import proposal_intelligence as pi
import analyst


# ── analyst.py: deterministic provenance / aggregation ─────────────────────

class TestBuildProposalSourceRef:

    def test_includes_only_fields_the_chunk_actually_carries(self):
        chunk = {"heading": "Pricing", "start": 100, "end": 400}
        ref = analyst._build_proposal_source_ref(chunk)
        assert ref == {"section": "Pricing", "char_start": 100, "char_end": 400}
        assert "file_id" not in ref and "content_hash" not in ref

    def test_package_chunk_carries_full_file_identity(self):
        chunk = {
            "heading": "Support Plan", "start": 0, "end": 50,
            "source_file_id": "f1", "source_content_hash": "hash1",
            "source_filename": "Tech.pdf", "source_package_path": "Tech.pdf",
            "source_file_type": "pdf",
        }
        ref = analyst._build_proposal_source_ref(chunk)
        assert ref == {
            "file_id": "f1", "content_hash": "hash1", "filename": "Tech.pdf",
            "package_path": "Tech.pdf", "file_type": "pdf",
            "section": "Support Plan", "char_start": 0, "char_end": 50,
        }

    def test_never_invents_a_missing_coordinate(self):
        """No page/sheet/row/cell coordinate is fabricated when the chunk
        metadata doesn't actually carry one."""
        ref = analyst._build_proposal_source_ref({"heading": "X", "start": 0, "end": 1})
        assert "page" not in ref and "sheet" not in ref and "row" not in ref and "cell" not in ref


class TestAttachChunkProvenance:

    def _chunk(self):
        return {"heading": "Pricing", "start": 10, "end": 20,
                "source_file_id": "f1", "source_filename": "Tech.pdf"}

    def test_attaches_deterministic_ref_to_assertions_and_findings(self):
        parsed = {
            "requirement_assertions": [{"req_id": "R1", "coverage": "Fully Addressed",
                                        "confidence": "High", "evidence": "x", "evidence_strength": "STRONG"}],
            "chunk_findings": [{"severity": "Low", "title": "t", "issue": "i", "deficiency_type": "WEAK_EVIDENCE"}],
        }
        out = analyst._attach_chunk_provenance(parsed, self._chunk(), "Tech.pdf — Pricing")
        assert out["requirement_assertions"][0]["_source_ref"]["file_id"] == "f1"
        assert out["chunk_findings"][0]["_source_ref"]["file_id"] == "f1"

    def test_model_cannot_override_physical_identity(self):
        """Even if a chunk dict somehow carried a model-supplied file_id
        key, only the deterministic chunk metadata is ever used to build
        the ref -- _build_proposal_source_ref only reads source_* keys."""
        parsed = {"requirement_assertions": [{"req_id": "R1", "coverage": "Fully Addressed",
                                              "file_id": "MODEL-FABRICATED", "evidence": "x"}],
                 "chunk_findings": []}
        out = analyst._attach_chunk_provenance(parsed, self._chunk(), "label")
        assert out["requirement_assertions"][0]["_source_ref"]["file_id"] == "f1"

    def test_invalid_evidence_strength_is_dropped_not_guessed(self):
        parsed = {"requirement_assertions": [{"req_id": "R1", "coverage": "Fully Addressed",
                                              "evidence": "x", "evidence_strength": "SUPER_STRONG"}],
                 "chunk_findings": []}
        out = analyst._attach_chunk_provenance(parsed, self._chunk(), "label")
        assert out["requirement_assertions"][0]["evidence_strength"] is None

    def test_invalid_deficiency_type_falls_back_to_other(self):
        parsed = {"requirement_assertions": [],
                 "chunk_findings": [{"severity": "Low", "title": "t", "issue": "i", "deficiency_type": "MADE_UP"}]}
        out = analyst._attach_chunk_provenance(parsed, self._chunk(), "label")
        assert out["chunk_findings"][0]["deficiency_type"] == "OTHER"

    def test_missing_deficiency_type_stays_absent_not_forced_to_other(self):
        parsed = {"requirement_assertions": [],
                 "chunk_findings": [{"severity": "Low", "title": "t", "issue": "i"}]}
        out = analyst._attach_chunk_provenance(parsed, self._chunk(), "label")
        assert out["chunk_findings"][0]["deficiency_type"] is None

    def test_unrecognized_observation_type_is_dropped_fail_closed(self):
        parsed = {"requirement_assertions": [], "chunk_findings": [],
                 "proposal_observations": [{"observation_type": "SCOPE_CREEP", "statement": "x"}]}
        out = analyst._attach_chunk_provenance(parsed, self._chunk(), "label")
        assert out["proposal_observations"] == []

    def test_valid_observation_gets_provenance_and_location(self):
        parsed = {"requirement_assertions": [], "chunk_findings": [],
                 "proposal_observations": [{"observation_type": "DELIVERY_COMMITMENT",
                                            "req_id": "R1", "title": "24/7 support", "statement": "we commit to 24/7",
                                            "implication": "staffing needed", "confidence": "High"}]}
        out = analyst._attach_chunk_provenance(parsed, self._chunk(), "Tech.pdf — Pricing")
        obs = out["proposal_observations"][0]
        assert obs["proposal_location"] == "Tech.pdf — Pricing"
        assert obs["_source_ref"]["file_id"] == "f1"


class TestAggregateRequirementCoveragePI2A:

    def _chunk_result(self, label, assertions):
        return {"chunk_label": label, "requirement_assertions": assertions, "chunk_findings": []}

    def test_preserves_all_positive_evidence_locations_not_just_winner(self):
        chunk_results = [
            self._chunk_result("Tech.pdf — A", [
                {"req_id": "R1", "coverage": "Partially Addressed", "confidence": "Medium",
                 "evidence": "some", "_source_ref": {"file_id": "f1", "section": "A"}},
            ]),
            self._chunk_result("Tech.pdf — B", [
                {"req_id": "R1", "coverage": "Fully Addressed", "confidence": "High",
                 "evidence": "more", "_source_ref": {"file_id": "f1", "section": "B"}, "evidence_strength": "STRONG"},
            ]),
        ]
        rows = analyst._aggregate_requirement_coverage([{"req_id": "R1", "category": "Rated"}], chunk_results, True)
        row = rows[0]
        assert row["coverage"] == "Fully Addressed"  # winner unchanged (strongest-coverage-wins)
        assert row["evidence_strength"] == "STRONG"
        assert len(row["proposal_source_refs"]) == 2  # BOTH locations preserved, not just the winner's

    def test_legacy_fields_still_populated_for_existing_ui_pdf(self):
        chunk_results = [self._chunk_result("Tech.pdf — A", [
            {"req_id": "R1", "coverage": "Fully Addressed", "confidence": "High",
             "evidence": "concrete evidence", "_source_ref": {}},
        ])]
        rows = analyst._aggregate_requirement_coverage([{"req_id": "R1", "category": "Rated"}], chunk_results, True)
        assert rows[0]["evidence_location"] == "Tech.pdf — A"
        assert rows[0]["notes"] == "concrete evidence"

    def test_absence_row_has_empty_source_refs_never_fabricated(self):
        rows = analyst._aggregate_requirement_coverage([{"req_id": "R1", "category": "Rated"}], [], True)
        assert rows[0]["coverage"] == "Not Addressed"
        assert rows[0]["proposal_source_refs"] == []

    def test_score_and_coverage_classification_unchanged_by_pi2a(self):
        """Coverage rank / Fully > Partially classification logic must be
        byte-for-byte the same as before PI-2A -- only additive fields
        were introduced."""
        chunk_results = [
            self._chunk_result("A", [{"req_id": "R1", "coverage": "Partially Addressed", "confidence": "Low",
                                      "evidence": "e", "_source_ref": {}}]),
            self._chunk_result("B", [{"req_id": "R1", "coverage": "Fully Addressed", "confidence": "High",
                                      "evidence": "e2", "_source_ref": {}}]),
        ]
        rows = analyst._aggregate_requirement_coverage([{"req_id": "R1", "category": "Rated"}], chunk_results, True)
        assert rows[0]["coverage"] == "Fully Addressed"


class TestAggregateFindingsPI2A:

    def test_deficiency_type_kept_separate_from_existing_theme_field(self):
        chunk_results = [{"chunk_label": "L", "requirement_assertions": [], "chunk_findings": [
            {"severity": "High", "title": "Unclear pricing", "issue": "pricing is ambiguous and incomplete",
             "recommendation": "clarify", "deficiency_type": "WEAK_EVIDENCE", "_source_ref": {"file_id": "f1"}},
        ]}]
        findings = analyst._aggregate_findings(chunk_results)
        f = findings[0]
        assert f["deficiency_type"] == "WEAK_EVIDENCE"
        assert f["finding_type"] != "WEAK_EVIDENCE"  # unrelated pre-existing theme label, untouched
        assert f["proposal_source_refs"][0]["file_id"] == "f1"


class TestAggregateProposalObservations:

    def test_dedups_exact_duplicates_across_overlapping_chunks(self):
        chunk_results = [
            {"chunk_label": "A", "proposal_observations": [
                {"observation_type": "DELIVERY_COMMITMENT", "req_id": "R1", "title": "t",
                 "statement": "We commit to a 4-hour response SLA.", "implication": "i", "confidence": "High",
                 "proposal_location": "A", "_source_ref": {"file_id": "f1"}},
            ]},
            {"chunk_label": "B", "proposal_observations": [
                {"observation_type": "DELIVERY_COMMITMENT", "req_id": "R1", "title": "t",
                 "statement": "We commit to a 4-hour response SLA.", "implication": "i", "confidence": "High",
                 "proposal_location": "B", "_source_ref": {"file_id": "f1"}},
            ]},
        ]
        out = analyst._aggregate_proposal_observations(chunk_results)
        assert len(out) == 1

    def test_never_merges_genuinely_different_observations(self):
        chunk_results = [
            {"chunk_label": "A", "proposal_observations": [
                {"observation_type": "DELIVERY_COMMITMENT", "req_id": "R1", "title": "t",
                 "statement": "4-hour SLA.", "implication": "i", "confidence": "High",
                 "proposal_location": "A", "_source_ref": {}},
            ]},
            {"chunk_label": "B", "proposal_observations": [
                {"observation_type": "COMMERCIAL_EXPOSURE", "req_id": "R1", "title": "t2",
                 "statement": "Travel costs are billed separately.", "implication": "i2", "confidence": "Medium",
                 "proposal_location": "B", "_source_ref": {}},
            ]},
        ]
        out = analyst._aggregate_proposal_observations(chunk_results)
        assert len(out) == 2

    def test_stable_ordering_by_first_appearance(self):
        chunk_results = [
            {"chunk_label": "A", "proposal_observations": [
                {"observation_type": "DELIVERY_COMMITMENT", "req_id": None, "title": "first",
                 "statement": "s1", "implication": "", "confidence": "High", "proposal_location": "A", "_source_ref": {}},
            ]},
            {"chunk_label": "B", "proposal_observations": [
                {"observation_type": "DELIVERY_COMMITMENT", "req_id": None, "title": "second",
                 "statement": "s2", "implication": "", "confidence": "High", "proposal_location": "B", "_source_ref": {}},
            ]},
        ]
        out = analyst._aggregate_proposal_observations(chunk_results)
        assert [o["title"] for o in out] == ["first", "second"]


class TestChunkPromptSchemaAdditions:

    def test_schema_exposes_new_optional_fields(self):
        chunk = {"heading": "Pricing", "index": 0, "total": 1, "text": "Some text."}
        prompt = analyst._align_chunk_prompt("BID: X | CLIENT: Y", "context", "reqs", chunk)
        assert "evidence_strength" in prompt
        assert "deficiency_type" in prompt
        assert "proposal_observations" in prompt
        assert "DELIVERY_COMMITMENT" in prompt and "COMMERCIAL_EXPOSURE" in prompt

    def test_prompt_never_asks_model_for_physical_identity(self):
        chunk = {"heading": "Pricing", "index": 0, "total": 1, "text": "Some text."}
        prompt = analyst._align_chunk_prompt("BID: X | CLIENT: Y", "context", "reqs", chunk)
        assert "file_id" not in prompt and "content_hash" not in prompt and "char_start" not in prompt


# ── proposal_intelligence.py adapter: PI-2A additions ───────────────────────

class TestAdapterStructuredProvenance:

    def test_prefers_structured_refs_over_legacy_free_text(self):
        alignment_result = {"requirement_coverage": [
            {"req_id": "R1", "coverage": "Fully Addressed", "confidence": "High",
             "evidence_location": "Tech.pdf — A", "notes": "evidence",
             "proposal_source_refs": [{"file_id": "f1", "section": "A", "char_start": 0, "char_end": 10}],
             "evidence_strength": "STRONG"},
        ]}
        rows = pi.adapt_requirement_assessments(alignment_result, [{"req_id": "R1", "id": 7}])
        assert rows[0]["proposal_source_refs"] == [{"file_id": "f1", "section": "A", "char_start": 0, "char_end": 10}]
        assert rows[0]["evidence_strength"] == "STRONG"
        assert rows[0]["requirement_id"] == 7

    def test_falls_back_to_legacy_shape_without_crashing(self):
        """A PI-1-shaped result (no proposal_source_refs/evidence_strength
        keys at all) must still adapt cleanly."""
        alignment_result = {"requirement_coverage": [
            {"req_id": "R1", "coverage": "Fully Addressed", "confidence": "High",
             "evidence_location": "Tech.pdf — A", "notes": "evidence"},
        ]}
        rows = pi.adapt_requirement_assessments(alignment_result, [{"req_id": "R1", "id": 7}])
        assert rows[0]["proposal_source_refs"] == [{"evidence_location": "Tech.pdf — A", "excerpt": "evidence"}]
        assert rows[0]["evidence_strength"] is None

    def test_invalid_evidence_strength_fails_closed_to_none(self):
        alignment_result = {"requirement_coverage": [
            {"req_id": "R1", "coverage": "Fully Addressed", "confidence": "High",
             "evidence_location": "", "notes": "", "evidence_strength": "TOTALLY_MADE_UP"},
        ]}
        rows = pi.adapt_requirement_assessments(alignment_result, [{"req_id": "R1", "id": 1}])
        assert rows[0]["evidence_strength"] is None


class TestAdapterProcurementProvenance:

    def test_resolves_canonical_source_refs_by_exact_req_id(self):
        requirements = [{"req_id": "R1", "id": 7, "source_refs": [{"document": "RFP.pdf", "page": 3}]}]
        alignment_result = {"requirement_coverage": [
            {"req_id": "R1", "coverage": "Fully Addressed", "confidence": "High",
             "evidence_location": "", "notes": ""},
        ]}
        rows = pi.adapt_requirement_assessments(alignment_result, requirements)
        assert rows[0]["procurement_source_refs"] == [{"document": "RFP.pdf", "page": 3}]

    def test_no_canonical_source_refs_yields_empty_list_never_synthesized(self):
        requirements = [{"req_id": "R1", "id": 7}]
        alignment_result = {"requirement_coverage": [
            {"req_id": "R1", "coverage": "Fully Addressed", "confidence": "High",
             "evidence_location": "", "notes": ""},
        ]}
        rows = pi.adapt_requirement_assessments(alignment_result, requirements)
        assert rows[0]["procurement_source_refs"] == []

    def test_findings_linked_to_a_requirement_also_get_procurement_refs(self):
        requirements = [{"req_id": "R1", "id": 7, "source_refs": [{"document": "RFP.pdf"}]}]
        alignment_result = {"findings": [
            {"severity": "High", "req_id": "R1", "title": "t", "issue": "i", "deficiency_type": "WEAK_EVIDENCE"},
        ]}
        findings = pi.adapt_findings(alignment_result, requirements)
        assert findings[0]["procurement_source_refs"] == [{"document": "RFP.pdf"}]


class TestAdapterTypedFindings:

    def test_maps_recognized_deficiency_type(self):
        alignment_result = {"findings": [
            {"severity": "High", "req_id": "R1", "title": "t", "issue": "i", "deficiency_type": "CONTRADICTION"},
        ]}
        findings = pi.adapt_findings(alignment_result)
        assert findings[0]["finding_type"] == pi.FINDING_TYPE_CONTRADICTION

    def test_missing_deficiency_type_falls_back_to_other(self):
        alignment_result = {"findings": [{"severity": "High", "req_id": "R1", "title": "t", "issue": "i"}]}
        findings = pi.adapt_findings(alignment_result)
        assert findings[0]["finding_type"] == pi.FINDING_TYPE_OTHER

    def test_unrecognized_deficiency_type_never_guessed_falls_back_to_other(self):
        alignment_result = {"findings": [
            {"severity": "High", "req_id": "R1", "title": "t", "issue": "i", "deficiency_type": "MADE_UP_TYPE"},
        ]}
        findings = pi.adapt_findings(alignment_result)
        assert findings[0]["finding_type"] == pi.FINDING_TYPE_OTHER


class TestAdapterObservations:

    def test_delivery_commitment_maps_to_its_own_finding_type(self):
        alignment_result = {"proposal_observations": [
            {"observation_type": "DELIVERY_COMMITMENT", "req_id": "R1", "title": "24/7 support",
             "statement": "We commit to 24/7 support.", "implication": "staffing", "confidence": "High",
             "proposal_source_refs": [{"file_id": "f1"}]},
        ]}
        findings = pi.adapt_findings(alignment_result)
        assert len(findings) == 1
        assert findings[0]["finding_type"] == pi.FINDING_TYPE_DELIVERY_COMMITMENT
        assert findings[0]["message"] == "We commit to 24/7 support."
        assert findings[0]["proposal_source_refs"] == [{"file_id": "f1"}]

    def test_commercial_exposure_maps_to_its_own_finding_type(self):
        alignment_result = {"proposal_observations": [
            {"observation_type": "COMMERCIAL_EXPOSURE", "req_id": None, "title": "Travel",
             "statement": "Travel costs are billed at actuals.", "implication": "open-ended cost",
             "confidence": "Medium", "proposal_source_refs": []},
        ]}
        findings = pi.adapt_findings(alignment_result)
        assert findings[0]["finding_type"] == pi.FINDING_TYPE_COMMERCIAL_EXPOSURE

    def test_unrecognized_observation_type_never_persisted(self):
        alignment_result = {"proposal_observations": [
            {"observation_type": "SCOPE_CREEP", "statement": "x"},
        ]}
        findings = pi.adapt_findings(alignment_result)
        assert findings == []

    def test_observations_never_collide_with_deficiency_findings(self):
        alignment_result = {
            "findings": [{"severity": "High", "req_id": "R1", "title": "t", "issue": "i",
                         "deficiency_type": "WEAK_EVIDENCE"}],
            "proposal_observations": [{"observation_type": "DELIVERY_COMMITMENT", "req_id": "R1",
                                       "title": "t2", "statement": "s", "implication": "", "confidence": "High"}],
        }
        findings = pi.adapt_findings(alignment_result)
        assert len(findings) == 2
        types = {f["finding_type"] for f in findings}
        assert types == {pi.FINDING_TYPE_WEAK_EVIDENCE, pi.FINDING_TYPE_DELIVERY_COMMITMENT}


class TestIncompleteCoverageNeverManufacturesAbsence:

    def test_incomplete_package_still_preserves_positive_observations(self):
        """analyst.py's own incomplete-coverage branch must still surface
        proposal_observations gathered from chunks that WERE successfully
        analyzed (PI-2A step 18) -- absence of coverage elsewhere must
        never suppress positive evidence already found."""
        chunk_results = [{"chunk_label": "A", "proposal_observations": [
            {"observation_type": "DELIVERY_COMMITMENT", "req_id": None, "title": "t",
             "statement": "s", "implication": "", "confidence": "High", "proposal_location": "A", "_source_ref": {}},
        ]}]
        out = analyst._aggregate_proposal_observations(chunk_results)
        assert len(out) == 1  # a package-level "coverage_complete=False" never touches this function at all


class TestAnalysisVersioning:

    def test_version_bumped_to_v2(self):
        # PI-2B1 bumped ANALYSIS_VERSION again, to "proposal-intelligence-v3"
        # (see tests/test_proposal_intelligence_pi2b1.py's
        # TestAnalysisVersionBump) -- this test now only asserts the
        # version is NOT the pre-PI-2A "v1"-equivalent baseline value it
        # originally guarded against; the current literal is checked in
        # the PI-2B1 test file, kept as the single source of truth for it.
        assert pi.PROPOSAL_INTELLIGENCE_ANALYSIS_VERSION != "proposal-intelligence-v1"

    def test_old_v1_run_is_correctly_flagged_stale_against_v2(self):
        old_run = {
            "based_on_procurement_revision": 3, "proposal_package_snapshot_id": 10,
            "analysis_version": "proposal-intelligence-v1",
        }
        reasons = pi.staleness_reasons(old_run, current_procurement_revision=3, current_package_snapshot_id=10)
        assert pi.STALE_ANALYSIS_VERSION_CHANGED in reasons
        assert not pi.is_current(old_run, current_procurement_revision=3, current_package_snapshot_id=10)

    def test_new_v2_run_is_current_against_itself(self):
        run = {
            "based_on_procurement_revision": 3, "proposal_package_snapshot_id": 10,
            "analysis_version": pi.PROPOSAL_INTELLIGENCE_ANALYSIS_VERSION,
        }
        assert pi.is_current(run, current_procurement_revision=3, current_package_snapshot_id=10)


class TestReloadReconstruction:

    def test_typed_findings_survive_reload_not_dropped_as_other_only(self):
        """Regression guard: reconstruct_legacy_align_result must not
        silently drop a WEAK_EVIDENCE/UNSUPPORTED_CLAIM/etc-typed finding
        just because it isn't literally FINDING_TYPE_OTHER."""
        run = {"status": "COMPLETE", "legacy_result": {}}
        assessments = []
        findings = [{
            "finding_type": pi.FINDING_TYPE_WEAK_EVIDENCE, "severity": "Medium", "title": "t",
            "message": "i", "explanation": "r", "related_req_id": "R1",
            "proposal_source_refs": [], "procurement_source_refs": [],
            "payload": {"severity": "Medium", "title": "t", "issue": "i", "req_id": "R1"},
        }]
        result = pi.reconstruct_legacy_align_result(run, assessments, findings)
        assert len(result["findings"]) == 1
        assert result["findings"][0]["title"] == "t"

    def test_observations_reconstructed_separately_from_findings(self):
        run = {"status": "COMPLETE", "legacy_result": {}}
        findings = [{
            "finding_type": pi.FINDING_TYPE_DELIVERY_COMMITMENT, "severity": None, "title": "t",
            "message": "s", "explanation": "i", "related_req_id": None,
            "proposal_source_refs": [], "procurement_source_refs": [],
            "payload": {"observation_type": "DELIVERY_COMMITMENT", "title": "t", "statement": "s"},
        }]
        result = pi.reconstruct_legacy_align_result(run, [], findings)
        assert result["findings"] == []  # never mixed into the general Audit Findings list
        assert len(result["proposal_observations"]) == 1
        assert result["proposal_observations"][0]["observation_type"] == "DELIVERY_COMMITMENT"

    def test_legacy_pi1_run_with_no_new_fields_reloads_without_crashing(self):
        """A historical PI-1 run's assessments/findings never carried
        evidence_strength, structured proposal_source_refs beyond a single
        legacy entry, or any deficiency_type/observation rows at all."""
        run = {"status": "COMPLETE", "legacy_result": {}, "analysis_version": "proposal-intelligence-v1"}
        assessments = [{
            "req_id": "R1", "category": "Rated", "description": "d",
            "assessment_status": "Fully Addressed", "confidence": "High",
            "proposal_source_refs": [{"evidence_location": "Tech.pdf — A", "excerpt": "e"}],
        }]
        findings = [{
            "finding_type": pi.FINDING_TYPE_OTHER, "severity": "Low", "title": "t",
            "message": "i", "explanation": "r", "related_req_id": "R1",
            "payload": {"severity": "Low", "title": "t", "issue": "i"},
        }]
        result = pi.reconstruct_legacy_align_result(run, assessments, findings)
        assert result["requirement_coverage"][0]["evidence_strength"] is None
        assert len(result["findings"]) == 1
        assert result["proposal_observations"] == []
