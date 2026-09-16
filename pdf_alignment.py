"""
Proposal Alignment Audit Report PDF — Enable My Growth identity.

Deterministic report generator: renders an ALREADY-COMPUTED align_result
(the dict analyst.analyze_proposal_alignment() returns) to a PDF, in
memory, with no LLM calls, no re-analysis, and no modification of the
score/findings/coverage it is given. Isolated from every other PDF
generator in this codebase (pdf_export.py's compliance matrix,
pdf_styles.py's clarifications/proposal-review reports, pages_extra.py's
executive dashboard) -- it reuses only pdf_styles.py's shared, already
production-used design-system helpers (fonts, colours, cover_header,
make_footer, content_w), never their report-specific rendering
functions, so later Package 4 persistence work can decide independently
whether/how this specific report gets stored, without touching any
other report path.

Traceability discipline: every location/evidence string rendered here
comes verbatim from align_result (as already shown in the CHECK UI) --
if a field is empty, this renders "Not identified", never a fabricated
page number or citation.
"""
import io
from datetime import datetime

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                 TableStyle, KeepTogether, HRFlowable)
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER

from pdf_styles import (
    pp, safe, cover_header, make_footer, content_w, STYLES,
    C_NAVY, C_BLUE, C_BLUE_L, C_WHITE, C_BLACK, C_GREY_1, C_GREY_2, C_GREY_3, C_GREY_4,
    C_RED, C_AMBER, C_GREEN, ML, MR, MT, MB, _font,
)

_COVERAGE_COLOUR = {
    "Fully Addressed": C_GREEN, "Partially Addressed": C_AMBER,
    "Not Addressed": C_RED, "Cannot Assess": C_GREY_2,
}
_SEVERITY_COLOUR = {
    "Critical": C_RED, "High": C_AMBER, "Medium": C_BLUE, "Low": C_GREY_2,
}


def _not_identified(text) -> str:
    """Never fabricate a location/citation -- an empty evidence/location
    field renders exactly as 'Not identified', nothing invented."""
    text = (text or "").strip()
    return text if text else "Not identified"


def _section_bar(title: str, accent=C_BLUE):
    """Navy header bar, white bold text, coloured accent rule -- the
    same visual idiom pdf_export.py's compliance matrix already uses
    for its own category section headers, reproduced locally (not
    imported) to keep this generator fully isolated."""
    bar = Table(
        [[Paragraph(
            f'<font name="{_font("bold")}" color="#FFFFFF">{title.upper()}</font>',
            ParagraphStyle("sb", fontName=_font("bold"), fontSize=9, leading=12, textColor=C_WHITE)
        )]],
        colWidths=[content_w(True)]
    )
    bar.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), C_NAVY),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5 * mm),
        ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
        ("LINEABOVE", (0, 0), (-1, 0), 2, accent),
    ]))
    return bar


