"""
components/check_report_model.py -- CHECK-2D: the deterministic report model
behind the concise Proposal Assurance Report.

PURE. No Streamlit, no database, no PDF library, no model/provider client and
no import of check_coverage.py / check_run_service.py. It reuses the pure
CHECK-2C view helpers (components/check_workspace_view.py) and turns what the
durable CHECK run already persisted into structured report content:

    durable CHECK result (persisted adjudications + bounded evidence index)
            |
    build_report_model()   <- this module: selection, ordering, citations
            |
    check_assurance_report.render_pdf()   <- reportlab renderer

Nothing here writes prose about the proposal. Every sentence in the model is
either persisted CHECK data (buyer wording, element lists, evidence
summaries, review reasons, buyer weights, locators), a count of persisted
data, or one of the fixed explanatory texts defined as constants below.
There is no score, percentage, readiness figure, predicted evaluator mark or
win probability anywhere in the model.

Attention ordering (ATTENTION_CLASSES) is explainable from buyer metadata
and status only -- no hidden risk or severity score.
"""
from __future__ import annotations

import hashlib
import json

from components import check_review_text as crt
from components import check_workspace_view as cwv

REPORT_MODEL_VERSION = "check-2d-report-1"

ADDRESSED, PARTIAL, NOT_ADDRESSED = cwv.ADDRESSED, cwv.PARTIAL, cwv.NOT_ADDRESSED
NOT_VERIFIABLE, HUMAN_REVIEW, NOT_APPLICABLE = cwv.NOT_VERIFIABLE, cwv.HUMAN_REVIEW, cwv.NOT_APPLICABLE
ATTENTION_STATUSES = (PARTIAL, HUMAN_REVIEW, NOT_VERIFIABLE, NOT_ADDRESSED)

RUN_COMPLETE, RUN_PARTIAL = cwv.RUN_COMPLETE, cwv.RUN_PARTIAL
EXPORTABLE_RUN_STATUSES = (RUN_COMPLETE, RUN_PARTIAL)

REPORT_TITLE = "Proposal Assurance Report"
PARTIAL_REPORT_TITLE = "Partial Proposal Assurance Report"

#: Report status labels (text, never colour alone).
STATUS_LABEL = {
    ADDRESSED: "Addressed", PARTIAL: "Partially addressed", NOT_ADDRESSED: "Not addressed",
    NOT_VERIFIABLE: "Not verifiable from the submitted files", HUMAN_REVIEW: "Human review required",
    NOT_APPLICABLE: "Non-submission / informational",
}
#: Compact status tag for tables.
STATUS_TAG = {
    ADDRESSED: "ADDRESSED", PARTIAL: "PARTIALLY ADDRESSED", NOT_ADDRESSED: "NOT ADDRESSED",
    NOT_VERIFIABLE: "NOT VERIFIABLE FROM FILES", HUMAN_REVIEW: "HUMAN REVIEW REQUIRED",
    NOT_APPLICABLE: "NON-SUBMISSION",
}
STATUS_DEFINITION = {
    ADDRESSED: "The submitted files demonstrate every element CHECK recorded for what the buyer asked.",
    PARTIAL: ("Some recorded elements of what the buyer asked are demonstrated in the submitted files; "
              "others are not, or only partly."),
    NOT_ADDRESSED: "The whole submitted package was searched and no response to the buyer object was found.",
    NOT_VERIFIABLE: ("The submitted files cannot show whether this is met (for example, it is answered in the "
                     "buyer's portal, or it is a property a completed form does not disclose). This is a limit "
                     "of file-based assurance, not a gap in the proposal."),
    HUMAN_REVIEW: ("CHECK could not safely make a definitive judgment. A person should confirm it. This is not "
                   "a confirmed weakness."),
    NOT_APPLICABLE: ("Not a proposal obligation: buyer process, post-award obligation, informational content "
                     "or something deemed by the act of submitting."),
}

