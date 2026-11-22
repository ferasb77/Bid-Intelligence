"""ENAB-46/47: FULL report compacted into an execution playbook -- compact, page-deduplicated citations,
each fact stated once across Sections 5/7/8, no INFORMATIONAL filler, a tick-box Section 8 checklist and
the FAST brief's typography (synthetic data, no model calls, no disk writes)."""
from __future__ import annotations

import copy
import io
import re

from pypdf import PdfReader

from engine import reports, review
from engine import render as R

RUN_DATE = "2030-03-10"


def _entry(eid, statement, *, category="QUALIFICATION", materiality="CRITICAL", applicability="CURRENT",
           page="3", document="Tender.pdf", quote=None, values=None):
    return {"entry_id": eid, "category": category, "modality": "MUST", "materiality": materiality,
            "applicability": applicability, "statement": statement, "quote": quote or statement,
            "document": document, "page": page, "sources": [f"F-{eid}"], "partners": [], "relationships": [],
            "values": values or []}


def _entries(multi=False):
    d2 = "Annex.pdf" if multi else "Tender.pdf"
    return [
        _entry("E001", "The buyer seeks a facilitation programme for 40 participants.", category="SCOPE",
               materiality="MATERIAL", page="2"),
        _entry("E002", "Background on the buyer's history is provided for context.", category="SCOPE",
               materiality="INFORMATIONAL", page="1"),
        _entry("E003", "Bidders must demonstrate at least 7 years of relevant experience.", page="4"),
        _entry("E004", "Bidders must provide two references.", category="REQUIRED_DOCUMENT", page="4", document=d2),
        _entry("E005", "A signed declaration form is required.", category="REQUIRED_DOCUMENT",
               materiality="MATERIAL", page="5"),
        _entry("E006", "A cover letter may be attached.", category="REQUIRED_DOCUMENT", materiality="INFORMATIONAL",
               page="5"),
        _entry("E007", "Proposals are due no later than March 18, 2030 at 12:00.", category="DEADLINE", page="6",
               values=[{"kind": "DATE", "text": "March 18, 2030", "normalized": "2030-03-18"}]),
        _entry("E008", "Proposals must be e-mailed to the tender mailbox.", category="SUBMISSION_METHOD", page="6"),
        _entry("E009", "Late proposals will be rejected.", category="DISQUALIFICATION", page="6"),
        _entry("E010", "Late proposals will be rejected.", category="DISQUALIFICATION", page="6"),   # restated
        _entry("E011", "Bidders must furnish a bid bond of 2% issued by a licensed bank and valid for the whole "
                       "tender validity period stated in the instructions.", category="GUARANTEE", page="7",
               quote="bid bond of 2%"),
        _entry("E012", "The price is a fixed lump sum.", category="PRICING", applicability="CONFLICTED", page="7"),
        _entry("E013", "The price is broken down per day.", category="PRICING", applicability="CONFLICTED",
               page="8", document=d2),
    ]


def _conflicts(extra_question=False):
    clar = [{"entry_ids": ["E012", "E013"], "question": "Which price basis applies?"}]
    if extra_question:
        clar.append({"entry_ids": ["E003"], "question": "May the experience be met by the team as a whole?"})
    return {"conflicts": [{"entry_ids": ["E012", "E013"], "issue": "E012 and E013 state different price bases.",
                           "clarification_question": "Which price basis applies?"}],
            "clarifications": clar}


def _an():
    return {"title": "Facilitation Programme", "buyer": "The Buyer", "reference": "", "summary": [],
            "points": [{"heading": "Pricing tension", "analysis": "Two price bases apply.", "kind": "RISK",
                        "entry_ids": ["E012", "E012", "E013", "E011", "E011"]}]}


def _compose(entries=None, conflicts=None, multi=False):
    entries = entries if entries is not None else _entries(multi)
    return reports.compose(copy.deepcopy(entries), an=_an(), conflicts=conflicts or _conflicts(),
                           readability={"locations": 8, "problems": []}, run_meta={"run_date": RUN_DATE})


def _sec(rep, title):
    return next((s for s in rep["sections"] if s["title"] == title), {"groups": []})


def _full_items(full):
    for s in full["sections"]:
        for g in s.get("groups") or []:
            yield s["title"], g["title"], g["items"]


# ── 1. compact, page-deduplicated citations across FULL ────────────────────

