"""Extraction split-and-retry when an answer hits the output-token limit
(synthetic package, scripted analysts; no model calls)."""
from __future__ import annotations

import re

import pytest

from engine import extraction
from engine.extraction import MAX_TEXT_SPLITS, split_text
from engine.package import build_package
from engine.providers import (AnthropicAnalyst, ProviderOutputLimit, ScriptedAnalyst, UsageLedger)
from engine.verify import locate_quote

DOC = "Synthetic_Dense_Spec.pdf"
CLAUSES = [f"Clause {i}: The supplier must provide item {i} within {i + 2} business days of the order."
           for i in range(1, 9)]


def dense_package():
    page = "\n\n".join(CLAUSES)
    text = f"[[SOURCE: {DOC} | PAGE: 1]]\n{page}\n"
    return build_package([{"name": DOC, "text": text, "meta": {"page_count": 1}}], data_class="SYNTHETIC")


def analyst(max_clauses: int | None, calls: list):
    """Answers with one finding per clause in the unit; raises the output-limit
    error when the unit holds more than `max_clauses` clauses (None = always)."""
    def respond(purpose, system, user, schema):
        calls.append(purpose)
        body = user[user.index("Extract every material provision"):]
        found = [c for c in CLAUSES if c in body]
        if max_clauses is None or len(found) > max_clauses:
            raise ProviderOutputLimit("output limit reached before the answer was complete")
        ids = re.findall(r"SECTION_ID: (\S+) \|", body)
        return {"findings": [{"document": DOC, "page": "1", "quote": c, "statement": c, "category": "DELIVERABLE"}
                             for c in found],
                "sections": [{"section_id": i, "status": "HAS_FINDINGS", "note": ""} for i in ids]}
    return ScriptedAnalyst(respond, name="A")


@pytest.fixture(autouse=True)
def big_units(monkeypatch):
    # keep the dense page as one unit so the reactive split is what is tested
    monkeypatch.setenv("ENGINE_UNIT_CHARS", "100000")


def test_split_text_cuts_on_a_paragraph_boundary_and_keeps_verbatim_halves():
    text = "\n\n".join(CLAUSES)
    a, b = split_text(text)
    assert a.endswith(CLAUSES[3]) and b.startswith(CLAUSES[4])
    assert a in text and b in text
    assert split_text("x") is None and split_text("nobreakshere" * 10) is None


def test_output_limit_bisects_and_succeeds_when_both_halves_succeed():
    calls, pkg = [], dense_package()
    inv = extraction.extract(analyst(4, calls), pkg, UsageLedger("t", path=""), tag="A", concurrency=1)
    assert calls == ["extract:U1", "extract:U1s1", "extract:U1s2"]
    assert inv["gaps"] == []
    assert sorted(f["quote"] for f in inv["findings"]) == sorted(CLAUSES)
    assert len({f["id"] for f in inv["findings"]}) == len(CLAUSES)
    assert [a["section_id"] for a in inv["accounts"]] == [pkg.documents[0].locations[0].loc_id]
    for f in inv["findings"]:   # halves are slices of the page: quotes verify against the whole page
        assert locate_quote(pkg, f["quote"], DOC, "1")["status"] == "VERIFIED"


def test_two_levels_of_bisection_are_used_when_needed():
    calls = []
    inv = extraction.extract(analyst(2, calls), dense_package(), UsageLedger("t", path=""), tag="A",
                             concurrency=1)
    assert len(calls) == 1 + 2 + 4
    assert inv["gaps"] == [] and len(inv["findings"]) == len(CLAUSES)


def test_max_split_depth_fails_cleanly_without_looping():
    calls, pkg = [], dense_package()
    inv = extraction.extract(analyst(None, calls), pkg, UsageLedger("t", path=""), tag="A", concurrency=1)
    assert MAX_TEXT_SPLITS == 2
    assert len(calls) == 1 + 2 + 4          # bounded: never more than two levels of halving
    assert inv["findings"] == []
    assert len(inv["gaps"]) == 1            # one failure per location, not one per part
    gap = inv["gaps"][0]
    assert gap["loc_id"] == pkg.documents[0].locations[0].loc_id
    assert gap["reason"].startswith("extraction failed") and "output limit" in gap["reason"]


def test_partial_success_still_reports_the_location_as_failed():
    calls = []

    def respond(purpose, system, user, schema):
        calls.append(purpose)
        body = user[user.index("Extract every material provision"):]
        if CLAUSES[0] in body:
            raise ProviderOutputLimit("output limit reached before the answer was complete")
        ids = re.findall(r"SECTION_ID: (\S+) \|", body)
        return {"findings": [{"document": DOC, "page": "1", "quote": c} for c in CLAUSES if c in body],
                "sections": [{"section_id": i, "status": "HAS_FINDINGS", "note": ""} for i in ids]}
    inv = extraction.extract(ScriptedAnalyst(respond, name="A"), dense_package(), UsageLedger("t", path=""),
                             tag="A", concurrency=1)
    assert len(calls) == 1 + 2 + 2          # only the failing half is split again
    assert len(inv["findings"]) == len(CLAUSES) - 2
    assert [g["reason"][:17] for g in inv["gaps"]] == ["extraction failed"]


def test_oversized_location_is_read_in_parts_up_front(monkeypatch):
    monkeypatch.setenv("ENGINE_UNIT_CHARS", "400")
    calls = []
    inv = extraction.extract(analyst(8, calls), dense_package(), UsageLedger("t", path=""), tag="A", concurrency=1)
    assert all(re.fullmatch(r"extract:U1p\d+", c) for c in calls) and len(calls) > 1
    assert inv["gaps"] == [] and sorted(f["quote"] for f in inv["findings"]) == sorted(CLAUSES)


class _Stream:
    def __init__(self, msg):
        self.msg = msg

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self.msg


def test_anthropic_max_tokens_raises_output_limit_without_retrying():
    from types import SimpleNamespace as NS
    attempts = []
    msg = NS(stop_reason="max_tokens", content=[], _request_id="r1",
             usage=NS(input_tokens=10, output_tokens=32000, cache_read_input_tokens=0,
                      cache_creation_input_tokens=0))

    def stream(**kw):
        attempts.append(kw["max_tokens"])
        return _Stream(msg)
    client = NS(messages=NS(stream=stream))
    a = AnthropicAnalyst(client=client, name="claude-primary")
    with pytest.raises(ProviderOutputLimit) as err:
        a.call_json("s", "u", {}, purpose="extract:U8", ledger=UsageLedger("t", path=""), data_class="SYNTHETIC")
    assert "failed for extract:U8: output limit reached" in str(err.value)
    assert attempts == [32000]              # the same request is not repeated
