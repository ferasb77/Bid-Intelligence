"""Deterministic Opportunity Structure ledger.

Opportunity Structure is the constitutional owner of the normalized
procurement *structure* a solicitation establishes: Requirement, Evaluation
Criterion, Commercial Clause, Deliverable, and Submission Rule. It owns
exactly the already-normalized, already-deduplicated, already-conflict-
checked content Stage B/C place under the ``requirements``,
``evaluation_criteria``, ``commercial_clauses``, ``deliverables``, and
``submission_rules`` keys of a package's normalized facts -- never the raw
``typed_observations`` families that ``canonical_opportunity.py`` already
owns, and never any interpretation, confidence, Unknown, or Human Decision
about what the structure means (Opportunity Intelligence's exclusive
domain, unchanged by this module).

This ledger performs no reconciliation Stage B/C has not already performed.
Its only original work is: (1) assigning each record the exact stable
identity ``opportunity_intelligence.py``'s own ``_record_id`` already
derives for it -- so a future Opportunity Structure Publication can satisfy
Opportunity Intelligence's existing, unmodified evidence-support contract
without inventing a new identifier scheme; (2) independently validating
each record's own ``source_refs`` against the real corpus, exactly as
``canonical_opportunity.py`` already validates ``typed_observations``
source_refs, rather than trusting any upstream "verified" flag; and (3)
surfacing -- never silently resolving -- any case where that reused
identity scheme is not actually collision-free against real production
data (Stage A assigns some identifiers, such as ``req_id``, per source
document rather than per package, so the same identifier can legitimately
name two unrelated requirements drawn from two different documents).  A
genuine collision is recorded exactly as ``canonical_opportunity.py``
already records one -- never merged, never guessed away -- and blocks
publication through the identical ``collision_free`` integrity gate.
"""
from __future__ import annotations

from typing import Mapping

from canonical_opportunity import _id, _validate_ref, canonical_json
from opportunity_intelligence import _record_id

SCHEMA_VERSION = "opportunity-structure/1"

FAMILIES = {"REQUIREMENT", "EVALUATION_CRITERION", "COMMERCIAL_CLAUSE", "DELIVERABLE", "SUBMISSION_RULE"}

SECTION_BY_FAMILY = {
    "REQUIREMENT": "requirements",
    "EVALUATION_CRITERION": "evaluation_criteria",
    "COMMERCIAL_CLAUSE": "commercial_clauses",
    "DELIVERABLE": "deliverables",
    "SUBMISSION_RULE": "submission_rules",
}

# Stage B/C already detect per-field cross-occurrence disagreement for these
# families using a "<field>_conflict" boolean paired with a
# "<field>_observations" list of the distinct raw values seen. Opportunity
# Structure surfaces that already-computed signal as a governed conflict; it
# does not invent new conflict detection.
CONFLICT_FIELDS_BY_FAMILY = {
    "EVALUATION_CRITERION": ("role", "weight"),
    "SUBMISSION_RULE": ("artifact_type", "file_format", "mandatory", "submission_channel"),
}

_NON_SEMANTIC_RECORD_KEYS = ("source_refs", "occurrences")


def _record_fields(raw: Mapping) -> dict:
    return {key: value for key, value in raw.items() if key not in _NON_SEMANTIC_RECORD_KEYS}


def _provenance_status(statuses: list) -> str:
    if statuses and all(status == "VERIFIED" for status in statuses):
        return "VERIFIED"
    if any(status in {"VERIFIED", "PARTIAL"} for status in statuses):
        return "PARTIAL"
    return "UNVERIFIED"


