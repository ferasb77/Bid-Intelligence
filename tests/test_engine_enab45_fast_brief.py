"""ENAB-45: synthesized 1-2 page FAST decision-triage brief, piggybacked on the existing analysis call
(synthetic data, no model calls, no disk writes)."""
from __future__ import annotations

import copy
import io
import re

from pypdf import PdfReader

from engine import reports, review
from engine import render as R
from engine.providers import ScriptedAnalyst, UsageLedger

RUN_DATE = "2030-03-10"


def _entry(eid, statement, *, category="QUALIFICATION", materiality="CRITICAL", applicability="CURRENT",
           page="3", document="Tender.pdf", values=None):
    return {"entry_id": eid, "category": category, "modality": "MUST", "materiality": materiality,
            "applicability": applicability, "statement": statement, "quote": statement, "document": document,
            "page": page, "sources": [f"F-{eid}"], "partners": [], "relationships": [], "values": values or []}


def _date(iso, text):
    return {"kind": "DATE", "text": text, "normalized": iso}


def _entries(multi=False):
    d2 = "Annex.pdf" if multi else "Tender.pdf"
    return [
        _entry("E001", "The buyer seeks a supplier to deliver a facilitation programme for 40 participants.",
               category="SCOPE", materiality="MATERIAL", page="2"),
        _entry("E002", "Delivery takes place over 4 days at the buyer's premises.", category="DURATION",
               materiality="MATERIAL", page="2"),
        _entry("E003", "Bidders must demonstrate at least 7 years of relevant experience.", page="4"),
        _entry("E004", "Bidders must provide two references.", category="REQUIRED_DOCUMENT", page="4", document=d2),
        _entry("E005", "Without a tax certificate a 5% deduction is applied to payments.", category="PAYMENT",
               materiality="MATERIAL", page="5", document=d2),
        _entry("E006", "Proposals are due no later than March 18, 2030 at 12:00.", category="DEADLINE", page="6",
               values=[_date("2030-03-18", "March 18, 2030"), {"kind": "TIME", "text": "12:00", "normalized": "12:00"}]),
        _entry("E007", "Questions must be received before March 8, 2030.", category="DEADLINE",
               materiality="MATERIAL", page="6", values=[_date("2030-03-08", "March 8, 2030")]),
        _entry("E008", "Late proposals will be rejected.", category="DISQUALIFICATION", page="6"),
        _entry("E009", "Payment is made 30 days after acceptance of each deliverable.", category="PAYMENT",
               materiality="MATERIAL", page="7"),
        _entry("E010", "The price is a fixed lump sum.", category="PRICING", applicability="CONFLICTED", page="7"),
        _entry("E011", "The price is broken down per day.", category="PRICING", applicability="CONFLICTED",
               page="8", document=d2),
        _entry("E012", "The maximum budget is USD 50,000.", category="FINANCIAL_THRESHOLD", page="2"),
        _entry("E013", "An excluded provision.", applicability="EXCLUDED_UNSUPPORTED", page="9"),
    ]


def _conflicts():
    return {"conflicts": [{"entry_ids": ["E010", "E011"], "issue": "E010 and E011 state different price bases."}],
            "clarifications": []}


def B(text, *ids):
    return {"text": text, "entry_ids": list(ids)}


def _payload(words_per_bullet=0):
    pad = (" " + " ".join(["detail"] * words_per_bullet)) if words_per_bullet else ""
    return {
        "stated_budget": B("USD 50,000 maximum", "E012"),
        "what_is_it": [B("Facilitation programme for 40 participants (see E001)." + pad, "E001"),
                       B("Delivered over 4 days at the buyer's premises." + pad, "E002")],
        "can_we_qualify_hard_gates": [B("At least 7 years of relevant experience." + pad, "E003"),
                                      B("Two references are required." + pad, "E004")],
        "can_we_qualify_admin_penalties": [B("No tax certificate means a 5% deduction." + pad, "E005")],
        "can_we_bid_in_time": [B("Question window per E007; late proposals are rejected." + pad, "E007", "E008")],
        "is_it_worth_it": [B("Payment 30 days after acceptance; weighting not disclosed." + pad, "E009")],
        "material_conflicts": [B("Price basis: lump sum vs. per day -> price form must be clarified." + pad,
                                 "E010", "E011")],
    }


def _analysis(payload, entries=None):
    entries = entries or _entries()
    resp = {"title": B("Facilitation Programme", "E001"), "buyer": B("", ), "reference": B(""),
            "summary": [B("A facilitation programme for 40 participants.", "E001")], "points": []}
    if payload is not None:
        resp["fast_brief"] = payload
    seen = []

    def responder(purpose, system, user, schema):
        seen.append((purpose, schema))
        return copy.deepcopy(resp)
    led = UsageLedger("enab45-test", path="")          # never appends to a cost ledger file
    an = reports.analysis(ScriptedAnalyst(responder), entries, led, "SYNTHETIC", run_date=RUN_DATE)
    return an, seen


def _compose(an, entries=None, run_date=RUN_DATE):
    entries = entries or _entries()
    return reports.compose(entries, an=an, conflicts=_conflicts(), readability={},
                           run_meta={"run_date": run_date})


