"""review.deterministic_checks (ENAB-30): an unresolved conflict is verified against the
Conflicts / Open Items section, not against inline labels on body-section bullets
(synthetic entries, no model calls)."""
from __future__ import annotations

import copy

from engine import reports, review


def _entry(eid, statement, iso, applicability="CONFLICTED", category="DEADLINE"):
    return {"entry_id": eid, "category": category, "modality": "MUST", "materiality": "CRITICAL",
            "applicability": applicability, "statement": statement, "quote": statement, "document": "Doc.pdf",
            "page": "3", "sources": [f"F-{eid}"], "partners": [], "relationships": [],
            "values": [{"kind": "DATE", "text": iso, "normalized": iso}]}


def _entries():
    return [_entry("E1", "Proposals must be received by 2031-04-30.", "2031-04-30"),
            _entry("E2", "Proposals must be received by 2031-05-31.", "2031-05-31"),
            _entry("E3", "Questions must be submitted by 2031-04-01.", "2031-04-01", applicability="CURRENT")]


CONFLICTS = {"conflicts": [{"entry_ids": ["E1", "E2"], "issue": "Two closing dates"}], "clarifications": []}


def _compose(entries, conflicts):
    return reports.compose(entries, an={}, conflicts=copy.deepcopy(conflicts), readability={}, run_meta={})


def _contradictory(issues):
    return [i for i in issues if i["type"] == "CONTRADICTORY"]


def test_conflict_listed_in_open_items_without_inline_label_is_not_flagged():
    entries = _entries()
    comp = _compose(entries, CONFLICTS)
    body = [it for s in comp["fast"]["sections"] if s["title"] != "Conflicts and Clarifications Affecting Participation"
            for it in s.get("items", []) if {"E1", "E2"} & set(it["entry_ids"])]
    assert body and all("Unresolved conflict" not in it["labels"] for it in body)
    assert _contradictory(review.deterministic_checks(comp, entries)) == []


def test_conflict_missing_from_open_items_is_flagged():
    entries = _entries()
    comp = _compose(entries, {"conflicts": [], "clarifications": []})
    issues = _contradictory(review.deterministic_checks(comp, entries))
    assert sorted({i["entry_ids"][0] for i in issues}) == ["E1", "E2"]
    assert {i["description"].split(" the ")[1].split()[0] for i in issues} == {"FAST", "FULL"}


def test_partially_listed_conflict_flags_only_the_missing_entry():
    entries = _entries() + [_entry("E4", "Proposals must be received by 2031-06-15.", "2031-06-15")]
    comp = _compose(entries, CONFLICTS)
    issues = _contradictory(review.deterministic_checks(comp, entries))
    assert issues and all(i["entry_ids"] == ["E4"] for i in issues)


def test_other_deterministic_checks_are_preserved():
    entries = _entries()
    comp = _compose(entries, CONFLICTS)
    comp["ledger"]["violations"] = ["E3"]
    issues = review.deterministic_checks(comp, entries)
    assert [i["entry_ids"] for i in issues if i["type"] == "MISSING_MANDATORY"] == [["E3"]]
