"""PDF rendering of the composed FAST and FULL content models, in the
application's brand style. Pure presentation: it prints what the composed
model contains and nothing else."""
from __future__ import annotations

import io
from datetime import date
from xml.sax.saxutils import escape

from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (KeepTogether, ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer,
                                Table, TableStyle)

import pdf_styles as ps

BODY_W = letter[0] - 36 * mm
_F, _FM = ps._font("regular"), ps._font("medium")
NIGHT, GOLD, IVORY, GREY = HexColor("#0A0A0F"), HexColor("#C9A96E"), HexColor("#F3EFE7"), HexColor("#6B675F")
ST = {
    "title": ParagraphStyle("t", fontName=_FM, fontSize=17, leading=21, textColor=NIGHT),
    "kicker": ParagraphStyle("k", fontName=_FM, fontSize=8, leading=10, textColor=GOLD),
    "h1": ParagraphStyle("h1", fontName=_FM, fontSize=11.5, leading=14, textColor=NIGHT, spaceBefore=9, spaceAfter=4),
    "h2": ParagraphStyle("h2", fontName=_FM, fontSize=9.2, leading=11.5, textColor=NIGHT, spaceBefore=5, spaceAfter=2),
    "body": ParagraphStyle("b", fontName=_F, fontSize=8.6, leading=11.2, textColor=HexColor("#282830"), alignment=TA_LEFT),
    "item": ParagraphStyle("i", fontName=_F, fontSize=8.4, leading=10.8, textColor=HexColor("#282830")),
    "note": ParagraphStyle("n", fontName=_F, fontSize=7.6, leading=9.6, textColor=GREY),
    "banner": ParagraphStyle("bn", fontName=_F, fontSize=8, leading=10.2, textColor=NIGHT),
    "cell": ParagraphStyle("c", fontName=_F, fontSize=8, leading=10.2),
    "cellb": ParagraphStyle("cb", fontName=_FM, fontSize=8, leading=10.2),
}
_LABEL_COLOUR = {"Unresolved conflict": "#C00000", "Interpretation disputed": "#E26B0A",
                 "Ambiguous in the source": "#E26B0A", "Updated": "#2B5C8A", "New": "#375623",
                 "From OCR text": "#6B675F"}


def _t(v) -> str:
    try:
        import phoenix_reports
        v = phoenix_reports.latin_only(v)
    except Exception:
        v = str(v if v is not None else "")
    return escape(v)


def _item_para(it: dict) -> Paragraph:
    labels = "".join(f'<font name="{_FM}" size="7" color="{_LABEL_COLOUR.get(lb, "#6B675F")}">'
                     f'{_t(lb.upper())}</font> ' for lb in it.get("labels") or [])
    refs = "; ".join(it.get("refs") or [])
    ref = f' <font size="7" color="#6B675F">[{_t(refs)}]</font>' if refs else ""
    return Paragraph(labels + _t(it["text"]) + ref, ST["item"])


def _bullets(items: list[dict]) -> ListFlowable:
    return ListFlowable([ListItem(_item_para(it), leftIndent=9, value="•") for it in items], bulletType="bullet",
                        start="•", leftIndent=9, bulletFontSize=7, bulletColor=GOLD)


def _kv(rows) -> Table:
    t = Table([[Paragraph(_t(k), ST["cellb"]), Paragraph(_t(v), ST["cell"])] for k, v in rows],
              colWidths=[BODY_W * 0.22, BODY_W * 0.78])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BACKGROUND", (0, 0), (0, -1), IVORY),
                           ("LINEBELOW", (0, 0), (-1, -1), 0.3, HexColor("#DDD6C8")),
                           ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    return t


def _banner(ver: dict) -> Table:
    colour = {"INDEPENDENTLY_VERIFIED": "#375623", "VERIFIED_WITH_LIMITATIONS": "#E26B0A",
              "SINGLE_ANALYST": "#E26B0A", "SYNTHETIC": "#C00000"}.get(ver.get("status"), "#C00000")
    text = f'<font name="{_FM}" color="{colour}">{_t(ver.get("status", "").replace("_", " "))}</font> — {_t(ver.get("text"))}'
    t = Table([[Paragraph(text, ST["banner"])]], colWidths=[BODY_W])
    t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, HexColor(colour)), ("BACKGROUND", (0, 0), (-1, -1), IVORY),
                           ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    return t


def _footer(label: str):
    def draw(canvas, doc):
        canvas.saveState()
        canvas.setFont(_F, 7)
        canvas.setFillColor(GREY)
        canvas.drawString(18 * mm, 10 * mm, f"Bid Intelligence · {label} · prepared {date.today().isoformat()}")
        canvas.drawRightString(letter[0] - 18 * mm, 10 * mm, f"Page {doc.page}")
        canvas.restoreState()
    return draw