def _score_and_confidence_block(align_result: dict, cov: dict, is_complete: bool):
    """Section A -- score card (or the explicit no-score states) plus
    coverage/confidence metadata, matching the CHECK UI's own section A
    field-for-field."""
    o_score = align_result.get("overall_score")
    score_basis = align_result.get("score_basis") or ""
    recommendation = align_result.get("recommendation") or ""
    score_rationale = align_result.get("score_rationale") or ""

    if not is_complete:
        score_text = "—"
        rec_colour = C_RED
    elif o_score is None:
        score_text = "N/A"
        rec_colour = C_BLUE
    else:
        score_text = f"{o_score:.0f}/100"
        rec_colour = (
            C_GREEN if "SUBMIT" in recommendation
            else C_AMBER if "REVISE" in recommendation
            else C_BLUE if "NO EVALUATIVE CRITERIA" in recommendation
            else C_RED
        )

    score_style = ParagraphStyle("score_big", fontName=_font("bold"), fontSize=22,
                                  leading=26, textColor=rec_colour, alignment=TA_CENTER)
    rec_style = ParagraphStyle("score_rec", fontName=_font("semibold"), fontSize=8.5,
                                leading=11, textColor=C_BLACK, alignment=TA_CENTER)
    basis_style = ParagraphStyle("score_basis", fontName=_font("regular"), fontSize=7,
                                  leading=9, textColor=C_GREY_2, alignment=TA_CENTER)

    score_cell = [
        Paragraph("ALIGNMENT SCORE", ParagraphStyle("lbl", fontName=_font("semibold"),
                                                      fontSize=6.5, leading=8, textColor=C_GREY_2,
                                                      alignment=TA_CENTER)),
        Spacer(1, 1 * mm),
        Paragraph(score_text, score_style),
        Paragraph(safe(recommendation, 60) if recommendation else "—", rec_style),
        Paragraph(safe(score_basis, 80), basis_style),
    ]

    meta_lines = []
    if score_rationale:
        meta_lines.append(f"<b>Score Rationale:</b> {safe(score_rationale, 300)}")
    meta_lines.append(
        f"<b>Proposal coverage:</b> {cov.get('percentage_covered', 0)}% "
        f"({cov.get('chars_processed', 0):,}/{cov.get('chars_total', 0):,} characters analyzed, "
        f"{cov.get('successful_chunks', 0)}/{cov.get('chunk_count', 0)} sections)"
    )
    if cov.get("failed_or_skipped_chunks"):
        meta_lines.append(f"<b>Failed/skipped sections:</b> {cov.get('failed_or_skipped_chunks', 0)}")
    req_coverage = align_result.get("requirement_coverage") or []
    assessed = sum(1 for r in req_coverage if r.get("coverage") != "Cannot Assess")
    meta_lines.append(f"<b>Requirements assessed:</b> {assessed}/{len(req_coverage)}")

    meta_style = ParagraphStyle("meta_line", fontName=_font("regular"), fontSize=8,
                                 leading=12, textColor=C_BLACK, alignment=TA_LEFT)
    meta_cell = [Paragraph(line, meta_style) for line in meta_lines]

    cw = content_w(True)
    table = Table([[score_cell, meta_cell]], colWidths=[cw * 0.28, cw * 0.72])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), C_GREY_4),
        ("BOX", (0, 0), (0, 0), 0.75, rec_colour),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4 * mm),
        ("LEFTPADDING", (0, 0), (0, 0), 3 * mm),
        ("RIGHTPADDING", (0, 0), (0, 0), 3 * mm),
        ("LEFTPADDING", (1, 0), (1, 0), 6 * mm),
    ]))
    return table


def _partial_audit_summary_block(partial_summary: dict):
    """Deterministic Partial Audit Summary -- purely a render of already-
    computed structured fields (analyst._build_partial_audit_summary()),
    zero LLM calls. Distinguishes CONFIRMED coverage counts from genuine
    UNKNOWNS (Cannot Assess / unresolved mandatory-qualification items)."""
    if not partial_summary:
        return None
    ps = partial_summary
    lines = [
        f'<font name="{_font("bold")}" color="#{C_AMBER.hexval()[2:]}" size="10">{safe(ps.get("headline"), 200)}</font><br/>',
        f'<font size="8">📊 Coverage: <b>{ps.get("coverage_percentage", 0)}%</b> &nbsp;·&nbsp; '
        f'Sections analyzed: <b>{safe(ps.get("sections_analyzed"), 20)}</b> &nbsp;·&nbsp; '
        f'Failed: <b>{ps.get("sections_failed", 0)}</b> &nbsp;·&nbsp; '
        f'Ceiling-skipped: <b>{ps.get("sections_ceiling_skipped", 0)}</b></font><br/>',
        f'<font size="8">✅ Fully Addressed: <b>{ps.get("requirements_fully_addressed", 0)}</b> &nbsp;·&nbsp; '
        f'🟠 Partially Addressed: <b>{ps.get("requirements_partially_addressed", 0)}</b> &nbsp;·&nbsp; '
        f'❓ Cannot Assess: <b>{ps.get("requirements_cannot_assess", 0)}</b></font>',
    ]
    box = Table([[Paragraph("".join(lines), ParagraphStyle("partial_summary", fontName=_font("regular"),
                                                              fontSize=8, leading=12))]],
                colWidths=[content_w(True)])
    box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), C_GREY_4),
        ("BOX", (0, 0), (-1, -1), 0.75, C_AMBER),
        ("LINEBEFORE", (0, 0), (0, -1), 2.5, C_AMBER),
        ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
        ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
    ]))
    return box


