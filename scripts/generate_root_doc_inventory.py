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


# ---------------------------------------------------------------------------
# Phase 3: docs/current/DOCUMENT_AUTHORITY_MAP.json -- a richer, still
# fully deterministic classification adding git history, inbound-reference
# counts, and a 5-tier confidence classification. No LLM calls, no body
# summarization -- only signals already computed above plus git log and a
# repo-wide filename-mention grep.
# ---------------------------------------------------------------------------
AUTHORITY_MAP_PATH = ROOT / "docs" / "current" / "DOCUMENT_AUTHORITY_MAP.json"

# The one version family with an explicit, verified-in-code current version
# (fast_analysis.py: FAST_ANALYSIS_ENGINE_VERSION = "fast-analysis-v4").
# Deliberately NOT auto-detected generically (e.g. by regex on "V\d") --
# every other apparent cluster (BUYER_*, OPPORTUNITY_*, PHASE-numbered) has
# no equivalent single-source-of-truth code fact to cite, so none of them
# are auto-classified as a version chain here; they stay NEEDS_REVIEW.
_VERIFIED_SUPERSEDED_VERSIONS = {
    "FAST_ANALYSIS_V1_IMPLEMENTATION_REPORT.md": "fast-analysis (current: fast_analysis.py, v4)",
    "FAST_ANALYSIS_V2_IMPLEMENTATION_REPORT.md": "fast-analysis (current: fast_analysis.py, v4)",
    "FAST_ANALYSIS_V3_IMPLEMENTATION_REPORT.md": "fast-analysis (current: fast_analysis.py, v4)",
}
# The current version's OWN report is deliberately left out of the
# superseded set (it describes the still-current engine) but is also not
# safely auto-movable to a "current" location without risking being read as
# living architecture -- see classification_basis for the reasoning applied.
_CURRENT_VERSION_REPORTS_NEEDING_REVIEW = {
    "FAST_ANALYSIS_V4_IMPLEMENTATION_REPORT.md",
    "FAST_ANALYSIS_V4_SOURCE_TRUTH_RECONCILIATION.md",
}

# Phase 3: this session's own new root agent-instruction files. Filename
# category correctly finds no content-shape signal for them (they aren't
# architecture/report-shaped) -- they are current by definition (created
# this session as the always-on agent entry points), not genuinely
# ambiguous, so this is a named override rather than a guess.
_KNOWN_CURRENT_FILES = {"AGENTS.md", "CLAUDE.md", "GEMINI.md"}

# Phase 3: a small, bounded set of files where filename+metadata signals
# alone left real ambiguity (17 candidates). Each was resolved by reading
# ONLY its header (<=8 lines, via `head`), never the full body, never
# summarized by a model -- the exact quoted evidence is recorded here so
# the decision is reproducible and auditable, not a black-box judgment.
_MANUAL_REVIEW_OVERRIDES = {
    "DECISION_ANALYST_ARCHITECTURE_PHASE2.md": (
        "HIGH_CONFIDENCE_PROPOSED",
        "header states verbatim: 'No production module imports Phase 2. It changes no "
        "extraction, validation, synthesis, replay, checkpoint, persistence, proposal, "
        "schema, prompt, or public API behavior.' -- self-declared not-yet-implemented.",
        "docs/archive/proposed/",
    ),
    "DECISION_INTELLIGENCE_ARCHITECTURE_PHASE1.md": (
        "HIGH_CONFIDENCE_PROPOSED",
        "header states verbatim: 'Phase 1 defines structures only. It contains no "
        "specialist business rules, procurement inference, prompt, model call, "
        "persistence, search, scoring, moderation, or UI behavior.'",
        "docs/archive/proposed/",
    ),
    "BID_INTELLIGENCE_PHASE8_AUTH_TENANCY_FOUNDATION.md": (
        "HIGH_CONFIDENCE_HISTORICAL",
        "header: 'Phase 8 Remediation Package 2 ... Package 3 closes the authorization "
        "gap' -- an intermediate step explicitly superseded by Package 3 (below); "
        "grouped with the other two Phase 8 packages as one coherent operational record.",
        "docs/archive/operational/",
    ),
    "BID_INTELLIGENCE_PHASE8_RLS_REMEDIATION_1.md": (
        "HIGH_CONFIDENCE_HISTORICAL",
        "header: 'Phase 8 Remediation Package 1 ... Nothing else' -- a scoped, completed "
        "remediation step with a cited baseline commit; grouped with the other two "
        "Phase 8 packages.",
        "docs/archive/operational/",
    ),
    "BID_INTELLIGENCE_PHASE8_TENANT_RLS_ENFORCEMENT.md": (
        "HIGH_CONFIDENCE_HISTORICAL",
        "header: 'Phase 8 Remediation Package 3 ... FINAL INTERACTIVE CUTOVER COMPLETE'. "
        "This is the largest root document (106KB) and describes the RLS architecture "
        "that IS the live tenancy model (migration 008, tenancy.py) -- but it is itself "
        "still a dated completion report, not the architecture's living source (the code "
        "and migration 008 are). Archived as a complete Phase-8 trilogy alongside "
        "packages 1-2, not split.",
        "docs/archive/operational/",
    ),
    "RC1_PRE_MERGE_REVIEW.md": (
        "HIGH_CONFIDENCE_HISTORICAL",
        "header: point-in-time pre-merge review for a specific old RC HEAD "
        "(926065bec5f0fb3cfcd4b38c16652da45d8c6aec) on a since-merged/abandoned branch.",
        "docs/archive/operational/",
    ),
    "BID_INTELLIGENCE_COMMISSIONED_BASELINE.md": (
        "HIGH_CONFIDENCE_HISTORICAL",
        "header states verbatim it 'freezes the current ... state as the reproducible "
        "commissioned baseline' as of 2026-09-15 -- a dated snapshot, since superseded by "
        "all later work (raw-snapshot persistence, Section Analyzer, etc.).",
        "docs/archive/operational/",
    ),
    "BRAND-INTEGRATION.md": (
        "HIGH_CONFIDENCE_CURRENT",
        "header content is present-tense, ongoing brand/positioning guidance (product "
        "name, edition), not a record of a past event or decision.",
        None,
    ),
    "CONSTITUTIONAL_COMPLETENESS_REVIEW.md": (
        "HIGH_CONFIDENCE_HISTORICAL",
        "DOES self-declare metadata (Authority level: 'Level 5 -- Operational "
        "architectural review', Status: 'Review finding') but under a level-2 '## "
        "Document metadata' heading with lowercase field names -- a format deviation "
        "from the '# Document Metadata' convention that made the strict deterministic "
        "extractor miss it. Confirmed by direct header read, not guessed. Flagged for "
        "Phase 4: standardize the metadata heading format repo-wide.",
        "docs/archive/operational/",
    ),
}


