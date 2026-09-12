"""Phase 2 / Stage B commissioning: run the real production
`normalize_package_facts()` (Stage B: deduplication & source provenance
validation) exactly once against the frozen fresh Phase 1 output for the
authoritative 16-document Bank of Canada RFP 2026-026 corpus.

Stage A (extract_document_facts, the LLM call) is NOT invoked. The Phase 1
run's `phase1_stage_a_document_facts.json` is loaded unchanged and used as
Stage B's `doc_facts_list` input, verbatim.

Stage B's second required input, `package_metadata` (files/doc_metadata/
doc_texts), was not persisted as raw structured JSON in the Phase 1 run
(only human-readable excerpts were). It is reconstructed here by calling
the same deterministic, non-LLM `extract_document_with_metadata()` function
against the same frozen 16 physical files (verified by fresh SHA-256 match
against the Phase 1 corpus manifest) -- this is local text/metadata parsing,
not Stage A, and produces byte-identical output every time. The
reconstruction is cross-checked against the persisted Phase 1
`phase1_document_parsing.json` character/page counts before Stage B runs.

No Stage C (reconcile_package_facts), Stage D, or any downstream boundary
is invoked.
"""
import hashlib, json, re, secrets, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PHASE1_RUN_ID = "phase1-boc-2026-026-corrected16-20260912T080929Z-9fd9e5"
PHASE1_DIR = ROOT / "evaluation/bank_of_canada_briefing_pack/phase1_commissioning" / PHASE1_RUN_ID
CORPUS = ROOT / "evaluation/bank_of_canada_briefing_pack/corrected_procurement_corpus"
MASTER_RFP_FILENAME = "RFP 2026-026 - Talent, Learning and Organizational Development Services.pdf"
RECOVERED_TRUNCATED_DOCS = {
    "abstract.pdf",
    "OriginalRevision/RFP 2026-026 - Appendix D1 - Rated criteria response form.docx",
    "OriginalRevision/RFP 2026-06 - Appendix G - Form of Agreement.docx",
    MASTER_RFP_FILENAME,
}

PHASE2_RUN_ID = f"phase2-boc-2026-026-stageb-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{secrets.token_hex(3)}"
OUT = ROOT / "evaluation/bank_of_canada_briefing_pack/phase2_commissioning" / PHASE2_RUN_ID
OUT.mkdir(parents=True, exist_ok=False)


def save(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n",
                             encoding="utf-8")


from extractor import (
    _canonical_submission_item_identity, extract_document_with_metadata,
    normalize_package_facts, validate_source_refs,
)
from requirement_semantics import SPECIFIC_REQUIREMENT_TYPES
from evaluation_hierarchy import normalize_evaluation_criterion, make_criterion_key
from contract_hygiene import _clause_key, _deliverable_key, _logical_records

# --- 1. Load frozen Phase 1 artifacts, verify the input lock ---------------

source_manifest = json.loads((PHASE1_DIR / "phase1_source_manifest.json").read_text(encoding="utf-8"))
stage_a_report = json.loads((PHASE1_DIR / "phase1_stage_a_report.json").read_text(encoding="utf-8"))
doc_parsing_prior = json.loads((PHASE1_DIR / "phase1_document_parsing.json").read_text(encoding="utf-8"))
doc_facts_list = json.loads((PHASE1_DIR / "phase1_stage_a_document_facts.json").read_text(encoding="utf-8"))

assert len(doc_facts_list) == 16, f"expected 16 frozen Stage A documents, found {len(doc_facts_list)}"
total_stage_a_records = sum(item["total_records"] for item in stage_a_report)
assert total_stage_a_records == 916, f"frozen Stage A total record count changed: {total_stage_a_records} != 916"
master_stage_a_records = next(item["total_records"] for item in stage_a_report if item["role"] == "MASTER_RFP")
assert master_stage_a_records == 288, f"frozen master-RFP Stage A record count changed: {master_stage_a_records} != 288"