def _brief_items(brief):
    return [it for s in brief["sections"] for g in s["groups"] for it in g["items"]]


# ── 1. one analysis call returns and checks the brief ──────────────────────

def test_brief_is_requested_in_the_existing_analysis_call_and_schema_is_strict():
    an, seen = _analysis(_payload())
    assert [p for p, _ in seen] == ["analysis"]                        # one call, no extra purpose
    sch = seen[0][1]
    assert "fast_brief" in sch["properties"] and "fast_brief" in sch["required"]

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node.get("additionalProperties") is False
                assert sorted(node.get("required") or []) == sorted(node.get("properties") or {})
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk(reports.ANALYSIS_OUTPUT)
    fb = an["fast_brief"]
    assert fb["stated_budget"] == {"text": "USD 50,000 maximum", "entry_ids": ["E012"]}
    assert [b["entry_ids"] for b in fb["what_is_it"]] == [["E001"], ["E002"]]


def test_ungrounded_uncited_and_advisory_bullets_are_rejected():
    p = _payload()
    p["what_is_it"] += [B("Programme for 400 participants.", "E001"),            # figure not in the entry
                        B("An uncited statement."),                              # no entry ids
                        B("Covers an unknown provision.", "E013"),               # not reportable
                        B("We recommend a no-go decision.", "E001")]             # advice wording
    p["stated_budget"] = B("USD 75,000", "E012")                                 # figure not in the entry
    an, _ = _analysis(p)
    fb = an["fast_brief"]
    assert [b["text"] for b in fb["what_is_it"]] == [b["text"] for b in _payload()["what_is_it"]]
    assert fb["stated_budget"] == {"text": "Not disclosed", "entry_ids": []}
    reasons = [r["reason"] for r in an["rejected"] if r["element"].startswith("fast_brief")]
    assert len(reasons) == 5 and "recommendation or rating wording" in reasons


def test_bullet_caps_are_enforced():
    p = _payload()
    p["what_is_it"] = [B(f"Facilitation programme item {c}.", "E001") for c in "abcdef"]
    an, _ = _analysis(p)
    assert len(an["fast_brief"]["what_is_it"]) == 4


def test_missing_or_empty_brief_reads_as_none():
    assert _analysis(None)[0]["fast_brief"] is None
    empty = {k: [] for k, _ in reports.FAST_BRIEF_LISTS}
    empty["stated_budget"] = B("Not disclosed")
    assert _analysis(empty)[0]["fast_brief"] is None


# ── 2. deterministic date math ─────────────────────────────────────────────

def test_countdown_is_computed_from_the_run_date():
    assert reports.countdown("2026-11-30", "2026-11-22") == "Nov 30, 2026 (8 days left)"
    assert reports.countdown("2026-11-23", "2026-11-22") == "Nov 23, 2026 (1 day left)"
    assert reports.countdown("2026-11-22", "2026-11-22") == "Nov 22, 2026 (due today)"
    assert reports.countdown("2026-11-21", "2026-11-22") == "Closed Nov 21, 2026 (1 day ago)"
    assert reports.countdown("2026-11-20", "2026-11-22") == "Closed Nov 20, 2026 (2 days ago)"
    assert reports.countdown("2027-01-05", "2026-12-30") == "Jan 5, 2027 (6 days left)"


def test_decision_header_deadline_and_qa_window():
    an, _ = _analysis(_payload())
    hdr = dict(_compose(an)["fast"]["brief"]["header"])
    assert hdr["Submission Deadline"] == "Mar 18, 2030, 12:00 (8 days left) [p. 6]"
    assert hdr["Q&A Window"] == "Closed Mar 8, 2030 (2 days ago) [p. 6]"
    assert hdr["Stated Budget"] == "USD 50,000 maximum [p. 2]"
    assert list(hdr)[:4] == ["Client / Program", "Submission Deadline", "Q&A Window", "Stated Budget"]
    open_hdr = dict(_compose(an, run_date="2030-03-05")["fast"]["brief"]["header"])
    assert open_hdr["Q&A Window"] == "Open until Mar 8, 2030 (3 days left) [p. 6]"


# ── 3. compact citations ───────────────────────────────────────────────────

def test_single_document_citations_and_legend():
    an, _ = _analysis(_payload())
    brief = _compose(an)["fast"]["brief"]
    assert dict(brief["header"])["Source File"] == "Tender.pdf"
    cites = {it["text"].split(".")[0]: it["cite"] for it in _brief_items(brief)}
    assert cites["Price basis: lump sum vs"] == "[p. 7, p. 8]"
    assert all(re.fullmatch(r"\[p\. \d+(, p\. \d+)*\]", it["cite"]) for it in _brief_items(brief))


def test_multi_document_citations_use_short_keys_and_one_line_legend():
    entries = _entries(multi=True)
    an, _ = _analysis(_payload(), entries)
    brief = _compose(an, entries)["fast"]["brief"]
    assert dict(brief["header"])["Source Files"] == "D1 = Tender.pdf; D2 = Annex.pdf"
    by_text = {it["entry_ids"][0]: it["cite"] for it in _brief_items(brief)}
    assert by_text["E004"] == "[D2, p. 4]"
    assert by_text["E010"] == "[D1, p. 7; D2, p. 8]"
    assert by_text["E001"] == "[D1, p. 2]"