def test_single_document_full_uses_compact_deduplicated_page_citations_and_names_the_file_once():
    full = _compose()["full"]
    for _, _, items in _full_items(full):
        for it in items:
            assert "Tender.pdf" not in it["text"] and all("Tender.pdf" not in r for r in it["refs"]), it
            # a conflict item cites its members inline; every other item carries one compact bracket
            assert len(it["refs"]) == (0 if "Unresolved conflict" in it["labels"] else 1), it
    dq = _sec(full, "Submission and Compliance")
    dq = next(g for g in dq["groups"] if g["title"] == "Disqualification and Rejection")["items"]
    assert [(it["entry_ids"], it["refs"]) for it in dq] == [(["E009", "E010"], ["p. 6"])]   # [p. 6], not twice
    assert dict(full["identity"])["Source file"] == "Tender.pdf"
    assert dict(full["identity"])["Key deadline"].endswith("[p. 6]")
    # Specialist Analysis: one bracket, each page once, in page order
    pt = _sec(full, "Specialist Analysis")["analysis"][0]
    assert pt["refs"] == ["p. 7, p. 8"]


def test_multi_document_full_uses_document_keys_and_a_header_legend():
    full = _compose(multi=True)["full"]
    assert dict(full["identity"])["Source files"] == "D1 = Tender.pdf; D2 = Annex.pdf"
    pt = _sec(full, "Specialist Analysis")["analysis"][0]
    assert pt["refs"] == ["D1, p. 7; D2, p. 8"]
    conf = [it for _, _, its in _full_items(full) for it in its if "Unresolved conflict" in it["labels"]]
    assert conf[0]["text"].startswith("[D1, p. 7; D2, p. 8] state different price bases.")


def test_fast_content_model_keeps_its_full_references():
    fast = _compose()["fast"]
    assert "Source file" not in dict(fast["identity"])
    assert all(r.startswith("Tender.pdf, ") for s in fast["sections"] for it in s.get("items") or []
               for r in it["refs"])


def test_bare_id_lists_in_conflict_wording_become_one_deduplicated_bracket():
    by_id = {e["entry_id"]: e for e in _entries()}
    keys = reports.source_keys(_entries())
    text, _ = reports._readable_issue("E009, E010 and E011 differ from E003.", by_id, keys=keys)
    assert text == "[p. 6, p. 7] differ from [p. 4]."
    # default (FAST) wording is unchanged
    assert reports._readable_issue("E009 and E011 differ.", by_id)[0] == \
        "[Tender.pdf, p. 6] and [Tender.pdf, p. 7] differ."


# ── 2. each fact once: Sections 5 / 7 / 8 ──────────────────────────────────

def test_required_documents_listed_once_in_the_section8_checklist():
    comp = _compose()
    full = comp["full"]
    assert all(g["title"] != "Required Documents and Forms" for g in _sec(full, "Submission and Compliance")["groups"])
    dr = _sec(full, "Management Decision Reference")["decision_reference"]
    assert [it["entry_ids"] for it in dr["documents"]] == [["E004"], ["E005"]]
    assert all("Source text:" not in it["text"] for it in dr["documents"])
    # the deadline + method summary line replaces the separate submission-logistics block
    assert [(it["lead"], it["entry_ids"]) for it in dr["checklist"]] == [("Deadline", ["E007"]), ("Method", ["E008"])]
    assert not {"submission", "clarifications", "qa_window_notice"} & set(dr)
    rows = {r["entry_id"]: r for r in comp["ledger"]["rows"]}
    assert "FULL:Checklist" in rows["E004"]["placements"] and "FULL:Checklist" in rows["E005"]["placements"]


def test_buyer_questions_stated_once_in_section7_and_none_dropped():
    full = _compose(conflicts=_conflicts(extra_question=True))["full"]
    texts = [it["text"] for _, g, its in _full_items(full) if g.startswith("Unresolved Conflicts") for it in its]
    assert sum("Which price basis applies?" in t for t in texts) == 1          # carried by the conflict item
    assert sum("May the experience be met by the team as a whole?" in t for t in texts) == 1   # appended once


def test_redundant_source_text_echo_is_suppressed_in_full_only():
    comp = _compose()
    full_bond = next(it for _, _, its in _full_items(comp["full"]) for it in its if it["entry_ids"] == ["E011"])
    assert "Source text:" not in full_bond["text"]             # "bid bond of 2%" is already in the statement
    fast_bond = next(it for s in comp["fast"]["sections"] for it in s.get("items") or [] if it["entry_ids"] == ["E011"])
    assert 'Source text: "bid bond of 2%"' in fast_bond["text"]   # FAST composition unchanged
    # a quote carrying wording the statement lacks is still shown
    e = _entry("E1", "A bond is required.", category="GUARANTEE", quote="Tenderers shall furnish a guarantee.")
    assert "Source text:" in reports._item([e], keys={"Tender.pdf": ""})["text"]