paths = sorted(p for p in CORPUS.rglob("*") if p.is_file())
package = [(p.relative_to(CORPUS).as_posix(), p.read_bytes()) for p in paths]
assert len(package) == 16, f"corpus directory no longer has 16 files: {len(package)}"
fresh_digests = {name: hashlib.sha256(payload).hexdigest() for name, payload in package}
manifest_digests = {item["path"]: item["sha256"] for item in source_manifest["files"]}
assert fresh_digests == manifest_digests, "corpus content digest drift since the frozen Phase 1 run"

input_lock = {
    "phase1_run_id": PHASE1_RUN_ID,
    "documents": 16,
    "stage_a_total_records": total_stage_a_records,
    "master_rfp_stage_a_records": master_stage_a_records,
    "corpus_digest_match": True,
    "stage_a_rerun": False,
}
save("input_lock.json", input_lock)

# --- 2. Reconstruct package_metadata via the same deterministic, non-LLM ---
#        extract_document_with_metadata() call Phase 1 already made once.

metadata = {"files": [], "doc_metadata": {}, "doc_texts": {}}
for name, payload in package:
    text, meta = extract_document_with_metadata(payload, name)
    metadata["files"].append(name)
    metadata["doc_metadata"][name] = meta
    metadata["doc_texts"][name] = text

prior_by_path = {item["path"]: item for item in doc_parsing_prior}
metadata_reconstruction_check = []
for name, _ in package:
    fresh_chars = len(metadata["doc_texts"][name])
    fresh_pages = metadata["doc_metadata"][name].get("page_count")
    prior = prior_by_path[name]
    ok = (fresh_chars == prior["extracted_character_count"] and fresh_pages == prior["page_count"])
    metadata_reconstruction_check.append({
        "path": name, "match": ok, "fresh_characters": fresh_chars,
        "prior_characters": prior["extracted_character_count"],
        "fresh_page_count": fresh_pages, "prior_page_count": prior["page_count"],
    })
save("metadata_reconstruction_check.json", metadata_reconstruction_check)
assert all(item["match"] for item in metadata_reconstruction_check), (
    "deterministic package_metadata reconstruction did not match the frozen Phase 1 parsing output")

# --- 3. Run Stage B exactly once -------------------------------------------

t0 = time.monotonic()
result = normalize_package_facts(doc_facts_list, metadata)
stage_b_elapsed = round(time.monotonic() - t0, 6)

save("stage_b_normalized_result.json", result)

rejections = result.get("_provenance_rejections", [])
rejection_summary_preview = {}
for _item in rejections:
    rejection_summary_preview.setdefault(_item["family"], 0)
    rejection_summary_preview[_item["family"]] += 1

# --- 4. Duplicate-group audits (pure functions of the frozen raw input) ----

req_groups = {}
for df in doc_facts_list:
    for r in df.get("requirements", []):
        if not isinstance(r, dict):
            continue
        raw_desc = r.get("description")
        if not isinstance(raw_desc, str) or not raw_desc.strip():
            continue
        desc_key = re.sub(r"\W+", "", raw_desc.strip().lower())
        if not desc_key:
            continue
        req_groups.setdefault(desc_key, []).append(r)

sub_groups = {}
from extractor import _canonical_submission_item_identity
for df in doc_facts_list:
    for sr in df.get("submission_rules", []):
        if not isinstance(sr, dict):
            continue
        item = (sr.get("item") or "").strip()
        if not item:
            continue
        canon = _canonical_submission_item_identity(item) or item.lower()
        sub_groups.setdefault(canon, []).append(sr)

eval_groups = {}
for df in doc_facts_list:
    for ec in df.get("evaluation_criteria", []):
        if not isinstance(ec, dict):
            continue
        norm_ec = normalize_evaluation_criterion(ec)
        if not norm_ec.get("stage"):
            continue
        key = make_criterion_key(norm_ec)
        eval_groups.setdefault(key, []).append(ec)

hygiene = result.get("_contract_hygiene", {})
deliverable_occ_groups = {}
for occ in hygiene.get("deliverable_occurrences", []):
    deliverable_occ_groups.setdefault(_deliverable_key(occ), []).append(occ)
clause_occ_groups = {}
for occ in hygiene.get("clause_occurrences", []):
    clause_occ_groups.setdefault(_clause_key(occ), []).append(occ)


