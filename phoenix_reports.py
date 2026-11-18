"""Phoenix Bid Intelligence reports.

Two management-ready PDFs, built from document-verified facts only:

* FAST  -- "Opportunity Snapshot" (about 2 pages): opportunity at a glance,
           scope and delivery essentials, evaluation and eligibility,
           commercial and submission essentials, additional material facts.
* FULL  -- "Bid Opportunity Assessment" (about 3-6 pages), readable on its
           own: executive intelligence summary, opportunity and delivery
           requirements, buyer intelligence (external, dated, with URLs),
           evaluation and commercial intelligence, material information and
           amendments, management decision reference.

Each statement is printed once per report (a statement-level de-duplication
tracker), as one concise line in the document's own words with a reference.

Factual rules enforced here:
* every statement is either a verbatim span of an uploaded document (with
  document/page/sheet reference), a FAST-extracted fact whose excerpt is
  verified against the document text, a dated external source with URL, or a
  value explicitly marked as manually entered by a Phoenix user;
* no bid/no-bid recommendation, score, probability or suitability judgement;
* an empty AI field is never reported as "the RFP does not state ..." --
  sections with nothing verifiable are simply omitted;
* specialist free text from the FULL engine is NOT reproduced (it is advisory
  and can contradict the documents); detailed evidence stays in the app.

Zero model calls. Pure functions over persisted data + document text.
"""
from __future__ import annotations

import io
import re
import threading
from datetime import date, datetime
from xml.sax.saxutils import escape as _xml_escape

from reportlab.lib.colors import HexColor
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate, Frame, KeepTogether, PageTemplate, Paragraph as _RLParagraph, Spacer, Table,
    TableStyle,
)

import change_tracking as ct
import procurement_digest as pdg
import scripts.build_boc_bid_intelligence_preview_pdf as base

NIGHT, INK, GOLD, MUTED, RULE, IVORY, PAPER, BAND = (
    base.NIGHT, base.INK, base.GOLD, base.MUTED, base.RULE, base.IVORY, base.PAPER, base.BAND)
PAGE_W, PAGE_H, MARGIN = base.PAGE_W, base.PAGE_H, base.MARGIN
BODY_W = PAGE_W - 2 * MARGIN
S = base.styles

GREEN = "#2E7D4F"
AMBER = "#9A6A12"
RED = "#A93226"

_st = {
    "sec": ParagraphStyle("px_sec", fontName="Display", fontSize=15.5, leading=19, textColor=INK,
                          spaceBefore=10, spaceAfter=2),
    "sub": ParagraphStyle("px_sub", fontName="BodyMed", fontSize=9.4, leading=12.5, textColor=INK,
                          spaceBefore=6, spaceAfter=2),
    "body": ParagraphStyle("px_body", fontName="Body", fontSize=9.1, leading=12.8, textColor=INK,
                           spaceAfter=3),
    "bul": ParagraphStyle("px_bul", fontName="Body", fontSize=8.9, leading=12.2, textColor=INK,
                          leftIndent=10, bulletIndent=0, spaceAfter=1.5),
    "ref": ParagraphStyle("px_ref", fontName="Body", fontSize=7.3, leading=9.5, textColor=MUTED),
    "note": ParagraphStyle("px_note", fontName="Body", fontSize=7.9, leading=10.6, textColor=MUTED,
                           spaceAfter=2),
    "cell": ParagraphStyle("px_cell", fontName="Body", fontSize=8.3, leading=11, textColor=INK),
    "cell_b": ParagraphStyle("px_cell_b", fontName="BodyMed", fontSize=8.3, leading=11, textColor=INK),
    "cell_s": ParagraphStyle("px_cell_s", fontName="Body", fontSize=7.2, leading=9.4, textColor=MUTED),
    "head": ParagraphStyle("px_head", fontName="BodyMed", fontSize=7.9, leading=10, textColor=PAPER),
    "t_kick": ParagraphStyle("px_tk", fontName="BodyMed", fontSize=8, leading=10, textColor=GOLD),
    "t_title": ParagraphStyle("px_tt", fontName="Display", fontSize=19, leading=22.5, textColor=IVORY,
                              spaceBefore=3, spaceAfter=3),
    "t_sub": ParagraphStyle("px_ts", fontName="Body", fontSize=9, leading=12, textColor=HexColor("#C7C3B8")),
}

SNAPSHOT = "SNAPSHOT"
ASSESSMENT = "ASSESSMENT"


def Paragraph(text, style):  # noqa: N802
    text = str(text).replace("<b>", '<font name="BodyMed">').replace("</b>", "</font>")
    return _RLParagraph(text, style)


_ARABIC_RUN = re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]"
                        r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿\s\d\W]*"
                        r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]|"
                        r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")


def latin_only(v) -> str:
    """The reports are English and their fonts have no Arabic glyphs: any
    Arabic text that reaches the PDF (e.g. a user-typed Arabic title) is
    shown as a marker, never as unreadable boxes. Arabic-Indic digits become
    Western digits. The original Arabic is available in the app."""
    import arabic_text
    s = str(v if v is not None else "")
    if not arabic_text.has_arabic(s) and not re.search(r"[٠-٩۰-۹]", s):
        return s
    s = _ARABIC_RUN.sub(lambda m: "[Arabic text]" if arabic_text.has_arabic(m.group(0)) else m.group(0), s)
    return arabic_text.to_western_digits(s)


def esc(v) -> str:
    return _xml_escape(latin_only(v))


def fmt_date(v) -> str:
    if not v:
        return ""
    s = str(v)[:10]
    try:
        return datetime.strptime(s, "%Y-%m-%d").strftime("%d %B %Y").lstrip("0")
    except ValueError:
        return str(v)


_ctx = threading.local()


def ref_text(ref: dict | None) -> str:
    """Compact reference. Documents are aliased D1, D2 ... (listed in the
    document-basis note); with a single document only the page/sheet shows."""
    if not ref:
        return ""
    alias = getattr(_ctx, "alias", None) or {}
    doc = ref.get("doc")
    parts = []
    if doc and alias.get(doc, doc):
        parts.append(alias.get(doc, doc))
    if ref.get("page"):
        parts.append(f"p.{ref['page']}")
    if ref.get("sheet"):
        parts.append(f'sheet "{ref["sheet"]}"')
    return " ".join(parts) if alias else pdg.ref_label(doc, ref.get("page"), ref.get("sheet"))


def _set_alias(f: dict) -> None:
    names = [d["name"] for d in f.get("documents") or []]
    single = len(names) == 1 and not pdg._ARABIC_CHAR.search(names[0])
    _ctx.alias = {names[0]: ""} if single else {n: f"D{i}" for i, n in enumerate(names, 1)}


def clip(text: str, n: int) -> str:
    t = pdg.norm(text)
    if len(t) <= n:
        return t
    cut = t[:n].rsplit(" ", 1)[0]
    return cut.rstrip(",;:") + "\u2026"


# ═══════════════════════════════════════════════════════════════════════
# TEXT HELPERS -- concise, faithful one-line facts (no paraphrase)
# ═══════════════════════════════════════════════════════════════════════

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"“(])")
_LABEL = re.compile(r"^([A-Z][A-Za-z0-9 &/()'-]{2,45}):\s+(.+)$", re.S)


def sentences_of(text: str) -> list[str]:
    return [p.strip() for p in _SENT_SPLIT.split(pdg.norm(text)) if p.strip()]


def label_of(text: str) -> tuple[str | None, str]:
    """'Curriculum Facilitation: Execute ...' -> ('Curriculum Facilitation', 'Execute ...')."""
    m = _LABEL.match(pdg.norm(text))
    return (m.group(1).strip(), m.group(2).strip()) if m else (None, pdg.norm(text))


def brief(text: str, n: int = 150) -> str:
    """The item's own words, limited to its first sentence; a sentence longer
    than `n` is cut at a clause boundary (never mid-word) and marked '…'."""
    lab, rest = label_of(text)
    s = (sentences_of(rest) or [rest])[0]
    if len(s) > n:
        cut = s[:n]
        idx = max(cut.rfind(sep) for sep in ("; ", ", ", " (", " – ", " - "))
        s = (cut[:idx].rstrip(",;:( ") + "…") if idx >= n * 0.55 else clip(s, n)
    return f"{lab}: {s}" if lab else s


def doc_name(text: str) -> str:
    """'Updated CV - Highlighting relevant experience' -> 'Updated CV'."""
    t = re.sub(r"[,;]?\s*(?:and|or)?$", "", pdg.norm(text).rstrip(":.,; ")).strip(" ,;")  # list-joining tails
    t = re.sub(r'^["“](.+)["”]$', r"\1", t)
    for sep in (" - ", " – ", ": "):
        if sep in t and len(t.split(sep)[0]) >= 3:
            return t.split(sep)[0].strip()
    return clip(t, 70)


class _Shown:
    """Statements already printed in this report -- a statement is printed once."""

    def __init__(self):
        self._t: list[str] = []

    def add(self, *texts) -> None:
        self._t.extend(pdg.fold(t) for t in texts if t)

    def same(self, text: str) -> bool:
        """Exactly this statement was printed already (facts are distinct
        statements; one may legitimately contain another's words)."""
        return pdg.fold(text) in self._t

    def seen(self, text: str) -> bool:
        ft = pdg.fold(text)
        if not ft:
            return True
        head = ft[:60]
        return any(head in s or (len(s) >= 25 and s[:60] in ft) for s in self._t)


# ═══════════════════════════════════════════════════════════════════════
# EVALUATION WEIGHT HIERARCHY (generic, arithmetic-first)
# ═══════════════════════════════════════════════════════════════════════

_PCT = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_PRICE_FORM = re.compile(r"\b(pric(e|ing) (form|schedule|sheet)|bill of quantities|cost (breakdown|schedule)|"
                         r"weighted (price|pricing))\b", re.I)


def pct(w) -> float | None:
    m = _PCT.search(str(w or ""))
    return float(m.group(1)) if m else None


def child_weight_basis(parent_name: str, parent_weight, child_weights: list, child_excerpts: list[str]) -> str:
    """How the buyer's sub-criterion weights relate to their parent.

    * 'within'  -- an excerpt explicitly says "N% of/within <parent>", or the
                   children sum to 100 (they divide the parent);
    * 'overall' -- the children sum to the parent's own weight (< 100), so
                   each child is a share of the total score
                   (e.g. Technical 60% = 25 + 15 + 10 + 10);
    * 'published' -- anything else: the weight is shown exactly as published,
                   with no qualifier (ambiguity is not reinterpreted).
    """
    ws = [pct(w) for w in child_weights]
    if not ws or any(w is None for w in ws):
        return "published"
    first = (pdg.fold(parent_name).split() or [""])[0]
    if first and any(re.search(rf"%\s+(of|within)\s+(the\s+)?{re.escape(first)}\b", pdg.fold(e)) for e in child_excerpts):
        return "within"
    total, pw = sum(ws), pct(parent_weight)
    if pw is not None and pw < 100 and abs(total - pw) <= 0.5:
        return "overall"
    if abs(total - 100) <= 0.5:
        return "within"
    return "published"


