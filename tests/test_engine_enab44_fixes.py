"""ENAB-44: hyphenated entry-id ranges in conflict wording, a complete FULL Section 8 documents
checklist, and an unbroken H1 -> rule -> [notice] -> H2 -> first-bullet keep chain in the PDF
(synthetic data, no model calls, no disk writes)."""
from __future__ import annotations

import copy
import io
import re

from pypdf import PdfReader

from engine import reports, review
from engine import render as R


def _entry(eid, statement, quote="q", *, category="REQUIRED_DOCUMENT", materiality="CRITICAL",
           applicability="CURRENT", page="3"):
    return {"entry_id": eid, "category": category, "modality": "MUST", "materiality": materiality,
            "applicability": applicability, "statement": statement, "quote": quote, "document": "Doc.pdf",
            "page": page, "sources": [f"F-{eid}"], "partners": [], "relationships": [], "values": []}


def _compose(entries, conflicts=None):
    return reports.compose(entries, an={}, conflicts=copy.deepcopy(conflicts or {"conflicts": [], "clarifications": []}),
                           readability={}, run_meta={})


# ── 1. hyphenated entry-id ranges ──────────────────────────────────────────

def _by_id():
    return {f"E{n:03d}": _entry(f"E{n:03d}", f"s{n}", page=str(n)) for n in (10, 11, 41, 42, 43, 50)}


def test_hyphen_and_dash_ranges_expand_to_their_source_refs():
    by_id = _by_id()
    for sep in ("-", "–", "—", " - "):
        text, named = reports._readable_issue(f"E041{sep}E043 require a fixed price.", by_id)
        assert text == "[Doc.pdf, p. 41; Doc.pdf, p. 42; Doc.pdf, p. 43] require a fixed price.", sep
        assert named == {"Doc.pdf, p. 41", "Doc.pdf, p. 42", "Doc.pdf, p. 43"}


def test_short_range_mixed_list_and_parenthesised_group():
    by_id = _by_id()
    text, _ = reports._readable_issue("E041-43, E010 and E011 differ from (E050, E010-E011).", by_id)
    assert text == ("[Doc.pdf, p. 41; Doc.pdf, p. 42; Doc.pdf, p. 43], [Doc.pdf, p. 10] and [Doc.pdf, p. 11] "
                    "differ from [Doc.pdf, p. 50; Doc.pdf, p. 10; Doc.pdf, p. 11].")
    assert not re.search(r"\bE\d{3}\b", text)


def test_range_ids_are_deduplicated_and_gaps_skipped():
    by_id = _by_id()                                   # E044..E049 are not in the register
    text, _ = reports._readable_issue("E041-E050 conflict.", by_id)
    assert text == "[Doc.pdf, p. 41; Doc.pdf, p. 42; Doc.pdf, p. 43; Doc.pdf, p. 50] conflict."
    same_page = {i: dict(e, page="7") for i, e in by_id.items()}
    assert reports._readable_issue("E041-E043 conflict.", same_page)[0] == "[Doc.pdf, p. 7] conflict."


def test_non_register_ranges_are_left_as_written():
    by_id = _by_id()
    for s in ("Between 2026-2027 only.", "E900-E903 are unknown.", "E043-E041 reversed.", "X041-E043 mixed."):
        assert reports._readable_issue(s, by_id)[0] == s


def test_conflict_bullet_with_range_has_no_raw_ids_or_redundant_sources_suffix():
    entries = [_entry(f"E{n:03d}", f"Payment rule {n}.", category="PAYMENT", applicability="CONFLICTED",
                      page=str(n)) for n in (41, 42, 43, 73)]
    conflicts = {"conflicts": [{"entry_ids": ["E041", "E042", "E043", "E073"],
                                "issue": "E041-E043 require per-deliverable payment, while E073 requires per-day "
                                         "payment.", "implication": "Payment basis is unclear."}],
                 "clarifications": []}
    comp = _compose(entries, conflicts)
    # FAST keeps full references; FULL (ENAB-47) uses compact page citations, the file named in its header
    for rep, start in ((comp["fast"], "[Doc.pdf, p. 41; Doc.pdf, p. 42; Doc.pdf, p. 43] require per-deliverable "
                                      "payment, while [Doc.pdf, p. 73] requires per-day payment."),
                       (comp["full"], "[p. 41, p. 42, p. 43] require per-deliverable payment, while [p. 73] requires "
                                      "per-day payment.")):
        secs = rep["sections"] + [g for s in rep["sections"] for g in s.get("groups", [])]
        conf = [it for s in secs for it in s.get("items", []) if "Unresolved conflict" in it["labels"]]
        assert len(conf) == 1
        text = conf[0]["text"]
        assert text.startswith(start)
        assert "Sources:" not in text
        assert not re.search(r"\bE\d+\b", text)
    assert [i for i in review.deterministic_checks(comp, entries) if i["type"] == "CONTRADICTORY"] == []