_HISTORICAL_SHAPED_CATEGORIES = {
    "commissioning_report", "remediation_report", "validation_report",
    "acceptance_report", "benchmark_report", "release_note", "audit",
    "architectural_review", "brief", "report",
}
_CURRENT_SHAPED_CATEGORIES = {"architecture", "specification", "constitutional"}

# Root .md files that the current-orientation layer (SYSTEM_STATE.md,
# NAVIGATION.md, README.md) itself names -- computed once, used to avoid
# moving anything those files point a fresh agent at.
_CURRENT_DOC_REFERRERS = ["SYSTEM_STATE.md", "NAVIGATION.md"]


def _git_last_modified(filename: str) -> str | None:
    import subprocess
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%ai", "--", filename],
            cwd=ROOT, capture_output=True, text=True, timeout=10)
        out = result.stdout.strip()
        return out or None
    except Exception:
        return None


def _build_reference_index() -> dict:
    """One repo-wide grep pass (not 102 separate ones) counting how many
    times each root .md filename is mentioned in *.md/*.py/*.sql/*.json/
    *.toml, excluding the file's own body and .git. A crude but
    deterministic, cheap, zero-LLM proxy for 'is anything still pointing at
    this file.'"""
    import subprocess
    filenames = [p.name for p in ROOT.glob("*.md")]
    counts = {name: 0 for name in filenames}
    referrers = {name: set() for name in filenames}
    exts = ("*.md", "*.py", "*.sql", "*.json", "*.toml")
    candidate_files = []
    for ext in exts:
        candidate_files.extend(ROOT.rglob(ext))
    for f in candidate_files:
        rel = f.relative_to(ROOT)
        parts = rel.parts
        if parts and parts[0] in (".git", "node_modules", ".pytest_cache"):
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for name in filenames:
            if name == f.name:
                continue  # a file doesn't count as referencing itself
            if name in text:
                counts[name] += text.count(name)
                referrers[name].add(str(rel).replace("\\", "/"))
    return counts, referrers


