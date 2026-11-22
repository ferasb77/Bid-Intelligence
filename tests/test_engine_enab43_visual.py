"""ENAB-43: executive visual & typographic upgrade of the FAST/FULL PDFs (presentation only;
synthetic data, no model calls, no disk writes)."""
from __future__ import annotations

import io
import os
import re
import sys

from pypdf import PdfReader
from reportlab.lib.colors import HexColor
from reportlab.platypus import HRFlowable, Paragraph, Table

sys.path.insert(0, os.path.dirname(__file__))
from engine import render as R  # noqa: E402

LAPSE = "[LAPSED PER UPLOADED DOCUMENTS as of 2030-03-15 — verify whether an extension was issued]"


def _rep(kind="FULL"):
    title = "Bid Opportunity Assessment" if kind == "FULL" else "Opportunity Snapshot"
    secs = [{"title": "Deadlines", "qa_window_notice": "Documented Q&A deadline has passed as of 2030-03-15.",
             "items": [{"text": f"Questions must be received by 1 March. {LAPSE}", "refs": ["Doc.pdf, p. 2"],
                        "labels": [], "entry_ids": ["E1"]}]},
            {"title": "Specialist Analysis",
             "analysis": [{"heading": "H1", "analysis": "A.", "kind": "RISK", "refs": ["Doc.pdf, p. 1"]},
                          {"heading": "H2", "analysis": "B.", "kind": "OPEN_QUESTION", "refs": []},
                          {"heading": "H3", "analysis": "C.", "kind": "DEPENDENCY", "refs": []}]},
            {"title": "Decision Reference", "decision_reference": {
                "clarifications": [{"question": "Can the deadline be extended?"}],
                "qa_window_notice": "Documented Q&A deadline has passed as of 2030-03-15.",
                "coverage": {"locations": 3, "problems": []}}}]
    return {"kind": kind, "title": title, "run_date": "2030-03-15",
            "identity": [("Opportunity", "Synthetic Harbour Works Tender"), ("Issued by", "Synthetic Buyer")],
            "summary": ["A synthetic summary.", "Second sentence."], "sections": secs,
            "verification": {"status": "SINGLE_ANALYST", "text": "One analyst.", "limitations": ["One limitation."]}}


def _hex(c) -> str:
    return c.hexval().replace("0x", "#").upper()


def test_palette_values():
    expected = {"INK": "#0A0A0F", "BODY": "#1F242D", "MUTED": "#636B78", "GOLD": "#C9A96E",
                "GOLD_DARK": "#7A6038", "TINT": "#F7F5F0", "BORDER": "#E2DDD2", "ALERT_BG": "#FDF6EC",
                "ALERT_BORDER": "#C58A2B", "RISK_RED": "#9B2C2C", "DEP_BLUE": "#2B547E"}
    for name, hx in expected.items():
        assert _hex(getattr(R, name)) == hx, name


def test_typography_and_margins_use_builtin_fonts():
    for st in R.ST.values():
        assert st.fontName in ("Helvetica", "Helvetica-Bold")
    assert 9.2 <= R.ST["body"].fontSize <= 9.5 and 13.2 <= R.ST["body"].leading <= 13.5
    assert 9.2 <= R.ST["item"].fontSize <= 9.5 and 13.2 <= R.ST["item"].leading <= 13.5
    h2 = R.ST["h2"]
    assert h2.textColor == R.GOLD_DARK and h2.fontName == "Helvetica-Bold" and 9.5 <= h2.fontSize <= 10
    assert h2.spaceBefore == 10 and h2.spaceAfter == 4 and h2.keepWithNext == 1
    assert 15 <= R.ST["title"].fontSize <= 16
    assert abs(R.MARGIN - 18 * R.mm) < 1e-6


