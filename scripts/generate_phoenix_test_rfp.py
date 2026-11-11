"""
scripts/generate_phoenix_test_rfp.py

Generates a representative, realistic procurement RFP PDF for Phoenix Consulting beta commissioning:
City of Edmonton - Municipal IT Operations Transformation & Strategic Advisory Services
RFP Solicitation No: COE-RFP-2026-088
"""
import io
import os
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak


def generate_rfp_pdf_bytes() -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=54, rightMargin=54, topMargin=54, bottomMargin=54
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "RFPTitle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=24,
        textColor=colors.HexColor("#1A2B4C"),
        spaceAfter=12
    )
    subtitle_style = ParagraphStyle(
        "RFPSubTitle",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=17,
        textColor=colors.HexColor("#334D6E"),
        spaceAfter=14
    )
    h2_style = ParagraphStyle(
        "RFPH2",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#1A2B4C"),
        spaceBefore=14,
        spaceAfter=6
    )
    body_style = ParagraphStyle(
        "RFPBody",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9.5,
        leading=13.5,
        textColor=colors.HexColor("#2C3E50"),
        spaceAfter=6
    )
    table_cell = ParagraphStyle(
        "TableBody",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=11.5,
        textColor=colors.HexColor("#2C3E50")
    )
    table_header = ParagraphStyle(
        "TableHdr",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8.5,
        leading=11.5,
        textColor=colors.white
    )

    story = []

    # Title & Metadata
    story.append(Paragraph("REQUEST FOR PROPOSALS (RFP)", title_style))
    story.append(Paragraph("SOLICITATION NUMBER: COE-RFP-2026-088", subtitle_style))
    story.append(Paragraph("<b>Title:</b> Municipal IT Operations Transformation & Strategic Advisory Services", body_style))
    story.append(Paragraph("<b>Issuing Authority:</b> City of Edmonton, Procurement and Digital Governance Services", body_style))
    story.append(Paragraph("<b>Target Consultant:</b> Professional Advisory & IT Management Firms", body_style))
    story.append(Spacer(1, 10))

    # Section 1: Overview
    story.append(Paragraph("1. PROCUREMENT OVERVIEW AND OBJECTIVES", h2_style))
    story.append(Paragraph(
        "The City of Edmonton invites qualified advisory firms to submit proposals for the modernization, "
        "operational consolidation, and cloud-readiness advisory of the City's Municipal IT Operations. "
        "The engagement will encompass enterprise architecture review, governance optimization, workflow digitization, "
        "and vendor transition management over a 24-month horizon.",
        body_style
    ))
    story.append(Spacer(1, 8))

    # Key Dates Table
    story.append(Paragraph("2. KEY PROCUREMENT DATES AND TIMELINE", h2_style))
    key_dates_data = [
        [Paragraph("Milestone Event", table_header), Paragraph("Date & Time", table_header), Paragraph("Submission / Clarification Details", table_header)],
        [Paragraph("RFP Issuance Date", table_cell), Paragraph("August 1, 2026", table_cell), Paragraph("Published on Alberta Purchasing Connection (APC)", table_cell)],
        [Paragraph("Clarification Request Deadline", table_cell), Paragraph("August 18, 2026 at 16:00 MT", table_cell), Paragraph("Formal questions via procurement portal only", table_cell)],
        [Paragraph("Final Addendum Issuance", table_cell), Paragraph("August 22, 2026", table_cell), Paragraph("Responses to all vendor clarification requests", table_cell)],
        [Paragraph("Proposal Submission Deadline", table_cell), Paragraph("September 8, 2026 at 14:00 MT", table_cell), Paragraph("Strict cutoff. Late proposals will be rejected", table_cell)],
        [Paragraph("Anticipated Contract Award", table_cell), Paragraph("October 1, 2026", table_cell), Paragraph("Execution of Master Professional Services Agreement", table_cell)],
    ]
    t_dates = Table(key_dates_data, colWidths=[150, 140, 214])
    t_dates.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1A2B4C")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D0D7DE")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t_dates)
    story.append(Spacer(1, 12))

    # Section 3: Mandatory Requirements
    story.append(Paragraph("3. MANDATORY SUBMISSION REQUIREMENTS (PASS / FAIL)", h2_style))
    story.append(Paragraph(
        "Proponents must satisfy all mandatory requirements set out below. Proposals that fail to provide "
        "full compliance evidence for any mandatory criterion will be disqualified from further evaluation.",
        body_style
    ))
    mand_data = [
        [Paragraph("Ref ID", table_header), Paragraph("Mandatory Requirement Description", table_header), Paragraph("Compliance Evidence Required", table_header)],
        [Paragraph("M1", table_cell), Paragraph("Corporate Experience: Minimum 5 years of experience delivering IT advisory to Canadian municipal or public sector entities.", table_cell), Paragraph("Provide 3 public sector client reference letters completed within the last 5 years.", table_cell)],
        [Paragraph("M2", table_cell), Paragraph("Project Manager Certification: The designated Engagement Manager must hold active PMP (Project Management Professional) or equivalent certification.", table_cell), Paragraph("Copy of current certification credential and resume showing minimum 7 years experience.", table_cell)],
        [Paragraph("M3", table_cell), Paragraph("Bilingual Lead Capability: Primary stakeholder consultation team must include at least one lead consultant fluent in French and English.", table_cell), Paragraph("Staff CV indicating language competencies and bilingual advisory project references.", table_cell)],
        [Paragraph("M4", table_cell), Paragraph("Information Security & Privacy: Proponent must demonstrate certified compliance with ISO/IEC 27001 or SOC 2 Type II data security standards.", table_cell), Paragraph("Valid third-party audit certificate or SOC 2 report summary issued within past 12 months.", table_cell)],
    ]
    t_mand = Table(mand_data, colWidths=[40, 260, 204])
    t_mand.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#C0392B")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D0D7DE")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t_mand)
    story.append(Spacer(1, 12))

    # Section 4: Rated Evaluation Criteria
    story.append(Paragraph("4. RATED EVALUATION CRITERIA (100 TOTAL POINTS)", h2_style))
    story.append(Paragraph(
        "Proposals meeting all mandatory requirements will be evaluated against the rated criteria below. "
        "A minimum threshold score of 70% in Technical Methodology is required to proceed to Financial Opening.",
        body_style
    ))
    eval_data = [
        [Paragraph("Criterion ID", table_header), Paragraph("Evaluation Factor & Scope", table_header), Paragraph("Weight", table_header), Paragraph("Min Score", table_header)],
        [Paragraph("R1", table_cell), Paragraph("Technical Methodology & Work Plan: Approach to municipal enterprise architecture review, business alignment, and cloud roadmap feasibility.", table_cell), Paragraph("40%", table_cell), Paragraph("28 / 40", table_cell)],
        [Paragraph("R2", table_cell), Paragraph("Team Qualifications & Subject Matter Expertise: Experience of key personnel in municipal IT governance, change management, and service design.", table_cell), Paragraph("30%", table_cell), Paragraph("21 / 30", table_cell)],
        [Paragraph("R3", table_cell), Paragraph("Value Proposition & Innovation: Novel efficiency frameworks, automation accelerators, and knowledge transfer to City staff.", table_cell), Paragraph("15%", table_cell), Paragraph("None", table_cell)],
        [Paragraph("R4", table_cell), Paragraph("Commercial & Pricing Structure: Total cost of services, blended daily rate card, and transparent milestone fee schedule.", table_cell), Paragraph("15%", table_cell), Paragraph("Formula", table_cell)],
    ]
    t_eval = Table(eval_data, colWidths=[65, 300, 65, 74])
    t_eval.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1A2B4C")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D0D7DE")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t_eval)
    story.append(Spacer(1, 12))

    # Section 5: Commercial Terms & Pricing Instructions
    story.append(Paragraph("5. COMMERCIAL TERMS AND PRICING FORMAT", h2_style))
    story.append(Paragraph(
        "All pricing must be quoted in Canadian Dollars (CAD), exclusive of GST. Proponents must provide a "
        "firm fixed price for Phase 1 (Discovery & Architecture Assessment) capped at $250,000 CAD, and a "
        "time-and-materials rate schedule with hourly ceiling rates for Phase 2 Implementation Advisory. "
        "Payment terms are net 30 days upon satisfactory milestone acceptance. Liquidated damages of $1,000 per business day "
        "apply to unapproved milestone delivery delays exceeding 10 business days.",
        body_style
    ))
    story.append(Spacer(1, 8))

    # Section 6: Submission Instructions & Envelopes
    story.append(Paragraph("6. SUBMISSION INSTRUCTIONS & ENVELOPE SEPARATION", h2_style))
    story.append(Paragraph(
        "Submissions must be delivered electronically via the City of Edmonton Bonfire procurement portal. "
        "Proponents must submit their proposal as two strictly separate files: "
        "<br/>• <b>Envelope A (Technical Proposal):</b> Executive summary, compliance matrix, methodology, and resumes. No pricing information allowed. "
        "<br/>• <b>Envelope B (Financial Proposal):</b> Completed Schedule C Pricing Table, rate card, and commercial assumption notes.",
        body_style
    ))

    doc.build(story)
    return buffer.getvalue()


if __name__ == "__main__":
    b = generate_rfp_pdf_bytes()
    out_path = os.path.join(os.path.dirname(__file__), "phoenix_commissioning_rfp_coe.pdf")
    with open(out_path, "wb") as f:
        f.write(b)
    print(f"Generated Phoenix Commissioning RFP PDF: {out_path} ({len(b)} bytes)")
