"""PDF rendering of the composed FAST and FULL content models, in the
application's brand style. Pure presentation: it prints what the composed
model contains and nothing else."""
from __future__ import annotations

import io
import re
from datetime import date
from xml.sax.saxutils import escape

from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (HRFlowable, KeepTogether, ListFlowable, ListItem, Paragraph, SimpleDocTemplate,
                                Spacer, Table, TableStyle)
from reportlab.platypus.flowables import _listWrapOn

MARGIN = 18 * mm
BODY_W = letter[0] - 2 * MARGIN
# ReportLab built-in base-14 fonts only: rendering needs no font files and is fully portable.
_F, _FM = "Helvetica", "Helvetica-Bold"
# Palette (hex strings are reused inside Paragraph <font color> markup).
INK_HEX, BODY_HEX, MUTED_HEX = "#0A0A0F", "#1F242D", "#636B78"
GOLD_HEX, GOLD_DARK_HEX, TINT_HEX, BORDER_HEX = "#C9A96E", "#7A6038", "#F7F5F0", "#E2DDD2"
ALERT_BG_HEX, ALERT_BORDER_HEX, RISK_RED_HEX, DEP_BLUE_HEX = "#FDF6EC", "#C58A2B", "#9B2C2C", "#2B547E"
INK, BODY, MUTED = HexColor(INK_HEX), HexColor(BODY_HEX), HexColor(MUTED_HEX)
GOLD, GOLD_DARK, TINT, BORDER = HexColor(GOLD_HEX), HexColor(GOLD_DARK_HEX), HexColor(TINT_HEX), HexColor(BORDER_HEX)
ALERT_BG, ALERT_BORDER = HexColor(ALERT_BG_HEX), HexColor(ALERT_BORDER_HEX)
RISK_RED, DEP_BLUE = HexColor(RISK_RED_HEX), HexColor(DEP_BLUE_HEX)
WHITE = HexColor("#FFFFFF")
ST = {
    "title": ParagraphStyle("t", fontName=_FM, fontSize=15.5, leading=19.5, textColor=WHITE),
    "kicker": ParagraphStyle("k", fontName=_FM, fontSize=7.8, leading=10, textColor=GOLD),
    "h1": ParagraphStyle("h1", fontName=_FM, fontSize=12, leading=15, textColor=INK, spaceBefore=12, spaceAfter=2,
                         keepWithNext=1),
    "h2": ParagraphStyle("h2", fontName=_FM, fontSize=9.8, leading=12.4, textColor=GOLD_DARK, spaceBefore=10,
                         spaceAfter=4, keepWithNext=1),
    "body": ParagraphStyle("b", fontName=_F, fontSize=9.4, leading=13.4, textColor=BODY, alignment=TA_LEFT),
    "item": ParagraphStyle("i", fontName=_F, fontSize=9.3, leading=13.3, textColor=BODY,
                           allowOrphans=0, allowWidows=0),
    "note": ParagraphStyle("n", fontName=_F, fontSize=8, leading=10.6, textColor=MUTED, keepWithNext=1),
    "alert": ParagraphStyle("al", fontName=_F, fontSize=8.4, leading=11.2, textColor=BODY),
    "banner": ParagraphStyle("bn", fontName=_F, fontSize=8.2, leading=10.8, textColor=BODY),
    "cell": ParagraphStyle("c", fontName=_F, fontSize=8.6, leading=11.2, textColor=BODY),
    "cellb": ParagraphStyle("cb", fontName=_FM, fontSize=8.6, leading=11.2, textColor=INK),
}
_LABEL_COLOUR = {"Unresolved conflict": RISK_RED_HEX, "Interpretation disputed": ALERT_BORDER_HEX,
                 "Ambiguous in the source": ALERT_BORDER_HEX, "Updated": DEP_BLUE_HEX, "New": "#375623",
                 "From OCR text": MUTED_HEX,
                 # Specialist Analysis lead-in tags
                 "Risk": RISK_RED_HEX, "Open Question": GOLD_DARK_HEX, "Dependency": DEP_BLUE_HEX}
# inline lapse warning appended by reports._annotate_lapsed; matched on the already-escaped text
_LAPSED = re.compile(r"\[LAPSED PER UPLOADED DOCUMENTS[^\]]*\]")


