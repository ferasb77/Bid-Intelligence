"""ENAB-41: enumerated-list / grouped-exclusion prompt rules, run-date-aware and jargon-free
analysis prompt, and PDF pagination/layout polish (synthetic data, no model calls)."""
from __future__ import annotations

import io
import os
import re
import sys

from pypdf import PdfReader
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import ListFlowable, Paragraph

sys.path.insert(0, os.path.dirname(__file__))
import engine_synthetic as S  # noqa: E402

from engine import adjudicate, extraction, pipeline, reports  # noqa: E402
from engine import render as R  # noqa: E402
from engine.package import build_package  # noqa: E402
from engine.providers import ScriptedAnalyst, UsageLedger  # noqa: E402


# ── 1. enumerated lists & grouped exclusions ──────────────────────────────

def _rules(system: str, first: int, last: int) -> str:
    m = re.search(rf"\n{first}\. .*?(?=\n{last + 1}\. )", system, re.S)
    assert m, "rules block not found"
    return m.group(0)


def test_extraction_rules_1_to_3_preserve_every_enumerated_item():
    block = _rules(extraction.SYSTEM, 1, 3)
    assert "enumerat" in block and "and\"/\"or" in block
    assert "EVERY listed item" in block
    assert "complete enumerated list intact in one statement" in block
    assert "separate finding for every single item" in block
    assert "Zero omissions" in block


def test_adjudicator_corrected_rule_preserves_every_enumerated_item():
    corrected = re.search(r"- CORRECTED:.*?(?=\n- BOTH_VALID)", adjudicate.SYSTEM, re.S).group(0)
    assert "enumerated list" in corrected and "grouped and/or exclusion" in corrected
    assert "preserve EVERY listed item" in corrected
    assert "never drop" in corrected


def test_prompts_contain_no_document_specific_examples():
    for text in (extraction.SYSTEM, adjudicate.SYSTEM, reports.ANALYSIS_SYSTEM):
        assert not re.search(r"(lau|york|bank of canada|lebanese)", text, re.I)


# ── 2. run-date-aware, jargon-free analysis ────────────────────────────────

def test_analysis_prompt_is_date_aware_and_bans_register_jargon():
    s = reports.ANALYSIS_SYSTEM
    assert "RUN DATE" in s and "already passed" in s and "assumptions or risks" in s
    for status in ("CONFLICTED", "AMBIGUOUS", "DISPUTED", "CURRENT"):
        assert status in s
    assert "internal metadata" in s
    for jargon in ("flagged as conflicted", "marked conflicted", "in the register"):
        assert jargon in s


def _entry(eid="E1"):
    return {"entry_id": eid, "category": "DEADLINE", "modality": "MUST", "materiality": "CRITICAL",
            "applicability": "CURRENT", "statement": "Questions must be received by 1 May.", "quote": "x",
            "document": "Doc.pdf", "page": "2"}


def _capture():
    seen = {}

    def responder(purpose, system, user, schema):
        seen.update(purpose=purpose, system=system, user=user)
        return {"summary": [], "points": []}
    return seen, ScriptedAnalyst(responder, name="w")


def test_analysis_passes_run_date_into_user_payload():
    seen, w = _capture()
    reports.analysis(w, [_entry()], UsageLedger("t", path=""), "SYNTHETIC", run_date="2030-03-15")
    assert seen["user"].startswith("RUN DATE: 2030-03-15")
    assert "EVIDENCE REGISTER:" in seen["user"]


def test_analysis_run_date_is_optional_and_backward_compatible():
    seen, w = _capture()
    out = reports.analysis(w, [_entry()], UsageLedger("t", path=""), "SYNTHETIC")
    assert seen["user"].startswith("EVIDENCE REGISTER:") and "RUN DATE" not in seen["user"]
    assert out["error"] is None


def test_pipeline_passes_run_started_date_to_analysis():
    captured = []
    base = S.adjudicator()

    def adj(purpose, system, user, schema):
        if purpose == "analysis":
            captured.append(user)
        return base(purpose, system, user, schema)
    rl = pipeline.EngineRoles(primary=ScriptedAnalyst(S.responder("A"), name="A"),
                              independent=ScriptedAnalyst(S.responder("B"), name="B", provider="scripted-b"),
                              adjudicator=ScriptedAnalyst(adj, name="adj"))
    r = pipeline.run(build_package(S.documents(), data_class="SYNTHETIC"), rl, ledger=UsageLedger("t", path=""))
    assert captured, "analysis was not called"
    assert captured[0].startswith(f"RUN DATE: {r.record['started_at'][:10]}")