#: Deterministic attention classes (lower first). Within a class: higher
#: buyer-stated weight, then a stated minimum threshold, then persisted order.
ATTENTION_CLASSES = (
    ("criterion", PARTIAL), ("criterion", HUMAN_REVIEW), ("criterion", NOT_VERIFIABLE),
    ("criterion", NOT_ADDRESSED),
    ("mandatory", PARTIAL), ("mandatory", HUMAN_REVIEW), ("mandatory", NOT_VERIFIABLE),
    ("mandatory", NOT_ADDRESSED),
    ("other", PARTIAL), ("other", HUMAN_REVIEW), ("other", NOT_VERIFIABLE), ("other", NOT_ADDRESSED),
)
ATTENTION_ORDERING_TEXT = (
    "Findings are ordered by buyer facts and CHECK status only: evaluation criteria first (partially addressed, "
    "then human review, then not verifiable, then not addressed), then mandatory or submission-wide "
    "requirements in the same status order, then other requirements. Within each group: the higher "
    "buyer-stated weight first, then a stated minimum threshold, then the buyer's own order. No hidden risk "
    "or severity score is used.")

#: CHECK-2B replay provenance segments persisted inside a review reason. They
#: describe how the run was recorded, not why a finding has its status, so
#: they are not repeated in a client report (the persisted row is unchanged).
#: CHECK-2D.1: defined once in components.check_review_text, which
#: cwv.review_notes already applies (with routing-notation normalization);
#: kept here as a second guard.
NON_SUBSTANTIVE_REASON_MARKERS = (crt.COMMISSIONING_PLACEHOLDER_MARKER,)
_REVIEW_ELEMENT_PREFIX = "element needs review:"

MAX_ELEMENT_CITES = 1
MAX_FINDING_EVIDENCE = 3
MAX_ROW_CITES = 2
EXPECTATION_DETAIL = 400
EXPECTATION_ROW = 130
ELEMENT_CHARS = 230
REASON_CHARS = 320
CITATION_TEXT = 130

METHODOLOGY = (
    ("What CHECK does",
     "CHECK compares the submitted proposal files with the canonical buyer requirements and evaluation "
     "criteria extracted from the buyer's procurement documents. Every conclusion is tied to the buyer "
     "source it came from and to the bidder evidence (file, page, section, sheet, cell, row or form field) "
     "that supports it. This report is rendered directly from the saved CHECK run; producing it does not "
     "re-run the assessment and uses no AI-written summary."),
    ("Buyer weights",
     "Weights and minimum thresholds are the buyer's own published values, shown as buyer metadata. Where "
     "buyer sources state differing weights, both are shown and CHECK does not choose between them."),
    ("What CHECK does not do",
     "CHECK does not predict how an evaluator will score the proposal, does not produce an overall or "
     "compliance percentage, and does not estimate the likelihood of winning. It reports what the submitted "
     "files do and do not demonstrate."),
    ("Non-submission items",
     "Buyer process steps, post-award obligations, informational content and items deemed by the act of "
     "submitting are listed separately and are never counted as proposal deficiencies."),
)


class ReportNotExportableError(Exception):
    """The CHECK run is not in an exportable state (COMPLETE or PARTIAL)."""


# ═══════════════════════════════════════════════════════════════════════
# Small pure helpers
# ═══════════════════════════════════════════════════════════════════════

def clip(text, n: int) -> str:
    return cwv.clip(text, n)


def weight_text(a: dict) -> str | None:
    w = cwv.stated_weights(a)
    return " / ".join(w) if w else None


def object_name(a: dict) -> str:
    if cwv.is_criterion(a) and a.get("buyer_label"):
        return str(a["buyer_label"])
    return str(a.get("buyer_object_id"))


def object_group(a: dict) -> str:
    if cwv.is_criterion(a):
        return "criterion"
    return "mandatory" if cwv.is_mandatory(a) else "other"


def attention_class(a: dict) -> int:
    try:
        return ATTENTION_CLASSES.index((object_group(a), a.get("status")))
    except ValueError:
        return len(ATTENTION_CLASSES)


def attention_key(a: dict) -> tuple:
    w = cwv.max_weight(a)
    return (attention_class(a), -(w if w is not None else -1.0), 0 if a.get("buyer_threshold") else 1,
            a.get("_ordinal", 0))


def substantive_reasons(a: dict) -> list:
    """The client-safe review / ambiguity reason segments (the shared
    components.check_review_text projection via cwv.review_notes: persisted
    text minus the CHECK-2B.1 commissioning placeholder, internal routing
    notation in plain language)."""
    out = []
    for seg in cwv.review_notes(a):
        body = seg
        if body.startswith("[") and "]" in body:
            body = body[body.index("]") + 1:].strip()
        if any(m in body for m in NON_SUBSTANTIVE_REASON_MARKERS):
            continue
        out.append(seg)
    return out


