"""Offline Stage D size comparison for canonical integration."""
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import extractor
from canonical_opportunity import build_canonical_opportunity, resolve_canonical_opportunity
from stage_d_projection import build_stage_d_synthesis_projection, finalize_stage_d_request


def size(normalized, conflicts):
    projection = build_stage_d_synthesis_projection(normalized, conflicts)
    return finalize_stage_d_request(projection, extractor.STAGE_D_SYNTHESIS_PROMPT)["diagnostics"]


def empty_legacy_canonical(files):
    meta = {"files": files, "doc_metadata": {}, "doc_texts": {}}
    value = resolve_canonical_opportunity(build_canonical_opportunity([], meta))
    value["integrity_diagnostics"]["legacy_replay_missing_typed_observations"] = True
    return value


def main():
    results = []
    directory = ROOT / "tests/acceptance/results"
    for prefix in ("boc_2026_026", "bc_ir67tvet42026_attempt2"):
        normalized = json.loads((directory / f"{prefix}_normalized_facts.json").read_text(encoding="utf-8"))
        conflicts = json.loads((directory / f"{prefix}_conflicts.json").read_text(encoding="utf-8"))
        before = size(normalized, conflicts)
        after_input = copy.deepcopy(normalized)
        files = sorted({r.get("source_doc") for section in ("requirements", "dates", "commercial_clauses")
                        for r in normalized.get(section, []) if isinstance(r, dict) and r.get("source_doc")})
        after_input["_canonical_opportunity"] = empty_legacy_canonical(files)
        after = size(after_input, conflicts)
        results.append({"fixture": prefix, "replay_mode": "RETAINED_LEGACY_NO_TYPED_OBSERVATIONS",
                        "before_chars": before["total_prompt_chars"], "after_chars": after["total_prompt_chars"],
                        "difference_chars": after["total_prompt_chars"] - before["total_prompt_chars"],
                        "guard_chars": after["guard_chars"], "headroom_chars": after["headroom_chars"],
                        "dispatch_allowed": after["dispatch_allowed"],
                        "full_canonical_ledger_in_prompt": False})

    text = "[[SOURCE: synthetic.txt | PAGE: 1]]\nAlpha Procurement Buyer Alpha SOL-1 closes 2030-01-02. CAD 1000."
    typed = [{"typed_observations": [
        {"family": "IDENTITY", "semantic_kind": "OPPORTUNITY_TITLE", "original_value": "Alpha Procurement", "source_doc": "synthetic.txt", "source_refs": [{"source_doc": "synthetic.txt", "page": 1, "excerpt": "Alpha Procurement"}]},
        {"family": "MILESTONE", "semantic_kind": "SUBMISSION_DEADLINE", "original_value": "2030-01-02", "date": "2030-01-02", "source_doc": "synthetic.txt", "source_refs": [{"source_doc": "synthetic.txt", "page": 1, "excerpt": "2030-01-02"}]},
        {"family": "MONETARY", "semantic_kind": "ESTIMATED_CONTRACT_VALUE", "original_value": "1000", "amount": "1000", "currency": "CAD", "source_doc": "synthetic.txt", "source_refs": [{"source_doc": "synthetic.txt", "page": 1, "excerpt": "CAD 1000"}]},
    ]}]
    normalized = {"doc_metadata": {}, "requirements": [], "dates": [], "evaluation_criteria": [], "submission_rules": [], "deliverables": [], "commercial_clauses": [], "contract_risks": []}
    before = size(normalized, [])
    normalized["_canonical_opportunity"] = resolve_canonical_opportunity(build_canonical_opportunity(
        typed, {"files": ["synthetic.txt"], "doc_metadata": {"synthetic.txt": {"page_count": 1}}, "doc_texts": {"synthetic.txt": text}}))
    after = size(normalized, [])
    results.append({"fixture": "synthetic_canonical_package", "replay_mode": "NATIVE_TYPED_OBSERVATIONS",
                    "before_chars": before["total_prompt_chars"], "after_chars": after["total_prompt_chars"],
                    "difference_chars": after["total_prompt_chars"] - before["total_prompt_chars"],
                    "guard_chars": after["guard_chars"], "headroom_chars": after["headroom_chars"],
                    "dispatch_allowed": after["dispatch_allowed"], "full_canonical_ledger_in_prompt": False})
    output = {"evidence_kind": "CANONICAL_STAGE_D_CAPACITY_REGRESSION", "measurements": results}
    (directory / "canonical_opportunity_stage_d_measurements.json").write_text(
        json.dumps(output, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
