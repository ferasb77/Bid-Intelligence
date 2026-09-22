"""
full_analysis_report.py -- MA-2C: Full Bid Intelligence PDF report export.

PURE PRESENTATION over an already-persisted FullAnalysisResult. This module
never imports full_analysis.py, full_analysis_service.py, analysis_service.py
or any provider SDK; it never calls a specialist, reconciliation, Fast
Analysis or a model; it never writes to the database. The caller (tenancy.
export_full_analysis_report_for_organization) does the authorized reads and
hands the persisted objects in.

Inputs (all as persisted):
  * status  -- full_analysis_service.get_full_analysis_status(...) dict
  * bundle  -- full_analysis_service.get_full_analysis_result(...) dict
               {"run", "result", "specialist_results" (with effective_status)}
  * identity_facts -- the source Fast Analysis run's persisted
               report_content_snapshot["SNAPSHOT_FACTS"] (buyer, solicitation...)
  * canonical_tables -- optional persisted snapshot tables (EVAL_WEIGHTS,
               EVAL_MINIMUM_SCORES, KEY_DATES) shown as canonical reference
  * bid     -- the bids row (title/client fallback identity only)

Rendering reuses the shared Bid Intelligence report stack
(scripts/build_boc_bid_intelligence_preview_pdf.py): the same reportlab
platypus flow, registered brand fonts, colour tokens, cover treatment and
table styling -- so the Full report is visually one family with the Fast
Analysis report.

Truthfulness (same rules as MA-2B's view, reused from components/
full_analysis_view.py): specialist status is the row `effective_status`
(never the raw column); PARTIAL is never rendered as COMPLETE; no narrative
is generated to fill an empty section.
"""
from __future__ import annotations

import io
import re
from datetime import datetime
from xml.sax.saxutils import escape as _xml_escape

from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate, Frame, KeepTogether, NextPageTemplate, PageBreak, PageTemplate,
    Paragraph as _RLParagraph, Spacer, Table, TableStyle,
)

import scripts.build_boc_bid_intelligence_preview_pdf as base
from components import full_analysis_view as fav

# Brand tokens / layout: shared with the Fast Analysis report.
NIGHT, INK, GOLD, MUTED, RULE, IVORY, PAPER, BAND = (
    base.NIGHT, base.INK, base.GOLD, base.MUTED, base.RULE, base.IVORY, base.PAPER, base.BAND)
PAGE_W, PAGE_H, MARGIN = base.PAGE_W, base.PAGE_H, base.MARGIN
BODY_W = PAGE_W - 2 * MARGIN
S = base.styles

AMBER = HexColor("#9A6A12")
AMBER_BG = HexColor("#FBF3E2")
AMBER_LINE = HexColor("#D9A441")
GREEN = HexColor("#2E7D4F")
GREEN_BG = HexColor("#EAF5EE")
RED = HexColor("#A93226")
RED_BG = HexColor("#FBEAEA")

_st = {
    "find_t": ParagraphStyle("fa_find_t", fontName="BodyMed", fontSize=9.8, leading=13, textColor=INK,
                             spaceAfter=2),
    "find_d": ParagraphStyle("fa_find_d", fontName="Body", fontSize=9.1, leading=13, textColor=INK,
                             spaceAfter=2),
    "find_m": ParagraphStyle("fa_find_m", fontName="Body", fontSize=7.9, leading=10.6, textColor=MUTED,
                             spaceAfter=1),
    "banner": ParagraphStyle("fa_banner", fontName="Body", fontSize=9.4, leading=13.4, textColor=INK),
    "cover_status": ParagraphStyle("fa_cover_status", fontName="BodyMed", fontSize=11, leading=15,
                                   textColor=GOLD, alignment=TA_CENTER, spaceBefore=6),
    "cell": ParagraphStyle("fa_cell", fontName="Body", fontSize=8.4, leading=11.4, textColor=INK),
    "cell_b": ParagraphStyle("fa_cell_b", fontName="BodyMed", fontSize=8.4, leading=11.4, textColor=INK),
    "cell_s": ParagraphStyle("fa_cell_s", fontName="Body", fontSize=7.6, leading=10, textColor=MUTED),
}

SPECIALIST_IDS = fav.SPECIALIST_IDS
SPECIALIST_NAME = fav.SPECIALIST_NAME
RECON_NAME = "Reconciliation & Assurance"