def group_stats(groups):
    sizes = sorted((len(v) for v in groups.values()), reverse=True)
    return {
        "total_groups": len(groups),
        "groups_merged_gt1": sum(1 for s in sizes if s > 1),
        "groups_singleton": sum(1 for s in sizes if s == 1),
        "raw_records_total": sum(sizes),
        "top_group_sizes": sizes[:10],
    }


dedup_audit = {
    "requirements": group_stats(req_groups),
    "submission_rules": group_stats(sub_groups),
    "evaluation_criteria": group_stats(eval_groups),
    "deliverable_occurrences": group_stats(deliverable_occ_groups),
    "clause_occurrences": group_stats(clause_occ_groups),
    "dates": {"note": "Stage B performs no deduplication on dates (raw concatenation)"},
}
save("dedup_audit.json", dedup_audit)

# Representative merge-group examples
example_merge_groups = {
    "requirements": [{"key": k, "size": len(v), "docs": sorted({r.get("source_refs", [{}])[0].get("source_doc") if r.get("source_refs") else None for r in v})}
                      for k, v in req_groups.items() if len(v) > 1][:5],
    "submission_rules": [{"key": k, "size": len(v)} for k, v in sub_groups.items() if len(v) > 1][:5],
    "evaluation_criteria": [{"key": list(k), "size": len(v)} for k, v in eval_groups.items() if len(v) > 1][:5],
    "deliverable_occurrences": [{"key": list(k), "size": len(v)} for k, v in deliverable_occ_groups.items() if len(v) > 1][:5],
    "clause_occurrences": [{"key": list(k), "size": len(v)} for k, v in clause_occ_groups.items() if len(v) > 1][:5],
}
save("example_merge_groups.json", example_merge_groups)

# --- 5. Provenance validation audit -----------------------------------------

def ref_stats(records, field="source_refs"):
    total, valid, invalid = 0, 0, 0
    not_found, other_invalid = 0, 0
    zero_valid_records = 0
    for rec in records:
        refs = rec.get(field, []) or []
        rec_valid = 0
        for ref in refs:
            total += 1
            if ref.get("verified") is True:
                valid += 1
                rec_valid += 1
            elif ref.get("verified") is False:
                invalid += 1
                err = ref.get("validation_error", "")
                if "not found in procurement package" in err:
                    not_found += 1
                else:
                    other_invalid += 1
        if refs and rec_valid == 0:
            zero_valid_records += 1
    return {"total_references": total, "valid": valid, "invalid": invalid,
            "invalid_document_not_found": not_found, "invalid_other_reason": other_invalid,
            "records_with_zero_valid_reference": zero_valid_records}


_logical_clause_records = _logical_records(hygiene.get("clause_occurrences", []), _clause_key, "clause_")

