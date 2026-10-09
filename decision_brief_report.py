"""Executive ReportLab PDF Renderer for Bid Intelligence Decision Brief (BI-VALUE-3).

Generates a professional 7-8 page consulting decision brief formatted for
bid directors, proposal leads, and executive decision-makers.

Page Architecture:
- Page 1: Executive Opportunity Snapshot (Postures, Metadata, Observations, Blockers)
- Page 2: What the Buyer Is Actually Buying (Audience, Deliverables, Model, Scope)
- Page 3: Buyer Intelligence & Strategic Context (yorku.ca Signals, Mandate, Policy)
- Page 4: Technical Capability Requirements (Provider Profile, 13 Key Capabilities)
- Page 5: How the Bid Will Be Evaluated (Scoring Structure, 80/20, Subcriteria)
- Page 6: What the Bidder Must Prove (Mandatory Evidence vs Strategy Recommendations)
- Page 7: Risks, Commercial Watch-outs & Bid Team Priorities (Gates, Terms, Actions)
- Page 8: Pre-Bid Clarifications & Decision Sign-off
"""
from __future__ import annotations

import html
import tempfile
from pathlib import Path
from typing import Sequence

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from decision_brief import DecisionBrief, EpistemicClass

# ---------------------------------------------------------------------------
# Font Registration & Color Palette
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent
FONTS = ROOT / "assets" / "fonts"

DISPLAY_FONT = "Helvetica-Bold"
BODY_FONT = "Helvetica"
BODY_MED_FONT = "Helvetica-Bold"

for name, filename in (
    ("BriefDisplay", "CormorantGaramond-SemiBold.otf"),
    ("BriefBody", "Inter-Regular.otf"),
    ("BriefBodyMed", "Inter-Medium.otf"),
):
    try:
        font_path = str(FONTS / filename)
        if (FONTS / filename).exists():
            pdfmetrics.registerFont(TTFont(name, font_path))
            if name == "BriefDisplay":
                DISPLAY_FONT = "BriefDisplay"
            elif name == "BriefBody":
                BODY_FONT = "BriefBody"
            elif name == "BriefBodyMed":
                BODY_MED_FONT = "BriefBodyMed"
    except Exception:
        pass

# Palette
NIGHT = HexColor("#0F172A")    # Slate 900
DARK_BLUE = HexColor("#1E293B")# Slate 800
INK = HexColor("#1E1E24")      # Neutral dark
GOLD = HexColor("#92400E")     # Amber 800 / Warm Gold
GOLD_BG = HexColor("#FEF3C7")  # Amber 100
MUTED = HexColor("#64748B")    # Slate 500
RULE = HexColor("#E2E8F0")     # Slate 200
BAND = HexColor("#F8FAFC")     # Slate 50
PAPER = HexColor("#FFFFFF")
TAG_BLUE_BG = HexColor("#EFF6FF")
TAG_BLUE_TXT = HexColor("#1E40AF")
TAG_GREEN_BG = HexColor("#F0FDF4")
TAG_GREEN_TXT = HexColor("#166534")
TAG_AMBER_BG = HexColor("#FFFBEB")
TAG_AMBER_TXT = HexColor("#B45309")
BORDER_CARD = HexColor("#CBD5E1")

MARGIN_X = 0.58 * inch
PAGE_WIDTH = 8.5 * inch
USABLE_WIDTH = PAGE_WIDTH - (2 * MARGIN_X)  # ~7.34 in = ~528 pt

# ---------------------------------------------------------------------------
# Typography Styles
# ---------------------------------------------------------------------------

