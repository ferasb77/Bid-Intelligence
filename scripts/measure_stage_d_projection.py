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
    finalize_stage_d_request, validate_stage_d_response, expand_prompt_context,
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


def synthetic_high_cardinality_facts(count=559):
    """Generic shape stress, calibrated to retained length statistics, not buyer facts.

    Retained descriptions average 187--197 chars, proof 73--79, excerpts
    132--220. One or two refs per requirement; independent locations make
    evidence high-cardinality even where related text repeats.
    """
    def ref(index, text, variant=0):
        result = {"source_doc": f"schedule-{(index + variant) % 8 + 1:02d}-service-delivery-and-procurement-conditions.pdf",
                  "page": index // 8 + 1, "section": f"Schedule {(index % 8) + 1}, clause {index + 1}",
                  "excerpt": text, "verified": True}
        if index % 9 == 0:
            result.update(sheet="Service requirements", rows=[index + 1, index + 2], cells=f"B{index + 1}:F{index + 2}")
        return result

    descriptions = [
        "Provide an implementation plan covering service transition, responsibilities, acceptance checks and escalation. Identify dependencies and explain how continuity will be maintained during rollout.",
        "Maintain a documented support process with named escalation roles and service reporting. Report incidents, response times and corrective actions throughout the contract, including subcontracted work.",
        "Submit the proposed quality assurance approach for delivery milestones. Explain review responsibilities, defect tracking, acceptance evidence and the process for obtaining written approval of changes.",
        "Describe the delivery team's proposed approach to accessibility and secure information handling. Include review checkpoints, training materials and the process for addressing identified service gaps.",
    ]
    proof = ["Submit the service procedure, named roles and reporting records.",
             "Provide the implementation schedule and acceptance responsibilities.",
             "Include the review process and service assurance documentation."]
    nf = {"doc_metadata": {"title": "Generic managed services procurement", "client": "Synthetic purchasing organization"},
          "requirements": [], **{k: [] for k in ("dates", "evaluation_criteria", "submission_rules", "deliverables", "commercial_clauses", "contract_risks")}}
    for i in range(count):
        description = f"Obligation {i + 1}. " + descriptions[i % len(descriptions)]
        # Not exact copies of description: the model must see the complete
        # separately worded source context, including its final qualification.
        excerpt = (f"Service clause {i + 1}: the response shall explain delivery responsibilities, review checkpoints, "
                   "acceptance evidence and escalation arrangements. Changes require written approval; approval is not automatic.")
        refs = [ref(i, excerpt)]
        if i % 2 == 0:
            refs.append(ref(i, excerpt + " The alternate schedule remains subject to clarification.", 1))
        nf["requirements"].append({"req_id": f"REQ-{i + 1}", "category": "Rated" if i % 4 == 0 else "Mandatory",
                                   "requirement_type": "Evaluation / Scored" if i % 4 == 0 else "Delivery / SLA",
                                   "description": description, "rfso_ref": f"Schedule {i % 8 + 1}, clause {i + 1}",
                                   "weight": "5 points" if i % 4 == 0 else None, "evidence": proof[i % len(proof)] + f" Ref {i + 1}.",
                                   "qual_status": "UNKNOWN", "evidence_status": "MISSING", "source_refs": refs})
    templates = {
        "dates": (12, lambda i: {"milestone": f"Review milestone {i + 1}", "date": None}),
        "evaluation_criteria": (24, lambda i: {"stage": f"Service assessment {i + 1}", "parent_stage": None,
                                              "weight": "5 points", "weight_basis": "Unknown", "threshold": None,
                                              "notes": "Assess the proposed method, relevant delivery evidence and quality assurance approach. Do not infer an overall percentage."}),
        "submission_rules": (76, lambda i: {"item": f"Response component {i + 1}", "format": "PDF", "mandatory": 1,
                                           "artifact_type": "Proposal / Response", "file_format": "PDF", "submission_channel": "Portal",
                                           "details": "Include the delivery approach, responsible roles, acceptance evidence and proposed escalation process. Upload through the specified channel."}),
        "deliverables": (48, lambda i: {"title": f"Service output {i + 1}", "category": "Core",
                                       "description": "Provide documented service procedures, periodic reports and acceptance records. Obtain written approval at the applicable delivery checkpoint."}),
        "commercial_clauses": (24, lambda i: {"topic": f"Commercial condition {i + 1}",
                                             "details": "Proposed pricing must identify the assumptions, applicable rates and approved change process. Additional work requires written agreement."}),
        "contract_risks": (30, lambda i: {"risk": f"Delivery dependency {i + 1}", "severity": "Medium",
                                        "details": "Unconfirmed dependencies may affect the delivery schedule. Identify the assumption and seek clarification before committing to the relevant milestone."}),
    }
    index = count
    for section, (number, factory) in templates.items():
        for i in range(number):
            record = factory(i)
            text = record.get("details", record.get("description", record.get("notes", "The milestone date remains to be confirmed.")))
            record["source_refs"] = [ref(index, text)]
            nf[section].append(record)
            index += 1
    conflicts = [{"conflict_id": f"CONFLICT-{i + 1}", "conflict_type": "SCOPE_CONFLICT", "classification": "TRUE_CONFLICT",
                  "confidence": "HIGH", "source_validity": "PHYSICAL_BOTH", "topic": f"Support coverage {i + 1}",
                  "reason": "The source schedules specify different coverage periods.", "assessment": "Both alternatives require clarification.",
                  "recommended_action": "Request written clarification; do not assume one schedule prevails.",
                  "source_a": {"doc": "schedule-01-service-delivery-and-procurement-conditions.pdf", "ref": f"Coverage {i + 1}", "text": "Provide weekday support during office hours."},
                  "source_b": {"doc": "schedule-02-service-delivery-and-procurement-conditions.pdf", "ref": f"Coverage {i + 1}", "text": "Provide support throughout the week, including weekends."}}
                 for i in range(4)]
    return nf, conflicts


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
        "old_prompt_chars": len(old), "new_prompt_chars": finalized["diagnostics"]["total_prompt_chars"],
        "reduction_chars": len(old) - finalized["diagnostics"]["total_prompt_chars"],
        "reduction_percent": round(100 * (len(old) - finalized["diagnostics"]["total_prompt_chars"]) / len(old), 3),
        "requirements_preserved": len(expand_prompt_context(projection["prompt_context"])["requirements"]) == len(before.get("requirements", [])),
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
        store.write("stage-d/output-config.json", finalized["output_config"])
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
    high_facts, high_conflicts = synthetic_high_cardinality_facts()
    cases.append(("synthetic_559_high_cardinality_provenance", high_facts, high_conflicts))
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