#: Report domain sections, in report order: (specialist id, title, blurb).
DOMAIN_SECTIONS = (
    ("PROCUREMENT_STRUCTURE", "Procurement Structure",
     "Procurement model, category structure, award mechanics, document and amendment implications, "
     "submission architecture."),
    ("REQUIREMENTS_COMPLIANCE", "Requirements & Compliance",
     "Mandatory gates, qualification requirements, submission obligations, category applicability, "
     "compliance risks."),
    ("EVALUATION_INTELLIGENCE", "Evaluation Intelligence",
     "Criteria, weights, category-specific evidence expectations, response priorities, evaluation risks."),
    ("SCOPE_DELIVERABLES", "Scope & Delivery",
     "Services and workstreams, deliverables, resource implications, delivery complexity."),
    ("COMMERCIAL_CONTRACTUAL", "Commercial & Contractual",
     "Pricing constraints, IP, confidentiality, privacy and security, termination, insurance, "
     "material exposure."),
    ("SCHEDULE_SUBMISSION", "Schedule & Submission",
     "Clarification and submission deadlines, category milestones, presentations, timing dependencies, "
     "submission mechanics."),
)

STATUS_TEXT = {
    fav.COMPLETE: "Complete",
    fav.PARTIAL: "Partial output",
    fav.FAILED: "Failed",
    fav.SKIPPED: "Not run",
}
FINDING_TYPE_LABEL = {
    "FACT": "Fact", "ATTENTION_ITEM": "Attention item", "GAP": "Gap", "AMBIGUITY": "Ambiguity",
    "INTERPRETATION": "Interpretation", "RISK": "Risk",
}
_SEV_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
_SEV_COLOR = {"HIGH": "#A93226", "MEDIUM": "#9A6A12", "LOW": "#6B675F"}
EXPORTABLE_RUN_STATUSES = (fav.COMPLETE, fav.PARTIAL)
PARTIAL_TITLE = "PARTIAL FULL BID INTELLIGENCE"


class ReportNotExportableError(Exception):
    """The run is not in an exportable terminal state (COMPLETE/PARTIAL)."""


def Paragraph(text, style):  # noqa: N802 -- <b> maps to the brand medium face
    text = str(text).replace("<b>", '<font name="BodyMed">').replace("</b>", "</font>")
    return _RLParagraph(text, style)


def esc(value) -> str:
    """XML-escape persisted text for a reportlab Paragraph."""
    return _xml_escape(str(value if value is not None else ""))


# ═══════════════════════════════════════════════════════════════════════
# Report model (pure data -- unit-tested without rendering)
# ═══════════════════════════════════════════════════════════════════════

def _facts_dict(identity_facts) -> dict:
    out = {}
    for pair in identity_facts or []:
        if isinstance(pair, (list, tuple)) and len(pair) >= 2 and pair[0]:
            out[str(pair[0])] = str(pair[1]) if pair[1] is not None else ""
    return out


_NOT_KNOWN = {"", "none", "not extracted", "not stated", "n/a", "unknown"}


def _known(value) -> str | None:
    v = str(value or "").strip()
    return None if v.lower() in _NOT_KNOWN else v


def identity(bid: dict | None, identity_facts=None) -> dict:
    """Cover identity. Persisted canonical snapshot facts first, the bid row
    only as fallback. Never invents a value -- a missing one stays None."""
    facts = _facts_dict(identity_facts)
    bid = bid or {}
    return {
        "buyer": _known(facts.get("Buyer")) or _known(bid.get("client")),
        "opportunity": _known(facts.get("Opportunity")) or _known(bid.get("title")),
        "solicitation": _known(facts.get("Solicitation Number")) or _known(bid.get("file_number")),
        "categories": _known(facts.get("Service Categories")),
        "procurement_model": _known(facts.get("Procurement Model")),
        "bid_title": _known(bid.get("title")),
        "bid_id": bid.get("id"),
    }


def report_filename(ident: dict) -> str:
    """Bid_Intelligence_<Solicitation>_Full_Analysis.pdf, sanitized. Falls
    back to opportunity/bid title, then bid id. No run id."""
    key = ident.get("solicitation") or ident.get("opportunity") or ident.get("bid_title")
    if not key and ident.get("bid_id") is not None:
        key = f"Bid_{ident['bid_id']}"
    key = re.sub(r"[^A-Za-z0-9._-]+", "_", str(key or "Bid")).strip("._-")[:80] or "Bid"
    return f"Bid_Intelligence_{key}_Full_Analysis.pdf"


def specialist_statuses(status: dict | None, rows) -> dict:
    """{specialist_id: state} -- row effective_status first (MA-2A.2), via
    MA-2B's own bot_state; never the raw row `status` column."""
    rows_map = fav.rows_by_specialist(rows)
    return {sid: fav.bot_state(sid, status, rows_map) for sid in SPECIALIST_IDS}


def reconciliation_status(status: dict | None, result: dict | None) -> str:
    st = fav.reconciliation_state(status)
    if st == fav.WAITING:  # no status given: fall back to the persisted result
        inner = ((result or {}).get("reconciliation") or {}).get("status")
        if inner in (fav.COMPLETE, fav.PARTIAL, fav.FAILED, fav.SKIPPED):
            return inner
        return fav.SKIPPED
    return st


