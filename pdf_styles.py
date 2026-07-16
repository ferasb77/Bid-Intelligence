"""
Shared McKinsey-style PDF design system.
White background, Inter typography, colour used only as signal.
"""
import os
from reportlab.lib.colors import HexColor, white, black
from reportlab.lib.units import mm
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ── Font registration ─────────────────────────────────────────────────────────
FONT_DIR = os.path.join(os.path.dirname(__file__), "..", "fonts")

def register_fonts():
    fonts = {
        "Inter":    "Inter-Regular.ttf",
        "Inter-M":  "Inter-Medium.ttf",
        "Inter-SB": "Inter-SemiBold.ttf",
        "Inter-B":  "Inter-Bold.ttf",
    }
    for name, fname in fonts.items():
        path = os.path.join(FONT_DIR, fname)
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont(name, path))
            except Exception:
                pass

register_fonts()

def _font(weight="regular"):
    """Return registered Inter variant or Helvetica fallback."""
    mapping = {
        "regular":  ("Inter",    "Helvetica"),
        "medium":   ("Inter-M",  "Helvetica"),
        "semibold": ("Inter-SB", "Helvetica-Bold"),
        "bold":     ("Inter-B",  "Helvetica-Bold"),
    }
    preferred, fallback = mapping.get(weight, ("Inter", "Helvetica"))
    try:
        pdfmetrics.getFont(preferred)
        return preferred
    except Exception:
        return fallback

# ── Colour palette (McKinsey-adjacent) ───────────────────────────────────────
# Primary: deep navy blue for headers
# Accent: single blue stripe only — no colour fills on data rows
# Signal colours: red/amber/green for status only, never for decoration

C_BLACK     = HexColor("#1A1A1A")   # near-black body text
C_NAVY      = HexColor("#002060")   # McKinsey blue — headlines, header rules
C_BLUE      = HexColor("#1F5C99")   # accent — section bars, column headers
C_BLUE_L    = HexColor("#EBF2FA")   # very light blue tint — alternating rows
C_GREY_1    = HexColor("#595959")   # secondary text
C_GREY_2    = HexColor("#8C8C8C")   # tertiary / labels
C_GREY_3    = HexColor("#D9D9D9")   # borders, rules
C_GREY_4    = HexColor("#F5F5F5")   # lightest row fill
C_WHITE     = HexColor("#FFFFFF")

# Status signal colours
C_RED       = HexColor("#C00000")
C_AMBER     = HexColor("#E26B0A")
C_GREEN     = HexColor("#375623")
C_GREEN_L   = HexColor("#70AD47")
C_PURPLE    = HexColor("#7030A0")
C_BLUE_SIG  = HexColor("#1F5C99")

# Category accent colours (used ONLY for left-border stripe, not fills)
CAT_ACCENT = {
    "Mandatory":       C_RED,
    "Rated":           C_BLUE,
    "Financial":       C_GREEN,
    "Supporting":      C_PURPLE,
    "Core Service":    C_BLUE,
    "Optional Service":C_PURPLE,
    "Call-up Mechanic":HexColor("#7F6000"),
    "Reporting":       C_GREEN,
}

STATUS_COLOUR = {
    "Not Started": C_GREY_2,
    "In Progress": C_BLUE_SIG,
    "Draft":       HexColor("#7F6000"),
    "In Review":   C_PURPLE,
    "Complete":    C_GREEN,
    "Blocked":     C_RED,
    "N/A":         C_GREY_2,
}

# ── Typography helpers ────────────────────────────────────────────────────────
def S(name, size=9, weight="regular", color=None, align=TA_LEFT,
      leading=None, space_before=0, space_after=0):
    return ParagraphStyle(
        name,
        fontName   = _font(weight),
        fontSize   = size,
        leading    = leading or max(size * 1.3, size + 3),
        textColor  = color or C_BLACK,
        alignment  = align,
        spaceBefore= space_before,
        spaceAfter = space_after,
    )

# Pre-built style set
STYLES = {
    # Cover / page headers
    "firm":       S("firm",    7,  "semibold", C_NAVY,   TA_LEFT),
    "doc_type":   S("dtype",   8,  "regular",  C_GREY_1, TA_LEFT),
    "title":      S("title",   20, "bold",     C_NAVY,   TA_LEFT, leading=24),
    "subtitle":   S("sub",     10, "regular",  C_GREY_1, TA_LEFT),
    "meta":       S("meta",    8,  "regular",  C_GREY_2, TA_LEFT),
    # Section
    "section":    S("sec",     9,  "bold",     C_WHITE,  TA_LEFT),
    "col_hdr":    S("colhdr",  7.5,"semibold", C_WHITE,  TA_LEFT),
    # Body
    "cell":       S("cell",    8,  "regular",  C_BLACK,  TA_LEFT),
    "cell_b":     S("cellb",   8,  "semibold", C_BLACK,  TA_LEFT),
    "cell_id":    S("cellid",  8,  "bold",     C_NAVY,   TA_LEFT),
    "cell_sm":    S("cellsm",  7,  "regular",  C_GREY_1, TA_LEFT),
    "cell_ref":   S("cellref", 7,  "regular",  C_BLUE,   TA_LEFT),
    "cell_num":   S("cellnum", 8,  "semibold", C_BLACK,  TA_RIGHT),
    # Scorecard
    "sc_cat":     S("sccat",   7.5,"semibold", C_GREY_1, TA_CENTER),
    "sc_val":     S("scval",   20, "bold",     C_NAVY,   TA_CENTER, leading=22),
    "sc_sub":     S("scsub",   7,  "regular",  C_GREY_2, TA_CENTER),
    # Footer
    "footer_l":   S("ftl",     7,  "regular",  C_GREY_2, TA_LEFT),
    "footer_r":   S("ftr",     7,  "regular",  C_GREY_2, TA_RIGHT),
    # Callout
    "warn":       S("warn",    7.5,"semibold", C_RED,    TA_LEFT),
    "note":       S("note",    7.5,"regular",  C_GREY_1, TA_LEFT),
    "price_lg":   S("pricelg", 14, "bold",     C_NAVY,   TA_CENTER, leading=16),
    "price_lbl":  S("pricelbl",7,  "semibold", C_GREY_1, TA_CENTER),
    "price_sub":  S("pricesub",6.5,"regular",  C_GREY_2, TA_CENTER),
}

def pp(text, style="cell"):
    from reportlab.platypus import Paragraph
    st = STYLES.get(style) or STYLES["cell"]
    return Paragraph(str(text) if text else "—", st)

def safe(v, n=250):
    if not v:
        return "—"
    s = str(v)
    return s[:n] + "…" if len(s) > n else s

def pct(w):
    return f"{w*100:.0f}%" if w else "—"

def fmt_cad(v):
    return f"CAD {v:,.2f}" if v else "—"

