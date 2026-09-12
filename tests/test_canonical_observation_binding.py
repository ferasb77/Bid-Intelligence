from datetime import date

import pytest

from canonical_observation_binding import ObservationBindingError, build_observation_bindings
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
    from hashlib import sha256
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


def _canonical(observations):
    return {"observations": observations}


def _observation(oid="obs_1", *, page="1", excerpt="The supplier shall respond within ten days.",
                 extra_ref=None, provenance_status="VERIFIED"):
    ref = {"source_doc": FILENAME, "page": page, "excerpt": excerpt}
    refs = [ref] if extra_ref is None else [ref, extra_ref]
    return {
        "observation_id": oid,
        "source_refs": refs,
        "extraction_occurrences": [{"digest": "occ_1", "count": 1}],
        "provenance_status": provenance_status,
    }


def test_binds_a_single_verified_ref_to_the_exact_occurrence_and_extract():
    snapshot, publication = _snapshot_and_publication(page="1")
    canonical = _canonical([_observation()])
    bindings = build_observation_bindings(canonical, snapshot, publication)
    assert len(bindings) == 1
    binding = bindings[0]
    assert binding.observation_id == "obs_1"
    assert len(binding.evidence_references) == 1
    assert len(binding.provenance_references) == 1
    assert binding.evidence_references[0].object_class == "EVIDENCE_EXTRACT"
    assert binding.provenance_references[0].object_class == "EVIDENCE_OCCURRENCE"


def test_hyphenated_line_wrap_excerpt_still_binds():
    """A word hyphenated across a PDF line wrap ('one-\\nyear') in the real
    Evidence extract must still bind against a clean excerpt ('one-year') --
    the words are identical, only incidental reflow whitespace differs. This
    mirrors canonical_opportunity.py's own _grounding_norm tolerance: an
    observation that module already declared VERIFIED using that tolerance
    must not fail here, in a separate, stricter re-check, over the same
    incidental artifact."""
    text = "extend for up to two additional one-\nyear terms."
    snapshot, publication = _snapshot_and_publication(page="1", text=text)
    canonical = _canonical([_observation(excerpt="extend for up to two additional one-year terms.")])
    bindings = build_observation_bindings(canonical, snapshot, publication)
    assert len(bindings[0].evidence_references) == 1


def test_missing_space_after_punctuation_excerpt_still_binds():
    text = "Duration:3 years"
    snapshot, publication = _snapshot_and_publication(page="1", text=text)
    canonical = _canonical([_observation(excerpt="Duration: 3 years")])
    bindings = build_observation_bindings(canonical, snapshot, publication)
    assert len(bindings[0].evidence_references) == 1


def test_genuinely_absent_excerpt_still_fails_closed():
    """The whitespace tolerance must not become a license to fabricate -- an
    excerpt whose actual words are not present anywhere in the extract must
    still fail closed."""
    snapshot, publication = _snapshot_and_publication(page="1", text="Unrelated content only.")
    canonical = _canonical([_observation(excerpt="Duration: 3 years", provenance_status="PARTIAL")])
    bindings = build_observation_bindings(canonical, snapshot, publication)
    assert bindings[0].evidence_references == () and bindings[0].provenance_references == ()


def test_observation_without_source_gets_empty_bindings():
    snapshot, publication = _snapshot_and_publication()
    canonical = _canonical([{"observation_id": "obs_none", "source_refs": [], "extraction_occurrences": []}])
    bindings = build_observation_bindings(canonical, snapshot, publication)
    assert bindings == (bindings[0].__class__("obs_none", (), ()),)


def test_fails_closed_when_no_occurrence_matches_the_locator():
    snapshot, publication = _snapshot_and_publication(page="1")
    canonical = _canonical([_observation(page="99")])
    with pytest.raises(ObservationBindingError, match="no Evidence occurrence matches"):
        build_observation_bindings(canonical, snapshot, publication)


def test_fails_closed_when_ref_has_no_coordinates_at_all():
    snapshot, publication = _snapshot_and_publication(page="1")
    observation = {
        "observation_id": "obs_no_coordinates",
        "source_refs": [{"source_doc": FILENAME, "excerpt": "x"}],
        "extraction_occurrences": [{"digest": "occ_1", "count": 1}],
        "provenance_status": "VERIFIED",
    }
    canonical = _canonical([observation])
    with pytest.raises(ObservationBindingError, match="does not carry a locator"):
        build_observation_bindings(canonical, snapshot, publication)