def reviewer_checks(a: dict) -> list:
    """What a reviewer should confirm -- ONLY items named by persisted review
    metadata: an 'element needs review: X' segment, or an element recorded
    as unverifiable / needing review on this human-review finding."""
    out = []
    for seg in cwv.review_notes(a):
        low = seg.lower()
        if _REVIEW_ELEMENT_PREFIX in low:
            item = seg[low.index(_REVIEW_ELEMENT_PREFIX) + len(_REVIEW_ELEMENT_PREFIX):].strip()
            if item and item not in out:
                out.append(item)
    for el in a.get("unverifiable_elements") or []:
        text = str((el or {}).get("element") or "").strip()
        if text and text not in out:
            out.append(text)
    return [clip(x, ELEMENT_CHARS) for x in out]


def buyer_sources(a: dict, limit: int = 2) -> list:
    prov = a.get("source_provenance") or {}
    out = []
    for r in (prov.get("source_refs") or [])[:limit]:
        out.append({"document": r.get("source_doc"), "section": r.get("section"), "page": r.get("page"),
                    "sheet": r.get("sheet"), "excerpt": clip(r.get("excerpt"), 220) if r.get("excerpt") else None})
    if not out:
        out = [{"document": d, "section": None, "page": None, "sheet": None, "excerpt": None}
               for d in (prov.get("source_docs") or [])[:limit]]
    return out


def source_line(src: dict) -> str:
    parts = [src.get("document") or "Buyer source"]
    if src.get("section"):
        parts.append(f"section {src['section']}")
    if src.get("page") is not None:
        parts.append(f"p. {src['page']}")
    if src.get("sheet"):
        parts.append(f"sheet {src['sheet']}")
    return ", ".join(str(p) for p in parts)


# ═══════════════════════════════════════════════════════════════════════
# Evidence citations (E1..En, assigned in first-use order)
# ═══════════════════════════════════════════════════════════════════════

class Citations:
    """Deterministic report citation ids. Only evidence ids that resolve in
    THIS bid's evidence index can be cited; anything else is counted as
    unresolved and never shown or fabricated."""

    def __init__(self, index: dict):
        self.index = index or {}
        self.refs: dict = {}
        self.unresolved: set = set()

    def cite(self, eid: str) -> str | None:
        if eid not in self.index:
            self.unresolved.add(eid)
            return None
        if eid not in self.refs:
            self.refs[eid] = f"E{len(self.refs) + 1}"
        return self.refs[eid]

    def cite_many(self, ids, limit: int) -> tuple:
        """(refs for the first `limit` resolvable ids, count of further resolvable ids)."""
        resolvable = [e for e in dict.fromkeys(ids or []) if e in self.index]
        for e in ids or []:
            if e not in self.index:
                self.unresolved.add(e)
        shown = [self.cite(e) for e in resolvable[:limit]]
        return shown, max(0, len(resolvable) - limit)

    def label(self, ref_or_eid: str) -> str:
        eid = next((e for e, r in self.refs.items() if r == ref_or_eid), ref_or_eid)
        ev = self.index.get(eid)
        return citation_label(ev) if ev else ref_or_eid

    def appendix(self) -> list:
        rows = []
        for eid, ref in self.refs.items():
            ev = self.index[eid]
            if ev.get("value") is not None and ev.get("field_label"):
                label = str(ev["field_label"]).strip().rstrip(":").strip()
                text = f"{clip(label, 90)}: {clip(ev['value'], 120)}"
            else:
                text = clip(tidy_excerpt(ev.get("excerpt")), CITATION_TEXT)
            rows.append({"ref": ref, "evidence_id": eid, "filename": ev.get("filename"),
                         "role_label": ev.get("role_label"), "kind_label": ev.get("kind_label"),
                         "location": citation_location(ev), "short_location": citation_location(ev, short=True),
                         "text": text})
        return rows


def tidy_excerpt(text) -> str:
    """Collapse ASCII table rules ('+-----+', '|====|') in an excerpt to a
    single separator. Presentation only: no word is added or removed."""
    import re
    body = re.sub(r"[+\-=_|]{4,}", " ", str(text or ""))
    body = re.sub(r"\|(?:\s*[|^]\s*)+", "|", body)      # stacked cell borders / arrow stubs
    return re.sub(r"\s+", " ", body).strip()