def _t_plain(v) -> str:
    """Latin-safe plain text (no XML escaping) -- for direct canvas drawing."""
    try:
        import phoenix_reports
        return phoenix_reports.latin_only(v)
    except Exception:
        return str(v if v is not None else "")


def _t(v) -> str:
    return escape(_t_plain(v))


def _item_para(it: dict) -> Paragraph:
    labels = "".join(f'<font name="{_FM}" size="7.6" color="{_LABEL_COLOUR.get(lb, MUTED_HEX)}">'
                     f'{_t(lb.upper())}</font> ' for lb in it.get("labels") or [])
    text = _LAPSED.sub(lambda m: f'<font name="{_FM}" color="{RISK_RED_HEX}">{m.group(0)}</font>', _t(it["text"]))
    refs = "; ".join(it.get("refs") or [])
    ref = f' <font size="8" color="{MUTED_HEX}">[{_t(refs)}]</font>' if refs else ""
    return Paragraph(labels + text + ref, ST["item"])


def _bullets(items: list[dict]) -> ListFlowable:
    return ListFlowable([ListItem(_item_para(it), leftIndent=10, value="•", spaceAfter=4) for it in items],
                        bulletType="bullet", start="•", leftIndent=10, bulletFontSize=7.5, bulletColor=GOLD,
                        spaceAfter=4)


def _callout(paras: list, fill, stripe, width: float, pad: float, *, keep_with_next: bool = False) -> Table:
    """Full-width tinted box with a coloured left stripe (one row per paragraph). splitInRow lets an
    unusually long paragraph continue on the next page instead of raising a LayoutError."""
    t = Table([[p] for p in paras], colWidths=[BODY_W], splitInRow=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), fill), ("LINEBEFORE", (0, 0), (0, -1), width, stripe),
                           ("LEFTPADDING", (0, 0), (-1, -1), pad + 2), ("RIGHTPADDING", (0, 0), (-1, -1), pad),
                           ("TOPPADDING", (0, 0), (-1, -1), pad), ("BOTTOMPADDING", (0, 0), (-1, -1), pad)]))
    if keep_with_next:
        t.keepWithNext = 1
    return t


def _qa_notice(text: str) -> Table:
    """Q&A window notice: compact alert callout that stays with what follows it (never orphaned)."""
    return _callout([Paragraph(_t(text), ST["alert"])], ALERT_BG, ALERT_BORDER, 2.5, 6, keep_with_next=True)


def _h1(text: str) -> list:
    """Section heading with a gold bottom hairline; both carry keepWithNext."""
    rule = HRFlowable(width="100%", thickness=0.6, color=GOLD, spaceBefore=0, spaceAfter=6)
    rule.keepWithNext = 1
    return [Paragraph(text, ST["h1"]), rule]


def _kv(rows) -> Table:
    t = Table([[Paragraph(_t(k), ST["cellb"]), Paragraph(_t(v), ST["cell"])] for k, v in rows],
              colWidths=[BODY_W * 0.24, BODY_W * 0.76])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BACKGROUND", (0, 0), (0, -1), TINT),
                           ("LINEABOVE", (0, 0), (-1, 0), 1.2, GOLD),
                           ("LINEBELOW", (0, 0), (-1, -1), 0.4, BORDER),
                           ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                           ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    return t


def _banner(ver: dict) -> Table:
    colour = {"INDEPENDENTLY_VERIFIED": "#375623", "VERIFIED_WITH_LIMITATIONS": ALERT_BORDER_HEX,
              "SINGLE_ANALYST": ALERT_BORDER_HEX, "SYNTHETIC": RISK_RED_HEX}.get(ver.get("status"), RISK_RED_HEX)
    text = f'<font name="{_FM}" color="{colour}">{_t(ver.get("status", "").replace("_", " "))}</font> — {_t(ver.get("text"))}'
    t = Table([[Paragraph(text, ST["banner"])]], colWidths=[BODY_W])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), TINT), ("LINEBEFORE", (0, 0), (0, -1), 3, HexColor(colour)),
                           ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                           ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5)]))
    return t


def _masthead(rep: dict) -> Table:
    kicker = ("FAST " if rep["kind"] == "FAST" else "FULL ") + rep["title"].upper()
    title = dict(rep.get("identity") or []).get("Opportunity") or "Procurement opportunity"
    t = Table([[Paragraph(_t(kicker), ST["kicker"])], [Paragraph(_t(title), ST["title"])]], colWidths=[BODY_W])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), INK),
                           ("LEFTPADDING", (0, 0), (-1, -1), 12), ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                           ("TOPPADDING", (0, 0), (-1, 0), 11), ("BOTTOMPADDING", (0, 0), (-1, 0), 3),
                           ("TOPPADDING", (0, 1), (-1, 1), 0), ("BOTTOMPADDING", (0, 1), (-1, 1), 12)]))
    return t


