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
    ("Commercial, Payment and Contractual Terms", ["PRICING", "PAYMENT", "GUARANTEE", "FINANCIAL_THRESHOLD",
                                                   "CONTRACT_TERM"]),
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
requirements or buyer preferences. Every figure you write must appear in a cited entry.
Dates: you receive RUN DATE, the date this analysis is prepared. Check every date against it. Never advise \
raising, submitting or asking questions or clarifications during a question/clarification period whose deadline \
has already passed as of RUN DATE; treat such open points as proposal-level assumptions or risks instead.
Plain language: the register's status/applicability column (CONFLICTED, AMBIGUOUS, DISPUTED, CURRENT) is \
internal metadata. Describe a substantive conflict or ambiguity plainly in prose by what the provisions say; \
never echo internal register jargon such as "flagged as conflicted", "marked conflicted" or "in the register".
4. fast_brief: a one-to-two page decision-triage brief for management, synthesized from the same register. \
Each bullet is one scannable line that merges related provisions; state each fact once across the whole brief; \
every bullet cites the register entry ids it rests on (entry_ids) and never writes an entry id in its text. \
Target roughly 450-650 words in total.
- stated_budget: the stated budget, ceiling or estimated value exactly as an entry gives it (cite it), or \
'Not disclosed' with no entry ids when no entry states one.
- what_is_it: 3-4 bullets: scope and methodology; scale and staffing; delivery window and location; \
contracting / sponsor or donor context.
- can_we_qualify_hard_gates: 2-4 bullets: mandatory gates that exclude a bidder (experience, credentials, \
staffing, language, mandatory work samples or references). Omit generic boilerplate (e.g. not bankrupt, not \
debarred) unless it is unusual.
- can_we_qualify_admin_penalties: 0-3 bullets: administrative or registration items that trigger a financial \
penalty or an extra step rather than exclusion.
- can_we_bid_in_time: 2-3 bullets: proposal assembly burden (what must be prepared, signed, split or \
protected); the clarification/question window; the instant-disqualification traps, consolidated in one line.
- is_it_worth_it: 2-4 bullets: budget or volume signal; pricing and cash-flow mechanics (payment triggers, \
payment lag, unpaid revisions, uncosted items treated as free); award and lock-in terms (validity, partial or \
multiple award, evaluation basis, or 'Weighting not disclosed' when no weights are stated). Report the terms \
only; never judge whether the opportunity is worth pursuing.
- material_conflicts: one line per substantive conflict, formatted 'Topic: conflict -> decision impact'; no \
clarification paragraphs.
The brief is neutral triage: no go/no-go or bid/no-bid recommendation, no score, rating or probability."""


# the analysis call's output schema: schema.ANALYSIS_OUTPUT plus the FAST decision-triage brief, requested in
# the same call (no additional provider call). Strict structured output needs every property required; a
# result.json written before the brief existed simply has no "fast_brief" (read as None).
def _cited_list(desc: str) -> dict:
    return {"type": "array", "items": schema._CITED, "description": desc}


FAST_BRIEF_OUTPUT = schema._obj({
    "stated_budget": schema._CITED,
    "what_is_it": _cited_list("3-4 synthesized bullets"),
    "can_we_qualify_hard_gates": _cited_list("2-4 mandatory exclusion gates"),
    "can_we_qualify_admin_penalties": _cited_list("0-3 administrative / penalty items"),
    "can_we_bid_in_time": _cited_list("2-3 bullets on timing and assembly burden"),
    "is_it_worth_it": _cited_list("2-4 bullets on commercial terms"),
    "material_conflicts": _cited_list("'Topic: conflict -> decision impact' lines"),
})
ANALYSIS_OUTPUT = dict(schema.ANALYSIS_OUTPUT,
                       properties=dict(schema.ANALYSIS_OUTPUT["properties"], fast_brief=FAST_BRIEF_OUTPUT),
                       required=list(schema.ANALYSIS_OUTPUT["required"]) + ["fast_brief"])

# (key, maximum bullets kept) for every bullet list of the brief, in reading order
FAST_BRIEF_LISTS = [("what_is_it", 4), ("can_we_qualify_hard_gates", 4), ("can_we_qualify_admin_penalties", 3),
                    ("can_we_bid_in_time", 3), ("is_it_worth_it", 4), ("material_conflicts", 5)]
NOT_DISCLOSED = "Not disclosed"
# wording that would turn neutral triage into a bid recommendation or a rating; such a bullet is dropped
# (the buyer's own scoring method is a document fact and stays reportable)
_ADVICE = re.compile(r"\b(?:go\s*/\s*no[\s-]*go|no[\s-]go\b|bid\s*/\s*no[\s-]*bid|(?:we|i)\s+recommend|"
                     r"recommend(?:ed|ation|s)?\s+(?:to\s+)?(?:not\s+)?(?:bid|pursu|decline)|"
                     r"(?:we|you|the\s+firm)\s+should\s+(?:not\s+)?(?:bid|pursue)|win\s+probability|"
                     r"probability\s+of\s+(?:winning|award|success)|chance\s+of\s+winning|"
                     r"likelihood\s+of\s+(?:winning|success)|worth\s+(?:pursuing|bidding))",
                     re.IGNORECASE)


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


_QUOTE_OVERLAP = 0.60   # statement tokens also in the quote, at or above which the quote adds nothing


def _quote_overlap(statement: str, quote: str) -> float:
    """Share of the statement's (lowercase alphanumeric) tokens that the quote also contains."""
    st = set(tokens(statement))
    return len(st & set(tokens(quote))) / len(st) if st else 0.0


