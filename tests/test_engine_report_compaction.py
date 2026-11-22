"""Report compaction (ENAB-33): a verbatim quote that merely restates the statement is not
repeated; the Management Decision Reference is a compact critical-only checklist without
quotes; conflict bullets name their members by entry id and source reference instead of
re-printing each statement (synthetic entries, no model calls)."""
from __future__ import annotations

import copy

from engine import reports, review


def _entry(eid, statement, quote, *, category="REQUIRED_DOCUMENT", materiality="CRITICAL",
           applicability="CURRENT", page="3"):
    return {"entry_id": eid, "category": category, "modality": "MUST", "materiality": materiality,
            "applicability": applicability, "statement": statement, "quote": quote, "document": "Doc.pdf",
            "page": page, "sources": [f"F-{eid}"], "partners": [], "relationships": [], "values": []}


def _compose(entries, conflicts=None):
    return reports.compose(entries, an={}, conflicts=copy.deepcopy(conflicts or {"conflicts": [], "clarifications": []}),
                           readability={}, run_meta={})


def _decision_ref(comp):
    return next(s for s in comp["full"]["sections"] if s.get("decision_reference"))["decision_reference"]


# ── token-overlap quote suppression ─────────────────────────────────────────

def test_quote_restating_the_statement_is_suppressed():
    e = _entry("E1", "Bidders must submit a signed tender form.",
               "Each bidder shall submit a signed tender form with its offer.")
    it = reports._item([e])
    assert "Source text:" not in it["text"]
    assert it["text"] == e["statement"]
    assert it["quote"] == e["quote"]                     # grounding is still carried on the item


def test_quote_with_distinct_wording_is_kept():
    e = _entry("E1", "A bid bond is required.",
               "Tenderers shall furnish a guarantee issued by a licensed bank valid for ninety days.")
    it = reports._item([e])
    assert 'Source text: "Tenderers shall furnish a guarantee' in it["text"]


def test_overlap_threshold_is_inclusive_at_sixty_percent():
    # statement tokens: five, three of which (60%) the quote contains -> suppressed
    assert reports._quote_overlap("alpha beta gamma delta epsilon", "alpha beta gamma zeta") == 0.6
    e = _entry("E1", "alpha beta gamma delta epsilon", "alpha beta gamma zeta")
    assert "Source text:" not in reports._item([e])["text"]
    # two of five (40%) -> kept
    e = _entry("E2", "alpha beta gamma delta epsilon", "alpha beta zeta eta")
    assert "Source text:" in reports._item([e])["text"]


def test_include_quote_false_never_appends_the_quote():
    e = _entry("E1", "A bid bond is required.", "Tenderers shall furnish a guarantee issued by a licensed bank.")
    assert "Source text:" not in reports._item([e], include_quote=False)["text"]
    items = reports._items_for([e], ["REQUIRED_DOCUMENT"], include_quote=False)
    assert items and all("Source text:" not in it["text"] for it in items)


# ── Section 8: compact Management Decision Reference ────────────────────────

def test_decision_reference_is_the_single_quote_free_documents_checklist():
    entries = [_entry("E1", "A bid bond is required.", "Tenderers shall furnish a guarantee from a licensed bank."),
               _entry("E2", "A company profile is required.", "Attach the corporate brochure and history.",
                      materiality="MATERIAL"),
               _entry("E3", "Submit by e-mail.", "Offers are to be sent electronically to the tender mailbox.",
                      category="SUBMISSION_METHOD")]
    comp = _compose(entries)
    dr = _decision_ref(comp)
    # ENAB-44: the documents checklist lists every MATERIAL+ required document. ENAB-47: it is the only
    # place they are listed, and the separate submission-logistics block became one deadline + method line
    assert [i["entry_ids"] for i in dr["documents"]] == [["E1"], ["E2"]]
    assert [(i["lead"], i["entry_ids"]) for i in dr["checklist"]] == [("Method", ["E3"])]
    assert "submission" not in dr
    assert all("Source text:" not in i["text"] for i in dr["documents"] + dr["checklist"])
    sub = next(s for s in comp["full"]["sections"] if s["title"] == "Submission and Compliance")
    assert all(g["title"] != "Required Documents and Forms" for g in sub["groups"])


# ── Section 7: compact conflict bullets ─────────────────────────────────────

def test_conflict_bullet_lists_refs_without_ids_or_statements():
    entries = [_entry("E1", "Proposals must be received by 30 April.", "Closing: 30 April.", category="DEADLINE",
                      applicability="CONFLICTED", page="2"),
               _entry("E2", "Proposals must be received by 31 May.", "Closing: 31 May.", category="DEADLINE",
                      applicability="CONFLICTED", page="5")]
    conflicts = {"conflicts": [{"entry_ids": ["E1", "E2"], "issue": "Two closing dates",
                                "implication": "The binding date is unclear."}], "clarifications": []}
    comp = _compose(entries, conflicts)
    for rep, start in ((comp["fast"], "Two closing dates. Sources: [Doc.pdf, p. 2]; [Doc.pdf, p. 5]."),
                       (comp["full"], "Two closing dates. Sources: [p. 2, p. 5].")):   # ENAB-47 compact FULL
        secs = rep["sections"] + [g for s in rep["sections"] for g in s.get("groups", [])]
        conf = [it for s in secs for it in s.get("items", []) if "Unresolved conflict" in it["labels"]]
        assert len(conf) == 1
        text = conf[0]["text"]
        # ENAB-36: members are named by source reference only, never by raw register entry id
        assert text.startswith(start)
        assert "E1" not in text and "E2" not in text
        assert "Implication: The binding date is unclear." in text
        assert all(e["statement"] not in text for e in entries)
        assert conf[0]["entry_ids"] == ["E1", "E2"]
    assert [i for i in review.deterministic_checks(comp, entries) if i["type"] == "CONTRADICTORY"] == []