def _sort_findings(items):
    return sorted(items, key=lambda f: (_SEV_ORDER.get(f.get("severity"), 3), str(f.get("title") or "")))


def build_report_model(status: dict | None, bundle: dict, *, bid: dict | None = None,
                       identity_facts=None, canonical_tables: dict | None = None) -> dict:
    """Pure: persisted objects -> the complete, ordered report content."""
    bundle = bundle or {}
    run = bundle.get("run") or {}
    result = bundle.get("result") or {}
    rows = bundle.get("specialist_results") or []
    run_status = (status or {}).get("status") or run.get("status")
    if run_status not in EXPORTABLE_RUN_STATUSES:
        raise ReportNotExportableError(f"Full Analysis status {run_status!r} is not exportable")

    bots = specialist_statuses(status, rows)
    recon = reconciliation_status(status, result)
    view = {"bots": bots, "reconciliation": recon, "run_status": run_status,
            "progress": fav.progress_text(bots, recon), "stuck": False}
    tone, _mark, _title, body_lines = fav.overall_banner(view, status)

    grouped = fav.group_result(result, rows)
    # Stable finding reference numbers (F1..Fn) in report order.
    refs, numbered = {}, {}
    n = 0
    for sid, _t, _b in DOMAIN_SECTIONS:
        items = grouped["domains"].get(sid) or []
        numbered[sid] = []
        for f in items:
            n += 1
            ref = f"F{n}"
            if f.get("finding_id"):
                refs[str(f["finding_id"])] = ref
            numbered[sid].append((ref, f))

    rec = result.get("reconciliation") or {}
    cross = [(f"X{i}", f) for i, f in enumerate(_sort_findings(
        [f for f in grouped["cross_domain_risks"] if isinstance(f, dict)]), 1)]
    contradictions = [(f"C{i}", f) for i, f in enumerate(_sort_findings(
        [f for f in (rec.get("contradictions") or []) if isinstance(f, dict)]), 1)]

    all_numbered = [x for sid in numbered for x in numbered[sid]]
    executive = [(ref, f) for ref, f in sorted(
        all_numbered, key=lambda x: (_SEV_ORDER.get(x[1].get("severity"), 3), int(x[0][1:])))
        if f.get("severity") == "HIGH"]

    completed = run.get("completed_at") or (status or {}).get("completed_at") or result.get("completed_at")
    return {
        "identity": identity(bid, identity_facts),
        "run_status": run_status,
        "is_partial": run_status == fav.PARTIAL,
        "banner_tone": tone,
        "banner_lines": body_lines,
        "analysis_date": _fmt_date(completed),
        "specialists": bots,
        "reconciliation": recon,
        "reconciliation_note": _recon_note(rec),
        "domains": numbered,
        "finding_refs": refs,
        "executive": executive,
        "cross_domain": cross,
        "contradictions": contradictions,
        "gaps": [f for f in grouped["gaps"] if isinstance(f, dict)],
        "ambiguities": [f for f in grouped["ambiguities"] if isinstance(f, dict)],
        "human_confirmation": [f for f in grouped["human_confirmation"] if isinstance(f, dict)],
        "orphaned_requirements": [o for o in (rec.get("orphaned_requirements") or []) if isinstance(o, dict)],
        "completeness_note": grouped["completeness_note"],
        "source_refs": [s for s in (result.get("source_refs") or []) if isinstance(s, dict)],
        "canonical_tables": canonical_tables or {},
        "run_id": run.get("id") or (status or {}).get("run_id"),
    }


def _recon_note(rec: dict) -> str:
    """Client-facing wording for why reconciliation is incomplete -- never
    the raw provider/stop-reason diagnostic."""
    if rec.get("output_truncated") or rec.get("stop_reason") == "max_tokens":
        return ("Reconciliation output reached its length limit before finishing. Every reconciled item "
                "that was persisted is included in this report; any further cross-domain checks are missing.")
    if rec.get("status") == fav.FAILED:
        return "Reconciliation did not produce a usable result for this run."
    return ""


def _fmt_date(value) -> str | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).strftime("%B %d, %Y").replace(" 0", " ")
    except ValueError:
        return str(value)[:10]


# ═══════════════════════════════════════════════════════════════════════
# Rendering helpers
# ═══════════════════════════════════════════════════════════════════════

def short_ref(cid: str, limit: int = 26) -> str:
    cid = str(cid)
    return cid if len(cid) <= limit else cid[: limit - 1] + "…"


def evidence_line(f: dict, ref: str | None, max_ids: int = 4) -> str | None:
    cids = [str(c) for c in (f.get("canonical_ids") or [])]
    if not cids:
        return None
    shown = ", ".join(esc(short_ref(c)) for c in cids[:max_ids])
    more = f" +{len(cids) - max_ids} more" if len(cids) > max_ids else ""
    where = f" · Appendix A, {ref}" if ref else ""
    return f"<b>Evidence:</b> {shown}{more}{where}"


