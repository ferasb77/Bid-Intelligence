"""ReportLab renderer for the primary, concise UNDERSTAND customer export."""
from __future__ import annotations

from pathlib import Path
import html
import tempfile

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import BaseDocTemplate, Frame, PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle

from understand_brief import BidIntelligenceBrief

ROOT = Path(__file__).resolve().parent
FONTS = ROOT / "assets" / "fonts"
for name, filename in (("BriefDisplay", "CormorantGaramond-SemiBold.otf"), ("BriefBody", "Inter-Regular.otf"), ("BriefBodyMed", "Inter-Medium.otf")):
    try: pdfmetrics.registerFont(TTFont(name, str(FONTS / filename)))
    except (KeyError, OSError): pass
NIGHT, INK, GOLD, MUTED, RULE, BAND, PAPER = map(HexColor, ("#111111", "#1C1B1F", "#B5924F", "#6B675F", "#D9D5CC", "#F4F1EA", "#FFFFFF"))
MARGIN = .72 * inch
styles = {
    "cover": ParagraphStyle("cover", fontName="BriefDisplay", fontSize=35, leading=40, textColor=INK, spaceAfter=12),
    "title": ParagraphStyle("title", fontName="BriefDisplay", fontSize=27, leading=31, textColor=INK, spaceAfter=6),
    "sub": ParagraphStyle("sub", fontName="BriefDisplay", fontSize=17, leading=22, textColor=INK, spaceAfter=14),
    "h2": ParagraphStyle("h2", fontName="BriefDisplay", fontSize=15, leading=19, textColor=INK, spaceBefore=9, spaceAfter=4),
    "body": ParagraphStyle("body", fontName="BriefBody", fontSize=9.1, leading=12.4, textColor=INK, spaceAfter=4),
    "cell": ParagraphStyle("cell", fontName="BriefBody", fontSize=8.1, leading=10.7, textColor=INK),
    "cellb": ParagraphStyle("cellb", fontName="BriefBodyMed", fontSize=8.1, leading=10.7, textColor=INK),
    "head": ParagraphStyle("head", fontName="BriefBodyMed", fontSize=8.1, leading=10.3, textColor=PAPER),
    "note": ParagraphStyle("note", fontName="BriefBody", fontSize=8.2, leading=11, textColor=MUTED),
}

def _p(value, kind="body"):
    return Paragraph(html.escape(str(value or "—")).replace("\n", "<br/>"), styles[kind])

def _table(headers, rows, widths):
    data = [[_p(h, "head") for h in headers]] + [[_p(v, "cellb" if i == 0 else "cell") for i, v in enumerate(row)] for row in rows]
    table = Table(data, colWidths=widths, repeatRows=1)
    table.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), NIGHT), ("ROWBACKGROUNDS", (0,1), (-1,-1), [PAPER, BAND]), ("VALIGN", (0,0), (-1,-1), "TOP"), ("GRID", (0,0), (-1,-1), .25, RULE), ("TOPPADDING", (0,0), (-1,-1), 4), ("BOTTOMPADDING", (0,0), (-1,-1), 4), ("LEFTPADDING", (0,0), (-1,-1), 6), ("RIGHTPADDING", (0,0), (-1,-1), 6)]))
    return table

def _header(canvas, doc):
    canvas.saveState(); canvas.setStrokeColor(RULE); canvas.line(MARGIN, 10.85*inch, 7.78*inch, 10.85*inch)
    canvas.setFont("BriefBodyMed", 7.5); canvas.setFillColor(GOLD); canvas.drawString(MARGIN, 10.98*inch, "BID INTELLIGENCE BRIEF")
    canvas.setFont("BriefBody", 7.5); canvas.setFillColor(MUTED); canvas.drawRightString(7.78*inch, 10.98*inch, doc.brief_header)
    canvas.line(MARGIN, .55*inch, 7.78*inch, .55*inch); canvas.drawString(MARGIN, .38*inch, "Confidential · prepared for bid-team review · Enable My Growth / Bid Intelligence")
    canvas.setFillColor(GOLD); canvas.drawRightString(7.78*inch, .38*inch, str(canvas.getPageNumber()-1)); canvas.restoreState()

def _cover(canvas, doc):
    canvas.saveState(); canvas.setFillColor(PAPER); canvas.rect(0,0,8.5*inch,11*inch,fill=1,stroke=0); canvas.restoreState()

