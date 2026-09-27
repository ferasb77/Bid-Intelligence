"""
check_assurance_report.py -- CHECK-2D: concise, client-ready Proposal
Assurance Report (PDF) for one durable CHECK run.

PURE PRESENTATION. The content comes entirely from
components/check_report_model.build_report_model() -- a deterministic
selection over the persisted CHECK adjudications. This module never imports
check_coverage.py / check_run_service.py / tenancy / database / a provider
SDK, never calls a model and never writes anything. The caller
(tenancy.export_check_assurance_report_for_organization) does the authorized,
read-only reads and hands the persisted objects in.

Rendering reuses the shared Bid Intelligence report stack exactly like
MA-2C's full_analysis_report.py: scripts/build_boc_bid_intelligence_preview_pdf
(reportlab platypus flow, registered brand fonts, colour tokens, dark cover,
table styling) plus MA-2C's banner / table / section helpers.
"""
from __future__ import annotations

import io
import unicodedata

from reportlab.lib.colors import HexColor
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate, CondPageBreak, Frame, KeepTogether, NextPageTemplate, PageBreak, PageTemplate, Spacer, Table,
    TableStyle,
)

import full_analysis_report as far
import scripts.build_boc_bid_intelligence_preview_pdf as base
from components import check_report_model as crm

NIGHT, INK, GOLD, MUTED, RULE, PAPER, BAND = base.NIGHT, base.INK, base.GOLD, base.MUTED, base.RULE, base.PAPER, \
    base.BAND
PAGE_W, PAGE_H, MARGIN = base.PAGE_W, base.PAGE_H, base.MARGIN
BODY_W = PAGE_W - 2 * MARGIN
S = base.styles
Paragraph = far.Paragraph  # <b> -> brand medium face

ReportNotExportableError = crm.ReportNotExportableError

#: Status text colours. The status is always also written out as text.
STATUS_COLOR = {
    crm.ADDRESSED: "#2E7D4F", crm.PARTIAL: "#9A6A12", crm.NOT_ADDRESSED: "#A93226",
    crm.NOT_VERIFIABLE: "#4F5F7A", crm.HUMAN_REVIEW: "#6B4FA0", crm.NOT_APPLICABLE: "#6B675F",
}

_st = {
    "cell": ParagraphStyle("ck_cell", fontName="Body", fontSize=8.0, leading=10.8, textColor=INK),
    "cell_b": ParagraphStyle("ck_cell_b", fontName="BodyMed", fontSize=8.0, leading=10.8, textColor=INK),
    "cell_x": ParagraphStyle("ck_cell_x", fontName="Body", fontSize=7.4, leading=9.6, textColor=INK),
    "cell_s": ParagraphStyle("ck_cell_s", fontName="Body", fontSize=7.4, leading=9.8, textColor=MUTED),
    "f_title": ParagraphStyle("ck_f_title", fontName="BodyMed", fontSize=10, leading=13.4, textColor=INK,
                              spaceAfter=3),
    "f_body": ParagraphStyle("ck_f_body", fontName="Body", fontSize=8.7, leading=12.2, textColor=INK,
                             spaceAfter=3),
    "f_meta": ParagraphStyle("ck_f_meta", fontName="Body", fontSize=7.9, leading=10.8, textColor=MUTED,
                             spaceAfter=2),
    "f_label": ParagraphStyle("ck_f_label", fontName="BodyMed", fontSize=7.4, leading=9.6, textColor=GOLD,
                              spaceBefore=3, spaceAfter=1),
    "el": ParagraphStyle("ck_el", fontName="Body", fontSize=8.1, leading=11, textColor=INK, leftIndent=8,
                         firstLineIndent=-8, spaceAfter=1.5),
    "count_n": ParagraphStyle("ck_count_n", fontName="BodyMed", fontSize=13, leading=15, textColor=INK),
    "cover_title": ParagraphStyle("ck_cover_title", parent=S["cover_title"], fontSize=29, leading=34),
}

# ═══════════════════════════════════════════════════════════════════════
# Text safety: brand fonts cover a Latin subset. Characters outside it are
# mapped to plain equivalents (never silently rendered as empty boxes).
# ═══════════════════════════════════════════════════════════════════════