def resolve_criteria(criteria: list[dict]) -> list[dict]:
    """Drop pricing-form weights (price calculation, not evaluation), merge
    duplicate extractions of the same criterion, nest children under their
    parent (in the buyer's order and terminology) and set each child's weight
    basis by arithmetic over the published weights."""
    out: list[dict] = []
    idx: dict[str, int] = {}
    for c in criteria:
        if _PRICE_FORM.search(f"{c['stage']} {c.get('parent') or ''}"):
            continue
        k = pdg.fold(c["stage"])
        if k in idx:
            if not out[idx[k]].get("weight") and c.get("weight"):
                out[idx[k]] = dict(c)
            continue
        idx[k] = len(out)
        out.append(dict(c))
    names = list(idx)
    for c in out:
        p, own = pdg.fold(c.get("parent") or ""), pdg.fold(c["stage"])
        if not p or p == own:
            c["_pk"] = None
        elif p in idx:
            c["_pk"] = p
        else:  # "Team Experience and Qualifications (Evaluation Criteria 2)" -> "Team Experience ..."
            cands = [n for n in names if n != own and p.startswith(n + " ")]
            c["_pk"] = max(cands, key=len) if cands else None
    ordered: list[dict] = []
    placed: set[int] = set()

    def walk(c: dict, depth: int) -> None:
        if id(c) in placed:
            return
        placed.add(id(c))
        c["level"] = depth
        c.setdefault("basis", None)
        ordered.append(c)
        kids = [k for k in out if k["_pk"] == pdg.fold(c["stage"]) and id(k) not in placed]
        basis = child_weight_basis(c["stage"], c.get("weight"), [k.get("weight") for k in kids],
                                   [(k.get("ref") or {}).get("excerpt") or "" for k in kids]) if kids else None
        c["children_basis"] = basis
        for k in kids:
            k["basis"], k["parent"] = basis, c["stage"]
            walk(k, depth + 1)

    for c in out:
        c["basis"] = None
    for c in [c for c in out if c["_pk"] is None] + out:  # roots first; anything left (cycles) as a root
        if id(c) not in placed:
            walk(c, 0)
    for c in ordered:
        c.pop("_pk", None)
    return ordered


# ═══════════════════════════════════════════════════════════════════════
# FACT MODEL
# ═══════════════════════════════════════════════════════════════════════

_GATE_ROLE = re.compile(r"gate|qualification|pass\s*/?\s*fail|eligib", re.I)
_GATE_LABEL = re.compile(r"eligib|mandatory|pass\s*/?\s*fail|qualifying|minimum requirement|"
                         r"شروط\s*(?:ال)?(?:أهلية|اهلية|تأهيل|تاهيل)|متطلبات\s*(?:ال)?إلزامية", re.I)


def _is_eligibility_gate(c: dict, criteria: list[dict]) -> bool:
    """A pass/fail condition (FAST role "Qualification / Gate", or an unweighted
    entry under an eligibility/mandatory heading) -- unless it carries a
    published weight or is the parent of other criteria."""
    if c.get("weight"):
        return False
    own = pdg.fold(c.get("stage") or "")
    if any(pdg.fold(o.get("parent") or "") == own for o in criteria if o is not c):
        return False
    return bool(_GATE_ROLE.search(c.get("role") or "")
                or _GATE_LABEL.search(f"{c.get('parent') or ''} {c.get('stage') or ''}"))


def _verified(documents, excerpt: str) -> bool:
    """An extracted excerpt is publishable only if it is found in the documents."""
    e = pdg.norm(excerpt)
    if not e:
        return False
    return pdg.corpus_contains(documents, e[:90]) or pdg.corpus_contains(documents, e[:45])


def _ref_from(source_refs) -> dict:
    r = (source_refs or [{}])[0] or {}
    out = {"doc": r.get("source_doc"), "page": r.get("page"), "sheet": r.get("sheet"),
           "excerpt": pdg.norm(r.get("excerpt") or "")}
    if r.get("excerpt_original"):  # Arabic source (see source_translation.localize_fast_result)
        out["original"] = r["excerpt_original"]
    return out


def _items(secs: dict, key: str, *, drop_leadin: bool = False) -> list[dict]:
    out = []
    for s in secs.get(key) or []:
        for it in s["items"]:
            t = it["text"]
            if drop_leadin and t.endswith(":") and len(t) < 120:
                continue
            out.append(it)
    return out


def _is_subhead(text: str) -> bool:
    t = text.strip()
    return len(t.split()) <= 6 and not re.search(r"[.:;,%]$", t) and not re.search(r"\d{2,}", t)


_COLUMN_WORDS = {"ref", "no", "nr", "title", "description", "format", "deadline", "due", "date", "item", "qty",
                 "quantity", "unit", "phase", "stage", "responsible", "party", "remarks", "deliverable",
                 "deliverables", "output", "outputs", "required", "milestone", "submission", "s"}


def _is_column_header(text: str) -> bool:
    """A table's column-header row read as text ("Phase Ref.", "Deliverable
    title") -- a layout label, not a deliverable or a document."""
    words = re.findall(r"[a-z]+", text.lower())
    return 0 < len(words) <= 4 and all(w in _COLUMN_WORDS for w in words)


def _groups(items: list[dict]) -> list[dict]:
    """Items grouped under the document's own sub-headings (lead-ins dropped)."""
    groups: list[dict] = []
    for it in items:
        t = it["text"]
        if t.endswith(":") and len(t) < 120:
            continue
        if _is_subhead(t):
            groups.append({"heading": t, "items": [], "ref": it})
            continue
        if not groups:
            groups.append({"heading": None, "items": [], "ref": it})
        groups[-1]["items"].append(it)
    return [g for g in groups if g["items"]]


_PROGRAMME_GEO = re.compile(r"\b(project|programme|program|initiative|network|operates|across)\b", re.I)
_DELIVERY_GEO = re.compile(r"\b(training|workshops?|sessions?|services?|assignment|work)\b.{0,40}\b(will|shall|must)\b.{0,30}"
                           r"\b(take place|be (delivered|held|conducted|performed))\b|\bvenue\b|place of (performance|delivery)",
                           re.I)


def location_kind(text: str) -> str:
    """'delivery' only when the sentence says where the assignment itself is
    delivered; a sentence about where a programme or organisation operates is
    'programme' geography -- never presented as the delivery location."""
    if _DELIVERY_GEO.search(text):
        return "delivery"
    return "programme" if _PROGRAMME_GEO.search(text) else "unspecified"


_LOCATION_LABEL = {"delivery": "Delivery location", "programme": "Programme locations",
                   "unspecified": "Location (as documented)"}

_RECEIPT = re.compile(r"\b(bids?|proposals?|offers?|tenders?|quotations?|applications?)\b.{0,80}"
                      r"\b(received|submitted|delivered|lodged)\b", re.I)
_LOCATION = re.compile(r"\b(locations?|venues?|place of (performance|delivery)|delivered (in|at)|on-?site at)\b", re.I)
_BUDGET = re.compile(r"\b(budget|ceiling|not (to )?exceed|maximum (contract |total )?(value|amount)|estimated (contract )?value)\b", re.I)
# A budget statement names a budget/ceiling AND states an amount; "shall not
# exceed the Contract Price" in a liability or damages clause is a cap on
# liability, not the buyer's budget.
_AMOUNT = re.compile(r"(?:\b(?:USD|US\$|EUR|GBP|CAD|AUD|AED|SAR|QAR|KWD|OMR|BHD|EGP|JOD|LBP|SDG|CHF)|[$€£])[:\s]{0,2}\d"
                     r"|\d[\d,.]*\s?(?:USD|EUR|GBP|CAD|AUD|AED|SAR|dollars|euros)\b", re.I)
# Securities the bidder must provide (bid bond, performance guarantee, retention):
# commercial obligations -- reported with the commercial terms, never as qualifications.
_SECURITY = re.compile(r"\b(bid bond|bid security|tender (bond|security)|performance (bond|security|guarantee)|"
                       r"bank guarantee|retention( money)?|parent company guarantee|advance payment (bond|guarantee))\b", re.I)
_PERCENT = re.compile(r"\d+(?:\.\d+)?\s?%|\bpercent\b", re.I)
def _states_security(text: str) -> bool:
    """A security named together with its own amount or percentage (within a
    short span) -- not a payment milestone that merely mentions a guarantee."""
    vals = [m.start() for rx in (_AMOUNT, _PERCENT) for m in rx.finditer(text)]
    return any(abs(m.start() - v) <= 90 for m in _SECURITY.finditer(text) for v in vals)


_NOT_BUDGET = re.compile(r"\b(liab\w*|damages|indemn\w*|penalt\w*|insurance|guarantee|bond|security)\b", re.I)
_PRICING = re.compile(r"\b(rate|price|pricing|cost|quotation|quote|currency|vat|tax|inclusive|lump.?sum|fee)\b", re.I)
_COST_BEARING = re.compile(r"(borne by|charged (on|to) the (service provider|contractor|supplier|bidder|consultant)|"
                           r"at the (contractor|supplier|consultant|bidder)'?s? (own )?(cost|expense)|"
                           r"won'?t handle any|will not (handle|cover|pay))", re.I)
_INCLUSIVE = re.compile(r"inclusive of all|all.?inclusive|including all costs", re.I)
_TIME_BOUND = re.compile(r"\bwithin\s+\d+\s+(calendar |working |business )?(days?|weeks?|hours?|months?)\b", re.I)
_NUMW = r"(?:\d+(?:\.\d+)?|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|twenty)"
_QTY = re.compile(
    rf"\b{_NUMW}(?:\s*\(\d+\))?[- ](?:sessions?|workshops?|modules?|days?|weeks?|months?|years?|cohorts?|"
    rf"participants?|trainees?|beneficiaries|hours?|lots?|sites?)\b(?:\s*[×x]\s*\d+\s*hours?(?: per day)?)?"
    r"|\baged?\s+\d+\s*(?:[–-]|to)\s*\d+", re.I)
_LATE_VERB = re.compile(r"\b(shall|will|would|must)\s+not\s+be\s+(considered|accepted|evaluated|opened|received)\b.*", re.I)


def _quantities(docs, exclude: list[str]) -> list[dict]:
    """Stated quantities and durations (sessions, days, hours, ages ...) in
    their own words, each once, with a short verbatim window and reference.
    Inconsistent statements are all shown as published -- never reconciled."""
    out, keys = [], set()
    excl = [pdg.fold(e) for e in exclude if e]
    parts = [dict(s, text=p.strip()) for s in pdg.located_sentences(docs)
             for p in re.split(r"\s+-\s+(?=[A-Z])", s["text"]) if p.strip()]  # inline bullets
    for s in parts:
        text = s["text"]
        ms = [m for m in _QTY.finditer(text) if pdg.fold(m.group(0)) not in keys]
        if not ms or any(pdg.fold(text)[:60] in e for e in excl):
            continue
        for m in ms:
            keys.add(pdg.fold(m.group(0)))
        if len(text) <= 180:
            frag = text
        else:
            a, b = ms[0].start(), ms[-1].end()
            lo = text.rfind(" ", 0, max(0, a - 55)) + 1 if a > 60 else 0
            hi = text.find(" ", b + 45) if len(text) > b + 50 else len(text)
            hi = len(text) if hi < 0 else hi
            frag = ("…" if lo else "") + text[lo:hi].strip() + ("…" if hi < len(text) else "")
        out.append({"text": frag, "doc": s["doc"], "page": s.get("page"), "sheet": s.get("sheet")})
    return out[:5]


_DOC_NOUN = re.compile(r"\b(forms?|certificates?|letters?|proposals?|cv|cvs|resumes?|profiles?|statements?|"
                       r"declarations?|licen[cs]es?|registrations?|bonds?|guarantees?|copy|copies|quotations?|"
                       r"offers?|plans?|methodology|portfolios?|references?|evidence|documents?|"
                       r"schedules?|samples?|undertakings?|affidavits?|pricing|price)\b", re.I)


