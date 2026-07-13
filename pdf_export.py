"""
Compliance Matrix PDF — McKinsey style.
White background, Inter typography, colour as signal only.
"""
import io
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                 TableStyle, HRFlowable, KeepTogether)
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT

from pdf_styles import (
    pp, safe, pct, status_para, cover_header, make_footer,
    content_w, STYLES, CAT_ACCENT, STATUS_COLOUR,
    C_NAVY, C_BLUE, C_BLUE_L, C_WHITE, C_BLACK,
    C_GREY_1, C_GREY_2, C_GREY_3, C_GREY_4,
    C_RED, PW_L, PH_L, ML, MR, MT, MB,
    _font,
)

# Column widths (mm, landscape A4 ≈ 239mm usable)
RAW_CW = [11, 18, 65, 50, 26, 16, 12, 26]
SCALE  = content_w(True) / sum(r * mm for r in RAW_CW)
COL_W  = [r * mm * SCALE for r in RAW_CW]
HDR    = ["ID", "RFSO Ref", "Requirement", "Evidence Required",
          "Owner", "Deadline", "Weight", "Status"]


def _section(cat, reqs):
    """Build one KeepTogether section for a requirement category."""
    accent = CAT_ACCENT.get(cat, C_BLUE)
    done   = sum(1 for r in reqs if r.get("status") == "Complete")
    total  = len(reqs)
    pct_str= f"{round(done/total*100) if total else 0}%"

    # Section header bar — navy fill, white text
    hdr_bar = Table(
        [[Paragraph(
            f'<font name="{_font("bold")}" color="#FFFFFF">'
            f'{cat.upper()}</font>'
            f'<font name="{_font("regular")}" color="#FFFFFF"> — </font>'
            f'<font name="{_font("semibold")}" color="#FFFFFF">'
            f'{done}/{total} complete ({pct_str})</font>',
            ParagraphStyle("sh", fontName=_font("bold"), fontSize=8.5,
                           leading=11, textColor=C_WHITE)
        )]],
        colWidths=[content_w(True)]
    )
    hdr_bar.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), C_NAVY),
        ("TOPPADDING",    (0,0),(-1,-1), 3*mm),
        ("BOTTOMPADDING", (0,0),(-1,-1), 3*mm),
        ("LEFTPADDING",   (0,0),(-1,-1), 3*mm),
        ("LINEABOVE",     (0,0),(-1,0),  2, accent),
    ]))

    # Column header row
    hdr_row = [Paragraph(h, STYLES["col_hdr"]) for h in HDR]

    # Data rows
    tdata = [hdr_row]
    for req in reqs:
        row = [
            pp(safe(req.get("req_id"),   8),  "cell_id"),
            pp(safe(req.get("rfso_ref"), 50),  "cell_ref"),
            pp(safe(req.get("description"), 280), "cell"),
            pp(safe(req.get("evidence"),   180), "cell_sm"),
            pp(safe(req.get("owner"),       30), "cell"),
            pp(safe(req.get("deadline"),    20), "cell_sm"),
            pp(pct(req.get("weight")),           "cell"),
            status_para(req.get("status", "Not Started")),
        ]
        tdata.append(row)

    t = Table(tdata, colWidths=COL_W, repeatRows=1)
    ts = TableStyle([
        # Column header
        ("BACKGROUND",    (0,0), (-1,0), C_BLUE),
        ("TOPPADDING",    (0,0), (-1,0), 2.5*mm),
        ("BOTTOMPADDING", (0,0), (-1,0), 2.5*mm),
        ("LINEBELOW",     (0,0), (-1,0), 1.5, C_NAVY),
        # Data cells
        ("VALIGN",        (0,0), (-1,-1), "TOP"),
        ("TOPPADDING",    (0,1), (-1,-1), 3),
        ("BOTTOMPADDING", (0,1), (-1,-1), 3),
        ("LEFTPADDING",   (0,0), (-1,-1), 3),
        ("RIGHTPADDING",  (0,0), (-1,-1), 3),
        # Borders — thin grey only
        ("LINEBELOW",     (0,1), (-1,-1), 0.4, C_GREY_3),
        ("BOX",           (0,0), (-1,-1), 0.5, C_GREY_3),
        # Left accent stripe (category colour) on ID column
        ("LINEBEFORE",    (0,1), (0,-1),  2.5, accent),
    ])
    # Alternating row backgrounds — white / very light blue
    for i in range(1, len(tdata)):
        bg = C_WHITE if i % 2 == 1 else C_BLUE_L
        ts.add("BACKGROUND", (0,i), (-1,i), bg)

    t.setStyle(ts)
    return KeepTogether([hdr_bar, t, Spacer(1, 5*mm)])