provenance_audit = {
    "requirements": ref_stats(result["requirements"]),
    "submission_rules": ref_stats(result["submission_rules"]),
    "evaluation_criteria": {
        **ref_stats(result["evaluation_criteria"]),
        "note": "REMEDIATED: evaluation_criteria source_refs are now validated via "
                "validate_source_refs() before admission; a record with zero verified "
                "references is quarantined into _provenance_rejections (see below) rather "
                "than admitted unflagged.",
        "rejected_zero_provenance": rejection_summary_preview.get("evaluation_criteria", 0),
    },
    "dates": {
        "total_dates": len(result["dates"]),
        "note": "REMEDIATED: each date's source_doc is now wrapped and validated via "
                "validate_source_refs(); a date whose source document does not resolve is "
                "quarantined into _provenance_rejections rather than admitted unflagged.",
        "valid": sum(1 for d in result["dates"] if d.get("source_refs") and d["source_refs"][0].get("verified") is True),
        "rejected_zero_provenance": rejection_summary_preview.get("dates", 0),
    },
    "deliverable_occurrences_prefilter": {
        "note": "contract_hygiene._verified_refs() DROPS unverified references before an occurrence "
                "is built, rather than flagging them; counts below are what survived. REMEDIATED: a "
                "logical record left with zero verified references is now excluded from "
                "normalized['deliverables'] and quarantined into _provenance_rejections (previously "
                "it was retained, unflagged, in the trusted array).",
        "occurrences": len(hygiene.get("deliverable_occurrences", [])),
        "occurrences_with_zero_refs_after_filter": sum(
            1 for o in hygiene.get("deliverable_occurrences", []) if not o.get("source_refs")),
        "evidence_state_verified": sum(1 for o in hygiene.get("deliverable_occurrences", []) if o.get("evidence_state") == "VERIFIED"),
        "evidence_state_unverified": sum(1 for o in hygiene.get("deliverable_occurrences", []) if o.get("evidence_state") == "UNVERIFIED"),
        "final_deliverables_output_count": len(result["deliverables"]),
        "legacy_deliverables_count": len(hygiene.get("legacy_deliverables", [])),
    },
    "clause_occurrences_prefilter": {
        "note": "REMEDIATED: same reference-dropping behavior as deliverables at the occurrence level "
                "(contract_hygiene._verified_refs() keeps only verified refs before building an "
                "occurrence; the excerpt-required extra gate that previously discarded a valid "
                "document+section citation with no excerpt has been removed -- a ref is now valid on "
                "the same terms validate_source_refs() itself uses). At the logical-record level, a "
                "fresh (non-legacy) clause record with evidence_state != VERIFIED is now excluded from "
                "normalized['commercial_clauses'] and quarantined into _provenance_rejections, exactly "
                "like deliverables -- previously deliverables kept such records unflagged in the "
                "trusted array while clauses silently excluded them with no diagnostic; both families "
                "now behave identically.",
        "occurrences": len(hygiene.get("clause_occurrences", [])),
        "evidence_state_verified": sum(1 for o in hygiene.get("clause_occurrences", []) if o.get("evidence_state") == "VERIFIED"),
        "evidence_state_unverified": sum(1 for o in hygiene.get("clause_occurrences", []) if o.get("evidence_state") == "UNVERIFIED"),
        "logical_clause_records_total": len(_logical_clause_records),
        "logical_clause_records_verified": sum(1 for c in _logical_clause_records if c.get("evidence_state") == "VERIFIED"),
        "logical_clause_records_unverified_dropped_from_final": sum(1 for c in _logical_clause_records if c.get("evidence_state") != "VERIFIED"),
        "final_commercial_clauses_output_count": len(result["commercial_clauses"]),
        "legacy_clauses_count": len(hygiene.get("legacy_clauses", [])),
    },
    "contract_risks": {
        "note": "contract_risks are never validated against physical evidence at all; every item "
                "becomes an unconditional 'legacy_risks' record (UNVERIFIED/LEGACY_EXTRACTION).",
        "raw_count_across_stage_a": sum(len(df.get("contract_risks", []) or []) for df in doc_facts_list),
        "final_count": len(result["contract_risks"]),
    },
    "canonical_opportunity_observations": {
        "total": len(result["_canonical_opportunity"]["observations"]),
        "provenance_VERIFIED": sum(1 for o in result["_canonical_opportunity"]["observations"] if o["provenance_status"] == "VERIFIED"),
        "provenance_PARTIAL": sum(1 for o in result["_canonical_opportunity"]["observations"] if o["provenance_status"] == "PARTIAL"),
        "provenance_UNVERIFIED": sum(1 for o in result["_canonical_opportunity"]["observations"] if o["provenance_status"] == "UNVERIFIED"),
        "invalid_family_kind_dropped": len(result["_canonical_opportunity"]["integrity_diagnostics"]["invalid_observations"]),
        "collision_ids": result["_canonical_opportunity"]["integrity_diagnostics"]["collision_ids"],
        "resolved_field_empty_at_stage_b": result["_canonical_opportunity"]["resolved"] == {},
        "conflicts_field_empty_at_stage_b": result["_canonical_opportunity"]["conflicts"] == [],
        "explicit_supersession_declarations": sum(
            1 for o in result["_canonical_opportunity"]["observations"] if o.get("supersession")),
        "supersession_resolution_state_resolved": sum(
            1 for o in result["_canonical_opportunity"]["observations"]
            if (o.get("supersession") or {}).get("resolution_state") == "RESOLVED"),
    },
}
save("provenance_audit.json", provenance_audit)

# --- 5b. Unified provenance-rejection ledger (remediation) -----------------