def _required_docs(secs: dict) -> list[dict]:
    """Submission documents as the buyer numbered them: name + its own
    sub-points (e.g. Quotation -> rate basis). Method, deadline, subject-line
    and late-submission sentences are not documents."""
    skip = re.compile(r"no later than|after the deadline|subject line|via e-?mail|submit the following", re.I)
    out: list[dict] = []
    for s in secs.get("submission") or []:
        items = [it for it in s["items"] if not (pdg.EMAIL.search(it["text"]) or skip.search(it["text"]))]
        if not any(it.get("numbered") for it in items):
            continue
        cur = None
        for it in items:
            if it.get("numbered"):
                cur = {"name": doc_name(it["text"]), "text": it["text"], "details": [], **{k: it.get(k) for k in ("doc", "page", "sheet")}}
                out.append(cur)
            elif cur is not None and not it["text"].endswith(":"):
                cur["details"].append(it)
    if out:
        return out
    for s in secs.get("submission") or []:  # un-numbered lists: each line is one document
        for it in s["items"]:
            if pdg.EMAIL.search(it["text"]) or skip.search(it["text"]) or it["text"].endswith(":"):
                continue
            if not _DOC_NOUN.search(it["text"]):
                continue  # "General Submission Requirements" is a heading, not a document
            if len(it["text"]) <= 120:
                out.append({"name": doc_name(it["text"]), "text": it["text"], "details": [],
                            **{k: it.get(k) for k in ("doc", "page", "sheet")}})
    return out


def build_facts(*, bid: dict, fast_result: dict, documents: list[tuple[str, str]],
                files: list[tuple[str, bytes]] | None = None,
                previous_result: dict | None = None, previous_doc_names: list[str] | None = None,
                analysis_date: str | None = None, run_id: int | None = None,
                coverage: dict | None = None) -> dict:
    """Verified fact model shared by both reports. `coverage` is the FAST
    run's telemetry summary (coverage_gaps / split_exhausted_rows): passages
    the extraction could not read in full are disclosed, never hidden."""
    import bid_identity
    import source_translation as sx
    import workbook_intelligence as wbi
    r = fast_result or {}
    originals = list(documents or [])
    # Arabic / bilingual packages: every deterministic step below reads the
    # line-linked English view (checked renderings of the original lines,
    # same markers and page/sheet positions), and FAST's Arabic excerpts are
    # replaced by the checked rendering of the original lines that contain
    # them. Unsupported renderings are left out, so nothing below can
    # publish an unchecked translation. English packages are untouched.
    translations = r.get("source_translations") or {}
    bilingual = bool(translations.get("documents")) or any(
        pdg._ARABIC_CHAR.search(t or "") for _, t in originals)
    if bilingual:
        # saved renderings re-checked with the current verifier (no model call)
        translations = sx.revalidate(translations, originals)
        docs = sx.english_view(originals, translations)
        r = sx.localize_fast_result(r, originals, translations)
        if previous_result:
            previous_result = sx.localize_fast_result(
                previous_result, originals,
                sx.revalidate(previous_result.get("source_translations") or translations))
    else:
        docs = originals
    secs = pdg.by_key(pdg.sections(docs))
    sub = pdg.submission_instructions(docs)

    # ── identification ──
    try:
        import canonical_procurement as cp
        merged = cp.merge_identity_fields(r.get("doc_metadata_by_doc") or {})
    except Exception:
        merged = {}
    title = bid.get("title") if bid.get("title") not in (None, "", bid_identity.PLACEHOLDER_TITLE) else None
    title = title or merged.get("title") or bid.get("title")
    org = bid.get("client") if bid.get("client") not in (None, "", bid_identity.PLACEHOLDER_CLIENT) else None
    org = org or (merged.get("client") if merged.get("client") and (
        pdg.corpus_contains(docs, merged["client"])
        or (bilingual and sx.original_grounded(merged.get("client_original"), originals))) else None)
    if bilingual and title and bid_identity._words(title) == [] and merged.get("title"):
        title = merged["title"]  # an Arabic-only bid title cannot be printed in the English report
    reference = merged.get("file_number") or bid.get("file_number")
    if reference and not pdg.corpus_contains(docs, str(reference)):
        reference = bid.get("file_number") or None
    # "received ... at the proper location" is about where bids arrive, not where the work happens
    location = next((s for s in pdg.find_sentences(docs, _LOCATION.pattern, 3) if len(s["text"]) <= 180
                     and not _RECEIPT.search(s["text"]) and not s["text"].isupper()), None)  # not a table header
    if location:
        location = dict(location, kind=location_kind(location["text"]))

    # ── deadline: extracted (with addendum authority) + manual override ──
    dl = ct.effective_deadline(r, docs)
    manual = bid.get("submission_deadline")
    deadline = {
        "extracted": dl["value"], "extracted_ref": dl["ref"], "amended_from": dl["amended_from"],
        "conflict": dl["conflict"], "manual": manual if manual and str(manual)[:10] != str(dl["value"] or "")[:10] else None,
        "unverified": dl.get("unverified"),
    }
    deadline["effective"] = deadline["manual"] or dl["value"]

    # ── overview / scope / delivery ──
    overview = _items(secs, "overview", drop_leadin=True)[:3]
    ov_sents = [dict(it, text=s) for it in overview for s in sentences_of(it["text"])]
    about = _items(secs, "about", drop_leadin=True)
    scope = _items(secs, "scope")
    if not scope:
        for q in r.get("requirements") or []:
            ref = _ref_from(q.get("source_refs"))
            if "scope" in (q.get("description") or "").lower() and _verified(docs, ref["excerpt"]):
                scope.append({"text": ref["excerpt"], **ref})
    def _deliverable(it):
        return (it.get("listed") or not _is_subhead(it["text"])) and not _is_column_header(it["text"])
    deliverables = [it for it in _items(secs, "deliverables", drop_leadin=True) if _deliverable(it)]
    # The first deliverables list is the one the snapshot summarises; long
    # packages repeat deliverables per phase with full descriptions (kept for
    # the Assessment).
    primary = next(([it for it in s["items"] if _deliverable(it)
                     and not (it["text"].endswith(":") and len(it["text"]) < 120)]
                    for s in secs.get("deliverables") or []
                    if any(_deliverable(it) for it in s["items"])), [])
    timeline = _items(secs, "timeline")
    qualifications = [it for it in _items(secs, "qualifications", drop_leadin=True) if not _is_subhead(it["text"])]
    general = _items(secs, "general", drop_leadin=True)

    # ── evaluation ──
    criteria = []
    import procurement_normalization as _pn  # saved snapshots predate the FAST-side merge
    for ec in _pn.dedupe_evaluation_criteria(r.get("evaluation_criteria") or []):
        ref = _ref_from(ec.get("source_refs"))
        if not _verified(docs, ref["excerpt"]):
            continue
        w = ec.get("weight")
        if w and pdg.fold(str(w)) not in pdg.fold(ref["excerpt"]):
            w = None  # weight not visible in its own excerpt -> not published
        criteria.append({"stage": pdg.norm(ec.get("stage")), "weight": w, "parent": ec.get("parent_stage"),
                         "threshold": ec.get("threshold"), "ref": ref, "role": ec.get("evaluation_role")})
    # Pass/fail eligibility conditions are not weighted evaluation criteria:
    # they are reported with the qualifications, in the buyer's own words and
    # with their own (original-language) reference -- never in the weights table.
    gates = [c for c in criteria if _is_eligibility_gate(c, criteria)]
    criteria = resolve_criteria([c for c in criteria if not any(c is g for g in gates)])
    for c in criteria:
        c.pop("role", None)
    for g in gates:
        item = {"text": g["ref"]["excerpt"] or g["stage"], **g["ref"], "label": g["stage"], "kind": "eligibility"}
        if not any(ct._similar(item["text"], q["text"]) > 0.6 or pdg.fold(item["text"]) in pdg.fold(q["text"])
                   or pdg.fold(q["text"]) in pdg.fold(item["text"]) for q in qualifications):
            qualifications.append(item)
    eval_text = [] if criteria else _items(secs, "evaluation")

    # ── submission documents; pricing kept apart from the document list ──
    required = _required_docs(secs)
    pricing = []
    for d in required:
        if _PRICING.search(d["name"]):
            pricing += d["details"]
    pricing += [it for it in _items(secs, "pricing", drop_leadin=True) if it not in pricing and not _is_subhead(it["text"])]
    budget = [s for s in pdg.located_sentences(docs) if _BUDGET.search(s["text"]) and _AMOUNT.search(s["text"])
              and not _NOT_BUDGET.search(s["text"])][:2]
    payment = _items(secs, "payment", drop_leadin=True)
    securities = [s for s in pdg.located_sentences(docs) if len(s["text"]) <= 400 and _states_security(s["text"])][:3]
    clauses = []
    for cc in r.get("commercial_clauses") or []:
        ref = _ref_from(cc.get("source_refs"))
        if not _verified(docs, ref["excerpt"]):
            continue
        if "PAYMENT" in (cc.get("clause_kind") or "") and payment:
            continue
        clauses.append({"topic": pdg.norm(cc.get("topic")), "text": ref["excerpt"], "ref": ref})
    clauses += [{"topic": None, "text": it["text"], "ref": it} for it in _items(secs, "contract", drop_leadin=True)]
    stated = [it["text"] for it in qualifications + general + payment + pricing]
    clauses = [c for c in clauses if not any(ct._similar(c["text"], t) > 0.6 or pdg.fold(t) in pdg.fold(c["text"])
                                             or pdg.fold(c["text"]) in pdg.fold(t) for t in stated)]
    key_dates = []
    for m in r.get("canonical_milestones") or []:
        ref = _ref_from(m.get("source_refs"))
        if m.get("normalized_date_start") and _verified(docs, ref["excerpt"]) and \
                (m.get("label") or "").upper() != "SUBMISSION_DEADLINE":
            key_dates.append({"label": (m.get("label") or "").replace("_", " ").title(),
                              "value": m["normalized_date_start"], "ref": ref})

    quantities = _quantities(docs, exclude=[p["text"] for p in pricing])

    # ── changes, workbooks ──
    changes = ct.detect_changes(r, docs, previous_result, previous_doc_names)
    workbooks = wbi.analyse_package(files or [], docs) if files else []

    # ── material facts: candidates, each printed at most once by the renderer ──
    matters = []
    for c in changes:
        if c["kind"] in ("NEW", "UPDATED") and c["topic"] != "Submission deadline":
            matters.append({"text": str(c["current"]), "kind": c["kind"], "ref": c.get("source")})
    for c in changes:
        if c["kind"] == "CONFLICT":
            matters.append({"text": f"The documents state different values for {c['topic'].lower()} "
                                    f"({c['current']} / {c['previous']}); no amendment resolving this was found.",
                            "kind": "CONFLICT", "ref": c.get("source")})
    for s in pdg.located_sentences(docs):
        if _TIME_BOUND.search(s["text"]) and not pdg.EMAIL.search(s["text"]):
            matters.append({"text": s["text"], "kind": None, "ref": s})
    for s in pdg.located_sentences(docs):
        if _COST_BEARING.search(s["text"]):
            matters.append({"text": s["text"], "kind": None, "ref": s})
            break
    for it in pricing:
        if _INCLUSIVE.search(it["text"]):
            matters.append({"text": it["text"], "kind": None, "ref": it})
            break

    doc_basis = []
    for name, text in docs:
        pages = sorted({ln["page"] for ln in pdg.located_lines([(name, text)]) if ln.get("page")})
        doc_basis.append({"name": name, "amending": ct.is_amending_document(name, text),
                          "pages": len(pages) or None, "workbook": wbi.is_workbook(name)})

    facts = {
        "bid_id": bid.get("id"), "run_id": run_id,
        "identity": {"title": title, "organization": org, "reference": reference, "location": location},
        "deadline": deadline, "submission": sub, "required_docs": required, "key_dates": key_dates,
        "overview": overview, "synopsis": ov_sents[:2], "about": about, "scope": scope,
        "deliverables": deliverables, "deliverables_primary": primary, "timeline": timeline, "qualifications": qualifications, "general": general,
        "quantities": quantities, "criteria": criteria, "eval_text": eval_text,
        "pricing": pricing, "budget": budget, "securities": securities, "payment": payment, "clauses": clauses,
        "changes": changes, "workbooks": workbooks, "matters": matters,
        "documents": doc_basis, "analysis_date": analysis_date or date.today().isoformat(),
        "languages": r.get("source_languages") or (sx.document_languages(originals) if bilingual else {}),
        "translation_note": sx.payload_summary_line(translations) if bilingual else None,
        "coverage_note": coverage_limitation(coverage),
        "mode": "digest",
    }
    # Typed, source-verified facts from the FAST run (procurement_facts.py)
    # replace every keyword-based classification above. Older runs, which
    # have none, keep the document-digest reading.
    verified = _report_facts(r, docs, context=[title, org, reference])
    if verified and verified["facts"]:
        _apply_report_facts(facts, verified)
        # the reports now rest on the facts pass: its unread passages are the
        # limitation to disclose (the extraction pass's own gaps affected
        # facts that are no longer printed from it)
        facts["coverage_note"] = coverage_limitation({"coverage_gaps": verified["coverage_gaps"]})
    if bilingual:
        # Original Arabic evidence for every located English statement, for
        # display in the app (the PDFs stay English).
        idx = sx.EvidenceIndex(originals, translations)
        if not translations.get("documents"):
            facts["translation_note"] = ("Arabic text in the source documents could not be rendered in English "
                                         "for this analysis; statements from it are not included. Re-run the "
                                         "analysis to include them.")
        for d in facts["documents"]:
            d["language"] = facts["languages"].get(d["name"])
        sx.annotate_with_originals({k: v for k, v in facts.items() if k not in ("documents", "workbooks")}, idx)
    return facts