_FALLBACK = {
    "‑": "-", "‐": "-", "‒": "-", "−": "-", "­": "",
    "●": "•", "○": "-", "▪": "•", "■": "•", "◦": "-",
    "►": ">", "▶": ">", "◄": "<", "◀": "<", "▼": "v", "▲": "^",
    "─": "-", "━": "-", "│": "|", "┃": "|", "└": "+", "┘": "+", "┌": "+",
    "┐": "+", "├": "+", "┤": "+", "┬": "+", "┴": "+", "┼": "+",
    "→": "->", "←": "<-", "✓": "", "✔": "", "✕": "x", "✗": "x", "�": "?",
    "​": "", "﻿": "", "\t": " ",
}


def _font_chars() -> set:
    try:
        from reportlab.pdfbase import pdfmetrics
        return set(pdfmetrics.getFont("Body").face.charToGlyph)
    except Exception:  # pragma: no cover - fonts are registered by `base` at import
        return set()


_CHARS = _font_chars()


def safe(value) -> str:
    out = []
    for ch in str(value if value is not None else ""):
        if ch in _FALLBACK:
            out.append(_FALLBACK[ch])
        elif ch in ("\n", "\r"):
            out.append(" ")
        elif not _CHARS or ord(ch) < 128 or ord(ch) in _CHARS:
            out.append(ch)
        else:
            plain = unicodedata.normalize("NFKD", ch).encode("ascii", "ignore").decode("ascii")
            out.append(plain or "?")
    return "".join(out)


def t(value) -> str:
    """Persisted text -> escaped, font-safe Paragraph markup."""
    return far.esc(safe(value))


def tag(status: str, *, size: float = 7.4) -> str:
    color = STATUS_COLOR.get(status, "#6B675F")
    return f'<font color="{color}" size="{size}"><b>{t(crm.STATUS_TAG.get(status, status))}</b></font>'


def cites_text(refs, more: int = 0) -> str:
    if not refs:
        return ""
    s = ", ".join(refs)
    if more:
        s += f" +{more} more"
    return f'<font color="#B5924F">[{t(s)}]</font>'


# ═══════════════════════════════════════════════════════════════════════
# Building blocks (MA-2C's table / section helpers, compact variants)
# ═══════════════════════════════════════════════════════════════════════

def table(header, rows, widths, *, header_bg=NIGHT, pad=4, cell_style=None):
    data = [[Paragraph(t(h), S["table_head"]) for h in header]]
    for r in rows:
        data.append([c if not isinstance(c, str) else Paragraph(c, cell_style or _st["cell"]) for c in r])
    tb = Table(data, colWidths=widths, repeatRows=1)
    tb.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), header_bg),
        ("TOPPADDING", (0, 0), (-1, -1), pad), ("BOTTOMPADDING", (0, 0), (-1, -1), pad),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 1), (-1, -1), 0.5, RULE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [PAPER, BAND]),
    ]))
    return tb


def _section(story, num: int, title: str, blurb: str | None = None, *, new_page: bool = True):
    if new_page:
        story.append(PageBreak())
    else:
        # Start on a new page only when too little room is left for the
        # heading plus the first rows of its content (no orphan headings).
        story.append(CondPageBreak(2.4 * inch))
        story.append(Spacer(1, 10))
    head = [Paragraph(f"SECTION {num}", S["section_kicker"]), Paragraph(t(title), S["h1"]),
            base.hr(GOLD, 1.1, 0, 8)]
    if blurb:
        head.append(Paragraph(t(blurb), S["note"]))
    return head


def _applies_text(f: dict) -> str:
    parts = []
    for m in f["applies_to"]:
        facts = []
        if m["weight"]:
            facts.append(f"buyer weight {m['weight']}")
        if m["threshold"]:
            facts.append(f"minimum threshold {m['threshold']}")
        if not m["is_criterion"]:
            kind = (m.get("category") or "").strip()
            facts.append(f"{kind.lower()} requirement" if kind else "requirement")
        else:
            facts.append("evaluation criterion")
        parts.append(f"<b>{t(m['name'])}</b> ({t(', '.join(facts))}; {t(m['status_label'].lower())})")
    return "; ".join(parts)


def _sources_text(f: dict) -> str:
    return "; ".join(t(crm.source_line(s)) for s in f["buyer_sources"]) or "No buyer source reference was persisted."


