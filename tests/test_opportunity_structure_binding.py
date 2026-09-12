from datetime import date
from hashlib import sha256

import pytest

from opportunity_structure_binding import StructureBindingError, build_structure_bindings
from evidence import (
    ArtifactKind,
    AuthenticityState,
    EvidenceArtifact,
    EvidenceExtract,
    EvidenceOccurrence,
    EvidenceSource,
    LocatorKind,
    SourceKind,
    create_evidence_snapshot,
)
from evidence_publication import publish_evidence, validate_evidence_publication


FILENAME = "RFP.pdf"


def _hash(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def _snapshot_and_publication(*, page="1", section=None, text="The supplier shall respond within ten days."):
    content = text.encode("utf-8")
    digest = _hash(text)
    source = EvidenceSource("source:buyer", "Buyer", SourceKind.ORGANIZATION, "https://buyer.example/")
    artifact = EvidenceArtifact(
        source.object_id, ArtifactKind.DOCUMENT, FILENAME, "1", "application/pdf", "en", digest, content)
    locator_kind = LocatorKind.PAGE if page else LocatorKind.SECTION
    locator = f"page:{page}" if page else f"section:{section}"
    occurrence = EvidenceOccurrence(
        source.object_id, artifact.object_id, f"{digest}:0",
        locator_kind, locator, "en", date(2026, 9, 8), AuthenticityState.VERIFIED, digest)
    extract = EvidenceExtract(
        artifact.object_id, occurrence.object_id, locator_kind, locator, "en", text, digest)
    snapshot = create_evidence_snapshot((source, artifact, occurrence, extract))
    publication = validate_evidence_publication(publish_evidence(snapshot))
    return snapshot, publication


def _structure(records):
    return {"records": records}


def _record(record_id="req_1", *, page="1", excerpt="The supplier shall respond within ten days.",
            extra_ref=None, provenance_status="VERIFIED"):
    ref = {"source_doc": FILENAME, "page": page, "excerpt": excerpt}
    refs = [ref] if extra_ref is None else [ref, extra_ref]
    return {"record_id": record_id, "source_refs": refs, "provenance_status": provenance_status}


def test_binds_a_single_verified_ref_to_the_exact_occurrence_and_extract():
    snapshot, publication = _snapshot_and_publication(page="1")
    structure = _structure([_record()])
    bindings = build_structure_bindings(structure, snapshot, publication)
    assert len(bindings) == 1
    binding = bindings[0]
    assert binding.record_id == "req_1"
    assert len(binding.evidence_references) == 1
    assert len(binding.provenance_references) == 1
    assert binding.evidence_references[0].object_class == "EVIDENCE_EXTRACT"
    assert binding.provenance_references[0].object_class == "EVIDENCE_OCCURRENCE"


def test_record_without_source_gets_empty_bindings():
    snapshot, publication = _snapshot_and_publication()
    structure = _structure([{"record_id": "req_none", "source_refs": [], "provenance_status": "UNVERIFIED"}])
    bindings = build_structure_bindings(structure, snapshot, publication)
    assert bindings == (bindings[0].__class__("req_none", (), ()),)


def test_fails_closed_when_no_occurrence_matches_the_locator():
    snapshot, publication = _snapshot_and_publication(page="1")
    structure = _structure([_record(page="99")])
    with pytest.raises(StructureBindingError, match="no Evidence occurrence matches"):
        build_structure_bindings(structure, snapshot, publication)


def test_fails_closed_when_excerpt_is_not_verbatim_in_the_extract():
    snapshot, publication = _snapshot_and_publication(page="1")
    structure = _structure([_record(excerpt="This text was never in the document.")])
    with pytest.raises(StructureBindingError, match="excerpt not found verbatim"):
        build_structure_bindings(structure, snapshot, publication)


def test_partial_provenance_record_gets_empty_binding_instead_of_raising():
    snapshot, publication = _snapshot_and_publication(page="1")
    structure = _structure([_record(page="99", provenance_status="PARTIAL")])
    bindings = build_structure_bindings(structure, snapshot, publication)
    assert bindings == (bindings[0].__class__("req_1", (), ()),)


def test_verified_record_still_fails_closed_even_when_unresolvable():
    snapshot, publication = _snapshot_and_publication(page="1")
    structure = _structure([_record(page="99", provenance_status="VERIFIED")])
    with pytest.raises(StructureBindingError):
        build_structure_bindings(structure, snapshot, publication)


def test_missing_provenance_status_still_fails_closed_by_default():
    snapshot, publication = _snapshot_and_publication(page="1")
    structure = _structure([{"record_id": "req_1", "source_refs": [
        {"source_doc": FILENAME, "page": "99", "excerpt": "x"}]}])
    with pytest.raises(StructureBindingError):
        build_structure_bindings(structure, snapshot, publication)


def test_stale_evidence_publication_is_refused():
    snapshot, publication = _snapshot_and_publication(page="1")
    other_snapshot, _ = _snapshot_and_publication(page="2")
    structure = _structure([_record()])
    with pytest.raises(StructureBindingError, match="does not attest"):
        build_structure_bindings(structure, other_snapshot, publication)