def _classify(entry: dict, ref_count: int, referring_files: set) -> tuple[str, str, str | None]:
    """Returns (classification, basis, proposed_destination).
    classification is one of HIGH_CONFIDENCE_CURRENT / _HISTORICAL /
    _PROPOSED / _SUPERSEDED / NEEDS_REVIEW."""
    name = entry["path"]
    category = entry["category"]
    currentness = entry["currentness"]

    referenced_by_current = any(r in referring_files for r in _CURRENT_DOC_REFERRERS)

    if name in _KNOWN_CURRENT_FILES:
        return ("HIGH_CONFIDENCE_CURRENT",
               "known agent-instruction entry point (Phase 2 of this program)", None)

    if name in _MANUAL_REVIEW_OVERRIDES:
        classification, basis, destination = _MANUAL_REVIEW_OVERRIDES[name]
        return (classification, f"bounded header-only review (Phase 3): {basis}", destination)

    if name in _VERIFIED_SUPERSEDED_VERSIONS:
        return ("HIGH_CONFIDENCE_SUPERSEDED",
               f"explicit verified-in-code version chain: {_VERIFIED_SUPERSEDED_VERSIONS[name]}",
               "docs/archive/superseded/fast-analysis/")

    if name in _CURRENT_VERSION_REPORTS_NEEDING_REVIEW:
        return ("NEEDS_REVIEW",
               "current version's own implementation report -- describes still-active engine but "
               "is itself an operational record (Level 5 by governance definition); destination "
               "ambiguous between 'current-adjacent' and 'archive', left for Phase 4 decision",
               None)

    if currentness == "PROPOSED_OR_DRAFT":
        return ("HIGH_CONFIDENCE_PROPOSED",
               f"self-declared metadata: status={entry['declared_status']!r}",
               "docs/archive/proposed/")

    if currentness == "CURRENT_DECLARED":
        if referenced_by_current:
            return ("HIGH_CONFIDENCE_CURRENT",
                   "self-declared current + referenced by SYSTEM_STATE.md/NAVIGATION.md", None)
        return ("HIGH_CONFIDENCE_CURRENT",
               f"self-declared metadata: authority={entry['declared_authority_level']!r}, "
               f"status={entry['declared_status']!r}", None)

    # No metadata table (currentness == UNKNOWN) from here down -- filename
    # + reference-graph signals only, per instruction 1/3.
    if entry["declared_authority_level"] and entry["declared_authority_level"].startswith("Level 5"):
        return ("HIGH_CONFIDENCE_HISTORICAL",
               f"self-declared Authority Level 5 (Operational Record) with no current/draft status "
               f"word: status={entry['declared_status']!r}",
               "docs/archive/operational/")

    if referenced_by_current:
        return ("NEEDS_REVIEW",
               "no metadata, but referenced by SYSTEM_STATE.md/NAVIGATION.md -- do not move without "
               "checking why it's still cited", None)

    if category in _CURRENT_SHAPED_CATEGORIES:
        return ("HIGH_CONFIDENCE_CURRENT",
               f"filename category '{category}' (architecture/specification-shaped), no contradicting "
               f"metadata, not referenced elsewhere as superseded", None)

    if category in _HISTORICAL_SHAPED_CATEGORIES:
        dest = "docs/archive/operational/"
        if name.startswith("BANK_OF_CANADA_"):
            dest = "docs/archive/engagements/bank-of-canada/"
        return ("HIGH_CONFIDENCE_HISTORICAL",
               f"filename category '{category}' (Level-5-shaped per GOVERNANCE.md's own definition), "
               f"no metadata contradicting this, not referenced by current-orientation docs",
               dest)

    if name.startswith("BANK_OF_CANADA_"):
        return ("HIGH_CONFIDENCE_HISTORICAL",
               "engagement-specific filename prefix (Bank of Canada), no metadata, filename "
               "category gives no independent content-shape signal but the prefix itself is a "
               "reliable engagement marker for this corpus (14 such files, none architecture/"
               "specification-shaped per Phase 1's audit)",
               "docs/archive/engagements/bank-of-canada/")

    return ("NEEDS_REVIEW", f"no metadata table, filename category '{category}' gives no signal", None)


def build_authority_map() -> dict:
    inventory = build_inventory()
    ref_counts, referrers = _build_reference_index()

    entries = []
    for e in inventory["documents"]:
        name = e["path"]
        classification, basis, destination = _classify(e, ref_counts.get(name, 0), referrers.get(name, set()))
        entries.append({
            "path": name,
            "bytes": e["bytes"],
            "declared_authority": e["declared_authority_level"],
            "declared_status": e["declared_status"],
            "filename_category": e["category"],
            "git_last_modified": _git_last_modified(name),
            "inbound_reference_count": ref_counts.get(name, 0),
            "referenced_by_current_docs": sorted(referrers.get(name, set()) & set(_CURRENT_DOC_REFERRERS)),
            "classification": classification,
            "classification_basis": basis,
            "proposed_destination": destination,
        })

    summary = {}
    for e in entries:
        summary[e["classification"]] = summary.get(e["classification"], 0) + 1

    return {
        "schema_version": "1.0",
        "generated_by": "scripts/generate_root_doc_inventory.py (build_authority_map)",
        "classification_tiers": ["HIGH_CONFIDENCE_CURRENT", "HIGH_CONFIDENCE_HISTORICAL",
                                "HIGH_CONFIDENCE_PROPOSED", "HIGH_CONFIDENCE_SUPERSEDED",
                                "NEEDS_REVIEW"],
        "classification_method": "deterministic only: self-declared Document Metadata (Authority "
                                 "Level / Status), filename-category pattern, one explicit "
                                 "verified-in-code version chain (Fast Analysis V1-V4), and a "
                                 "repo-wide filename-mention reference count. No LLM summarization "
                                 "or semantic judgment.",
        "total_files": len(entries),
        "classification_summary": summary,
        "documents": entries,
    }


def main():
    inventory = build_inventory()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUT_PATH.relative_to(ROOT)}: {inventory['total_files']} files, "
         f"{inventory['currentness_summary']}")

    authority_map = build_authority_map()
    AUTHORITY_MAP_PATH.write_text(json.dumps(authority_map, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {AUTHORITY_MAP_PATH.relative_to(ROOT)}: {authority_map['total_files']} files, "
         f"{authority_map['classification_summary']}")


if __name__ == "__main__":
    sys.exit(main())
