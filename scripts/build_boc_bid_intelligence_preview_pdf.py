"""
Builds BANK_OF_CANADA_RFP_2026_026_BID_INTELLIGENCE_PREVIEW.pdf -- a
client-facing, product-feedback prototype report. Pure rendering logic;
all report content lives in boc_bid_intelligence_preview_content.py.

No pipeline/engineering terminology appears in the rendered output.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame, NextPageTemplate, PageBreak,
    Paragraph, Spacer, Table, TableStyle, KeepTogether, HRFlowable, Image,
)
from reportlab.lib.styles import ParagraphStyle

import scripts.boc_bid_intelligence_preview_content as _DEEP_CONTENT

# ---------------------------------------------------------------------------
# Brand tokens (Enable My Growth identity, adapted for a light, print-style
# consulting report -- the dark palette is used only on the cover).
# ---------------------------------------------------------------------------
NIGHT = HexColor("#0A0A0F")
INK = HexColor("#1C1B1F")
GOLD = HexColor("#B5924F")
MUTED = HexColor("#6B675F")
RULE = HexColor("#D9D5CC")
IVORY = HexColor("#EDEAE3")
PAPER = HexColor("#FFFFFF")
BAND = HexColor("#F6F4EF")

ASSETS = ROOT / "assets"
FONTS = ASSETS / "fonts"
OUT_PDF = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "BANK_OF_CANADA_RFP_2026_026_BID_INTELLIGENCE_PREVIEW.pdf"

pdfmetrics.registerFont(TTFont("Display", str(FONTS / "CormorantGaramond-SemiBold.otf")))
pdfmetrics.registerFont(TTFont("DisplayReg", str(FONTS / "CormorantGaramond-Regular.otf")))
pdfmetrics.registerFont(TTFont("Body", str(FONTS / "Inter-Regular.otf")))
pdfmetrics.registerFont(TTFont("BodyMed", str(FONTS / "Inter-Medium.otf")))

PAGE_W, PAGE_H = LETTER
MARGIN = 0.85 * inch

styles = {
    "cover_kicker": ParagraphStyle("cover_kicker", fontName="BodyMed", fontSize=10.5, leading=14,
                                   textColor=GOLD, alignment=TA_CENTER, tracking=2),
    "cover_title": ParagraphStyle("cover_title", fontName="Display", fontSize=40, leading=46,
                                  textColor=IVORY, alignment=TA_CENTER, spaceBefore=14, spaceAfter=10),
    "cover_sub1": ParagraphStyle("cover_sub1", fontName="DisplayReg", fontSize=19, leading=24,
                                 textColor=IVORY, alignment=TA_CENTER, spaceAfter=4),
    "cover_sub2": ParagraphStyle("cover_sub2", fontName="Body", fontSize=12, leading=17,
                                 textColor=HexColor("#C7C3B8"), alignment=TA_CENTER, spaceAfter=6),
    "cover_footer": ParagraphStyle("cover_footer", fontName="Body", fontSize=9, leading=12,
                                   textColor=MUTED, alignment=TA_CENTER),
    "section_kicker": ParagraphStyle("section_kicker", fontName="BodyMed", fontSize=9, leading=11,
                                     textColor=GOLD, alignment=TA_LEFT, spaceAfter=2),
    "h1": ParagraphStyle("h1", fontName="Display", fontSize=21, leading=25, textColor=INK,
                         alignment=TA_LEFT, spaceAfter=10),
    "h2": ParagraphStyle("h2", fontName="Display", fontSize=13.5, leading=17, textColor=INK,
                         alignment=TA_LEFT, spaceBefore=12, spaceAfter=5),
    "body": ParagraphStyle("body", fontName="Body", fontSize=9.6, leading=14.2, textColor=INK,
                           alignment=TA_LEFT, spaceAfter=6),
    "body_tight": ParagraphStyle("body_tight", fontName="Body", fontSize=9.3, leading=13, textColor=INK,
                                 alignment=TA_LEFT, spaceAfter=3),
    "note": ParagraphStyle("note", fontName="Body", fontSize=8.6, leading=12.4, textColor=MUTED,
                           alignment=TA_LEFT, spaceAfter=6, borderPadding=0),
    "card_label": ParagraphStyle("card_label", fontName="BodyMed", fontSize=8, leading=10,
                                 textColor=GOLD),
    "card_value": ParagraphStyle("card_value", fontName="Body", fontSize=9.6, leading=13,
                                 textColor=INK),
    "table_head": ParagraphStyle("table_head", fontName="BodyMed", fontSize=8.4, leading=11,
                                 textColor=PAPER),
    "table_cell": ParagraphStyle("table_cell", fontName="Body", fontSize=8.8, leading=12.5,
                                 textColor=INK),
    "table_cell_b": ParagraphStyle("table_cell_b", fontName="BodyMed", fontSize=8.8, leading=12.5,
                                   textColor=INK),
    "bullet": ParagraphStyle("bullet", fontName="Body", fontSize=9.4, leading=13.6, textColor=INK,
                             spaceAfter=5, leftIndent=12, bulletIndent=0),
    "amb_issue": ParagraphStyle("amb_issue", fontName="BodyMed", fontSize=10, leading=13.5,
                                textColor=INK, spaceAfter=2),
    "amb_label": ParagraphStyle("amb_label", fontName="BodyMed", fontSize=7.8, leading=10,
                                textColor=GOLD, spaceBefore=4, spaceAfter=1),
    "amb_body": ParagraphStyle("amb_body", fontName="Body", fontSize=9, leading=12.8, textColor=INK,
                               spaceAfter=2),
    "attn_num": ParagraphStyle("attn_num", fontName="Display", fontSize=15, leading=15,
                               textColor=GOLD),
}


def hr(color=RULE, thickness=0.6, space_before=4, space_after=8):
    return HRFlowable(width="100%", thickness=thickness, color=color,
                       spaceBefore=space_before, spaceAfter=space_after)


def section_header(kicker, title, story):
    story.append(Paragraph(kicker.upper(), styles["section_kicker"]))
    story.append(Paragraph(title, styles["h1"]))
    story.append(hr(GOLD, 1.1, 0, 10))


def on_cover(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(NIGHT)
    canvas.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    canvas.setStrokeColor(HexColor("#2A2A33"))
    canvas.setLineWidth(0.8)
    canvas.line(MARGIN, PAGE_H - 1.55 * inch, PAGE_W - MARGIN, PAGE_H - 1.55 * inch)
    canvas.line(MARGIN, 1.35 * inch, PAGE_W - MARGIN, 1.35 * inch)
    canvas.setFillColor(GOLD)
    canvas.setFont("BodyMed", 8)
    canvas.drawCentredString(PAGE_W / 2, 1.02 * inch, "AN ENABLE MY GROWTH APPLICATION · BID INTELLIGENCE")
    canvas.restoreState()


def on_body(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(PAPER)
    canvas.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    # header
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.6)
    canvas.line(MARGIN, PAGE_H - 0.62 * inch, PAGE_W - MARGIN, PAGE_H - 0.62 * inch)
    canvas.setFont("BodyMed", 7.6)
    canvas.setFillColor(MUTED)
    canvas.drawString(MARGIN, PAGE_H - 0.52 * inch, "BID INTELLIGENCE PREVIEW")
    canvas.setFont("Body", 7.6)
    canvas.drawRightString(PAGE_W - MARGIN, PAGE_H - 0.52 * inch,
                            getattr(doc, "_header_text", "") or "")
    # footer
    canvas.setLineWidth(0.6)
    canvas.setStrokeColor(RULE)
    canvas.line(MARGIN, 0.62 * inch, PAGE_W - MARGIN, 0.62 * inch)
    canvas.setFont("Body", 7.6)
    canvas.setFillColor(MUTED)
    canvas.drawString(MARGIN, 0.44 * inch, "Prototype analysis for product-feedback purposes")
    canvas.setFont("BodyMed", 8)
    canvas.setFillColor(GOLD)
    canvas.drawRightString(PAGE_W - MARGIN, 0.44 * inch, str(canvas.getPageNumber() - 1))
    canvas.restoreState()


def fact_card_table(pairs, col_widths=(2.0 * inch, 4.4 * inch)):
    rows = []
    for label, value in pairs:
        rows.append([Paragraph(label.upper(), styles["card_label"]),
                     Paragraph(value, styles["card_value"])])
    t = Table(rows, colWidths=list(col_widths))
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LINEBELOW", (0, 0), (-1, -2), 0.5, RULE),
        ("LEFTPADDING", (0, 0), (0, -1), 0),
    ]))
    return t


def styled_table(header, rows, col_widths, header_bg=NIGHT, pad=5.5):
    data = [[Paragraph(h, styles["table_head"]) for h in header]]
    for r in rows:
        data.append([c if isinstance(c, Paragraph) else Paragraph(str(c), styles["table_cell"])
                    for c in r])
    t = Table(data, colWidths=col_widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), header_bg),
        ("TOPPADDING", (0, 0), (-1, -1), pad),
        ("BOTTOMPADDING", (0, 0), (-1, -1), pad),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 1), (-1, -1), 0.5, RULE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [PAPER, BAND]),
    ]
    t.setStyle(TableStyle(style))
    return t


def build(content=None, out_path=None):
    C = content if content is not None else _DEEP_CONTENT
    header_text = getattr(C, "HEADER_TEXT", None) or getattr(C, "SUBTITLE_1", "") or ""
    pdf_title = f"{getattr(C, 'TITLE', 'Bid Intelligence Preview')} — {header_text}" if header_text \
        else getattr(C, "TITLE", "Bid Intelligence Preview")
    doc = BaseDocTemplate(str(out_path or OUT_PDF), pagesize=LETTER,
                          leftMargin=MARGIN, rightMargin=MARGIN,
                          topMargin=MARGIN, bottomMargin=MARGIN,
                          title=pdf_title)
    doc._header_text = header_text
    cover_frame = Frame(0, 0, PAGE_W, PAGE_H, id="cover")
    body_frame = Frame(MARGIN, MARGIN, PAGE_W - 2 * MARGIN, PAGE_H - 2 * MARGIN - 0.15 * inch, id="body")
    doc.addPageTemplates([
        PageTemplate(id="Cover", frames=[cover_frame], onPage=on_cover),
        PageTemplate(id="Body", frames=[body_frame], onPage=on_body),
    ])

    story = []

    # ---------------- COVER ----------------
    story.append(Spacer(1, 2.55 * inch))
    story.append(Paragraph("BID INTELLIGENCE PREVIEW", styles["cover_kicker"]))
    story.append(Spacer(1, 10))
    story.append(Paragraph(C.SUBTITLE_1, styles["cover_title"]))
    story.append(Paragraph(C.SUBTITLE_2, styles["cover_sub1"]))
    story.append(Spacer(1, 14))
    story.append(Paragraph("Prepared as a decision-support preview for bid-team review",
                           styles["cover_sub2"]))
    story.append(NextPageTemplate("Body"))
    story.append(PageBreak())

    sec_num = 0

    def emit_section(title: str):
        nonlocal sec_num
        sec_num += 1
        section_header(f"Section {sec_num}", title, story)

    # ---------------- EXECUTIVE OPPORTUNITY SNAPSHOT ----------------
    emit_section("Executive Opportunity Snapshot")
    story.append(fact_card_table(C.SNAPSHOT_FACTS))
    story.append(Spacer(1, 14))
    cat_rows = []
    for cat, name, meta in C.SNAPSHOT_CATEGORY_CARDS:
        cat_rows.append([
            Paragraph(cat.upper(), styles["card_label"]),
            Paragraph(f"<b>{name}</b><br/><font color='#6B675F' size='8'>{meta}</font>", styles["card_value"]),
        ])
    if cat_rows:
        # Phase 5: a corpus with no discovered category/lot structure (a
        # single flat evaluation scope) has an empty SNAPSHOT_CATEGORY_CARDS
        # -- an empty reportlab Table would raise, so this whole block is
        # genuinely omitted rather than shown with nothing in it.
        t = Table(cat_rows, colWidths=[1.1 * inch, 5.3 * inch])
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("BACKGROUND", (0, 0), (-1, -1), BAND),
            ("LINEBELOW", (0, 0), (-1, -2), 0.5, RULE),
            ("LEFTPADDING", (0, 0), (0, -1), 10),
        ]))
        story.append(t)
        story.append(Spacer(1, 10))
    story.append(Paragraph(C.SNAPSHOT_NOTE, styles["note"]))
    story.append(PageBreak())

    # ---------------- 2. BUYER INTELLIGENCE ----------------
    # Phase 5: this section (and its underlying VERIFIED_BUYER_FACTS /
    # RELEVANT_BUYER_SIGNALS / BID_TEAM_PANEL_ITEMS tables, none of which
    # tolerate an empty reportlab Table) only exists as real content for one
    # buyer today -- for any other buyer the adapter sets
    # BUYER_INTEL_AVAILABLE=False and supplies none of these fields, so the
    # ---------------- BUYER INTELLIGENCE ----------------
    # Phase 5: this section (and its underlying VERIFIED_BUYER_FACTS /
    # RELEVANT_BUYER_SIGNALS / BID_TEAM_PANEL_ITEMS tables, none of which
    # tolerate an empty reportlab Table) only exists as real content for one
    # buyer today -- for any other buyer the adapter sets
    # BUYER_INTEL_AVAILABLE=False and supplies none of these fields, so the
    # whole section is skipped rather than rendered empty or with another
    # buyer's real content.
    if getattr(C, "BUYER_INTEL_AVAILABLE", True):
        emit_section("Buyer Intelligence")
        story.append(Paragraph(C.BUYER_INTEL_INTRO, styles["body_tight"]))
        story.append(Spacer(1, 3))

        story.append(Paragraph("Buyer at a Glance", styles["h2"]))
        rows = [[Paragraph(f"<b>{label}</b>", styles["table_cell_b"]),
                 Paragraph(detail, styles["table_cell"]),
                 Paragraph(f"<font color='#6B675F' size='7.4'>{src}</font>", styles["table_cell"])]
                for label, detail, src in C.VERIFIED_BUYER_FACTS]
        story.append(styled_table(["Topic", "Verified Fact", "Source"], rows,
                                  [1.15 * inch, 3.85 * inch, 1.5 * inch], pad=2.8))
        story.append(Spacer(1, 2))
        story.append(Paragraph(C.BUYER_FACTS_NOTE, styles["note"]))
        story.append(Spacer(1, 4))

        story.append(Paragraph("Relevant Public Signals", styles["h2"]))
        rows = [[Paragraph(f"<b>{label}</b>", styles["table_cell_b"]), Paragraph(detail, styles["table_cell"])]
                for label, detail in C.RELEVANT_BUYER_SIGNALS]
        story.append(styled_table(
            ["Signal", getattr(C, "BUYER_SIGNALS_COL_HEADER", "What the Buyer Has Publicly Stated")],
            rows, [1.85 * inch, 4.65 * inch], header_bg=GOLD, pad=2.8))
        story.append(Spacer(1, 4))

        tight_body = ParagraphStyle("bi_body", fontName="Body", fontSize=8.3, leading=10.6, textColor=INK,
                                    spaceAfter=1.5)
        bi_lbl_style = ParagraphStyle("bi_lbl", fontName="BodyMed", fontSize=8.0, leading=9.8,
                                      textColor=GOLD, spaceAfter=1)
        # The heading + disclaimer are kept together with at least the
        # FIRST bid-relevance item (a real fix for a real widow seen live:
        # the heading and disclaimer alone can otherwise render at the
        # bottom of one page while every item flows to the next). Later
        # items keep their own independent KeepTogether so they can still
        # break normally between each other.
        header_block = [
            Paragraph("What This May Mean for the Bid", styles["h2"]),
            Paragraph(
                getattr(C, "BUYER_INTEL_DISCLAIMER",
                        "<i>Interpretation only — not a statement of the Bank's evaluation intent.</i>"),
                styles["note"]),
        ]
        if C.BID_RELEVANCE_ITEMS:
            first_label, first_text = C.BID_RELEVANCE_ITEMS[0]
            header_block += [Paragraph(first_label, bi_lbl_style), Paragraph(first_text, tight_body)]
            story.append(KeepTogether(header_block))
            for label, text in C.BID_RELEVANCE_ITEMS[1:]:
                story.append(KeepTogether([Paragraph(label, bi_lbl_style), Paragraph(text, tight_body)]))
        else:
            story.append(KeepTogether(header_block))
        story.append(Spacer(1, 3))

        if getattr(C, "BID_TEAM_PANEL_ITEMS", None):
            panel_rows = [[Paragraph(f"{i}.", ParagraphStyle("pnl_num", fontName="BodyMed", fontSize=8.8,
                                                              leading=12.5, textColor=INK)),
                          Paragraph(item, styles["table_cell"])]
                          for i, item in enumerate(C.BID_TEAM_PANEL_ITEMS, 1)]
            panel_header = Table([[Paragraph(C.BID_TEAM_PANEL_TITLE.upper(), styles["table_head"])]],
                                colWidths=[6.4 * inch])
            panel_header.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), NIGHT),
                                              ("TOPPADDING", (0, 0), (-1, -1), 6),
                                              ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                                              ("LEFTPADDING", (0, 0), (-1, -1), 9)]))
            panel_body = Table(panel_rows, colWidths=[0.42 * inch, 5.98 * inch])
            panel_body.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 3.2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3.2),
                ("LEFTPADDING", (0, 0), (0, -1), 9),
                ("BACKGROUND", (0, 0), (-1, -1), BAND),
            ]))
            panel_wrap = Table([[panel_header], [panel_body]], colWidths=[6.4 * inch])
            panel_wrap.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.9, GOLD),
                                            ("TOPPADDING", (0, 0), (-1, -1), 0),
                                            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                                            ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                            ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
            story.append(panel_wrap)
            story.append(Spacer(1, 3))
        story.append(Paragraph(C.BUYER_INTEL_SOURCES_NOTE, styles["note"]))
        story.append(Spacer(1, 8))

    # ---------------- WHAT IS BEING PROCURED ----------------
    emit_section("What Is Being Procured?")
    story.append(Paragraph(C.PROCURED_INTRO, styles["body"]))
    story.append(Spacer(1, 6))
    for name, tag, desc in C.SERVICE_CATEGORIES:
        story.append(KeepTogether([
            Paragraph(f"<b>{name}</b>  <font color='#B5924F' size='8'>{tag.upper()}</font>", styles["h2"]),
            Paragraph(desc, styles["body_tight"]),
        ]))
    story.append(Spacer(1, 4))
    story.append(hr())
    story.append(Paragraph("How Suppliers Participate", styles["h2"]))
    story.append(Paragraph(C.PROCURED_STRUCTURE, styles["body"]))
    story.append(Paragraph("Call-Off Engagement Model", styles["h2"]))
    story.append(Paragraph(C.PROCURED_MODEL_NOTE, styles["body"]))
    story.append(Spacer(1, 10))

    # ---------------- CRITICAL DATES & BID MECHANICS ----------------
    emit_section("Critical Dates & Bid Mechanics")
    date_rows = [[Paragraph(f"<b>{d}</b>", styles["table_cell_b"]), Paragraph(m, styles["table_cell"])]
                 for d, m in C.KEY_DATES]
    t = Table(date_rows, colWidths=[2.15 * inch, 4.25 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), IVORY),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("LINEBELOW", (0, 0), (-1, -2), 0.5, RULE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (0, 0), (-1, -1), 0.8, GOLD),
    ]))
    story.append(t)
    story.append(Spacer(1, 6))
    if getattr(C, "DATES_NOTE", None):
        story.append(Paragraph(C.DATES_NOTE, styles["note"]))
    if getattr(C, "BID_MECHANICS", None):
        story.append(Paragraph("Submission Mechanics", styles["h2"]))
        for item in C.BID_MECHANICS:
            story.append(Paragraph(f"•&nbsp;&nbsp;{item}", styles["bullet"]))
    story.append(Spacer(1, 10))

    # ---------------- EVALUATION ----------------
    emit_section("Evaluation — How the Bid Will Be Judged")
    if getattr(C, "EVAL_STAGES", None):
        story.append(styled_table(
            ["Stage", "Component", "Basis"],
            C.EVAL_STAGES, [0.85 * inch, 2.55 * inch, 3.0 * inch]))
        story.append(Spacer(1, 10))
    story.append(Paragraph("Mandatory Submission Gates", styles["h2"]))
    for item in C.GATE_EXAMPLES:
        story.append(Paragraph(f"•&nbsp;&nbsp;{item}", styles["bullet"]))
    story.append(Spacer(1, 8))

    story.append(Paragraph("Rated-Criteria Weighting by Category", styles["h2"]))
    eval_min_scores = getattr(C, "EVAL_MINIMUM_SCORES", {}) or {}
    for cat, rows in C.EVAL_WEIGHTS.items():
        story.append(Paragraph(cat, styles["h2"]))
        min_scores = eval_min_scores.get(cat)
        if min_scores:
            # A third "Minimum Score" column only for categories where at
            # least one criterion has a stated per-criterion minimum --
            # rows without one show "N/A" (the source table's own
            # convention for a criterion with no minimum-score gate).
            rows3 = [(label, weight, min_scores.get(label, "N/A")) for label, weight in rows]
            story.append(styled_table(["Criterion", "Weight", "Minimum Score"], rows3,
                                      [3.4 * inch, 1.3 * inch, 1.7 * inch], header_bg=GOLD))
        else:
            story.append(styled_table(["Criterion", "Weight"], rows, [4.6 * inch, 1.8 * inch], header_bg=GOLD))
        story.append(Spacer(1, 8))

    if getattr(C, "TIE_BREAK_RULES", None):
        story.append(Paragraph("Tie-Break Order", styles["h2"]))
        for i, rule in enumerate(C.TIE_BREAK_RULES, 1):
            story.append(Paragraph(f"{i}.&nbsp;&nbsp;{rule}", styles["bullet"]))
        story.append(Spacer(1, 8))

    if getattr(C, "QUALIFICATION_MECHANISMS", None):
        story.append(Paragraph("Reference Checks / Other Qualification Mechanisms", styles["h2"]))
        for item in C.QUALIFICATION_MECHANISMS:
            story.append(Paragraph(f"•&nbsp;&nbsp;{item}", styles["bullet"]))
        story.append(Spacer(1, 8))

    story.append(Paragraph(C.EVAL_WEIGHT_NOTE, styles["note"]))
    story.append(PageBreak())

    # ---------------- RESPONSE REQUIREMENTS ----------------
    emit_section("Response Requirements")
    story.append(Paragraph("Mandatory Submission Gates", styles["h2"]))
    story.append(Paragraph(
        "See Mandatory Submission Gates in the Evaluation section above for the full pass/fail "
        "gate list.", styles["note"]))
    story.append(Spacer(1, 8))

    if getattr(C, "RG_EVIDENCE_MAP", None):
        story.append(Paragraph("Key Evaluated Response / Evidence Requirements", styles["h2"]))
        rg_rows = [[Paragraph(f"<b>{rg} — {crit}</b>", styles["table_cell_b"]),
                    Paragraph(evidence, styles["table_cell"])]
                   for rg, crit, evidence in C.RG_EVIDENCE_MAP]
        story.append(styled_table(["Criterion", "Requested Evidence"], rg_rows,
                                  [2.2 * inch, 4.2 * inch]))
        story.append(Spacer(1, 10))

    if getattr(C, "PRICING_SUBMISSION_RULES", None):
        story.append(Paragraph("Pricing Submission Rules", styles["h2"]))
        for item in C.PRICING_SUBMISSION_RULES:
            story.append(Paragraph(f"•&nbsp;&nbsp;{item}", styles["bullet"]))
        story.append(Spacer(1, 10))

    story.append(Paragraph("Additional Submission Mechanics", styles["h2"]))
    rows = [[Paragraph(f"<b>{a}</b>", styles["table_cell_b"]), Paragraph(n, styles["table_cell"]),
             Paragraph(d, styles["table_cell"])] for a, n, d in C.RESPONSE_CHECKLIST]
    story.append(styled_table(["Item", "Description", "Notes"], rows,
                              [1.1 * inch, 2.55 * inch, 2.75 * inch]))
    story.append(Spacer(1, 10))
    if getattr(C, "RESPONSE_OTHER_REQUIREMENTS", None):
        story.append(Paragraph("Also Required", styles["h2"]))
        for item in C.RESPONSE_OTHER_REQUIREMENTS:
            story.append(Paragraph(f"•&nbsp;&nbsp;{item}", styles["bullet"]))
    story.append(PageBreak())

    # ---------------- COMMERCIAL & CONTRACTUAL ----------------
    emit_section("Commercial & Contractual Considerations")
    rows = [[Paragraph(f"<b>{label}</b>", styles["table_cell_b"]), Paragraph(text, styles["table_cell"])]
            for label, text in C.COMMERCIAL_POINTS]
    story.append(styled_table(["Topic", "What to Know"], rows, [1.55 * inch, 4.85 * inch]))
    story.append(PageBreak())

    # ---------------- IMPORTANT AMBIGUITIES ----------------
    if getattr(C, "AMBIGUITIES", None):
        emit_section("Important Ambiguities / Items to Clarify")
        for i, amb in enumerate(C.AMBIGUITIES, 1):
            block = [
                Paragraph(f"Ambiguity {i}", styles["amb_label"]),
                Paragraph(amb["issue"], styles["amb_issue"]),
                Paragraph("WHY IT MATTERS", styles["amb_label"]),
                Paragraph(amb["why"], styles["amb_body"]),
                Paragraph("SOURCE", styles["amb_label"]),
                Paragraph(amb["source"], styles["amb_body"]),
                Paragraph("SUGGESTED CLARIFICATION QUESTION", styles["amb_label"]),
                Paragraph(f"“{amb['question']}”", styles["amb_body"]),
                Spacer(1, 4), hr(RULE, 0.6, 2, 10),
            ]
            story.append(KeepTogether(block))
        story.append(Spacer(1, 10))

    # ---------------- BID TEAM ATTENTION POINTS ----------------
    emit_section("Bid Team Attention Points")
    story.append(Paragraph("<i>Things I would resolve first if preparing this bid</i>",
                           ParagraphStyle("sub", fontName="DisplayReg", fontSize=13, textColor=GOLD,
                                          spaceAfter=10)))
    for i, item in enumerate(C.ATTENTION_POINTS, 1):
        row = Table([[Paragraph(str(i), styles["attn_num"]), Paragraph(item, styles["body"])]],
                    colWidths=[0.35 * inch, 5.65 * inch])
        row.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                 ("TOPPADDING", (0, 0), (-1, -1), 4),
                                 ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
        story.append(row)
    story.append(PageBreak())

    # ---------------- SOURCE MAP ----------------
    emit_section("Source Map / Reference Appendix")
    story.append(Paragraph("Procurement Documents Used", styles["h2"]))
    rows = [[Paragraph(f"<b>{a}</b>", styles["table_cell_b"]), Paragraph(b, styles["table_cell"])]
            for a, b in C.SOURCE_DOCUMENTS]
    story.append(styled_table(["Document", "Content"], rows, [2.5 * inch, 3.9 * inch], pad=2.2))
    story.append(Spacer(1, 3))

    if getattr(C, "EXTERNAL_BUYER_SOURCES", None):
        story.append(Paragraph("External Buyer Intelligence Sources", styles["h2"]))
        ext_rows = [[Paragraph(f"<b>{a}</b>", styles["table_cell_b"]), Paragraph(b, styles["table_cell"])]
                    for a, b in C.EXTERNAL_BUYER_SOURCES]
        story.append(styled_table(["External Source / Publication", "Reference & Provenance"],
                                  ext_rows, [2.5 * inch, 3.9 * inch], pad=2.2))
        story.append(Spacer(1, 3))
    story.append(Paragraph("Selected Source References for Key Findings", styles["h2"]))
    rows = [[Paragraph(f"<b>{a}</b>", styles["table_cell_b"]), Paragraph(b, styles["table_cell"])]
            for a, b in C.SOURCE_REF_TABLE]
    story.append(styled_table(["Finding", "Reference"], rows, [2.5 * inch, 3.9 * inch], pad=2.2))
    story.append(Spacer(1, 3))
    story.append(hr(space_before=1, space_after=3))
    val_note_style = ParagraphStyle("val_note", parent=styles["note"], fontSize=7.2, leading=8.8)
    story.append(Paragraph(C.VALIDATION_FOOTER_NOTE, val_note_style))

    doc.build(story)
    return out_path or OUT_PDF


if __name__ == "__main__":
    path = build()
    print("PDF written to:", path)
