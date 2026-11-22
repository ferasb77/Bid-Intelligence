"""FAST (Opportunity Snapshot) and FULL (Bid Opportunity Assessment) composed
from the reconciled register, with an omission ledger that accounts for every
register entry: where it appears, or why it does not.

Document facts are the register's verified statements. Model-written text
(the summary and the specialist analysis) must cite register entries and may
not introduce figures those entries do not contain; anything else is dropped
and recorded."""
from __future__ import annotations

import re
from datetime import date

from engine import schema
from engine.providers import Analyst, ProviderError, UsageLedger
from engine.verify import _EMAIL, STOPWORDS, _numbers, normalize, tokens

REPORTABLE = {"CURRENT", "AMBIGUOUS", "DISPUTED", "CONFLICTED"}
_LABEL = {"AMBIGUOUS": "Ambiguous in the source", "DISPUTED": "Interpretation disputed",
          "CONFLICTED": "Unresolved conflict"}

FAST_SECTIONS = [
    ("Eligibility and Qualification", ["ELIGIBILITY", "QUALIFICATION"]),
    ("Submission Instructions and Deadlines", ["DEADLINE", "SUBMISSION_METHOD", "SUBMISSION_REQUIREMENT"]),
    ("Mandatory Forms and Documents", ["REQUIRED_DOCUMENT"]),
    ("Commercial, Payment and Financial Terms", ["PRICING", "PAYMENT", "GUARANTEE", "FINANCIAL_THRESHOLD"]),
    ("Evaluation and Award", ["EVALUATION"]),
    ("Disqualification and Rejection Risks", ["DISQUALIFICATION"]),
    ("Scope and Principal Deliverables", ["SCOPE", "DELIVERABLE", "DURATION"]),
]
FULL_SECTIONS = [
    ("Opportunity and Delivery Requirements", [
        ("Scope", ["SCOPE"]), ("Deliverables and Activities", ["DELIVERABLE"]),
        ("Duration and Implementation", ["DURATION"]),
        ("Risks, Dependencies and Buyer Responsibilities", ["RISK_DEPENDENCY"])]),
    ("Eligibility and Qualification", [
        ("Eligibility", ["ELIGIBILITY"]), ("Qualifications", ["QUALIFICATION"])]),
    ("Evaluation and Commercial Intelligence", [
        ("Evaluation and Award", ["EVALUATION"]), ("Pricing", ["PRICING"]), ("Payment", ["PAYMENT"]),
        ("Guarantees and Securities", ["GUARANTEE"]), ("Financial Thresholds", ["FINANCIAL_THRESHOLD"]),
        ("Contractual Obligations and Restrictions", ["CONTRACT_TERM"])]),
    ("Submission and Compliance", [
        ("Deadlines and Schedule", ["DEADLINE"]), ("Submission Method", ["SUBMISSION_METHOD"]),
        ("Proposal Requirements", ["SUBMISSION_REQUIREMENT"]), ("Required Documents and Forms", ["REQUIRED_DOCUMENT"]),
        ("Disqualification and Rejection", ["DISQUALIFICATION"]),
        ("Document Precedence", ["DOCUMENT_AUTHORITY"]),
        ("Changes to the Tender and Reserved Rights", ["AMENDMENT"]),
        ("Other Provisions", ["OTHER", "IDENTITY"])]),
]

ANALYSIS_SYSTEM = """You are a senior bid analyst writing for a consulting firm's management. You receive a \
verified evidence register of one procurement package (entry id, category, modal force, statement, status). \
Write:
1. title, buyer, reference: exactly as stated in the entries (cite them); '' if not stated.
2. summary: two to four factual sentences on what is procured, from whom, and the decisive conditions, each \
citing the entries it rests on.
3. points: up to 10 analytical points a bid manager needs that are not obvious from reading each provision \
alone -- consequences that follow directly, dependencies between provisions, timing pressures, compliance \
risks, open questions. Each point cites the entries it rests on and must be no stronger than they are: keep \
conditions, alternatives and approximations; never present a 'will' or 'should' as a 'must'.
Never: recommend bidding or not, estimate win probability, judge attractiveness, invent figures, dates, \
requirements or buyer preferences. Every figure you write must appear in a cited entry."""


def reportable(e: dict) -> bool:
    return e.get("applicability") in REPORTABLE


def _refs(e: dict) -> list[str]:
    return [f"{e.get('document')}, {_page(e)}"]


def _page(e: dict) -> str:
    p = str(e.get("page") or "")
    return f"p. {p}" if p.isdigit() else p