def status_para(status):
    col = STATUS_COLOUR.get(status, C_GREY_2)
    fn  = _font("semibold")
    from reportlab.platypus import Paragraph
    hex_col = col.hexval()[2:]
    return Paragraph(
        f'<font name="{fn}" color="#{hex_col}">{status}</font>',
        ParagraphStyle("sp", fontName=fn, fontSize=7.5, leading=10,
                       textColor=col, alignment=TA_LEFT)
    )

# ── Page geometry ─────────────────────────────────────────────────────────────
PW_L, PH_L = landscape(A4)
PW_P, PH_P = A4
ML = MR = 18 * mm
MT = 20 * mm
MB = 18 * mm

def content_w(landscape_mode=True):
    return (PW_L if landscape_mode else PW_P) - ML - MR

# ── Footer builder ────────────────────────────────────────────────────────────
def make_footer(left_text, landscape_mode=True):
    PW = PW_L if landscape_mode else PW_P
    def _footer(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(C_GREY_3)
        canvas.setLineWidth(0.5)
        canvas.line(ML, MB - 2*mm, PW - MR, MB - 2*mm)
        canvas.setFont(_font("regular"), 7)
        canvas.setFillColor(C_GREY_2)
        canvas.drawString(ML, MB - 6*mm, left_text)
        canvas.drawRightString(PW - MR, MB - 6*mm,
                               f"Page {doc.page}")
        canvas.restoreState()
    return _footer

# ── Cover header builder ──────────────────────────────────────────────────────
def cover_header(story, bid, doc_type_label):
    """Append McKinsey-style page header to story list."""
    from reportlab.platypus import Paragraph, Spacer, HRFlowable
    from datetime import date

    story.append(pp("Enable My Growth  ·  Bid Intelligence Platform", "firm"))
    story.append(Spacer(1, 1*mm))
    story.append(pp(doc_type_label, "doc_type"))
    story.append(Spacer(1, 3*mm))

    # Thick navy rule
    story.append(HRFlowable(width="100%", thickness=3, color=C_NAVY, spaceAfter=3*mm))

    story.append(pp(bid.get("client", ""), "title"))
    story.append(Spacer(1, 1*mm))
    story.append(pp(bid.get("title", ""), "subtitle"))
    story.append(Spacer(1, 2*mm))

    parts = []
    if bid.get("file_number"):
        parts.append(f"File #{bid['file_number']}")
    if bid.get("submission_deadline"):
        parts.append(f"Submission  {bid['submission_deadline']}")
    if bid.get("clarification_deadline"):
        parts.append(f"Clarifications  {bid['clarification_deadline']}")
    if bid.get("owner"):
        parts.append(f"Proposal Lead  {bid['owner']}")
    parts.append(f"Generated  {date.today().strftime('%B %d, %Y')}")
    story.append(pp("     |     ".join(parts), "meta"))
    story.append(Spacer(1, 1.5*mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=C_GREY_3, spaceAfter=5*mm))


# ── Clarification Questions PDF ───────────────────────────────────────────────
def generate_clarifications_pdf(bid: dict, questions: list, include_rationale: bool = False) -> bytes:
    """
    McKinsey-style clarification questions PDF.
    Two modes: submission-ready (questions only) or internal (with rationale).
    """
    import io
    from datetime import date
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.colors import HexColor
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                     Table, TableStyle, HRFlowable, KeepTogether)
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT

    # Colours
    C_NAVY   = HexColor("#002060")
    C_BLUE   = HexColor("#1F5C99")
    C_GREY_1 = HexColor("#595959")
    C_GREY_2 = HexColor("#8C8C8C")
    C_GREY_3 = HexColor("#D9D9D9")
    C_GREY_4 = HexColor("#F5F5F5")
    C_WHITE  = HexColor("#FFFFFF")
    C_BLACK  = HexColor("#1A1A1A")
    C_RED    = HexColor("#C00000")
    C_AMBER  = HexColor("#E26B0A")

    PRI_COLOUR = {"Critical": C_RED, "High": C_AMBER, "Medium": C_BLUE, "Low": C_GREY_2}

    fn_r  = _font("regular")
    fn_m  = _font("medium")
    fn_sb = _font("semibold")
    fn_b  = _font("bold")

    def sp(name, size=9, fn=None, color=None, align=TA_LEFT, leading=None):
        return ParagraphStyle(name, fontName=fn or fn_r, fontSize=size,
                              leading=leading or size*1.35, textColor=color or C_BLACK,
                              alignment=align, spaceAfter=0, spaceBefore=0)

    def pp(text, size=9, fn=None, color=None, align=TA_LEFT, leading=None):
        return Paragraph(str(text) if text else "", sp("x", size, fn, color, align, leading))

    buf = io.BytesIO()
    PW, PH = A4
    ML = MR = 20*mm
    MT = 22*mm
    MB = 20*mm

    doc_label = (
        "Clarification Questions — Submission Copy" if not include_rationale
        else "Clarification Questions — Internal Working Document"
    )

    doc = SimpleDocTemplate(buf, pagesize=A4,
        leftMargin=ML, rightMargin=MR, topMargin=MT, bottomMargin=MB+10*mm,
        title=f"{doc_label} — {bid.get('client','')}",
        author="Enable My Growth — Bid Intelligence Platform")

    # Footer
    cw = PW - ML - MR
    def footer(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(C_GREY_3)
        canvas.setLineWidth(0.5)
        canvas.line(ML, MB, PW-MR, MB)
        canvas.setFont(fn_r, 7)
        canvas.setFillColor(C_GREY_2)
        canvas.drawString(ML, MB-4*mm,
            f"{bid.get('client','')}  ·  {bid.get('title','')}  ·  {doc_label}")
        canvas.drawRightString(PW-MR, MB-4*mm, f"Page {doc.page}")
        if include_rationale:
            canvas.setFillColor(C_RED)
            canvas.drawCentredString(PW/2, MB-4*mm, "INTERNAL USE ONLY — NOT FOR SUBMISSION")
        canvas.restoreState()

    story = []

    # ── Cover header ──────────────────────────────────────────────────────────
    story.append(pp("Enable My Growth  ·  Bid Intelligence Platform",
                    7.5, fn_sb, C_BLUE))
    story.append(Spacer(1, 1*mm))
    story.append(pp(doc_label, 8, fn_r, C_GREY_1))
    story.append(Spacer(1, 3*mm))
    story.append(HRFlowable(width="100%", thickness=3, color=C_NAVY, spaceAfter=3*mm))
    story.append(pp(bid.get("client",""), 20, fn_b, C_NAVY, leading=24))
    story.append(Spacer(1, 1*mm))
    story.append(pp(bid.get("title",""), 10, fn_r, C_GREY_1))
    story.append(Spacer(1, 2*mm))

    # Meta line
    parts = []
    if bid.get("file_number"):
        parts.append(f"File #{bid['file_number']}")
    if bid.get("clarification_deadline"):
        parts.append(f"Enquiry Deadline  {bid['clarification_deadline']}  14:00 Ottawa")
    if bid.get("submission_deadline"):
        parts.append(f"Submission  {bid['submission_deadline']}")
    parts.append(f"Generated  {date.today().strftime('%B %d, %Y')}")
    story.append(pp("     |     ".join(parts), 8, fn_r, C_GREY_2))
    story.append(Spacer(1, 1.5*mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=C_GREY_3, spaceAfter=4*mm))

    # ── Internal banner ───────────────────────────────────────────────────────
    if include_rationale:
        banner = Table([[pp("INTERNAL WORKING DOCUMENT — CONTAINS PRIVATE RATIONALE — NOT FOR SUBMISSION",
                            8, fn_sb, C_WHITE, TA_CENTER)]],
                       colWidths=[cw])
        banner.setStyle(TableStyle([
            ("BACKGROUND",    (0,0),(-1,-1), C_RED),
            ("TOPPADDING",    (0,0),(-1,-1), 3*mm),
            ("BOTTOMPADDING", (0,0),(-1,-1), 3*mm),
        ]))
        story.append(banner)
        story.append(Spacer(1, 4*mm))

    # ── Scorecard ─────────────────────────────────────────────────────────────
    pris = ["Critical", "High", "Medium"]
    counts = {p: len([q for q in questions if q.get("priority")==p]) for p in pris}
    total_q = len(questions)

    sc_data = [
        [pp(p, 7.5, fn_sb, PRI_COLOUR.get(p, C_GREY_1), TA_CENTER) for p in pris + ["Total"]],
        [pp(str(counts.get(p,0)), 18, fn_b, PRI_COLOUR.get(p, C_GREY_1), TA_CENTER) for p in pris]
        + [pp(str(total_q), 18, fn_b, C_NAVY, TA_CENTER)],
        [pp("questions", 7, fn_r, C_GREY_2, TA_CENTER) for _ in range(4)],
    ]
    sc_w = cw / 4
    sc = Table(sc_data, colWidths=[sc_w]*4, rowHeights=[7*mm, 11*mm, 6*mm])
    sc.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), C_GREY_4),
        ("LINEAFTER",     (0,0),(2,2),   0.5, C_GREY_3),
        ("BOX",           (0,0),(-1,-1), 0.5, C_GREY_3),
        ("LINEABOVE",     (0,0),(0,0),   3,   C_RED),
        ("LINEABOVE",     (1,0),(1,0),   3,   C_AMBER),
        ("LINEABOVE",     (2,0),(2,0),   3,   C_BLUE),
        ("LINEABOVE",     (3,0),(3,0),   3,   C_NAVY),
        ("TOPPADDING",    (0,0),(-1,-1), 2),
        ("BOTTOMPADDING", (0,0),(-1,-1), 2),
    ]))
    story.append(sc)
    story.append(Spacer(1, 3*mm))

    # Submission note
    if not include_rationale:
        story.append(pp(
            "Note: As required under §2.6, all enquiries and responses will be provided to all "
            "organizations invited to respond. Questions are submitted by email to "
            f"contracts@cda-amc.ca before {bid.get('clarification_deadline','')} 14:00 Ottawa local time.",
            7.5, fn_r, C_GREY_1))
        story.append(Spacer(1, 5*mm))
    else:
        story.append(pp(
            "Strategic context: Questions are phrased neutrally to avoid revealing Phoenix's "
            "position, subcontracting structure, or gaps. Rationale and risk assessments below "
            "are for internal planning only and must not be submitted.",
            7.5, fn_r, C_GREY_1))
        story.append(Spacer(1, 5*mm))

    story.append(HRFlowable(width="100%", thickness=0.5, color=C_GREY_3, spaceAfter=4*mm))

    # ── Questions ─────────────────────────────────────────────────────────────
    sorted_qs = sorted(questions,
        key=lambda q: {"Critical":0,"High":1,"Medium":2,"Low":3}.get(q.get("priority","Medium"),2))

    for i, q in enumerate(sorted_qs):
        pri     = q.get("priority","Medium")
        pri_col = PRI_COLOUR.get(pri, C_GREY_1)
        cat     = q.get("category","")
        qid     = q.get("id") or q.get("question_id") or str(i+1)
        relates = q.get("relates_to") or []
        if isinstance(relates, list):
            relates_str = ", ".join(relates)
        else:
            relates_str = str(relates)

        elems = []

        # Question number + priority badge row
        badge_w = 22*mm
        num_cell = pp(f"Q{qid}", 11, fn_b, C_NAVY)
        pri_text = Paragraph(
            f'<font name="{fn_sb}" size="7" color="#{pri_col.hexval()[2:]}">{pri.upper()}</font>',
            ParagraphStyle("pb", fontName=fn_sb, fontSize=7, leading=9,
                           textColor=pri_col, alignment=TA_CENTER,
                           borderPadding=2))

        hdr_row_tbl = Table(
            [[num_cell,
              Table([[pri_text]], colWidths=[badge_w-4*mm],
                    style=[("BACKGROUND",(0,0),(-1,-1),
                            HexColor(f"#{pri_col.hexval()[2:]}") if False else
                            HexColor("#{:02x}{:02x}{:02x}".format(
                                max(0,int(pri_col.red*255)-180+200),
                                max(0,int(pri_col.green*255)-180+200),
                                max(0,int(pri_col.blue*255)-180+200)))),
                           ("BOX",(0,0),(-1,-1),0.5,pri_col),
                           ("TOPPADDING",(0,0),(-1,-1),1),
                           ("BOTTOMPADDING",(0,0),(-1,-1),1)])
            ]],
            colWidths=[cw - badge_w, badge_w]
        )
        hdr_row_tbl.setStyle(TableStyle([
            ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
            ("LEFTPADDING",(0,0),(-1,-1),0),
            ("RIGHTPADDING",(0,0),(-1,-1),0),
        ]))
        elems.append(hdr_row_tbl)
        elems.append(Spacer(1, 1.5*mm))

        # Question text — prominent
        elems.append(pp(q.get("question",""), 9.5, fn_m, C_BLACK, leading=14))

        # Tags line
        tags = []
        if cat:
            tags.append(cat)
        if relates_str:
            tags.append(f"Ref: {relates_str}")
        if tags:
            elems.append(Spacer(1, 1*mm))
            elems.append(pp("  ·  ".join(tags), 7, fn_r, C_GREY_2))

        # Internal rationale block
        if include_rationale:
            rationale = q.get("rationale","")
            risk      = q.get("risk_if_unanswered","")
            if rationale or risk:
                elems.append(Spacer(1, 2*mm))
                rat_content = []
                if rationale:
                    rat_content.append(pp(f"Strategic rationale:  {rationale}",
                                          7.5, fn_r, C_GREY_1, leading=11))
                if risk:
                    rat_content.append(Spacer(1, 1*mm))
                    rat_content.append(pp(f"Risk if unanswered:  {risk}",
                                          7.5, fn_sb, C_RED, leading=11))

                rat_tbl = Table([[rat_content]], colWidths=[cw - 6*mm])
                rat_tbl.setStyle(TableStyle([
                    ("BACKGROUND",    (0,0),(-1,-1), HexColor("#FFF8F8")),
                    ("LINEBEFORE",    (0,0),(-1,-1), 2.5, C_RED),
                    ("TOPPADDING",    (0,0),(-1,-1), 3*mm),
                    ("BOTTOMPADDING", (0,0),(-1,-1), 3*mm),
                    ("LEFTPADDING",   (0,0),(-1,-1), 3*mm),
                    ("RIGHTPADDING",  (0,0),(-1,-1), 2*mm),
                ]))
                elems.append(rat_tbl)

        # Wrap question in a bordered card
        card = Table([[elems]], colWidths=[cw])
        card.setStyle(TableStyle([
            ("BACKGROUND",    (0,0),(-1,-1), C_WHITE),
            ("BOX",           (0,0),(-1,-1), 0.5, C_GREY_3),
            ("LINEBEFORE",    (0,0),(-1,-1), 3.5, pri_col),
            ("TOPPADDING",    (0,0),(-1,-1), 4*mm),
            ("BOTTOMPADDING", (0,0),(-1,-1), 4*mm),
            ("LEFTPADDING",   (0,0),(-1,-1), 4*mm),
            ("RIGHTPADDING",  (0,0),(-1,-1), 3*mm),
        ]))
        story.append(KeepTogether([card, Spacer(1, 3*mm)]))

    # ── Submission instructions (submission copy only) ─────────────────────────
    if not include_rationale:
        story.append(HRFlowable(width="100%", thickness=0.5, color=C_GREY_3, spaceAfter=4*mm))
        story.append(pp("Submission Instructions", 11, fn_b, C_NAVY))
        story.append(Spacer(1, 2*mm))
        instructions = [
            ("Submit to", f"contracts@cda-amc.ca"),
            ("Deadline", f"{bid.get('clarification_deadline','')} — 14:00 Ottawa local time (21:00 Beirut)"),
            ("Reference", f"File #{bid.get('file_number','')} in subject line"),
            ("Note", "All questions and responses will be shared with all invited organizations (§2.6)"),
            ("Responses", "CDA-AMC will respond within 2 business days; bulletins issued by July 28, 2026"),
        ]
        for label, value in instructions:
            row = Table([[pp(label, 8, fn_sb, C_NAVY), pp(value, 8, fn_r, C_BLACK)]],
                        colWidths=[35*mm, cw-35*mm])
            row.setStyle(TableStyle([
                ("LINEBELOW",     (0,0),(-1,-1), 0.4, C_GREY_3),
                ("TOPPADDING",    (0,0),(-1,-1), 2*mm),
                ("BOTTOMPADDING", (0,0),(-1,-1), 2*mm),
                ("LEFTPADDING",   (0,0),(-1,-1), 0),
            ]))
            story.append(row)

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


