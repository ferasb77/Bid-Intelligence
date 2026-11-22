"""Stage C conflict post-processing (ENAB-28): a conflict whose entries are a subset
of another conflict's entries is adjudicated and reported once, and conflicted
clauses are not stamped with an inline "Unresolved conflict" label in the body
sections (synthetic entries, no model calls)."""
from __future__ import annotations

import copy

from engine import conflicts as cf
from engine import reports


def _entry(eid, statement, iso, applicability="CONFLICTED", category="DEADLINE"):
    return {"entry_id": eid, "category": category, "modality": "MUST", "materiality": "CRITICAL",
            "applicability": applicability, "statement": statement, "quote": statement, "document": "Doc.pdf",
            "page": "3", "sources": [f"F-{eid}"], "partners": [], "relationships": [],
            "values": [{"kind": "DATE", "text": iso, "normalized": iso}]}


def _review(*groups):
    return {"relationships": [{"type": "UNRESOLVED_CONTRADICTION", "finding_ids": [f"F-{i}" for i in g],
                               "explanation": "x"} for g in groups]}


def _entries():
    return [_entry("E1", "Services must be delivered between the start and end of the window.", "2031-05-31"),
            _entry("E2", "Services must be delivered before the earlier closing date.", "2031-04-30"),
            _entry("E3", "Delivery must be completed by the stated final date.", "2031-04-30"),
            _entry("E4", "No retainer or effort-based payment shall apply.", "", category="PAYMENT")]


# 1. collect_candidates: subset suppression

def test_subset_candidate_after_superset_is_not_added():
    cands = cf.collect_candidates(_entries(), [_review(["E1", "E2", "E3"], ["E1", "E2"])])
    assert [c["entry_ids"] for c in cands] == [["E1", "E2", "E3"]]
    assert cands[0]["candidate_id"] == "C01"


def test_superset_candidate_replaces_earlier_subset():
    cands = cf.collect_candidates(_entries(), [_review(["E1", "E2"], ["E2", "E3"], ["E1", "E2", "E3"])])
    assert [c["entry_ids"] for c in cands] == [["E1", "E2", "E3"]]
    assert [c["candidate_id"] for c in cands] == ["C01"]


def test_overlapping_but_not_nested_candidates_are_both_kept():
    cands = cf.collect_candidates(_entries(), [_review(["E1", "E2"], ["E2", "E4"])])
    assert [c["entry_ids"] for c in cands] == [["E1", "E2"], ["E2", "E4"]]
    assert [c["candidate_id"] for c in cands] == ["C01", "C02"]


def test_value_scan_pair_covered_by_analyst_candidate_is_suppressed():
    es = _entries()
    for e in es:
        e["applicability"] = "CURRENT"
    scanned = cf.scan_candidates(es)
    assert scanned, "fixture must produce a value-scan pair"
    cands = cf.collect_candidates(es, [_review(["E1", "E2", "E3"])])
    assert [c["origin"] for c in cands] == ["analyst_review"]
    assert all(set(p) <= set(cands[0]["entry_ids"]) for p in scanned)


# 2. report-level deduplication of conflicts and clarifications (saved runs)

SAVED = {"conflicts": [
    {"entry_ids": ["E1", "E2", "E3"], "type": "UNRESOLVED_CONTRADICTION", "issue": "Delivery window differs",
     "clarification_question": "Which delivery window applies?", "implication": "x"},
    {"entry_ids": ["E1", "E2"], "type": "UNRESOLVED_CONTRADICTION", "issue": "Delivery window differs again",
     "clarification_question": "Which delivery window applies (repeat)?", "implication": "x"}],
    "clarifications": [{"entry_ids": ["E1", "E2", "E3"], "question": "Which delivery window applies?"},
                       {"entry_ids": ["E1", "E2"], "question": "Which delivery window applies (repeat)?"}]}


def _decision(comp):
    return next(s for s in comp["full"]["sections"] if s.get("decision_reference"))["decision_reference"]


def _sections(rep):
    for sec in rep["sections"]:
        for g in sec.get("groups") or [{"title": sec["title"], "items": sec.get("items") or []}]:
            yield sec["title"], g.get("title") or "", g.get("items") or []


def test_open_items_drop_strict_subset_conflict():
    items = reports._open_items(_entries(), copy.deepcopy(SAVED))
    conflict_items = [it for it in items if "Unresolved conflict" in it["labels"]]
    assert [it["entry_ids"] for it in conflict_items] == [["E1", "E2", "E3"]]


def test_compose_drops_subset_conflict_and_its_clarification():
    saved = copy.deepcopy(SAVED)
    comp = reports.compose(_entries(), an={}, conflicts=saved, readability={}, run_meta={})
    # ENAB-47: buyer questions are listed once, in FULL Section 7; the dropped subset's question never appears
    open_texts = [it["text"] for _, g, its in _sections(comp["full"]) if g.startswith("Unresolved Conflicts")
                  for it in its]
    assert any("Which delivery window applies?" in t for t in open_texts)
    assert not any("(repeat)" in t for t in open_texts)
    assert "clarifications" not in _decision(comp)
    for rep in (comp["fast"], comp["full"]):
        conflict_items = [it for _, _, its in _sections(rep) for it in its if "Unresolved conflict" in it["labels"]]
        assert [it["entry_ids"] for it in conflict_items] == [["E1", "E2", "E3"]]
    assert saved == SAVED   # input conflicts record is not mutated


def test_identical_and_disjoint_conflicts_are_untouched():
    data = {"conflicts": [{"entry_ids": ["E1", "E2"]}, {"entry_ids": ["E3", "E4"]}],
            "clarifications": [{"entry_ids": ["E1", "E2"], "question": "a"},
                               {"entry_ids": ["E3", "E4"], "question": "b"}]}
    out = reports._distinct_conflicts(data)
    assert out["conflicts"] == data["conflicts"] and out["clarifications"] == data["clarifications"]


# 3. no inline "Unresolved conflict" label on body-section items

def test_body_items_carry_no_inline_conflict_label_and_register_is_untouched():
    entries = _entries()
    before = copy.deepcopy(entries)
    comp = reports.compose(entries, an={}, conflicts=copy.deepcopy(SAVED), readability={}, run_meta={})
    body = [(t, it) for rep in (comp["fast"], comp["full"]) for sec, g, its in _sections(rep)
            for it in its for t in [sec + "/" + g] if "Conflict" not in t]
    assert any("E4" in it["entry_ids"] for _, it in body), "conflicted clause must still be reported"
    assert all("Unresolved conflict" not in it["labels"] for _, it in body)
    assert entries == before and {e["applicability"] for e in entries} == {"CONFLICTED"}


def test_ambiguous_and_disputed_labels_are_kept():
    e = _entry("E9", "Some provision.", "2031-01-01", applicability="AMBIGUOUS")
    d = _entry("E8", "Other provision.", "2031-01-02", applicability="DISPUTED")
    assert reports._item([e])["labels"] == ["Ambiguous in the source"]
    assert reports._item([d])["labels"] == ["Interpretation disputed"]