def _same(a: dict, b: dict) -> bool:
    if a.get("category") != b.get("category") or a.get("modality") != b.get("modality"):
        return False
    va = {normalize(v.get("text") or "") for v in a.get("values") or []}
    vb = {normalize(v.get("text") or "") for v in b.get("values") or []}
    if va != vb:
        return False
    ta, tb = set(tokens(a.get("statement"))), set(tokens(b.get("statement")))
    if not (ta and tb) or len(ta & tb) / len(ta | tb) < 0.8:
        return False
    return not _distinct_sources(a, b, ta, tb)


def _distinct_sources(a: dict, b: dict, ta: set[str], tb: set[str]) -> bool:
    """Two different source quotes whose statements differ by a content word that
    one quote contains and the other does not (e.g. one document vs another) are
    different provisions, however similar the rest of the wording."""
    qa, qb = set(tokens(a.get("quote"))), set(tokens(b.get("quote")))
    if not (qa and qb) or qa == qb:
        return False
    return any(t not in STOPWORDS and t in own and t not in other
               for diff, own, other in ((ta - tb, qa, qb), (tb - ta, qb, qa)) for t in diff)


def group_restatements(entries: list[dict]) -> list[list[dict]]:
    """The same provision restated (same category, force and values, near-identical
    wording) is shown once with every reference. Different values never merge."""
    groups: list[list[dict]] = []
    for e in entries:
        g = next((g for g in groups if _same(g[0], e)), None)
        (g.append(e) if g else groups.append([e]))
    return groups


def _item(group: list[dict]) -> dict:
    e = group[0]
    refs: list[str] = []
    for x in group:
        for r in _refs(x):
            if r not in refs:
                refs.append(r)
    # an unresolved conflict is reported once, in the Conflicts / Open Items section,
    # not stamped onto each clause of the candidate cluster in the body sections
    labels = sorted({_LABEL[x["applicability"]] for x in group
                     if x.get("applicability") in _LABEL and x["applicability"] != "CONFLICTED"})
    if any((x.get("verification") or {}).get("ocr_source") for x in group):
        labels.append("From OCR text")
    if e.get("previous"):
        labels.append("Updated")
    if e.get("new_in_update"):
        labels.append("New")
    text = e.get("statement") or ""
    if e.get("previous"):
        text += " (Previously: " + "; ".join(f"{p['statement']} [{p['document']}, {_page(p)}]"
                                             for p in e["previous"]) + ")"
    if e.get("applicability") == "AMBIGUOUS" and e.get("uncertainty"):
        text += f" Unclear: {e['uncertainty']}"
    # verbatim source grounding: the quote the statement was verified against
    quote = e.get("quote") or ""
    if quote and normalize(quote) != normalize(e.get("statement") or ""):
        text += f' Source text: "{" ".join(quote.split())}"'
    return {"text": text, "quote": quote, "refs": refs, "labels": labels, "entry_ids": [x["entry_id"] for x in group],
            "materiality": max((x.get("materiality") for x in group), key=lambda m: {"CRITICAL": 3, "MATERIAL": 2}
                               .get(m, 1))}


_RANK = {"CRITICAL": 3, "MATERIAL": 2, "INFORMATIONAL": 1}


def placement(e: dict, by_id: dict) -> tuple[str, str]:
    """(category, materiality) under which an entry is reported. An amendment
    or clarification that replaced a provision is reported where that provision
    belongs, at least as prominently."""
    cat, mat = e.get("category"), e.get("materiality")
    if cat in ("AMENDMENT", "OTHER", "DOCUMENT_AUTHORITY") and e.get("previous"):
        olds = [by_id[p["entry_id"]] for p in e["previous"] if p.get("entry_id") in by_id]
        if olds:
            cat = olds[0].get("category") or cat
            mat = max([mat] + [o.get("materiality") for o in olds], key=lambda m: _RANK.get(m, 1))
    return cat, mat


def _items_for(entries: list[dict], cats: list[str], *, min_rank: int = 1) -> list[dict]:
    by_id = {e["entry_id"]: e for e in entries}
    pl = {e["entry_id"]: placement(e, by_id) for e in entries}
    sel = [e for e in entries if pl[e["entry_id"]][0] in cats and reportable(e)
           and _RANK.get(pl[e["entry_id"]][1], 1) >= min_rank]
    sel.sort(key=lambda e: (-_RANK.get(pl[e["entry_id"]][1], 1), cats.index(pl[e["entry_id"]][0])))
    return [_item(g) for g in group_restatements(sel)]


# ── model-written text: cited and figure-checked ────────────────────────────