def test_fails_closed_when_sheet_only_ref_matches_no_record_occurrence():
    snapshot, publication = _snapshot_and_publication(page="1")
    observation = {
        "observation_id": "obs_sheet_only",
        "source_refs": [{"source_doc": FILENAME, "sheet": "Sheet1", "excerpt": "x"}],
        "extraction_occurrences": [{"digest": "occ_1", "count": 1}],
        "provenance_status": "VERIFIED",
    }
    canonical = _canonical([observation])
    with pytest.raises(ObservationBindingError, match="no Evidence occurrence matches"):
        build_observation_bindings(canonical, snapshot, publication)


def test_fails_closed_when_excerpt_is_not_verbatim_in_the_extract():
    snapshot, publication = _snapshot_and_publication(page="1")
    canonical = _canonical([_observation(excerpt="This text was never in the document.")])
    with pytest.raises(ObservationBindingError, match="excerpt not found verbatim"):
        build_observation_bindings(canonical, snapshot, publication)


def test_fails_closed_when_source_document_is_unknown():
    snapshot, publication = _snapshot_and_publication(page="1")
    observation = _observation()
    observation["source_refs"][0]["source_doc"] = "Unrelated.pdf"
    canonical = _canonical([observation])
    with pytest.raises(ObservationBindingError, match="source document not found"):
        build_observation_bindings(canonical, snapshot, publication)


def test_fails_closed_when_two_occurrences_share_the_same_locator():
    content = "Repeated page marker content.".encode("utf-8")
    digest = _hash("Repeated page marker content.")
    source = EvidenceSource("source:buyer", "Buyer", SourceKind.ORGANIZATION, "https://buyer.example/")
    artifact = EvidenceArtifact(
        source.object_id, ArtifactKind.DOCUMENT, FILENAME, "1", "application/pdf", "en", digest, content)
    occ_a = EvidenceOccurrence(
        source.object_id, artifact.object_id, f"{digest}:0",
        LocatorKind.PAGE, "page:1", "en", date(2026, 9, 8), AuthenticityState.VERIFIED, digest)
    occ_b = EvidenceOccurrence(
        source.object_id, artifact.object_id, f"{digest}:50",
        LocatorKind.PAGE, "page:1", "en", date(2026, 9, 8), AuthenticityState.VERIFIED, digest)
    extract_a = EvidenceExtract(
        artifact.object_id, occ_a.object_id, LocatorKind.PAGE, "page:1", "en",
        "Repeated page marker content.", digest)
    snapshot = create_evidence_snapshot((source, artifact, occ_a, occ_b, extract_a))
    publication = validate_evidence_publication(publish_evidence(snapshot))
    canonical = _canonical([_observation(excerpt="Repeated page marker content.")])
    with pytest.raises(ObservationBindingError, match="ambiguous"):
        build_observation_bindings(canonical, snapshot, publication)


def test_fails_closed_when_evidence_publication_does_not_match_the_snapshot():
    snapshot, _ = _snapshot_and_publication(page="1")
    _, other_publication = _snapshot_and_publication(page="2")
    canonical = _canonical([_observation()])
    with pytest.raises(ObservationBindingError, match="does not attest the supplied Evidence snapshot"):
        build_observation_bindings(canonical, snapshot, other_publication)


def test_bindings_are_returned_sorted_by_observation_id():
    snapshot, publication = _snapshot_and_publication(page="1")
    canonical = _canonical([_observation("obs_b"), _observation("obs_a")])
    bindings = build_observation_bindings(canonical, snapshot, publication)
    assert [item.observation_id for item in bindings] == ["obs_a", "obs_b"]


def _sheet_snapshot_and_publication(row_specs):
    """row_specs: list of (row_range, text) -- one RECORD occurrence+extract per entry."""
    source = EvidenceSource("source:buyer", "Buyer", SourceKind.ORGANIZATION, "https://buyer.example/")
    text_all = "".join(text for _, text in row_specs)
    digest = _hash(text_all)
    artifact = EvidenceArtifact(
        source.object_id, ArtifactKind.DOCUMENT, "Mandatory.xlsx", "1",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "en", digest,
        text_all.encode("utf-8"))
    objects = [source, artifact]
    for index, (rows, text) in enumerate(row_specs):
        locator = f"record:sheet=Mandatory Criteria;rows={rows}"
        occ_digest = _hash(f"{rows}:{text}")
        extract_digest = _hash(text)
        occurrence = EvidenceOccurrence(
            source.object_id, artifact.object_id, f"{occ_digest}:{index}",
            LocatorKind.RECORD, locator, "en", date(2026, 9, 8), AuthenticityState.VERIFIED, occ_digest)
        extract = EvidenceExtract(
            artifact.object_id, occurrence.object_id, LocatorKind.RECORD, locator, "en", text, extract_digest)
        objects.extend([occurrence, extract])
    snapshot = create_evidence_snapshot(tuple(objects))
    publication = validate_evidence_publication(publish_evidence(snapshot))
    return snapshot, publication


