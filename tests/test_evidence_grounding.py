"""Regression coverage for the shared evidence_grounding.py module -- the
single implementation now used by both canonical_observation_binding.py and
opportunity_structure_binding.py.

These tests exercise match_refs() directly (not through either binding
adapter) so the underlying grounding algorithm -- exact locator matching,
the SECTION-only "Model 2 / hierarchical" coarser-locator fallback, and the
excerpt/locator text-normalization contract -- is proven independently of
either caller's own PARTIAL/UNVERIFIED fallback policy. A handful of
cross-adapter tests at the bottom confirm canonical_observation_binding.py
and opportunity_structure_binding.py agree on the same ref, which is the
concrete guarantee the centralization refactor exists to provide.

Fixtures are modeled on the real Bank of Canada RFP 2026-026 DOCX shape
found during the provenance-granularity remediation: a single coarse
SECTION marker (e.g. one "Header" marker for an entire Appendix) whose
extract text contains several real, human-readable clause headings that
were never themselves emitted as distinct SECTION markers. See
BANK_OF_CANADA_PROVENANCE_GRANULARITY_REMEDIATION_REPORT.md.
"""
from datetime import date
from hashlib import sha256

import pytest

from canonical_observation_binding import build_observation_bindings
from opportunity_structure_binding import build_structure_bindings
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
from evidence_grounding import build_locator_index, match_refs, normalize_excerpt_text, normalize_locator_text


FILENAME = "Appendix G - Draft Agreement.docx"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class GroundingTestError(ValueError):
    """Local stand-in for the caller-specific error types match_refs() raises through `fail`."""


def _fail(entity_id: str, reason: str):
    raise GroundingTestError(f"{entity_id}: {reason}")