def _cited_ok(text: str, ids: list[str], by_id: dict) -> tuple[bool, str]:
    cited = [by_id[i] for i in ids or [] if i in by_id and reportable(by_id[i])]
    if not cited:
        return False, "cites no reportable register entry"
    basis = " ".join(f"{e.get('statement')} {e.get('quote')}" for e in cited)
    extra = _numbers(text) - _numbers(basis)
    if extra:
        return False, "figures not in the cited entries: " + ", ".join(sorted(extra))
    for m in _EMAIL.findall(text):
        if m.lower() not in normalize(basis):
            return False, f"e-mail {m} not in the cited entries"
    return True, ""


def analysis(writer: Analyst | None, entries: list[dict], ledger: UsageLedger, data_class: str) -> dict:
    """Summary, identity and specialist points. Every element is checked; rejected
    elements are kept in `rejected` with the reason (never published)."""
    out = {"title": "", "buyer": "", "reference": "", "summary": [], "points": [], "rejected": [], "error": None}
    if writer is None:
        out["error"] = "no writer configured"
        return out
    live = [e for e in entries if reportable(e)]
    by_id = {e["entry_id"]: e for e in live}
    user = "EVIDENCE REGISTER:\n" + "\n".join(
        f"{e['entry_id']} | {e.get('category')} | {e.get('modality')} | {e.get('materiality')} | "
        f"{e.get('applicability')} | {e.get('statement')}" for e in live)
    try:
        data = writer.call_json(ANALYSIS_SYSTEM, user, schema.ANALYSIS_OUTPUT, purpose="analysis", ledger=ledger,
                                data_class=data_class, max_tokens=16000)
    except ProviderError as exc:
        out["error"] = str(exc)[:300]
        return out
    for k in ("title", "buyer", "reference"):
        c = data.get(k) or {}
        txt = (c.get("text") or "").strip()
        cited = [by_id[i] for i in c.get("entry_ids") or [] if i in by_id]
        if txt and cited and any(set(tokens(txt)) <= set(tokens(x.get("quote") or "") + tokens(x.get("statement") or ""))
                                 for x in cited):
            out[k] = txt
        elif txt:
            out["rejected"].append({"element": k, "text": txt, "reason": "not stated in the cited entries"})
    for s in data.get("summary") or []:
        ok, why = _cited_ok(s.get("text") or "", s.get("entry_ids"), by_id)
        (out["summary"].append(s) if ok else out["rejected"].append({"element": "summary", "text": s.get("text"),
                                                                     "reason": why}))
    for p in data.get("points") or []:
        ok, why = _cited_ok(f"{p.get('heading')} {p.get('analysis')}", p.get("entry_ids"), by_id)
        if ok:
            p["refs"] = [r for i in p["entry_ids"] if i in by_id for r in _refs(by_id[i])]
            out["points"].append(p)
        else:
            out["rejected"].append({"element": "point", "text": p.get("analysis"), "reason": why})
    return out


# ── deadline status relative to the run date (deterministic, annotation only) ──

_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
# generic wording of a clarification / question window; never document-specific
_QA_TERMS = re.compile(r"\b(questions?|quer(?:y|ies)|clarifications?|inquir(?:y|ies)|enquir(?:y|ies)|q\s*&\s*a)\b",
                       re.IGNORECASE)


def run_date_of(run_meta: dict | None) -> str:
    """ISO date (YYYY-MM-DD) the run is judged against; today when not supplied."""
    rd = str((run_meta or {}).get("run_date") or "")[:10]
    return rd if _ISO_DATE.fullmatch(rd) else date.today().isoformat()


def _lapsed_dates(e: dict, run_date: str) -> list[str]:
    """Normalized DATE values of a DEADLINE entry strictly earlier than run_date."""
    if e.get("category") != "DEADLINE":
        return []
    out = []
    for v in e.get("values") or []:
        d = str(v.get("normalized") or "")[:10]
        if v.get("kind") == "DATE" and _ISO_DATE.fullmatch(d) and d < run_date:
            out.append(d)
    return sorted(set(out))


def _lapse_warning(run_date: str) -> str:
    return (f"[LAPSED PER UPLOADED DOCUMENTS as of {run_date} — verify whether an extension was issued via "
            f"email or e-bid portal]")


def _is_qa_deadline(e: dict) -> bool:
    return bool(_QA_TERMS.search(f"{e.get('statement') or ''} {e.get('quote') or ''}"))