def test_raw_entry_ids_in_bullet_text_become_compact_citations():
    an, _ = _analysis(_payload())
    items = _brief_items(_compose(an)["fast"]["brief"])
    texts = " ".join(it["text"] for it in items)
    assert "Facilitation programme for 40 participants (see [p. 2])." in texts
    assert "Question window per [p. 6];" in texts
    assert not re.search(r"\bE\d{3}\b", texts)


# ── 4. deterministic_checks grounding ──────────────────────────────────────

def test_deterministic_checks_pass_on_a_grounded_brief_and_flag_defects():
    entries = _entries()
    an, _ = _analysis(_payload(), entries)
    comp = _compose(an, entries)
    assert review.deterministic_checks(comp, entries) == []
    assert comp["ledger"]["complete"]
    bad = copy.deepcopy(comp)
    items = _brief_items(bad["fast"]["brief"])
    items[0]["entry_ids"] = ["E999"]
    items[1]["text"] += " See E003."
    items[2]["cite"] = ""
    issues = [i for i in review.deterministic_checks(bad, entries) if i["source"] == "fast_brief"]
    assert len(issues) == 3
    assert any("raw register entry id" in i["description"] for i in issues)


# ── 5. legacy result.json without a brief ──────────────────────────────────

def test_legacy_analysis_without_brief_keeps_the_deterministic_fast():
    entries = _entries()
    legacy = {"title": "Facilitation Programme", "summary": [], "points": [], "rejected": [], "error": None}
    before = _compose(legacy, entries)
    after = _compose(dict(legacy, fast_brief=None), entries)
    assert "brief" not in before["fast"] and "brief" not in after["fast"]
    assert before == after
    assert review.deterministic_checks(before, entries) == []
    pdf = R.render(before["fast"])
    text = "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf)).pages)
    assert "FAST OPPORTUNITY SNAPSHOT" in text and "FAST OPPORTUNITY BRIEF" not in text


def test_full_report_is_unchanged_by_the_brief():
    entries = _entries()
    an, _ = _analysis(_payload(), entries)
    with_brief = _compose(an, entries)
    without = _compose(dict(an, fast_brief=None), entries)
    assert with_brief["full"] == without["full"]
    assert with_brief["fast"]["sections"] == without["fast"]["sections"]
    assert R.render(with_brief["full"])[:4] == b"%PDF"


# ── 6. rendered layout: 1-2 pages, no orphaned headings ────────────────────

def _pages(pdf):
    return [p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf)).pages]


def _brief_rep(words_per_bullet, multi=False, limitations=2):
    entries = _entries(multi)
    an, _ = _analysis(_payload(words_per_bullet), entries)
    fast = _compose(an, entries)["fast"]
    fast["verification"] = {"status": "SINGLE_ANALYST", "text": "Single-analyst analysis.",
                            "limitations": [f"Limitation {i}." for i in range(limitations)]}
    return fast


def test_brief_renders_masthead_header_and_five_sections():
    fast = _brief_rep(0)
    text = "\n".join(_pages(R.render(fast)))
    for s in ("FAST OPPORTUNITY BRIEF", "SINGLE ANALYST", "CLIENT / PROGRAM", "SUBMISSION DEADLINE", "Q&A WINDOW",
              "STATED BUDGET", "SOURCE FILE", "1. What Is It?", "2. Can We Qualify?", "Hard Gates",
              "Admin & Penalty Gates", "3. Can We Bid in Time?", "4. Is It Worth It Commercially?",
              "5. Material Conflicts & Caveats", "Verification limitation: Limitation 1.", "Page 1 of 1"):
        assert s in text, s
    assert R.BST["item"].fontSize == 8.8 and R.BST["item"].leading == 11.8
    assert 14 * R.mm <= R.BRIEF_MARGIN <= 15 * R.mm
    assert not re.search(r"\bE\d{3}\b", text)


def test_typical_and_upper_target_briefs_fit_on_one_to_two_pages_without_orphaned_headings():
    for words, multi in ((0, False), (40, False), (55, True)):
        fast = _brief_rep(words, multi, limitations=3)
        wc = fast["brief"]["word_count"]
        pages = _pages(R.render(fast))
        assert 1 <= len(pages) <= 2, (words, wc, len(pages))
        heads = {f"{n}. {s['title']}" for n, s in enumerate(fast["brief"]["sections"], 1)} | {
            "Hard Gates", "Admin & Penalty Gates"}
        for text in pages:
            body = [ln.strip() for ln in text.splitlines()
                    if ln.strip() and not re.search(r"Page \d+ of \d+|prepared \d", ln)]
            assert body[-1] not in heads, (words, body[-3:])
        assert all(f"Page {i} of {len(pages)}" in t for i, t in enumerate(pages, 1))
    assert wc >= 450          # the upper case exceeds the 450-650 word target and still fits on two pages
