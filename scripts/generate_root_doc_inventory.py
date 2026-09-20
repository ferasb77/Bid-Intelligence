"""
scripts/generate_root_doc_inventory.py

Deterministic, zero-LLM generator for docs/current/ROOT_DOC_INVENTORY.json.
No summarization, no semantic judgment -- every field is extracted from a
document's own self-declared "Document Metadata" table (the convention
GOVERNANCE.md itself mandates: "Every governing or architectural document
must declare: Document, Title, Authority Level, Version, Status...") or
from its filename, per the exact rules below. Nothing here reads a
document's body prose to infer meaning.

Re-run this any time root .md files change; it is safe to run repeatedly
(pure function of current repo state -> JSON, no side effects beyond the
one output file).
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT / "docs" / "current" / "ROOT_DOC_INVENTORY.json"

# Same deterministic filename-category rules used in the Phase 1 audit --
# order matters (first match wins), each checked against the filename only.
_CATEGORY_RULES = [
    (re.compile(r"_ARCHITECTURAL_(REVIEW|VALIDATION)\.md$"), "architectural_review"),
    (re.compile(r"_ARCHITECTURE\.md$"), "architecture"),
    (re.compile(r"_SPECIFICATION\.md$"), "specification"),
    (re.compile(r"_COMMISSIONING_REPORT\.md$"), "commissioning_report"),
    (re.compile(r"_REMEDIATION_REPORT\.md$"), "remediation_report"),
    (re.compile(r"_VALIDATION_(REPORT|NOTE)\.md$"), "validation_report"),
    (re.compile(r"_ACCEPTANCE_REPORT\.md$"), "acceptance_report"),
    (re.compile(r"_(BASELINE|TELEMETRY|PILOT)_REPORT\.md$"), "benchmark_report"),
    (re.compile(r"_RELEASE_NOTES\.md$"), "release_note"),
    (re.compile(r"_AUDIT\.md$"), "audit"),
    (re.compile(r"_REVIEW\.md$"), "review"),
    (re.compile(r"_BRIEF(ING_PACK)?\.md$"), "brief"),
    (re.compile(r"_REPORT\.md$"), "report"),
    (re.compile(r"^(AGENT|ANTI_GOALS|GOVERNANCE|MANIFESTO|README)\.md$"), "constitutional"),
]


def _category(filename: str) -> str:
    for pattern, label in _CATEGORY_RULES:
        if pattern.search(filename):
            return label
    return "unknown"


_METADATA_FIELD_RE = re.compile(r"^\|\s*([A-Za-z ]+?)\s*\|\s*(.+?)\s*\|\s*$", re.MULTILINE)

_CURRENT_STATUS_WORDS = ("ratified", "current", "approved", "implemented", "complete")
_DRAFT_STATUS_WORDS = ("proposed", "draft", "review only", "review finding", "investigation complete")


def _extract_metadata(text: str) -> dict:
    """Parses the 'Document Metadata' markdown table this repo's own
    GOVERNANCE.md convention defines. Returns {} if the file doesn't use
    it -- never guessed from prose.

    Scoped strictly to the table immediately following a top-level
    '# Document Metadata' heading, up to the next '#' heading -- NOT any
    '| Status | ... |'-shaped line anywhere in the file. Several report
    bodies contain unrelated tables with their own 'Status' column (e.g. a
    PASS/FAIL results table); matching those would silently misclassify a
    document's currentness from the wrong table entirely."""
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip() == "# Document Metadata":
            start = i + 1
            break
    if start is None:
        return {}
    fields = {}
    for line in lines[start:]:
        if line.strip().startswith("# "):
            break
        m = _METADATA_FIELD_RE.match(line.strip())
        if m:
            key, value = m.group(1).strip(), m.group(2).strip()
            if key in ("Document", "Title", "Authority Level", "Version", "Status",
                      "Purpose", "Higher Authority"):
                fields[key] = value
    return fields


def _currentness(metadata: dict) -> str:
    """CURRENT_DECLARED / HISTORICAL_DECLARED / PROPOSED_OR_DRAFT / UNKNOWN
    -- computed ONLY from the document's own declared Authority Level /
    Status fields, never from filename or body content. A document with no
    metadata table is UNKNOWN, regardless of what its filename suggests
    (filename-derived `category` is a separate field below, for exactly
    this reason -- so the two signals are never conflated)."""
    authority = metadata.get("Authority Level", "")
    status = metadata.get("Status", "").lower()

    if authority.startswith("Level 1") or authority.startswith("Level 2"):
        return "CURRENT_DECLARED"
    if any(w in status for w in _DRAFT_STATUS_WORDS):
        return "PROPOSED_OR_DRAFT"
    if any(w in status for w in _CURRENT_STATUS_WORDS):
        return "CURRENT_DECLARED"
    if authority.startswith("Level 5"):
        return "HISTORICAL_DECLARED"
    if authority.startswith("Level 3") or authority.startswith("Level 4"):
        return "CURRENT_DECLARED"
    return "UNKNOWN"


def build_inventory() -> dict:
    entries = []
    for path in sorted(ROOT.glob("*.md")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        metadata = _extract_metadata(text)
        entries.append({
            "path": path.name,
            "bytes": path.stat().st_size,
            "category": _category(path.name),
            "declared_authority_level": metadata.get("Authority Level"),
            "declared_status": metadata.get("Status"),
            "currentness": _currentness(metadata),
            "has_metadata_table": bool(metadata),
        })
    by_currentness = {}
    for e in entries:
        by_currentness[e["currentness"]] = by_currentness.get(e["currentness"], 0) + 1
    return {
        "schema_version": "1.0",
        "generated_by": "scripts/generate_root_doc_inventory.py",
        "classification_method": "deterministic: self-declared Document Metadata table only "
                                 "(Authority Level / Status); filename analysis contributes only "
                                 "the separate `category` field, never `currentness`. No LLM "
                                 "summarization or semantic judgment was used.",
        "total_files": len(entries),
        "total_bytes": sum(e["bytes"] for e in entries),
        "currentness_summary": by_currentness,
        "documents": entries,
    }


def main():
    inventory = build_inventory()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUT_PATH.relative_to(ROOT)}: {inventory['total_files']} files, "
         f"{inventory['currentness_summary']}")


if __name__ == "__main__":
    sys.exit(main())