def _producers(f: dict) -> list:
    return [p for p in (f.get("produced_by") or f.get("domains") or []) if p in SPECIALIST_NAME]


def finding_flowable(ref: str | None, f: dict, *, primary: str | None = None):
    sev = f.get("severity") or "MEDIUM"
    head = (f'<font color="{_SEV_COLOR.get(sev, "#6B675F")}" size="7.6"><b>{esc(sev)}</b></font>'
            f'&nbsp;&nbsp;{f"<font color=\"#B5924F\">{esc(ref)}</font>&nbsp;&nbsp;" if ref else ""}'
            f'{esc(f.get("title") or "Untitled finding")}')
    meta = []
    ftype = FINDING_TYPE_LABEL.get(f.get("finding_type"))
    if ftype:
        meta.append(ftype)
    auth = f.get("authority")
    if auth == "CANONICAL":
        meta.append("Canonical fact")
    elif auth:
        meta.append("Specialist interpretation")
    if f.get("human_confirmation_required"):
        meta.append('<font color="#9A6A12"><b>Needs human confirmation</b></font>')
    if f.get("category_scope"):
        meta.append(f"Scope: {esc(f['category_scope'])}")
    producers = _producers(f)
    if primary is None and producers:
        meta.append("Raised by: " + esc("; ".join(SPECIALIST_NAME[p] for p in producers)))
    else:
        others = [SPECIALIST_NAME[p] for p in producers if p != primary]
        if others:
            meta.append('<font color="#1C1B1F">Also raised by: ' + esc("; ".join(others)) + "</font>")
    parts = [Paragraph(head, _st["find_t"])]
    if f.get("detail"):
        parts.append(Paragraph(esc(f["detail"]), _st["find_d"]))
    if meta:
        parts.append(Paragraph(" · ".join(meta), _st["find_m"]))
    ev = evidence_line(f, ref)
    if ev:
        parts.append(Paragraph(ev, _st["find_m"]))
    inner = Table([[parts]], colWidths=[BODY_W])
    inner.setStyle(TableStyle([
        ("LINEBEFORE", (0, 0), (0, -1), 2 if sev == "HIGH" else 1,
         GOLD if sev == "HIGH" else RULE),
        ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    # A Table with one cell splits across pages only by row; the finding is
    # short enough to keep together, and KeepTogether never clips content.
    return KeepTogether([inner, Spacer(1, 4)])


def banner(lines, tone: str, title: str):
    color, bg = {"success": (GREEN, GREEN_BG), "caution": (AMBER_LINE, AMBER_BG),
                 "error": (RED, RED_BG)}.get(tone, (GOLD, BAND))
    text_color = {"success": "#2E7D4F", "caution": "#7A520B", "error": "#A93226"}.get(tone, "#1C1B1F")
    body = "<br/>".join(esc(l) for l in lines or [])
    p = Paragraph(f'<font color="{text_color}"><b>{esc(title)}</b></font>'
                  f'{"<br/>" + body if body else ""}', _st["banner"])
    t = Table([[p]], colWidths=[BODY_W])
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 1, color), ("LINEBEFORE", (0, 0), (0, -1), 4, color),
        ("BACKGROUND", (0, 0), (-1, -1), bg),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
        ("LEFTPADDING", (0, 0), (-1, -1), 12), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
    ]))
    return t


def table(header, rows, widths, header_bg=NIGHT):
    data = [[Paragraph(esc(h), S["table_head"]) for h in header]]
    for r in rows:
        data.append([c if not isinstance(c, str) else Paragraph(c, _st["cell"]) for c in r])
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), header_bg),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 1), (-1, -1), 0.5, RULE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [PAPER, BAND]),
    ]))
    return t


def _status_cell(state: str) -> str:
    color = {fav.COMPLETE: "#2E7D4F", fav.PARTIAL: "#9A6A12", fav.FAILED: "#A93226"}.get(state, "#6B675F")
    return f'<font color="{color}"><b>{esc(STATUS_TEXT.get(state, state).upper())}</b></font>'


def _domain_note(state: str) -> str | None:
    if state == fav.PARTIAL:
        return ("This specialist returned partial output. Its preserved findings are shown below, "
                "but this domain's analysis is incomplete.")
    if state == fav.FAILED:
        return "This specialist analysis failed. Its domain analysis is unavailable in this report."
    if state == fav.SKIPPED:
        return "This specialist analysis did not run. Its domain analysis is unavailable in this report."
    return None


# ═══════════════════════════════════════════════════════════════════════
# PDF
# ═══════════════════════════════════════════════════════════════════════

