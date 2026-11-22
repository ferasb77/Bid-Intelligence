"""Report fidelity and parity (ENAB-36): a longer verbatim quote that covers the statement
is shown in its place; conflict bullets name source references instead of register entry
ids; FAST carries the Q&A window notice and contractual terms; lapse wording names no
submission channel; the PDF footer date is the run date (synthetic entries, no model calls)."""
from __future__ import annotations

import copy
import re
from datetime import date

from engine import reports, review
from engine import render as render_mod


def _entry(eid, statement, quote, *, category="ELIGIBILITY", materiality="CRITICAL", applicability="CURRENT",
           page="3", document="Doc.pdf", values=None):
    return {"entry_id": eid, "category": category, "modality": "MUST", "materiality": materiality,
            "applicability": applicability, "statement": statement, "quote": quote, "document": document,
            "page": page, "sources": [f"F-{eid}"], "partners": [], "relationships": [], "values": values or []}


def _compose(entries, conflicts=None, run_meta=None):
    return reports.compose(entries, an={}, conflicts=copy.deepcopy(conflicts or {"conflicts": [], "clarifications": []}),
                           readability={}, run_meta=run_meta or {})


def _conflict_items(rep):
    secs = rep["sections"] + [g for s in rep["sections"] for g in s.get("groups", [])]
    return [it for s in secs for it in s.get("items", []) if "Unresolved conflict" in it["labels"]]


# ── 1. quote-superset swap ─────────────────────────────────────────────────

STMT = "All bidders must ensure that, at the time of submission, they are not sanctioned."
QUOTE = "All bidders must ensure - that at the time of\nsubmission - they are not bankrupt, suspended, sanctioned"


def test_longer_covering_quote_replaces_the_statement():
    e = _entry("E1", STMT, QUOTE)
    it = reports._item([e])
    assert it["text"] == " ".join(QUOTE.split())
    assert "suspended" in it["text"] and "Source text:" not in it["text"]
    assert it["quote"] == QUOTE and it["entry_ids"] == ["E1"] and it["refs"] == ["Doc.pdf, p. 3"]
    assert it["materiality"] == "CRITICAL" and it["labels"] == []


def test_superset_swap_keeps_suffixes():
    e = _entry("E1", STMT, QUOTE, applicability="AMBIGUOUS")
    e["uncertainty"] = "scope of sanctions unclear"
    e["previous"] = [{"statement": "Old rule.", "document": "Old.pdf", "page": "1"}]
    it = reports._item([e])
    assert it["text"].startswith(" ".join(QUOTE.split()) + " (Previously: Old rule. [Old.pdf, p. 1])")
    assert it["text"].endswith("Unclear: scope of sanctions unclear")
    assert "Updated" in it["labels"]


def test_superset_swap_not_applied_without_quotes():
    e = _entry("E1", STMT, QUOTE)
    assert reports._item([e], include_quote=False)["text"] == STMT


def test_quote_not_longer_than_statement_is_not_swapped():
    # full overlap, same length: the statement stays (suppression unchanged)
    e = _entry("E1", "alpha beta gamma delta epsilon", "alpha beta gamma delta epsilon.")
    assert reports._item([e])["text"] == e["statement"]


def test_overlap_between_sixty_and_eighty_percent_is_suppressed_not_swapped():
    # four of five statement tokens (80%) -> swap; three of five (60%) -> suppressed only
    e = _entry("E1", "alpha beta gamma delta epsilon", "alpha beta gamma delta zeta eta theta")
    assert reports._item([e])["text"] == "alpha beta gamma delta zeta eta theta"
    e = _entry("E2", "alpha beta gamma delta epsilon", "alpha beta gamma zeta eta theta iota")
    it = reports._item([e])
    assert it["text"] == e["statement"] and "Source text:" not in it["text"]


def test_low_overlap_quote_still_appended_as_source_text():
    e = _entry("E1", "A bid bond is required.",
               "Tenderers shall furnish a guarantee issued by a licensed bank valid for ninety days.")
    it = reports._item([e])
    assert it["text"].startswith("A bid bond is required. Source text: \"Tenderers shall furnish")