def _sheet_only_observation(oid="obs_sheet", *, excerpt="Bidder must hold valid registration.",
                            provenance_status="VERIFIED"):
    return {
        "observation_id": oid,
        "source_refs": [{"source_doc": "Mandatory.xlsx", "sheet": "Mandatory Criteria", "excerpt": excerpt}],
        "extraction_occurrences": [{"digest": "occ_1", "count": 1}],
        "provenance_status": provenance_status,
    }


def test_verified_observation_with_extraction_occurrences_but_no_source_refs_still_fails_closed():
    snapshot, publication = _snapshot_and_publication(page="1")
    observation = {
        "observation_id": "obs_no_refs",
        "source_refs": [],
        "extraction_occurrences": [{"digest": "occ_1", "count": 1}],
        "provenance_status": "VERIFIED",
    }
    canonical = _canonical([observation])
    with pytest.raises(ObservationBindingError, match="no source_refs"):
        build_observation_bindings(canonical, snapshot, publication)


def test_unverified_observation_with_extraction_occurrences_but_no_source_refs_gets_empty_binding():
    # Real production case: a typed observation (e.g. a document title) can
    # carry extraction_occurrences with no source_refs at all. Canonical
    # Opportunity's own provenance check already marks this UNVERIFIED in
    # that case; this adapter must agree rather than raise.
    snapshot, publication = _snapshot_and_publication(page="1")
    observation = {
        "observation_id": "obs_no_refs",
        "source_refs": [],
        "extraction_occurrences": [{"digest": "occ_1", "count": 1}],
        "provenance_status": "UNVERIFIED",
    }
    canonical = _canonical([observation])
    bindings = build_observation_bindings(canonical, snapshot, publication)
    assert bindings[0].evidence_references == ()
    assert bindings[0].provenance_references == ()


def test_binds_section_ref_despite_case_and_whitespace_differences_from_the_marker():
    # Regression test: canonical_opportunity.py's own _locator_matches
    # compares section names via whitespace-collapse + casefold, so this
    # adapter must match observations Canonical Opportunity already
    # declared VERIFIED even when the ref's section text and the real
    # marker's section text differ only in case or incidental whitespace.
    source = EvidenceSource("source:buyer", "Buyer", SourceKind.ORGANIZATION, "https://buyer.example/")
    text = "The supplier shall respond within ten days."
    digest = _hash(text)
    artifact = EvidenceArtifact(
        source.object_id, ArtifactKind.DOCUMENT, FILENAME, "1", "application/pdf", "en", digest,
        text.encode("utf-8"))
    marker_locator = "section:2.  Acknowledgement   of Terms"
    occurrence = EvidenceOccurrence(
        source.object_id, artifact.object_id, f"{digest}:0",
        LocatorKind.SECTION, marker_locator, "en", date(2026, 9, 8), AuthenticityState.VERIFIED, digest)
    extract = EvidenceExtract(
        artifact.object_id, occurrence.object_id, LocatorKind.SECTION, marker_locator, "en", text, digest)
    snapshot = create_evidence_snapshot((source, artifact, occurrence, extract))
    publication = validate_evidence_publication(publish_evidence(snapshot))
    observation = {
        "observation_id": "obs_case",
        "source_refs": [{"source_doc": FILENAME, "section": "2. ACKNOWLEDGEMENT OF TERMS", "excerpt": text}],
        "extraction_occurrences": [{"digest": "occ_1", "count": 1}],
        "provenance_status": "VERIFIED",
    }
    canonical = _canonical([observation])
    bindings = build_observation_bindings(canonical, snapshot, publication)
    assert len(bindings) == 1
    assert len(bindings[0].evidence_references) == 1
    assert len(bindings[0].provenance_references) == 1


