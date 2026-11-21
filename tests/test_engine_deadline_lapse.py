"""Deterministic deadline-vs-run-date check (ENAB-25): lapsed deadlines are
annotated, never removed; a lapsed Q&A window adds an extension-aware notice to
the buyer-questions section; register entries are never mutated."""
from __future__ import annotations

import copy
from datetime import date

from engine import reports

WARN = "LAPSED PER UPLOADED DOCUMENTS"


def _deadline(eid, statement, iso, materiality="MATERIAL"):
    return {"entry_id": eid, "category": "DEADLINE", "modality": "MUST", "materiality": materiality,
            "applicability": "CURRENT", "statement": statement, "quote": statement, "document": "Doc.pdf",
            "page": "2", "values": [{"kind": "DATE", "text": iso, "normalized": iso}]}


QA = _deadline("E1", "All questions must be received before the stated date.", "2030-03-10")
FINAL = _deadline("E2", "Proposals are required no later than the closing date.", "2030-03-20", "CRITICAL")
CLARS = {"clarifications": [{"entry_ids": ["E2"], "question": "Is a late extension available?"}]}


def _compose(entries, run_meta):
    return reports.compose(entries, an={}, conflicts=CLARS, readability={}, run_meta=run_meta)


def _texts(comp, eid):
    out = []

    def walk(n):
        if isinstance(n, dict):
            if eid in (n.get("entry_ids") or []) and isinstance(n.get("text"), str):
                out.append(n["text"])
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)
    walk([comp["fast"], comp["full"]])
    return out


def _decision(comp):
    return next(s for s in comp["full"]["sections"] if s.get("decision_reference"))["decision_reference"]


def test_lapsed_qa_deadline_flagged_and_notice_attached():
    entries = [copy.deepcopy(QA), copy.deepcopy(FINAL)]
    snap = copy.deepcopy(entries)
    comp = _compose(entries, {"run_date": "2030-03-15"})
    texts = _texts(comp, "E1")
    assert texts and all(WARN in t and "as of 2030-03-15" in t for t in texts)
    assert all(QA["statement"] in t for t in texts)          # original date/text preserved
    notice = _decision(comp)["qa_window_notice"]
    assert "Documented Q&A deadline (2030-03-10) has passed as of 2030-03-15" in notice
    assert "extension" in notice
    assert _decision(comp)["clarifications"] == CLARS["clarifications"]   # questions not suppressed
    assert entries == snap                                    # canonical register untouched


def test_lapsed_final_submission_deadline_flagged_including_key_deadline():
    comp = _compose([copy.deepcopy(QA), copy.deepcopy(FINAL)], {"run_date": "2030-03-21"})
    assert all(WARN in t for t in _texts(comp, "E2"))
    assert WARN in dict(comp["fast"]["identity"])["Key deadline"]


def test_future_deadline_not_flagged_and_no_notice():
    comp = _compose([copy.deepcopy(QA), copy.deepcopy(FINAL)], {"run_date": "2030-03-10"})  # same day: not lapsed
    assert not any(WARN in t for t in _texts(comp, "E1") + _texts(comp, "E2"))
    assert WARN not in dict(comp["fast"]["identity"])["Key deadline"]
    assert _decision(comp)["qa_window_notice"] == ""


def test_non_qa_lapsed_deadline_does_not_trigger_notice():
    other = _deadline("E3", "Site visit registration closes on the date stated.", "2030-03-11")
    comp = _compose([copy.deepcopy(FINAL), other], {"run_date": "2030-03-12"})
    assert all(WARN in t for t in _texts(comp, "E3"))
    assert _decision(comp)["qa_window_notice"] == ""


def test_run_date_fallback_to_today():
    assert reports.run_date_of({}) == date.today().isoformat()
    assert reports.run_date_of({"run_date": ""}) == date.today().isoformat()
    assert reports.run_date_of({"run_date": "2030-03-15T10:00:00"}) == "2030-03-15"
    past = _deadline("E1", "All questions must be received before the stated date.", "2000-01-01")
    comp = _compose([past], {"verification": None})
    assert all(f"as of {date.today().isoformat()}" in t for t in _texts(comp, "E1"))
    assert "(2000-01-01)" in _decision(comp)["qa_window_notice"]


def test_superseded_deadline_not_flagged():
    old = dict(copy.deepcopy(QA), applicability="SUPERSEDED")
    comp = _compose([old, copy.deepcopy(FINAL)], {"run_date": "2030-03-15"})
    assert _decision(comp)["qa_window_notice"] == ""
