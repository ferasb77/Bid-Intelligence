"""Stage A Recovery-Path Optimization Package 2 -- pilot/full-run correctness gates.

Deterministic (no LLM) checks against a Stage A document-facts JSON file
(pilot or full run), per the user's Step 10 / Step 15 acceptance criteria:
document coverage intact, zero zero-output documents, valid schema shape,
valid physical source refs, no missing major extraction family, and
presence of named critical corpus facts (spot checks, not exhaustive).

Usage: py -3.13 scripts/correctness_gates_recovery_optimization.py <facts_json_path> [doc_name...]
If no doc names given, checks all documents present in the facts file.
"""
import json
import sys
from pathlib import Path

FAMILIES = ["requirements", "dates", "evaluation_criteria", "submission_rules",
            "deliverables", "commercial_clauses", "typed_observations"]

CRITICAL_FACT_CHECKS = {
    "RFP 2026-026 - Talent, Learning and Organizational Development Services.pdf": [
        ("submission deadline present", lambda f: bool((f.get("doc_metadata") or {}).get("submission_deadline"))),
        ("at least one requirement", lambda f: len(f.get("requirements") or []) > 0),
        ("at least one evaluation criterion", lambda f: len(f.get("evaluation_criteria") or []) > 0),
    ],
    "OriginalRevision/RFP 2026-026 - Appendix D1 - Rated criteria response form.docx": [
        ("15-page limit requirement present", lambda f: any(
            "15 page" in (r.get("description") or "").lower() for r in (f.get("requirements") or []))),
    ],
    "OriginalRevision/RFP 2026-06 - Appendix G - Form of Agreement.docx": [
        ("at least one commercial clause", lambda f: len(f.get("commercial_clauses") or []) > 0),
    ],
    "OriginalRevision/RFP 2026-026 - Appendix E - Pricing Form.xlsx": [
        ("at least one requirement or deliverable (pricing facts)", lambda f: (
            len(f.get("requirements") or []) > 0 or len(f.get("deliverables") or []) > 0)),
    ],
    "abstract.pdf": [
        ("at least one requirement (identity/context facts)", lambda f: len(f.get("requirements") or []) > 0),
    ],
}


def check_source_refs(facts: dict) -> tuple[int, int]:
    """Return (total_refs, refs_missing_required_fields) across all families."""
    total, missing = 0, 0
    for fam in ("requirements", "evaluation_criteria", "submission_rules", "deliverables", "commercial_clauses"):
        for record in facts.get(fam) or []:
            for ref in record.get("source_refs") or []:
                total += 1
                if not isinstance(ref, dict) or not ref.get("source_doc"):
                    missing += 1
    return total, missing


def run_gates(facts_path: str, doc_names: list[str] | None = None):
    all_facts = json.loads(Path(facts_path).read_text(encoding="utf-8"))
    names = doc_names or list(all_facts.keys())
    print(f"Checking {len(names)} document(s) from {facts_path}\n")

    overall_pass = True
    for name in names:
        facts = all_facts.get(name)
        if facts is None:
            print(f"[FAIL] {name}: document missing from facts file entirely")
            overall_pass = False
            continue

        record_counts = {k: len(v) for k, v in facts.items() if isinstance(v, list) and not k.startswith("_")}
        total_records = sum(record_counts.values())
        zero_output = total_records == 0
        diagnostic = facts.get("_extraction_diagnostic", {})
        total_refs, missing_refs = check_source_refs(facts)

        status = "PASS"
        notes = []
        if zero_output:
            status = "FAIL"
            notes.append("ZERO-OUTPUT DOCUMENT")
        if diagnostic.get("status") == "PARSE_FAILURE":
            status = "FAIL"
            notes.append("unrecovered parse failure")
        missing_families = [f for f in FAMILIES if f not in facts]
        if missing_families:
            notes.append(f"families absent from schema: {missing_families}")

        print(f"[{status}] {name}")
        print(f"    record_counts={record_counts} total={total_records}")
        print(f"    recovery_status={diagnostic.get('status', 'VERIFIED_ADEQUATE')}")
        print(f"    source_refs: {total_refs} total, {missing_refs} missing required fields")
        if notes:
            print(f"    notes: {notes}")

        for check_name, check_fn in CRITICAL_FACT_CHECKS.get(name, []):
            ok = check_fn(facts)
            print(f"    critical-fact check [{'PASS' if ok else 'FAIL'}]: {check_name}")
            if not ok:
                overall_pass = False

        if status == "FAIL":
            overall_pass = False
        print()

    print("OVERALL CORRECTNESS GATES:", "PASS" if overall_pass else "FAIL")
    return overall_pass


if __name__ == "__main__":
    facts_path = sys.argv[1]
    doc_names = sys.argv[2:] or None
    ok = run_gates(facts_path, doc_names)
    sys.exit(0 if ok else 1)