def test_fails_closed_when_sheet_only_ref_excerpt_is_not_verbatim():
    # Regression test: the sheet-only fallback path does not assign
    # locator_kind/locator_str (those are exact-locator-path locals), so the
    # excerpt-mismatch error message must not reference them directly.
    snapshot, publication = _sheet_snapshot_and_publication(
        [("1-5", "Bidder must hold valid registration.")])
    canonical = _canonical([_sheet_only_observation(excerpt="This was never in the sheet.")])
    with pytest.raises(ObservationBindingError, match="excerpt not found verbatim"):
        build_observation_bindings(canonical, snapshot, publication)


def test_binds_sheet_only_ref_when_the_sheet_has_exactly_one_occurrence():
    snapshot, publication = _sheet_snapshot_and_publication(
        [("1-5", "Bidder must hold valid registration.")])
    canonical = _canonical([_sheet_only_observation()])
    bindings = build_observation_bindings(canonical, snapshot, publication)
    assert len(bindings) == 1
    assert len(bindings[0].provenance_references) == 1
    assert len(bindings[0].evidence_references) == 1


def test_fails_closed_when_sheet_only_ref_has_multiple_row_blocks():
    snapshot, publication = _sheet_snapshot_and_publication([
        ("1-5", "Bidder must hold valid registration."),
        ("6-10", "Bidder must submit audited financials."),
    ])
    canonical = _canonical([_sheet_only_observation()])
    with pytest.raises(ObservationBindingError, match="ambiguous"):
        build_observation_bindings(canonical, snapshot, publication)


def test_fails_closed_when_sheet_has_zero_occurrences_in_this_artifact():
    snapshot, publication = _sheet_snapshot_and_publication(
        [("1-5", "Unrelated content entirely.")])
    canonical = _canonical([_sheet_only_observation(excerpt="Bidder must hold valid registration.")])
    observation = canonical["observations"][0]
    observation["source_refs"][0]["sheet"] = "A Different Sheet"
    with pytest.raises(ObservationBindingError, match="no Evidence occurrence matches"):
        build_observation_bindings(canonical, snapshot, publication)


def test_partial_provenance_observation_gets_explicit_empty_binding_instead_of_raising():
    # Canonical Opportunity already declared this observation's provenance
    # PARTIAL (its own independent check, not this adapter's). This adapter
    # independently cannot ground the excerpt either -- consistent with that
    # declaration, not a new anomaly -- so it must publish an honest, empty
    # binding rather than blocking every other observation's publication.
    snapshot, publication = _snapshot_and_publication(page="1")
    canonical = _canonical([_observation(
        excerpt="This text was never in the document.", provenance_status="PARTIAL")])
    bindings = build_observation_bindings(canonical, snapshot, publication)
    assert len(bindings) == 1
    assert bindings[0].observation_id == "obs_1"
    assert bindings[0].evidence_references == ()
    assert bindings[0].provenance_references == ()


def test_unverified_provenance_observation_gets_explicit_empty_binding_instead_of_raising():
    snapshot, publication = _snapshot_and_publication(page="1")
    canonical = _canonical([_observation(page="99", provenance_status="UNVERIFIED")])
    bindings = build_observation_bindings(canonical, snapshot, publication)
    assert bindings[0].evidence_references == ()
    assert bindings[0].provenance_references == ()


def test_verified_observation_still_fails_closed_even_when_unresolvable():
    # The strict path is unchanged for observations Canonical Opportunity
    # itself already declared VERIFIED -- a binding failure there remains a
    # genuine anomaly, not an expected, already-disclosed weak state.
    snapshot, publication = _snapshot_and_publication(page="1")
    canonical = _canonical([_observation(
        excerpt="This text was never in the document.", provenance_status="VERIFIED")])
    with pytest.raises(ObservationBindingError, match="excerpt not found verbatim"):
        build_observation_bindings(canonical, snapshot, publication)


def test_missing_provenance_status_still_fails_closed_by_default():
    # Absence of a provenance_status field must not be treated as an
    # implicit license to fall back -- only an explicit, non-VERIFIED
    # declaration does. Silence is not a governed absence.
    snapshot, publication = _snapshot_and_publication(page="1")
    observation = _observation(excerpt="This text was never in the document.")
    del observation["provenance_status"]
    canonical = _canonical([observation])
    with pytest.raises(ObservationBindingError, match="excerpt not found verbatim"):
        build_observation_bindings(canonical, snapshot, publication)
