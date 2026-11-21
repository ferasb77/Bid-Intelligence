"""Regression tests: short verbatim quotes, list items under a heading, and distinct
documents in near-identical wording must not be dropped (synthetic text, no model calls)."""
from __future__ import annotations

from engine import register as rg
from engine.package import build_package
from engine.reports import group_restatements
from engine.verify import locate_quote, verify_finding

PAGE1 = ("Bidders must read these instructions carefully before preparing any submission to the buyer.\n"
         "The technical proposal shall cover at least the following areas:\n"
         "Methodology\nWork Plan\nStaff Profiles\nRisk Management Approach\n")
PAGE2 = "Pricing must be stated in the currency of the tender. Work Plan\n"


def _pkg():
    return build_package([{"name": "doc.txt", "text": "[[SOURCE: doc.txt | PAGE: 1]]\n" + PAGE1 +
                           "[[SOURCE: doc.txt | PAGE: 2]]\n" + PAGE2}], data_class="SYNTHETIC")


def _finding(fid, quote, statement, page="1", **kw):
    f = {"id": fid, "analyst": "A", "category": "REQUIRED_DOCUMENT", "modality": "MUST", "materiality": "MATERIAL",
         "statement": statement, "quote": quote, "document": "doc.txt", "page": page, "values": [],
         "conditions": [], "exceptions": [], "consequence": ""}
    f.update(kw)
    return f


# 1. verify.locate_quote ─ short quotes

def test_one_and_two_word_quotes_verify_on_their_cited_page():
    p = _pkg()
    assert locate_quote(p, "Methodology", "doc.txt", "1")["status"] == "VERIFIED"
    hit = locate_quote(p, "Staff Profiles", "doc.txt", "1")
    assert hit["status"] == "VERIFIED" and hit["span"][1] - hit["span"][0] == 2


def test_short_quote_is_not_relocated_and_needs_a_cited_location():
    p = _pkg()
    # absent from the cited page: not searched elsewhere in the package
    assert locate_quote(p, "Methodology", "doc.txt", "2")["status"] == "NOT_FOUND"
    # without a cited location a short quote cannot be verified
    assert locate_quote(p, "Methodology")["status"] == "EMPTY"


def test_meaningless_short_fragments_stay_empty():
    p = _pkg()
    for q in ("a", "the", "of the", "must", "", "..."):
        assert locate_quote(p, q, "doc.txt", "1")["status"] == "EMPTY", q


def test_short_quote_not_on_cited_page_is_not_found():
    assert locate_quote(_pkg(), "Insurance", "doc.txt", "1")["status"] == "NOT_FOUND"


def test_long_quotes_still_relocate():
    hit = locate_quote(_pkg(), "Pricing must be stated in the currency", "doc.txt", "1")
    assert hit["status"] == "RELOCATED"


# 2. register._dedupe ─ child list item vs generic parent

def test_list_item_is_not_folded_into_its_heading():
    p = _pkg()
    parent = verify_finding(p, _finding("A-1", "The technical proposal shall cover at least the following areas:",
                                        "The technical proposal must cover the listed areas."))
    child = verify_finding(p, _finding("A-2", "The technical proposal shall cover at least the following areas: "
                                              "... Methodology",
                                       "The technical proposal must cover Methodology."))
    assert rg.overlap(child, parent) >= 0.9          # same span: the pre-fix condition for folding
    kept, dups = rg._dedupe([parent, child])
    assert [f["id"] for f in kept] == ["A-1", "A-2"] and dups == []


def test_true_duplicates_are_still_folded():
    p = _pkg()
    a = verify_finding(p, _finding("A-1", "The technical proposal shall cover at least the following areas",
                                   "The technical proposal must cover the listed areas."))
    b = verify_finding(p, _finding("A-2", "the technical proposal shall cover at least the following areas:",
                                   "The technical proposal must cover the areas listed."))
    kept, dups = rg._dedupe([a, b])
    assert [f["id"] for f in kept] == ["A-1"] and dups[0]["duplicate_of"] == "A-1"


# 3. reports._same / group_restatements ─ distinct documents in near-identical wording

def _entry(eid, statement, quote, span):
    return {"entry_id": eid, "category": "REQUIRED_DOCUMENT", "modality": "MUST", "values": [],
            "statement": statement, "quote": quote, "applicability": "CURRENT",
            "verification": {"loc_id": "D1-L1", "span": list(span)}}


def test_documents_differing_by_one_noun_are_not_merged():
    a = _entry("E1", "A copy of the trade licence (firms) is required with the offer.",
               "Copy of the trade licence (firms);", (10, 16))
    b = _entry("E2", "A copy of the tax licence (firms) is required with the offer.",
               "Copy of the tax licence (firms).", (16, 22))
    assert len(group_restatements([a, b])) == 2


def test_restatements_of_the_same_provision_still_merge():
    a = _entry("E1", "Offers submitted by other means will be rejected.",
               "Offers submitted by means other than as specified below will be rejected.", (1, 13))
    b = _entry("E2", "Offers submitted by other means will be rejected.",
               "Offers submitted by means other than as specified above will be rejected.", (40, 52))
    c = _entry("E3", "Offers submitted by any other means will be rejected.",
               "Offers submitted by means other than as specified above will be rejected.", (70, 82))
    assert [len(g) for g in group_restatements([a, b, c])] == [3]


def test_different_values_never_merge():
    a = _entry("E1", "Bids are due within 30 days.", "Bids are due within 30 days.", (1, 6))
    b = dict(_entry("E2", "Bids are due within 30 days.", "Bids are due within 30 days.", (9, 14)),
             values=[{"text": "30 days"}])
    assert len(group_restatements([a, b])) == 2