def build_opportunity_structure(stage_facts: Mapping, package_metadata: Mapping) -> dict:
    """Build a complete, order-independent structure ledger from real Stage B/C output.

    stage_facts: the real normalized_facts mapping produced by
        ``extractor.normalize_package_facts`` / ``reconcile_package_facts``
        (the same mapping ``opportunity_intelligence.analyze_opportunity``
        consumes), containing the five section keys above.
    package_metadata: the same ``{"files": [...], "doc_texts": {...}}``
        mapping ``canonical_opportunity.build_canonical_opportunity`` uses,
        for the identical corpus, so source_refs validate against the
        identical real document text.
    """
    docs = []
    for name in sorted(package_metadata.get("files", []), key=str.casefold):
        docs.append({"source_document_id": _id("doc_", {"version": SCHEMA_VERSION, "name": name.casefold()}), "source_doc": name})

    logical: dict[tuple, dict] = {}
    assigned_ids: dict[str, set] = {}
    collisions = []
    invalid = []

    for family in sorted(FAMILIES):
        section = SECTION_BY_FAMILY[family]
        raw_list = stage_facts.get(section)
        if raw_list is None:
            raw_list = []
        if not isinstance(raw_list, list):
            invalid.append({"section": section, "reason": "SECTION_NOT_A_LIST"})
            continue
        for index, raw in enumerate(raw_list):
            if not isinstance(raw, Mapping):
                invalid.append({"section": section, "index": index, "reason": "RECORD_NOT_A_MAPPING"})
                continue
            fields = _record_fields(raw)
            refs, statuses = [], []
            for ref in raw.get("source_refs") or []:
                if not isinstance(ref, Mapping):
                    continue
                clean, status = _validate_ref(ref, package_metadata)
                refs.append(clean)
                statuses.append(status)
            # Duplicate detection groups on the record's own semantic
            # content (mirroring canonical_opportunity.py's identity_material
            # comparison), never on _record_id's output -- a section such as
            # "requirements" falls through to _record_id's content-and-
            # position hash, which is deliberately position-salted to avoid
            # trusting a document-local label as identity, and would
            # otherwise prevent two genuinely identical extractions (e.g. a
            # Stage A chunk-boundary re-extraction) from ever being
            # recognized as the same record.
            content_key = (family, canonical_json(fields))
            existing = logical.get(content_key)
            if existing is not None:
                seen = {canonical_json(r) for r in existing["source_refs"]}
                for ref, status in zip(refs, statuses):
                    digest = canonical_json(ref)
                    if digest not in seen:
                        existing["source_refs"].append(ref)
                        existing["_statuses"].append(status)
                        seen.add(digest)
                existing["occurrence_count"] += 1
                continue
            record_id = _record_id(section, raw, index)
            if record_id in assigned_ids.get(family, ()):
                collisions.append({"family": family, "record_id": record_id})
                continue
            assigned_ids.setdefault(family, set()).add(record_id)
            logical[content_key] = {
                "record_id": record_id, "family": family, "section": section,
                "fields": fields, "source_refs": refs,
                "_statuses": statuses, "occurrence_count": 1,
            }

    records = []
    for entry in logical.values():
        entry["provenance_status"] = _provenance_status(entry.pop("_statuses"))
        entry["conflict_ids"] = []
        records.append(entry)
    records.sort(key=lambda item: (item["family"], item["record_id"]))

    conflicts = []
    for record in records:
        for field in CONFLICT_FIELDS_BY_FAMILY.get(record["family"], ()):
            if record["fields"].get(f"{field}_conflict") is not True:
                continue
            values = record["fields"].get(f"{field}_observations") or []
            conflict_id = _id("struct_conf_", {
                "version": SCHEMA_VERSION, "family": record["family"],
                "record_id": record["record_id"], "field": field, "values": values,
            })
            conflicts.append({
                "conflict_id": conflict_id, "state": "ACTIVE", "family": record["family"],
                "field": field, "affected_record_ids": [record["record_id"]],
                "incompatible_values": values,
            })
            record["conflict_ids"].append(conflict_id)

    for record in records:
        record["conflict_ids"].sort()

    collision_ids = sorted({canonical_json(item) for item in collisions})
    coverage = {family: {"records_present": any(r["family"] == family for r in records)} for family in sorted(FAMILIES)}

    structure = {
        "schema_version": SCHEMA_VERSION,
        "documents": docs,
        "records": records,
        "conflicts": sorted(conflicts, key=lambda item: item["conflict_id"]),
        "coverage": coverage,
        "integrity_diagnostics": {
            "collision_ids": collision_ids,
            "collision_free": not collision_ids,
            "invalid_records": sorted(invalid, key=canonical_json),
            "record_count": len(records),
            "conflict_count": len(conflicts),
        },
    }
    structure["input_digest"] = _id("input_", {"documents": docs, "records": records})
    return structure


__all__ = ["CONFLICT_FIELDS_BY_FAMILY", "FAMILIES", "SCHEMA_VERSION", "SECTION_BY_FAMILY", "build_opportunity_structure"]