def test_superset_quote_appears_in_fast_and_full_and_register_untouched():
    entries = [_entry("E1", STMT, QUOTE)]
    snap = copy.deepcopy(entries)
    comp = _compose(entries)
    for rep in (comp["fast"], comp["full"]):
        texts = [it["text"] for s in rep["sections"] for g in (s.get("groups") or [s]) for it in g.get("items", [])]
        assert any("suspended" in t for t in texts)
    assert entries == snap


# ── 2. human-readable conflict bullets ─────────────────────────────────────

def _conflict_fixture():
    entries = [_entry("E018", "Delivery runs January to May.", "January to May", category="DEADLINE",
                      applicability="CONFLICTED", page="2"),
               _entry("E023", "Delivery ends in April.", "End of April", category="DEADLINE",
                      applicability="CONFLICTED", page="2"),
               _entry("E048", "Completion by 30 April.", "no later than April 30", category="DEADLINE",
                      applicability="CONFLICTED", page="3"),
               _entry("E060", "Payment on acceptance.", "upon acceptance", category="PAYMENT",
                      applicability="CONFLICTED", page="5")]
    conflicts = {"conflicts": [{"entry_ids": ["E018", "E023", "E048", "E060"],
                                "issue": "E018 places delivery in May, while (E023, E048) end it in April",
                                "implication": "Window unclear."}], "clarifications": []}
    return entries, conflicts


def test_conflict_issue_ids_replaced_by_source_refs():
    entries, conflicts = _conflict_fixture()
    comp = _compose(entries, conflicts)
    for rep in (comp["fast"], comp["full"]):
        conf = _conflict_items(rep)
        assert len(conf) == 1
        text = conf[0]["text"]
        assert not re.search(r"\bE\d+\b", text)
        # bare id -> its ref; parenthesised group -> one bracket of distinct refs
        assert text.startswith("[Doc.pdf, p. 2] places delivery in May, while [Doc.pdf, p. 2; Doc.pdf, p. 3] "
                               "end it in April. Sources: [Doc.pdf, p. 5]. Implication: Window unclear.")
        assert conf[0]["entry_ids"] == ["E018", "E023", "E048", "E060"]
    assert [i for i in review.deterministic_checks(comp, entries) if i["type"] == "CONTRADICTORY"] == []


def test_no_sources_note_when_every_ref_is_already_named():
    entries, conflicts = _conflict_fixture()
    conflicts["conflicts"][0]["entry_ids"] = ["E018", "E023", "E048"]
    text = _conflict_items(_compose(entries[:3], conflicts)["fast"])[0]["text"]
    assert "Sources:" not in text


def test_unknown_ids_and_lookalike_words_are_left_alone():
    by_id = {"E1": _entry("E1", "x", "x", page="4")}
    assert reports._readable_issue("E1 and E9 differ (E1, E9); see E10.", by_id) == \
        ("[Doc.pdf, p. 4] and E9 differ ([Doc.pdf, p. 4], E9); see E10.", {"Doc.pdf, p. 4"})


# ── 3. FAST parity: Q&A window notice and contractual terms ────────────────

def _deadline(eid, statement, iso, materiality="MATERIAL"):
    return _entry(eid, statement, statement, category="DEADLINE", materiality=materiality, page="2",
                  values=[{"kind": "DATE", "text": iso, "normalized": iso}])


def test_fast_conflicts_section_carries_qa_window_notice():
    qa = _deadline("E1", "All questions must be received before the stated date.", "2030-03-10")
    amb = _entry("E2", "The award basis is unclear.", "award basis", category="EVALUATION",
                 applicability="AMBIGUOUS", materiality="MATERIAL")
    comp = _compose([qa, amb], run_meta={"run_date": "2030-03-15"})
    sec = next(s for s in comp["fast"]["sections"] if s["title"] == "Conflicts and Clarifications Affecting Participation")
    assert "Documented Q&A deadline (2030-03-10) has passed as of 2030-03-15" in sec["qa_window_notice"]
    full_dr = next(s for s in comp["full"]["sections"] if s.get("decision_reference"))["decision_reference"]
    assert sec["qa_window_notice"] == full_dr["qa_window_notice"]
    comp = _compose([qa, amb], run_meta={"run_date": "2030-03-01"})
    sec = next(s for s in comp["fast"]["sections"] if s["title"] == "Conflicts and Clarifications Affecting Participation")
    assert sec["qa_window_notice"] == ""


