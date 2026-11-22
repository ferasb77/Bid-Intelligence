"""Final source-grounded review before publication.

Deterministic checks run first (omission ledger, figures, unresolved items
labelled); meaning (modal force, conditions) is judged by the review model. Then an independent critique pass reads the
composed reports against the register and the source. A correction is applied
only when its quote verifies and its figures come from that quote; everything
else is recorded as an unresolved review issue -- never rewritten into a
definitive finding."""
from __future__ import annotations

import re

from engine import schema
from engine.package import SourcePackage
from engine.providers import Analyst, ProviderError, UsageLedger
from engine.verify import locate_quote, normalize, value_issues


SYSTEM = """You are the final quality reviewer of two procurement intelligence reports (FAST snapshot and FULL \
assessment) built from a verified evidence register. Compare the reports with the register entries and their \
verbatim quotes, and with the source excerpts, and report only real defects:
- MISSING_MANDATORY: a mandatory requirement (eligibility, qualification, submission, deadline, required \
document, guarantee, disqualification, evaluation) present in the source or register but absent from the \
reports -- give its verbatim quote and category;
- WRONG_MODALITY, CHANGED_CONDITION, UNSUPPORTED_CONSEQUENCE, WRONG_FIGURE, MISCLASSIFIED: a report statement \
that differs from its source -- give the corrected statement and verbatim quote;
- CONTRADICTORY: dates or instructions that contradict each other without being labelled as a conflict;
- MISLEADING_ANALYSIS: an analysis point stronger than its cited entries;
- DUPLICATION / VERBOSITY: repetition that hampers reading.
Quotes must be verbatim from the source. Do not restyle correct text. Do not recommend bidding decisions."""


def deterministic_checks(composed: dict, entries: list[dict]) -> list[dict]:
    issues = []
    for v in composed["ledger"]["violations"]:
        issues.append({"type": "MISSING_MANDATORY", "entry_ids": [v], "source": "ledger",
                       "description": "material register entry not placed in the required report"})
    for e in entries:
        if e.get("applicability") not in ("CURRENT", "AMBIGUOUS", "DISPUTED", "CONFLICTED"):
            continue
        vi = value_issues(e)
        if vi:
            issues.append({"type": "WRONG_FIGURE", "entry_ids": [e["entry_id"]], "source": "deterministic",
                           "description": "; ".join(vi)})
    # an unresolved conflict is reported once, in the Conflicts / Open Items section (the items
    # labelled "Unresolved conflict"), not inline on body bullets: every conflicted entry must appear there
    conflicted = [e["entry_id"] for e in entries if e.get("applicability") == "CONFLICTED"]
    if conflicted:
        for rep in (composed["fast"], composed["full"]):
            secs = rep["sections"] + [g for s in rep["sections"] for g in s.get("groups", [])]
            listed = {i for sec in secs for it in sec.get("items", [])
                      if "Unresolved conflict" in (it.get("labels") or []) for i in it["entry_ids"]}
            for i in conflicted:
                if i not in listed:
                    issues.append({"type": "CONTRADICTORY", "entry_ids": [i], "source": "deterministic",
                                   "description": f"conflicted provision missing from the {rep['kind']} "
                                                  "Conflicts / Open Items section"})
    issues += _brief_checks(composed["fast"].get("brief"), entries)
    return issues


# a raw register entry id (E001, E012R, ...) left in published text
_RAW_ID = re.compile(r"(?<![\w-])E\d{2,}R?(?![\w-])")


def _brief_checks(brief: dict | None, entries: list[dict]) -> list[dict]:
    """Every bullet of the synthesized FAST brief cites at least one reportable register entry, carries a
    compact citation, and shows no raw entry id; the same holds for the Decision Header values."""
    if not brief:
        return []
    live = {e["entry_id"] for e in entries
            if e.get("applicability") in ("CURRENT", "AMBIGUOUS", "DISPUTED", "CONFLICTED")}
    issues = []
    for sec in brief.get("sections") or []:
        for g in sec.get("groups") or []:
            for it in g.get("items") or []:
                ids = it.get("entry_ids") or []
                bad = [i for i in ids if i not in live]
                if not ids or bad or not it.get("cite"):
                    issues.append({"type": "OTHER", "entry_ids": ids, "source": "fast_brief",
                                   "description": f"FAST brief bullet in '{sec.get('title')}' is not grounded in "
                                                  "reportable register entries" + (f" ({', '.join(bad)})" if bad else "")})
                if _RAW_ID.search(it.get("text") or ""):
                    issues.append({"type": "OTHER", "entry_ids": ids, "source": "fast_brief",
                                   "description": f"FAST brief bullet in '{sec.get('title')}' shows a raw register "
                                                  "entry id"})
    for label, value in brief.get("header") or []:
        if _RAW_ID.search(str(value)):
            issues.append({"type": "OTHER", "entry_ids": [], "source": "fast_brief",
                           "description": f"FAST Decision Header '{label}' shows a raw register entry id"})
    return issues


def _report_text(composed: dict) -> str:
    out = []
    for rep in (composed["fast"], composed["full"]):
        out.append(f"##### {rep['kind']} — {rep['title']}")
        out += [f"[summary] {s}" for s in rep.get("summary") or []]
        for sec in rep["sections"]:
            out.append(f"## {sec['title']}")
            for g in sec.get("groups", [{"title": "", "items": sec.get("items", [])}]):
                for it in g.get("items", []):
                    out.append(f"- ({', '.join(it['entry_ids'])}) {it['text']}")
            for p in sec.get("analysis", []) or []:
                out.append(f"- [analysis {', '.join(p['entry_ids'])}] {p['heading']}: {p['analysis']}")
            # the FULL checklist (Section 8) is the only place the required documents are listed
            dr = sec.get("decision_reference") or {}
            for it in (dr.get("checklist") or []) + (dr.get("documents") or []):
                out.append(f"- ({', '.join(it['entry_ids'])}) {it['text']}")
    return "\n".join(out)