def _priority_actions_section(priority_actions: list):
    """Priority Actions Before Submission -- deterministic, bounded
    (analyst._select_priority_actions(), max 10): established mandatory/
    qualification failures first, then Proposal-Submission-stage
    findings by severity. Never negotiation/execution/contractual-
    obligation items or Cannot-Assess unresolved items."""
    if not priority_actions:
        return None
    rows = [KeepTogether([_section_bar(f"Priority Actions Before Submission ({len(priority_actions)})", accent=C_RED)]),
            Spacer(1, 2 * mm)]
    for i, pa in enumerate(priority_actions, 1):
        sev = pa.get("severity", "Medium")
        sev_colour = _SEVERITY_COLOUR.get(sev, C_GREY_2)
        rec = pa.get("recommendation", "")
        body = (
            f'<font name="{_font("bold")}" color="#{sev_colour.hexval()[2:]}">#{i} · [{safe(sev, 12)}]</font> '
            f'<font name="{_font("semibold")}" size="8.5">{safe(pa.get("title"), 200)}</font><br/>'
            f'<font size="8">{safe(pa.get("detail"), 260)}</font>'
        )
        if rec:
            body += f'<br/><font size="7.5" color="#{C_GREEN.hexval()[2:]}">Recommendation: {safe(rec, 240)}</font>'
        box = Table([[Paragraph(body, ParagraphStyle("parow", fontName=_font("regular"), fontSize=8, leading=11))]],
                    colWidths=[content_w(True)])
        box.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), C_BLUE_L),
            ("LINEBEFORE", (0, 0), (0, -1), 2.5, sev_colour),
            ("BOX", (0, 0), (-1, -1), 0.5, C_GREY_3),
            ("TOPPADDING", (0, 0), (-1, -1), 2.5 * mm),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5 * mm),
            ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
        ]))
        rows.append(box)
        rows.append(Spacer(1, 1.5 * mm))
    return rows


def _unresolved_items_section(unresolved_items: list):
    """Needs Verification / Cannot Assess -- deliberately separate from
    Audit Findings: these are NOT established compliance defects, only
    requirements the package coverage couldn't confirm or deny."""
    if not unresolved_items:
        return None
    rows = [KeepTogether([_section_bar(f"Needs Verification / Cannot Assess ({len(unresolved_items)})", accent=C_GREY_2)]),
            Spacer(1, 2 * mm)]
    for u in unresolved_items:
        box = Table([[Paragraph(
            f'<font name="{_font("bold")}" color="#{C_GREY_1.hexval()[2:]}">'
            f'[{safe(u.get("req_id"), 20)}] {safe(u.get("category"), 30)}</font><br/>'
            f'<font size="8">{safe(u.get("reason"), 300)}</font>',
            ParagraphStyle("unresolved_row", fontName=_font("regular"), fontSize=8, leading=11)
        )]], colWidths=[content_w(True)])
        box.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), C_GREY_4),
            ("LINEBEFORE", (0, 0), (0, -1), 2.5, C_GREY_2),
            ("BOX", (0, 0), (-1, -1), 0.5, C_GREY_3),
            ("TOPPADDING", (0, 0), (-1, -1), 2.5 * mm),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5 * mm),
            ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
        ]))
        rows.append(box)
        rows.append(Spacer(1, 1.5 * mm))
    return rows


def _failed_section_diagnostics_block(diagnostics: list):
    """Sections Not Analyzed -- safe categories only (filename, section
    label, closed-vocabulary reason category). Never prompts, proposal
    text, or raw exception bodies. Visually distinguishes analysis-
    engine failures from package-ceiling budget limits."""
    if not diagnostics:
        return None
    lines = []
    for d in diagnostics:
        is_ceiling = d.get("category") == "beyond_analysis_ceiling"
        label = "Package ceiling" if is_ceiling else "Analysis engine"
        colour = C_GREY_2 if is_ceiling else C_RED
        lines.append(
            f'<font color="#{colour.hexval()[2:]}"><b>[{label}]</b></font> '
            f'{safe(d.get("filename") or "—", 80)} — {safe(d.get("section"), 100)} '
            f'<font color="#{C_GREY_2.hexval()[2:]}">({safe(d.get("category"), 40)})</font><br/>'
        )
    box = Table([[Paragraph("".join(lines), ParagraphStyle("diag", fontName=_font("regular"),
                                                              fontSize=7.5, leading=11))]],
                colWidths=[content_w(True)])
    box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), C_GREY_4),
        ("BOX", (0, 0), (-1, -1), 0.5, C_GREY_3),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5 * mm),
        ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
    ]))
    return box