def _report_facts(r: dict, docs: list[tuple[str, str]], *, context: list | None = None) -> dict | None:
    import procurement_facts as pf
    payload = r.get("report_facts")
    if not isinstance(payload, dict) or not payload.get("facts"):
        return None
    return pf.verify(payload, docs, context=[str(c) for c in context or [] if c])


def _apply_report_facts(facts: dict, verified: dict) -> None:
    """Fill the report fields from verified, model-classified facts. A field
    with no fact stays empty -- nothing is filled in from keyword matches."""
    import procurement_facts as pf
    cat = pf.by_category(verified)
    g = lambda k: list(cat.get(k) or [])  # noqa: E731
    loc = g("DELIVERY_LOCATION")
    facts["identity"]["location"] = dict(loc[0], kind="delivery") if loc else None
    facts["synopsis"] = [verified["assignment"]] if verified.get("assignment") else []
    facts["overview"] = []
    facts["about"] = g("BUYER_CONTEXT")
    facts["scope"] = g("SCOPE")
    facts["deliverables"] = facts["deliverables_primary"] = g("DELIVERABLE")
    facts["schedule"] = g("SCHEDULE")
    facts["timeline"], facts["quantities"], facts["general"] = [], [], []
    facts["eligibility"] = g("ELIGIBILITY")
    facts["qualifications"] = g("QUALIFICATION")
    facts["eval_text"] = g("EVALUATION")
    facts["award"] = g("AWARD")
    facts["proposal_content"] = g("PROPOSAL_CONTENT")
    facts["required_docs"] = [{"name": it["text"], "details": [], "doc": it["doc"], "page": it["page"],
                               "sheet": it.get("sheet")} for it in facts["proposal_content"]]
    sub = facts["submission"]
    sub.update(channel=None, method_sentences=[], emails=[], contact_emails=[], subject_rule=None,
               late_rule=None, methods=g("SUBMISSION_METHOD"), rules=g("SUBMISSION_DEADLINE") + g("SUBMISSION_RULE"),
               questions=g("CLARIFICATION"))
    facts["pricing"] = g("PRICING")
    facts["budget"] = g("BUDGET")
    facts["payment"] = g("PAYMENT")
    facts["securities"] = g("GUARANTEE")
    facts["clauses"] = [{"topic": None, "text": it["text"], "ref": it} for it in g("CONTRACT_TERM")]
    facts["matters"] = [m for m in facts["matters"] if m.get("kind")] + [
        {"text": it["text"], "kind": None, "ref": it} for it in g("OTHER")]
    facts["mode"] = "facts"


# ═══════════════════════════════════════════════════════════════════════
# RENDERING HELPERS
# ═══════════════════════════════════════════════════════════════════════

def _sec(n: int, title: str) -> list:
    return [Paragraph(f"{n}. {esc(title)}", _st["sec"]), base.hr(GOLD, 0.9, 0, 5)]


def _rt(ref) -> str:
    r = ref_text(ref) if ref else ""
    return f' <font size="7" color="#6B675F">[{esc(r)}]</font>' if r else ""


def _lines(items: list[dict], shown: _Shown, *, n: int = 150, limit: int | None = None) -> list:
    """One concise line per item, in the document's words, each with its
    reference; items already printed elsewhere in the report are skipped."""
    out = []
    fresh = [it for it in items if not shown.seen(it["text"])]
    for it in fresh[:limit] if limit else fresh:
        out.append(_RLParagraph(f"{esc(brief(it['text'], n))}{_rt(it)}", _st["bul"], bulletText="•"))
        shown.add(it["text"])
    return out


def _sub(text: str) -> Paragraph:
    return Paragraph(f"<b>{esc(text)}</b>", _st["sub"])


def _kt(items: list) -> KeepTogether:
    """KeepTogether without nesting (nested KeepTogether forces page breaks)."""
    flat = []
    for it in items:
        flat.extend(it._content if isinstance(it, KeepTogether) else [it])
    return KeepTogether(flat)


def _headed(title: str, blocks: list) -> list:
    """A sub-heading kept on the same page as its first block; [] if empty."""
    blocks = [b for b in blocks if b is not None]
    return [_kt([_sub(title), blocks[0]])] + blocks[1:] if blocks else []


def _topic_line(group: dict, shown: _Shown) -> Paragraph | None:
    """'Heading — Label; Label; Label' for a labelled list, else None."""
    labels = [label_of(it["text"])[0] for it in group["items"]]
    if not group["items"] or any(lab is None for lab in labels):
        return None
    shown.add(*[it["text"] for it in group["items"]])
    head = f"<b>{esc(group['heading'])}</b> — " if group["heading"] else ""
    return _RLParagraph(f"{head}{esc('; '.join(labels))}{_rt(group['items'][0])}", _st["bul"], bulletText="•")


def _refs_line(items: list[dict]) -> Paragraph | None:
    labels = []
    for it in items:
        lab = ref_text(it)
        if lab and lab not in labels:
            labels.append(lab)
    return Paragraph("Source: " + esc("; ".join(labels)), _st["ref"]) if labels else None


def _table(header, rows, widths) -> Table:
    data = [[Paragraph(esc(h), _st["head"]) for h in header]]
    for row in rows:
        data.append([c if not isinstance(c, str) else Paragraph(c, _st["cell"]) for c in row])
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NIGHT),
        ("TOPPADDING", (0, 0), (-1, -1), 3.2), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.2),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, RULE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [PAPER, BAND]),
    ]))
    return t


def _kv(rows: list[tuple[str, str]]) -> Table:
    data = [[Paragraph(esc(k).upper(), S["card_label"]), Paragraph(v, _st["cell"])] for k, v in rows]
    t = Table(data, colWidths=[1.55 * inch, BODY_W - 1.55 * inch])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
        ("LEFTPADDING", (0, 0), (0, -1), 0),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, RULE),
    ]))
    return t


def _label(kind: str) -> str:
    color = {"NEW": GREEN, "UPDATED": AMBER, "CONFLICT": RED, "UNVERIFIED": AMBER,
             "COVERAGE LIMITATION": AMBER}.get(kind, "#6B675F")
    text = {"NEW": "NEW INFORMATION", "UPDATED": "UPDATED INFORMATION", "CONFLICT": "UNRESOLVED CONFLICT",
            "UNVERIFIED": "UNVERIFIED (OCR)"}.get(kind, kind)
    return f'<font name="BodyMed" color="{color}" size="7.2">{text}</font>'


def _title_block(kicker: str, f: dict) -> Table:
    ident = f["identity"]
    sub = " · ".join(x for x in (ident.get("organization"), ident.get("reference") and f"Ref. {ident['reference']}") if x)
    rows = [[Paragraph(esc(kicker), _st["t_kick"])],
            [Paragraph(esc(ident.get("title") or "Opportunity"), _st["t_title"])]]
    if sub:
        rows.append([Paragraph(esc(sub), _st["t_sub"])])
    t = Table(rows, colWidths=[BODY_W])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), NIGHT),
        ("LEFTPADDING", (0, 0), (-1, -1), 14), ("RIGHTPADDING", (0, 0), (-1, -1), 14),
        ("TOPPADDING", (0, 0), (0, 0), 12), ("BOTTOMPADDING", (0, -1), (-1, -1), 12),
        ("TOPPADDING", (0, 1), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -2), 0),
        ("LINEBELOW", (0, -1), (-1, -1), 2, GOLD),
    ]))
    return t


def _deadline_value(f: dict) -> str:
    d = f["deadline"]
    parts = []
    if d["manual"]:
        parts.append(f"<b>{esc(fmt_date(d['manual']))}</b> "
                     f'<font color="{AMBER}" size="7.4">MANUALLY ENTERED BY PHOENIX</font>')
        if d["extracted"]:
            parts.append(f'<font size="7.6" color="#6B675F">Documents state {esc(fmt_date(d["extracted"]))} '
                         f'[{esc(ref_text(d["extracted_ref"]))}]</font>')
    elif d["extracted"]:
        parts.append(f"<b>{esc(fmt_date(d['extracted']))}</b>{_rt(d['extracted_ref'])}")
    if d.get("unverified") == "OCR" and d["extracted"]:
        parts.append(f'{_label("UNVERIFIED")} <font size="7.6">read by OCR from a scanned page; '
                     f'no checked sentence states it -- confirm in the original document</font>')
    if d["amended_from"]:
        parts.append(f'{_label("UPDATED")} <font size="7.6">previously {esc(fmt_date(d["amended_from"]["value"]))} '
                     f'[{esc(ref_text(d["amended_from"]["ref"]))}]</font>')
    if d["conflict"]:
        vals = "; ".join(f"{fmt_date(c['value'])} [{ref_text(c['ref'])}]" for c in d["conflict"])
        parts.append(f'{_label("CONFLICT")} <font size="7.6">{esc(vals)}</font>')
    return "<br/>".join(parts)


def _glance_rows(f: dict, shown: _Shown, *, synopsis_sentences: int, identity: bool = True) -> list[tuple[str, str]]:
    ident = f["identity"] if identity else {"location": f["identity"].get("location")}
    rows = []
    if ident.get("organization"):
        rows.append(("Buyer", esc(ident["organization"])))
    if ident.get("title"):
        rows.append(("Title", esc(ident["title"])))
    if ident.get("reference"):
        rows.append(("Reference", esc(ident["reference"])))
    if ident.get("location"):
        loc = ident["location"]
        rows.append((_LOCATION_LABEL[loc.get("kind") or "unspecified"], f"{esc(loc['text'])}{_rt(loc)}"))
        shown.add(loc["text"])
    dv = _deadline_value(f)
    if dv:
        rows.append(("Submission deadline", dv))
    syn = f["synopsis"][:synopsis_sentences]
    if syn:
        rows.append(("Synopsis", esc(" ".join(s["text"] for s in syn)) + _rt(syn[0])))
        shown.add(*[s["text"] for s in syn])
    return rows