def _evidence_line(f: dict, cite_labels: dict) -> str | None:
    if not f["evidence"]:
        return None
    items = [f'<font color="#B5924F">{t(r)}</font> {t(cite_labels.get(r, ""))}' for r in f["evidence"]]
    more = f"; +{f['more_evidence']} further cited item(s)" if f["more_evidence"] else ""
    return "<b>Bidder evidence:</b> " + "; ".join(items) + t(more)


def _element_para(el: dict, *, bullet: str = "•") -> object:
    tail = []
    if el.get("coverage_label"):
        tail.append(f'<font color="#6B675F">({t(el["coverage_label"].lower())})</font>')
    c = cites_text(el.get("cites"), el.get("more_cites") or 0)
    if c:
        tail.append(c)
    return Paragraph(f"{bullet} {t(el['element'])}" + (" " + " ".join(tail) if tail else ""), _st["el"])


def _block(inner: list, color) -> Table:
    # splitInRow: a long block continues on the next page instead of leaving
    # a large blank area (reportlab >= 3.6).
    tb = Table([[inner]], colWidths=[BODY_W], splitInRow=1)
    tb.setStyle(TableStyle([
        ("LINEBEFORE", (0, 0), (0, -1), 2, color),
        ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return tb


def _finding_head(f: dict) -> list:
    return [Paragraph(f'<font color="#B5924F">{t(f["ref"])}</font>&nbsp;&nbsp;{tag(f["status"])}'
                      f'&nbsp;&nbsp;{t(f["title"])}', _st["f_title"]),
            Paragraph("<b>Applies to:</b> " + _applies_text(f), _st["f_meta"])]


def partial_flowables(f: dict, cite_labels: dict, lead: list | None = None) -> list:
    """Buyer expected / Demonstrated / Not demonstrated / Evidence."""
    color = HexColor(STATUS_COLOR[crm.PARTIAL])
    top = _finding_head(f) + [
        Paragraph("BUYER EXPECTED", _st["f_label"]),
        Paragraph(t(f["expectation"]), _st["f_body"]),
        Paragraph("<b>Buyer source:</b> " + _sources_text(f), _st["f_meta"]),
    ]
    for note in f["weight_notes"]:
        top.append(Paragraph(t(note), _st["f_meta"]))
    dem, miss = f["demonstrated"], f["not_demonstrated"]
    half = (BODY_W - 9) / 2
    head = [Paragraph(f'<font color="#2E7D4F"><b>DEMONSTRATED ({len(dem)})</b></font>', _st["f_label"]),
            Paragraph(f'<font color="#9A6A12"><b>NOT DEMONSTRATED ({len(miss)})</b></font>', _st["f_label"])]
    # One row per column (each column an independent list), so a long item in
    # one column never opens a gap in the other. The status rule is drawn on
    # the narrow first column.
    left = [_element_para(el) for el in dem] or [Paragraph("None recorded.", _st["cell_s"])]
    right = [_element_para(el) for el in miss] or [Paragraph("None.", _st["cell_s"])]
    grid = Table([["", head[0], head[1]], ["", left, right]], colWidths=[9, half, half], repeatRows=1,
                 splitInRow=1)
    grid.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LINEBELOW", (1, 0), (-1, 0), 0.5, RULE),
        ("LINEBEFORE", (0, 0), (0, -1), 2, color),
    ]))
    tail = []
    if f["unverifiable"]:
        tail.append(Paragraph("NOT VERIFIABLE FROM THE SUBMITTED FILES", _st["f_label"]))
        tail += [_element_para(el) for el in f["unverifiable"]]
    has_element_cites = any(el.get("cites") for el in dem + miss + f["unverifiable"])
    ev = None if has_element_cites else _evidence_line(f, cite_labels)
    if ev:
        tail.append(Spacer(1, 3))
        tail.append(Paragraph(ev, _st["f_meta"]))
    # Header + buyer expectation stay together with the first element rows;
    # the element grid itself may continue across a page by whole rows.
    # The finding header, buyer expectation and the start of the
    # demonstrated / not-demonstrated comparison begin on the same page (no
    # orphaned finding header); the comparison may then continue by line.
    top_block = _block(top, color)
    need = sum(x.wrap(BODY_W, PAGE_H)[1] for x in list(lead or []) + [top_block]) + 1.1 * inch
    out = [CondPageBreak(need), *(lead or []), top_block, grid]
    if tail:
        out.append(_block(tail, color))
    return out + [Spacer(1, 12)]