def _on_body(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.6)
    canvas.line(MARGIN, PAGE_H - 0.62 * inch, PAGE_W - MARGIN, PAGE_H - 0.62 * inch)
    canvas.setFont("BodyMed", 7.6)
    canvas.setFillColor(MUTED)
    canvas.drawString(MARGIN, PAGE_H - 0.52 * inch, "FULL BID INTELLIGENCE")
    if getattr(doc, "_fa_partial", False):
        canvas.setFillColor(AMBER)
        canvas.drawString(MARGIN + 1.45 * inch, PAGE_H - 0.52 * inch, "PARTIAL")
        canvas.setFillColor(MUTED)
    canvas.setFont("Body", 7.6)
    canvas.drawRightString(PAGE_W - MARGIN, PAGE_H - 0.52 * inch, getattr(doc, "_fa_header", "") or "")
    canvas.line(MARGIN, 0.62 * inch, PAGE_W - MARGIN, 0.62 * inch)
    canvas.drawString(MARGIN, 0.44 * inch, "Confidential · prepared for bid-team decision support")
    canvas.setFont("BodyMed", 8)
    canvas.setFillColor(GOLD)
    canvas.drawRightString(PAGE_W - MARGIN, 0.44 * inch, str(canvas.getPageNumber() - 1))
    canvas.restoreState()


def _section(story, num: int, title: str, blurb: str | None = None, *, new_page: bool = True):
    if new_page:
        story.append(PageBreak())
    head = [Paragraph(f"SECTION {num}", S["section_kicker"]), Paragraph(esc(title), S["h1"]),
            base.hr(GOLD, 1.1, 0, 8)]
    if blurb:
        head.append(Paragraph(esc(blurb), S["note"]))
    return head  # caller keeps this with the first content block (no orphan headings)


def _emit(story, head, blocks):
    """Heading kept together with the first content block."""
    if blocks:
        story.append(KeepTogether(head + [blocks[0]]))
        story.extend(blocks[1:])
    else:
        story.extend(head)


def _canonical_eval_blocks(tables: dict) -> list:
    weights = tables.get("EVAL_WEIGHTS") or {}
    mins = tables.get("EVAL_MINIMUM_SCORES") or {}
    out = []
    for cat, items in weights.items():
        pairs = [i for i in (items or []) if isinstance(i, (list, tuple)) and len(i) >= 2]
        if not pairs:
            continue
        cat_min = mins.get(cat) or {}
        if cat_min:
            rows = [[esc(i[0]), esc(i[1]), esc(cat_min.get(i[0], "N/A"))] for i in pairs]
            t = table(["Criterion", "Weight", "Minimum score"], rows,
                      [3.8 * inch, 1.3 * inch, 1.5 * inch], header_bg=GOLD)
        else:
            rows = [[esc(i[0]), esc(i[1])] for i in pairs]
            t = table(["Criterion", "Weight"], rows, [5.0 * inch, 1.6 * inch], header_bg=GOLD)
        out.append(KeepTogether([Paragraph(f"<b>{esc(cat)}</b>", S["body_tight"]), t, Spacer(1, 8)]))
    if not out:
        return []
    return [Paragraph("Canonical Evaluation Criteria &amp; Weights", S["h2"]),
            Paragraph("As extracted into the canonical procurement package the specialists analysed.",
                      S["note"])] + out + [Spacer(1, 4)]


def _canonical_dates_blocks(tables: dict) -> list:
    rows = [[esc(d[0]), esc(d[1])] for d in (tables.get("KEY_DATES") or [])
            if isinstance(d, (list, tuple)) and len(d) >= 2]
    if not rows:
        return []
    return [Paragraph("Canonical Key Dates &amp; Milestones", S["h2"]),
            Paragraph("As extracted into the canonical procurement package the specialists analysed.",
                      S["note"]),
            table(["Milestone / Date", "Detail"], rows, [2.2 * inch, BODY_W - 2.2 * inch], header_bg=GOLD),
            Spacer(1, 10)]


def _ref_table(items, refs: dict, title: str, title_refs: dict | None = None) -> list:
    if not items:
        return []
    rows = []
    for f in _sort_findings(items):
        fids = [f.get("finding_id")] if f.get("finding_id") else list(f.get("finding_ids") or [])
        fr = ", ".join(refs[x] for x in fids if x in refs)
        if not fr and title_refs:
            fr = title_refs.get(str(f.get("title") or "").strip().lower(), "")
        rows.append([esc(fr or "—"),
                     f"<b>{esc(f.get('title') or 'Untitled')}</b>",
                     esc("; ".join(SPECIALIST_NAME[p] for p in _producers(f)) or "—"),
                     esc(f.get("severity") or "—")])
    return [Paragraph(f"{esc(title)} ({len(items)})", S["h2"]),
            table(["Ref", "Item", "Raised by", "Severity"], rows,
                  [0.55 * inch, 3.45 * inch, 1.75 * inch, 0.85 * inch]),
            Spacer(1, 8)]