styles = {
    "cover_tag": ParagraphStyle("cover_tag", fontName=BODY_MED_FONT, fontSize=7.8, leading=10, textColor=GOLD, spaceAfter=4),
    "cover_title": ParagraphStyle("cover_title", fontName=DISPLAY_FONT, fontSize=24, leading=27, textColor=NIGHT, spaceAfter=4),
    "cover_sub": ParagraphStyle("cover_sub", fontName=BODY_MED_FONT, fontSize=11, leading=14, textColor=DARK_BLUE, spaceAfter=8),
    "section_h1": ParagraphStyle("section_h1", fontName=DISPLAY_FONT, fontSize=16, leading=19, textColor=NIGHT, spaceBefore=4, spaceAfter=5),
    "section_num": ParagraphStyle("section_num", fontName=BODY_MED_FONT, fontSize=7.5, leading=9, textColor=GOLD, spaceAfter=2),
    "h2": ParagraphStyle("h2", fontName=BODY_MED_FONT, fontSize=9.5, leading=12, textColor=DARK_BLUE, spaceBefore=5, spaceAfter=3),
    "body": ParagraphStyle("body", fontName=BODY_FONT, fontSize=8.1, leading=10.8, textColor=INK, spaceAfter=3),
    "body_bold": ParagraphStyle("body_bold", fontName=BODY_MED_FONT, fontSize=8.1, leading=10.8, textColor=INK),
    "bullet": ParagraphStyle("bullet", fontName=BODY_FONT, fontSize=8.0, leading=10.6, textColor=INK, leftIndent=8, spaceAfter=2),
    "meta_label": ParagraphStyle("meta_label", fontName=BODY_MED_FONT, fontSize=7.8, leading=10, textColor=DARK_BLUE),
    "meta_val": ParagraphStyle("meta_val", fontName=BODY_FONT, fontSize=7.8, leading=10.2, textColor=INK),
    "table_head": ParagraphStyle("table_head", fontName=BODY_MED_FONT, fontSize=7.8, leading=10, textColor=PAPER),
    "table_cell": ParagraphStyle("table_cell", fontName=BODY_FONT, fontSize=7.5, leading=9.8, textColor=INK),
    "table_cell_bold": ParagraphStyle("table_cell_bold", fontName=BODY_MED_FONT, fontSize=7.5, leading=9.8, textColor=INK),
    "callout": ParagraphStyle("callout", fontName=BODY_FONT, fontSize=8.1, leading=11, textColor=INK),
    "badge_rfp": ParagraphStyle("badge_rfp", fontName=BODY_MED_FONT, fontSize=6.8, leading=8.5, textColor=TAG_BLUE_TXT),
    "badge_ext": ParagraphStyle("badge_ext", fontName=BODY_MED_FONT, fontSize=6.8, leading=8.5, textColor=TAG_GREEN_TXT),
    "badge_interp": ParagraphStyle("badge_interp", fontName=BODY_MED_FONT, fontSize=6.8, leading=8.5, textColor=TAG_AMBER_TXT),
    "note": ParagraphStyle("note", fontName=BODY_FONT, fontSize=7.2, leading=9.2, textColor=MUTED),
}


def _p(text: str, kind: str = "body") -> Paragraph:
    safe = html.escape(str(text or "—")).replace("\n", "<br/>")
    return Paragraph(safe, styles[kind])


def _badge(eclass: str) -> Paragraph:
    if eclass == EpistemicClass.RFP_FACT.value:
        return Paragraph(f"<b>[RFP FACT]</b>", styles["badge_rfp"])
    elif eclass == EpistemicClass.EXTERNAL_BUYER_FACT.value:
        return Paragraph(f"<b>[EXTERNAL BUYER FACT]</b>", styles["badge_ext"])
    elif eclass == EpistemicClass.BID_INTELLIGENCE_INTERPRETATION.value:
        return Paragraph(f"<b>[INTERPRETATION]</b>", styles["badge_interp"])
    elif eclass == EpistemicClass.BID_STRATEGY_RECOMMENDATION.value:
        return Paragraph(f"<b>[STRATEGY REC]</b>", styles["badge_interp"])
    return Paragraph(f"<b>[UNKNOWN]</b>", styles["note"])


def _card(title: str, content: str | list[str], badge_class: str | None = None) -> Table:
    rows = []
    head_content = []
    if badge_class:
        head_content.append(_badge(badge_class))
    head_content.append(_p(title, "body_bold"))
    rows.append([head_content])
    
    if isinstance(content, list):
        body_flow = [_p(f"• {item}", "bullet") for item in content]
        rows.append([body_flow])
    else:
        rows.append([_p(content, "body")])

    t = Table(rows, colWidths=[USABLE_WIDTH])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BAND),
        ("BOX", (0, 0), (-1, -1), 0.5, BORDER_CARD),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("LINEBEFORE", (0, 0), (0, -1), 2.5, GOLD),
    ]))
    return t