def review_flowable(f: dict, cite_labels: dict):
    color = HexColor(STATUS_COLOR.get(f["status"], "#6B675F"))
    parts = _finding_head(f)
    parts += [Paragraph("BUYER REQUIREMENT", _st["f_label"]),
              Paragraph(t(f["expectation"]) if f["expectation"] else
                        "The canonical buyer object carries no wording.", _st["f_body"]),
              Paragraph("<b>Buyer source:</b> " + _sources_text(f), _st["f_meta"])]
    ev = _evidence_line(f, cite_labels)
    parts.append(Paragraph("EVIDENCE FOUND", _st["f_label"]))
    parts.append(Paragraph(ev if ev else "No bidder evidence was cited for this finding.", _st["f_meta"]))
    if f["demonstrated"]:
        parts += [_element_para(el) for el in f["demonstrated"]]
    parts.append(Paragraph("WHY CHECK DID NOT MAKE A DEFINITIVE JUDGMENT", _st["f_label"]))
    reasons = f["reasons"] or [crm.STATUS_DEFINITION[crm.HUMAN_REVIEW]]
    parts += [Paragraph("• " + t(r), _st["el"]) for r in reasons]
    if f["reviewer_checks"]:
        parts.append(Paragraph("WHAT A REVIEWER SHOULD CONFIRM (FROM THE RECORDED REVIEW REASON)", _st["f_label"]))
        parts += [Paragraph("• Whether the submission meets: " + t(x), _st["el"]) for x in f["reviewer_checks"]]
    return _block(parts, color)


# ═══════════════════════════════════════════════════════════════════════
# Page chrome
# ═══════════════════════════════════════════════════════════════════════

def _on_body(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.6)
    canvas.line(MARGIN, PAGE_H - 0.62 * inch, PAGE_W - MARGIN, PAGE_H - 0.62 * inch)
    canvas.setFont("BodyMed", 7.6)
    canvas.setFillColor(MUTED)
    label = "PARTIAL PROPOSAL ASSURANCE REPORT" if getattr(doc, "_ck_partial", False) else "PROPOSAL ASSURANCE REPORT"
    if getattr(doc, "_ck_partial", False):
        canvas.setFillColor(far.AMBER)
    canvas.drawString(MARGIN, PAGE_H - 0.52 * inch, label)
    canvas.setFillColor(MUTED)
    canvas.setFont("Body", 7.6)
    canvas.drawRightString(PAGE_W - MARGIN, PAGE_H - 0.52 * inch, getattr(doc, "_ck_header", "") or "")
    canvas.line(MARGIN, 0.62 * inch, PAGE_W - MARGIN, 0.62 * inch)
    canvas.drawString(MARGIN, 0.44 * inch, getattr(doc, "_ck_footer", "") or "")
    canvas.setFont("BodyMed", 8)
    canvas.setFillColor(GOLD)
    canvas.drawRightString(PAGE_W - MARGIN, 0.44 * inch, str(canvas.getPageNumber() - 1))
    canvas.restoreState()


def _emit(story, head, blocks):
    """Heading followed by its content. _section() already guaranteed room
    for the heading plus the first part of its content (CondPageBreak), and
    every block can continue across a page (tables by row, finding blocks by
    line), so nothing is pushed wholesale to the next page."""
    story.extend(head)
    story.extend(blocks)


# ═══════════════════════════════════════════════════════════════════════
# PDF
# ═══════════════════════════════════════════════════════════════════════