def _item(group: list[dict], include_quote: bool = True) -> dict:
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
    # verbatim source grounding: the quote the statement was verified against, shown only when
    # it carries wording the statement does not (a near-restatement is not repeated)
    quote = e.get("quote") or ""
    if include_quote and quote and normalize(quote) != normalize(e.get("statement") or "") \
            and _quote_overlap(e.get("statement") or "", quote) < _QUOTE_OVERLAP:
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


def _items_for(entries: list[dict], cats: list[str], *, min_rank: int = 1,
               include_quote: bool = True) -> list[dict]:
    by_id = {e["entry_id"]: e for e in entries}
    pl = {e["entry_id"]: placement(e, by_id) for e in entries}
    sel = [e for e in entries if pl[e["entry_id"]][0] in cats and reportable(e)
           and _RANK.get(pl[e["entry_id"]][1], 1) >= min_rank]
    sel.sort(key=lambda e: (-_RANK.get(pl[e["entry_id"]][1], 1), cats.index(pl[e["entry_id"]][0])))
    return [_item(g, include_quote) for g in group_restatements(sel)]


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


def analysis(writer: Analyst | None, entries: list[dict], ledger: UsageLedger, data_class: str,
             run_date: str = "") -> dict:
    """Summary, identity and specialist points. Every element is checked; rejected
    elements are kept in `rejected` with the reason (never published). `run_date`
    (YYYY-MM-DD) is given to the writer so lapsed windows are not advised on."""
    out = {"title": "", "buyer": "", "reference": "", "summary": [], "points": [], "rejected": [], "error": None,
           "fast_brief": None}
    if writer is None:
        out["error"] = "no writer configured"
        return out
    live = [e for e in entries if reportable(e)]
    by_id = {e["entry_id"]: e for e in live}
    user = (f"RUN DATE: {run_date}\n\n" if run_date else "") + "EVIDENCE REGISTER:\n" + "\n".join(
        f"{e['entry_id']} | {e.get('category')} | {e.get('modality')} | {e.get('materiality')} | "
        f"{e.get('applicability')} | {e.get('statement')}" for e in live)
    try:
        data = writer.call_json(ANALYSIS_SYSTEM, user, ANALYSIS_OUTPUT, purpose="analysis", ledger=ledger,
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
    out["fast_brief"] = _checked_brief(data.get("fast_brief"), by_id, out["rejected"])
    return out


def _checked_brief(fb, by_id: dict, rejected: list) -> dict | None:
    """The FAST brief as written, keeping only bullets that cite reportable entries, add no figure or e-mail
    the cited entries lack and carry no recommendation or rating wording. None when nothing survives."""
    if not isinstance(fb, dict):
        return None
    out: dict = {}
    for key, cap in FAST_BRIEF_LISTS:
        kept = []
        for b in fb.get(key) or []:
            text = " ".join(str((b or {}).get("text") or "").split())
            if not text:
                continue
            ids = list(dict.fromkeys(i for i in (b.get("entry_ids") or []) if i in by_id))
            # an entry id written in the text is a citation (made compact at composition), not a figure
            bare = _readable_issue(text, by_id, ref_of=lambda e: "")[0]
            ok, why = _cited_ok(bare, ids, by_id)
            if ok and _ADVICE.search(bare):
                ok, why = False, "recommendation or rating wording"
            if ok and len(kept) < cap:
                kept.append({"text": text, "entry_ids": ids})
            elif ok:
                rejected.append({"element": f"fast_brief.{key}", "text": text, "reason": f"over the {cap}-bullet cap"})
            else:
                rejected.append({"element": f"fast_brief.{key}", "text": text, "reason": why})
        out[key] = kept
    sb = fb.get("stated_budget") or {}
    text = " ".join(str(sb.get("text") or "").split())
    ids = list(dict.fromkeys(i for i in (sb.get("entry_ids") or []) if i in by_id))
    if text and ids and _cited_ok(text, ids, by_id)[0]:
        out["stated_budget"] = {"text": text, "entry_ids": ids}
    else:
        if text and not text.lower().startswith("not disclosed"):
            rejected.append({"element": "fast_brief.stated_budget", "text": text,
                             "reason": _cited_ok(text, ids, by_id)[1]})
        out["stated_budget"] = {"text": NOT_DISCLOSED, "entry_ids": []}
    if not any(out[k] for k, _ in FAST_BRIEF_LISTS):
        return None
    return out


# ── deadline status relative to the run date (deterministic, annotation only) ──

_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
# an entry-id range such as "E041-E043", "E041–E043" or "E041-43" (prefix letters + zero-padded number)
_ID_RANGE = re.compile(r"(?<![\w-])([A-Za-z]+)(\d+)\s*[-–—]\s*([A-Za-z]+)?(\d+)(?![\w-])")
_MAX_RANGE = 200
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
    return f"[LAPSED PER UPLOADED DOCUMENTS as of {run_date} — verify whether an extension was issued]"


def _is_qa_deadline(e: dict) -> bool:
    return bool(_QA_TERMS.search(f"{e.get('statement') or ''} {e.get('quote') or ''}"))


def _qa_window_notice(entries: list[dict], run_date: str) -> str:
    lapsed = [d for e in entries if reportable(e) and _is_qa_deadline(e) for d in _lapsed_dates(e, run_date)]
    if not lapsed:
        return ""
    return (f"Documented Q&A deadline ({max(lapsed)}) has passed as of {run_date}. Verify whether an extension was "
            f"issued; if no extension applies, treat the items below as proposal-level assumptions/risks rather "
            f"than buyer questions.")


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


# ── FAST decision-triage brief: deterministic dates and compact citations ────

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
FAST_BRIEF_SECTIONS = [
    ("What Is It?", [("", "what_is_it")]),
    ("Can We Qualify?", [("Hard Gates", "can_we_qualify_hard_gates"),
                         ("Admin & Penalty Gates", "can_we_qualify_admin_penalties")]),
    ("Can We Bid in Time?", [("", "can_we_bid_in_time")]),
    ("Is It Worth It Commercially?", [("", "is_it_worth_it")]),
    ("Material Conflicts & Caveats", [("", "material_conflicts")]),
]


def fmt_date(iso: str) -> str:
    """'2026-11-30' -> 'Nov 30, 2026' (locale-independent)."""
    d = date.fromisoformat(iso[:10])
    return f"{_MONTHS[d.month - 1]} {d.day}, {d.year}"


def days_between(iso: str, run_date: str) -> int:
    """Calendar days from run_date to iso (negative when iso is earlier)."""
    return (date.fromisoformat(iso[:10]) - date.fromisoformat(run_date[:10])).days


def countdown(iso: str, run_date: str) -> str:
    """Relative status of a deadline as of run_date, computed, never written by a model:
    'Nov 30, 2026 (8 days left)', 'Nov 22, 2026 (due today)', 'Closed Nov 20, 2026 (2 days ago)'."""
    n = days_between(iso, run_date)
    if n > 0:
        return f"{fmt_date(iso)} ({n} day{'s' if n != 1 else ''} left)"
    if n == 0:
        return f"{fmt_date(iso)} (due today)"
    return f"Closed {fmt_date(iso)} ({-n} day{'s' if n != -1 else ''} ago)"


def _iso_dates(e: dict) -> list[str]:
    return [str(v.get("normalized"))[:10] for v in e.get("values") or []
            if v.get("kind") == "DATE" and _ISO_DATE.fullmatch(str(v.get("normalized") or "")[:10])]


def source_keys(entries: list[dict]) -> dict[str, str]:
    """Document -> short citation key, in order of first appearance in the register. A single-document
    package needs no key (''); a multi-document package gets 'D1', 'D2', ..."""
    docs = list(dict.fromkeys(str(e.get("document") or "") for e in entries if e.get("document")))
    return {d: ("" if len(docs) == 1 else f"D{n}") for n, d in enumerate(docs, 1)}


def _page_key(p: str):
    return (0, int(p), "") if p.isdigit() else (1, 0, p)


def compact_ref(e: dict, keys: dict[str, str]) -> str:
    """'p. 4' (single document) or 'D2, p. 4' (multi-document)."""
    k = keys.get(str(e.get("document") or ""), "")
    return f"{k}, {_page(e)}" if k else _page(e)


def compact_cite(ids: list[str], by_id: dict, keys: dict[str, str]) -> str:
    """'[p. 3, p. 6]' or '[D1, p. 4; D2, p. 2]': distinct pages grouped per document, in page order."""
    per_doc: dict[str, list[str]] = {}
    for i in ids:
        e = by_id.get(i)
        if e is None:
            continue
        pages = per_doc.setdefault(str(e.get("document") or ""), [])
        p = str(e.get("page") or "")
        if p not in pages:
            pages.append(p)
    parts = []
    for doc, pages in per_doc.items():
        pp = ", ".join(_page({"page": p}) for p in sorted(pages, key=_page_key))
        parts.append(f"{keys[doc]}, {pp}" if keys.get(doc) else pp)
    return "[" + "; ".join(parts) + "]" if parts else ""


def _decision_header(an: dict, entries: list[dict], run_date: str, keys: dict[str, str], by_id: dict,
                     budget: dict) -> list[tuple[str, str]]:
    live = [e for e in entries if reportable(e)]
    client = an.get("buyer") or "Not stated"
    if an.get("reference"):
        client += f" · Ref. {an['reference']}"
    deadlines = [e for e in live if e.get("category") == "DEADLINE" and e.get("materiality") == "CRITICAL"
                 and not _is_qa_deadline(e)]
    dated = [e for e in deadlines if _iso_dates(e)]
    sub = (dated or deadlines or [None])[0]
    if sub is None:
        deadline = "Not stated"
    elif _iso_dates(sub):
        times = [str(v.get("text") or "") for v in sub.get("values") or [] if v.get("kind") == "TIME"]
        when = countdown(_iso_dates(sub)[0], run_date)
        if times and not when.startswith("Closed"):
            when = when.replace(" (", f", {times[0]} (", 1)
        deadline = f"{when} {compact_cite([sub['entry_id']], by_id, keys)}"
    else:
        deadline = f"{sub['statement']} {compact_cite([sub['entry_id']], by_id, keys)}"
    qa = [(d, e) for e in live if e.get("category") == "DEADLINE" and _is_qa_deadline(e) for d in _iso_dates(e)]
    if qa:
        last = max(d for d, _ in qa)
        ids = [e["entry_id"] for d, e in qa if d == last]
        status = countdown(last, run_date)
        status = status if status.startswith("Closed") else "Open until " + status
        qa_text = f"{status} {compact_cite(ids, by_id, keys)}"
    else:
        qa_text = "Not stated"
    btext = budget.get("text") or NOT_DISCLOSED
    if budget.get("entry_ids"):
        btext += " " + compact_cite(budget["entry_ids"], by_id, keys)
    docs = list(keys)
    legend = docs[0] if len(docs) == 1 else "; ".join(f"{keys[d]} = {d}" for d in docs)
    return [("Client / Program", client), ("Submission Deadline", deadline), ("Q&A Window", qa_text),
            ("Stated Budget", btext), ("Source File" + ("s" if len(docs) > 1 else ""), legend or "Not stated")]


def fast_brief(an: dict, entries: list[dict], run_date: str) -> dict | None:
    """Composes the synthesized FAST brief from an["fast_brief"] (checked in `analysis`). None when the
    analysis carries no brief (e.g. a result.json written before it existed): FAST then keeps its
    deterministic composition. Entry ids written into a bullet are replaced by compact citations."""
    fb = (an or {}).get("fast_brief")
    if not isinstance(fb, dict):
        return None
    by_id = {e["entry_id"]: e for e in entries if reportable(e)}
    keys = source_keys(entries)

    def item(b: dict) -> dict | None:
        ids = [i for i in b.get("entry_ids") or [] if i in by_id]
        if not ids or not (b.get("text") or "").strip():
            return None
        text, _ = _readable_issue(b["text"], by_id, ref_of=lambda e: compact_ref(e, keys))
        return {"text": text, "entry_ids": ids, "cite": compact_cite(ids, by_id, keys), "refs": [], "labels": []}

    sections = []
    for title, parts in FAST_BRIEF_SECTIONS:
        groups = []
        for lead, key in parts:
            cap = dict(FAST_BRIEF_LISTS)[key]
            items = [it for it in (item(b) for b in (fb.get(key) or [])[:cap]) if it]
            if items:
                groups.append({"lead": lead, "items": items})
        sections.append({"title": title, "groups": groups})
    if not any(s["groups"] for s in sections):
        return None
    budget = fb.get("stated_budget") or {}
    budget = {"text": budget.get("text") or NOT_DISCLOSED,
              "entry_ids": [i for i in budget.get("entry_ids") or [] if i in by_id]}
    header = _decision_header(an, entries, run_date, keys, by_id, budget)
    words = sum(len(it["text"].split()) for s in sections for g in s["groups"] for it in g["items"])
    return {"header": header, "sources": [{"key": k, "document": d} for d, k in keys.items()],
            "stated_budget": budget, "sections": sections, "word_count": words, "run_date": run_date}


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
            "summary": [s["text"] for s in an.get("summary") or []], "run_date": run_date, "sections": []}
    for title, cats in FAST_SECTIONS:
        min_rank = 2 if cats[0] in ("SCOPE",) else 2
        items = mark(_items_for(entries, cats, min_rank=min_rank), f"FAST:{title}")
        if items:
            fast["sections"].append({"title": title, "items": items})
    open_items = _open_items(entries, conflicts)
    if open_items:
        fast["sections"].append({"title": "Conflicts and Clarifications Affecting Participation",
                                 "qa_window_notice": _qa_window_notice(entries, run_date),
                                 "items": mark(open_items, "FAST:Conflicts")})

    # FULL
    full = {"kind": "FULL", "title": "Bid Opportunity Assessment", "identity": fast["identity"],
            "summary": fast["summary"], "run_date": run_date, "sections": []}
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
    # a compact checklist: critical items only, without the verbatim quotes the body sections already show
    full["sections"].append({"title": "Management Decision Reference", "decision_reference": {
        "submission": _items_for(entries, ["SUBMISSION_METHOD", "DEADLINE"], min_rank=3, include_quote=False),
        # same selection as FULL "Required Documents and Forms" / FAST "Mandatory Forms and Documents"
        "documents": _items_for(entries, ["REQUIRED_DOCUMENT"], min_rank=2, include_quote=False),
        "clarifications": conflicts.get("clarifications") or [],
        "qa_window_notice": _qa_window_notice(entries, run_date),
        "coverage": readability, "verification": run_meta.get("verification")}})

    lapsed_ids = {e["entry_id"] for e in entries if reportable(e) and _lapsed_dates(e, run_date)}
    if lapsed_ids:
        _annotate_lapsed({"fast": fast, "full": full}, lapsed_ids, run_date)
    # the synthesized decision-triage brief (when the analysis call returned one) is added after the lapse
    # annotation: its Decision Header states window status once, so bullets are not stamped again
    brief = fast_brief(an, entries, run_date)
    if brief:
        fast["brief"] = brief
        for sec in brief["sections"]:
            for g in sec["groups"]:
                mark(g["items"], "FAST:Brief")
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
        # members are named by source reference, not register entry id; their statements are in the body sections
        text, named = _readable_issue(c.get("issue") or "Conflicting provisions", by_id)
        missing = list(dict.fromkeys(f"[{_refs(e)[0]}]" for e in es if _refs(e)[0] not in named))
        if missing:
            text += (" " if text[-1:] in ".;:!?" else ". ") + "Sources: " + "; ".join(missing) + "."
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