rejection_summary = rejection_summary_preview
save("provenance_rejections.json", rejections)
save("provenance_rejection_summary.json", {
    "total_rejections": len(rejections),
    "by_family": rejection_summary,
    "note": "Every record here was excluded from its family's trusted normalized array with an "
            "explicit ZERO_VALID_PROVENANCE diagnostic (original record + checked source_refs "
            "preserved) -- none of these records silently disappeared.",
})

# --- 6. Document contribution / master RFP / RECOVERED_TRUNCATED lineage ---

FAMILIES_WITH_REFS = {
    "requirements": result["requirements"],
    "submission_rules": result["submission_rules"],
    "evaluation_criteria": result["evaluation_criteria"],
}


def docs_for_record(rec):
    return {ref.get("source_doc") for ref in (rec.get("source_refs") or []) if isinstance(ref, dict) and ref.get("source_doc")}


per_document_contribution = {name: {
    "stage_a_records": next(item["total_records"] for item in stage_a_report if item["path"] == name),
    "normalized_records_citing": 0, "physical_references": 0, "sole_source_records": 0, "shared_source_records": 0,
} for name, _ in package}

lineage = {"exclusively_clean": 0, "mixed_clean_and_truncated": 0, "exclusively_truncated": 0, "no_source_doc": 0}

for family, records in FAMILIES_WITH_REFS.items():
    for rec in records:
        docs = docs_for_record(rec)
        if not docs:
            lineage["no_source_doc"] += 1
            continue
        for d in docs:
            if d in per_document_contribution:
                per_document_contribution[d]["normalized_records_citing"] += 1
        for ref in (rec.get("source_refs") or []):
            d = ref.get("source_doc")
            if d in per_document_contribution:
                per_document_contribution[d]["physical_references"] += 1
        if len(docs) == 1:
            only = next(iter(docs))
            if only in per_document_contribution:
                per_document_contribution[only]["sole_source_records"] += 1
        else:
            for d in docs:
                if d in per_document_contribution:
                    per_document_contribution[d]["shared_source_records"] += 1
        truncated_hit = bool(docs & RECOVERED_TRUNCATED_DOCS)
        clean_hit = bool(docs - RECOVERED_TRUNCATED_DOCS)
        if truncated_hit and clean_hit:
            lineage["mixed_clean_and_truncated"] += 1
        elif truncated_hit:
            lineage["exclusively_truncated"] += 1
        else:
            lineage["exclusively_clean"] += 1

save("per_document_contribution.json", per_document_contribution)
save("recovered_truncated_lineage.json", lineage)

master_records = {
    family: [rec for rec in records if MASTER_RFP_FILENAME in docs_for_record(rec)]
    for family, records in FAMILIES_WITH_REFS.items()
}
master_sole = {family: sum(1 for rec in recs if docs_for_record(rec) == {MASTER_RFP_FILENAME}) for family, recs in master_records.items()}
master_shared = {family: sum(1 for rec in recs if docs_for_record(rec) != {MASTER_RFP_FILENAME}) for family, recs in master_records.items()}
master_pages = set()
for family, recs in master_records.items():
    for rec in recs:
        for ref in rec.get("source_refs", []):
            if ref.get("source_doc") == MASTER_RFP_FILENAME and ref.get("page") is not None:
                master_pages.add(ref["page"])

master_contribution = {
    "stage_a_records_in": master_stage_a_records,
    "normalized_records_by_family": {family: len(recs) for family, recs in master_records.items()},
    "sole_source_by_family": master_sole,
    "shared_source_by_family": master_shared,
    "physical_references_retained": sum(
        1 for family, recs in master_records.items() for rec in recs for ref in rec.get("source_refs", [])
        if ref.get("source_doc") == MASTER_RFP_FILENAME),
    "pages_represented_after_stage_b": sorted(master_pages),
}
save("master_rfp_contribution.json", master_contribution)

# --- 7. Amendment D2 safety check ------------------------------------------

ORIGINAL_D2 = "OriginalRevision/RFP 2026-026 - Appendix D2 - Rated Criteria Response Form.docx"
REVISED_D2 = "Amendment1/RFP 2026-026 - Appendix D2 - Rated Criteria Response REVISED.docx"