def _footer(label: str, prepared: str = ""):
    prepared = prepared or date.today().isoformat()

    def draw(canvas, doc):
        canvas.saveState()
        canvas.setFont(_F, 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(MARGIN, 10 * mm, f"Bid Intelligence · {label} · prepared {prepared}")
        canvas.restoreState()
    return draw


def _numbered_canvas(header: str):
    """Single-pass canvasmaker: pages are buffered so that every page can show
    "Page N of M", and pages 2+ carry a running header with a thin rule."""
    header = header[:110]

    class NumberedCanvas(Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._saved_pages = []

        def showPage(self):
            self._saved_pages.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._saved_pages)
            for state in self._saved_pages:
                self.__dict__.update(state)
                self._decorate(total)
                super().showPage()
            super().save()

        def _decorate(self, total: int):
            n = self._pageNumber
            self.saveState()
            self.setFont(_F, 7)
            self.setFillColor(MUTED)
            self.drawRightString(letter[0] - MARGIN, 10 * mm, f"Page {n} of {total}")
            if n > 1 and header:
                y = letter[1] - 10 * mm
                self.drawString(MARGIN, y, header)
                self.setStrokeColor(GOLD)
                self.setLineWidth(0.5)
                self.line(MARGIN, y - 2 * mm, letter[0] - MARGIN, y - 2 * mm)
            self.restoreState()
    return NumberedCanvas


class _KeepWithFirst(KeepTogether):
    """keepWithNext group (heading [+ note] + following flowable) that only
    requires the heading(s) and the FIRST item of a following list to share a
    page; the rest of the list flows naturally instead of being pushed whole."""

    def split(self, aW, aH):
        if getattr(self, "_wrapInfo", None) != (aW, aH):
            self.wrap(aW, aH)
        S = self._content[:]
        last = S[-1]
        lead = S[:-1] + ((last._content[:1] or [last]) if isinstance(last, ListFlowable) else [last])
        need = _listWrapOn(lead, aW, self.canv)[1]
        cf = getattr(self, "_frame", None)
        if need > aH and not (cf and getattr(cf, "_atTop", 0)):
            S.insert(0, self.FrameBreak())
        return S


def _head(rep: dict) -> list:
    story = [_masthead(rep), Spacer(1, 7)]
    if rep.get("verification"):
        story += [_banner(rep["verification"]), Spacer(1, 8)]
    rows = [r for r in rep.get("identity") or [] if r[0] != "Opportunity"]
    if rows:
        story += [_kv(rows), Spacer(1, 10)]
    if rep.get("summary"):
        story.append(_callout([Paragraph(_t(" ".join(rep["summary"])), ST["body"])], TINT, GOLD, 3, 9))
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
            out.append(_qa_notice(d["qa_window_notice"]))
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
    doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN,
                            bottomMargin=MARGIN, title=rep["title"], keepTogetherClass=_KeepWithFirst)
    story = _head(rep)
    for n, sec in enumerate(rep["sections"], 1):
        block = _h1(f"{n}. {_t(sec['title'])}")
        if sec.get("qa_window_notice"):
            block.append(_qa_notice(sec["qa_window_notice"]))
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
        # h1 / h2 / note carry keepWithNext: the heading (+ optional notice) stays with the
        # first bullet only (_KeepWithFirst); a whole list is never pushed to the next page.
        story += block
    ver = rep.get("verification") or {}
    if limitations_appendix and ver.get("limitations"):
        story += _h1("Verification limitations") + [
                  _bullets([{"text": x, "refs": [], "labels": []} for x in ver["limitations"]])]
    label = "Opportunity Snapshot" if rep["kind"] == "FAST" else "Bid Opportunity Assessment"
    footer = _footer(label, str(rep.get("run_date") or "")[:10])
    header = dict(rep.get("identity") or []).get("Opportunity") or "Procurement opportunity"
    doc.build(story, onFirstPage=footer, onLaterPages=footer, canvasmaker=_numbered_canvas(_t_plain(header)))
    return buf.getvalue()