def _mandatory_risks_section(mandatory_failures: list):
    if not mandatory_failures:
        return None
    rows = [KeepTogether([_section_bar("Mandatory / Qualification Risks", accent=C_RED)]), Spacer(1, 2 * mm)]
    for mf in mandatory_failures:
        box = Table([[Paragraph(
            f'<font name="{_font("bold")}" color="#{C_RED.hexval()[2:]}">'
            f'[{safe(mf.get("req_id"), 20)}] MANDATORY — NOT ADDRESSED</font><br/>'
            f'<font name="{_font("regular")}" size="8">{safe(mf.get("description"), 200)}</font><br/>'
            f'<font name="{_font("regular")}" size="7.5" color="#{C_GREY_1.hexval()[2:]}">'
            f'{safe(mf.get("reason"), 300)}</font>',
            ParagraphStyle("mfrow", fontName=_font("regular"), fontSize=8, leading=11)
        )]], colWidths=[content_w(True)])
        box.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), C_BLUE_L),
            ("BOX", (0, 0), (-1, -1), 0.5, C_RED),
            ("LINEBEFORE", (0, 0), (0, -1), 2.5, C_RED),
            ("TOPPADDING", (0, 0), (-1, -1), 2.5 * mm),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5 * mm),
            ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
        ]))
        rows.append(box)
        rows.append(Spacer(1, 1.5 * mm))
    return rows


def _findings_section(findings: list):
    if not findings:
        return None
    hdr = ["Sev", "Req ID", "Category", "Issue", "Location / Evidence", "Recommendation", "Effort"]
    raw_w = [10, 14, 18, 52, 42, 52, 20]
    scale = content_w(True) / sum(w * mm for w in raw_w)
    col_w = [w * mm * scale for w in raw_w]

    tdata = [[Paragraph(h, STYLES["col_hdr"]) for h in hdr]]
    for f in findings:
        sev = f.get("severity", "Medium")
        sev_colour = _SEVERITY_COLOUR.get(sev, C_GREY_2)
        tdata.append([
            Paragraph(f'<font color="#{sev_colour.hexval()[2:]}"><b>{safe(sev, 12)}</b></font>',
                      STYLES["cell_sm"]),
            pp(safe(f.get("req_id") or "—", 20), "cell_id"),
            pp(safe(f.get("category"), 30), "cell_sm"),
            pp(safe(f.get("issue"), 260), "cell"),
            pp(_not_identified(f.get("proposal_location")), "cell_sm"),
            pp(safe(f.get("recommendation"), 260), "cell_sm"),
            pp(safe(f.get("effort"), 30), "cell_sm"),
        ])

    t = Table(tdata, colWidths=col_w, repeatRows=1)
    ts = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), C_BLUE),
        ("TOPPADDING", (0, 0), (-1, 0), 2.5 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 2.5 * mm),
        ("LINEBELOW", (0, 0), (-1, 0), 1.5, C_NAVY),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 1), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 2.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, C_GREY_3),
        ("BOX", (0, 0), (-1, -1), 0.5, C_GREY_3),
    ])
    for i in range(1, len(tdata)):
        ts.add("BACKGROUND", (0, i), (-1, i), C_WHITE if i % 2 == 1 else C_BLUE_L)
    t.setStyle(ts)
    return t