def citation_location(ev: dict, short: bool = False) -> str:
    """'p. 5, section PART 4 ...' / 'Sheet Price Form, cell D6' -- only locator
    detail the registry actually holds; never fabricated. `short` drops the
    table / field detail (kept in the appendix)."""
    out = []
    for part in ev.get("location") or []:
        p = str(part)
        if short and (p.startswith("Table ") or p.startswith("Field ")):
            continue
        if p.startswith("Page "):
            p = "p. " + p[5:]
        elif p.startswith("Section "):
            p = "section " + p[8:]
        elif p.startswith("Cell ") or p.startswith("Row ") or p.startswith("Table ") or p.startswith("Field "):
            p = p[0].lower() + p[1:]
        out.append(p)
    return ", ".join(out) or "location not recorded"


def citation_label(ev: dict) -> str:
    return f"{ev.get('role_label') or 'Submitted file'}, {citation_location(ev, short=True)}"


# ═══════════════════════════════════════════════════════════════════════
# Attention findings
# ═══════════════════════════════════════════════════════════════════════

def _element_rows(elements, cites: Citations, show_coverage: bool) -> list:
    rows = []
    for el in elements or []:
        el = el or {}
        refs, more = cites.cite_many(el.get("evidence_ids") or [], MAX_ELEMENT_CITES)
        cov = el.get("coverage")
        rows.append({"element": clip(el.get("element"), ELEMENT_CHARS),
                     "coverage": cov,
                     "coverage_label": (cwv.ELEMENT_COVERAGE_LABEL.get(cov, cov) if show_coverage and cov else None),
                     "note": clip(el.get("note"), 200) if el.get("note") else None,
                     "cites": refs, "more_cites": more})
    return rows


def _unverifiable_reasons(a: dict) -> list:
    """Why verification is unavailable: the persisted per-element notes when
    they exist (the most specific reason), else the persisted verdict-level
    reasons. Verbatim, de-duplicated, bounded."""
    out = []
    for el in a.get("unverifiable_elements") or []:
        note = str((el or {}).get("note") or "").strip()
        if note and note not in out:
            out.append(note)
    if not out:
        out = substantive_reasons(a)
    return [clip(x, REASON_CHARS) for x in out]


def _units(a: dict, by_id: dict) -> list:
    """The buyer object(s) whose persisted element lists carry the detail of
    `a`. A criterion derived from linked requirements points at those linked
    requirements that themselves need attention, so the same elements are
    shown once, not repeated per criterion."""
    if cwv.is_criterion(a) and a.get("linked_requirement_ids"):
        units = [rid for rid in a["linked_requirement_ids"]
                 if rid in by_id and by_id[rid].get("status") in ATTENTION_STATUSES]
        if units:
            return units
    return [a.get("buyer_object_id")]


def _applies_row(a: dict) -> dict:
    return {"object_id": a.get("buyer_object_id"), "name": object_name(a), "is_criterion": cwv.is_criterion(a),
            "weight": weight_text(a), "weight_variants_differ": len(cwv.stated_weights(a)) > 1,
            "threshold": a.get("buyer_threshold"), "status": a.get("status"),
            "status_label": STATUS_LABEL.get(a.get("status"), a.get("status")),
            "category": a.get("buyer_category"), "applicability": a.get("applicability")}