def model_review(reviewer: Analyst, package: SourcePackage, composed: dict, entries: list[dict],
                 ledger: UsageLedger, excerpt_chars: int = 120000) -> dict:
    reg = "\n".join(f"{e['entry_id']} | {e.get('document')} {e.get('page')} | {e.get('category')} | "
                    f"{e.get('modality')} | {e.get('applicability')} | {e.get('statement')} || \"{(e.get('quote') or '')[:400]}\""
                    for e in entries if not str(e.get("applicability")).startswith("EXCLUDED"))
    src, n = [], 0
    for loc in package.locations:   # source text, in order, as far as the budget allows
        piece = f"=== {loc.ref()} ===\n{loc.text}"
        if n + len(piece) > excerpt_chars:
            src.append("(source text truncated for the review pass; the register covers the remainder)")
            break
        src.append(piece)
        n += len(piece)
    user = (f"REPORTS:\n{_report_text(composed)}\n\nREGISTER:\n{reg}\n\nSOURCE:\n" + "\n\n".join(src))
    try:
        return reviewer.call_json(SYSTEM, user, schema.REVIEW_OUTPUT, purpose="final_review", ledger=ledger,
                                  data_class=package.data_class, max_tokens=24000)
    except ProviderError as exc:
        return {"issues": [], "error": str(exc)[:300]}


def apply_corrections(package: SourcePackage, entries: list[dict], issues: list[dict],
                      analysis: dict | None = None) -> dict:
    """Applies evidence-backed corrections in place; returns {"applied", "unresolved", "added"}.
    An analysis point the reviewer finds stronger than its evidence is withdrawn
    (removing interpretation is always safe; strengthening never happens here)."""
    by_id = {e["entry_id"]: e for e in entries}
    applied, unresolved, added = [], [], []
    for iss in issues:
        t = iss.get("type")
        quote = (iss.get("quote") or "").strip()
        fix = (iss.get("corrected_statement") or "").strip()
        ids = [i for i in iss.get("entry_ids") or [] if i in by_id]
        if t == "MISLEADING_ANALYSIS" and analysis and analysis.get("points"):
            pts = analysis["points"]
            best = max(len(set(p.get("entry_ids") or []) & set(ids)) for p in pts)
            hit = [p for p in pts if best and len(set(p.get("entry_ids") or []) & set(ids)) == best]
            if hit:
                for p in hit:
                    pts.remove(p)
                    analysis.setdefault("rejected", []).append({"element": "point", "text": p.get("analysis"),
                                                                "reason": "review: " + (iss.get("description") or "")[:200]})
                applied.append(dict(iss, resolution=f"analysis point withdrawn ({len(hit)})"))
                continue
        if t in ("DUPLICATION", "VERBOSITY"):
            unresolved.append(dict(iss, resolution="presentation note"))
            continue
        if t == "MISSING_MANDATORY" and not ids and quote:
            loc = locate_quote(package, quote)
            if loc["status"] in ("VERIFIED", "RELOCATED") and fix and not value_issues(
                    {"statement": fix, "quote": quote}):
                l2 = package.location(loc["loc_id"])
                eid = f"E{len(entries) + len(added) + 1:03d}R"
                new = {"entry_id": eid, "category": iss.get("category") or "OTHER", "statement": fix,
                       "quote": quote, "document": l2.doc, "page": l2.label, "modality": iss.get("modality") or "IS",
                       "conditions": [], "exceptions": [], "values": [], "consequence": "", "relations": [],
                       "uncertainty": "", "party": "", "action": "", "section": "",
                       "status": "REVIEW_ADDED", "materiality": "CRITICAL", "sources": [], "partners": [],
                       "analysts": ["review"], "differences": [], "interpretations": {}, "adjudication": None,
                       "applicability": "CURRENT", "relationships": [],
                       "verification": {"status": "VERIFIED", "quote_status": loc["status"], "loc_id": loc["loc_id"],
                                        "span": list(loc["span"]), "issues": []}}
                added.append(new)
                continue
            unresolved.append(dict(iss, resolution="missing provision could not be verified in the source"))
            continue
        if fix and quote and len(ids) == 1:
            e = by_id[ids[0]]
            loc = locate_quote(package, quote, e.get("document") or "", e.get("page") or "")
            if loc["status"] in ("VERIFIED", "RELOCATED") and not value_issues({"statement": fix, "quote": quote}):
                e.setdefault("review_history", []).append({"before": e.get("statement"), "issue": t})
                e["statement"], e["quote"] = fix, quote
                if iss.get("modality"):
                    e["modality"] = iss["modality"]
                e["verification"] = dict(e.get("verification") or {}, status="VERIFIED", quote_status=loc["status"],
                                         loc_id=loc["loc_id"], span=list(loc["span"]), issues=[])
                applied.append(dict(iss, resolution="corrected"))
                continue
        unresolved.append(dict(iss, resolution="no verifiable correction"))
    entries.extend(added)
    return {"applied": applied, "unresolved": unresolved, "added": [a["entry_id"] for a in added]}