def _coverage_matrix_section(requirement_coverage: list):
    if not requirement_coverage:
        return None
    hdr = ["Requirement", "Category", "Coverage", "Confidence", "Proposal Evidence / Location", "Gap / Action"]
    raw_w = [16, 20, 26, 18, 88, 88]
    scale = content_w(True) / sum(w * mm for w in raw_w)
    col_w = [w * mm * scale for w in raw_w]

    tdata = [[Paragraph(h, STYLES["col_hdr"]) for h in hdr]]
    for r in requirement_coverage:
        cov_state = r.get("coverage", "")
        cov_colour = _COVERAGE_COLOUR.get(cov_state, C_GREY_2)
        tdata.append([
            pp(safe(r.get("req_id"), 20), "cell_id"),
            pp(safe(r.get("category"), 30), "cell_sm"),
            Paragraph(f'<font color="#{cov_colour.hexval()[2:]}"><b>{safe(cov_state, 30)}</b></font>',
                      STYLES["cell_sm"]),
            pp(safe(r.get("confidence"), 15), "cell_sm"),
            pp(_not_identified(r.get("evidence_location")), "cell_sm"),
            pp(safe(r.get("notes"), 260), "cell_sm"),
        ])

    t = Table(tdata, colWidths=col_w, repeatRows=1)
    ts = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), C_BLUE),
        ("TOPPADDING", (0, 0), (-1, 0), 2.5 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 2.5 * mm),
        ("LINEBELOW", (0, 0), (-1, 0), 1.5, C_NAVY),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 1), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 2.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, C_GREY_3),
        ("BOX", (0, 0), (-1, -1), 0.5, C_GREY_3),
    ])
    for i in range(1, len(tdata)):
        ts.add("BACKGROUND", (0, i), (-1, i), C_WHITE if i % 2 == 1 else C_BLUE_L)
    t.setStyle(ts)
    return t


_LIFECYCLE_COLOUR = {
    "extracted": C_GREEN, "failed": C_RED, "unsupported": C_AMBER,
    "duplicate": C_GREY_2, "rejected": C_RED,
}
_LIFECYCLE_LABEL = {
    "extracted": "Included", "failed": "Failed", "unsupported": "Unsupported",
    "duplicate": "Duplicate", "rejected": "Rejected",
}