def test_fast_section_4_includes_contract_terms():
    ct = _entry("E1", "The contractor must keep all material confidential.", "confidential",
                category="CONTRACT_TERM", materiality="MATERIAL")
    pay = _entry("E2", "Payment follows acceptance.", "acceptance", category="PAYMENT", materiality="MATERIAL")
    comp = _compose([ct, pay])
    sec = next(s for s in comp["fast"]["sections"] if s["title"] == "Commercial, Payment and Contractual Terms")
    assert {i for it in sec["items"] for i in it["entry_ids"]} == {"E1", "E2"}
    row = next(r for r in comp["ledger"]["rows"] if r["entry_id"] == "E1")
    assert any(p.startswith("FAST:") for p in row["placements"])


# ── 4. channel-agnostic lapse wording and footer date ──────────────────────

def test_lapse_wording_names_no_channel():
    w = reports._lapse_warning("2030-03-15")
    assert w == "[LAPSED PER UPLOADED DOCUMENTS as of 2030-03-15 — verify whether an extension was issued]"
    qa = _deadline("E1", "All questions must be received before the stated date.", "2030-03-10")
    notice = reports._qa_window_notice([qa], "2030-03-15")
    for text in (w, notice):
        assert "e-bid" not in text and "email" not in text.lower() and "portal" not in text and "platform" not in text
    assert "Verify whether an extension was issued;" in notice


def test_composed_reports_carry_run_date():
    comp = _compose([_entry("E1", STMT, QUOTE)], run_meta={"run_date": "2030-03-15T09:00:00"})
    assert comp["fast"]["run_date"] == comp["full"]["run_date"] == "2030-03-15"
    assert _compose([_entry("E1", STMT, QUOTE)])["fast"]["run_date"] == date.today().isoformat()


def _footer_text(rep):
    seen = []
    orig = render_mod._footer

    def spy(label, prepared=""):
        draw = orig(label, prepared)

        def wrapped(canvas, doc):
            real = canvas.drawString
            canvas.drawString = lambda x, y, s: (seen.append(s), real(x, y, s))[1]
            try:
                draw(canvas, doc)
            finally:
                canvas.drawString = real
        return wrapped
    render_mod._footer = spy
    try:
        assert render_mod.render(rep)[:4] == b"%PDF"
    finally:
        render_mod._footer = orig
    return [s for s in seen if "prepared" in s]


def test_footer_uses_run_date_and_falls_back_to_today():
    qa = _deadline("E1", "All questions must be received before the stated date.", "2030-03-10")
    amb = _entry("E2", "The award basis is unclear.", "award basis", category="EVALUATION",
                 applicability="AMBIGUOUS", materiality="MATERIAL")
    comp = _compose([qa, amb], run_meta={"run_date": "2030-03-15"})
    for k in ("fast", "full"):
        assert _footer_text(comp[k]) and all(s.endswith("prepared 2030-03-15") for s in _footer_text(comp[k]))
    legacy = {k: v for k, v in comp["fast"].items() if k != "run_date"}
    assert all(s.endswith(f"prepared {date.today().isoformat()}") for s in _footer_text(legacy))


def test_render_prints_fast_qa_notice_above_conflict_items():
    qa = _deadline("E1", "All questions must be received before the stated date.", "2030-03-10")
    amb = _entry("E2", "The award basis is unclear.", "award basis", category="EVALUATION",
                 applicability="AMBIGUOUS", materiality="MATERIAL")
    comp = _compose([qa, amb], run_meta={"run_date": "2030-03-15"})
    captured = []
    orig = render_mod.Paragraph

    def para(text, style, *a, **kw):
        captured.append(text)
        return orig(text, style, *a, **kw)
    render_mod.Paragraph = para
    try:
        render_mod.render(comp["fast"])
    finally:
        render_mod.Paragraph = orig
    head = next(i for i, t in enumerate(captured) if "Conflicts and Clarifications Affecting Participation" in t)
    notice = next(i for i, t in enumerate(captured) if "Documented Q&amp;A deadline" in t)
    item = max(i for i, t in enumerate(captured) if "The award basis is unclear." in t)   # Section 8 copy
    assert head < notice < item