def _readable_issue(issue: str, by_id: dict, ref_of=None) -> tuple[str, set[str]]:
    """Replaces register entry ids in conflict wording with their source references: a bare id
    becomes "[doc, p. X]", a parenthesised id list "(E1, E2)" becomes one bracket of its distinct refs.
    A hyphenated range "E041-E043" (or with an en/em dash) is expanded to the register ids it spans
    and becomes one bracket of their distinct refs. Ids not in the register are left as written.
    Returns the text and the references it now names. `ref_of(entry) -> str` overrides the reference
    wording (default "doc, p. X")."""
    ref_of = ref_of or (lambda e: _refs(e)[0])
    issue = " ".join(issue.split())
    named: set[str] = set()
    ids = sorted((i for i in by_id if i and i in issue), key=len, reverse=True)
    if not ids and not _ID_RANGE.search(issue):
        return issue, named
    one = r"(?<![\w-])(?:" + "|".join(re.escape(i) for i in ids) + r")(?![\w-])" if ids else r"(?!x)x"
    token = r"(?:" + _ID_RANGE.pattern + "|" + one + ")"

    def expand(tok: str) -> list[str]:
        m = _ID_RANGE.fullmatch(tok)
        if not m:
            return [tok] if tok in by_id else []
        pre, lo, hi = m.group(1), int(m.group(2)), int(m.group(4))
        if m.group(3) not in (None, pre) or not 0 <= hi - lo <= _MAX_RANGE:
            return []
        width = len(m.group(2))
        return [i for i in (f"{pre}{n:0{width}d}" for n in range(lo, hi + 1)) if i in by_id]

    def refs(found: list[str]) -> str:
        rs = list(dict.fromkeys(ref_of(by_id[i]) for i in found))
        named.update(rs)
        return "[" + "; ".join(rs) + "]"

    def single(m) -> str:
        found = expand(m.group(0))
        return refs(found) if found else m.group(0)

    def grouped(m) -> str:
        parts = [expand(t.group(0)) for t in re.finditer(token, m.group(0))]
        if all(parts):
            return refs([i for p in parts for i in p])
        return re.sub(token, single, m.group(0))     # an unresolvable member: resolve the others one by one
    group = r"\(\s*" + token + r"(?:\s*(?:,|;|and|&)\s*" + token + r")*\s*\)"
    # one pass, so a document name inside an inserted reference is never rewritten
    return re.sub(group + "|" + token,
                  lambda m: grouped(m) if m.group(0).startswith("(") else single(m), issue), named


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