def render_pdf(model: dict) -> bytes:
    ident, run, ov = model["identity"], model["run"], model["overview"]
    buf = io.BytesIO()
    header = " · ".join(x for x in (ident.get("buyer"), f"RFP {ident['rfp_id']}" if ident.get("rfp_id") else None)
                        if x)
    doc = BaseDocTemplate(buf, pagesize=base.LETTER, leftMargin=MARGIN, rightMargin=MARGIN,
                          topMargin=MARGIN, bottomMargin=MARGIN,
                          title=f"{model['title']} — {header}" if header else model["title"],
                          author="Bid Intelligence", invariant=1)
    doc._ck_header = safe(header)
    doc._ck_partial = model["is_partial"]
    doc._ck_footer = safe(f"Confidential · CHECK run {run.get('run_id')} · rendered from the saved assurance run, "
                          "not an evaluation score")
    doc.addPageTemplates([
        PageTemplate(id="Cover", frames=[Frame(MARGIN, 0, BODY_W, PAGE_H, id="cover")], onPage=base.on_cover),
        PageTemplate(id="Body", frames=[Frame(MARGIN, MARGIN, BODY_W, PAGE_H - 2 * MARGIN - 0.15 * inch,
                                              id="body")], onPage=_on_body),
    ])
    cite_labels = {c["ref"]: f"{c['role_label']}, {c['short_location']}" for c in model["citations"]}
    findings = {f["ref"]: f for f in model["attention"]}
    story = []

    # ── Cover ──
    story.append(Spacer(1, 2.05 * inch))
    story.append(Paragraph(t(model["title"].upper()), S["cover_kicker"]))
    story.append(Spacer(1, 6))
    story.append(Paragraph(t(ident.get("title") or ident.get("buyer") or "Procurement"), _st["cover_title"]))
    if ident.get("buyer"):
        story.append(Paragraph(t(ident["buyer"]), S["cover_sub1"]))
    sub = []
    if ident.get("rfp_id"):
        sub.append(f"RFP {t(ident['rfp_id'])}")
    if run.get("run_id") is not None:
        sub.append(f"CHECK run {t(run['run_id'])}")
    if run.get("assessed_date"):
        sub.append(f"Assessed {t(run['assessed_date'])}")
    if sub:
        story.append(Paragraph(" · ".join(sub), S["cover_sub2"]))
    nfiles = len(model["files"])
    if nfiles:
        story.append(Paragraph(f"Submission assessed: {nfiles} submitted file{'s' if nfiles != 1 else ''}"
                               + (f" (package snapshot {t(run['package_snapshot_id'])})"
                                  if run.get("package_snapshot_id") is not None else ""), S["cover_sub2"]))
    status_txt = ('<font color="#E0A84A">PARTIAL — NOT COMPLETE ASSURANCE</font>' if model["is_partial"]
                  else '<font color="#7FBF94">COMPLETE</font>')
    story.append(Spacer(1, 10))
    story.append(Paragraph(f"CHECK run status: {status_txt}", far._st["cover_status"]))
    story.append(NextPageTemplate("Body"))

    sec = 0
    # ── 1. Assurance overview ──
    sec += 1
    head = _section(story, sec, "Assurance Overview",
                    "What was assessed, and the factual picture across every buyer requirement and evaluation "
                    "criterion.")
    blocks = []
    if model["is_partial"]:
        blocks += [far.banner(model["partial_lines"] or ["Some adjudication stages did not complete."], "caution",
                              "PARTIAL CHECK RUN — THIS IS NOT COMPLETE ASSURANCE"), Spacer(1, 8)]
    if not run.get("digest_verified", True):
        blocks += [far.banner(["The saved CHECK result did not pass its integrity digest check. Treat this report "
                               "with caution."], "error", "INTEGRITY CHECK NOT PASSED"), Spacer(1, 8)]
    facts = [("Buyer", ident.get("buyer")), ("Procurement", ident.get("title")), ("RFP identifier", ident.get("rfp_id")),
             ("Submission assessed", (f"{nfiles} submitted file{'s' if nfiles != 1 else ''}: "
                                      + "; ".join(f"{f['role_label']}" for f in model["files"])) if nfiles else None),
             ("CHECK run", f"Run {run.get('run_id')} · {run.get('status_label')}"),
             ("Assessment date", run.get("assessed_date"))]
    blocks.append(base.fact_card_table([(k, t(v)) for k, v in facts if v],
                                       col_widths=(1.55 * inch, BODY_W - 1.55 * inch)))
    blocks.append(Spacer(1, 10))
    rows = []
    for c in ov["counts"]:
        rows.append([Paragraph(t(str(c["count"])), _st["count_n"]), tag(c["status"], size=8),
                     Paragraph(t(c["definition"]), _st["cell_s"])])
    blocks.append(Paragraph(f"Status of {ov['total'] - ov['non_submission']} proposal-assurance buyer objects",
                            S["h2"]))
    blocks.append(table(["Count", "Status", "Meaning"], rows, [0.7 * inch, 1.75 * inch, BODY_W - 2.45 * inch]))
    blocks.append(Spacer(1, 6))
    blocks.append(Paragraph(
        f"Separately, <b>{ov['non_submission']}</b> buyer object{'s' if ov['non_submission'] != 1 else ''} "
        "are outside proposal-assurance scope (buyer process, post-award, informational or deemed by "
        "submission) and are not proposal gaps (Section 7 lists them). In total the buyer package holds "
        f"{ov['total']} objects: {ov['requirements']} requirements and {ov['criteria']} scoped evaluation criteria.",
        S["body_tight"]))
    blocks.append(Paragraph(
        "These are counts of factual CHECK outcomes, not a score. CHECK does not calculate an overall or compliance "
        "percentage and does not predict how an evaluator will score this proposal.", S["note"]))
    _emit(story, head, blocks)

    # ── 2. Evaluation criteria ──
    sec += 1
    crit = model["criteria"]
    head = _section(story, sec, "Evaluation Criteria Overview",
                    f"All {len(crit)} scoped evaluation criteria, items needing attention first. Buyer weight and "
                    "threshold are the buyer's published metadata, not predicted marks.")
    rows = []
    for c in crit:
        w = t(c["weight"]) if c["weight"] else '<font color="#6B675F">None stated</font>'
        if c["threshold"]:
            w += f"<br/>Min. threshold {t(c['threshold'])}"
        if c["weight_variants_differ"]:
            w += '<br/><font color="#6B675F" size="7">buyer sources differ</font>'
        concl = t(c["conclusion"])
        if c["evidence"]:
            concl += " " + cites_text(c["evidence"])
        rows.append([f"<b>{t(c['name'])}</b>", w, tag(c["status"]), t(c["expectation"]), concl])
    blocks = [table(["Criterion", "Buyer weight", "CHECK status", "Buyer expectation", "Assurance conclusion"], rows,
                    [1.3 * inch, 0.75 * inch, 0.95 * inch, 1.75 * inch, BODY_W - 4.75 * inch])]
    _emit(story, head, blocks)

    # ── 3. Attention findings ──
    sec += 1
    att = model["attention"]
    head = _section(story, sec, "Findings Requiring Attention", model["attention_ordering"], new_page=False)
    section_of = {crm.PARTIAL: "Section 3", crm.HUMAN_REVIEW: "Section 4", crm.NOT_VERIFIABLE: "Section 5",
                  crm.NOT_ADDRESSED: "Section 5"}
    rows = []
    for f in att:
        applies = "; ".join(m["name"] + (f" ({m['weight']})" if m["weight"] else "") for m in f["applies_to"])
        rows.append([f'<font color="#B5924F"><b>{t(f["ref"])}</b></font>', t(crm.clip(f["title"], 80)), t(applies),
                     tag(f["status"]), t(section_of.get(f["status"], ""))])
    blocks = []
    if rows:
        blocks.append(table(["Ref", "Finding", "Applies to (buyer weight)", "Status", "Detail"], rows,
                            [0.4 * inch, 2.35 * inch, 2.0 * inch, 1.3 * inch, BODY_W - 6.05 * inch]))
    else:
        blocks.append(Paragraph("No finding needs attention: nothing is partially addressed, not addressed, "
                                "unverifiable or awaiting human review.", S["note"]))
    partials = [findings[r] for r in model["partials"]]
    lead = []
    if partials:  # kept on the same page as the first partial finding (no orphan heading)
        lead = [Paragraph(f"Partially Addressed ({len(partials)})", S["h2"]),
                Paragraph("Each finding compares what the buyer expected with the elements the submission "
                          "demonstrates and those it does not. Bracketed references [E#] point to the "
                          "evidence appendix.", S["note"])]
    _emit(story, head, blocks)
    for i, f in enumerate(partials):
        story.extend(partial_flowables(f, cite_labels, lead if i == 0 else None))

    # ── 4. Human review ──
    sec += 1
    hr_items = [findings[r] for r in model["human_review"]]
    head = _section(story, sec, "Human Review Required",
                    "CHECK did not make a definitive judgment on these items. They are not confirmed weaknesses; a "
                    "person should confirm them.", new_page=False)
    blocks = [x for f in hr_items for x in (review_flowable(f, cite_labels), Spacer(1, 10))] or [
        Paragraph("No finding requires human review.", S["note"])]
    _emit(story, head, blocks)

    # ── 5. Not verifiable / not addressed ──
    sec += 1
    nv = [findings[r] for r in model["not_verifiable"]]
    head = _section(story, sec, "Not Verifiable from the Submitted Files & Not Addressed",
                    "Not verifiable means the submitted files cannot show whether the item is met (for example, it "
                    "is answered in the buyer's portal). It is a limit of file-based assurance, not missing proposal "
                    "content.", new_page=False)
    blocks = []
    if nv:
        rows = []
        for f in nv:
            applies = "; ".join(m["name"] + (f" ({m['weight']})" if m["weight"] else "") for m in f["applies_to"])
            why = "<br/>".join(t(r) for r in f["unverifiable_reasons"]) or                 t(crm.STATUS_DEFINITION[crm.NOT_VERIFIABLE])
            ev = (" " + cites_text(f["evidence"], f["more_evidence"])) if f["evidence"] else ""
            rows.append([f'<font color="#B5924F"><b>{t(f["ref"])}</b></font><br/>{t(applies)}',
                         t(crm.clip(f["expectation"], 230)),
                         why + ev,
                         f'<font size="7.2" color="#6B675F">{_sources_text(f)}</font>'])
        blocks.append(Paragraph(f"Not Verifiable from the Submitted Files ({len(nv)})", S["h2"]))
        blocks.append(table(["Ref / applies to", "Buyer expectation", "Why it cannot be verified from the files",
                             "Buyer source"], rows,
                            [1.15 * inch, 2.0 * inch, 2.25 * inch, BODY_W - 5.4 * inch]))
    else:
        blocks.append(Paragraph("No finding is limited by what the submitted files can show.", S["note"]))
    na = [findings[r] for r in model["not_addressed"]]
    blocks.append(Paragraph(f"Not Addressed ({len(na)})", S["h2"]))
    if na:
        rows = [[f'<font color="#B5924F"><b>{t(f["ref"])}</b></font>', t(f["title"]), t(f["expectation"]),
                 _sources_text(f)] for f in na]
        blocks.append(table(["Ref", "Buyer object", "Buyer expectation", "Buyer source"], rows,
                            [0.45 * inch, 1.6 * inch, 2.9 * inch, BODY_W - 4.95 * inch]))
    else:
        blocks.append(Paragraph("CHECK recorded no buyer requirement or evaluation criterion as not addressed in "
                                "this run.", S["body_tight"]))
    _emit(story, head, blocks)

    # ── 6. Mandatory requirements evidenced ──
    sec += 1
    mand = model["mandatory_addressed"]
    head = _section(story, sec, "Addressed Mandatory Requirements — Where the Submission Responded",
                    "Mandatory and submission-wide buyer requirements the submitted files demonstrate, with the "
                    "bidder evidence CHECK relied on. Shown for traceability; they need no action.", new_page=False)
    rows = []
    for r in mand:
        ev = cites_text(r["evidence"], r["more_evidence"]) or '<font color="#6B675F">—</font>'
        where = "<br/>".join(t(cite_labels.get(x, "")) for x in r["evidence"])
        summ = t(r["summary"]) if r["summary"] else ""
        if r["unverifiable_elements"]:
            n = r["unverifiable_elements"]
            summ += (" " if summ else "") + t(f"{n} further element{'s' if n != 1 else ''} cannot be verified "
                                               "from the files.")
        rows.append([f"<b>{t(r['object_id'])}</b>", t(r["expectation"]), summ or '<font color="#6B675F">—</font>',
                     f"{ev}<br/><font size='7.2' color='#6B675F'>{where}</font>"])
    blocks = [table(["Req.", "Buyer requirement", "What CHECK found", "Evidence"], rows,
                    [0.62 * inch, 2.38 * inch, 2.0 * inch, BODY_W - 5.0 * inch])] if rows else [
        Paragraph("No mandatory requirement is recorded as addressed.", S["note"])]
    _emit(story, head, blocks)

    # ── 7. Non-submission ──
    sec += 1
    head = _section(story, sec, "Outside Proposal-Assurance Scope",
                    "Buyer objects the scope rules classified as not being proposal obligations. They are never "
                    "counted as proposal gaps.", new_page=False)
    rows = [[f"<b>{t(g['scope_label'])}</b>", t(str(g["count"])), t(", ".join(g["ids"]))]
            for g in model["non_submission"]]
    blocks = [table(["Classification", "Count", "Buyer objects"], rows,
                    [2.2 * inch, 0.6 * inch, BODY_W - 2.8 * inch])] if rows else [
        Paragraph("None.", S["note"])]
    _emit(story, head, blocks)

    # ── 8. Evidence appendix ──
    sec += 1
    head = _section(story, sec, "Evidence Appendix",
                    "The submitted artifacts CHECK assessed, and every bidder evidence reference cited in this "
                    "report. Excerpts are bounded; the full record is in the CHECK workspace.")
    blocks = []
    if model["files"]:
        rows = []
        for f in model["files"]:
            size = (f"{f['page_count']} pages" if f.get("page_count") else
                    ("Sheets: " + ", ".join(f.get("sheets") or []) if f.get("sheets") else "—"))
            rows.append([f"<b>{t(f['role_label'])}</b>", t(f["filename"]), t((f.get("file_type") or "").upper()),
                         t(size), t(str(f.get("evidence_count") if f.get("evidence_count") is not None else "—"))])
        blocks += [Paragraph("Submitted Artifacts", S["h2"]),
                   table(["Role", "File", "Type", "Pages / sheets", "Evidence items"], rows,
                         [1.2 * inch, 3.2 * inch, 0.5 * inch, 0.95 * inch, BODY_W - 5.85 * inch])]
    if model["citations"]:
        rows = [[f'<font color="#B5924F"><b>{t(c["ref"])}</b></font>',
                 f"<b>{t(c['role_label'])}</b><br/>{t(c['location'])}", t(c["text"])] for c in model["citations"]]
        blocks += [Paragraph(f"Evidence References ({len(model['citations'])})", S["h2"]),
                   table(["Ref", "Artifact and location", "Bounded excerpt or field value"], rows,
                         [0.42 * inch, 2.45 * inch, BODY_W - 2.87 * inch], pad=2.5, cell_style=_st["cell_x"])]
    if model["unresolved_evidence"]:
        n = len(model["unresolved_evidence"])
        blocks.append(Paragraph(f"{n} cited evidence reference(s) could not be resolved in this bid's submission "
                                "registry and are not shown.", S["note"]))
    _emit(story, head, blocks)

    # ── 9. Methodology ──
    sec += 1
    head = _section(story, sec, "Methodology & Status Definitions", new_page=False)
    blocks = []
    for m in model["methodology"]:
        blocks.append(Paragraph(f"<b>{t(m['heading'])}.</b> {t(m['text'])}", S["body_tight"]))
    rows = [[tag(d["status"], size=7.6), t(d["definition"])] for d in model["status_definitions"]]
    blocks += [Spacer(1, 6), KeepTogether([table(["Status", "Meaning"], rows, [1.8 * inch, BODY_W - 1.8 * inch])])]
    blocks.append(Spacer(1, 8))
    blocks.append(Paragraph(
        f"Rendered from durable CHECK run {t(run.get('run_id'))} ({t(run.get('status_label'))}"
        + (f", engine {t(run['engine_version'])}" if run.get("engine_version") else "")
        + (f", input fingerprint {t(run['fingerprint'])}…" if run.get("fingerprint") else "")
        + f"). Report model {t(model['version'])}.", S["note"]))
    _emit(story, head, blocks)

    doc.build(story)
    return buf.getvalue()


def render_report(*, run: dict, adjudications: list, evidence_index: dict, files=None, bid=None,
                  partial_lines=None, digest_verified: bool = True) -> dict:
    """{"pdf": bytes, "filename": str, "model": dict, "digest": str}. Pure presentation."""
    model = crm.build_report_model(run=run, adjudications=adjudications, evidence_index=evidence_index,
                                   files=files, bid=bid, partial_lines=partial_lines,
                                   digest_verified=digest_verified)
    return {"pdf": render_pdf(model), "filename": crm.report_filename(model), "model": model,
            "digest": crm.model_digest(model)}