# ── Proposal Review PDF ───────────────────────────────────────────────────────
def generate_proposal_review_pdf(bid: dict, result: dict, proposal_filename: str = "") -> bytes:
    """
    McKinsey-style A4 portrait PDF for the proposal alignment review report.
    Sections: cover header → score card → executive summary → findings by
    severity → requirement coverage table → next steps.
    """
    import io
    from datetime import date
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, HRFlowable, Table, TableStyle,
        KeepTogether,
    )
    from reportlab.lib.colors import HexColor
    from reportlab.lib import colors

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=ML, rightMargin=MR,
        topMargin=MT, bottomMargin=MB + 8*mm,
        title=f"Proposal Review — {bid.get('client','')}",
    )

    CW = PW_P - ML - MR
    fn_r  = _font("regular")
    fn_sb = _font("semibold")

    # Local colour shortcuts
    C_CRIT   = HexColor("#C00000")
    C_HIGH   = HexColor("#E26B0A")
    C_MED    = HexColor("#7F6000")
    C_LOW    = C_GREY_2
    C_FULL   = HexColor("#375623")
    C_PART   = HexColor("#E26B0A")
    C_NONE   = C_CRIT

    SEV_COL  = {"Critical": C_CRIT, "High": C_HIGH, "Medium": C_MED, "Low": C_LOW}
    COV_COL  = {
        "Fully Addressed":     C_FULL,
        "Partially Addressed": C_PART,
        "Not Addressed":       C_NONE,
        "Cannot Assess":       C_GREY_2,
    }
    REC_COL  = {
        "SUBMIT AS-IS":             HexColor("#375623"),
        "REVISE BEFORE SUBMITTING": HexColor("#E26B0A"),
        "MAJOR REVISION NEEDED":    HexColor("#C00000"),
    }

    def _p(text, size=9, weight="regular", color=None, align=TA_LEFT, leading=None):
        from reportlab.platypus import Paragraph as _Para
        st = ParagraphStyle(
            "x", fontName=_font(weight), fontSize=size,
            leading=leading or max(size*1.3, size+3),
            textColor=color or C_BLACK, alignment=align,
        )
        return _Para(str(text) if text else "—", st)

    def _hr(thickness=0.5, color=C_GREY_3, space=3*mm):
        return HRFlowable(width="100%", thickness=thickness,
                          color=color, spaceAfter=space, spaceBefore=space)

    def _section_bar(label):
        """Full-width navy bar with white label — matches other PDFs."""
        tbl = Table([[_p(label, 8, "semibold", C_WHITE)]], colWidths=[CW])
        tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0,0), (-1,-1), C_NAVY),
            ("TOPPADDING",    (0,0), (-1,-1), 3*mm),
            ("BOTTOMPADDING", (0,0), (-1,-1), 3*mm),
            ("LEFTPADDING",   (0,0), (-1,-1), 4*mm),
        ]))
        return tbl

    story = []

    # ── Footer ────────────────────────────────────────────────────────────────
    footer_left = (f"{bid.get('client','')}  ·  Proposal Review  ·  "
                   f"Generated {date.today().strftime('%B %d, %Y')}")
    def footer(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(C_GREY_3)
        canvas.setLineWidth(0.5)
        canvas.line(ML, MB, PW_P - MR, MB)
        canvas.setFont(fn_r, 7)
        canvas.setFillColor(C_GREY_2)
        canvas.drawString(ML, MB - 4*mm, footer_left)
        canvas.drawRightString(PW_P - MR, MB - 4*mm, f"Page {doc.page}")
        canvas.restoreState()

    # ── Cover header ──────────────────────────────────────────────────────────
    cover_header(story, bid, "Proposal Alignment Review")
    if proposal_filename:
        story.append(_p(f"Analyzed file: {proposal_filename}", 7.5,
                        color=C_GREY_1))
        story.append(Spacer(1, 3*mm))

    # ── Score card ────────────────────────────────────────────────────────────
    score = result.get("overall_score", 0)
    rec   = result.get("recommendation", "")
    rec_c = REC_COL.get(rec, C_GREY_2)

    score_col = C_CRIT if score < 55 else (C_HIGH if score < 75 else C_FULL)

    score_tbl = Table(
        [[
            _p(str(score), 36, "bold", score_col, TA_CENTER),
            Table([
                [_p(rec, 9, "semibold", rec_c)],
                [_p(result.get("score_rationale", ""), 8, color=C_GREY_1)],
            ], colWidths=[CW * 0.72]),
        ]],
        colWidths=[CW * 0.18, CW * 0.82],
    )
    score_tbl.setStyle(TableStyle([
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
        ("LEFTPADDING",   (0,0), (-1,-1), 0),
        ("RIGHTPADDING",  (0,0), (-1,-1), 0),
        ("TOPPADDING",    (0,0), (-1,-1), 2*mm),
        ("BOTTOMPADDING", (0,0), (-1,-1), 2*mm),
        ("LINEBELOW",     (0,0), (-1,-1), 0.5, C_GREY_3),
    ]))
    story.append(score_tbl)
    story.append(Spacer(1, 4*mm))

    # ── Executive summary ─────────────────────────────────────────────────────
    story.append(_section_bar("EXECUTIVE SUMMARY"))
    story.append(Spacer(1, 2*mm))
    story.append(_p(result.get("executive_summary", ""), 8.5, color=C_GREY_1))

    # Strengths inline
    strengths = result.get("strengths", [])
    if strengths:
        story.append(Spacer(1, 3*mm))
        story.append(_p("Key Strengths", 8, "semibold", C_FULL))
        for s in strengths:
            story.append(_p(f"✓  {s}", 8, color=C_FULL))
    story.append(Spacer(1, 5*mm))

    # ── Findings ──────────────────────────────────────────────────────────────
    findings = result.get("findings", [])
    SEV_ORDER = ["Critical", "High", "Medium", "Low"]

    if findings:
        story.append(_section_bar("FINDINGS BY SEVERITY"))
        story.append(Spacer(1, 2*mm))

        # Summary count strip
        summary_cells = []
        for sev in SEV_ORDER:
            count = sum(1 for f in findings if f.get("severity") == sev)
            sc = SEV_COL.get(sev, C_GREY_2)
            summary_cells.append(
                Table([[
                    _p(str(count), 16, "bold", sc, TA_CENTER),
                    _p(sev, 7, color=C_GREY_1, align=TA_CENTER),
                ]], colWidths=[CW/4*0.35, CW/4*0.65])
            )
        strip = Table([summary_cells], colWidths=[CW/4]*4)
        strip.setStyle(TableStyle([
            ("LINEAFTER",     (0,0), (-3,-1), 0.5, C_GREY_3),
            ("ALIGN",         (0,0), (-1,-1), "CENTER"),
            ("TOPPADDING",    (0,0), (-1,-1), 1*mm),
            ("BOTTOMPADDING", (0,0), (-1,-1), 2*mm),
        ]))
        story.append(strip)
        story.append(_hr())

        for sev in SEV_ORDER:
            sev_findings = [f for f in findings if f.get("severity") == sev]
            if not sev_findings:
                continue
            sc = SEV_COL.get(sev, C_GREY_2)

            # Severity group label
            story.append(_p(f"{sev.upper()}  ({len(sev_findings)})",
                            7.5, "semibold", sc))
            story.append(Spacer(1, 1*mm))

            STAGE_COL_PDF = {
                "Proposal Submission":       HexColor("#C00000"),
                "Negotiation / Shortlist":   HexColor("#E26B0A"),
                "Contract Execution":        HexColor("#1F5C99"),
                "Contractual Obligation":    C_GREY_2,
            }

            for idx, finding in enumerate(sev_findings):
                title    = finding.get("title", "")
                issue    = finding.get("issue", "")
                rec_text = finding.get("recommendation", "")
                location = finding.get("proposal_location", "")
                effort   = finding.get("effort", "")
                req_id   = finding.get("req_id") or ""
                cat      = finding.get("category", "")
                stage    = finding.get("stage", "")
                stage_c  = STAGE_COL_PDF.get(stage, C_GREY_2)

                meta_parts = [x for x in [cat, f"Req {req_id}" if req_id else "",
                              location if location and location != "N/A" else ""] if x]
                meta_str   = "  ·  ".join(meta_parts)

                effort_col = {
                    "Minor edit":             C_FULL,
                    "Moderate rewrite":       C_HIGH,
                    "Major addition":         C_CRIT,
                    "Post-submission action": HexColor("#1F5C99"),
                }.get(effort, C_GREY_2)

                inner_rows = [
                    [_p(f"{sev[0]}{idx+1}  {title}", 8.5, "semibold")],
                    [_p(meta_str, 7, color=C_GREY_2)],
                ]
                if stage:
                    hex_sc = stage_c.hexval()[2:]
                    inner_rows.append([_p(
                        f'<font name="{fn_sb}" color="#{hex_sc}">\u23f1 {stage}</font>', 7
                    )])
                inner_rows += [
                    [_p(f"Issue: {issue}", 8, color=C_GREY_1)],
                    [_p(f"Recommendation: {rec_text}", 8, "semibold")],
                    [_p(f"Effort: {effort}", 7, color=effort_col)],
                ]

                finding_block = Table(
                    [[
                        Spacer(3*mm, 1),
                        Table(inner_rows, colWidths=[CW - 3*mm - 4*mm]),
                    ]],
                    colWidths=[3*mm, CW - 3*mm],
                )
                finding_block.setStyle(TableStyle([
                    ("BACKGROUND",    (0,0), (0,-1), sc),
                    ("BACKGROUND",    (1,0), (1,-1), C_GREY_4),
                    ("TOPPADDING",    (0,0), (-1,-1), 2.5*mm),
                    ("BOTTOMPADDING", (0,0), (-1,-1), 2.5*mm),
                    ("LEFTPADDING",   (1,0), (1,-1), 3*mm),
                    ("RIGHTPADDING",  (1,0), (1,-1), 3*mm),
                    ("LEFTPADDING",   (0,0), (0,-1), 0),
                    ("RIGHTPADDING",  (0,0), (0,-1), 0),
                    ("LINEBELOW",     (0,0), (-1,-1), 0.5, C_GREY_3),
                ]))
                story.append(KeepTogether(finding_block))
                story.append(Spacer(1, 1.5*mm))

            story.append(Spacer(1, 3*mm))

    # ── Requirement coverage ──────────────────────────────────────────────────
    coverage = result.get("requirement_coverage", [])
    if coverage:
        story.append(_section_bar("REQUIREMENT COVERAGE"))
        story.append(Spacer(1, 2*mm))

        # Column widths: ID | Cat | Description | Coverage | Confidence
        col_w = [c*mm for c in [18, 25, 90, 40, 22]]
        scale = CW / sum(col_w)
        col_w = [w * scale for w in col_w]

        hdr_row = [
            _p(h, 7, "semibold", C_WHITE)
            for h in ["Req ID", "Category", "Description", "Coverage", "Conf."]
        ]
        rows = [hdr_row]

        for cov in coverage:
            cov_status = cov.get("coverage", "")
            cc = COV_COL.get(cov_status, C_GREY_2)
            hex_cc = cc.hexval()[2:]
            fn_sb_name = fn_sb

            rows.append([
                _p(cov.get("req_id", ""), 7.5, "bold", C_NAVY),
                _p(cov.get("category", ""), 7, color=C_GREY_1),
                Table([
                    [_p(cov.get("description", ""), 7.5)],
                    [_p(cov.get("notes", ""), 7, color=C_GREY_2)],
                ], colWidths=[col_w[2]]),
                _p(
                    f'<font name="{fn_sb_name}" color="#{hex_cc}">{cov_status}</font>',
                    7.5
                ),
                _p(cov.get("confidence", ""), 7, color=C_GREY_1, align=TA_CENTER),
            ])

        cov_tbl = Table(rows, colWidths=col_w, repeatRows=1)
        cov_tbl.setStyle(TableStyle([
            # Header row
            ("BACKGROUND",    (0,0), (-1,0), C_NAVY),
            ("TOPPADDING",    (0,0), (-1,0), 2.5*mm),
            ("BOTTOMPADDING", (0,0), (-1,0), 2.5*mm),
            ("LEFTPADDING",   (0,0), (-1,-1), 2*mm),
            ("RIGHTPADDING",  (0,0), (-1,-1), 2*mm),
            # Data rows
            ("TOPPADDING",    (0,1), (-1,-1), 2*mm),
            ("BOTTOMPADDING", (0,1), (-1,-1), 2*mm),
            ("VALIGN",        (0,0), (-1,-1), "TOP"),
            ("ROWBACKGROUNDS",(0,1), (-1,-1), [C_WHITE, C_GREY_4]),
            ("LINEBELOW",     (0,0), (-1,-1), 0.4, C_GREY_3),
        ]))
        story.append(cov_tbl)
        story.append(Spacer(1, 5*mm))

    # ── Next steps ────────────────────────────────────────────────────────────
    next_steps = result.get("next_steps", [])
    if next_steps:
        story.append(_section_bar("RECOMMENDED NEXT STEPS"))
        story.append(Spacer(1, 2*mm))

        for step in sorted(next_steps, key=lambda x: x.get("priority", 99)):
            pri    = step.get("priority", "")
            action = step.get("action", "")
            rat    = step.get("rationale", "")
            when   = step.get("when", "")

            step_block = Table([[
                _p(f"#{pri}", 9, "bold", C_NAVY, TA_CENTER),
                Table([
                    [_p(action, 8.5, "semibold")],
                    [_p(f"When: {when}  ·  {rat}" if when else rat, 8, color=C_GREY_1)],
                ], colWidths=[CW - 16*mm]),
            ]], colWidths=[16*mm, CW - 16*mm])
            step_block.setStyle(TableStyle([
                ("VALIGN",        (0,0), (-1,-1), "TOP"),
                ("LINEBELOW",     (0,0), (-1,-1), 0.4, C_GREY_3),
                ("TOPPADDING",    (0,0), (-1,-1), 2*mm),
                ("BOTTOMPADDING", (0,0), (-1,-1), 2.5*mm),
                ("LEFTPADDING",   (0,0), (-1,-1), 0),
                ("RIGHTPADDING",  (0,0), (-1,-1), 0),
            ]))
            story.append(KeepTogether(step_block))

    # ── Truncation note ───────────────────────────────────────────────────────
    if result.get("_truncated"):
        story.append(Spacer(1, 5*mm))
        story.append(_p(
            "Note: AI response was partially truncated. Coverage table or "
            "next steps may be incomplete. Re-run analysis for full output.",
            7.5, color=C_AMBER,
        ))

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


# ── Proposal Review PDF ───────────────────────────────────────────────────────
def generate_proposal_review_pdf(bid: dict, result: dict, proposal_filename: str = "") -> bytes:
    """
    McKinsey-style A4 portrait PDF of the proposal alignment analysis report.
    Sections: cover header → score panel → executive summary → strengths →
              findings by severity → requirement coverage → next steps.
    """
    import io
    from datetime import date
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, HRFlowable, Table, TableStyle,
        KeepTogether,
    )
    from reportlab.lib import colors

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=ML, rightMargin=MR,
        topMargin=MT, bottomMargin=MB + 8*mm,
    )

    fn_r  = _font("regular")
    CW    = content_w(landscape_mode=False)

    # ── Style helpers ─────────────────────────────────────────────────────────
    def _p(text, size=8, weight="regular", color=C_BLACK, align=TA_LEFT, leading=None):
        fn = _font(weight)
        st = ParagraphStyle(
            f"pr_{size}_{weight}", fontName=fn, fontSize=size,
            leading=leading or max(size * 1.35, size + 3),
            textColor=color, alignment=align,
        )
        from reportlab.platypus import Paragraph as _Para
        return _Para(str(text) if text else "—", st)

    SEV_COLOUR = {
        "Critical": C_RED,
        "High":     C_AMBER,
        "Medium":   HexColor("#7F6000"),
        "Low":      C_GREY_2,
    }
    SEV_BG = {
        "Critical": HexColor("#FFF0F0"),
        "High":     HexColor("#FFF8F0"),
        "Medium":   HexColor("#FDFAF0"),
        "Low":      C_GREY_4,
    }
    COV_COLOUR = {
        "Fully Addressed":     C_GREEN,
        "Partially Addressed": C_AMBER,
        "Not Addressed":       C_RED,
        "Cannot Assess":       C_GREY_2,
    }
    EFFORT_COL = {
        "Minor edit":       C_GREEN,
        "Moderate rewrite": C_AMBER,
        "Major addition":   C_RED,
    }
    REC_COLOUR = {
        "SUBMIT AS-IS":             C_GREEN,
        "REVISE BEFORE SUBMITTING": C_AMBER,
        "MAJOR REVISION NEEDED":    C_RED,
    }

    story = []

    # ── Footer ────────────────────────────────────────────────────────────────
    footer_label = f"{bid.get('client','')}  ·  Proposal Review Report  ·  {date.today().strftime('%B %d, %Y')}"
    footer = make_footer(footer_label, landscape_mode=False)

    # ── Cover header ──────────────────────────────────────────────────────────
    cover_header(story, bid, "Proposal Review — RFP Alignment Analysis")
    if proposal_filename:
        story.append(_p(f"Reviewed file: {proposal_filename}", 7.5, color=C_GREY_2))
        story.append(Spacer(1, 3*mm))

    # ── Score panel ───────────────────────────────────────────────────────────
    score     = result.get("overall_score", 0)
    rec       = result.get("recommendation", "")
    rec_col   = REC_COLOUR.get(rec, C_GREY_1)
    score_col = C_GREEN if score >= 75 else C_AMBER if score >= 55 else C_RED

    score_tbl = Table(
        [[
            _p(str(score), 32, "bold", score_col, TA_CENTER),
            Table(
                [[_p("RECOMMENDATION", 6.5, "semibold", C_GREY_2)],
                 [_p(rec, 9, "bold", rec_col)],
                 [Spacer(1, 2*mm)],
                 [_p(result.get("score_rationale", ""), 7.5, color=C_GREY_1)]],
                colWidths=[CW * 0.72],
                style=TableStyle([("VALIGN", (0,0), (-1,-1), "TOP"),
                                  ("LEFTPADDING", (0,0), (-1,-1), 0),
                                  ("RIGHTPADDING", (0,0), (-1,-1), 0)])
            ),
        ]],
        colWidths=[CW * 0.18, CW * 0.82],
    )
    score_tbl.setStyle(TableStyle([
        ("BOX",        (0,0), (-1,-1), 0.75, C_GREY_3),
        ("LINEAFTER",  (0,0), (0,-1),  0.5,  C_GREY_3),
        ("VALIGN",     (0,0), (-1,-1), "MIDDLE"),
        ("LEFTPADDING",(0,0), (-1,-1), 6),
        ("TOPPADDING", (0,0), (-1,-1), 6),
        ("BOTTOMPADDING",(0,0),(-1,-1), 6),
        ("BACKGROUND", (0,0), (0,-1),  C_GREY_4),
    ]))
    story.append(score_tbl)
    story.append(Spacer(1, 5*mm))

    # ── Executive summary ─────────────────────────────────────────────────────
    story.append(_p("EXECUTIVE SUMMARY", 7.5, "semibold", C_NAVY))
    story.append(Spacer(1, 1*mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=C_GREY_3, spaceAfter=2*mm))
    story.append(_p(result.get("executive_summary", ""), 8.5, color=C_GREY_1, leading=13))
    story.append(Spacer(1, 5*mm))

    # ── Strengths ─────────────────────────────────────────────────────────────
    strengths = result.get("strengths", [])
    if strengths:
        story.append(_p("STRENGTHS", 7.5, "semibold", C_NAVY))
        story.append(Spacer(1, 1*mm))
        story.append(HRFlowable(width="100%", thickness=0.5, color=C_GREY_3, spaceAfter=2*mm))
        for s in strengths:
            row = Table(
                [[_p("✓", 8, "semibold", C_GREEN), _p(s, 8, color=C_GREY_1)]],
                colWidths=[6*mm, CW - 6*mm],
            )
            row.setStyle(TableStyle([
                ("VALIGN",       (0,0),(-1,-1),"TOP"),
                ("LEFTPADDING",  (0,0),(-1,-1), 0),
                ("RIGHTPADDING", (0,0),(-1,-1), 0),
                ("TOPPADDING",   (0,0),(-1,-1), 1),
                ("BOTTOMPADDING",(0,0),(-1,-1), 1),
            ]))
            story.append(row)
        story.append(Spacer(1, 5*mm))

    # ── Findings ──────────────────────────────────────────────────────────────
    findings = result.get("findings", [])
    if findings:
        story.append(_p("FINDINGS BY SEVERITY", 7.5, "semibold", C_NAVY))
        story.append(Spacer(1, 1*mm))
        story.append(HRFlowable(width="100%", thickness=0.5, color=C_GREY_3, spaceAfter=3*mm))

        # Severity summary strip
        sev_counts = {}
        for f in findings:
            sev_counts[f.get("severity","")] = sev_counts.get(f.get("severity",""), 0) + 1
        sev_cells = []
        for sev in ("Critical", "High", "Medium", "Low"):
            cnt = sev_counts.get(sev, 0)
            if cnt:
                sc = SEV_COLOUR[sev]
                sev_cells.append([
                    _p(sev, 7, "semibold", sc, TA_CENTER),
                    _p(str(cnt), 12, "bold", sc, TA_CENTER),
                ])
        if sev_cells:
            # Transpose: one row per col
            strip_data = [[c[0] for c in sev_cells], [c[1] for c in sev_cells]]
            col_w = CW / len(sev_cells)
            strip = Table(strip_data, colWidths=[col_w] * len(sev_cells))
            strip.setStyle(TableStyle([
                ("BOX",          (0,0),(-1,-1), 0.5, C_GREY_3),
                ("INNERGRID",    (0,0),(-1,-1), 0.5, C_GREY_3),
                ("TOPPADDING",   (0,0),(-1,-1), 3),
                ("BOTTOMPADDING",(0,0),(-1,-1), 3),
                ("BACKGROUND",   (0,0),(-1,-1), C_GREY_4),
            ]))
            story.append(strip)
            story.append(Spacer(1, 4*mm))

        for sev in ("Critical", "High", "Medium", "Low"):
            sev_findings = [f for f in findings if f.get("severity") == sev]
            if not sev_findings:
                continue
            sc = SEV_COLOUR[sev]
            bg = SEV_BG[sev]

            # Severity group header
            hdr = Table(
                [[_p(f"  {sev.upper()}  ({len(sev_findings)})", 7.5, "semibold", C_WHITE)]],
                colWidths=[CW],
            )
            hdr.setStyle(TableStyle([
                ("BACKGROUND",   (0,0),(-1,-1), sc),
                ("TOPPADDING",   (0,0),(-1,-1), 3),
                ("BOTTOMPADDING",(0,0),(-1,-1), 3),
                ("LEFTPADDING",  (0,0),(-1,-1), 4),
            ]))
            story.append(hdr)
            story.append(Spacer(1, 1*mm))

            for idx, f in enumerate(sev_findings):
                title    = f.get("title", "")
                req_id   = f.get("req_id") or ""
                cat      = f.get("category", "")
                issue    = f.get("issue", "")
                rec_text = f.get("recommendation", "")
                location = f.get("proposal_location", "")
                effort   = f.get("effort", "")
                ec       = EFFORT_COL.get(effort, C_GREY_2)

                tag_parts = [p for p in [cat, f"Req {req_id}" if req_id else "", location] if p]
                tags_str  = "  ·  ".join(tag_parts)

                finding_block = Table(
                    [
                        [_p(f"{sev[0]}{idx+1}  {title}", 8.5, "semibold", C_BLACK)],
                        [_p(tags_str, 7, color=C_GREY_2)] if tags_str else [Spacer(1, 1)],
                        [Spacer(1, 1*mm)],
                        [_p(f"Issue: {issue}", 8, color=C_GREY_1)],
                        [Spacer(1, 1*mm)],
                        [_p(f"Recommendation: {rec_text}", 8, "semibold", C_BLACK)],
                        [_p(f"Effort: {effort}", 7, color=ec)],
                    ],
                    colWidths=[CW - 6*mm],
                )
                finding_block.setStyle(TableStyle([
                    ("LEFTPADDING",  (0,0),(-1,-1), 4),
                    ("RIGHTPADDING", (0,0),(-1,-1), 4),
                    ("TOPPADDING",   (0,0),(-1,-1), 1),
                    ("BOTTOMPADDING",(0,0),(-1,-1), 1),
                    ("BACKGROUND",   (0,0),(-1,-1), bg),
                ]))

                # Left border stripe via wrapper table
                wrapper = Table(
                    [[Table([[_p("", 1)]], colWidths=[4*mm],
                             style=TableStyle([("BACKGROUND",(0,0),(-1,-1), sc),
                                               ("LEFTPADDING",(0,0),(-1,-1),0),
                                               ("RIGHTPADDING",(0,0),(-1,-1),0)])),
                      finding_block]],
                    colWidths=[4*mm, CW - 4*mm],
                )
                wrapper.setStyle(TableStyle([
                    ("LEFTPADDING",  (0,0),(-1,-1), 0),
                    ("RIGHTPADDING", (0,0),(-1,-1), 0),
                    ("TOPPADDING",   (0,0),(-1,-1), 0),
                    ("BOTTOMPADDING",(0,0),(-1,-1), 0),
                    ("BOX",          (0,0),(-1,-1), 0.5, C_GREY_3),
                ]))
                story.append(KeepTogether(wrapper))
                story.append(Spacer(1, 2*mm))

        story.append(Spacer(1, 3*mm))

    # ── Requirement coverage ──────────────────────────────────────────────────
    coverage = result.get("requirement_coverage", [])
    if coverage:
        story.append(_p("REQUIREMENT COVERAGE", 7.5, "semibold", C_NAVY))
        story.append(Spacer(1, 1*mm))
        story.append(HRFlowable(width="100%", thickness=0.5, color=C_GREY_3, spaceAfter=2*mm))

        # Coverage summary strip
        cov_counts = {}
        for c in coverage:
            k = c.get("coverage", "")
            cov_counts[k] = cov_counts.get(k, 0) + 1
        cov_order = ["Fully Addressed","Partially Addressed","Not Addressed","Cannot Assess"]
        cov_strip_data = [[],[]]
        for k in cov_order:
            if cov_counts.get(k):
                cc = COV_COLOUR[k]
                cov_strip_data[0].append(_p(k, 6.5, "semibold", cc, TA_CENTER))
                cov_strip_data[1].append(_p(str(cov_counts[k]), 11, "bold", cc, TA_CENTER))
        if cov_strip_data[0]:
            n = len(cov_strip_data[0])
            cs = Table(cov_strip_data, colWidths=[CW/n]*n)
            cs.setStyle(TableStyle([
                ("BOX",          (0,0),(-1,-1), 0.5, C_GREY_3),
                ("INNERGRID",    (0,0),(-1,-1), 0.5, C_GREY_3),
                ("TOPPADDING",   (0,0),(-1,-1), 3),
                ("BOTTOMPADDING",(0,0),(-1,-1), 3),
                ("BACKGROUND",   (0,0),(-1,-1), C_GREY_4),
            ]))
            story.append(cs)
            story.append(Spacer(1, 3*mm))

        # Table header
        col_w = [14*mm, 22*mm, 60*mm, 42*mm, 20*mm]
        scale = CW / sum(col_w)
        col_w = [w * scale for w in col_w]
        hdr_data = [[
            _p("Req ID",     7, "semibold", C_WHITE),
            _p("Category",   7, "semibold", C_WHITE),
            _p("Description",7, "semibold", C_WHITE),
            _p("Coverage",   7, "semibold", C_WHITE),
            _p("Confidence", 7, "semibold", C_WHITE),
        ]]
        hdr_tbl = Table(hdr_data, colWidths=col_w)
        hdr_tbl.setStyle(TableStyle([
            ("BACKGROUND",   (0,0),(-1,-1), C_NAVY),
            ("TOPPADDING",   (0,0),(-1,-1), 3),
            ("BOTTOMPADDING",(0,0),(-1,-1), 3),
            ("LEFTPADDING",  (0,0),(-1,-1), 4),
        ]))
        story.append(hdr_tbl)

        for row_i, cov in enumerate(coverage):
            cov_status = cov.get("coverage", "")
            cc = COV_COLOUR.get(cov_status, C_GREY_2)
            bg = C_GREY_4 if row_i % 2 == 0 else C_WHITE
            notes = cov.get("notes", "")
            desc  = cov.get("description", "")
            desc_cell = f"{desc}<br/><font name='{fn_r}' size='6.5' color='#8C8C8C'>{notes}</font>" if notes else desc

            row_data = [[
                _p(cov.get("req_id",""),    7.5, "semibold", C_NAVY),
                _p(cov.get("category",""),  7.5, color=C_GREY_1),
                Paragraph(desc_cell, ParagraphStyle("dc", fontName=fn_r, fontSize=7.5,
                          leading=10, textColor=C_BLACK)),
                _p(cov_status, 7.5, "semibold", cc),
                _p(cov.get("confidence",""), 7.5, color=C_GREY_2),
            ]]
            row_tbl = Table(row_data, colWidths=col_w)
            row_tbl.setStyle(TableStyle([
                ("BACKGROUND",   (0,0),(-1,-1), bg),
                ("TOPPADDING",   (0,0),(-1,-1), 3),
                ("BOTTOMPADDING",(0,0),(-1,-1), 3),
                ("LEFTPADDING",  (0,0),(-1,-1), 4),
                ("LINEBELOW",    (0,0),(-1,-1), 0.25, C_GREY_3),
                ("VALIGN",       (0,0),(-1,-1), "TOP"),
            ]))
            story.append(row_tbl)

        story.append(Spacer(1, 5*mm))

    # ── Next steps ────────────────────────────────────────────────────────────
    next_steps = result.get("next_steps", [])
    if next_steps:
        story.append(_p("RECOMMENDED NEXT STEPS", 7.5, "semibold", C_NAVY))
        story.append(Spacer(1, 1*mm))
        story.append(HRFlowable(width="100%", thickness=0.5, color=C_GREY_3, spaceAfter=2*mm))
        for step in sorted(next_steps, key=lambda x: x.get("priority", 99)):
            pri = step.get("priority", "")
            action = step.get("action", "")
            rationale = step.get("rationale", "")
            ns_row = Table(
                [[
                    _p(f"#{pri}", 9, "bold", C_NAVY, TA_CENTER),
                    Table(
                        [[_p(action, 8.5, "semibold", C_BLACK)],
                         [_p(rationale, 7.5, color=C_GREY_1)]],
                        colWidths=[CW - 14*mm],
                        style=TableStyle([("LEFTPADDING",(0,0),(-1,-1),0),
                                          ("RIGHTPADDING",(0,0),(-1,-1),0),
                                          ("TOPPADDING",(0,0),(-1,-1),1),
                                          ("BOTTOMPADDING",(0,0),(-1,-1),1)])
                    ),
                ]],
                colWidths=[12*mm, CW - 12*mm],
            )
            ns_row.setStyle(TableStyle([
                ("BOX",          (0,0),(-1,-1), 0.5, C_GREY_3),
                ("LINEAFTER",    (0,0),(0,-1),  0.5, C_GREY_3),
                ("BACKGROUND",   (0,0),(0,-1),  C_GREY_4),
                ("VALIGN",       (0,0),(-1,-1), "TOP"),
                ("LEFTPADDING",  (0,0),(-1,-1), 4),
                ("TOPPADDING",   (0,0),(-1,-1), 4),
                ("BOTTOMPADDING",(0,0),(-1,-1), 4),
            ]))
            story.append(KeepTogether(ns_row))
            story.append(Spacer(1, 2*mm))

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