def _package_manifest_section(package_manifest: list, coverage_by_file: dict, skipped_file_ids: set):
    """Submission Package Manifest (instruction 9 / 11): one row per
    discovered file (whatever its status), plus summary counts -- exactly
    the same manifest the CHECK UI itself renders, so the PDF can never
    disagree with what the user saw on screen. `coverage_by_file` maps
    file_id -> that file's entry from align_result["coverage_metadata"]
    ["files"] (chars_processed/chunk_count as actually analyzed), when
    available. `skipped_file_ids` is align_result["coverage_metadata"]
    ["skipped_files"]'s file_ids -- an included, analyzable file that the
    package-wide chunk ceiling gave zero analyzed sections to; rendered
    with an explicit SKIPPED status rather than left to be inferred from
    a "0 sections" content count."""
    if not package_manifest:
        return None

    summary_counts = {
        "supplied": len(package_manifest),
        "included": sum(1 for f in package_manifest if f.get("included")),
        "excluded": sum(1 for f in package_manifest if not f.get("included")),
        "unsupported": sum(1 for f in package_manifest if f.get("lifecycle_status") == "unsupported"),
        "failed": sum(1 for f in package_manifest if f.get("lifecycle_status") == "failed"),
        "duplicate": sum(1 for f in package_manifest if f.get("lifecycle_status") == "duplicate"),
    }
    summary_line = pp(
        f"Files supplied: <b>{summary_counts['supplied']}</b>  ·  "
        f"Included: <b>{summary_counts['included']}</b>  ·  "
        f"Excluded: <b>{summary_counts['excluded']}</b>  ·  "
        f"Unsupported: <b>{summary_counts['unsupported']}</b>  ·  "
        f"Failed: <b>{summary_counts['failed']}</b>  ·  "
        f"Duplicates: <b>{summary_counts['duplicate']}</b>",
        "cell_sm"
    )

    hdr = ["File / Package Path", "Type", "Status", "Content Analyzed", "Notes"]
    raw_w = [70, 14, 24, 30, 82]
    scale = content_w(True) / sum(w * mm for w in raw_w)
    col_w = [w * mm * scale for w in raw_w]

    tdata = [[Paragraph(h, STYLES["col_hdr"]) for h in hdr]]
    for f in package_manifest:
        status = f.get("lifecycle_status", "")
        is_skipped_by_ceiling = f.get("file_id") in skipped_file_ids
        colour = C_RED if is_skipped_by_ceiling else _LIFECYCLE_COLOUR.get(status, C_GREY_2)
        label = "Skipped (ceiling)" if is_skipped_by_ceiling else _LIFECYCLE_LABEL.get(status, status or "Unknown")
        if not is_skipped_by_ceiling and status not in ("duplicate", "rejected") and not f.get("included", True):
            label = f"{label} (Excluded)"
        primary_tag = "  ⭐ Primary" if f.get("role") == "primary" else ""
        name_html = (
            f"{safe(f.get('filename'), 80)}{primary_tag}<br/>"
            f"<font size='6.5' color='#{C_GREY_2.hexval()[2:]}'>{safe(f.get('package_path'), 100)}</font>"
        )
        cov_entry = coverage_by_file.get(f.get("file_id")) or {}
        if cov_entry.get("chunk_count"):
            content_text = f"{cov_entry.get('chars_processed', 0):,}/{f.get('char_count', 0):,} chars ({cov_entry.get('chunk_count', 0)} sections)"
        elif f.get("char_count"):
            content_text = f"{f['char_count']:,} chars"
        else:
            content_text = "—"
        notes = f.get("unusable_reason") or (
            f"Duplicate of {safe(f.get('duplicate_of_file_id'), 40)}" if status == "duplicate" else ""
        )
        if is_skipped_by_ceiling:
            notes = "Not fully analyzed -- excluded by the package-wide chunk ceiling, not by content or user choice."
        tdata.append([
            Paragraph(name_html, STYLES["cell_sm"]),
            pp(safe((f.get("file_type") or "").upper(), 12), "cell_sm"),
            Paragraph(f'<font color="#{colour.hexval()[2:]}"><b>{safe(label, 40)}</b></font>', STYLES["cell_sm"]),
            pp(content_text, "cell_sm"),
            pp(safe(notes, 200), "cell_sm"),
        ])

    t = Table(tdata, colWidths=col_w, repeatRows=1)
    ts = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), C_BLUE),
        ("TOPPADDING", (0, 0), (-1, 0), 2.5 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 2.5 * mm),
        ("LINEBELOW", (0, 0), (-1, 0), 1.5, C_NAVY),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 1), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 2.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, C_GREY_3),
        ("BOX", (0, 0), (-1, -1), 0.5, C_GREY_3),
    ])
    for i in range(1, len(tdata)):
        ts.add("BACKGROUND", (0, i), (-1, i), C_WHITE if i % 2 == 1 else C_BLUE_L)
    t.setStyle(ts)
    return [summary_line, Spacer(1, 2 * mm), t]


def _next_steps_section(next_steps: list):
    if not next_steps:
        return None
    rows = []
    for step in sorted(next_steps, key=lambda x: x.get("priority", 99)):
        box = Table([[Paragraph(
            f'<font name="{_font("bold")}" color="#{C_BLUE.hexval()[2:]}">#{safe(step.get("priority"), 5)}</font> '
            f'<font name="{_font("semibold")}" size="8.5">{safe(step.get("action"), 200)}</font> '
            f'<font size="7" color="#{C_GREY_2.hexval()[2:]}">({safe(step.get("when"), 40)})</font><br/>'
            f'<font size="7.5" color="#{C_GREY_1.hexval()[2:]}">{safe(step.get("rationale"), 240)}</font>',
            ParagraphStyle("nsrow", fontName=_font("regular"), fontSize=8, leading=11)
        )]], colWidths=[content_w(True)])
        box.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), C_GREY_4),
            ("LINEBEFORE", (0, 0), (0, -1), 2.5, C_BLUE),
            ("BOX", (0, 0), (-1, -1), 0.5, C_GREY_3),
            ("TOPPADDING", (0, 0), (-1, -1), 2 * mm),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
            ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
        ]))
        rows.append(box)
        rows.append(Spacer(1, 1.5 * mm))
    return rows