def test_masthead_is_ink_block_with_gold_kicker():
    for kind, kicker in (("FULL", "FULL BID OPPORTUNITY ASSESSMENT"), ("FAST", "FAST OPPORTUNITY SNAPSHOT")):
        t = R._masthead(_rep(kind))
        assert isinstance(t, Table)
        assert any(c[0] == "BACKGROUND" and c[3] == R.INK for c in t._bkgrndcmds)
        texts = [row[0].text for row in t._cellvalues]
        assert texts == [kicker, "Synthetic Harbour Works Tender"]
        assert t._cellvalues[0][0].style.textColor == R.GOLD


def test_banner_is_tinted_with_left_accent_not_box():
    t = R._banner({"status": "SINGLE_ANALYST", "text": "x"})
    assert not any(c[0] == "BOX" for c in t._linecmds)
    assert any(c[0] == "LINEBEFORE" for c in t._linecmds)
    assert any(c[0] == "BACKGROUND" and c[3] == R.TINT for c in t._bkgrndcmds)


def test_identity_table_tint_labels_and_gold_top_rule():
    t = R._kv([("Issued by", "A"), ("Key deadline", "B")])
    assert any(c[0] == "BACKGROUND" and c[3] == R.TINT for c in t._bkgrndcmds)
    assert any(c[0] == "LINEABOVE" and c[4] == R.GOLD for c in t._linecmds)
    assert any(c[0] == "LINEBELOW" and c[4] == R.BORDER for c in t._linecmds)


def test_summary_callout_and_qa_notice():
    story = R._head(_rep())
    callout = story[-1]
    assert isinstance(callout, Table)
    assert any(c[0] == "BACKGROUND" and c[3] == R.TINT for c in callout._bkgrndcmds)
    assert any(c[0] == "LINEBEFORE" and c[3] == 3 and c[4] == R.GOLD for c in callout._linecmds)
    assert callout._cellvalues[0][0].text == "A synthetic summary. Second sentence."   # wording unchanged
    qa = R._qa_notice("Notice.")
    assert qa.getKeepWithNext() == 1
    assert any(c[0] == "BACKGROUND" and c[3] == R.ALERT_BG for c in qa._bkgrndcmds)
    assert any(c[0] == "LINEBEFORE" and c[3] == 2.5 and c[4] == R.ALERT_BORDER for c in qa._linecmds)


def test_h1_has_hairline_and_keeps_with_next():
    head, rule = R._h1("1. Section")
    assert isinstance(head, Paragraph) and head.style.keepWithNext == 1
    assert isinstance(rule, HRFlowable) and rule.getKeepWithNext() == 1


def test_inline_markup_citations_lapse_and_lead_ins():
    p = R._item_para({"text": f"Due 1 March. {LAPSE}", "refs": ["Doc.pdf, p. 2"], "labels": []})
    assert f'<font size="8" color="{R.MUTED_HEX}">[Doc.pdf, p. 2]</font>' in p.text
    assert re.search(rf'<font name="Helvetica-Bold" color="{R.RISK_RED_HEX}">\[LAPSED PER UPLOADED DOCUMENTS',
                     p.text)
    for label, colour in (("Risk", R.RISK_RED_HEX), ("Open Question", R.GOLD_DARK_HEX),
                          ("Dependency", R.DEP_BLUE_HEX), ("Unresolved conflict", R.RISK_RED_HEX)):
        q = R._item_para({"text": "t", "labels": [label]})
        assert f'name="Helvetica-Bold" size="7.6" color="{colour}">{label.upper()}</font>' in q.text


def test_rendered_text_preserves_wording():
    for kind in ("FULL", "FAST"):
        pdf = R.render(_rep(kind))
        text = " ".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(pdf)).pages)
        flat = re.sub(r"\s+", " ", text)
        for s in ("A synthetic summary. Second sentence.", "Documented Q&A deadline has passed as of 2030-03-15.",
                  "LAPSED PER UPLOADED DOCUMENTS as of 2030-03-15", "[Doc.pdf, p. 2]", "RISK H1: A.",
                  "OPEN QUESTION H2: B.", "DEPENDENCY H3: C.", "Page 1 of"):
            assert s in flat, (kind, s)