def _criteria_table(f: dict, *, compact: bool) -> list:
    if not f["criteria"]:
        return []
    rows, notes = [], []
    for c in f["criteria"]:
        stage = clip(c["stage"], 110) if compact else c["stage"]
        name = ("&nbsp;&nbsp;&nbsp;" * c["level"] + "— " + esc(stage)) if c["level"] else f"<b>{esc(stage)}</b>"
        w = esc(c["weight"] or "—")
        if c["level"] and c["weight"] and c.get("basis") == "within":
            w += f' <font size="6.8" color="#6B675F">of {esc(c["parent"])}</font>'
        rows.append([name, w, Paragraph(esc(ref_text(c["ref"])), _st["cell_s"])])
    for p in f["criteria"]:
        if p.get("children_basis") == "overall":
            kids = [c for c in f["criteria"] if c["level"] and pdg.fold(c.get("parent") or "") == pdg.fold(p["stage"])]
            notes.append(f"{p['stage']} {p['weight']} = " + " + ".join(str(k["weight"]) for k in kids))
    out = [_table(["Criterion", "Weight", "Source"], rows, [BODY_W * 0.66, BODY_W * 0.14, BODY_W * 0.20])]
    if notes:
        out.append(Paragraph("Sub-criterion weights are shares of the total score, as their sums show: "
                             + esc("; ".join(notes)) + ".", _st["note"]))
    return [KeepTogether(out)] if len(rows) <= 14 else out


def _late_text(sub: dict) -> str | None:
    s = sub.get("late_rule")
    if not s:
        return None
    m = _LATE_VERB.search(s["text"])
    return (m.group(0)[0].upper() + m.group(0)[1:]).rstrip(".") + "." if m else brief(s["text"], 140)


def _subject_text(sub: dict) -> str | None:
    s = sub.get("subject_rule")
    if not s:
        return None
    t = s["text"]
    return pdg.norm(t.split(":", 1)[1]).rstrip(".") if ":" in t and len(t.split(":", 1)[1]) < 120 else brief(t, 140)


def _method_text(sub: dict) -> str | None:
    if not (sub.get("channel") or sub.get("method_sentences")):
        return None
    ms = (sub.get("method_sentences") or [None])[0]
    if sub.get("emails") and sub.get("channel") == "Email":
        # Referenced to the sentence that states the address itself.
        ms = sub["emails"][0].get("sentence") or ms
        val = f"<b>{esc(sub.get('channel') or 'Email')}</b> to " + ", ".join(esc(e["email"]) for e in sub["emails"])
    else:
        val = f"<b>{esc(sub.get('channel') or 'As instructed')}</b>" + (f" — {esc(brief(ms['text'], 160))}" if ms else "")
    return val + _rt(ms)


def _contact_text(sub: dict) -> str | None:
    """E-mail addresses printed as contact details (not as the place the offer
    is sent), so they are never mistaken for the submission method."""
    cs = [c for c in sub.get("contact_emails") or [] if c["email"].lower() not in
          {e["email"].lower() for e in sub.get("emails") or []}]
    if not cs:
        return None
    return ", ".join(esc(c["email"]) for c in cs) + _rt(cs[0].get("sentence") or cs[0])


def _research_status_line(research: dict | None, context: list[str] | None = None) -> str:
    state = (research or {}).get("status") or "NONE"
    if state == "COMPLETE":
        n = len(research_items_for_display(research, context))
        return f"{n} verified external finding(s) — section 3" if n else "Completed; no verifiable public sources found"
    return {"RUNNING": "In progress when this report was generated",
            "FAILED": "Attempted; did not complete",
            "SKIPPED": "Not run — buyer organisation not identified"}.get(state, "Not yet run for this analysis")


def coverage_limitation(summary: dict | None) -> str | None:
    """Plain-language statement of the passages FAST could not read in full,
    from a run's telemetry summary; None when the whole package was read.
    Runs analysed before page ranges were recorded report the count only."""
    s = summary or {}
    gaps = [g for g in s.get("coverage_gaps") or [] if isinstance(g, dict)]
    count = len(gaps) or int(s.get("split_exhausted_rows") or 0)
    if not count:
        return None

    def first_page(p):
        try:
            return int(str(p).split("-")[0])
        except ValueError:
            return 10 ** 6
    pages = sorted({str(g["pages"]) for g in gaps if g.get("pages")}, key=first_page)
    docs = sorted({g.get("filename") for g in gaps if g.get("filename")})
    where = ""
    if pages:
        where = f" (page{'s' if len(pages) > 1 or '-' in pages[0] else ''} {', '.join(pages)}"
        where += f" of {docs[0]})" if len(docs) == 1 else ")"
    elif not gaps:
        where = " (the pages concerned were not recorded for this analysis)"
    return (f"FAST could not read {count} passage{'s' if count != 1 else ''} of the source in full{where}. "
            f"Requirements, contract conditions or dates on those pages may be missing from what FAST extracted; "
            f"check those pages in the documents before relying on anything being absent.")


_BASIS_DIGEST = "Statements are the documents' own words, with page/sheet references;"
_BASIS_FACTS = ("Each statement summarises the documents and was checked against the quoted source text on the "
                "cited page; every figure, date and address in it appears in that text.")


def _basis_note(f: dict, extra: str = "") -> Paragraph:
    names = []
    for d in f["documents"]:
        tag = []
        if d["pages"]:
            tag.append(f"{d['pages']} p.")
        if d["amending"]:
            tag.append("amending document")
        if d["workbook"]:
            tag.append("workbook")
        alias = (getattr(_ctx, "alias", None) or {}).get(d["name"])
        if d.get("language") in ("ar", "mixed"):
            tag.append("Arabic" if d["language"] == "ar" else "Arabic/English")
        shown_name = d["name"]
        if pdg._ARABIC_CHAR.search(shown_name):  # listed by alias; the name itself is shown in the app
            shown_name = "file with Arabic name" + (f" (.{shown_name.rsplit('.', 1)[-1]})" if "." in shown_name else "")
        names.append((f"{alias} " if alias else "") + shown_name + (f" ({', '.join(tag)})" if tag else ""))
    txt = (f"<b>Document basis.</b> {esc('; '.join(names))}. Analysis date {esc(fmt_date(f['analysis_date']))}. "
           f"{_BASIS_FACTS + ' Values' if f.get('mode') == 'facts' else _BASIS_DIGEST + ' values'} entered by a Phoenix "
           f"user and external sources are labelled as such. Nothing here is a recommendation on whether to bid."
           f"{(' ' + esc(f['translation_note'])) if f.get('translation_note') else ''}{extra}")
    return Paragraph(txt, _st["note"])


def _on_page(label):
    def draw(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN, 0.6 * inch, PAGE_W - MARGIN, 0.6 * inch)
        canvas.setFont("BodyMed", 7.2)
        canvas.setFillColor(MUTED)
        canvas.drawString(MARGIN, 0.43 * inch, f"PHOENIX BID INTELLIGENCE · {label}")
        canvas.setFont("Body", 7.2)
        canvas.drawRightString(PAGE_W - MARGIN - 0.3 * inch, 0.43 * inch, latin_only(getattr(doc, "_px_header", ""))[:60])
        canvas.setFillColor(GOLD)
        canvas.setFont("BodyMed", 7.6)
        canvas.drawRightString(PAGE_W - MARGIN, 0.43 * inch, str(canvas.getPageNumber()))
        canvas.restoreState()
    return draw


def _build(story: list, label: str, f: dict) -> bytes:
    buf = io.BytesIO()
    ident = f["identity"]
    header = " · ".join(x for x in (ident.get("organization"), ident.get("reference")) if x)
    doc = BaseDocTemplate(buf, pagesize=base.LETTER, leftMargin=MARGIN, rightMargin=MARGIN,
                          topMargin=0.6 * inch, bottomMargin=0.8 * inch,
                          title=latin_only(f"{label.title()} — {ident.get('title') or 'Opportunity'}"),
                          author="Phoenix Bid Intelligence", invariant=1)
    doc._px_header = header
    doc.addPageTemplates([PageTemplate(id="Body", frames=[Frame(
        MARGIN, 0.8 * inch, BODY_W, PAGE_H - 1.4 * inch, id="body", leftPadding=0, rightPadding=0,
        topPadding=0, bottomPadding=0)], onPage=_on_page(label))])
    doc.build(story)
    return buf.getvalue()


def _emit(story: list, head: list, blocks: list) -> bool:
    blocks = [b for b in blocks if b is not None]
    if not blocks:
        return False  # never an empty section
    story.append(_kt(head + blocks[:1]))
    story.extend(blocks[1:])
    return True


def required_document_names(f: dict) -> list[str]:
    return [d["name"] for d in f.get("required_docs") or []]


def report_filename(f: dict, kind: str) -> str:
    ident = f["identity"]
    key = ident.get("reference") or ident.get("title") or f"Bid_{f.get('bid_id')}"
    key = re.sub(r"[^A-Za-z0-9._-]+", "_", str(key)).strip("._-")[:70] or "Bid"
    return f"{key}_{'Opportunity_Snapshot' if kind == SNAPSHOT else 'Bid_Opportunity_Assessment'}.pdf"


_SNAPSHOT_SCOPE_GROUPS = 6  # the snapshot shows the first scope topics; the Assessment lists them all


def _scope_blocks(f: dict, shown: _Shown, *, detailed: bool) -> list:
    """Scope as the buyer's own topic labels (FAST) or one line per item (FULL)."""
    out = []
    groups = _groups(f["scope"])
    for g in groups if detailed else groups[:_SNAPSHOT_SCOPE_GROUPS]:
        line = None if detailed else _topic_line(g, shown)
        if line is not None:
            out.append(line)
            continue
        if g["heading"]:
            out.append(Paragraph(f"<i>{esc(g['heading'])}</i>", _st["body"]))
        out += _lines(g["items"], shown, n=160 if detailed else 120, limit=None if detailed else 5)
    if not detailed and len(groups) > _SNAPSHOT_SCOPE_GROUPS:
        out.append(Paragraph(f"{len(groups) - _SNAPSHOT_SCOPE_GROUPS} further scope topics are set out in the "
                             f"documents and listed in the Bid Opportunity Assessment.", _st["note"]))
    return out


def _req_table(pairs: list[tuple[str | None, dict]], shown: _Shown, *, n: int) -> list:
    """Compact 'Area | Requirement | Source' table: the item's own label as
    the area, its first sentence (cut at a clause boundary) as the summary."""
    rows = []
    for area, it in pairs:
        if shown.seen(it["text"]):
            continue
        lab, rest = label_of(it["text"])
        rows.append([f"<b>{esc(lab or area or '')}</b>", esc(brief(rest, n)),
                     Paragraph(esc(ref_text(it)), _st["cell_s"])])
        shown.add(it["text"])
    if not rows:
        return []
    return [_table(["Area", "Requirement (summary)", "Source"], rows, [BODY_W * 0.25, BODY_W * 0.62, BODY_W * 0.13])]