def attention_findings(adjs: list, cites: Citations) -> list:
    by_id = {a.get("buyer_object_id"): a for a in adjs}
    groups: dict = {}
    order: list = []
    for a in adjs:
        if a.get("status") not in ATTENTION_STATUSES:
            continue
        for unit in _units(a, by_id):
            if unit not in groups:
                groups[unit] = []
                order.append(unit)
            if all(m.get("buyer_object_id") != a.get("buyer_object_id") for m in groups[unit]):
                groups[unit].append(a)
    for unit in order:  # the subject itself always applies when it needs attention
        subj = by_id.get(unit)
        needs = subj is not None and subj.get("status") in ATTENTION_STATUSES
        if needs and all(m.get("buyer_object_id") != unit for m in groups[unit]):
            groups[unit].append(subj)

    keyed = []
    for unit in order:
        members = sorted(groups[unit], key=attention_key)
        keyed.append((min(attention_key(m) for m in members), unit, members))
    keyed.sort(key=lambda x: x[0])

    out = []
    for n, (key, unit, members) in enumerate(keyed, 1):
        subj = by_id.get(unit) or members[0]
        ref = f"A{n}"
        crits = [m for m in members if cwv.is_criterion(m)]
        title_base = subj.get("buyer_label") if cwv.is_criterion(subj) else cwv.concise_expectation(subj, 110)
        title = f"{unit} · {title_base}" if not cwv.is_criterion(subj) else str(title_base)
        if not str(title_base or "").strip():
            title = f"{unit} · (the canonical buyer object carries no wording)"
        demonstrated = _element_rows(subj.get("addressed_elements"), cites, False)
        not_demonstrated = _element_rows(subj.get("missing_elements"), cites, True)
        unverifiable = _element_rows(subj.get("unverifiable_elements"), cites, False)
        ev_refs, ev_more = cites.cite_many(subj.get("evidence_ids") or [], MAX_FINDING_EVIDENCE)
        weight_notes = [f"Buyer sources state differing weights for {object_name(m)}: {weight_text(m)}. "
                        "CHECK does not choose between them." for m in crits if len(cwv.stated_weights(m)) > 1]
        out.append({
            "ref": ref, "unit_id": unit, "title": title, "status": subj.get("status"),
            "status_label": STATUS_LABEL.get(subj.get("status"), subj.get("status")),
            "status_tag": STATUS_TAG.get(subj.get("status"), subj.get("status")),
            "class_rank": key[0], "class": ATTENTION_CLASSES[key[0]] if key[0] < len(ATTENTION_CLASSES) else None,
            "applies_to": [_applies_row(m) for m in members],
            "expectation": clip(cwv.concise_expectation(subj, EXPECTATION_DETAIL), EXPECTATION_DETAIL),
            "buyer_sources": buyer_sources(subj), "scope": subj.get("assurance_scope"),
            "scope_label": cwv.SCOPE_LABEL.get(subj.get("assurance_scope"), subj.get("assurance_scope")),
            "evidence_summary": clip(subj.get("evidence_summary"), 300) if subj.get("evidence_summary") else None,
            "demonstrated": demonstrated, "not_demonstrated": not_demonstrated, "unverifiable": unverifiable,
            "reasons": [clip(r, REASON_CHARS) for r in substantive_reasons(subj)],
            "unverifiable_reasons": _unverifiable_reasons(subj),
            "reviewer_checks": reviewer_checks(subj) if subj.get("status") == HUMAN_REVIEW else [],
            "evidence": ev_refs, "more_evidence": ev_more, "weight_notes": weight_notes,
            "method": cwv.METHOD_LABEL.get(subj.get("deterministic_or_model"), subj.get("deterministic_or_model")),
        })
    return out


# ═══════════════════════════════════════════════════════════════════════
# Criteria overview / mandatory evidence / non-submission
# ═══════════════════════════════════════════════════════════════════════

def _criterion_conclusion(a: dict, finding_refs: list, cites: Citations) -> tuple:
    """(conclusion text, evidence refs) -- counts and persisted text only."""
    st = a.get("status")
    g = cwv.element_groups(a)
    n_d, n_m = len(g["demonstrated"]), len(g["not_demonstrated"])
    see = f" See {', '.join(finding_refs)}." if finding_refs else ""
    if st == ADDRESSED:
        refs, _ = cites.cite_many(a.get("evidence_ids") or [], MAX_ROW_CITES)
        text = f"{n_d} of {n_d} recorded element{'s' if n_d != 1 else ''} demonstrated."
        if a.get("evidence_summary"):
            text += " " + clip(a["evidence_summary"], 185)
        return text, refs
    if st == PARTIAL:
        return (f"{n_d} of {n_d + n_m} recorded elements demonstrated; {n_m} not or only partly "
                f"demonstrated.{see}"), []
    if st == NOT_ADDRESSED:
        return f"No response found in the submitted files.{see}", []
    reasons = _unverifiable_reasons(a) if st == NOT_VERIFIABLE else substantive_reasons(a)
    lead = "Not verifiable from the submitted files" if st == NOT_VERIFIABLE else "Human review required"
    first = _strip_object_prefix(reasons[0]) if reasons else ""
    if first == crt.NEUTRAL_REVIEW_REASON:
        first = ""                                   # the lead already says it
    body = f": {clip(first, 130)}" if first else "."
    return f"{lead}{body}{see}", []