def _scorecard(requirements):
    """4-column summary scorecard."""
    cats   = ["Mandatory", "Rated", "Financial", "Supporting"]
    totals = {c: len([r for r in requirements if r["category"]==c]) for c in cats}
    dones  = {c: len([r for r in requirements if r["category"]==c
                       and r.get("status")=="Complete"]) for c in cats}

    rows = [
        [Paragraph(c, STYLES["sc_cat"]) for c in cats],
        [Paragraph(f"{dones[c]}/{totals[c]}", STYLES["sc_val"]) for c in cats],
        [Paragraph(
            f"{round(dones[c]/totals[c]*100) if totals[c] else 0}% complete",
            STYLES["sc_sub"]) for c in cats],
    ]
    cw = content_w(True) / 4
    t  = Table(rows, colWidths=[cw]*4, rowHeights=[7*mm, 11*mm, 7*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), C_GREY_4),
        ("LINEAFTER",     (0,0), (2,2),   0.5, C_GREY_3),
        ("LINEBELOW",     (0,0), (-1,0),  0.5, C_GREY_3),
        ("BOX",           (0,0), (-1,-1), 0.5, C_GREY_3),
        ("TOPPADDING",    (0,0), (-1,-1), 2),
        ("BOTTOMPADDING", (0,0), (-1,-1), 2),
        # Top accent per category
        ("LINEABOVE", (0,0), (0,0), 3, CAT_ACCENT.get("Mandatory", C_RED)),
        ("LINEABOVE", (1,0), (1,0), 3, CAT_ACCENT.get("Rated",     C_BLUE)),
        ("LINEABOVE", (2,0), (2,0), 3, CAT_ACCENT.get("Financial", HexColor("#375623"))),
        ("LINEABOVE", (3,0), (3,0), 3, CAT_ACCENT.get("Supporting",HexColor("#7030A0"))),
    ]))
    return t


def generate_compliance_pdf(bid: dict, requirements: list) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4),
        leftMargin=ML, rightMargin=MR,
        topMargin=MT, bottomMargin=MB + 8*mm,
        title=f"Compliance Matrix — {bid.get('client','')}",
        author="Enable My Growth — Bid Intelligence Platform",
    )

    footer = make_footer(
        f"{bid.get('client','')}  ·  {bid.get('title','')}  ·  Compliance Matrix",
        landscape_mode=True
    )

    story = []
    cover_header(story, bid, "Proposal Compliance Matrix")

    # Scorecard
    story.append(_scorecard(requirements))

    # Mandatory warning
    mfail = sum(1 for r in requirements
                if r["category"] == "Mandatory"
                and r.get("status") not in ("Complete", "N/A"))
    if mfail:
        story.append(Spacer(1, 2*mm))
        story.append(Paragraph(
            f"⚠  {mfail} mandatory requirement{'s' if mfail>1 else ''} outstanding — "
            f"submission may be disqualified if unresolved before the deadline.",
            STYLES["warn"]))

    story.append(Spacer(1, 5*mm))

    for cat in ["Mandatory", "Rated", "Financial", "Supporting"]:
        cr = [r for r in requirements if r["category"] == cat]
        if cr:
            story.append(_section(cat, cr))

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
