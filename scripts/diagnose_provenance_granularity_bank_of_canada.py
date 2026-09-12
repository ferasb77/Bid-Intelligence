"""Provenance-granularity remediation diagnostics against the frozen,
authoritative Bank of Canada RFP 2026-026 lineage
(phase1-boc-2026-026-corrected16-20260912T080929Z-9fd9e5).

No Stage A rerun. No LLM calls. Rebuilds only the deterministic Evidence
snapshot (real corpus parse) and the deterministic Canonical Opportunity /
Opportunity Structure ledgers from the already-frozen Stage C facts, exactly
as scripts/commission_executive_opportunity_brief_bank_of_canada.py already
does for the real commissioning run.

Produces, for BANK_OF_CANADA_PROVENANCE_GRANULARITY_REMEDIATION_REPORT.md:

  classification.json        -- Class A/B/C/D counts and examples for every
                                 DOCX source_ref whose locator does not exist
                                 as a real, exact Evidence occurrence.
  appendix_g_forensic.json    -- per real-marker / per-cited-section forensic
                                 table for Appendix G specifically (Section D
                                 of the report).
  provenance_status_counts.json -- VERIFIED/PARTIAL/UNVERIFIED counts, overall
                                 and per document, for both Canonical
                                 Opportunity observations and Opportunity
                                 Structure records.
  binding_outcome_before_after.json -- for every source_ref requiring the
                                 binding layer, whether it would have bound
                                 under the OLD (exact-locator-only, no
                                 coarser fallback) semantics vs the NEW
                                 (evidence_grounding.py Model-2 SECTION
                                 fallback) semantics. The "old" path is
                                 reproduced inline here (not by touching
                                 production code) using the identical
                                 build_locator_index() this diagnostic
                                 imports unmodified from evidence_grounding.py.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PHASE3_RUN_ID = "phase3-boc-2026-026-stagec-refresh-20260912T144353Z-3194c8"
PHASE3_DIR = ROOT / "evaluation/bank_of_canada_briefing_pack/phase3_commissioning" / PHASE3_RUN_ID
CORPUS = ROOT / "evaluation/bank_of_canada_briefing_pack/corrected_procurement_corpus"
MANIFEST = json.loads((ROOT / "evaluation/bank_of_canada_briefing_pack/corrected_corpus_manifest.json").read_text(encoding="utf-8"))
ACQ_FULL = json.loads((ROOT / "evaluation/bank_of_canada_briefing_pack/acquisition_manifest.json").read_text(encoding="utf-8"))
ACQ = {"retrieved_on": ACQ_FULL["retrieved_on"]}
SOURCE = {"source_id": "source:bank-of-canada-procurement", "publisher_name": "Bank of Canada",
          "base_url": "https://www.bankofcanada.ca/"}

OUT = ROOT / "evaluation/bank_of_canada_briefing_pack/provenance_granularity_remediation"
OUT.mkdir(parents=True, exist_ok=True)

from extractor import extract_document_with_metadata
from procurement_evidence_adapter import adapt_procurement_corpus
from evidence import EvidenceArtifact, EvidenceOccurrence, EvidenceExtract
from evidence_grounding import build_locator_index, locator_for_ref, normalize_excerpt_text, normalized_locator
from canonical_opportunity import _coordinates
from opportunity_structure import build_opportunity_structure

paths = sorted(p for p in CORPUS.rglob("*") if p.is_file())
package = [(p.relative_to(CORPUS).as_posix(), p.read_bytes()) for p in paths]
metadata = {"files": [], "doc_metadata": {}, "doc_texts": {}}
for name, payload in package:
    text, meta = extract_document_with_metadata(payload, name)
    metadata["files"].append(name); metadata["doc_metadata"][name] = meta; metadata["doc_texts"][name] = text
evidence_snapshot = adapt_procurement_corpus(package, metadata, MANIFEST, ACQ, SOURCE)

facts = json.loads((PHASE3_DIR / "stage_c_normalized_facts.json").read_text(encoding="utf-8"))
canonical = facts.get("_canonical_opportunity")
structure = build_opportunity_structure(facts, metadata)

DOCX_DOCS = sorted(name for name in metadata["files"] if name.lower().endswith(".docx"))

index = build_locator_index(evidence_snapshot)
artifact_id_by_filename, occurrences_by_locator, occurrences_by_artifact, extracts_by_occurrence = index


def _doc_name_for(source_doc):
    return source_doc


def _all_refs():
    """Yield (entity_kind, entity_id, ref) for every source_ref in both
    Canonical Opportunity observations and Opportunity Structure records."""
    for obs in canonical.get("observations", []):
        for ref in obs.get("source_refs") or []:
            yield "OBSERVATION", obs["observation_id"], ref, obs.get("provenance_status")
    for rec in structure.get("records", []):
        for ref in rec.get("source_refs") or []:
            yield "STRUCTURE_RECORD", rec["record_id"], ref, rec.get("provenance_status")


# --- Classification: Class A (exact match) / B (coarser, uniquely grounded)
# / C (coarser, ambiguously grounded) / D (not grounded anywhere real) ---
# Restricted to DOCX refs, since that is the confirmed, real shape of the
# defect (see module docstring and BANK_OF_CANADA_PROVENANCE_GRANULARITY_
# REMEDIATION_REPORT.md Section B).

classification = {"A": [], "B": [], "C": [], "D": []}
seen_ref_keys = set()

for entity_kind, entity_id, ref, provenance_status in _all_refs():
    source_doc = ref.get("source_doc")
    if source_doc not in DOCX_DOCS:
        continue
    excerpt = ref.get("excerpt")
    has_excerpt = isinstance(excerpt, str) and bool(excerpt.strip())
    dedup_key = (entity_kind, entity_id, source_doc, ref.get("section"), excerpt)
    if dedup_key in seen_ref_keys:
        continue
    seen_ref_keys.add(dedup_key)

    artifact_id = artifact_id_by_filename.get(source_doc)
    if artifact_id is None:
        continue

    locator = locator_for_ref(ref)
    exact_candidates = []
    if locator is not None:
        exact_candidates = occurrences_by_locator.get((artifact_id, locator[0], locator[1]), [])

    record = {
        "entity_kind": entity_kind, "entity_id": entity_id, "source_doc": source_doc,
        "requested_section": ref.get("section"), "excerpt_snippet": (excerpt or "")[:120],
        "upstream_provenance_status": provenance_status,
    }

    if exact_candidates:
        record["real_locator"] = f"{locator[0]}:{locator[1]}"
        classification["A"].append(record)
        continue

    if not has_excerpt:
        # No excerpt at all and no exact locator match -- not part of the
        # excerpt-grounded coarser-fallback population; leave unclassified
        # (handled directly by the strict exact-locator failure path).
        continue

    normalized_excerpt = normalize_excerpt_text(excerpt)
    owners = [
        occ for occ in occurrences_by_artifact.get(artifact_id, [])
        if any(isinstance(extract.content, str)
               and normalized_excerpt in normalize_excerpt_text(extract.content)
               for extract in extracts_by_occurrence.get(occ.object_id, []))
    ]
    if len(owners) == 1:
        record["coarser_real_occurrence"] = f"{owners[0].locator_kind.value}:{owners[0].locator}"
        classification["B"].append(record)
    elif len(owners) > 1:
        record["coarser_real_occurrences"] = [f"{o.locator_kind.value}:{o.locator}" for o in owners]
        classification["C"].append(record)
    else:
        classification["D"].append(record)

classification_summary = {kind: len(items) for kind, items in classification.items()}
(OUT / "classification.json").write_text(
    json.dumps({"summary": classification_summary, "records": classification},
               ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
print("CLASSIFICATION", json.dumps(classification_summary, sort_keys=True))


# --- Appendix G forensic table (Section D) ---

APPENDIX_G = next((n for n in DOCX_DOCS if "appendix g" in n.lower()), None)
appendix_g_forensic = {"document": APPENDIX_G, "real_markers": [], "cited_sections": []}
if APPENDIX_G:
    artifact_id = artifact_id_by_filename[APPENDIX_G]
    for occ in occurrences_by_artifact.get(artifact_id, []):
        extracts = extracts_by_occurrence.get(occ.object_id, [])
        appendix_g_forensic["real_markers"].append({
            "locator_kind": occ.locator_kind.value, "locator": occ.locator,
            "extract_chars": sum(len(e.content) for e in extracts if isinstance(e.content, str)),
        })
    cited = {}
    for entity_kind, entity_id, ref, provenance_status in _all_refs():
        if ref.get("source_doc") != APPENDIX_G:
            continue
        section = ref.get("section")
        excerpt = ref.get("excerpt")
        key = (section, excerpt)
        if key in cited:
            continue
        cited[key] = True
        locator = locator_for_ref(ref)
        exact = bool(locator and occurrences_by_locator.get((artifact_id, locator[0], locator[1])))
        has_excerpt = isinstance(excerpt, str) and bool(excerpt.strip())
        grounded_owner = None
        if has_excerpt and not exact:
            normalized_excerpt = normalize_excerpt_text(excerpt)
            owners = [
                occ for occ in occurrences_by_artifact.get(artifact_id, [])
                if any(isinstance(extract.content, str)
                       and normalized_excerpt in normalize_excerpt_text(extract.content)
                       for extract in extracts_by_occurrence.get(occ.object_id, []))
            ]
            if len(owners) == 1:
                grounded_owner = f"{owners[0].locator_kind.value}:{owners[0].locator}"
        appendix_g_forensic["cited_sections"].append({
            "entity_kind": entity_kind, "entity_id": entity_id,
            "requested_section": section, "excerpt_snippet": (excerpt or "")[:120],
            "exact_locator_exists": exact,
            "text_grounded_via_coarser_occurrence": grounded_owner,
            "upstream_provenance_status": provenance_status,
            "correct_status": (
                "VERIFIED-BY-COARSER-GROUNDING (Class B)" if grounded_owner
                else "EXACT (Class A)" if exact
                else "UNGROUNDED (Class D) -- must not bind"
            ),
        })
(OUT / "appendix_g_forensic.json").write_text(
    json.dumps(appendix_g_forensic, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
print("APPENDIX_G_MARKERS", len(appendix_g_forensic["real_markers"]),
      "CITED_SECTIONS", len(appendix_g_forensic["cited_sections"]))


# --- Provenance status counts: overall + per document + per source type ---
# (Unchanged by this remediation -- canonical_opportunity.py's own
# _validate_ref/_locator_matches, which sets provenance_status, was not
# modified. Recorded here to make that explicit and auditable, and to
# confirm no bulk re-verification occurred as a side effect of the binding
# layer fix.)

def _ext(name):
    return name.rsplit(".", 1)[-1].lower()


def _status_counts(items, id_field, doc_field_getter):
    overall = {"VERIFIED": 0, "PARTIAL": 0, "UNVERIFIED": 0}
    per_doc = {}
    per_type = {"pdf": {"VERIFIED": 0, "PARTIAL": 0, "UNVERIFIED": 0},
                "docx": {"VERIFIED": 0, "PARTIAL": 0, "UNVERIFIED": 0},
                "xlsx": {"VERIFIED": 0, "PARTIAL": 0, "UNVERIFIED": 0},
                "other": {"VERIFIED": 0, "PARTIAL": 0, "UNVERIFIED": 0}}
    for item in items:
        status = item.get("provenance_status")
        if status not in overall:
            continue
        overall[status] += 1
        doc = doc_field_getter(item)
        per_doc.setdefault(doc or "(none)", {"VERIFIED": 0, "PARTIAL": 0, "UNVERIFIED": 0})[status] += 1
        ext = _ext(doc) if doc else "other"
        per_type.get(ext, per_type["other"])[status] += 1
    return {"overall": overall, "per_document": per_doc, "per_source_type": per_type}


def _obs_doc(obs):
    refs = obs.get("source_refs") or []
    return refs[0].get("source_doc") if refs else obs.get("source_doc")


def _rec_doc(rec):
    refs = rec.get("source_refs") or []
    return refs[0].get("source_doc") if refs else None


provenance_status_counts = {
    "canonical_opportunity_observations": _status_counts(
        canonical.get("observations", []), "observation_id", _obs_doc),
    "opportunity_structure_records": _status_counts(
        structure.get("records", []), "record_id", _rec_doc),
}
(OUT / "provenance_status_counts.json").write_text(
    json.dumps(provenance_status_counts, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
print("PROVENANCE_STATUS_COUNTS", json.dumps(
    {k: v["overall"] for k, v in provenance_status_counts.items()}, sort_keys=True))


# --- Binding outcome before/after: OLD (exact-locator-only) vs NEW
# (evidence_grounding.py Model-2 SECTION fallback), per document ---

def _old_binds(ref):
    """Reproduce the pre-remediation binding algorithm exactly: an exact
    locator dictionary match only, never a coarser fallback. Does not import
    or alter production code -- this is a read-only simulation for the
    report."""
    source_doc = ref.get("source_doc")
    artifact_id = artifact_id_by_filename.get(source_doc)
    if artifact_id is None:
        return False
    locator = locator_for_ref(ref)
    if locator is None:
        return False
    return len(occurrences_by_locator.get((artifact_id, locator[0], locator[1]), [])) == 1


def _new_binds(ref):
    from evidence_grounding import match_refs

    def _swallow(_entity_id, _reason):
        raise ValueError(_reason)

    try:
        match_refs("diag", [ref], index, _swallow)
        return True
    except ValueError:
        return False


before_after = {"overall": {"old_bound": 0, "new_bound": 0, "refs": 0}, "per_document": {}}
for entity_kind, entity_id, ref, provenance_status in _all_refs():
    source_doc = ref.get("source_doc")
    if source_doc not in DOCX_DOCS:
        continue
    old = _old_binds(ref)
    new = _new_binds(ref)
    before_after["overall"]["refs"] += 1
    before_after["overall"]["old_bound"] += int(old)
    before_after["overall"]["new_bound"] += int(new)
    doc_bucket = before_after["per_document"].setdefault(
        source_doc, {"old_bound": 0, "new_bound": 0, "refs": 0})
    doc_bucket["refs"] += 1
    doc_bucket["old_bound"] += int(old)
    doc_bucket["new_bound"] += int(new)

(OUT / "binding_outcome_before_after.json").write_text(
    json.dumps(before_after, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
print("BINDING_BEFORE_AFTER", json.dumps(before_after["overall"], sort_keys=True))

print("OUT_DIR", str(OUT))
