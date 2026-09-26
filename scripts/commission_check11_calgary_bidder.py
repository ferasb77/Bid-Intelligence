"""
CHECK-1.1 -- one-off live commissioning step for the REAL Calgary 26-1603
bidder package (Phoenix Consulting Canada). Deterministic: zero model
calls in every subcommand.

  persist <bidder.zip> <bid_id> <organization_id> <out_dir>
      Build the canonical SubmissionPackage from the real ZIP (nested
      archive included), persist it through migration 021
      (tenancy.persist_submission_evidence_package_for_organization) and
      write <out_dir>/check11_expected.json -- the in-memory result the
      fresh-process verification compares against.

  verify <bid_id> <organization_id> <package_snapshot_id> <run_id> <out_dir>
      FRESH PROCESS, no in-memory state: reload the package from migration
      021 rows only, rebuild requirement / criterion mappings against the
      benchmark bid's canonical procurement package (Fast Analysis run
      <run_id>, rebuilt from its persisted raw snapshot with zero model
      calls) and compare everything with check11_expected.json.

  fixture <bidder.zip> <out_json>
      Write the derived, content-free benchmark fixture definition
      (hashes, roles, representation links, counts, structural locators --
      no prices, no personal contact data) used by
      tests/test_check11_real_calgary_benchmark.py.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import warnings

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
warnings.filterwarnings("ignore")


def _env():
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
    except Exception:
        pass


def _digest(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


RFP_DOC_PREFIX = "S-PT-073-RFP with Price"


def canonical_inputs(run_id: int):
    """(requirements, criteria) CHECK-1 inputs derived from the benchmark
    bid's persisted, canonicalized Fast Analysis result (zero model calls)
    -- buyer-side truth, INPUT only, never written anywhere.

    Requirements: FastAnalysisResult.requirements (canonicalized in place
    by procurement_normalization; req_id = the SAME REQ-<i> canonical id
    full_analysis.build_canonical_package assigns). The raw `category` is
    used because the CanonicalPackage projection reads `requirement_type`,
    which this run's requirements do not carry (reported, not patched).
    Criteria: evaluation_criteria whose source is the RFP's own evaluation
    table (the Q&A-log restatements carry conflicting weights that Fast
    Analysis itself flags as `evaluation_weight_conflicts`)."""
    import analysis_service
    r = analysis_service.load_raw_fast_analysis_result(run_id)
    reqs = [{"req_id": f"REQ-{i}", "category": q.get("category") or "", "description": q.get("description") or "",
             "source_doc": q.get("source_doc")}
            for i, q in enumerate(r.requirements) if isinstance(q, dict)]
    crits = []
    for c in r.evaluation_criteria:
        if not str(c.get("source_doc") or "").startswith(RFP_DOC_PREFIX):
            continue
        excerpt = " ".join(str(x.get("excerpt") or "") for x in (c.get("source_refs") or []))
        crits.append({"criterion_label": c.get("stage") or "", "category": "", "weight": c.get("weight"),
                      "threshold": c.get("threshold"), "prompt": excerpt})
    reqs.append(dict(SUPPLEMENTAL_MULTI_PARTY))
    return r, reqs, crits


# The B2 obligation sentence sits in a content control of the RFP DOCX that
# extractor.py's text extraction does not reach, so Fast Analysis never saw
# it and no canonical requirement carries it. It is used here VERBATIM, as
# a clearly-labelled commissioning input only (never persisted, never
# written to requirements) so the real B2 mapping can be exercised.
SUPPLEMENTAL_MULTI_PARTY = {
    "req_id": "SUPP-B2-VERBATIM", "category": "Mandatory",
    "description": ("Each proposal that is submitted on behalf of, and contemplates the provision of the "
                    "Deliverables by a Multi-Party Team must include a Multi-Party Confirmation Form completed and "
                    "signed by all Team Members."),
    "source_doc": "S-PT-073-RFP with Price - V2.5_Design and Delivery Services for Leadership Learning and "
                  "Development_June 12.docx (word/document.xml, B2: MULTI-PARTY CONFIRMATION FORM)",
    "provenance": "VERBATIM_BUYER_CLAUSE_NOT_IN_FAST_ANALYSIS",
}


def cmd_buyer_snapshot(run_id, out_json):
    """Derived buyer-side canonical snapshot for the tests (public RFP
    text only)."""
    r, reqs, crits = canonical_inputs(int(run_id))
    out = {
        "_provenance": (f"Buyer-side canonical procurement objects of benchmark bid 1360, Fast Analysis run {run_id} "
                        "(fast-analysis-v4, persisted raw snapshot, read with zero model calls). Requirements are the "
                        "canonicalized FastAnalysisResult.requirements verbatim (req_id = canonical REQ-<i>); criteria "
                        "are the RFP evaluation-table rows. One clearly-labelled VERBATIM supplemental clause (B2) is "
                        "appended; it is NOT part of the Fast Analysis canonical set."),
        "analysis_run_id": int(run_id),
        "requirements": reqs,
        "rfp_evaluation_criteria": [{k: c[k] for k in ("criterion_label", "weight", "threshold")} for c in crits],
        "milestones": [{"label": m.get("label"), "original_wording": m.get("original_wording"),
                        "normalized_date_start": m.get("normalized_date_start")} for m in r.canonical_milestones],
        "identity_by_document": r.doc_metadata_by_doc,
        "ambiguities": [a if isinstance(a, str) else str(a) for a in r.ambiguities],
    }
    with open(out_json, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False, default=str)
    print("buyer snapshot:", out_json, len(reqs), "requirements", len(crits), "criteria")


def mapping_view(package, reqs, crits) -> dict:
    import submission_package as sp
    rm = sp.map_requirements_to_submission(reqs, package)
    cm = sp.map_evaluation_criteria_to_sections(crits, package)
    return {"requirement_mappings": [m.to_dict() for m in rm], "criteria_mappings": [c.to_dict() for c in cm]}


def package_view(package) -> dict:
    import submission_package as sp
    payload = sp.build_persistence_payload(package)
    docs = sorted(payload["documents"], key=lambda d: d["submission_document_id"])
    items = sorted(payload["evidence_items"], key=lambda i: i["evidence_id"])
    return {"package_digest": package.package_digest, "documents": docs, "evidence_items": items,
            "member_documents": sorted(d.submission_document_id for d in package.member_documents()),
            "roles_present": {k: sorted(v) for k, v in package.roles_present().items()}}


def cmd_persist(zip_path, bid_id, org, out_dir):
    import tenancy
    raw = [(os.path.basename(zip_path), open(zip_path, "rb").read())]
    res = tenancy.persist_submission_evidence_package_for_organization(int(bid_id), org, raw)
    pkg = res["package"]
    view = package_view(pkg)
    out = {"package_snapshot": {k: res["package_snapshot"][k] for k in ("id", "bid_id", "package_version", "package_digest")},
           "evidence_rows_inserted": res["evidence_rows_inserted"], "already_persisted": res["already_persisted"],
           "package_view": view, "package_view_digest": _digest(view)}
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "check11_expected.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, default=str)
    print(json.dumps({k: v for k, v in out.items() if k != "package_view"}, indent=1, default=str))
    print("documents:", len(view["documents"]), "evidence:", len(view["evidence_items"]),
          "members:", len(view["member_documents"]))


def cmd_verify(bid_id, org, snapshot_id, run_id, out_dir):
    import tenancy
    import submission_package as sp
    expected = json.load(open(os.path.join(out_dir, "check11_expected.json"), encoding="utf-8"))
    pkg = tenancy.load_submission_evidence_package_for_organization(int(bid_id), org, int(snapshot_id))
    view = package_view(pkg)
    checks = {}
    ev = expected["package_view"]
    checks["package_digest"] = view["package_digest"] == ev["package_digest"]
    checks["documents_equal"] = _digest(view["documents"]) == _digest(ev["documents"])
    checks["evidence_items_equal"] = _digest(view["evidence_items"]) == _digest(ev["evidence_items"])
    checks["member_documents_equal"] = view["member_documents"] == ev["member_documents"]
    checks["roles_present_equal"] = view["roles_present"] == ev["roles_present"]
    checks["whole_view_digest_equal"] = _digest(view) == expected["package_view_digest"]
    checks["bid_ownership"] = all(i.bid_id == int(bid_id) for i in pkg.registry)
    try:
        other = sp.SubmissionEvidenceRegistry(int(bid_id), list(pkg.registry))
        other.get(next(iter(pkg.registry)).evidence_id, bid_id=int(bid_id) + 1)
        checks["cross_bid_resolution_fails_closed"] = False
    except sp.CrossBidEvidenceError:
        checks["cross_bid_resolution_fails_closed"] = True
    # Mappings: recomputed from the FRESH package vs. from a fresh in-memory
    # rebuild of the real files are compared in the persist/verify pair via
    # the mapping digest written below; here they are computed against the
    # canonical procurement package.
    cpkg, reqs, crits = canonical_inputs(int(run_id))
    mv = mapping_view(pkg, reqs, crits)
    with open(os.path.join(out_dir, "check11_mappings_from_db.json"), "w", encoding="utf-8") as fh:
        json.dump(mv, fh, indent=1, default=str)
    checks["mapping_digest_from_db"] = _digest(mv)
    print(json.dumps(checks, indent=1))


def cmd_mappings_in_memory(zip_path, bid_id, org, run_id, out_dir):
    import submission_package as sp
    raw = [(os.path.basename(zip_path), open(zip_path, "rb").read())]
    pkg = sp.build_submission_package(raw, bid_id=int(bid_id), organization_id=org)
    cpkg, reqs, crits = canonical_inputs(int(run_id))
    mv = mapping_view(pkg, reqs, crits)
    with open(os.path.join(out_dir, "check11_mappings_in_memory.json"), "w", encoding="utf-8") as fh:
        json.dump(mv, fh, indent=1, default=str)
    print(json.dumps({"mapping_digest_in_memory": _digest(mv), "requirements": len(reqs), "criteria": len(crits)}))


def cmd_fixture(zip_path, out_json):
    import submission_package as sp
    raw = [(os.path.basename(zip_path), open(zip_path, "rb").read())]
    pkg = sp.build_submission_package(raw, bid_id=0, organization_id="fixture")
    from collections import Counter
    docs = []
    for d in pkg.documents:
        items = pkg.registry.for_document(d.submission_document_id)
        docs.append({
            "package_path": d.package_path, "filename": d.filename, "file_type": d.file_type,
            "content_hash": d.content_hash, "lifecycle_status": d.lifecycle_status,
            "logical_artifact_id": d.logical_artifact_id, "representation_relationship": d.representation_relationship,
            "representation_of_path": pkg.document(d.representation_of).package_path if d.representation_of else None,
            "included": d.included, "primary_role": d.document_role, "secondary_roles": list(d.role.secondary_roles),
            "role_confidence": d.role.confidence, "parse_status": d.parse_status, "page_count": d.page_count,
            "sheets": list(d.sheets), "section_titles": [s.label for s in d.sections] if d.is_authoritative else [],
            "evidence_count": d.evidence_count, "evidence_kinds": dict(Counter(i.kind for i in items)),
        })
    pricing = next(d for d in pkg.member_documents() if d.document_role == sp.ROLE_PRICING_FORM)
    price_cells = [{"cell": i.location.get("cell"), "sheet": i.location.get("sheet"),
                    "is_input_cell": i.structured_value.get("is_input_cell"),
                    "is_formula": i.structured_value.get("is_formula"),
                    "completed": i.structured_value.get("completed"),
                    "column_header": i.structured_value.get("column_header")}
                   for i in pkg.registry.for_document(pricing.submission_document_id)
                   if i.kind == sp.EVIDENCE_KIND_SHEET_CELL and i.structured_value.get("is_input_cell")]
    subform = next(d for d in pkg.member_documents() if d.document_role == sp.ROLE_SUBMISSION_FORM)
    form_labels = [{"label": i.structured_value.get("label"), "completed": i.structured_value.get("completed"),
                    "page": i.location.get("page")}
                   for i in pkg.registry.for_document(subform.submission_document_id)
                   if i.kind == sp.EVIDENCE_KIND_FORM_FIELD and (i.structured_value or {}).get("source") == "pdf_form_table"]
    out = {
        "_provenance": ("DERIVED benchmark definition generated by scripts/commission_check11_calgary_bidder.py "
                        "fixture from the REAL Phoenix Consulting Canada submission for City of Calgary RFP 26-1603 "
                        "(OneDrive_2_9-27-2026.zip). Content-free by design: hashes, roles, representation links, "
                        "counts and structural locators only -- no prices, no contact details, no proposal prose."),
        "bidder_zip": {"filename": os.path.basename(zip_path),
                       "sha256": hashlib.sha256(open(zip_path, "rb").read()).hexdigest()},
        "contract_version": pkg.contract_version, "package_digest": pkg.package_digest,
        "documents": sorted(docs, key=lambda d: d["package_path"]),
        "logical_artifact_count": len(pkg.member_documents()),
        "pricing_input_cells": sorted(price_cells, key=lambda c: c["cell"]),
        "submission_form_fields": form_labels,
    }
    with open(out_json, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False)
    print("fixture written:", out_json, "documents:", len(docs), "members:", out["logical_artifact_count"])


if __name__ == "__main__":
    _env()
    cmd, *args = sys.argv[1:]
    {"persist": cmd_persist, "verify": cmd_verify, "fixture": cmd_fixture,
     "mappings": cmd_mappings_in_memory, "buyer_snapshot": cmd_buyer_snapshot}[cmd](*args)