def render_pdf(model: BidIntelligenceBrief, output_path: str | Path) -> Path:
    output_path = Path(output_path); output_path.parent.mkdir(parents=True, exist_ok=True)
    doc = BaseDocTemplate(str(output_path), pagesize=LETTER, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=.9*inch, bottomMargin=.75*inch, title=f"Bid Intelligence Brief — {model.solicitation}")
    doc.brief_header = f"{model.buyer} · {model.solicitation}"
    frame = Frame(MARGIN, .72*inch, 7.06*inch, 9.95*inch, id="body")
    doc.addPageTemplates([PageTemplate(id="cover", frames=[frame], onPage=_cover), PageTemplate(id="body", frames=[frame], onPage=_header)])
    s=[]
    s += [Spacer(1, 1.45*inch), _p("AN ENABLE MY GROWTH APPLICATION", "note"), Spacer(1, .22*inch), _p("BID INTELLIGENCE BRIEF", "cover"), _p(f"{model.buyer} · {model.solicitation}", "sub"), _p(model.opportunity, "sub"), Spacer(1,.18*inch)]
    purpose = "A concise buyer-intelligence summary of what is being procured, how proposals will be evaluated, what must be submitted, and material commercial terms."
    callout=Table([[Paragraph("<b>Purpose of this brief</b><br/>"+html.escape(purpose), styles["body"])]], colWidths=[7.06*inch]); callout.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),BAND),("LINEBEFORE",(0,0),(0,-1),2,GOLD),("LEFTPADDING",(0,0),(-1,-1),9),("RIGHTPADDING",(0,0),(-1,-1),9),("TOPPADDING",(0,0),(-1,-1),8),("BOTTOMPADDING",(0,0),(-1,-1),8)])); s += [callout, Spacer(1,.25*inch), _p("Prepared for bid-team review", "h2"), _p("Source package reviewed: " + "; ".join(model.source_documents[:8]), "note")]
    s += [PageBreak()]
    section_number = 0
    def section(title):
        nonlocal section_number
        section_number += 1
        s.extend([_p(str(section_number), "note"), _p(title, "title")])
    section("Executive Opportunity Snapshot")
    s.append(_table(["Fact", "Buyer-issued information"], model.snapshot, [2.1*inch,4.96*inch]))
    if model.partial_sections: s += [Spacer(1,6), _p("Some cross-domain analysis is incomplete. Verified buyer facts remain available; interpretive priority sections may be partial.", "note")]
    if model.immediate_matter: s += [_p("What matters immediately", "h2"), _p(model.immediate_matter)]
    if model.buyer_intent: s += [_p("Buyer intent", "h2")] + [_p("• " + x) for x in model.buyer_intent]
    if model.scope_intro or model.service_scope or model.success_profile:
        s += [PageBreak()]
        section("What the Buyer Is Buying")
        if model.scope_intro: s.append(_p(model.scope_intro))
        if model.service_scope: s += [_p("Core service scope", "h2")] + [_p("• " + x) for x in model.service_scope]
        if model.success_profile: s += [_p("Success profile implied by the RFP", "h2"), _p(model.success_profile)]
    if model.criteria:
        s += [PageBreak()]; section("How the Bid Will Be Evaluated")
        s.append(_table(["Criterion","Weight","Minimum","What the response must demonstrate"], [(x.name,x.weight,x.minimum or "—",x.response_expectation or "Not available from durable buyer intelligence") for x in model.criteria], [1.55*inch,.68*inch,.72*inch,4.11*inch]))
        if model.evaluation_implication: s += [_p("Response implication", "h2"), _p(model.evaluation_implication)]
    if model.submission or model.key_dates:
        s += [PageBreak()]; section("Submission Requirements & Critical Mechanics")
        if model.submission: s.append(_table(["Item","Requirement","Source / note"], model.submission, [1.28*inch,3.65*inch,2.13*inch]))
        if model.key_dates: s += [_p("Key dates", "h2")] + [_p("• " + x) for x in model.key_dates]
        if model.submission_distinction: s += [_p("Critical submission distinction", "h2"), _p(model.submission_distinction)]
    if model.commercial:
        s += [PageBreak()]; section("Commercial & Contractual Watch-outs")
        s.append(_table(["Topic","Material buyer term"], model.commercial, [2.1*inch,4.96*inch]))
        if model.commercial_implication: s += [_p("Commercial point to model carefully", "h2"), _p(model.commercial_implication)]
    s += [PageBreak()]; section("Bid-Team Priorities Before Writing")
    if model.priorities: s.append(_table(["#","Priority","What the team should do"], [(str(i),x.title,x.action) for i,x in enumerate(model.priorities,1)], [.3*inch,2.4*inch,4.36*inch]))
    if model.clarifications: s += [_p("Questions worth clarifying", "h2")] + [_p("• " + x) for x in model.clarifications]
    s += [_p("Source note", "h2"), _p("This brief summarizes the buyer-issued source package represented in the completed analysis; it does not replace those source documents.", "note")]
    doc.build(s); return output_path

def render_report(model: BidIntelligenceBrief) -> bytes:
    with tempfile.TemporaryDirectory() as directory:
        path = render_pdf(model, Path(directory) / "bid_intelligence_brief.pdf")
        return path.read_bytes()
