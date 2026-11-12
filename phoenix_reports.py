"""Phoenix Bid Intelligence reports.

Two management-ready PDFs, built from document-verified facts only:

* FAST  -- "Opportunity Snapshot" (about 2-3 pages): identification, overview,
           scope & deliverables, evaluation & eligibility, commercial and
           submission essentials, and up to three decision-relevant matters.
* FULL  -- "Bid Opportunity Assessment" (about 4-6 pages), organised around
           management needs and readable on its own: executive summary,
           opportunity & delivery requirements, buyer intelligence (external,
           dated, with URLs), evaluation & commercial intelligence, material
           findings & procurement changes, decision information summary.

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


def esc(v) -> str:
    return _xml_escape(str(v if v is not None else ""))


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
    _ctx.alias = {names[0]: ""} if len(names) == 1 else {n: f"D{i}" for i, n in enumerate(names, 1)}


def clip(text: str, n: int) -> str:
    t = pdg.norm(text)
    if len(t) <= n:
        return t
    cut = t[:n].rsplit(" ", 1)[0]
    return cut.rstrip(",;:") + "\u2026"


# ═══════════════════════════════════════════════════════════════════════
# FACT MODEL
# ═══════════════════════════════════════════════════════════════════════

def _verified(documents, excerpt: str) -> bool:
    """An extracted excerpt is publishable only if it is found in the documents."""
    e = pdg.norm(excerpt)
    if not e:
        return False
    return pdg.corpus_contains(documents, e[:90]) or pdg.corpus_contains(documents, e[:45])


def _ref_from(source_refs) -> dict:
    r = (source_refs or [{}])[0] or {}
    return {"doc": r.get("source_doc"), "page": r.get("page"), "sheet": r.get("sheet"),
            "excerpt": pdg.norm(r.get("excerpt") or "")}


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


_LOCATION = re.compile(r"\b(locations?|venues?|place of (performance|delivery)|delivered (in|at)|on-?site at)\b", re.I)
_BUDGET = re.compile(r"\b(budget|ceiling|not (to )?exceed|maximum (contract |total )?(value|amount)|estimated (contract )?value)\b", re.I)
_PRICING = re.compile(r"\b(rate|price|pricing|cost|quotation|quote|currency|vat|tax|inclusive|lump.?sum|fee)\b", re.I)
_COST_BEARING = re.compile(r"(borne by|charged (on|to) the (service provider|contractor|supplier|bidder|consultant)|"
                           r"at the (contractor|supplier|consultant|bidder)'?s? (own )?(cost|expense)|"
                           r"won'?t handle any|will not (handle|cover|pay))", re.I)
_INCLUSIVE = re.compile(r"inclusive of all|all.?inclusive|including all costs", re.I)


def build_facts(*, bid: dict, fast_result: dict, documents: list[tuple[str, str]],
                files: list[tuple[str, bytes]] | None = None,
                previous_result: dict | None = None, previous_doc_names: list[str] | None = None,
                analysis_date: str | None = None, run_id: int | None = None) -> dict:
    """Verified fact model shared by both reports."""
    import bid_identity
    import workbook_intelligence as wbi
    r = fast_result or {}
    docs = list(documents or [])
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
    org = org or (merged.get("client") if merged.get("client") and pdg.corpus_contains(docs, merged["client"]) else None)
    reference = merged.get("file_number") or bid.get("file_number")
    if reference and not pdg.corpus_contains(docs, str(reference)):
        reference = bid.get("file_number") or None
    location = next(iter(pdg.find_sentences(docs, _LOCATION.pattern, 1)), None)

    # ── deadline: extracted (with addendum authority) + manual override ──
    dl = ct.effective_deadline(r, docs)
    manual = bid.get("submission_deadline")
    deadline = {
        "extracted": dl["value"], "extracted_ref": dl["ref"], "amended_from": dl["amended_from"],
        "conflict": dl["conflict"], "manual": manual if manual and str(manual)[:10] != str(dl["value"] or "")[:10] else None,
    }
    deadline["effective"] = deadline["manual"] or dl["value"]

    # ── overview / scope / delivery ──
    overview = _items(secs, "overview", drop_leadin=True)[:3]
    about = _items(secs, "about", drop_leadin=True)
    scope = _items(secs, "scope")
    if not scope:
        for q in r.get("requirements") or []:
            ref = _ref_from(q.get("source_refs"))
            if "scope" in (q.get("description") or "").lower() and _verified(docs, ref["excerpt"]):
                scope.append({"text": pdg.norm(q["description"]), **ref})
    deliverables = _items(secs, "deliverables")
    timeline = _items(secs, "timeline")
    qualifications = _items(secs, "qualifications")
    general = _items(secs, "general")

    # ── evaluation ──
    criteria = []
    for ec in r.get("evaluation_criteria") or []:
        ref = _ref_from(ec.get("source_refs"))
        if not _verified(docs, ref["excerpt"]):
            continue
        w = ec.get("weight")
        if w and pdg.fold(str(w)) not in pdg.fold(ref["excerpt"]):
            w = None  # weight not visible in its own excerpt -> not published
        criteria.append({"stage": pdg.norm(ec.get("stage")), "weight": w, "parent": ec.get("parent_stage"),
                         "basis": ec.get("weight_basis"), "threshold": ec.get("threshold"), "ref": ref})
    stages = {c["stage"] for c in criteria}
    for c in criteria:
        c["level"] = 1 if c["parent"] in stages else 0
    eval_text = [] if criteria else _items(secs, "evaluation")

    # ── commercial ──
    pricing = _items(secs, "pricing")
    pricing += [it for it in _items(secs, "submission")
                if _PRICING.search(it["text"]) and not _is_subhead(it["text"]) and it not in pricing]
    budget = pdg.find_sentences(docs, _BUDGET.pattern, 2)
    payment = _items(secs, "payment", drop_leadin=True)
    clauses = []
    for cc in r.get("commercial_clauses") or []:
        ref = _ref_from(cc.get("source_refs"))
        if not _verified(docs, ref["excerpt"]):
            continue
        if "PAYMENT" in (cc.get("clause_kind") or "") and payment:
            continue
        clauses.append({"topic": pdg.norm(cc.get("topic")), "text": ref["excerpt"], "ref": ref})
    clauses += [{"topic": None, "text": it["text"], "ref": it} for it in _items(secs, "contract")]
    stated = [it["text"] for it in qualifications + general + payment]
    clauses = [c for c in clauses if not any(ct._similar(c["text"], t) > 0.6 or pdg.fold(t) in pdg.fold(c["text"])
                                             for t in stated)]

    # ── submission ──
    sub_docs = [it for it in _items(secs, "submission", drop_leadin=False)
                if not (pdg.EMAIL.search(it["text"]) or re.search(
                    r"no later than|after the deadline|subject line", it["text"], re.I))]
    key_dates = []
    for m in r.get("canonical_milestones") or []:
        ref = _ref_from(m.get("source_refs"))
        if m.get("normalized_date_start") and _verified(docs, ref["excerpt"]) and \
                (m.get("label") or "").upper() != "SUBMISSION_DEADLINE":
            key_dates.append({"label": (m.get("label") or "").replace("_", " ").title(),
                              "value": m["normalized_date_start"], "ref": ref})

    # ── changes, workbooks ──
    changes = ct.detect_changes(r, docs, previous_result, previous_doc_names)
    workbooks = wbi.analyse_package(files or [], docs) if files else []

    # ── decision-relevant factual matters (max 3, verbatim or factual template) ──
    matters = []
    if deadline["amended_from"]:
        matters.append({"text": f"The submission deadline was changed from {fmt_date(deadline['amended_from']['value'])} "
                                f"to {fmt_date(deadline['extracted'])} by {deadline['extracted_ref'].get('doc')}.",
                        "ref": deadline["extracted_ref"]})
    if deadline["manual"]:
        matters.append({"text": f"A Phoenix user entered the submission deadline manually as {fmt_date(deadline['manual'])}; "
                                f"the documents state {fmt_date(deadline['extracted']) or 'no single date'}.", "ref": None})
    new_count = sum(1 for c in changes if c["kind"] == "NEW")
    if new_count:
        srcs = sorted({(c["source"] or {}).get("doc") for c in changes if c["kind"] == "NEW"} - {None})
        matters.append({"text": f"{new_count} new requirement(s) or condition(s) introduced by {', '.join(srcs)}.",
                        "ref": None})
    if sub.get("late_rule"):
        matters.append({"text": sub["late_rule"]["text"], "ref": sub["late_rule"]})
    for s in pdg.located_sentences(docs):
        if _COST_BEARING.search(s["text"]):
            matters.append({"text": s["text"], "ref": s})
            break
    for it in pricing:
        if _INCLUSIVE.search(it["text"]):
            matters.append({"text": it["text"], "ref": it})
            break
    if any(c["kind"] == "CONFLICT" for c in changes):
        c = next(c for c in changes if c["kind"] == "CONFLICT")
        matters.append({"text": f"The documents state different values for {c['topic'].lower()} "
                                f"({c['current']} / {c['previous']}); no amendment resolving this was found.",
                        "ref": c["source"]})
    matters = matters[:3]

    doc_basis = []
    for name, text in docs:
        pages = sorted({ln["page"] for ln in pdg.located_lines([(name, text)]) if ln.get("page")})
        doc_basis.append({"name": name, "amending": ct.is_amending_document(name, text),
                          "pages": len(pages) or None, "workbook": wbi.is_workbook(name)})

    return {
        "bid_id": bid.get("id"), "run_id": run_id,
        "identity": {"title": title, "organization": org, "reference": reference, "location": location},
        "deadline": deadline, "submission": sub, "sub_docs": sub_docs, "key_dates": key_dates,
        "overview": overview, "about": about, "scope": scope, "deliverables": deliverables,
        "timeline": timeline, "qualifications": qualifications, "general": general,
        "criteria": criteria, "eval_text": eval_text,
        "pricing": pricing, "budget": budget, "payment": payment, "clauses": clauses,
        "changes": changes, "workbooks": workbooks, "matters": matters,
        "documents": doc_basis, "analysis_date": analysis_date or date.today().isoformat(),
    }


# ═══════════════════════════════════════════════════════════════════════
# RENDERING HELPERS
# ═══════════════════════════════════════════════════════════════════════

def _sec(n: int, title: str) -> list:
    return [Paragraph(f"{n}. {esc(title)}", _st["sec"]), base.hr(GOLD, 0.9, 0, 5)]


def _bullets(items: list[dict], limit: int | None = None, with_refs: bool = True) -> list:
    out = []
    shown = items if limit is None else items[:limit]
    for idx, it in enumerate(shown):
        t = it["text"]
        if _is_subhead(t):
            out.append(Paragraph(f"<b>{esc(t)}</b>", _st["sub"]))
            continue
        if t.endswith(":"):
            out.append(Paragraph(esc(t), _st["body"]))
            continue
        nxt = shown[idx + 1] if idx + 1 < len(shown) else None
        same_next = nxt is not None and ref_text(nxt) == ref_text(it) and not _is_subhead(nxt["text"])
        r = ref_text(it) if with_refs and not same_next else ""
        tail = f' <font size="7" color="#6B675F">[{esc(r)}]</font>' if r else ""
        out.append(_RLParagraph(f"{esc(t)}{tail}", _st["bul"], bulletText="•"))
    if limit is not None and len(items) > limit:
        out.append(Paragraph(f"+ {len(items) - limit} further item(s) — see the Understand page.", _st["note"]))
    return out


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
    color = {"NEW": GREEN, "UPDATED": AMBER, "CONFLICT": RED}.get(kind, "#6B675F")
    text = {"NEW": "NEW INFORMATION", "UPDATED": "UPDATED INFORMATION", "CONFLICT": "UNRESOLVED CONFLICT"}.get(kind, kind)
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


def _deadline_value(f: dict, long: bool = True) -> str:
    d = f["deadline"]
    parts = []
    if d["manual"]:
        parts.append(f"<b>{esc(fmt_date(d['manual']))}</b> "
                     f'<font color="{AMBER}" size="7.4">MANUALLY ENTERED BY PHOENIX</font>')
        if d["extracted"]:
            parts.append(f'<font size="7.6" color="#6B675F">Documents state {esc(fmt_date(d["extracted"]))} '
                         f'[{esc(ref_text(d["extracted_ref"]))}]</font>')
    elif d["extracted"]:
        parts.append(f"<b>{esc(fmt_date(d['extracted']))}</b>"
                     f' <font size="7.4" color="#6B675F">[{esc(ref_text(d["extracted_ref"]))}]</font>')
    if d["amended_from"]:
        parts.append(f'{_label("UPDATED")} <font size="7.6">previously {esc(fmt_date(d["amended_from"]["value"]))} '
                     f'[{esc(ref_text(d["amended_from"]["ref"]))}]</font>')
    if d["conflict"] and long:
        vals = "; ".join(f"{fmt_date(c['value'])} [{ref_text(c['ref'])}]" for c in d["conflict"])
        parts.append(f'{_label("CONFLICT")} <font size="7.6">{esc(vals)}</font>')
    return "<br/>".join(parts)


def _ident_rows(f: dict) -> list[tuple[str, str]]:
    ident = f["identity"]
    rows = []
    if ident.get("title"):
        rows.append(("Title", esc(ident["title"])))
    if ident.get("organization"):
        rows.append(("Organization", esc(ident["organization"])))
    if ident.get("reference"):
        rows.append(("Reference", esc(ident["reference"])))
    if ident.get("location"):
        loc = ident["location"]
        rows.append(("Location", f'{esc(loc["text"])} <font size="7" color="#6B675F">[{esc(ref_text(loc))}]</font>'))
    dv = _deadline_value(f)
    if dv:
        rows.append(("Submission deadline", dv))
    return rows


def _criteria_table(f: dict) -> Table | None:
    if not f["criteria"]:
        return None
    rows = []
    for c in f["criteria"]:
        name = esc(c["stage"])
        name = ("&nbsp;&nbsp;&nbsp;— " + name) if c["level"] else f"<b>{name}</b>"
        w = esc(c["weight"] or "—")
        if c["level"] and c["weight"]:
            w += f' <font size="6.8" color="#6B675F">of {esc(c["parent"])}</font>' if c.get("basis") == "Within Parent" else ""
        rows.append([name, w, Paragraph(esc(ref_text(c["ref"])), _st["cell_s"])])
    return _table(["Criterion", "Weight", "Source"], rows, [BODY_W * 0.62, BODY_W * 0.18, BODY_W * 0.20])


def _submission_rows(f: dict) -> list[tuple[str, str]]:
    sub = f["submission"]
    rows = []
    if sub.get("channel") or sub.get("method_sentences"):
        val = f"<b>{esc(sub.get('channel') or 'As instructed')}</b>"
        if sub.get("emails"):
            val += " — " + ", ".join(esc(e["email"]) for e in sub["emails"])
        ms = (sub.get("method_sentences") or [None])[0]
        if ms:
            val += f'<br/><font size="7.6" color="#6B675F">“{esc(ms["text"][:260])}” [{esc(ref_text(ms))}]</font>'
        rows.append(("Method", val))
    if sub.get("subject_rule"):
        s = sub["subject_rule"]
        rows.append(("Subject line", f'{esc(s["text"])} <font size="7" color="#6B675F">[{esc(ref_text(s))}]</font>'))
    if sub.get("late_rule"):
        s = sub["late_rule"]
        rows.append(("Late submissions", f'{esc(s["text"])} <font size="7" color="#6B675F">[{esc(ref_text(s))}]</font>'))
    dv = _deadline_value(f, long=False)
    if dv:
        rows.append(("Deadline", dv))
    for k in f["key_dates"]:
        rows.append((k["label"], f'{esc(fmt_date(k["value"]))} <font size="7" color="#6B675F">[{esc(ref_text(k["ref"]))}]</font>'))
    return rows


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
        names.append((f"{alias} " if alias else "") + d["name"] + (f" ({', '.join(tag)})" if tag else ""))
    txt = (f"<b>Document basis.</b> {len(names)} document(s) considered: {esc('; '.join(names))}. "
           f"Analysis date {esc(fmt_date(f['analysis_date']))}. Statements are taken from these documents with "
           f"their page/sheet references; nothing here is a recommendation on whether to bid.{extra}")
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
        canvas.drawRightString(PAGE_W - MARGIN - 0.3 * inch, 0.43 * inch, getattr(doc, "_px_header", "")[:60])
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
                          title=f"{label.title()} — {ident.get('title') or 'Opportunity'}",
                          author="Phoenix Bid Intelligence", invariant=1)
    doc._px_header = header
    doc.addPageTemplates([PageTemplate(id="Body", frames=[Frame(
        MARGIN, 0.8 * inch, BODY_W, PAGE_H - 1.4 * inch, id="body", leftPadding=0, rightPadding=0,
        topPadding=0, bottomPadding=0)], onPage=_on_page(label))])
    doc.build(story)
    return buf.getvalue()


def _emit(story: list, head: list, blocks: list) -> None:
    blocks = [b for b in blocks if b is not None]
    if not blocks:
        return  # never an empty section
    story.append(KeepTogether(head + blocks[:1]))
    story.extend(blocks[1:])


def required_document_names(f: dict) -> list[str]:
    items = [i for i in f["sub_docs"] if not i["text"].endswith(":")]
    heads = [i["text"] for i in items if i.get("numbered")] or [i["text"] for i in items if _is_subhead(i["text"])]
    return [clip(h, 70) for h in heads]


def report_filename(f: dict, kind: str) -> str:
    ident = f["identity"]
    key = ident.get("reference") or ident.get("title") or f"Bid_{f.get('bid_id')}"
    key = re.sub(r"[^A-Za-z0-9._-]+", "_", str(key)).strip("._-")[:70] or "Bid"
    return f"{key}_{'Opportunity_Snapshot' if kind == SNAPSHOT else 'Bid_Opportunity_Assessment'}.pdf"


# ═══════════════════════════════════════════════════════════════════════
# FAST -- OPPORTUNITY SNAPSHOT
# ═══════════════════════════════════════════════════════════════════════

def render_snapshot(f: dict) -> dict:
    _set_alias(f)
    story = [_title_block("FAST · OPPORTUNITY SNAPSHOT", f), Spacer(1, 8)]
    n = 0

    n += 1
    _emit(story, _sec(n, "Identification"), [_kv(_ident_rows(f))] if _ident_rows(f) else [])

    if f["overview"]:
        n += 1
        _emit(story, _sec(n, "Overview"), [Paragraph(esc(" ".join(i["text"] for i in f["overview"][:2])), _st["body"]),
                                           _refs_line(f["overview"][:2])])

    blocks = []
    if f["scope"]:
        blocks.append(Paragraph("<b>Scope of work</b>", _st["sub"]))
        blocks += _bullets(f["scope"], 7)
    if f["deliverables"]:
        blocks.append(Paragraph("<b>Key deliverables</b>", _st["sub"]))
        blocks += _bullets(f["deliverables"], 8)
    if blocks:
        n += 1
        _emit(story, _sec(n, "Scope and key deliverables"), blocks)

    blocks = []
    mand = f["qualifications"] + f["general"]
    if mand:
        blocks.append(Paragraph("<b>Qualifications, eligibility and general requirements</b>", _st["sub"]))
        blocks += _bullets(mand, 8)
    ct_ = _criteria_table(f)
    if ct_ is not None or f["eval_text"]:
        blocks.append(Paragraph("<b>Evaluation criteria and weights</b>", _st["sub"]))
        blocks += [ct_] if ct_ is not None else _bullets(f["eval_text"], 8)
    if blocks:
        n += 1
        _emit(story, _sec(n, "Evaluation and eligibility"), blocks)

    blocks = []
    if f["pricing"]:
        blocks.append(Paragraph("<b>Pricing instructions</b>", _st["sub"]))
        blocks += _bullets(f["pricing"], 5)
    if f["budget"]:
        blocks.append(Paragraph("<b>Budget</b>", _st["sub"]))
        blocks += _bullets(f["budget"], 2)
    if f["payment"]:
        blocks.append(Paragraph("<b>Payment terms</b>", _st["sub"]))
        blocks += _bullets(f["payment"], 4)
    other = [c for c in f["clauses"]]
    if other:
        blocks.append(Paragraph("<b>Significant contractual conditions</b>", _st["sub"]))
        blocks += _bullets([{"text": c["text"], **(c["ref"] or {})} for c in other], 4)
    if blocks:
        n += 1
        _emit(story, _sec(n, "Commercial essentials"), blocks)

    blocks = []
    if f["sub_docs"]:
        blocks.append(Paragraph("<b>Required documents</b>", _st["sub"]))
        blocks += _bullets(f["sub_docs"], 12, with_refs=False)
        blocks.append(_refs_line(f["sub_docs"]))
    rows = _submission_rows(f)
    if rows:
        blocks.append(Paragraph("<b>Method and key dates</b>", _st["sub"]))
        blocks.append(_kv(rows))
    if blocks:
        n += 1
        _emit(story, _sec(n, "Submission essentials"), blocks)

    if f["matters"]:
        n += 1
        blocks = []
        for i, m in enumerate(f["matters"], 1):
            r = ref_text(m.get("ref"))
            blocks.append(Paragraph(f"<b>{i}.</b> {esc(m['text'])}"
                                    + (f' <font size="7" color="#6B675F">[{esc(r)}]</font>' if r else ""), _st["body"]))
        _emit(story, _sec(n, "Decision-relevant factual matters"), blocks)

    changes = [c for c in f["changes"]]
    if changes:
        story.append(Spacer(1, 4))
        story.append(Paragraph(f"{len(changes)} new/updated item(s) from later documents are listed on the Understand "
                               f"page and in the Bid Opportunity Assessment.", _st["note"]))
    story.append(Spacer(1, 6))
    story.append(_basis_note(f))
    return {"pdf": _build(story, "OPPORTUNITY SNAPSHOT", f), "filename": report_filename(f, SNAPSHOT)}


# ═══════════════════════════════════════════════════════════════════════
# FULL -- BID OPPORTUNITY ASSESSMENT
# ═══════════════════════════════════════════════════════════════════════

def _change_rows(changes: list[dict]) -> list:
    rows = []
    for c in changes:
        cur = esc(fmt_date(c["current"]) if c["topic"] == "Submission deadline" else c["current"])
        what = f'{_label(c["kind"])}<br/><b>{esc(c["topic"])}</b><br/>{cur[:420]}'
        prev = ""
        if c.get("previous"):
            pv = fmt_date(c["previous"]) if c["topic"] == "Submission deadline" else c["previous"]
            prev = f"{esc(str(pv)[:300])}"
        if c.get("supersedes"):
            prev += f'<br/><font size="6.8" color="#6B675F">[{esc(ref_text(c["supersedes"]))}]</font>'
        src = esc(ref_text(c.get("source")))
        rows.append([what, prev or "—", Paragraph(src, _st["cell_s"])])
    return rows


def _research_blocks(research: dict | None) -> list:
    if not research or research.get("status") != "COMPLETE":
        state = (research or {}).get("status")
        msg = {"RUNNING": "External buyer research was still running when this report was generated; "
                          "re-export the report shortly to include it.",
               "SKIPPED": "External buyer research was not run because the buyer organisation is not identified."}.get(
            state, "External buyer research is not available for this analysis.")
        return [Paragraph(esc(msg), _st["note"])]
    items = research.get("items") or []
    if not items:
        return [Paragraph("External research found no verifiable public sources about this buyer.", _st["note"])]
    rows = []
    for it in items:
        src = esc(it.get("source_title") or it["url"])
        rows.append([f"{esc(it['statement'])}",
                     Paragraph(f'{src}<br/><font color="#2B5C8A">{esc(it["url"][:90])}</font>', _st["cell_s"]),
                     esc(it.get("published") or "undated")])
    return [
        Paragraph("Public sources found by targeted web research on "
                  f"{esc(fmt_date(str(research.get('researched_at'))[:10]))}. These are external facts about the buyer, "
                  "separate from the procurement requirements; they do not indicate the buyer's preferences.",
                  _st["note"]),
        _table(["External fact", "Source", "Published"], rows, [BODY_W * 0.50, BODY_W * 0.35, BODY_W * 0.15]),
    ]


def render_assessment(f: dict, *, full_status: str | None = None, research: dict | None = None) -> dict:
    _set_alias(f)
    story = [_title_block("FULL · BID OPPORTUNITY ASSESSMENT", f), Spacer(1, 8)]
    n = 0

    # 1. Executive Intelligence Summary
    n += 1
    blocks = []
    if f["overview"]:
        blocks.append(Paragraph(esc(" ".join(i["text"] for i in f["overview"][:2])), _st["body"]))
        blocks.append(_refs_line(f["overview"][:2]))
    rows = _ident_rows(f)
    top = [c for c in f["criteria"] if c["level"] == 0 and c["weight"]]
    if top:
        rows.append(("Evaluation basis", esc(" / ".join(f"{c['stage']} {c['weight']}" for c in top))))
    sub = f["submission"]
    if sub.get("channel"):
        rows.append(("Submission method", esc(sub["channel"] + (" — " + ", ".join(e["email"] for e in sub["emails"]) if sub.get("emails") else ""))))
    if f["sub_docs"]:
        heads = required_document_names(f)
        if heads:
            rows.append(("Documents required", esc("; ".join(heads[:8]))))
    if f["changes"]:
        k = {kind: sum(1 for c in f["changes"] if c["kind"] == kind) for kind in ("NEW", "UPDATED", "CONFLICT")}
        rows.append(("Procurement changes", esc(", ".join(f"{v} {kk.lower()}" for kk, v in k.items() if v))))
    blocks.append(_kv(rows))
    if f["matters"]:
        blocks.append(Paragraph("<b>Key factual matters</b>", _st["sub"]))
        blocks += _bullets([{"text": m["text"], **(m.get("ref") or {})} for m in f["matters"]])
    _emit(story, _sec(n, "Executive Intelligence Summary"), blocks)

    # 2. Opportunity & Delivery Requirements
    blocks = []
    if f["scope"]:
        blocks.append(Paragraph("<b>Scope of work</b>", _st["sub"]))
        blocks += _bullets(f["scope"], 14)
    if f["deliverables"]:
        blocks.append(Paragraph("<b>Deliverables</b>", _st["sub"]))
        blocks += _bullets(f["deliverables"], 14)
    if f["timeline"]:
        blocks.append(Paragraph("<b>Workflow and timeline</b>", _st["sub"]))
        blocks += _bullets(f["timeline"], 14)
    if f["qualifications"] or f["general"]:
        blocks.append(Paragraph("<b>Qualifications and general requirements</b>", _st["sub"]))
        blocks += _bullets(f["qualifications"] + f["general"], 14)
    if blocks:
        n += 1
        _emit(story, _sec(n, "Opportunity & Delivery Requirements"), blocks)

    # 3. Buyer Intelligence
    n += 1
    blocks = []
    if f["about"]:
        blocks.append(Paragraph("<b>As stated in the procurement documents</b>", _st["sub"]))
        blocks += _bullets(f["about"], 4)
    blocks.append(Paragraph("<b>External sources</b>", _st["sub"]))
    blocks += _research_blocks(research)
    _emit(story, _sec(n, "Buyer Intelligence"), blocks)

    # 4. Evaluation & Commercial Intelligence
    blocks = []
    ct_ = _criteria_table(f)
    if ct_ is not None or f["eval_text"]:
        blocks.append(Paragraph("<b>Evaluation criteria and weights</b>", _st["sub"]))
        blocks += [ct_] if ct_ is not None else _bullets(f["eval_text"], 10)
    if f["pricing"]:
        blocks.append(Paragraph("<b>Pricing instructions</b>", _st["sub"]))
        blocks += _bullets(f["pricing"], 8)
    if f["budget"]:
        blocks.append(Paragraph("<b>Budget</b>", _st["sub"]))
        blocks += _bullets(f["budget"], 2)
    if f["payment"]:
        blocks.append(Paragraph("<b>Payment terms</b>", _st["sub"]))
        blocks += _bullets(f["payment"], 6)
    if f["clauses"]:
        blocks.append(Paragraph("<b>Contractual conditions</b>", _st["sub"]))
        blocks += _bullets([{"text": c["text"], **(c["ref"] or {})} for c in f["clauses"]], 8)
    if f["workbooks"]:
        blocks.append(Paragraph("<b>Spreadsheets in the package</b>", _st["sub"]))
        blocks.append(_workbook_table(f["workbooks"]))
    if blocks:
        n += 1
        _emit(story, _sec(n, "Evaluation & Commercial Intelligence"), blocks)

    # 5. Material Findings & Procurement Changes
    n += 1
    blocks = []
    if f["changes"]:
        blocks.append(_table(["Item", "Previous / superseded", "Introduced by"], _change_rows(f["changes"]),
                             [BODY_W * 0.52, BODY_W * 0.30, BODY_W * 0.18]))
    else:
        blocks.append(Paragraph("No amending documents or changed values were found in the documents analysed; "
                                "requirements are as stated in the original package.", _st["body"]))
    sub_rows = _submission_rows(f)
    if sub_rows:
        blocks.append(Paragraph("<b>Submission instructions</b>", _st["sub"]))
        blocks.append(_kv(sub_rows))
    if f["sub_docs"]:
        blocks.append(Paragraph("<b>Required submission documents</b>", _st["sub"]))
        blocks += _bullets(f["sub_docs"], 14, with_refs=False)
        blocks.append(_refs_line(f["sub_docs"]))
    _emit(story, _sec(n, "Material Findings & Procurement Changes"), blocks)

    # 6. Decision Information Summary
    n += 1
    rows = []
    d = f["deadline"]
    if d["effective"]:
        rows.append(["Submission deadline", esc(fmt_date(d["effective"])) + (" (manually entered)" if d["manual"] else ""),
                     Paragraph(esc(ref_text(d["extracted_ref"])) if not d["manual"] else "Phoenix user", _st["cell_s"])])
    if sub.get("channel"):
        ms = (sub.get("method_sentences") or [None])[0]
        rows.append(["Submission method", esc(sub["channel"]), Paragraph(esc(ref_text(ms)), _st["cell_s"])])
    if top:
        rows.append(["Evaluation basis", esc(" / ".join(f"{c['stage']} {c['weight']}" for c in top)),
                     Paragraph(esc(ref_text(top[0]["ref"])), _st["cell_s"])])
    inc = next((p for p in f["pricing"] if _INCLUSIVE.search(p["text"])), None) or (f["pricing"] or [None])[0]
    if inc:
        rows.append(["Pricing basis", esc(clip(inc["text"], 220)), Paragraph(esc(ref_text(inc)), _st["cell_s"])])
    if f["payment"]:
        rows.append(["Payment terms", esc(clip(f["payment"][0]["text"], 220)), Paragraph(esc(ref_text(f["payment"][0])), _st["cell_s"])])
    if f["qualifications"]:
        rows.append(["Qualification conditions", f"{len([q for q in f['qualifications'] if not _is_subhead(q['text'])])} stated",
                     Paragraph(esc(ref_text(f["qualifications"][0])), _st["cell_s"])])
    if f["deliverables"]:
        rows.append(["Deliverables", f"{len([q for q in f['deliverables'] if not _is_subhead(q['text'])])} stated",
                     Paragraph(esc(ref_text(f["deliverables"][0])), _st["cell_s"])])
    nchg = len(f["changes"])
    rows.append(["Procurement changes", f"{nchg} identified" if nchg else "None identified", ""])
    unverified = [c for c in f["changes"] if c["kind"] == "CONFLICT"] + (
        [{"topic": "Submission deadline"}] if d["conflict"] and not d["amended_from"] else [])
    if unverified:
        rows.append(["Unverified matters", esc("; ".join(sorted({u["topic"] for u in unverified}))), ""])
    blocks = [_table(["Matter", "What the documents state", "Source"], rows, [BODY_W * 0.24, BODY_W * 0.54, BODY_W * 0.22]),
              Paragraph("This summary organises verified information for the bid decision. It does not recommend "
                        "whether to bid and contains no scores, probabilities or suitability judgements.", _st["note"])]
    _emit(story, _sec(n, "Decision Information Summary"), blocks)

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
