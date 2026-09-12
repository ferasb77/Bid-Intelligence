import copy

import pytest

from governed_reference_resolution import (
    AuthorityClass, SemanticField, SemanticValue, SemanticValueKind,
    create_governed_object, create_governed_snapshot, reference_to,
)
from opportunity_structure import build_opportunity_structure
from opportunity_structure_publication import (
    CONFLICT_CLASS, OpportunityStructurePublicationError,
    OpportunityStructureRecordBinding, StructurePublicationFailureCode,
    publish_opportunity_structure, validate_opportunity_structure_publication,
)


def _metadata(*names):
    return {
        "files": list(names),
        "doc_metadata": {name: {"page_count": 1} for name in names},
        "doc_texts": {name: f"[[SOURCE: {name} | PAGE: 1]]\nSample requirement text for {name}"
                      for name in names},
    }


def _ref(doc="a.pdf", excerpt=None, page=1):
    return {"source_doc": doc, "page": page, "excerpt": excerpt or f"Sample requirement text for {doc}"}


def _requirement(req_id="M1", doc="a.pdf"):
    return {"req_id": req_id, "category": "Mandatory", "requirement_type": "Submission Compliance",
            "description": "A requirement", "rfso_ref": "1", "weight": None, "evidence": None,
            "evidence_status": "MISSING", "source_refs": [_ref(doc)]}


def _criterion_with_conflict():
    return {"criterion_id": None, "title": "Corporate Profile", "role_conflict": True,
            "role_observations": ["Award Criterion", "Subcriterion"], "source_refs": [_ref()]}


def _facts(**sections):
    facts = {"requirements": [], "evaluation_criteria": [], "commercial_clauses": [],
             "deliverables": [], "submission_rules": []}
    facts.update(sections)
    return facts


def _structure(**sections):
    return build_opportunity_structure(_facts(**sections), _metadata("a.pdf"))


def _external_reference(object_class="EVIDENCE", object_id="evidence-1"):
    obj = create_governed_object(
        owner_domain="opportunity-evidence", owner_contract="evidence-record",
        contract_version="1.0.0", object_class=object_class, object_id=object_id,
        authority=AuthorityClass.EVIDENCE,
        semantic_fields=(SemanticField("digest", SemanticValue(SemanticValueKind.STRING, "d")),),
    )
    snapshot = create_governed_snapshot(
        owner_domain="opportunity-evidence", owner_contract="evidence-record",
        contract_version="1.0.0", snapshot_id="evidence-snapshot-1", objects=(obj,))
    return reference_to(snapshot, object_class, object_id)


def _bindings(structure, *, with_evidence=True):
    evidence = _external_reference("EVIDENCE", "evidence-1")
    provenance = _external_reference("PROVENANCE", "provenance-1")
    result = []
    for record in structure["records"]:
        has_source = bool(record["source_refs"])
        if has_source and with_evidence:
            result.append(OpportunityStructureRecordBinding(record["record_id"], (evidence,), (provenance,)))
        else:
            result.append(OpportunityStructureRecordBinding(record["record_id"], (), ()))
    return tuple(sorted(result, key=lambda item: item.record_id))


def _publish(structure=None, **kwargs):
    structure = structure if structure is not None else _structure(requirements=[_requirement("M1")])
    bindings = kwargs.pop("record_bindings", None) or _bindings(structure)
    return publish_opportunity_structure(structure, opportunity_id="opportunity-1", record_bindings=bindings)


def test_publishes_one_object_per_record_and_conflict():
    structure = _structure(requirements=[_requirement("M1")], evaluation_criteria=[_criterion_with_conflict()])
    publication = _publish(structure)
    classes = {item.object_class for item in publication.snapshot.objects}
    assert classes == {"REQUIREMENT", "EVALUATION_CRITERION", CONFLICT_CLASS}
    assert sum(1 for item in publication.snapshot.objects if item.object_class == "REQUIREMENT") == 1
    assert sum(1 for item in publication.snapshot.objects if item.object_class == CONFLICT_CLASS) == 1