def test_sources_suffix_still_names_members_not_cited_inline():
    entries = [_entry(f"E{n:03d}", f"Rule {n}.", category="PAYMENT", applicability="CONFLICTED", page=str(n))
               for n in (41, 42, 99)]
    conflicts = {"conflicts": [{"entry_ids": ["E041", "E042", "E099"], "issue": "E041-E042 differ."}],
                 "clarifications": []}
    full = _compose(entries, conflicts)["full"]
    text = next(it["text"] for s in full["sections"] for g in s.get("groups", []) for it in g["items"]
                if "Unresolved conflict" in it["labels"])
    assert text == "[p. 41, p. 42] differ. Sources: [p. 99]."          # ENAB-47 compact FULL citations


# ── 2. FULL Section 8 documents checklist parity ───────────────────────────

def test_section8_checklist_lists_every_required_document_once():
    entries = [_entry("E1", "A bid bond is required.", materiality="CRITICAL"),
               _entry("E2", "A copy of an identity document is required.", materiality="MATERIAL", page="4"),
               _entry("E3", "Three references are required.", materiality="MATERIAL", page="5"),
               _entry("E4", "A cover page is optional.", materiality="INFORMATIONAL", page="6")]
    comp = _compose(entries)
    dr = next(s for s in comp["full"]["sections"] if s.get("decision_reference"))["decision_reference"]
    sub = next((s for s in comp["full"]["sections"] if s["title"] == "Submission and Compliance"), {"groups": []})
    # ENAB-47: Section 8 is the single canonical documents checklist; Section 5 no longer repeats it
    assert all(g["title"] != "Required Documents and Forms" for g in sub["groups"])
    fast3 = next(s for s in comp["fast"]["sections"] if s["title"] == "Mandatory Forms and Documents")["items"]
    ids = lambda items: [i for it in items for i in it["entry_ids"]]   # noqa: E731
    assert ids(dr["documents"]) == ids(fast3) == ["E1", "E2", "E3"]
    assert all("Source text:" not in it["text"] for it in dr["documents"])


# ── 3. heading keep chain in the PDF ───────────────────────────────────────

def _flow_names(f):
    return [type(x).__name__ for x in f._content]


def test_chain_keeps_groups_h1_rule_notice_h2_and_list():
    story = (R._h1("1. A") + [R._qa_notice("Notice."), R.Paragraph("Sub", R.ST["h2"]),
                              R._bullets([{"text": "x"}, {"text": "y"}]), R.Paragraph("Tail", R.ST["body"])])
    out = R._chain_keeps(story)
    assert len(out) == 2 and isinstance(out[0], R._KeepWithFirst)
    assert _flow_names(out[0]) == ["Paragraph", "HRFlowable", "Table", "Paragraph", "ListFlowable"]
    assert out[1] is story[-1]


def _rep(lead_items: int):
    secs = [{"title": "Lead", "items": [{"text": f"Lead provision {i} " + "detail " * 14, "refs": ["Doc.pdf, p. 1"],
                                         "labels": []} for i in range(lead_items)]},
            {"title": "Target Section", "groups": [
                {"title": "Target Group", "items": [{"text": f"Target provision {i} " + "detail " * 14,
                                                     "refs": ["Doc.pdf, p. 2"], "labels": []} for i in range(6)]}]}]
    return {"kind": "FULL", "title": "Bid Opportunity Assessment", "run_date": "2030-03-15",
            "identity": [("Opportunity", "Synthetic Works"), ("Issued by", "Synthetic Buyer")],
            "summary": ["Summary."], "sections": secs, "verification": {}}


def test_h1_and_h2_never_end_a_page_at_any_position():
    """Slides the H1 + H2 pair across the page foot; neither may ever be the last body line."""
    heads = {"2. Target Section", "Target Group"}
    for n in range(10, 30):
        pages = [p.extract_text() or "" for p in PdfReader(io.BytesIO(R.render(_rep(n)))).pages]
        for text in pages:
            body = [ln.strip() for ln in text.splitlines() if ln.strip() and ln.strip() != "Synthetic Works"
                    and not re.search(r"Page \d+ of \d+|prepared \d", ln)]
            assert body[-1] not in heads, (n, body[-3:])
        whole = "\n".join(pages)
        page_of = lambda s: next(i for i, t in enumerate(pages) if s in t)   # noqa: E731
        assert page_of("2. Target Section") == page_of("Target Group") == page_of("Target provision 0")
        assert "Target provision 5" in whole