def _deliverables_block(f: dict, shown: _Shown, *, primary: bool = False) -> list:
    source = f.get("deliverables_primary") if primary and f.get("deliverables_primary") else f["deliverables"]
    items = [it for it in source if not shown.seen(it["text"])]
    if not items:
        return []
    if primary and len(source) < len(f["deliverables"]):
        return _deliverables_block(dict(f, deliverables=source), shown) + [Paragraph(
            "Deliverables are described in further detail elsewhere in the documents; the Bid Opportunity "
            "Assessment lists them.", _st["note"])]
    if all(len(it["text"]) <= 90 for it in items):
        shown.add(*[it["text"] for it in items])
        txt = "; ".join(it["text"].rstrip(".") for it in items)
        return [Paragraph(esc(txt) + "." + _rt(items[0]), _st["body"])]
    return _lines(items, shown, n=140)


def _quantity_block(f: dict, shown: _Shown) -> list:
    items = [q for q in f["quantities"] if not shown.seen(q["text"].strip("…"))]
    if not items:
        return []
    shown.add(*[q["text"].strip("…") for q in items])
    return [_RLParagraph(f"{esc(q['text'])}{_rt(q)}", _st["bul"], bulletText="•") for q in items]


def _material_facts(f: dict, shown: _Shown, limit: int) -> list:
    out = []
    for m in f["matters"]:
        if len(out) >= limit or shown.seen(m["text"]):
            continue
        label = (_label(m["kind"]) + " ") if m.get("kind") else ""
        out.append(_RLParagraph(f"{label}{esc(brief(m['text'], 200))}{_rt(m.get('ref'))}", _st["bul"], bulletText="•"))
        shown.add(m["text"])
    return out


# ═══════════════════════════════════════════════════════════════════════
# FAST -- OPPORTUNITY SNAPSHOT
# ═══════════════════════════════════════════════════════════════════════

def render_snapshot(f: dict) -> dict:
    if f.get("mode") == "facts":
        return _render_snapshot_facts(f)
    _set_alias(f)
    shown = _Shown()
    story = [_title_block("FAST · OPPORTUNITY SNAPSHOT", f), Spacer(1, 8)]
    n = 0

    def section(title, blocks):
        nonlocal n
        if [b for b in blocks if b is not None]:
            n += 1
            _emit(story, _sec(n, title), blocks)

    # 1. Opportunity at a Glance
    section("Opportunity at a Glance", [_kv(_glance_rows(f, shown, synopsis_sentences=1))])
    if f.get("coverage_note"):
        story.append(Paragraph(f'{_label("COVERAGE LIMITATION")} {esc(f["coverage_note"])}', _st["note"]))
        story.append(Spacer(1, 4))

    # 2. Scope and Delivery Essentials
    blocks = []
    sc = _scope_blocks(f, shown, detailed=False)
    if sc:
        blocks += _headed("Services", sc)
    dv = _deliverables_block(f, shown, primary=True)
    if dv:
        blocks += _headed("Deliverables", dv)
    qb = _quantity_block(f, shown)
    if qb:
        blocks += _headed("Stated quantities and durations", qb)
    gen = _lines(f["general"], shown, n=120, limit=4)
    if gen:
        blocks += _headed("Delivery conditions", gen)
    section("Scope and Delivery Essentials", blocks)

    # 3. Evaluation and Eligibility
    blocks = []
    if f["qualifications"]:
        labels = [label_of(q["text"])[0] for q in f["qualifications"]]
        if all(labels):
            shown.add(*[q["text"] for q in f["qualifications"]])
            blocks += _headed("Qualifications sought", [
                Paragraph(esc("; ".join(labels)) + _rt(f["qualifications"][0]), _st["body"])])
        else:
            blocks += _headed("Qualifications sought", _lines(f["qualifications"], shown, n=120, limit=5))
    crit = _criteria_table(f, compact=True)
    if crit:
        blocks += _headed("Evaluation criteria and weights", crit)
    elif f["eval_text"]:
        blocks += _headed("Evaluation criteria and weights", _lines(f["eval_text"], shown, n=140, limit=8))
    section("Evaluation and Eligibility", blocks)

    # 4. Commercial and Submission Essentials
    rows = []
    if f["pricing"]:
        shown.add(*[p["text"] for p in f["pricing"]])
        rows.append(("Pricing basis", "<br/>".join(esc(brief(p["text"], 170)) + _rt(p) for p in f["pricing"][:3])))
    for b in f["budget"]:
        if not shown.seen(b["text"]):
            shown.add(b["text"])
            rows.append(("Budget (as stated)", esc(brief(b["text"], 170)) + _rt(b)))
    secs_ = [x for x in f.get("securities") or [] if not shown.seen(x["text"])]
    if secs_:
        shown.add(*[x["text"] for x in secs_])
        rows.append(("Securities and guarantees", "<br/>".join(esc(brief(x["text"], 170)) + _rt(x) for x in secs_)))
    if f["payment"]:
        shown.add(*[p["text"] for p in f["payment"]])
        rows.append(("Payment", "<br/>".join(esc(brief(p["text"], 230)) + _rt(p) for p in f["payment"][:2])))
    if f["required_docs"]:
        rows.append(("Required documents", esc("; ".join(required_document_names(f))) + _rt(f["required_docs"][0])))
    mt = _method_text(f["submission"])
    if mt:
        rows.append(("Submission method", mt))
    if _contact_text(f["submission"]):
        rows.append(("Contact e-mail (as printed)", _contact_text(f["submission"])))
    if _subject_text(f["submission"]):
        rows.append(("Subject line", esc(_subject_text(f["submission"])) + _rt(f["submission"]["subject_rule"])))
    if _late_text(f["submission"]):
        shown.add(f["submission"]["late_rule"]["text"])
        rows.append(("Late submissions", esc(_late_text(f["submission"])) + _rt(f["submission"]["late_rule"])))
    section("Commercial and Submission Essentials", [_kv(rows)] if rows else [])

    # 5. Additional Material Facts (omitted when there is nothing new to add)
    section("Additional Material Facts", _material_facts(f, shown, 3))

    left = [c for c in f["changes"]]
    if left:
        story.append(Spacer(1, 4))
        story.append(Paragraph(f"Changes introduced by later documents ({len(left)}) are listed with their previous "
                               f"values in the Bid Opportunity Assessment and on the Understand page.", _st["note"]))
    story.append(Spacer(1, 6))
    story.append(_basis_note(f))
    return {"pdf": _build(story, "OPPORTUNITY SNAPSHOT", f), "filename": report_filename(f, SNAPSHOT)}


# ═══════════════════════════════════════════════════════════════════════
# FULL -- BID OPPORTUNITY ASSESSMENT
# ═══════════════════════════════════════════════════════════════════════

def _change_rows(changes: list[dict]) -> list:
    rows = []
    for c in changes:
        cur = fmt_date(c["current"]) if c["topic"] == "Submission deadline" else brief(str(c["current"]), 260)
        what = f'{_label(c["kind"])}<br/><b>{esc(c["topic"])}</b><br/>{esc(cur)}'
        prev = ""
        if c.get("previous"):
            pv = fmt_date(c["previous"]) if c["topic"] == "Submission deadline" else brief(str(c["previous"]), 200)
            prev = esc(pv)
        if c.get("supersedes"):
            prev += f'<br/><font size="6.8" color="#6B675F">[{esc(ref_text(c["supersedes"]))}]</font>'
        rows.append([what, prev or "—", Paragraph(esc(ref_text(c.get("source"))), _st["cell_s"])])
    return rows


def research_items_for_display(research: dict | None, context: list[str] | None = None) -> list[dict]:
    """External findings worth showing: only those whose quoted evidence was
    found on the cited page, minus items that restate the procurement
    documents (e.g. a generic organisation profile already in the ToR)."""
    ctx = [pdg.fold(c) for c in context or []]
    out = []
    for it in (research or {}).get("items") or []:
        if not it.get("evidence_verified"):
            continue
        st = pdg.fold(it.get("statement") or "")
        if it.get("topic") == "profile" and ctx:
            continue
        if any(ct._similar(st, c) > 0.5 for c in ctx):
            continue
        out.append(it)
    return out


def _research_blocks(research: dict | None, context: list[str] | None = None) -> list:
    state = (research or {}).get("status") or "NONE"
    when = fmt_date(str((research or {}).get("researched_at") or (research or {}).get("started_at") or "")[:10])
    if state != "COMPLETE":
        msg = {
            "RUNNING": "External buyer research was in progress when this report was generated. Re-export the "
                       "assessment once it has completed to include its findings.",
            "FAILED": f"External buyer research was attempted{(' on ' + when) if when else ''} but did not complete; "
                      f"it can be re-run from the Full Analysis page. No external findings are included.",
            "SKIPPED": "External buyer research was not run because the buyer organisation is not identified in "
                       "the bid details.",
        }.get(state, "External buyer research has not yet been run for this analysis. It starts when the Full "
                     "Analysis results are opened in Phoenix; re-export the assessment once it has completed.")
        return [Paragraph(esc(msg), _st["note"])]
    items = research_items_for_display(research, context)
    if not items:
        return [Paragraph(f"External buyer research{(' on ' + when) if when else ''} found no public source whose "
                          f"content could be verified to support a relevant fact about this buyer beyond the "
                          f"procurement documents; no external findings are included.", _st["note"])]
    order = list(TOPIC_LABELS)
    rows = []
    for it in sorted(items, key=lambda i: order.index(i.get("topic")) if i.get("topic") in order else len(order)):
        src = esc(clip(it.get("source_title") or "", 80) or it["url"][:60])
        dates = []
        if it.get("as_of"):
            dates.append(f"refers to {esc(it['as_of'])}")
        dates.append(f"published {esc(it['published'])}" if it.get("published") else "publication date not shown")
        ev = clip(it.get("evidence") or "", 200)
        rows.append([f'<font name="BodyMed" size="7.2" color="#6B675F">{esc(TOPIC_LABELS.get(it.get("topic"), "Buyer"))}'
                     f'</font><br/>{esc(it["statement"])}'
                     + (f'<br/><font size="7" color="#6B675F">Source text: “{esc(ev)}”</font>' if ev else ""),
                     Paragraph(f'{src}<br/><font color="#2B5C8A">{esc(it["url"][:90])}</font><br/>'
                               f'{"; ".join(dates)}', _st["cell_s"])])
    carried = " Carried over from an earlier Full Analysis of this bid." if research.get("reused_from_run") else ""
    return [
        Paragraph(f"Targeted web research on {esc(when)}. Each fact was kept only when its quoted source text was "
                  "found on the cited page. Historical facts are dated and do not establish current funding or "
                  f"partnerships; none of this indicates the buyer's preferences.{carried}", _st["note"]),
        _table(["Verified external fact", "Source"], rows, [BODY_W * 0.66, BODY_W * 0.34]),
    ]


TOPIC_LABELS = {"initiative": "Initiative named in the procurement", "programme": "Current programmes",
                "subject": "Work in the opportunity's subject", "partners": "Partnerships & funding",
                "procurement": "Comparable projects or procurements", "news": "Recent news",
                "profile": "Organisation profile"}


