import copy

from opportunity_intelligence import _record_id
from opportunity_structure import (
    FAMILIES, SCHEMA_VERSION, build_opportunity_structure,
)


def _metadata(*names):
    return {
        "files": list(names),
        "doc_metadata": {name: {"page_count": 1} for name in names},
        "doc_texts": {name: f"[[SOURCE: {name} | PAGE: 1]]\nSample requirement text for {name}"
                      for name in names},
    }


def _ref(doc="a.pdf", excerpt="Sample requirement text for a.pdf", page=1):
    return {"source_doc": doc, "page": page, "excerpt": excerpt}


def _requirement(req_id="M1", description="A requirement", doc="a.pdf"):
    return {"req_id": req_id, "category": "Mandatory", "requirement_type": "Submission Compliance",
            "description": description, "rfso_ref": "1", "weight": None, "evidence": None,
            "evidence_status": "MISSING",
            "source_refs": [_ref(doc, "Sample requirement text for " + doc)]}


def _facts(**sections):
    facts = {"requirements": [], "evaluation_criteria": [], "commercial_clauses": [],
             "deliverables": [], "submission_rules": []}
    facts.update(sections)
    return facts


def test_builds_one_record_per_family_with_reused_stage_a_identity():
    facts = _facts(
        requirements=[_requirement("M1")],
        evaluation_criteria=[{"criterion_id": None, "title": "Corporate Profile",
                              "source_refs": [_ref()]}],
        commercial_clauses=[{"clause_id": "clause_abc", "clause_kind": "LIABILITY_INDEMNITY",
                             "source_refs": [_ref()]}],
        deliverables=[{"deliverable_id": "dlv_abc", "title": "Report", "source_refs": [_ref()]}],
        submission_rules=[{"item": "Appendix A", "mandatory": 1, "source_refs": [_ref()]}],
    )
    structure = build_opportunity_structure(facts, _metadata("a.pdf"))
    assert structure["schema_version"] == SCHEMA_VERSION
    by_family = {r["family"]: r for r in structure["records"]}
    assert set(by_family) == FAMILIES
    # req_id is a document-local Stage A label, never trusted as identity --
    # reuse the exact deterministic content-and-position hash
    # opportunity_intelligence.py's own _record_id computes for "requirements".
    assert by_family["REQUIREMENT"]["record_id"] == _record_id(
        "requirements", facts["requirements"][0], 0)
    assert by_family["REQUIREMENT"]["fields"]["req_id"] == "M1"
    # clause_id/deliverable_id are already contract_hygiene.py's own
    # deterministic content hashes, not document-local labels -- these
    # remain trusted directly.
    assert by_family["COMMERCIAL_CLAUSE"]["record_id"] == "clause_abc"
    assert by_family["DELIVERABLE"]["record_id"] == "dlv_abc"
    # criterion_id and submission_rule_id were absent -> reuse the exact
    # deterministic hash-derived identity opportunity_intelligence.py's own
    # _record_id already computes for the same (section, record, index).
    assert by_family["EVALUATION_CRITERION"]["record_id"] == _record_id(
        "evaluation_criteria", facts["evaluation_criteria"][0], 0)
    assert by_family["SUBMISSION_RULE"]["record_id"] == _record_id(
        "submission_rules", facts["submission_rules"][0], 0)


def test_verified_source_ref_yields_verified_provenance():
    facts = _facts(requirements=[_requirement("M1")])
    structure = build_opportunity_structure(facts, _metadata("a.pdf"))
    assert structure["records"][0]["provenance_status"] == "VERIFIED"


def test_unresolvable_source_document_yields_unverified_provenance():
    req = _requirement("M1")
    req["source_refs"][0]["source_doc"] = "does-not-exist.pdf"
    structure = build_opportunity_structure(_facts(requirements=[req]), _metadata("a.pdf"))
    assert structure["records"][0]["provenance_status"] == "UNVERIFIED"


def test_locator_present_but_excerpt_unverifiable_yields_partial_provenance():
    req = _requirement("M1")
    req["source_refs"][0]["excerpt"] = "This text does not appear anywhere in the source"
    structure = build_opportunity_structure(_facts(requirements=[req]), _metadata("a.pdf"))
    assert structure["records"][0]["provenance_status"] == "PARTIAL"


def test_record_with_no_source_refs_has_no_provenance_and_is_publishable():
    req = _requirement("M1")
    req["source_refs"] = []
    structure = build_opportunity_structure(_facts(requirements=[req]), _metadata("a.pdf"))
    assert structure["records"][0]["provenance_status"] == "UNVERIFIED"
    assert structure["records"][0]["source_refs"] == []


def test_identical_repeated_record_merges_into_one_with_occurrence_count():
    req = _requirement("M1")
    structure = build_opportunity_structure(
        _facts(requirements=[copy.deepcopy(req), copy.deepcopy(req)]), _metadata("a.pdf"))
    assert len(structure["records"]) == 1
    assert structure["records"][0]["occurrence_count"] == 2


def test_identical_record_with_an_additional_source_ref_unions_refs():
    metadata = _metadata("a.pdf", "b.pdf")
    first = _requirement("M1", doc="a.pdf")
    second = copy.deepcopy(first)
    # Same identity and same semantic fields, but a genuinely additional
    # ref from a second document -- must be unioned in, not discarded.
    second["source_refs"].append(_ref("b.pdf", "Sample requirement text for b.pdf"))
    structure = build_opportunity_structure(_facts(requirements=[first, second]), metadata)
    assert len(structure["records"]) == 1
    record = structure["records"][0]
    assert record["occurrence_count"] == 2
    assert len(record["source_refs"]) == 2