def _qa_window_notice(entries: list[dict], run_date: str) -> str:
    lapsed = [d for e in entries if reportable(e) and _is_qa_deadline(e) for d in _lapsed_dates(e, run_date)]
    if not lapsed:
        return ""
    return (f"Documented Q&A deadline ({max(lapsed)}) has passed as of {run_date}. Verify whether an extension was "
            f"issued via email or the e-bid platform; if no extension applies, treat the items below as "
            f"proposal-level assumptions/risks rather than buyer questions.")


def _annotate_lapsed(composed: dict, lapsed_ids: set[str], run_date: str) -> None:
    """Appends the lapse warning to every composed item that reports a lapsed deadline.
    Composed items are copies; register entries are never touched."""
    warning = _lapse_warning(run_date)

    def walk(node):
        if isinstance(node, dict):
            if "entry_ids" in node and isinstance(node.get("text"), str) and lapsed_ids & set(node["entry_ids"]) \
                    and warning not in node["text"]:
                node["text"] += " " + warning
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk({"fast": composed["fast"], "full": composed["full"]})


# ── composition ─────────────────────────────────────────────────────────────

def _kv_identity(an: dict, entries: list[dict], run_date: str = "") -> list[tuple[str, str]]:
    rows = []
    for k, label in (("title", "Opportunity"), ("buyer", "Issued by"), ("reference", "Reference")):
        if an.get(k):
            rows.append((label, an[k]))
    deadline = next((e for e in entries if reportable(e) and e.get("category") == "DEADLINE"
                     and e.get("materiality") == "CRITICAL"), None)
    if deadline:
        text = f"{deadline['statement']} [{_refs(deadline)[0]}]"
        if run_date and _lapsed_dates(deadline, run_date):
            text += " " + _lapse_warning(run_date)
        rows.append(("Key deadline", text))
    methods = [e for e in entries if reportable(e) and e.get("category") == "SUBMISSION_METHOD"
               and e.get("modality") in ("MUST", "MAY", "IS")]
    # the row names where to submit: prefer provisions that carry an address (e-mail or URL value)
    methods.sort(key=lambda e: (not any(v.get("kind") in ("EMAIL", "URL") for v in e.get("values") or []),
                                -_RANK.get(e.get("materiality"), 1)))
    method = methods[0] if methods else None
    if method:
        rows.append(("Submission", f"{method['statement']} [{_refs(method)[0]}]"))
    return rows


def compose(entries: list[dict], *, an: dict, conflicts: dict, readability: dict, run_meta: dict,
            research: dict | None = None) -> dict:
    """Returns {"fast", "full", "ledger"} content models."""
    placed: dict[str, list[str]] = {}
    run_date = run_date_of(run_meta)
    conflicts = _distinct_conflicts(conflicts)

    def mark(items, where):
        for it in items:
            for i in it["entry_ids"]:
                placed.setdefault(i, []).append(where)
        return items

    # FAST
    fast = {"kind": "FAST", "title": "Opportunity Snapshot", "identity": _kv_identity(an, entries, run_date),
            "summary": [s["text"] for s in an.get("summary") or []], "sections": []}
    for title, cats in FAST_SECTIONS:
        min_rank = 2 if cats[0] in ("SCOPE",) else 2
        items = mark(_items_for(entries, cats, min_rank=min_rank), f"FAST:{title}")
        if items:
            fast["sections"].append({"title": title, "items": items})
    open_items = _open_items(entries, conflicts)
    if open_items:
        fast["sections"].append({"title": "Conflicts and Clarifications Affecting Participation",
                                 "items": mark(open_items, "FAST:Conflicts")})

    # FULL
    full = {"kind": "FULL", "title": "Bid Opportunity Assessment", "identity": fast["identity"],
            "summary": fast["summary"], "sections": []}
    for title, subs in FULL_SECTIONS:
        groups = []
        for sub, cats in subs:
            items = mark(_items_for(entries, cats, min_rank=2 if cats[0] not in ("SCOPE", "DELIVERABLE") else 1),
                         f"FULL:{title}")
            if items:
                groups.append({"title": sub, "items": items})
        if groups:
            full["sections"].append({"title": title, "groups": groups})
            if title == "Opportunity and Delivery Requirements":
                full["sections"].append({"title": "Buyer Intelligence", "research": research or {}})
    if an.get("points"):
        full["sections"].append({"title": "Specialist Analysis", "analysis": an["points"]})
    amend = _amendment_items(entries)
    if amend or open_items:
        full["sections"].append({"title": "Material Information, Amendments and Open Issues",
                                 "groups": ([{"title": "Amendments and Updated Information",
                                              "items": mark(amend, "FULL:Amendments")}] if amend else []) +
                                 ([{"title": "Unresolved Conflicts, Ambiguities and Clarification Questions",
                                    "items": mark(open_items, "FULL:Open")}] if open_items else [])})
    full["sections"].append({"title": "Management Decision Reference", "decision_reference": {
        "submission": [i for i in _items_for(entries, ["SUBMISSION_METHOD", "DEADLINE"], min_rank=3)],
        "documents": [i for i in _items_for(entries, ["REQUIRED_DOCUMENT"], min_rank=2)],
        "clarifications": conflicts.get("clarifications") or [],
        "qa_window_notice": _qa_window_notice(entries, run_date),
        "coverage": readability, "verification": run_meta.get("verification")}})

    lapsed_ids = {e["entry_id"] for e in entries if reportable(e) and _lapsed_dates(e, run_date)}
    if lapsed_ids:
        _annotate_lapsed({"fast": fast, "full": full}, lapsed_ids, run_date)
    ledger = _ledger(entries, placed)
    return {"fast": fast, "full": full, "ledger": ledger}