def _strip_object_prefix(text: str) -> str:
    """'[REQ-45] reason' -> 'reason' (a derived criterion's reason carries the
    linked requirement id, which the row already references)."""
    body = str(text or "").strip()
    if body.startswith("[") and "]" in body:
        body = body[body.index("]") + 1:].strip()
    return body


def criteria_rows(adjs: list, findings: list, cites: Citations) -> list:
    refs_by_obj: dict = {}
    for f in findings:
        for m in f["applies_to"]:
            refs_by_obj.setdefault(m["object_id"], []).append(f["ref"])
    rows = []
    for a in cwv.criteria(adjs):
        refs = refs_by_obj.get(a.get("buyer_object_id"), [])
        conclusion, ev = _criterion_conclusion(a, refs, cites)
        expectation = cwv.concise_expectation(a, EXPECTATION_ROW)
        if expectation.strip() == str(a.get("buyer_label") or "").strip():
            # The criterion wording is only its label: show the buyer's own
            # source excerpt instead (verbatim, bounded), when one exists.
            src = next((s for s in buyer_sources(a) if s.get("excerpt")), None)
            if src:
                expectation = clip(src["excerpt"], EXPECTATION_ROW)
        rows.append({"object_id": a.get("buyer_object_id"), "name": object_name(a), "weight": weight_text(a),
                     "weight_variants_differ": len(cwv.stated_weights(a)) > 1,
                     "threshold": a.get("buyer_threshold"), "status": a.get("status"),
                     "status_tag": STATUS_TAG.get(a.get("status"), a.get("status")),
                     "expectation": expectation,
                     "linked_requirements": list(a.get("linked_requirement_ids") or []),
                     "conclusion": conclusion, "evidence": ev, "finding_refs": refs})
    return rows


def mandatory_addressed_rows(adjs: list, cites: Citations) -> list:
    """ADDRESSED mandatory / submission-wide requirements, in buyer order,
    with where the bidder responded (bounded citations)."""
    rows = []
    for a in adjs:
        if cwv.is_criterion(a) or a.get("status") != ADDRESSED or not cwv.is_mandatory(a):
            continue
        refs, more = cites.cite_many(a.get("evidence_ids") or [], MAX_ROW_CITES)
        n_unv = len(a.get("unverifiable_elements") or [])
        summary = clip(a.get("evidence_summary"), 190) if a.get("evidence_summary") else None
        if not summary and a.get("addressed_elements"):
            names = [str((el or {}).get("element") or "").strip() for el in a["addressed_elements"]]
            summary = clip("Demonstrated: " + "; ".join(n for n in names if n), 190)
        rows.append({"object_id": a.get("buyer_object_id"),
                     "expectation": cwv.concise_expectation(a, EXPECTATION_ROW),
                     "summary": summary,
                     "unverifiable_elements": n_unv,
                     "roles": [cwv.ROLE_LABEL.get(r, r) for r in a.get("expected_evidence_roles") or []],
                     "applicability": a.get("applicability"), "evidence": refs, "more_evidence": more})
    return rows


def non_submission_groups(adjs: list) -> list:
    groups: dict = {}
    for a in cwv.non_submission(adjs):
        groups.setdefault(a.get("assurance_scope"), []).append(a.get("buyer_object_id"))
    order = ("BUYER_PROCESS", "POST_AWARD_OBLIGATION", "INFORMATIONAL", "DEEMED_BY_SUBMISSION")
    keys = [k for k in order if k in groups] + sorted(k for k in groups if k not in order)
    return [{"scope": k, "scope_label": cwv.SCOPE_LABEL.get(k, k), "count": len(groups[k]), "ids": groups[k]}
            for k in keys]


# ═══════════════════════════════════════════════════════════════════════
# The model
# ═══════════════════════════════════════════════════════════════════════

def _fmt_date(value) -> str | None:
    if not value:
        return None
    from datetime import datetime
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).strftime("%B %d, %Y").replace(" 0", " ")
    except ValueError:
        return str(value)[:10]


def identity(bid: dict | None) -> dict:
    bid = bid or {}
    return {"buyer": bid.get("client") or None, "title": bid.get("title") or None,
            "rfp_id": bid.get("file_number") or None, "bid_id": bid.get("id")}