def render_assessment(f: dict, *, full_status: str | None = None, research: dict | None = None) -> dict:
    if f.get("mode") == "facts":
        return _render_assessment_facts(f, full_status=full_status, research=research)
    _set_alias(f)
    shown = _Shown()
    story = [_title_block("FULL · BID OPPORTUNITY ASSESSMENT", f), Spacer(1, 8)]
    n = 0

    def section(title, blocks):
        nonlocal n
        if [b for b in blocks if b is not None]:
            n += 1
            _emit(story, _sec(n, title), blocks)

    # 1. Executive Intelligence Summary
    rows = _glance_rows(f, shown, synopsis_sentences=2, identity=False)
    top = [c for c in f["criteria"] if c["level"] == 0 and c["weight"]]
    if top:
        rows.append(("Evaluation basis", esc(" / ".join(f"{c['stage']} {c['weight']}" for c in top)) + _rt(top[0]["ref"])))
    if f["pricing"]:
        p = next((p for p in f["pricing"] if _INCLUSIVE.search(p["text"])), f["pricing"][0])
        rows.append(("Pricing basis", esc(brief(p["text"], 170)) + _rt(p)))
        shown.add(p["text"])
    if f["changes"]:
        k = {kind: sum(1 for c in f["changes"] if c["kind"] == kind) for kind in ("NEW", "UPDATED", "CONFLICT")}
        rows.append(("Changes in later documents", esc(", ".join(f"{v} {kk.lower()}" for kk, v in k.items() if v))
                     + " — section 5"))
    about_ctx = [(sentences_of(it["text"]) or [it["text"]])[0] for it in f["about"]][:2]
    rows.append(("External buyer research", esc(_research_status_line(research, about_ctx))))
    section("Executive Intelligence Summary", [_kv(rows)])
    if f.get("coverage_note"):
        story.append(Paragraph(f'{_label("COVERAGE LIMITATION")} {esc(f["coverage_note"])}', _st["note"]))
        story.append(Spacer(1, 4))

    # 2. Opportunity and Delivery Requirements
    blocks = []
    sc = _req_table([(g["heading"], it) for g in _groups(f["scope"]) for it in g["items"]], shown, n=175)
    if sc:
        blocks += _headed("Scope of work", sc)
    tl = []
    for g in _groups(f["timeline"]):
        labels = [label_of(it["text"])[0] or brief(it["text"], 90) for it in g["items"]]
        shown.add(*[it["text"] for it in g["items"] if label_of(it["text"])[0] is None])
        head = f"<b>{esc(g['heading'])}</b> — " if g["heading"] else ""
        tl.append(_RLParagraph(f"{head}{esc('; '.join(labels))}{_rt(g['items'][0])}", _st["bul"], bulletText="•"))
    if tl:
        blocks += _headed("Workflow and timeline", tl)
    dv = _deliverables_block(f, shown)
    if dv:
        blocks += _headed("Deliverables", dv)
    qb = _quantity_block(f, shown)
    if qb:
        blocks += _headed("Stated quantities and durations", qb)
    caps = _req_table([(None, it) for it in f["qualifications"]] + [("General requirement", it) for it in f["general"]],
                      shown, n=160)
    if caps:
        blocks += _headed("Required capabilities and conditions", caps)
    section("Opportunity and Delivery Requirements", blocks)

    # 3. Buyer Intelligence
    blocks = []
    about = [dict(it, text=(sentences_of(it["text"]) or [it["text"]])[0]) for it in f["about"]]
    about = about[:2]
    ab = _lines(about, shown, n=240, limit=2)
    if ab:
        blocks += _headed("Context from the procurement documents", ab)
    blocks += _headed("Verified external research", _research_blocks(research, context=[a["text"] for a in about]))
    section("Buyer Intelligence", blocks)

    # 4. Evaluation and Commercial Intelligence
    blocks = []
    crit = _criteria_table(f, compact=False)
    if crit:
        blocks += _headed("Evaluation criteria and weights", crit)
    elif f["eval_text"]:
        blocks += _headed("Evaluation criteria and weights", _lines(f["eval_text"], shown, n=160))
    evidence = [dict(x, text=f"{d['name']}: {x['text']}") for d in f["required_docs"]
                if not _PRICING.search(d["name"]) for x in d["details"] if not shown.seen(x["text"])]
    ev = _lines(evidence, shown, n=170)
    if ev:
        blocks += _headed("What the proposal must contain", ev)
    pr_ = _lines(f["pricing"], shown, n=180)
    if pr_:
        blocks += _headed("Pricing structure", pr_)
    bu = _lines(f["budget"], shown, n=180)
    if bu:
        blocks += _headed("Budget (as stated)", bu)
    se = _lines(f.get("securities") or [], shown, n=200)
    if se:
        blocks += _headed("Securities and guarantees", se)
    pa = _lines(f["payment"], shown, n=240, limit=3)
    if pa:
        blocks += _headed("Payment terms", pa)
    cl = _lines([{"text": c["text"], **(c["ref"] or {})} for c in f["clauses"]], shown, n=180, limit=5)
    if cl:
        blocks += _headed("Material contract terms", cl)
    if f["workbooks"]:
        blocks += _headed("Spreadsheets in the package", [_workbook_table(f["workbooks"])])
    section("Evaluation and Commercial Intelligence", blocks)

    # 5. Material Information and Amendments
    blocks = []
    if f["changes"]:
        blocks.append(_table(["Item", "Previous / superseded", "Introduced by"], _change_rows(f["changes"]),
                             [BODY_W * 0.52, BODY_W * 0.30, BODY_W * 0.18]))
        shown.add(*[str(c["current"]) for c in f["changes"]])
    elif not any(d["amending"] for d in f["documents"]):
        blocks.append(Paragraph("No addendum, clarification or amendment is among the documents analysed.", _st["note"]))
    mf = _material_facts(f, shown, 4)
    if mf:
        blocks += _headed("Other material facts", mf)
    section("Material Information and Amendments", blocks)

    # 6. Management Decision Reference -- submission logistics and open items
    rows = []
    if f["required_docs"]:
        rows.append(["Submission package", esc("; ".join(required_document_names(f))),
                     Paragraph(esc(ref_text(f["required_docs"][0])), _st["cell_s"])])
    sub = f["submission"]
    mt = _method_text(sub)
    if mt:
        rows.append(["Submission method", mt.split(' <font size="7"')[0],
                     Paragraph(esc(ref_text(((sub.get("emails") or [{}])[0].get("sentence"))
                                            or (sub.get("method_sentences") or [None])[0])), _st["cell_s"])])
    if _contact_text(sub):
        cs = _contact_text(sub)
        rows.append(["Contact e-mail (as printed)", cs.split(' <font size="7"')[0],
                     Paragraph(esc(ref_text(sub["contact_emails"][0].get("sentence"))), _st["cell_s"])])
    if _subject_text(sub):
        rows.append(["Subject line", esc(_subject_text(sub)), Paragraph(esc(ref_text(sub["subject_rule"])), _st["cell_s"])])
    if _late_text(sub):
        rows.append(["Late submissions", esc(_late_text(sub)), Paragraph(esc(ref_text(sub["late_rule"])), _st["cell_s"])])
    for k in f["key_dates"]:
        rows.append([esc(k["label"]), esc(fmt_date(k["value"])), Paragraph(esc(ref_text(k["ref"])), _st["cell_s"])])
    d = f["deadline"]
    if d["manual"]:
        rows.append(["Phoenix user entry", f"Submission deadline entered manually as {esc(fmt_date(d['manual']))}",
                     Paragraph("Phoenix user", _st["cell_s"])])
    open_items = []
    if d["conflict"] and not d["amended_from"]:
        open_items.append("submission deadline stated differently across documents")
    if d.get("unverified") == "OCR":
        open_items.append("submission deadline read by OCR from a scanned page, not verified")
    open_items += [f"{c['topic'].lower()} stated differently" for c in f["changes"] if c["kind"] == "CONFLICT"]
    open_items += [f"purpose of {w['name']} not confirmed from its contents" for w in f["workbooks"] if not w.get("purpose")]
    if open_items:
        rows.append(["Open items", esc("; ".join(open_items)), ""])
    blocks = []
    if rows:
        blocks.append(_table(["Matter", "As documented", "Source"], rows, [BODY_W * 0.22, BODY_W * 0.58, BODY_W * 0.20]))
    blocks.append(Paragraph("This reference organises documented facts for the bid decision. It does not recommend "
                            "whether to bid and contains no scores, probabilities or suitability judgements.", _st["note"]))
    section("Management Decision Reference", blocks)

    extra = ""
    if full_status == "PARTIAL":
        extra = (" Full analysis completed partially: specialist reconciliation did not finish, so this assessment "
                 "relies on the document-verified facts above; specialist working notes remain in the app.")
    elif full_status:
        extra = " Specialist working notes and detailed evidence remain in the app."
    story.append(Spacer(1, 6))
    story.append(_basis_note(f, extra))
    return {"pdf": _build(story, "BID OPPORTUNITY ASSESSMENT", f), "filename": report_filename(f, ASSESSMENT)}


def _workbook_table(workbooks: list[dict]) -> Table:
    rows = []
    for wb in workbooks:
        sheets = []
        for sh in wb["sheets"][:4]:
            hdr = ", ".join(h["text"] for h in sh["headers"][:5])
            fc = sh.get("formula_count")
            ftxt = "" if fc is None else (f"; {fc} formula cell(s), e.g. {sh['formula_samples'][0]['cell']} "
                                          f"{sh['formula_samples'][0]['formula']}" if fc else "; no formulas")
            sheets.append(f'<b>{esc(sh["name"])}</b>' + (f" (headers row {sh['header_row']}: {esc(hdr)})" if hdr else "")
                          + esc(ftxt))
        if wb["purpose"]:
            ev = wb["evidence"][0] if wb["evidence"] else {}
            loc = f'sheet "{ev.get("sheet")}"' + (f' cell {ev["cell"]}' if ev.get("cell") else "")
            purpose = f"<b>{esc(wb['purpose'])}</b><br/>" \
                      f'<font size="6.8" color="#6B675F">evidence: “{esc(ev.get("text", "")[:50])}”, {esc(loc)}</font>'
        else:
            purpose = '<font color="#9A6A12">Purpose unconfirmed</font>'
        links = wb.get("references") or []
        if links:
            l0 = links[0]
            link = (f'{"Referenced" if l0["status"] == "linked" else "Possible reference (unconfirmed)"}: '
                    f'“{esc(l0["text"][:160])}” [{esc(ref_text(l0))}]')
        else:
            link = '<font color="#9A6A12">Link to RFP/addendum unconfirmed</font>'
        if wb.get("error"):
            link += f"<br/>Workbook could not be fully read ({esc(wb['error'])})."
        rows.append([f"<b>{esc(wb['name'])}</b><br/>" + "<br/>".join(sheets), purpose, link])
    return _table(["Workbook / sheets", "Purpose", "RFP / addendum reference"], rows,
                  [BODY_W * 0.42, BODY_W * 0.22, BODY_W * 0.36])


# ═══════════════════════════════════════════════════════════════════════
# REPORTS FROM VERIFIED FACTS (runs with report facts; see procurement_facts)
# Each statement is a model-classified fact whose quote was found in the
# source and whose numbers, addresses and links all occur in that quote.
# ═══════════════════════════════════════════════════════════════════════

_FACT_N = 420  # facts are already concise; the cap only guards against a run-on quote


def _fact_lines(items: list[dict], shown: _Shown, *, limit: int | None = None, more: str | None = None) -> list:
    fresh = [it for it in items if not shown.same(it["text"])]
    out = []
    for it in fresh[:limit] if limit else fresh:
        out.append(_RLParagraph(f"{esc(brief(it['text'], _FACT_N))}{_rt(it)}", _st["bul"], bulletText="•"))
        shown.add(it["text"])
    if limit and more and len(fresh) > limit:
        out.append(Paragraph(f"The Bid Opportunity Assessment lists {len(fresh) - limit} more.", _st["note"]))
    return out