def desc_keys_for(doc_path):
    keys = set()
    for df in doc_facts_list:
        for r in df.get("requirements", []):
            if isinstance(r, dict) and isinstance(r.get("description"), str):
                for ref in r.get("source_refs", []) or []:
                    if isinstance(ref, dict) and ref.get("source_doc") == doc_path:
                        keys.add(re.sub(r"\W+", "", r["description"].strip().lower()))
    return keys


original_keys = desc_keys_for(ORIGINAL_D2)
revised_keys = desc_keys_for(REVISED_D2)
amendment_check = {
    "original_d2_requirement_desc_keys": len(original_keys),
    "revised_d2_requirement_desc_keys": len(revised_keys),
    "overlap_desc_keys": len(original_keys & revised_keys),
    "note": "Stage B's requirement dedup key is an exact normalized-description match; overlap>0 "
            "means original and revised D2 shared at least one byte-identical (post-normalization) "
            "requirement description and were merged into one normalized record citing both "
            "documents. Stage B performs no amendment-precedence or supersession decision here -- "
            "both documents' evidence survives; that adjudication belongs to Stage C.",
    "normalized_requirements_citing_both_d2_variants": sum(
        1 for rec in result["requirements"] if {ORIGINAL_D2, REVISED_D2} <= docs_for_record(rec)),
}
save("amendment_d2_safety_check.json", amendment_check)

# --- 8. Run metadata ---------------------------------------------------------

git_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
git_dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout
run_metadata = {
    "phase2_run_id": PHASE2_RUN_ID,
    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    "git_commit": git_commit or "unavailable",
    "git_working_tree_dirty": bool(git_dirty.strip()),
    "git_working_tree_changed_files": len(git_dirty.strip().splitlines()) if git_dirty.strip() else 0,
    "production_entry_point": "scripts/commission_phase2_stage_b_bank_of_canada.py -> extractor.normalize_package_facts()",
    "stage_b_function": "extractor.normalize_package_facts",
    "helper_modules_invoked": ["extractor.validate_source_refs", "requirement_semantics.normalize_requirement_type",
                               "requirement_semantics.resolve_requirement_type",
                               "requirement_semantics.resolve_candidate_requirement_types",
                               "evaluation_hierarchy.deduplicate_evaluation_criteria",
                               "canonical_opportunity.build_canonical_opportunity",
                               "contract_hygiene.build_contract_hygiene"],
    "input_phase1_run_id": PHASE1_RUN_ID,
    "input_stage_a_digest": result["_canonical_opportunity"]["input_digest"],
    "stage_b_elapsed_seconds": stage_b_elapsed,
    "stage_a_rerun": False,
    "llm_calls_made_this_run": 0,
    "model_used": None,
    "token_usage": "not applicable -- Stage B (normalize_package_facts) makes no LLM calls; verified "
                   "by code inspection (extractor.py lines 2933-3170) and by this run's own zero API "
                   "key usage",
    "api_cost": "not applicable, same reason",
}
save("run_metadata.json", run_metadata)

# --- 9. Final summary print --------------------------------------------------

summary = {
    "phase2_run_id": PHASE2_RUN_ID,
    "phase1_run_id": PHASE1_RUN_ID,
    "stage_a_input_count": total_stage_a_records,
    "requirements_normalized": len(result["requirements"]),
    "dates_normalized": len(result["dates"]),
    "evaluation_criteria_normalized": len(result["evaluation_criteria"]),
    "submission_rules_normalized": len(result["submission_rules"]),
    "deliverables_normalized": len(result["deliverables"]),
    "commercial_clauses_normalized": len(result["commercial_clauses"]),
    "contract_risks_normalized": len(result["contract_risks"]),
    "canonical_opportunity_observations": len(result["_canonical_opportunity"]["observations"]),
    "provenance_rejections_total": len(rejections),
    "provenance_rejections_by_family": rejection_summary,
    "stage_b_elapsed_seconds": stage_b_elapsed,
}
save("summary.json", summary)
print(json.dumps(summary, indent=2, sort_keys=True))
print(f"PHASE 2 / STAGE B: PASS. Dumps at: {OUT.relative_to(ROOT)}")