def test_same_local_id_with_different_content_from_different_documents_is_not_a_collision():
    # Stage A assigns req_id per source document, not per package -- the
    # same label can legitimately name two unrelated requirements from two
    # different documents (confirmed by live commissioning of the real Bank
    # of Canada corpus). Because identity is never derived from that label,
    # both are published distinctly, with distinct real identities, and
    # neither is merged, dropped, or flagged as a collision.
    req_a = _requirement("M1", description="Requirement from document A", doc="a.pdf")
    req_b = _requirement("M1", description="A completely different requirement", doc="b.pdf")
    structure = build_opportunity_structure(
        _facts(requirements=[req_a, req_b]), _metadata("a.pdf", "b.pdf"))
    assert structure["integrity_diagnostics"]["collision_free"] is True
    assert len(structure["records"]) == 2
    assert len({r["record_id"] for r in structure["records"]}) == 2
    descriptions = {r["fields"]["description"] for r in structure["records"]}
    assert descriptions == {"Requirement from document A", "A completely different requirement"}


def test_explicit_id_collision_across_different_content_is_flagged_not_merged():
    # clause_id/deliverable_id are trusted directly (contract_hygiene.py
    # already guarantees they are content-derived and unique) -- but this
    # ledger must never silently trust that guarantee blindly. If two
    # differently-worded clauses were ever assigned the same clause_id, that
    # is a genuine identity collision and must be recorded, never merged.
    clause_a = {"clause_id": "clause_abc", "clause_kind": "LIABILITY_INDEMNITY",
                "topic": "Liability", "source_refs": [_ref()]}
    clause_b = {"clause_id": "clause_abc", "clause_kind": "CONFIDENTIALITY",
                "topic": "Confidentiality", "source_refs": [_ref()]}
    structure = build_opportunity_structure(
        _facts(commercial_clauses=[clause_a, clause_b]), _metadata("a.pdf"))
    assert structure["integrity_diagnostics"]["collision_free"] is False
    assert len(structure["integrity_diagnostics"]["collision_ids"]) == 1
    assert len(structure["records"]) == 1


def test_conflict_flag_produces_a_conflict_object_linked_to_its_record():
    criterion = {"criterion_id": None, "title": "Corporate Profile",
                 "role_conflict": True, "role_observations": ["Award Criterion", "Subcriterion"],
                 "source_refs": [_ref()]}
    structure = build_opportunity_structure(
        _facts(evaluation_criteria=[criterion]), _metadata("a.pdf"))
    record = structure["records"][0]
    assert len(structure["conflicts"]) == 1
    conflict = structure["conflicts"][0]
    assert conflict["field"] == "role"
    assert conflict["incompatible_values"] == ["Award Criterion", "Subcriterion"]
    assert conflict["affected_record_ids"] == [record["record_id"]]
    assert record["conflict_ids"] == [conflict["conflict_id"]]


def test_non_mapping_records_are_skipped_and_recorded_as_invalid():
    structure = build_opportunity_structure(
        _facts(requirements=[_requirement("M1"), "not-a-mapping", 42]), _metadata("a.pdf"))
    assert len(structure["records"]) == 1
    assert len(structure["integrity_diagnostics"]["invalid_records"]) == 2


def test_coverage_reports_family_presence():
    structure = build_opportunity_structure(
        _facts(requirements=[_requirement("M1")]), _metadata("a.pdf"))
    assert structure["coverage"]["REQUIREMENT"]["records_present"] is True
    assert structure["coverage"]["DELIVERABLE"]["records_present"] is False


def test_build_is_deterministic_across_repeated_calls():
    # Replay determinism means the same real normalized_facts input always
    # produces the same output -- not that reordering an input list must be
    # a no-op. A hash-fallback identity (used whenever a family has no
    # trusted native ID, including "requirements" now that req_id is no
    # longer trusted) is deliberately position-salted, so it is tied to
    # Stage C's own already-deterministic list order, exactly like
    # opportunity_intelligence.py's existing evaluation_criteria/
    # submission_rules identities already are today.
    facts = _facts(requirements=[_requirement("M1", doc="a.pdf"), _requirement("M2", doc="a.pdf")])
    first = build_opportunity_structure(facts, _metadata("a.pdf"))
    second = build_opportunity_structure(copy.deepcopy(facts), _metadata("a.pdf"))
    assert first["input_digest"] == second["input_digest"]
    assert first["records"] == second["records"]


def test_explicit_id_families_are_order_independent():
    # Families with a trusted native ID (clause_id/deliverable_id) never
    # depend on list position, so their ledger content is independent of
    # input order.
    clause_a = {"clause_id": "clause_a", "clause_kind": "LIABILITY_INDEMNITY", "source_refs": [_ref()]}
    clause_b = {"clause_id": "clause_b", "clause_kind": "CONFIDENTIALITY", "source_refs": [_ref()]}
    forward = build_opportunity_structure(
        _facts(commercial_clauses=[clause_a, clause_b]), _metadata("a.pdf"))
    backward = build_opportunity_structure(
        _facts(commercial_clauses=[copy.deepcopy(clause_b), copy.deepcopy(clause_a)]), _metadata("a.pdf"))
    assert forward["input_digest"] == backward["input_digest"]
    assert forward["records"] == backward["records"]


def test_source_refs_and_occurrences_are_excluded_from_published_fields():
    clause = {"clause_id": "clause_abc", "clause_kind": "LIABILITY_INDEMNITY",
              "source_refs": [_ref()], "occurrences": [{"occurrence_id": "x"}]}
    structure = build_opportunity_structure(
        _facts(commercial_clauses=[clause]), _metadata("a.pdf"))
    record = structure["records"][0]
    assert "source_refs" not in record["fields"]
    assert "occurrences" not in record["fields"]
    assert record["fields"]["clause_kind"] == "LIABILITY_INDEMNITY"