def _distinct_conflicts(conflicts: dict) -> dict:
    """Drops a conflict, and its clarification, whose entry set is a strict subset
    of another conflict's entry set: the same clash is reported once."""
    conflicts = conflicts or {}
    sets = [set(c.get("entry_ids") or []) for c in conflicts.get("conflicts") or []]

    def covered(ids) -> bool:
        s = set(ids or [])
        return bool(s) and any(s < o for o in sets)
    return dict(conflicts,
                conflicts=[c for c in conflicts.get("conflicts") or [] if not covered(c.get("entry_ids"))],
                clarifications=[q for q in conflicts.get("clarifications") or [] if not covered(q.get("entry_ids"))])


def _open_items(entries: list[dict], conflicts: dict) -> list[dict]:
    by_id = {e["entry_id"]: e for e in entries}
    conflicts = _distinct_conflicts(conflicts)
    items = []
    for c in conflicts.get("conflicts") or []:
        es = [by_id[i] for i in c.get("entry_ids") or [] if i in by_id]
        if not es:
            continue
        text = (c.get("issue") or "Conflicting provisions") + ": " + " / ".join(
            f"\"{e['statement']}\" [{_refs(e)[0]}]" for e in es)
        if c.get("implication"):
            text += f" Implication: {c['implication']}"
        if c.get("clarification_question"):
            text += f" Suggested clarification: {c['clarification_question']}"
        items.append({"text": text, "refs": [], "labels": ["Unresolved conflict"],
                      "entry_ids": [e["entry_id"] for e in es], "materiality": "CRITICAL"})
    for e in entries:
        if e.get("applicability") in ("AMBIGUOUS", "DISPUTED") and e.get("materiality") in ("CRITICAL", "MATERIAL") \
                and not any(e["entry_id"] in it["entry_ids"] for it in items):
            items.append(_item([e]))
    return items


def _amendment_items(entries: list[dict]) -> list[dict]:
    return [_item([e]) for e in entries if reportable(e) and (e.get("previous") or e.get("new_in_update"))
            and e.get("materiality") in ("CRITICAL", "MATERIAL")]


def _ledger(entries: list[dict], placed: dict[str, list[str]]) -> dict:
    rows, violations = [], []
    by_id = {e["entry_id"]: e for e in entries}
    for e in entries:
        where = placed.get(e["entry_id"], [])
        pcat, pmat = placement(e, by_id)
        app = e.get("applicability")
        if where:
            reason = ""
        elif app == "SUPERSEDED":
            reason = f"superseded by {e.get('superseded_by')}"
        elif app == "DUPLICATE":
            reason = f"duplicate of {e.get('duplicate_of')}"
        elif app and app.startswith("EXCLUDED"):
            reason = app.lower().replace("_", " ") + ": " + str((e.get("adjudication") or {}).get("reason") or
                                                                 "quote not found in the package")
        elif e.get("materiality") == "INFORMATIONAL":
            reason = "informational (register only)"
        else:
            reason = "NOT PLACED"
            violations.append(e["entry_id"])
        if reportable(e) and (e.get("category") in schema.FAST_MANDATORY or pcat in schema.FAST_MANDATORY) \
                and "CRITICAL" in (e.get("materiality"), pmat) \
                and not any(w.startswith("FAST") for w in where):
            violations.append(e["entry_id"])
        rows.append({"entry_id": e["entry_id"], "category": e.get("category"), "materiality": e.get("materiality"),
                     "applicability": app, "placements": where, "reason": reason})
    return {"rows": rows, "violations": sorted(set(violations)), "complete": not violations}