# ── 3. PDF pagination and layout ───────────────────────────────────────────

def test_heading_and_bullet_styles():
    assert R.ST["h1"].keepWithNext == 1 and R.ST["h2"].keepWithNext == 1 and R.ST["note"].keepWithNext == 1
    assert R.ST["h2"].spaceBefore == 10   # ENAB-43 executive styling (was 8)
    assert R.ST["item"].allowOrphans == 0 and R.ST["item"].allowWidows == 0
    assert R._bullets([{"text": "a"}]).spaceAfter == 4   # ENAB-43 (was 3)


def test_identity_table_widths_padding_and_top_rule():
    t = R._kv([("Buyer", "A buyer"), ("Reference", "R-1")])
    assert [round(w / R.BODY_W, 2) for w in t._colWidths] == [0.24, 0.76]
    cells = [c for row in t._cellStyles for c in row]
    assert all(c.leftPadding == 5 and c.rightPadding == 5 for c in cells)
    assert any(c[0] == "LINEABOVE" and c[1] == (0, 0) and c[2] == (-1, 0) for c in t._linecmds)


def _keep(n_items=40):
    head = Paragraph("1. Heading", R.ST["h1"])
    lst = R._bullets([{"text": f"Item {i} " + "word " * 20, "refs": [], "labels": []} for i in range(n_items)])
    k = R._KeepWithFirst([head, lst])
    k.canv = Canvas(io.BytesIO())
    return k, head, lst


def _is_break(f) -> bool:
    return getattr(f, "action", None) == ("frameEnd", 0)


def test_keep_with_first_only_needs_heading_plus_first_bullet():
    k, head, lst = _keep()
    aW = R.BODY_W
    h_head = head.wrap(aW, 1e6)[1]
    h_first = lst._content[0].wrap(aW, 1e6)[1]
    roomy = h_head + h_first + 40             # far less than the whole list, more than heading + first bullet
    assert not _is_break(k.split(aW, roomy)[0])   # list flows; no whole-list page gap
    tight = h_head + h_first / 2               # heading would be orphaned
    assert _is_break(k.split(aW, tight)[0])


def _rep(n_sections=6, n_items=18, title="Synthetic Harbour Works Tender"):
    secs = [{"title": f"Section {s}", "items": [{"text": f"Provision {s}.{i} " + "detail " * 18,
                                                 "refs": ["Doc.pdf, p. 1"], "labels": []} for i in range(n_items)]}
            for s in range(n_sections)]
    secs[min(1, n_sections - 1)]["qa_window_notice"] = "Documented Q&A deadline has passed as of 2030-03-15."
    return {"kind": "FULL", "title": "Bid Opportunity Assessment", "run_date": "2030-03-15",
            "identity": [("Opportunity", title), ("Buyer", "Synthetic Buyer")],
            "summary": ["A synthetic summary."], "sections": secs,
            "verification": {"status": "SYNTHETIC", "text": "Synthetic.", "limitations": ["One limitation."]}}


def _pages(pdf: bytes) -> list[str]:
    return [p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf)).pages]


def test_page_n_of_m_footer_and_running_header():
    pages = _pages(R.render(_rep()))
    n = len(pages)
    assert n >= 3
    for i, text in enumerate(pages, 1):
        assert f"Page {i} of {n}" in text
        assert "prepared 2030-03-15" in text
    assert all("Synthetic Harbour Works Tender" in t for t in pages[1:])
    # page 1 shows the title once (document title), the running header is not added there
    assert pages[0].count("Synthetic Harbour Works Tender") == 1


def test_no_page_ends_with_an_orphan_heading():
    pages = _pages(R.render(_rep(n_sections=10, n_items=7)))
    for text in pages:
        body = [ln for ln in text.splitlines() if ln.strip() and not re.search(r"Page \d+ of \d+|prepared", ln)]
        assert body and not re.fullmatch(r"\d+\. Section \d+", body[-1].strip())
        assert body[-1].strip() != "Verification limitations"


def test_render_page_size_unchanged_and_pdf_valid():
    pdf = R.render(_rep(n_sections=1, n_items=2))
    assert pdf[:4] == b"%PDF"
    reader = PdfReader(io.BytesIO(pdf))
    assert len(reader.pages) == 1
    assert [round(float(x)) for x in reader.pages[0].mediabox[2:]] == [round(letter[0]), round(letter[1])]
    assert "Page 1 of 1" in reader.pages[0].extract_text()