def _table(headers: list[str], data_rows: list[list[Any]], widths: list[float], header_bg=NIGHT) -> Table:
    head = [_p(h, "table_head") for h in headers]
    body = []
    for r in data_rows:
        row_cells = []
        for i, val in enumerate(r):
            if isinstance(val, Paragraph):
                row_cells.append(val)
            elif isinstance(val, (list, tuple)):
                row_cells.append(val)
            else:
                row_cells.append(_p(val, "table_cell_bold" if i == 0 else "table_cell"))
        body.append(row_cells)

    table = Table([head] + body, colWidths=widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), header_bg),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [PAPER, BAND]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.3, RULE),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


# ---------------------------------------------------------------------------
# Page Layout Canvas Callbacks (Header & Footer)
# ---------------------------------------------------------------------------

def _draw_header_footer(canvas, doc):
    canvas.saveState()
    # Running Top Header
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.6)
    canvas.line(MARGIN_X, 10.45 * inch, PAGE_WIDTH - MARGIN_X, 10.45 * inch)
    
    canvas.setFont(BODY_MED_FONT, 7.5)
    canvas.setFillColor(GOLD)
    canvas.drawString(MARGIN_X, 10.55 * inch, "BID INTELLIGENCE DECISION BRIEF")
    
    canvas.setFont(BODY_FONT, 7.5)
    canvas.setFillColor(MUTED)
    header_right = getattr(doc, "brief_header", "Executive Decision Brief")
    canvas.drawRightString(PAGE_WIDTH - MARGIN_X, 10.55 * inch, header_right)
    
    # Running Bottom Footer
    canvas.line(MARGIN_X, 0.52 * inch, PAGE_WIDTH - MARGIN_X, 0.52 * inch)
    canvas.drawString(MARGIN_X, 0.38 * inch, "Confidential · Prepared for Bid Decision Maker · Enable My Growth / Bid Intelligence")
    canvas.setFont(BODY_MED_FONT, 7.5)
    canvas.setFillColor(DARK_BLUE)
    canvas.drawRightString(PAGE_WIDTH - MARGIN_X, 0.38 * inch, f"Page {canvas.getPageNumber()}")
    canvas.restoreState()


# ---------------------------------------------------------------------------
# Primary PDF Renderer (7-8 Pages)
# ---------------------------------------------------------------------------

