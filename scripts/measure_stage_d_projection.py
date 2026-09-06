"""Offline serialization only. Raw evidence goes to a required private bundle.

Run with --checkpoint-root outside all Git checkouts. No model calls or writes
to source fixtures. Optional --normalized/--conflicts measures an additional
retained pair; the synthetic case never represents buyer acceptance.
"""
import argparse
import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import extractor
from stage_d_checkpoints import checkpoint_run
from stage_d_projection import (
    AUTHORITATIVE_SECTIONS, build_stage_d_synthesis_projection,
    finalize_stage_d_request, validate_stage_d_response,
)


def synthetic_large_facts(count=559):
    """Generic shared schedules; mechanical scalability, not BC acceptance."""
    common = "Apply the documented service requirements. " * 8 + "Exceptions require written approval."
    refs = [{"source_doc": f"service-schedule-{i}.pdf", "page": i + 1, "section": "Service conditions",
             "excerpt": common, "verified": True} for i in range(4)]
    return {"requirements": [
        {"req_id": f"M{i}", "category": "Mandatory", "requirement_type": "Delivery / SLA",
         "description": f"Service obligation {i}: " + "Provide monitored support and document escalation procedures. " * 4,
         "evidence": "Provide the service procedure and escalation records.", "qual_status": "UNKNOWN",
         "evidence_status": "MISSING", "source_refs": copy.deepcopy(refs)} for i in range(count)]}


def _source_ref_count(value):
    if isinstance(value, list):
        return sum(_source_ref_count(v) for v in value)
    if isinstance(value, dict):
        return sum(len(v) if k == "source_refs" else _source_ref_count(v) for k, v in value.items())
    return 0


def measure(label, normalized, conflicts, checkpoint_root):
    before = copy.deepcopy(normalized)
    projection = build_stage_d_synthesis_projection(normalized, conflicts)
    finalized = finalize_stage_d_request(projection, extractor.STAGE_D_SYNTHESIS_PROMPT)
    old = (extractor.LEGACY_STAGE_D_SYNTHESIS_PROMPT + "\n\nNORMALIZED PROCUREMENT FACTS MODEL:\n"
           + json.dumps(extractor.build_stage_d_context(normalized, conflicts), indent=2))
    # Exercise validation/assembly with explicitly unknown interpretation.
    # This is not a generated Bid Brief or a live synthesis acceptance run.
    response = {"synthesis": {
        "bid": {"title": None, "client": None, "file_number": None, "owner": None,
                "sensitivity": "Standard", "submission_deadline": None, "clarification_deadline": None,
                "value_cad": None, "notes": None},
        "brief": {"executive_summary": None, "opportunity_type": None, "contract_term": "Not stated",
                  "procurement_model": None, "scope_categories": []}, "outline": []}, "citations": []}
    accepted = validate_stage_d_response(response, projection)
    actual = extractor.apply_stage_d_authoritative_sections(accepted["synthesis"], copy.deepcopy(normalized))
    expected = extractor.apply_stage_d_authoritative_sections({}, copy.deepcopy(normalized))
    final = extractor._assemble_procurement_result(actual, normalized, conflicts)
    source_refs = _source_ref_count(normalized)
    preserved = sum(len(e["source_pointers"]) for e in projection["sidecar"]["evidence"].values() if e["origin_kind"] == "source_ref")
    summary = {
        "case": label, "execution_mode": "OFFLINE_SERIALIZATION_NO_LLM",
        "old_prompt_chars": len(old), "new_prompt_chars": len(finalized["request_text"]),
        "reduction_chars": len(old) - len(finalized["request_text"]),
        "reduction_percent": round(100 * (len(old) - len(finalized["request_text"])) / len(old), 3),
        "requirements_preserved": len(projection["prompt_context"]["requirements"]) == len(before.get("requirements", [])),
        "source_ref_occurrences": source_refs, "preserved_source_ref_occurrences": preserved,
        "evidence_refs_preserved": source_refs == preserved,
        "authoritative_sections_unchanged": all(actual["brief"][k] == expected["brief"][k] for k in AUTHORITATIVE_SECTIONS),
        "final_requirements_unchanged": final["requirements"] == before.get("requirements", []),
        "final_conflicts_unchanged": final["brief"]["document_conflicts"] == conflicts,
        "final_documents_unchanged": final["documents"] == extractor.build_submission_documents(before.get("submission_rules", []), submission_deadline=None),
        "inputs_unchanged": normalized == before,
        "diagnostics": finalized["diagnostics"],
    }
    with checkpoint_run(mode="required", root=checkpoint_root) as store:
        store.write("stage-b/normalized-facts.json", normalized)
        store.write("stage-c/conflicts.json", conflicts)
        store.write("stage-d/projection.json", projection["prompt_context"])
        store.write("stage-d/sidecar.json", projection["sidecar"])
        store.write("stage-d/size-diagnostics.json", finalized["diagnostics"])
        store.write("stage-d/request.txt", finalized["request_text"], text=True)
        store.write("offline-measurement.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint-root", required=True)
    parser.add_argument("--normalized", type=Path)
    parser.add_argument("--conflicts", type=Path)
    args = parser.parse_args()
    if bool(args.normalized) != bool(args.conflicts):
        parser.error("Supply both --normalized and --conflicts")
    cases = [("synthetic_559_shared_schedules_NOT_BC_ACCEPTANCE", synthetic_large_facts(), [])]
    results = ROOT / "tests" / "acceptance" / "results"
    for prefix in ("boc_2026_026", "bc_ir67tvet42026_attempt2"):
        source = results / (prefix + "_normalized_facts.json")
        conflict = results / (prefix + "_conflicts.json")
        if source.exists() and conflict.exists():
            cases.append((prefix, json.loads(source.read_text(encoding="utf-8")), json.loads(conflict.read_text(encoding="utf-8"))))
    if args.normalized:
        cases.append(("additional_retained_pair", json.loads(args.normalized.read_text(encoding="utf-8")), json.loads(args.conflicts.read_text(encoding="utf-8"))))
    summaries = [measure(label, n, c, args.checkpoint_root) for label, n, c in cases]
    print(json.dumps(summaries, indent=2))


if __name__ == "__main__":
    main()