def _fact_cell(items: list[dict], shown: _Shown, limit: int | None = None) -> str | None:
    fresh = [it for it in items if not shown.same(it["text"])][:limit]
    if not fresh:
        return None
    shown.add(*[it["text"] for it in fresh])
    return "<br/>".join(esc(brief(it["text"], _FACT_N)) + _rt(it) for it in fresh)


def _weighted(f: dict) -> bool:
    return any(c.get("weight") for c in f["criteria"])


_NOT_EXTRACTED = "Not identified in the extracted facts; check the documents."


def _facts_glance(f: dict, shown: _Shown, *, identity: bool = True) -> list[tuple[str, str]]:
    ident, rows = f["identity"], []
    if identity:
        for label, key in (("Buyer", "organization"), ("Title", "title"), ("Reference", "reference")):
            if ident.get(key):
                rows.append((label, esc(ident[key])))
    if f["synopsis"]:
        a = f["synopsis"][0]
        rows.append(("The assignment", esc(a["text"]) + _rt(a)))
        shown.add(a["text"])
    if ident.get("location"):
        rows.append(("Delivery location", _fact_cell([ident["location"]], shown)))
    else:
        rows.append(("Delivery location", esc(_NOT_EXTRACTED)))
    if f.get("schedule"):
        rows.append(("Duration and schedule", _fact_cell(f["schedule"], shown, 1)))
    dv = _deadline_value(f)
    if dv:
        rows.append(("Submission deadline", dv))
    return [(k, v) for k, v in rows if v]


def _kv_rows(rows: list) -> list:
    rows = [(k, v) for k, v in rows if v]
    return [_kv(rows)] if rows else []


def _render_snapshot_facts(f: dict) -> dict:
    _set_alias(f)
    shown = _Shown()
    story = [_title_block("FAST · OPPORTUNITY SNAPSHOT", f), Spacer(1, 8)]
    n = 0

    def section(title, blocks):
        nonlocal n
        if [b for b in blocks if b is not None]:
            n += 1
            _emit(story, _sec(n, title), blocks)

    section("Opportunity at a Glance", [_kv(_facts_glance(f, shown))])
    if f.get("coverage_note"):
        story.append(Paragraph(f'{_label("COVERAGE LIMITATION")} {esc(f["coverage_note"])}', _st["note"]))
        story.append(Spacer(1, 4))

    blocks = []
    blocks += _headed("Services", _fact_lines(f["scope"], shown, limit=4, more="scope items are listed"))
    blocks += _headed("Deliverables", _fact_lines(f["deliverables"], shown, limit=6, more="deliverables are listed"))
    blocks += _headed("Schedule", _fact_lines(f.get("schedule") or [], shown, limit=2))
    section("Scope and Deliverables", blocks)

    blocks = []
    blocks += _headed("Eligibility", _fact_lines(f.get("eligibility") or [], shown, limit=3,
                                                 more="eligibility conditions are listed"))
    blocks += _headed("Qualifications sought", _fact_lines(f["qualifications"], shown, limit=4,
                                                           more="qualification requirements are listed"))
    if _weighted(f):
        blocks += _headed("Evaluation criteria and weights", _criteria_table(f, compact=True))
    else:
        blocks += _headed("Evaluation", _fact_lines(f["eval_text"], shown, limit=3))
    blocks += _headed("Award", _fact_lines(f.get("award") or [], shown, limit=2))
    section("Eligibility, Evaluation and Award", blocks)

    sub = f["submission"]
    methods = sub.get("methods") or []
    section("Submission", _kv_rows([
        ("Submission methods" if len(methods) > 1 else "Submission method", _fact_cell(methods, shown, 4)),
        ("Proposal must contain", _fact_cell(f.get("proposal_content") or [], shown, 4)),
        ("Submission rules", _fact_cell(sub.get("rules") or [], shown, 3)),
        ("Questions", _fact_cell(sub.get("questions") or [], shown, 1))]))

    section("Commercial Essentials", _kv_rows([
        ("Budget (as stated)", _fact_cell(f["budget"], shown, 2)),
        ("Pricing basis", _fact_cell(f["pricing"], shown, 2)),
        ("Payment", _fact_cell(f["payment"], shown, 1)),
        ("Securities and guarantees", _fact_cell(f.get("securities") or [], shown, 3)),
        ("Contract terms", _fact_cell([{"text": c["text"], **(c["ref"] or {})} for c in f["clauses"]], shown, 2))]))

    section("Additional Material Facts", _material_facts(f, shown, 2))
    if f["changes"]:
        story.append(Spacer(1, 4))
        story.append(Paragraph(f"Changes introduced by later documents ({len(f['changes'])}) are listed with their "
                               f"previous values in the Bid Opportunity Assessment and on the Understand page.",
                               _st["note"]))
    story.append(Spacer(1, 6))
    story.append(_basis_note(f))
    return {"pdf": _build(story, "OPPORTUNITY SNAPSHOT", f), "filename": report_filename(f, SNAPSHOT)}


def _render_assessment_facts(f: dict, *, full_status: str | None = None, research: dict | None = None) -> dict:
    _set_alias(f)
    shown = _Shown()
    story = [_title_block("FULL · BID OPPORTUNITY ASSESSMENT", f), Spacer(1, 8)]
    n = 0

    def section(title, blocks):
        nonlocal n
        if [b for b in blocks if b is not None]:
            n += 1
            _emit(story, _sec(n, title), blocks)

    rows = _facts_glance(f, shown, identity=False)
    top = [c for c in f["criteria"] if c["level"] == 0 and c["weight"]]
    if top:
        rows.append(("Evaluation basis", esc(" / ".join(f"{c['stage']} {c['weight']}" for c in top))
                     + _rt(top[0]["ref"])))
    methods = f["submission"].get("methods") or []
    if len(methods) > 1:
        rows.append(("Submission", f"{len(methods)} permitted submission methods — section 6"))
    if f["budget"]:
        rows.append(("Budget (as stated)", _fact_cell(f["budget"], shown, 1)))
    if f["changes"]:
        k = {kind: sum(1 for c in f["changes"] if c["kind"] == kind) for kind in ("NEW", "UPDATED", "CONFLICT")}
        rows.append(("Changes in later documents", esc(", ".join(f"{v} {kk.lower()}" for kk, v in k.items() if v))
                     + " — section 5"))
    about_ctx = [it["text"] for it in f["about"]][:2]
    rows.append(("External buyer research", esc(_research_status_line(research, about_ctx))))
    section("Executive Intelligence Summary", _kv_rows(rows))
    if f.get("coverage_note"):
        story.append(Paragraph(f'{_label("COVERAGE LIMITATION")} {esc(f["coverage_note"])}', _st["note"]))
        story.append(Spacer(1, 4))

    blocks = []
    blocks += _headed("Scope of work", _fact_lines(f["scope"], shown, limit=25))
    blocks += _headed("Deliverables", _fact_lines(f["deliverables"], shown, limit=40))
    blocks += _headed("Schedule and duration", _fact_lines(f.get("schedule") or [], shown, limit=10))
    blocks += _headed("Eligibility", _fact_lines(f.get("eligibility") or [], shown, limit=12))
    blocks += _headed("Qualifications sought", _fact_lines(f["qualifications"], shown, limit=15))
    section("Opportunity and Delivery Requirements", blocks)

    blocks = []
    blocks += _headed("Context from the procurement documents", _fact_lines(f["about"], shown, limit=3))
    blocks += _headed("Verified external research", _research_blocks(research, context=about_ctx))
    section("Buyer Intelligence", blocks)

    blocks = []
    if _weighted(f):
        blocks += _headed("Evaluation criteria and weights", _criteria_table(f, compact=False))
    blocks += _headed("Evaluation method", _fact_lines(f["eval_text"], shown, limit=10))
    blocks += _headed("Award", _fact_lines(f.get("award") or [], shown, limit=8))
    blocks += _headed("What the proposal must contain", _fact_lines(f.get("proposal_content") or [], shown, limit=20))
    blocks += _headed("Pricing", _fact_lines(f["pricing"], shown, limit=10))
    blocks += _headed("Budget (as stated)", _fact_lines(f["budget"], shown, limit=4))
    blocks += _headed("Securities and guarantees", _fact_lines(f.get("securities") or [], shown, limit=8))
    blocks += _headed("Payment terms", _fact_lines(f["payment"], shown, limit=8))
    blocks += _headed("Material contract terms", _fact_lines(
        [{"text": c["text"], **(c["ref"] or {})} for c in f["clauses"]], shown, limit=15))
    if f["workbooks"]:
        blocks += _headed("Spreadsheets in the package", [_workbook_table(f["workbooks"])])
    section("Evaluation and Commercial Intelligence", blocks)

    blocks = []
    if f["changes"]:
        blocks.append(_table(["Item", "Previous / superseded", "Introduced by"], _change_rows(f["changes"]),
                             [BODY_W * 0.52, BODY_W * 0.30, BODY_W * 0.18]))
        shown.add(*[str(c["current"]) for c in f["changes"]])
    elif not any(d["amending"] for d in f["documents"]):
        blocks.append(Paragraph("No addendum, clarification or amendment is among the documents analysed.",
                                _st["note"]))
    blocks += _headed("Other material facts", _material_facts(f, shown, 10))
    section("Material Information and Amendments", blocks)

    sub, rows = f["submission"], []

    def add(label, items, limit=None):
        for it in [it for it in items if not shown.same(it["text"])][:limit]:
            rows.append([esc(label), esc(brief(it["text"], _FACT_N)), Paragraph(esc(ref_text(it)), _st["cell_s"])])
            shown.add(it["text"])
    add("Submission method", sub.get("methods") or [])
    add("Submission rule", sub.get("rules") or [], 12)
    add("Questions", sub.get("questions") or [], 3)
    for k in f["key_dates"]:
        rows.append([esc(k["label"]), esc(fmt_date(k["value"])), Paragraph(esc(ref_text(k["ref"])), _st["cell_s"])])
    d = f["deadline"]
    if d["manual"]:
        rows.append(["Phoenix user entry", f"Submission deadline entered manually as {esc(fmt_date(d['manual']))}",
                     Paragraph("Phoenix user", _st["cell_s"])])
    open_items = []
    if d["conflict"] and not d["amended_from"]:
        open_items.append("submission deadline stated differently across documents")
    if d.get("unverified") == "OCR":
        open_items.append("submission deadline read by OCR from a scanned page, not verified")
    open_items += [f"{c['topic'].lower()} stated differently" for c in f["changes"] if c["kind"] == "CONFLICT"]
    open_items += [f"purpose of {w['name']} not confirmed from its contents" for w in f["workbooks"]
                   if not w.get("purpose")]
    if open_items:
        rows.append(["Open items", esc("; ".join(open_items)), ""])
    blocks = []
    if rows:
        blocks.append(_table(["Matter", "As documented", "Source"], rows,
                             [BODY_W * 0.22, BODY_W * 0.58, BODY_W * 0.20]))
    blocks.append(Paragraph("This reference organises documented facts for the bid decision. It does not recommend "
                            "whether to bid and contains no scores, probabilities or suitability judgements.",
                            _st["note"]))
    section("Management Decision Reference", blocks)

    extra = ""
    if full_status == "PARTIAL":
        extra = (" Full analysis completed partially: specialist reconciliation did not finish, so this assessment "
                 "relies on the document-verified facts above; specialist working notes remain in the app.")
    elif full_status:
        extra = " Specialist working notes and detailed evidence remain in the app."
    story.append(Spacer(1, 6))
    story.append(_basis_note(f, extra))
    return {"pdf": _build(story, "BID OPPORTUNITY ASSESSMENT", f), "filename": report_filename(f, ASSESSMENT)}