def build_report_model(*, run: dict, adjudications: list, evidence_index: dict, files: list | None = None,
                       bid: dict | None = None, partial_lines: list | None = None,
                       digest_verified: bool = True) -> dict:
    """Pure: the persisted CHECK run -> complete, ordered report content.

    `run` is the durable CHECK run row (status read from persistence),
    `adjudications` the persisted adjudications as dicts in persisted order
    (components.check_workspace_view.adjudications(result)), `evidence_index`
    {evidence_id: evidence_view} built from THIS bid's registry."""
    run = run or {}
    run_status = run.get("status")
    if run_status not in EXPORTABLE_RUN_STATUSES:
        raise ReportNotExportableError(f"CHECK run status {run_status!r} is not exportable")
    adjs = [dict(a, _ordinal=a.get("_ordinal", i)) for i, a in enumerate(adjudications or [])]
    cites = Citations(evidence_index)

    ov = cwv.overview(adjs)
    # Citation ids follow report order: criteria overview, attention findings,
    # then the mandatory evidence index. Finding refs (A#) do not depend on
    # citations, so a first pass fixes them for the criteria table.
    crit_rows = criteria_rows(adjs, attention_findings(adjs, Citations(evidence_index)), cites)
    findings = attention_findings(adjs, cites)
    mand_rows = mandatory_addressed_rows(adjs, cites)
    is_partial = run_status == RUN_PARTIAL
    files = list(files or [])
    return {
        "version": REPORT_MODEL_VERSION,
        "title": PARTIAL_REPORT_TITLE if is_partial else REPORT_TITLE,
        "is_partial": is_partial,
        "partial_lines": list(partial_lines or []) if is_partial else [],
        "identity": identity(bid),
        "run": {"run_id": run.get("id"), "status": run_status,
                "status_label": "Partial" if is_partial else "Complete",
                "assessed_date": _fmt_date(run.get("completed_at")), "completed_at": run.get("completed_at"),
                "source_analysis_run_id": run.get("source_analysis_run_id"),
                "package_snapshot_id": run.get("source_package_snapshot_id"),
                "engine_version": run.get("engine_version"),
                "fingerprint": (run.get("input_fingerprint") or "")[:12] or None,
                "digest_verified": bool(digest_verified)},
        "overview": {"counts": [{"status": s, "label": STATUS_LABEL[s], "tag": STATUS_TAG[s], "count": n,
                                 "definition": STATUS_DEFINITION[s]} for s, n in ov["counts"]],
                     "non_submission": ov["excluded"], "total": ov["total"], "criteria": ov["criteria"],
                     "requirements": ov["requirements"]},
        "criteria": crit_rows,
        "attention": findings,
        "attention_ordering": ATTENTION_ORDERING_TEXT,
        "partials": [f["ref"] for f in findings if f["status"] == PARTIAL],
        "human_review": [f["ref"] for f in findings if f["status"] == HUMAN_REVIEW],
        "not_verifiable": [f["ref"] for f in findings if f["status"] == NOT_VERIFIABLE],
        "not_addressed": [f["ref"] for f in findings if f["status"] == NOT_ADDRESSED],
        "mandatory_addressed": mand_rows,
        "non_submission": non_submission_groups(adjs),
        "files": files,
        "citations": cites.appendix(),
        "unresolved_evidence": sorted(cites.unresolved),
        "status_definitions": [{"status": s, "label": STATUS_LABEL[s], "definition": STATUS_DEFINITION[s]}
                               for s in (ADDRESSED, PARTIAL, NOT_ADDRESSED, NOT_VERIFIABLE, HUMAN_REVIEW,
                                         NOT_APPLICABLE)],
        "methodology": [{"heading": h, "text": t} for h, t in METHODOLOGY],
    }


def model_digest(model: dict) -> str:
    """sha256 over the semantic report content (no timestamps, no paths, no
    PDF bytes). The same durable run always yields the same digest."""
    semantic = {k: v for k, v in model.items() if k not in ("generated_at",)}
    return hashlib.sha256(json.dumps(semantic, sort_keys=True, default=str, ensure_ascii=False)
                          .encode("utf-8")).hexdigest()


def report_filename(model: dict) -> str:
    import re
    ident = model.get("identity") or {}
    key = ident.get("rfp_id") or ident.get("title") or (f"Bid_{ident['bid_id']}" if ident.get("bid_id") else "Bid")
    key = re.sub(r"[^A-Za-z0-9._-]+", "_", str(key)).strip("._-")[:80] or "Bid"
    prefix = "Partial_Proposal_Assurance_Report" if model.get("is_partial") else "Proposal_Assurance_Report"
    return f"{prefix}_{key}.pdf"