def _head(rep: dict) -> list:
    story = [Paragraph(_t(("FAST · " if rep["kind"] == "FAST" else "FULL · ") + rep["title"].upper()), ST["kicker"]),
             Paragraph(_t(dict(rep.get("identity") or []).get("Opportunity") or "Procurement opportunity"), ST["title"]),
             Spacer(1, 6)]
    if rep.get("verification"):
        story += [_banner(rep["verification"]), Spacer(1, 6)]
    rows = [r for r in rep.get("identity") or [] if r[0] != "Opportunity"]
    if rows:
        story += [_kv(rows), Spacer(1, 6)]
    if rep.get("summary"):
        story.append(Paragraph(_t(" ".join(rep["summary"])), ST["body"]))
    return story


def _research(research: dict) -> list:
    if not research or research.get("status") != "COMPLETE":
        return [Paragraph("External buyer research was not available for this analysis. Documented procurement "
                          "facts above are unaffected.", ST["note"])]
    try:
        import phoenix_reports
        items = phoenix_reports.research_items_for_display(research, None)
    except Exception:
        items = research.get("items") or []
    if not items:
        return [Paragraph("External research found no verifiable public fact about this buyer beyond the "
                          "procurement documents.", ST["note"])]
    out = [Paragraph("Verified external facts, kept separate from the documented procurement requirements. "
                     "Historical facts are dated and do not imply current funding, partnerships or preferences.",
                     ST["note"])]
    out.append(_bullets([{"text": it.get("statement", ""), "refs": [it.get("url", "")[:90]], "labels": []}
                         for it in items]))
    return out


def _decision_ref(d: dict) -> list:
    out = []
    if d.get("submission"):
        out += [Paragraph("Submission logistics", ST["h2"]), _bullets(d["submission"])]
    if d.get("documents"):
        out += [Paragraph("Documents and forms to submit (checklist)", ST["h2"]), _bullets(d["documents"])]
    if d.get("clarifications") or d.get("qa_window_notice"):
        out.append(Paragraph("Open questions for the buyer", ST["h2"]))
        if d.get("qa_window_notice"):
            out.append(Paragraph(_t(d["qa_window_notice"]), ST["note"]))
        if d.get("clarifications"):
            out.append(_bullets([{"text": c["question"], "refs": [], "labels": []} for c in d["clarifications"]]))
    cov = d.get("coverage") or {}
    probs = cov.get("problems") or []
    out.append(Paragraph("Source coverage", ST["h2"]))
    if probs:
        out.append(_bullets([{"text": f"{p['ref']}: {p['note'] or p['status'].lower()}", "refs": [], "labels": []}
                             for p in probs[:40]]))
    else:
        out.append(Paragraph(f"All {cov.get('locations', 0)} pages/sections of the package were read.", ST["note"]))
    return out


def render(rep: dict, *, limitations_appendix: bool = True) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
                            bottomMargin=16 * mm, title=rep["title"])
    story = _head(rep)
    for n, sec in enumerate(rep["sections"], 1):
        block = [Paragraph(f"{n}. {_t(sec['title'])}", ST["h1"])]
        if sec.get("items"):
            block.append(_bullets(sec["items"]))
        for g in sec.get("groups") or []:
            if g.get("items"):
                block += [Paragraph(_t(g["title"]), ST["h2"]), _bullets(g["items"])]
        if "research" in sec:
            block += _research(sec["research"])
        if sec.get("analysis"):
            block.append(Paragraph("Analysis by Bid Intelligence, grounded in the cited provisions. It is "
                                   "interpretation, not a document fact.", ST["note"]))
            block.append(_bullets([{"text": f"{p['heading']}: {p['analysis']}", "refs": p.get("refs") or [],
                                    "labels": [p.get("kind", "").replace("_", " ").title()]} for p in sec["analysis"]]))
        if sec.get("decision_reference"):
            block += _decision_ref(sec["decision_reference"])
        story.append(KeepTogether(block[:2]))
        story += block[2:]
    ver = rep.get("verification") or {}
    if limitations_appendix and ver.get("limitations"):
        story += [Paragraph("Verification limitations", ST["h1"]),
                  _bullets([{"text": x, "refs": [], "labels": []} for x in ver["limitations"]])]
    label = "Opportunity Snapshot" if rep["kind"] == "FAST" else "Bid Opportunity Assessment"
    doc.build(story, onFirstPage=_footer(label), onLaterPages=_footer(label))
    return buf.getvalue()