def render_pdf(model: dict) -> bytes:
    ident = model["identity"]
    buf = io.BytesIO()
    header = " · ".join(x for x in (ident.get("buyer"), ident.get("solicitation")) if x) \
        or (ident.get("opportunity") or "")
    doc = BaseDocTemplate(buf, pagesize=base.LETTER, leftMargin=MARGIN, rightMargin=MARGIN,
                          topMargin=MARGIN, bottomMargin=MARGIN,
                          title=f"Full Bid Intelligence — {header}" if header else "Full Bid Intelligence",
                          author="Bid Intelligence", invariant=1)
    doc._fa_header = header
    doc._fa_partial = model["is_partial"]
    doc.addPageTemplates([
        PageTemplate(id="Cover", frames=[Frame(MARGIN, 0, BODY_W, PAGE_H, id="cover")], onPage=base.on_cover),
        PageTemplate(id="Body", frames=[Frame(MARGIN, MARGIN, BODY_W, PAGE_H - 2 * MARGIN - 0.15 * inch,
                                              id="body")], onPage=_on_body),
    ])
    story = []

    # ── Cover ──
    story.append(Spacer(1, 2.3 * inch))
    story.append(Paragraph("FULL BID INTELLIGENCE", S["cover_kicker"]))
    story.append(Spacer(1, 8))
    story.append(Paragraph(esc(ident.get("opportunity") or ident.get("bid_title") or "Opportunity"),
                           S["cover_title"]))
    if ident.get("buyer"):
        story.append(Paragraph(esc(ident["buyer"]), S["cover_sub1"]))
    sub = []
    if ident.get("solicitation"):
        sub.append(f"Solicitation {esc(ident['solicitation'])}")
    if model.get("analysis_date"):
        sub.append(f"Analysis date {esc(model['analysis_date'])}")
    if sub:
        story.append(Paragraph(" · ".join(sub), S["cover_sub2"]))
    if ident.get("categories"):
        story.append(Paragraph(f"Service categories: {esc(ident['categories'])}", S["cover_sub2"]))
    status_txt = (f'<font color="#E0A84A">{PARTIAL_TITLE}</font>' if model["is_partial"]
                  else '<font color="#7FBF94">COMPLETE</font>')
    story.append(Spacer(1, 12))
    story.append(Paragraph(f"Analysis status: {status_txt}", _st["cover_status"]))
    story.append(NextPageTemplate("Body"))

    sec = 0

    # ── Analysis status (multi-agent summary) ──
    sec += 1
    head = _section(story, sec, "Analysis Status",
                    "Six specialist analyses read the same canonical procurement package; Reconciliation "
                    "& Assurance then cross-checks their findings.")
    if model["is_partial"]:
        top = banner(model["banner_lines"], "caution", PARTIAL_TITLE)
    else:
        top = banner(model["banner_lines"], "success", "FULL BID INTELLIGENCE COMPLETE")
    counts = {sid: len(model["domains"].get(sid) or []) for sid in SPECIALIST_IDS}
    rows = [[f"<b>{esc(SPECIALIST_NAME[sid])}</b>", _status_cell(model["specialists"][sid]),
             esc(counts[sid])] for sid in SPECIALIST_IDS]
    rows.append([f"<b>{RECON_NAME.replace('&', '&amp;')}</b>", _status_cell(model["reconciliation"]),
                 esc(len(model["cross_domain"]))])
    status_tbl = table(["Domain", "Status", "Findings"], rows, [3.4 * inch, 2.1 * inch, 1.1 * inch])
    blocks = [top, Spacer(1, 10), status_tbl, Spacer(1, 4),
              Paragraph("Findings for Reconciliation &amp; Assurance are cross-domain risks.", S["note"])]
    if model["reconciliation"] in (fav.PARTIAL, fav.FAILED) and model.get("reconciliation_note"):
        blocks.append(Paragraph("Reconciliation note: " + esc(model["reconciliation_note"]), S["note"]))
    _emit(story, head, blocks)

    # ── Executive intelligence ──
    sec += 1
    head = _section(story, sec, "Executive Intelligence",
                    "The highest-severity findings across all domains, and the highest-severity reconciled "
                    "cross-domain risks. Full detail is in each domain section.")
    blocks = []
    fx = ident
    facts = [(k, fx.get(k2)) for k, k2 in (("Buyer", "buyer"), ("Opportunity", "opportunity"),
                                          ("Solicitation", "solicitation"),
                                          ("Procurement model", "procurement_model"),
                                          ("Service categories", "categories")) if fx.get(k2)]
    if facts:
        blocks.append(base.fact_card_table([(k, esc(v)) for k, v in facts], col_widths=(1.6 * inch, BODY_W - 1.6 * inch)))
        blocks.append(Spacer(1, 10))
    cmp = "Partial" if model["is_partial"] else "Complete"
    total = sum(counts.values())
    blocks.append(Paragraph(
        f"<b>Completeness:</b> {cmp}. {total} specialist findings, {len(model['cross_domain'])} cross-domain "
        f"risks, {len(model['human_confirmation'])} items needing human confirmation.", S["body"]))
    if model["executive"]:
        name_of = {ref: SPECIALIST_NAME.get((_producers(f) or [""])[0], "") for ref, f in model["executive"]}
        rows = [[esc(ref), f"<b>{esc(f.get('title') or '')}</b>", esc(name_of[ref]),
                 ("Yes" if f.get("human_confirmation_required") else "")] for ref, f in model["executive"]]
        blocks += [Paragraph(f"High-Severity Findings ({len(rows)})", S["h2"]),
                   table(["Ref", "Finding", "Domain", "Confirm?"], rows,
                         [0.5 * inch, 3.7 * inch, 1.6 * inch, 0.8 * inch])]
    high_x = [(r, f) for r, f in model["cross_domain"] if f.get("severity") == "HIGH"]
    if high_x:
        blocks.append(Paragraph(f"High-Severity Cross-Domain Risks ({len(high_x)})", S["h2"]))
        rows = [[esc(r), f"<b>{esc(f.get('title') or '')}</b>",
                 esc("; ".join(SPECIALIST_NAME[p] for p in _producers(f)) or "—")] for r, f in high_x]
        blocks.append(table(["Ref", "Risk", "Domains"], rows, [0.5 * inch, 3.9 * inch, 2.2 * inch]))
        blocks.append(Paragraph("Full detail and evidence: Section 9, Cross-Domain Risks &amp; Gaps.", S["note"]))
    if not model["executive"] and not high_x:
        blocks.append(Paragraph("No high-severity findings were recorded in this analysis.", S["note"]))
    _emit(story, head, blocks)

    # ── Domain sections ──
    tables = model.get("canonical_tables") or {}
    for sid, title, blurb in DOMAIN_SECTIONS:
        sec += 1
        head = _section(story, sec, title, blurb)
        state = model["specialists"][sid]
        blocks = []
        note = _domain_note(state)
        if note:
            blocks.append(banner([note], "error" if state in (fav.FAILED, fav.SKIPPED) else "caution",
                                 f"{SPECIALIST_NAME[sid]} — {STATUS_TEXT.get(state, state)}"))
            blocks.append(Spacer(1, 8))
        if sid == "EVALUATION_INTELLIGENCE":
            blocks += _canonical_eval_blocks(tables)
        if sid == "SCHEDULE_SUBMISSION":
            blocks += _canonical_dates_blocks(tables)
        items = model["domains"].get(sid) or []
        if items:
            if len(blocks) and sid in ("EVALUATION_INTELLIGENCE", "SCHEDULE_SUBMISSION"):
                blocks.append(Paragraph("Specialist Findings", S["h2"]))
            blocks += [finding_flowable(ref, f, primary=sid) for ref, f in items]
        elif state in fav.USABLE:
            blocks.append(Paragraph("No findings were recorded in this domain.", S["note"]))
        _emit(story, head, blocks)

    # ── Cross-domain ──
    sec += 1
    head = _section(story, sec, "Cross-Domain Risks & Gaps",
                    "Reconciled across specialists: cross-domain risks, contradictions between domains, "
                    "gaps, ambiguities and items needing human confirmation.")
    blocks = []
    if model["reconciliation"] != fav.COMPLETE:
        msg = {fav.PARTIAL: "Reconciliation & Assurance returned partial output. The reconciled items below "
                            "are the valid persisted output; some cross-domain checks may be incomplete.",
               fav.FAILED: "Reconciliation & Assurance failed. Specialist findings are preserved, but "
                           "cross-domain reconciliation is missing."}.get(
            model["reconciliation"], "Reconciliation & Assurance did not run.")
        blocks += [banner([msg], "caution" if model["reconciliation"] == fav.PARTIAL else "error",
                          f"Reconciliation & Assurance — {STATUS_TEXT.get(model['reconciliation'], '')}"),
                   Spacer(1, 8)]
    if model["cross_domain"]:
        blocks.append(Paragraph(f"Cross-Domain Risks ({len(model['cross_domain'])})", S["h2"]))
        blocks += [finding_flowable(r, f) for r, f in model["cross_domain"]]
    if model["contradictions"]:
        blocks.append(Paragraph(f"Contradictions Between Domains ({len(model['contradictions'])})", S["h2"]))
        blocks += [finding_flowable(r, f) for r, f in model["contradictions"]]
    refs = model["finding_refs"]
    title_refs = {}
    for sid in model["domains"]:
        for ref, f in model["domains"][sid]:
            title_refs.setdefault(str(f.get("title") or "").strip().lower(), ref)
    blocks += _ref_table(model["human_confirmation"], refs, "Needs Human Confirmation", title_refs)
    orphan_ids = {str(o.get("canonical_id")) for o in model["orphaned_requirements"] if o.get("canonical_id")}

    def _is_orphan_gap(f):  # the same deterministic check, listed once in the table below
        cids = {str(c) for c in f.get("canonical_ids") or []}
        return not _producers(f) and cids and cids <= orphan_ids

    folded = [f for f in model["gaps"] if _is_orphan_gap(f)]
    blocks += _ref_table([f for f in model["gaps"] if not _is_orphan_gap(f)], refs, "Gaps", title_refs)
    if folded:
        blocks.append(Paragraph(f"A further {len(folded)} gap(s) are canonical requirements that no specialist "
                                "analysed; they are listed once, in full, in the table below.", S["note"]))
    blocks += _ref_table(model["ambiguities"], refs, "Ambiguities", title_refs)
    if model["orphaned_requirements"]:
        rows = [[esc(o.get("canonical_id") or "—"), esc(o.get("description") or ""),
                 esc((o.get("applicability") or "").replace("_", " ").capitalize())]
                for o in model["orphaned_requirements"]]
        blocks += [Paragraph(f"Canonical Requirements Not Addressed by Any Specialist "
                             f"({len(rows)})", S["h2"]),
                   Paragraph("Deterministic assurance check: canonical requirements that no specialist "
                             "finding cited. Review these for coverage.", S["note"]),
                   table(["Ref", "Requirement", "Applicability"], rows,
                         [0.65 * inch, 4.6 * inch, 1.35 * inch])]
    if model["completeness_note"]:
        blocks += [Spacer(1, 6), Paragraph("Reconciliation completeness note: " + esc(model["completeness_note"]),
                                           S["note"])]
    if len(blocks) == 0:
        blocks.append(Paragraph("No cross-domain items were recorded.", S["note"]))
    _emit(story, head, blocks)

    # ── Appendix ──
    sec += 1
    head = _section(story, sec, "Source & Evidence Appendix",
                    "Appendix A maps each finding reference to the canonical procurement objects it cites. "
                    "Appendix B lists the source-document excerpts the canonical package was built from.")
    rows = []
    for sid, _t, _b in DOMAIN_SECTIONS:
        for ref, f in model["domains"].get(sid) or []:
            rows.append([esc(ref), esc(f.get("title") or ""),
                         esc(", ".join(str(c) for c in f.get("canonical_ids") or []) or "—")])
    for ref, f in model["cross_domain"] + model["contradictions"]:
        rows.append([esc(ref), esc(f.get("title") or ""),
                     esc(", ".join(str(c) for c in f.get("canonical_ids") or []) or "—")])
    blocks = []
    if rows:
        blocks += [Paragraph("Appendix A — Finding References", S["h2"]),
                   table(["Ref", "Finding", "Canonical references"], rows,
                         [0.5 * inch, 3.0 * inch, 3.1 * inch]), Spacer(1, 10)]
    src_rows = []
    for s in model["source_refs"]:
        loc = ", ".join(x for x in (
            f"p. {s['page']}" if s.get("page") not in (None, "") else "",
            f"sheet {s['sheet']}" if s.get("sheet") else "",
            str(s["section"]) if s.get("section") else "") if x)
        src_rows.append([f"<b>{esc(s.get('source_doc') or '—')}</b>", esc(loc or "—"),
                         esc(s.get("excerpt") or "")])
    if src_rows:
        blocks += [Paragraph("Appendix B — Source Document Excerpts", S["h2"]),
                   table(["Document", "Location", "Excerpt"], src_rows,
                         [2.0 * inch, 1.0 * inch, 3.6 * inch])]
    blocks += [Spacer(1, 8), Paragraph(
        "This report is a deterministic rendering of the persisted Full Bid Intelligence result"
        f"{' (analysis record ' + esc(model['run_id']) + ')' if model.get('run_id') else ''}. "
        "Findings marked Specialist interpretation are advisory analysis, not procurement fact; confirm "
        "them against the source documents before relying on them.", S["note"])]
    _emit(story, head, blocks)

    doc.build(story)
    return buf.getvalue()


def render_report(status: dict | None, bundle: dict, *, bid: dict | None = None,
                  identity_facts=None, canonical_tables: dict | None = None) -> dict:
    """{"pdf": bytes, "filename": str, "model": dict}. Pure presentation."""
    model = build_report_model(status, bundle, bid=bid, identity_facts=identity_facts,
                               canonical_tables=canonical_tables)
    return {"pdf": render_pdf(model), "filename": report_filename(model["identity"]), "model": model}