def test_publication_is_deterministic_and_reconstructible():
    structure = _structure(requirements=[_requirement("M1")])
    first = _publish(structure)
    second = _publish(structure)
    assert first.digest == second.digest
    assert first.publication_id == second.publication_id
    validate_opportunity_structure_publication(first)


def test_record_with_source_refs_and_no_binding_evidence_fails_closed():
    structure = _structure(requirements=[_requirement("M1")])
    record_id = structure["records"][0]["record_id"]
    bindings = (OpportunityStructureRecordBinding(record_id, (), ()),)
    with pytest.raises(OpportunityStructurePublicationError) as excinfo:
        publish_opportunity_structure(structure, opportunity_id="opportunity-1", record_bindings=bindings)
    assert excinfo.value.code == StructurePublicationFailureCode.MISSING_RELATIONSHIP_BINDING


def test_partial_provenance_record_may_publish_with_empty_binding():
    req = _requirement("M1")
    req["source_refs"][0]["excerpt"] = "This text is not present in the source"
    structure = _structure(requirements=[req])
    assert structure["records"][0]["provenance_status"] == "PARTIAL"
    record_id = structure["records"][0]["record_id"]
    bindings = (OpportunityStructureRecordBinding(record_id, (), ()),)
    publication = publish_opportunity_structure(structure, opportunity_id="opportunity-1", record_bindings=bindings)
    assert publication.snapshot.objects[0].object_id == record_id


def test_record_with_no_source_and_a_populated_binding_fails_closed():
    req = _requirement("M1")
    req["source_refs"] = []
    structure = _structure(requirements=[req])
    record_id = structure["records"][0]["record_id"]
    evidence = _external_reference("EVIDENCE", "evidence-1")
    bindings = (OpportunityStructureRecordBinding(record_id, (evidence,), ()),)
    with pytest.raises(OpportunityStructurePublicationError) as excinfo:
        publish_opportunity_structure(structure, opportunity_id="opportunity-1", record_bindings=bindings)
    assert excinfo.value.code == StructurePublicationFailureCode.BROKEN_RELATIONSHIP


def test_collision_free_false_blocks_publication():
    # req_id is document-local and no longer trusted as identity, so two
    # differently-worded requirements sharing a req_id are NOT a collision
    # (see test_opportunity_structure.py). A genuine collision can still
    # occur for a family with a trusted native ID (clause_id) if two
    # differently-worded clauses were ever assigned the same one.
    clause_a = {"clause_id": "clause_abc", "clause_kind": "LIABILITY_INDEMNITY", "source_refs": [_ref()]}
    clause_b = {"clause_id": "clause_abc", "clause_kind": "CONFIDENTIALITY", "source_refs": [_ref()]}
    structure = build_opportunity_structure(
        _facts(commercial_clauses=[clause_a, clause_b]), _metadata("a.pdf"))
    assert structure["integrity_diagnostics"]["collision_free"] is False
    bindings = _bindings(structure)
    with pytest.raises(OpportunityStructurePublicationError) as excinfo:
        publish_opportunity_structure(structure, opportunity_id="opportunity-1", record_bindings=bindings)
    assert excinfo.value.code == StructurePublicationFailureCode.INVALID_STRUCTURE_STATE


def test_bindings_must_exactly_cover_records():
    structure = _structure(requirements=[_requirement("M1")])
    with pytest.raises(OpportunityStructurePublicationError) as excinfo:
        publish_opportunity_structure(structure, opportunity_id="opportunity-1", record_bindings=())
    assert excinfo.value.code == StructurePublicationFailureCode.MISSING_RELATIONSHIP_BINDING


def test_unsupported_schema_version_is_rejected():
    structure = _structure(requirements=[_requirement("M1")])
    structure = dict(structure, schema_version="opportunity-structure/999")
    with pytest.raises(OpportunityStructurePublicationError) as excinfo:
        publish_opportunity_structure(structure, opportunity_id="opportunity-1", record_bindings=_bindings(structure))
    assert excinfo.value.code == StructurePublicationFailureCode.VERSION_MISMATCH


def test_publication_does_not_mutate_its_source():
    structure = _structure(requirements=[_requirement("M1")])
    before = copy.deepcopy(structure)
    _publish(structure)
    assert structure == before