def render_decision_brief_pdf(brief: DecisionBrief, output_path: str | Path) -> Path:
    """Render the 8-page primary Decision Brief to PDF."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    doc = BaseDocTemplate(
        str(output_path),
        pagesize=LETTER,
        leftMargin=MARGIN_X,
        rightMargin=MARGIN_X,
        topMargin=0.68 * inch,
        bottomMargin=0.62 * inch,
        title=f"Bid Intelligence Brief — {brief.solicitation}",
    )
    doc.brief_header = f"{brief.buyer} · {brief.solicitation}"

    frame = Frame(
        MARGIN_X,
        0.58 * inch,
        USABLE_WIDTH,
        9.80 * inch,
        id="body",
        topPadding=0,
        bottomPadding=0,
        leftPadding=0,
        rightPadding=0,
    )
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=_draw_header_footer)])

    story = []

    # =========================================================================
    # PAGE 1: EXECUTIVE OPPORTUNITY SNAPSHOT
    # =========================================================================
    story.append(_p("ENABLE MY GROWTH · STRATEGIC BID INTELLIGENCE", "cover_tag"))
    story.append(_p(brief.opportunity, "cover_title"))
    story.append(_p(f"{brief.buyer}  |  Solicitation: {brief.solicitation}", "cover_sub"))

    # Posture Callout
    posture_table = Table([[
        _p("<b>OPPORTUNITY POSTURE:</b> " + brief.opportunity_posture, "callout")
    ]], colWidths=[USABLE_WIDTH])
    posture_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), GOLD_BG),
        ("LINEBEFORE", (0, 0), (0, -1), 3, GOLD),
        ("BOX", (0, 0), (-1, -1), 0.5, GOLD),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(posture_table)
    story.append(Spacer(1, 4))

    # Snapshot Metadata Table
    story.append(_p("Key Procurement Parameters", "h2"))
    story.append(_table(
        ["Procurement Parameter", "Buyer-Issued Detail"],
        [[label, val] for label, val in brief.snapshot_rows[:8]],
        [1.85 * inch, USABLE_WIDTH - 1.85 * inch],
    ))
    story.append(Spacer(1, 4))

    # Decision-Driving Observations
    story.append(_p("Decision-Driving Strategic Observations", "h2"))
    for obs in brief.observations[:3]:
        story.append(_card(
            obs.title,
            f"{obs.detail}  <i>[Grounding: {obs.supporting_rfp_fact}]</i>",
            badge_class=obs.epistemic_class,
        ))
        story.append(Spacer(1, 2))

    # Immediate Blockers
    story.append(Spacer(1, 2))
    story.append(_p("Immediate Compliance Blockers & Gates", "h2"))
    blocker_items = [_p(f"• <b>GATE:</b> {b}", "bullet") for b in brief.immediate_blockers]
    blocker_table = Table([[blocker_items]], colWidths=[USABLE_WIDTH])
    blocker_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), TAG_AMBER_BG),
        ("LINEBEFORE", (0, 0), (0, -1), 2.5, TAG_AMBER_TXT),
        ("BOX", (0, 0), (-1, -1), 0.4, TAG_AMBER_TXT),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(blocker_table)

    # =========================================================================
    # PAGE 2: WHAT THE BUYER IS ACTUALLY BUYING
    # =========================================================================
    story.append(PageBreak())
    story.append(_p("SECTION 1", "section_num"))
    story.append(_p("What the Buyer Is Actually Buying", "section_h1"))
    story.append(_p("A substantive breakdown of actual services, deliverables, methodology expectations, and intended beneficiaries beyond administrative titles.", "note"))
    story.append(Spacer(1, 4))

    story.append(_p("Target Audience & Ecosystem Beneficiaries", "h2"))
    story.append(_p(brief.target_beneficiaries, "body"))
    story.append(Spacer(1, 3))

    story.append(_p("Core Services & Deliverables", "h2"))
    for s in brief.services_deliverables:
        story.append(_p(f"• <b>Deliverable:</b> {s}", "bullet"))
    story.append(Spacer(1, 3))

    story.append(_p("Delivery Model & Operational Expectations", "h2"))
    story.append(_table(
        ["Operational Dimension", "Buyer Requirement / Expectation"],
        [
            ["Delivery Model", brief.delivery_model],
            ["Expected Outcomes", brief.expected_outcomes],
            ["Staffing Structure", "Named senior lead instructor + designated secondary backup mentors with verified CVs."],
            ["Availability", "Immediate availability upon contract award; zero lead-time hiring permitted."],
        ],
        [1.75 * inch, USABLE_WIDTH - 1.75 * inch],
    ))
    story.append(Spacer(1, 4))

    story.append(_p("Methodology & Curriculum Framework Expectations", "h2"))
    for m in brief.methodology_expectations:
        story.append(_p(f"• {m}", "bullet"))
    story.append(Spacer(1, 4))

    story.append(_p("Unstated / Ambiguous Scope Matters [UNKNOWN]", "h2"))
    for u in brief.unstated_scope_matters:
        story.append(_p(f"• <i>{u}</i>", "bullet"))

    # =========================================================================
    # PAGE 3: BUYER INTELLIGENCE & STRATEGIC CONTEXT
    # =========================================================================
    story.append(PageBreak())
    story.append(_p("SECTION 2", "section_num"))
    story.append(_p("Buyer Intelligence & Strategic Context", "section_h1"))
    story.append(_p(f"Verified external intelligence grounded exclusively in official buyer domains ({brief.verified_buyer_domain or 'yorku.ca'}) under source-authority-policy/3.", "note"))
    story.append(Spacer(1, 4))

    story.append(_p("Verified Institutional Mandate & Policy Signals", "h2"))
    mandate_rows = [
        [s["title"], f"{s['detail']}<br/><font color='#64748B'><i>Source: {s['source_title']} ({s['source_url']})</i></font>"]
        for s in brief.buyer_mandate_signals
    ]
    story.append(_table(
        ["Institutional Policy / Mandate", "Verified Fact & Official Source Provenance"],
        mandate_rows,
        [2.1 * inch, USABLE_WIDTH - 2.1 * inch],
    ))
    story.append(Spacer(1, 4))

    story.append(_p("Strategic Program Context & Ecosystem Initiatives", "h2"))
    strat_rows = [
        [s["title"], f"{s['detail']}<br/><font color='#64748B'><i>Source: {s['source_title']} ({s['source_url']})</i></font>"]
        for s in brief.buyer_strategic_context
    ]
    story.append(_table(
        ["Program Initiative", "Verified External Context & Strategic Alignment"],
        strat_rows,
        [2.1 * inch, USABLE_WIDTH - 2.1 * inch],
    ))
    story.append(Spacer(1, 4))

    story.append(_p("Bid Intelligence Interpretations: Why This External Context Matters", "h2"))
    for bi in brief.buyer_intelligence_interpretations:
        story.append(_card(
            bi.title,
            f"{bi.detail}  <i>[Evidence Grounding: {bi.supporting_rfp_fact}]</i>",
            badge_class=bi.epistemic_class,
        ))
        story.append(Spacer(1, 2))

    # =========================================================================
    # PAGE 4: TECHNICAL CAPABILITY REQUIREMENTS (PART 1)
    # =========================================================================
    story.append(PageBreak())
    story.append(_p("SECTION 3 (PART 1 OF 2)", "section_num"))
    story.append(_p("Technical Capability Requirements", "section_h1"))
    story.append(_p("Core operational profile and practitioner capability requirements from RFP specifications.", "note"))
    story.append(Spacer(1, 4))

    tech_table_rows_1 = []
    for tc in brief.technical_capabilities[:7]:
        req_cell = _p(f"<b>{tc.capability}</b><br/><font color='#64748B'>{tc.source}</font>", "table_cell_bold")
        detail_cell = _p(f"{tc.what_buyer_requires}<br/><b>Proof needed:</b> {tc.proof_needed}", "table_cell")
        why_cell = _p(tc.why_it_matters, "table_cell")
        tech_table_rows_1.append([req_cell, detail_cell, why_cell])

    story.append(_table(
        ["Capability & RFP Source", "What Buyer Requires & Proof Needed", "Why It Matters (Scoring Impact)"],
        tech_table_rows_1,
        [1.85 * inch, 3.35 * inch, USABLE_WIDTH - 5.2 * inch],
    ))

    # =========================================================================
    # PAGE 5: TECHNICAL CAPABILITY REQUIREMENTS (PART 2)
    # =========================================================================
    story.append(PageBreak())
    story.append(_p("SECTION 3 (PART 2 OF 2)", "section_num"))
    story.append(_p("Technical Capability Requirements (Cont.)", "section_h1"))
    story.append(_p("Methodology, pre-existing curriculum, reference verifications, and public sector delivery requirements.", "note"))
    story.append(Spacer(1, 4))

    tech_table_rows_2 = []
    for tc in brief.technical_capabilities[7:]:
        req_cell = _p(f"<b>{tc.capability}</b><br/><font color='#64748B'>{tc.source}</font>", "table_cell_bold")
        detail_cell = _p(f"{tc.what_buyer_requires}<br/><b>Proof needed:</b> {tc.proof_needed}", "table_cell")
        why_cell = _p(tc.why_it_matters, "table_cell")
        tech_table_rows_2.append([req_cell, detail_cell, why_cell])

    story.append(_table(
        ["Capability & RFP Source", "What Buyer Requires & Proof Needed", "Why It Matters (Scoring Impact)"],
        tech_table_rows_2,
        [1.85 * inch, 3.35 * inch, USABLE_WIDTH - 5.2 * inch],
    ))
    story.append(Spacer(1, 6))

    # Practitioner Profile Takeaway Card
    story.append(_card(
        "Provider Profile Synthesis & Evaluation Focus",
        "The 13 technical requirements demonstrate that York University is seeking an established commercial B2B sales practitioner with pre-existing curriculum assets and demonstrable AI fluency. Theoretical courseware and academic lecture formats will be heavily penalized under the 45-point Methodology criterion. Bidders must present named practitioners with attached resumes and verified Canadian venture references.",
        badge_class=EpistemicClass.BID_INTELLIGENCE_INTERPRETATION.value,
    ))

    # =========================================================================
    # PAGE 6: HOW THE BID WILL BE EVALUATED
    # =========================================================================
    story.append(PageBreak())
    story.append(_p("SECTION 4", "section_num"))
    story.append(_p("How the Proposal Will Be Evaluated", "section_h1"))
    story.append(_p("Mathematical scoring breakdown and evaluation stage rules extracted from Section 8.0 Best Value Analysis.", "note"))
    story.append(Spacer(1, 4))

    # Scoring Summary Box
    summary_html = (
        f"<b>TOTAL WRITTEN PROPOSAL SCORE: 100.0 POINTS</b> (100% of Written Evaluation)<br/>"
        f"• <b>Technical Evaluation: 80.0 Points (80.0%)</b> — Methodology: <b>45.0 pts (56.3% of tech)</b> | Qualifications & Experience: <b>35.0 pts (43.7% of tech)</b><br/>"
        f"• <b>Financial Evaluation: 20.0 Points (20.0%)</b> — Price Schedule total bid and hourly blended consulting rate<br/>"
        f"• <b>Short List Presentation (Part 4, Conditional): 20.0 Additional Points</b> — Invoked at York's sole option for top-scoring proponents."
    )
    story.append(Table([[
        _p(summary_html, "callout")
    ]], colWidths=[USABLE_WIDTH], style=[
        ("BACKGROUND", (0, 0), (-1, -1), BAND),
        ("BOX", (0, 0), (-1, -1), 0.5, BORDER_CARD),
        ("LINEBEFORE", (0, 0), (0, -1), 3, NIGHT),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(Spacer(1, 4))

    story.append(_p("Evaluation Criteria & Subcriteria Breakdown", "h2"))
    criteria_rows = []
    for c in brief.evaluation_criteria_breakdown:
        criteria_rows.append([
            c["name"],
            c["weight"],
            c["details"],
        ])
    story.append(_table(
        ["Evaluation Category / Stage", "Points & Weight Allocation", "Subcriteria & Response Focus"],
        criteria_rows,
        [2.0 * inch, 1.9 * inch, USABLE_WIDTH - 3.9 * inch],
    ))
    story.append(Spacer(1, 5))

    story.append(_p("Evaluation Rules & Threshold Disclosures", "h2"))
    story.append(_table(
        ["Evaluation Rule", "Stated RFP Provision / Fact"],
        [
            ["Minimum Passing Threshold", "<b>NONE STATED IN RFP:</b> York did not specify an explicit minimum passing threshold (e.g. 70% or 75%) to qualify for financial evaluation. Full 100-point composite scoring applies."],
            ["Short List Presentation Stage", "<b>CONDITIONAL (PART 4):</b> York reserves the right to invite only the highest-ranked proponents to presentations (worth an additional 20 points). Written proposal ranking is decisive."],
            ["Tie-Break Mechanism", "<b>TECHNICAL PRIORITY:</b> If two or more proposals achieve identical total scores, the proposal with the highest technical score will be ranked first."],
        ],
        [1.85 * inch, USABLE_WIDTH - 1.85 * inch],
    ))

    # =========================================================================
    # PAGE 7: WHAT THE BIDDER MUST PROVE
    # =========================================================================
    story.append(PageBreak())
    story.append(_p("SECTION 5", "section_num"))
    story.append(_p("What the Bidder Must Prove", "section_h1"))
    story.append(_p("Strict separation between mandatory buyer-required proof items (RFP Fact) and recommended proof strategies.", "note"))
    story.append(Spacer(1, 4))

    story.append(_p("Mandatory Buyer-Required Evidence Items [RFP FACT]", "h2"))
    mand_rows = []
    for pi in brief.proof_items:
        if pi.nature == "mandatory_requirement":
            mand_rows.append([
                _p(f"<b>{pi.title}</b>", "table_cell_bold"),
                _p(pi.detail, "table_cell"),
                _p(pi.source, "table_cell"),
                _badge(pi.epistemic_class),
            ])
    story.append(_table(
        ["Mandatory Evidence Item", "Exact RFP Specification", "RFP Section", "Epistemic Status"],
        mand_rows,
        [1.65 * inch, 3.4 * inch, 1.1 * inch, USABLE_WIDTH - 6.15 * inch],
    ))
    story.append(Spacer(1, 5))

    story.append(_p("Recommended Proof Strategy Items [BID STRATEGY / PROOF RECOMMENDATION]", "h2"))
    rec_rows = []
    for pi in brief.proof_items:
        if pi.nature == "recommendation":
            rec_rows.append([
                _p(f"<b>{pi.title}</b>", "table_cell_bold"),
                _p(pi.detail, "table_cell"),
                _p(pi.source, "table_cell"),
                _badge(pi.epistemic_class),
            ])
    story.append(_table(
        ["Strategic Exhibit Recommendation", "Proposal Exhibit Focus & Evidence Value", "Advisory Basis", "Epistemic Status"],
        rec_rows,
        [1.65 * inch, 3.4 * inch, 1.1 * inch, USABLE_WIDTH - 6.15 * inch],
    ))

    # =========================================================================
    # PAGE 8: COMMERCIAL, RISKS, PRIORITIES & DECISION SIGN-OFF
    # =========================================================================
    story.append(PageBreak())
    story.append(_p("SECTION 6", "section_num"))
    story.append(_p("Commercial Watch-Outs, Priorities & Decision Sign-Off", "section_h1"))
    story.append(_p("Material commercial constraints, compliance gates, actionable priorities, and executive decision sign-off.", "note"))
    story.append(Spacer(1, 3))

    # Commercial Watch-outs Table
    story.append(_p("Material Commercial & Contractual Terms", "h2"))
    story.append(_table(
        ["Commercial Clause / Topic", "Material Buyer Term & Contractual Impact"],
        [[topic, term] for topic, term in brief.commercial_clauses[:4]],
        [1.85 * inch, USABLE_WIDTH - 1.85 * inch],
    ))
    story.append(Spacer(1, 3))

    # Compliance Blockers
    gate_bullets = [_p(f"• <b>GATE:</b> {g}", "bullet") for g in brief.disqualification_gates[:3]]
    story.append(Table([[gate_bullets]], colWidths=[USABLE_WIDTH], style=[
        ("BACKGROUND", (0, 0), (-1, -1), TAG_AMBER_BG),
        ("BOX", (0, 0), (-1, -1), 0.5, TAG_AMBER_TXT),
        ("LINEBEFORE", (0, 0), (0, -1), 2.5, TAG_AMBER_TXT),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(Spacer(1, 3))

    # Top Priorities
    story.append(_p("Top Bid-Team Action Priorities Before Writing", "h2"))
    priority_rows = []
    for idx, prio in enumerate(brief.top_priorities[:5], 1):
        priority_rows.append([
            f"Priority {idx}",
            prio.title,
            prio.action,
        ])
    story.append(_table(
        ["#", "Action Priority", "What the Bid Team Must Execute"],
        priority_rows,
        [0.85 * inch, 2.1 * inch, USABLE_WIDTH - 2.95 * inch],
        header_bg=DARK_BLUE,
    ))
    story.append(Spacer(1, 3))

    # Clarifications Box
    clarif_bullets = [_p(f"• <b>INQUIRY:</b> {q}", "bullet") for q in brief.clarification_questions[:2]]
    story.append(_p("Recommended Pre-Bid Clarification Inquiries (Submit via Bonfire)", "h2"))
    story.append(Table([[clarif_bullets]], colWidths=[USABLE_WIDTH], style=[
        ("BACKGROUND", (0, 0), (-1, -1), BAND),
        ("BOX", (0, 0), (-1, -1), 0.5, BORDER_CARD),
        ("LINEBEFORE", (0, 0), (0, -1), 2.5, GOLD),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(Spacer(1, 4))

    # Executive Decision Sign-off Box
    signoff_html = (
        "<b>EXECUTIVE BID / NO-BID DECISION RECORD</b><br/>"
        "Opportunity: <b>" + brief.opportunity + "</b> (" + brief.solicitation + ") &nbsp;|&nbsp; Buyer: <b>" + brief.buyer + "</b><br/>"
        "[ &nbsp; ] &nbsp; <b>BID:</b> Proceed with full proposal preparation. Lead Instructor assigned.<br/>"
        "[ &nbsp; ] &nbsp; <b>NO-BID:</b> Archive opportunity.<br/>"
        "Decision Authority: ___________________________________ &nbsp;&nbsp;&nbsp;&nbsp; Date: ________________________"
    )
    story.append(Table([[
        _p(signoff_html, "body")
    ]], colWidths=[USABLE_WIDTH], style=[
        ("BACKGROUND", (0, 0), (-1, -1), PAPER),
        ("BOX", (0, 0), (-1, -1), 0.8, NIGHT),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))

    doc.build(story)
    return output_path


def render_decision_brief_bytes(brief: DecisionBrief) -> bytes:
    """Render DecisionBrief to PDF bytes in memory."""
    with tempfile.TemporaryDirectory() as directory:
        path = render_decision_brief_pdf(brief, Path(directory) / "decision_brief.pdf")
        return path.read_bytes()