def generate_alignment_audit_pdf(bid: dict, align_result: dict, proposal_filename: str = "",
                                  package_manifest: list | None = None) -> bytes:
    """Deterministic PDF render of an ALREADY-COMPUTED align_result (see
    analyst.analyze_proposal_alignment_package()). Makes no LLM calls,
    performs no re-analysis, and never modifies the score/findings/
    coverage it is given -- it only lays out what is already there,
    including the incomplete and zero-evaluation-universe cases exactly
    as the CHECK UI itself presents them.

    `package_manifest`, when supplied, is the Submission Package's file
    list AS AUDITED (extractor.build_alignment_submission_package()'s
    "files", a frozen snapshot taken at run time) -- renders the
    Submission Package Manifest section with per-file status/content/
    notes, cross-referenced against align_result["coverage_metadata"]
    ["files"] for actual chars-analyzed/chunk-count where available.
    Omitted or empty -> the manifest section is simply not rendered
    (keeps this function backward-compatible with any single-file
    align_result that carries no package/coverage_metadata.files)."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4),
        leftMargin=ML, rightMargin=MR, topMargin=MT, bottomMargin=MB + 8 * mm,
        title=f"Proposal Alignment Audit — {bid.get('client', '')}",
        author="Enable My Growth — Bid Intelligence",
    )
    footer = make_footer(
        f"{bid.get('client', '')}  ·  {bid.get('title', '')}  ·  Proposal Alignment & Compliance Audit",
        landscape_mode=True,
    )

    story = []
    cover_header(story, bid, "Proposal Alignment & Compliance Audit")

    # cover_header() already prints a DATE-level "Generated <date>" in its
    # shared meta line (used by every report built on pdf_styles.py, so
    # not changed here to avoid touching other, already-approved report
    # paths). This report additionally needs a full generated-AT
    # timestamp (date + time) -- added as its own line, isolated to this
    # generator only.
    story.append(pp(f"Report generated: {safe(datetime.now().strftime('%B %d, %Y at %I:%M %p'), 60)}", "meta"))
    story.append(Spacer(1, 2 * mm))

    if proposal_filename:
        story.append(pp(f"Proposal File: {safe(proposal_filename, 150)}", "meta"))
        story.append(Spacer(1, 2 * mm))

    story.append(pp(
        "Audit basis: assessed against the canonical procurement intelligence already extracted for "
        "this bid — applicable evaluation criteria, mandatory requirements, qualification gates, and "
        "commercial requirements — not a re-read of the physical tender documents during this run.",
        "note"
    ))
    story.append(Spacer(1, 3 * mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=C_GREY_3, spaceAfter=4 * mm))

    status = align_result.get("status")
    is_complete = status == "complete"
    cov = align_result.get("coverage_metadata") or {}

    # ── Submission Package Manifest ──────────────────────────────────────────
    if package_manifest:
        coverage_by_file = {f.get("file_id"): f for f in (cov.get("files") or [])}
        skipped_file_ids = {f.get("file_id") for f in (cov.get("skipped_files") or [])}
        story.append(_section_bar("Submission Package Manifest", accent=C_NAVY))
        story.append(Spacer(1, 2 * mm))
        story.extend(_package_manifest_section(package_manifest, coverage_by_file, skipped_file_ids))
        story.append(Spacer(1, 5 * mm))

    if not is_complete:
        story.append(Paragraph(
            f'<font name="{_font("bold")}" color="#{C_RED.hexval()[2:]}" size="11">'
            f'ALIGNMENT AUDIT INCOMPLETE — NO RELIABLE SCORE AVAILABLE</font>',
            ParagraphStyle("incomplete_hdr", fontName=_font("bold"), fontSize=11, leading=14)
        ))
        story.append(Spacer(1, 1.5 * mm))
        reason = align_result.get("reason") or align_result.get("message") or ""
        if reason:
            story.append(pp(safe(reason, 500), "note"))
        story.append(Spacer(1, 3 * mm))

        # ── Deterministic Partial Audit Summary (near the top for an
        # incomplete audit) -- zero LLM calls, purely structured.
        partial_block = _partial_audit_summary_block(align_result.get("partial_summary"))
        if partial_block:
            story.append(partial_block)
            story.append(Spacer(1, 4 * mm))

    # ── A. Alignment & confidence ────────────────────────────────────────────
    story.append(_score_and_confidence_block(align_result, cov, is_complete))
    story.append(Spacer(1, 5 * mm))

    if not is_complete:
        story.append(pp(
            "The findings and requirement coverage below reflect ONLY the proposal sections that were "
            "successfully analyzed before this audit was interrupted — this is a PARTIAL sample, not a "
            "complete scored audit.", "warn"
        ))
        story.append(Spacer(1, 4 * mm))

    # ── B. Executive Summary ─────────────────────────────────────────────────
    if is_complete:
        story.append(_section_bar("Executive Summary"))
        story.append(Spacer(1, 2 * mm))
        story.append(pp(safe(align_result.get("executive_summary"), 1500) or "Not available.", "cell"))
        story.append(Spacer(1, 5 * mm))

    # ── Priority Actions Before Submission ────────────────────────────────────
    priority_block = _priority_actions_section(align_result.get("priority_actions") or [])
    if priority_block:
        story.extend(priority_block)
        story.append(Spacer(1, 4 * mm))

    # ── C. Mandatory / Qualification Risks ───────────────────────────────────
    mandatory_block = _mandatory_risks_section(align_result.get("mandatory_failures") or [])
    if mandatory_block:
        story.extend(mandatory_block)
        story.append(Spacer(1, 4 * mm))

    # ── D. Audit Findings (renamed from "Critical Findings" -- contains
    # Critical, High, Medium, AND Low items, sorted in that order) ───────────
    findings = align_result.get("findings") or []
    findings_table = _findings_section(findings)
    if findings_table:
        sev_counts = {"Critical": 0, "High": 0, "Medium": 0, "Low": 0}
        for f in findings:
            sev_counts[f.get("severity", "Medium")] = sev_counts.get(f.get("severity", "Medium"), 0) + 1
        story.append(_section_bar(f"Audit Findings ({len(findings)})"))
        story.append(Spacer(1, 1.5 * mm))
        story.append(pp(
            f'Critical: <b>{sev_counts["Critical"]}</b>  ·  High: <b>{sev_counts["High"]}</b>  ·  '
            f'Medium: <b>{sev_counts["Medium"]}</b>  ·  Low: <b>{sev_counts["Low"]}</b>',
            "note"
        ))
        story.append(Spacer(1, 2 * mm))
        story.append(findings_table)
        story.append(Spacer(1, 5 * mm))

    # ── Needs Verification / Cannot Assess ────────────────────────────────────
    unresolved_block = _unresolved_items_section(align_result.get("unresolved_items") or [])
    if unresolved_block:
        story.extend(unresolved_block)
        story.append(Spacer(1, 4 * mm))

    # ── Sections Not Analyzed (failed / ceiling-skipped diagnostics) ─────────
    diagnostics_block = _failed_section_diagnostics_block(cov.get("failed_chunk_diagnostics") or [])
    if diagnostics_block:
        story.append(_section_bar("Sections Not Analyzed", accent=C_GREY_2))
        story.append(Spacer(1, 2 * mm))
        story.append(diagnostics_block)
        story.append(Spacer(1, 4 * mm))

    # ── E. Requirement Coverage Matrix ───────────────────────────────────────
    req_coverage = align_result.get("requirement_coverage") or []
    coverage_table = _coverage_matrix_section(req_coverage)
    if coverage_table:
        story.append(_section_bar(f"Requirement Coverage ({len(req_coverage)})"))
        story.append(Spacer(1, 2 * mm))
        story.append(coverage_table)
        story.append(Spacer(1, 5 * mm))

    # ── F. Strengths ──────────────────────────────────────────────────────────
    strengths = align_result.get("strengths") or []
    if is_complete and strengths:
        story.append(_section_bar("Strengths", accent=C_GREEN))
        story.append(Spacer(1, 2 * mm))
        for s in strengths:
            story.append(pp(f"✓  {safe(s, 300)}", "cell"))
        story.append(Spacer(1, 5 * mm))

    # ── G. Prioritized Next Steps ─────────────────────────────────────────────
    next_steps = align_result.get("next_steps") or []
    if is_complete and next_steps:
        story.append(_section_bar("Prioritized Next Steps"))
        story.append(Spacer(1, 2 * mm))
        story.extend(_next_steps_section(next_steps))

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