def test_informational_entries_are_register_only_and_the_ledger_stays_complete():
    comp = _compose()
    placed = {i for _, _, its in _full_items(comp["full"]) for it in its for i in it["entry_ids"]}
    dr = _sec(comp["full"], "Management Decision Reference")["decision_reference"]
    placed |= {i for it in dr["documents"] for i in it["entry_ids"]}
    assert "E002" not in placed and "E006" not in placed
    rows = {r["entry_id"]: r for r in comp["ledger"]["rows"]}
    assert rows["E002"]["reason"] == rows["E006"]["reason"] == "informational (register only)"
    # every CRITICAL / MATERIAL reportable provision is still in FULL
    crit = {e["entry_id"] for e in _entries() if e["materiality"] != "INFORMATIONAL"}
    full_placed = {i for i, r in rows.items() if any(p.startswith("FULL") for p in r["placements"])}
    assert crit <= full_placed
    assert comp["ledger"]["complete"] and review.deterministic_checks(comp, _entries()) == []


def test_model_review_text_still_sees_the_section8_documents():
    text = review._report_text(_compose())
    assert "(E004) Bidders must provide two references." in text
    assert "(E005) A signed declaration form is required." in text


# ── 3. rendering: playbook typography, checkbox checklist, no orphans ──────

def _pages(pdf):
    return [p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf)).pages]


def test_full_typography_matches_the_fast_brief_and_legacy_fast_is_unchanged():
    assert (R.FST["item"].fontSize, R.FST["item"].leading) == (8.8, 11.8)
    assert (R.FST["body"].fontSize, R.FST["body"].leading) == (8.8, 11.8)
    assert R.FST.margin == R.BRIEF_MARGIN == 14.5 * R.mm and R.FST.gap == 2.5
    assert R.FST["h1"].textColor == R.INK and R.FST["h2"].textColor == R.GOLD_DARK
    assert R.ST.margin == R.MARGIN == 18 * R.mm and R.ST["item"].fontSize == 9.3


def test_section8_documents_render_as_checkbox_rows():
    comp = _compose()
    dr = _sec(comp["full"], "Management Decision Reference")["decision_reference"]
    rows = R._checklist(dr["documents"], R.FST)
    assert len(rows) == 2 and all(isinstance(t._cellvalues[0][0], R._CheckBox) for t in rows)
    seen = []
    orig = R._checklist
    R._checklist = lambda items, st: (seen.append([it["entry_ids"] for it in items]), orig(items, st))[1]
    try:
        text = "\n".join(_pages(R.render(comp["full"])))
    finally:
        R._checklist = orig
    assert seen == [[["E004"], ["E005"]]]
    assert "Submission & Documents Checklist" in text and "Bidders must provide two references. [p. 4]" in text
    for gone in ("Submission logistics", "Open questions for the buyer", "Documents and forms to submit"):
        assert gone not in text


def test_rendered_full_has_no_raw_ids_no_orphaned_headings_and_limitations_inside_section8():
    entries = _entries() + [
        _entry(f"E1{n:02d}", f"Proposal requirement {n}: " + "the proposal must describe the approach " * 4,
               category="SUBMISSION_REQUIREMENT", materiality="MATERIAL", page=str(2 + n % 6)) for n in range(40)]
    comp = _compose(entries)
    full = comp["full"]
    full["verification"] = {"status": "SINGLE_ANALYST", "text": "Single-analyst analysis.",
                            "limitations": ["Limitation A.", "Limitation B."]}
    pages = _pages(R.render(full))
    text = "\n".join(pages)
    assert not re.search(r"(?<![\w-])E\d{2,}R?(?![\w-])", text)
    heads = {f"{n}. {s['title']}" for n, s in enumerate(full["sections"], 1)} | {
        g["title"] for s in full["sections"] for g in s.get("groups") or []} | {
        "Submission & Documents Checklist", "Source coverage", "Verification limitations"}
    for t in pages:
        body = [ln.strip() for ln in t.splitlines() if ln.strip() and not re.search(r"Page \d+ of \d+|prepared \d", ln)]
        assert body[-1] not in heads, body[-3:]
    assert all(f"Page {i} of {len(pages)}" in t for i, t in enumerate(pages, 1))
    # the limitations close Section 8 instead of a separate appendix heading after it
    assert text.count("Verification limitations") == 1
    assert text.index("8. Management Decision Reference") < text.index("Verification limitations") \
        < text.index("Limitation A.")
    assert review.deterministic_checks(comp, entries) == [] and comp["ledger"]["complete"]