def _hash(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def _build_snapshot(occurrences_spec, *, filename=FILENAME, mimetype=DOCX_MIME):
    """occurrences_spec: list of (locator_kind, locator, text) -- each becomes
    one real EvidenceOccurrence + EvidenceExtract inside one shared artifact,
    mirroring how procurement_evidence_adapter emits one occurrence per real
    [[SOURCE: ... ]] marker found in a single document."""
    source = EvidenceSource("source:buyer", "Buyer", SourceKind.ORGANIZATION, "https://buyer.example/")
    all_text = "\n".join(text for _, _, text in occurrences_spec)
    artifact = EvidenceArtifact(
        source.object_id, ArtifactKind.DOCUMENT, filename, "1", mimetype, "en", _hash(all_text),
        all_text.encode("utf-8"))
    objects = [source, artifact]
    for index, (kind, locator, text) in enumerate(occurrences_spec):
        occurrence_digest = _hash(f"{index}:{text}")
        extract_digest = _hash(text)
        occurrence = EvidenceOccurrence(
            source.object_id, artifact.object_id, f"{occurrence_digest}:{index}",
            kind, locator, "en", date(2026, 9, 8), AuthenticityState.VERIFIED, occurrence_digest)
        extract = EvidenceExtract(
            artifact.object_id, occurrence.object_id, kind, locator, "en", text, extract_digest)
        objects.extend([occurrence, extract])
    snapshot = create_evidence_snapshot(tuple(objects))
    publication = validate_evidence_publication(publish_evidence(snapshot))
    return snapshot, publication


# The Appendix-G-shaped fixture: one coarse SECTION marker for the whole
# document, whose extract text contains several real headings ("Corporate
# Profile", "Force Majeure", "Payment") that were never themselves emitted
# as distinct SECTION markers -- the confirmed, real shape of the defect.
APPENDIX_G_TEXT = (
    "Appendix G - Draft Agreement\n"
    "Corporate Profile\n"
    "The Contractor shall maintain a corporate profile current at all times.\n"
    "Force Majeure\n"
    "Neither party shall be liable for delay caused by events beyond reasonable control.\n"
    "Payment\n"
    "Payment shall be made net thirty days from invoice receipt."
)


def _appendix_g_snapshot():
    return _build_snapshot([(LocatorKind.SECTION, "section:Header", APPENDIX_G_TEXT)])


# --- 1. Exact DOCX section marker + excerpt -> matches (no fallback needed) ---

def test_exact_section_marker_and_excerpt_matches():
    snapshot, _ = _appendix_g_snapshot()
    index = build_locator_index(snapshot)
    refs = [{"source_doc": FILENAME, "section": "Header", "excerpt": "Corporate Profile"}]
    extract_ids, occurrence_ids = match_refs("e1", refs, index, _fail)
    assert len(extract_ids) == 1 and len(occurrence_ids) == 1


# --- 2. Exact locator + formatting-normalized excerpt -> still matches ---

def test_exact_locator_with_case_and_whitespace_normalized_excerpt_matches():
    snapshot, _ = _appendix_g_snapshot()
    index = build_locator_index(snapshot)
    refs = [{"source_doc": FILENAME, "section": "  HEADER  ", "excerpt": "corporate   profile"}]
    extract_ids, occurrence_ids = match_refs("e2", refs, index, _fail)
    assert len(extract_ids) == 1 and len(occurrence_ids) == 1


# --- 3. Coarse DOCX marker + grounded finer semantic section -> Class-B fallback succeeds ---

def test_coarse_section_marker_grounds_a_finer_requested_section_via_excerpt():
    snapshot, _ = _appendix_g_snapshot()
    index = build_locator_index(snapshot)
    refs = [{
        "source_doc": FILENAME, "section": "Force Majeure",
        "excerpt": "Neither party shall be liable for delay caused by events beyond reasonable control.",
    }]
    extract_ids, occurrence_ids = match_refs("e3", refs, index, _fail)
    assert len(extract_ids) == 1 and len(occurrence_ids) == 1


# --- 4. Coarse marker + unrelated requested section (excerpt not grounded) -> fails ---

def test_coarse_marker_with_excerpt_not_actually_present_fails():
    snapshot, _ = _appendix_g_snapshot()
    index = build_locator_index(snapshot)
    refs = [{"source_doc": FILENAME, "section": "Force Majeure", "excerpt": "This sentence is nowhere in the document."}]
    with pytest.raises(GroundingTestError, match="no Evidence occurrence matches"):
        match_refs("e4", refs, index, _fail)


# --- 5. Requested section absent entirely, but excerpt grounded in the coarse extract -> fallback succeeds ---

def test_requested_section_absent_but_excerpt_grounded_in_coarse_extract_matches():
    snapshot, _ = _appendix_g_snapshot()
    index = build_locator_index(snapshot)
    refs = [{
        "source_doc": FILENAME, "section": "Confidentiality",  # never appears anywhere, real or coarse
        "excerpt": "Payment shall be made net thirty days from invoice receipt.",
    }]
    extract_ids, occurrence_ids = match_refs("e5", refs, index, _fail)
    assert len(extract_ids) == 1 and len(occurrence_ids) == 1


# --- 6. Requested section absent AND excerpt not grounded -> fails closed ---

def test_requested_section_absent_and_excerpt_not_grounded_fails_closed():
    snapshot, _ = _appendix_g_snapshot()
    index = build_locator_index(snapshot)
    refs = [{"source_doc": FILENAME, "section": "Confidentiality", "excerpt": "This text is fabricated."}]
    with pytest.raises(GroundingTestError, match="no Evidence occurrence matches"):
        match_refs("e6", refs, index, _fail)


# --- 7. PDF hyphenated line-wrap grounding still passes (through the fallback too) ---

def test_hyphenated_line_wrap_excerpt_still_grounds_via_fallback():
    # "one-year" is a genuinely hyphenated compound word; a PDF/DOCX line
    # wrap can split it across a newline ("one-\nyear") without changing the
    # word itself. The clean excerpt keeps the hyphen -- only the incidental
    # newline differs.
    text = APPENDIX_G_TEXT.replace(
        "control.", "control for up to one-\nyear.")
    snapshot, _ = _build_snapshot([(LocatorKind.SECTION, "section:Header", text)])
    index = build_locator_index(snapshot)
    refs = [{
        "source_doc": FILENAME, "section": "Force Majeure",
        "excerpt": "Neither party shall be liable for delay caused by events beyond reasonable "
                   "control for up to one-year.",
    }]
    extract_ids, occurrence_ids = match_refs("e7", refs, index, _fail)
    assert len(extract_ids) == 1 and len(occurrence_ids) == 1


# --- 8. Missing-space-after-punctuation normalization still passes (through the fallback too) ---

def test_missing_space_after_colon_excerpt_still_grounds_via_fallback():
    text = APPENDIX_G_TEXT.replace("Payment shall be made net thirty days", "Payment:shall be made net thirty days")
    snapshot, _ = _build_snapshot([(LocatorKind.SECTION, "section:Header", text)])
    index = build_locator_index(snapshot)
    refs = [{"source_doc": FILENAME, "section": "Payment Terms", "excerpt": "Payment: shall be made net thirty days"}]
    extract_ids, occurrence_ids = match_refs("e8", refs, index, _fail)
    assert len(extract_ids) == 1 and len(occurrence_ids) == 1


# --- 9. Word-order change does not pass ---

def test_word_order_change_does_not_match():
    snapshot, _ = _appendix_g_snapshot()
    index = build_locator_index(snapshot)
    refs = [{
        "source_doc": FILENAME, "section": "Force Majeure",
        # Same words, reordered -- normalize_excerpt_text only strips whitespace, never reorders.
        "excerpt": "shall be liable Neither party for delay caused by events beyond reasonable control.",
    }]
    with pytest.raises(GroundingTestError, match="no Evidence occurrence matches"):
        match_refs("e9", refs, index, _fail)


# --- 10. A genuinely different word (singular/plural) does not pass -- guards against fuzzy matching ---

def test_different_number_word_does_not_match():
    # "eleven" is neither a substring of "ten" nor vice versa, unlike a
    # singular/plural pair -- a genuine word-content difference, not an
    # incidental whitespace artifact, must never be tolerated.
    snapshot, _ = _build_snapshot([(LocatorKind.SECTION, "section:Header",
                                     "The supplier shall respond within ten days.")])
    index = build_locator_index(snapshot)
    refs = [{"source_doc": FILENAME, "section": "Response Time", "excerpt": "respond within eleven days"}]
    with pytest.raises(GroundingTestError, match="no Evidence occurrence matches"):
        match_refs("e10", refs, index, _fail)


# --- 11. XLSX sheet match remains unchanged (no SECTION fallback involved) ---

def test_xlsx_sheet_and_rows_exact_match_is_unaffected_by_the_fallback():
    snapshot, _ = _build_snapshot(
        [(LocatorKind.RECORD, "record:sheet=Mandatory Criteria;rows=1-5",
          "Bidder must hold valid registration.")],
        filename="Mandatory.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    index = build_locator_index(snapshot)
    refs = [{
        "source_doc": "Mandatory.xlsx", "sheet": "Mandatory Criteria", "rows": "1-5",
        "excerpt": "Bidder must hold valid registration.",
    }]
    extract_ids, occurrence_ids = match_refs("e11", refs, index, _fail)
    assert len(extract_ids) == 1 and len(occurrence_ids) == 1


# --- 12. PDF page validation remains unchanged; a wrong page cannot be rescued by excerpt content ---

def test_exact_page_mismatch_is_not_rescued_by_excerpt_present_elsewhere():
    snapshot, _ = _build_snapshot(
        [(LocatorKind.PAGE, "page:1", "The supplier shall respond within ten days.")],
        filename="RFP.pdf", mimetype="application/pdf")
    index = build_locator_index(snapshot)
    # Wrong page, but the excerpt IS verbatim in the real page:1 occurrence.
    # PAGE is bounded/enumerable and already validated upstream -- the
    # SECTION-only fallback must never rescue this.
    refs = [{"source_doc": "RFP.pdf", "page": "99", "excerpt": "The supplier shall respond within ten days."}]
    with pytest.raises(GroundingTestError, match="no Evidence occurrence matches"):
        match_refs("e12", refs, index, _fail)


# --- 12b. Same guardrail for RECORD (sheet+rows) locators ---

def test_exact_record_mismatch_is_not_rescued_by_excerpt_present_elsewhere():
    snapshot, _ = _build_snapshot(
        [(LocatorKind.RECORD, "record:sheet=Mandatory Criteria;rows=1-5",
          "Bidder must hold valid registration.")],
        filename="Mandatory.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    index = build_locator_index(snapshot)
    refs = [{
        "source_doc": "Mandatory.xlsx", "sheet": "Mandatory Criteria", "rows": "6-10",
        "excerpt": "Bidder must hold valid registration.",
    }]
    with pytest.raises(GroundingTestError, match="no Evidence occurrence matches"):
        match_refs("e12b", refs, index, _fail)


# --- 13. Duplicate section names (same normalized exact locator) handled deterministically ---

def test_duplicate_exact_section_names_fail_deterministically_as_ambiguous():
    snapshot, _ = _build_snapshot([
        (LocatorKind.SECTION, "section:Corporate Profile", "The Contractor shall be a registered entity."),
        (LocatorKind.SECTION, "section:Corporate Profile", "The Contractor shall be a registered entity."),
    ])
    index = build_locator_index(snapshot)
    refs = [{"source_doc": FILENAME, "section": "Corporate Profile", "excerpt": "registered entity"}]
    with pytest.raises(GroundingTestError, match="ambiguous"):
        match_refs("e13", refs, index, _fail)
    # Deterministic: repeated evaluation raises the identical failure, not a flaky pick.
    with pytest.raises(GroundingTestError, match="ambiguous"):
        match_refs("e13", refs, index, _fail)


# --- 14. Multiple coarse extracts each independently containing the same excerpt -> ambiguous, no fabricated precision ---

def test_multiple_coarse_extracts_containing_the_same_excerpt_do_not_fabricate_precision():
    snapshot, _ = _build_snapshot([
        (LocatorKind.SECTION, "section:Schedule A", "Common boilerplate: payment terms apply as stated."),
        (LocatorKind.SECTION, "section:Schedule B", "Common boilerplate: payment terms apply as stated."),
    ])
    index = build_locator_index(snapshot)
    refs = [{
        "source_doc": FILENAME, "section": "Payment",  # not a real marker in either schedule
        "excerpt": "Common boilerplate: payment terms apply as stated.",
    }]
    with pytest.raises(GroundingTestError, match="ambiguous"):
        match_refs("e14", refs, index, _fail)


# --- 15. Provenance/grounding result is stable across repeated evaluation ---

def test_grounding_result_is_stable_across_repeated_evaluation():
    snapshot, _ = _appendix_g_snapshot()
    index = build_locator_index(snapshot)
    refs = [{
        "source_doc": FILENAME, "section": "Force Majeure",
        "excerpt": "Neither party shall be liable for delay caused by events beyond reasonable control.",
    }]
    first = match_refs("e15", refs, index, _fail)
    second = match_refs("e15", refs, index, _fail)
    assert first == second


# --- 16. Unrelated substring does not pass: an excerpt claim must be the genuine phrase, not any shared fragment ---

def test_unrelated_excerpt_sharing_only_a_short_substring_does_not_match():
    snapshot, _ = _appendix_g_snapshot()
    index = build_locator_index(snapshot)
    refs = [{
        "source_doc": FILENAME, "section": "Force Majeure",
        # "party" appears in the real text, but this full claimed sentence does not.
        "excerpt": "The party of the second part waives all rights hereunder.",
    }]
    with pytest.raises(GroundingTestError, match="no Evidence occurrence matches"):
        match_refs("e16", refs, index, _fail)


# --- normalize_* unit-level checks ---

def test_normalize_excerpt_text_strips_all_whitespace_and_casefolds():
    assert normalize_excerpt_text("Duration:  3\nyears ") == normalize_excerpt_text("duration: 3years")


def test_normalize_locator_text_preserves_word_boundaries():
    assert normalize_locator_text("Force   Majeure") == "force majeure"
    assert normalize_locator_text("Force") != normalize_locator_text("ForceMajeure")


# --- Cross-adapter consistency: canonical_observation_binding and opportunity_structure_binding
# must agree on the same ref now that both call the identical shared match_refs(). ---

def test_canonical_observation_and_opportunity_structure_bindings_agree_on_the_same_exact_ref():
    snapshot, publication = _appendix_g_snapshot()
    ref = {"source_doc": FILENAME, "section": "Header", "excerpt": "Corporate Profile"}
    canonical = {"observations": [{
        "observation_id": "obs_1", "source_refs": [ref],
        "extraction_occurrences": [{"digest": "occ_1", "count": 1}], "provenance_status": "VERIFIED",
    }]}
    structure = {"records": [{"record_id": "obs_1", "source_refs": [ref], "provenance_status": "VERIFIED"}]}

    observation_bindings = build_observation_bindings(canonical, snapshot, publication)
    structure_bindings = build_structure_bindings(structure, snapshot, publication)

    obs_evidence_ids = tuple(sorted(r.identity_key for r in observation_bindings[0].evidence_references))
    struct_evidence_ids = tuple(sorted(r.identity_key for r in structure_bindings[0].evidence_references))
    obs_provenance_ids = tuple(sorted(r.identity_key for r in observation_bindings[0].provenance_references))
    struct_provenance_ids = tuple(sorted(r.identity_key for r in structure_bindings[0].provenance_references))
    assert obs_evidence_ids == struct_evidence_ids
    assert obs_provenance_ids == struct_provenance_ids


def test_canonical_observation_and_opportunity_structure_bindings_agree_on_the_same_fallback_ref():
    snapshot, publication = _appendix_g_snapshot()
    ref = {
        "source_doc": FILENAME, "section": "Force Majeure",
        "excerpt": "Neither party shall be liable for delay caused by events beyond reasonable control.",
    }
    canonical = {"observations": [{
        "observation_id": "obs_2", "source_refs": [ref],
        "extraction_occurrences": [{"digest": "occ_1", "count": 1}], "provenance_status": "PARTIAL",
    }]}
    structure = {"records": [{"record_id": "obs_2", "source_refs": [ref], "provenance_status": "PARTIAL"}]}

    observation_bindings = build_observation_bindings(canonical, snapshot, publication)
    structure_bindings = build_structure_bindings(structure, snapshot, publication)

    obs_evidence_ids = tuple(sorted(r.identity_key for r in observation_bindings[0].evidence_references))
    struct_evidence_ids = tuple(sorted(r.identity_key for r in structure_bindings[0].evidence_references))
    assert obs_evidence_ids == struct_evidence_ids
    assert len(obs_evidence_ids) == 1
