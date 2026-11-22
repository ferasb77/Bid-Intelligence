"""Engine mechanics with synthetic documents and scripted analysts (no model calls)."""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import engine_synthetic as S  # noqa: E402

from engine import adjudicate as adj  # noqa: E402
from engine import conflicts as cf  # noqa: E402
from engine import pipeline, register as rg, reports  # noqa: E402
from engine.package import build_package, units  # noqa: E402
from engine.providers import (Analyst, OpenAIAnalyst, ProviderNotAuthorized, ScriptedAnalyst,  # noqa: E402
                              UsageLedger)
from engine.render import render  # noqa: E402
from engine.verify import locate_quote, value_issues, verify_finding  # noqa: E402


def pkg(data_class="SYNTHETIC"):
    return build_package(S.documents(), data_class=data_class)


def ledger():
    return UsageLedger("test", path="")


def roles(adjudicator=None):
    return pipeline.EngineRoles(primary=ScriptedAnalyst(S.responder("A"), name="A"),
                                independent=ScriptedAnalyst(S.responder("B"), name="B", provider="scripted-b"),
                                adjudicator=adjudicator or ScriptedAnalyst(S.adjudicator(), name="adj"))


# ── package ────────────────────────────────────────────────────────────────

def test_package_locations_and_readability():
    p = build_package([
        {"name": "a.pdf", "text": "[[SOURCE: a.pdf | PAGE: 1]]\nSome real text on the first page of the document.\n"
                                  "[[SOURCE: a.pdf | PAGE: 3 | OCR: tesseract]]\nRecognised text of a scanned page here.",
         "meta": {"page_count": 3, "ocr": {"status": "APPLIED", "pages": [3]}}},
        {"name": "b.docx", "text": "[[SOURCE: b.docx | SECTION: Terms]]\nBidders must sign.\n"
                                   "[[SOURCE: b.docx | TABLE]] Item | Qty\n"},
        {"name": "c.pdf", "text": "[[SOURCE: c.pdf]]\n[Scanned PDF: no text layer; Arabic OCR is not available on "
                                  "this server]"}])
    st = {(l.doc, l.label): l.status for l in p.locations}
    assert st[("a.pdf", "2")] == "MISSING"          # a page with no text is never silently skipped
    assert st[("a.pdf", "3")] == "OCR"
    assert st[("c.pdf", "1")] == "UNREADABLE"
    assert "Item | Qty" in p.find_location("b.docx", "Terms").text
    assert p.readability()["complete"] is False


def test_units_never_cut_a_page_and_cover_every_location():
    p = pkg()
    us = units(p, max_chars=200)
    assert sorted(l.loc_id for u in us for l in u.locations) == sorted(l.loc_id for l in p.locations)


# ── verification ───────────────────────────────────────────────────────────

def test_quote_verification_and_relocation():
    p = pkg()
    assert locate_quote(p, "Late proposals will not be considered", "Synthetic_RFP.pdf", "2")["status"] == "VERIFIED"
    assert locate_quote(p, "Late proposals will not be considered", "Synthetic_RFP.pdf", "3")["status"] == "RELOCATED"
    assert locate_quote(p, "Late proposals will be considered", "Synthetic_RFP.pdf", "2")["status"] == "NOT_FOUND"
    assert locate_quote(p, "Technical quality 70% ... price 30%", "Synthetic_RFP.pdf", "3")["status"] == "VERIFIED"


def test_figures_must_come_from_the_quote():
    f = {"statement": "Proposals are due by 16 March 2027.", "quote": "no later than 15 March 2027 at 12:00",
         "values": [{"kind": "DATE", "text": "15 March 2027", "normalized": ""}]}
    assert any("16" in i for i in value_issues(f))
    f["statement"] = "Proposals are due no later than 15 March 2027 at 12:00."
    assert value_issues(f) == []


# ── register ───────────────────────────────────────────────────────────────

def _inv(tag, fs):
    p = pkg()
    return {"tag": tag, "findings": [verify_finding(p, dict(f, id=f"{tag}-{i}", analyst=tag)) for i, f in enumerate(fs)]}


def test_reconciliation_agree_dispute_single():
    reg = rg.reconcile(_inv("A", S.BASE + [S.BRIEFING_A]), _inv("B", S.BASE + [S.BRIEFING_B] + S.B_EXTRA))
    by = {e["statement"]: e for e in reg["entries"]}
    assert by["Bidders must be registered non-profit organisations."]["status"] == "AGREED"
    brief = next(e for e in reg["entries"] if "briefing" in e["statement"])
    assert brief["status"] == "DISPUTED" and any("modal force" in d for d in brief["differences"])
    sec = next(e for e in reg["entries"] if e["category"] == "GUARANTEE")
    assert sec["status"] == "SINGLE_B"                       # kept although A missed it
    assert rg.needs_adjudication(sec, dual=True)


def test_similar_wording_is_not_merged_and_different_values_dispute():
    a = dict(S.BASE[4])
    b = dict(S.BASE[4], values=[{"kind": "DATE", "text": "15 March 2027", "normalized": "2027-03-16"}])
    reg = rg.reconcile(_inv("A", [a, S.BASE[8]]), _inv("B", [b, S.BASE[8]]))
    dl = [e for e in reg["entries"] if e["category"] == "DEADLINE"]
    assert len(dl) == 2                                      # two deadlines with similar wording stay distinct
    assert next(e for e in dl if "15 March" in e["statement"])["status"] == "DISPUTED"


# ── adjudication safeguards ────────────────────────────────────────────────

def _one_entry(status="SINGLE_A"):
    reg = rg.reconcile(_inv("A", [S.BASE[5]]), None)
    e = reg["entries"][0]
    return reg["entries"], e


def test_unverifiable_correction_is_rejected():
    entries, e = _one_entry()
    adj._apply(pkg(), e, {"decision": "CORRECTED", "statement": "Late proposals must be returned unopened.",
                          "quote": "Late proposals will be returned unopened", "modality": "MUST"}, {})
    assert e["statement"] == "Late proposals will not be considered." and e["adjudication"]["accepted"] is False


def test_unsupported_interpretation_keeps_the_verified_provision():
    entries, e = _one_entry()
    adj._apply(pkg(), e, {"decision": "UNSUPPORTED", "reason": "x"}, {})
    assert e in entries and e["applicability"] == "EXCLUDED_UNSUPPORTED"
    comp = reports.compose(entries, an={}, conflicts={}, readability={}, run_meta={})
    row = next(r for r in comp["ledger"]["rows"] if r["entry_id"] == e["entry_id"])
    assert row["reason"].startswith("excluded unsupported")   # traceable, not erased


# ── conflicts and amendments ───────────────────────────────────────────────

def _deadline_entries():
    reg = rg.reconcile(_inv("A", [S.BASE[4], S.BASE[8], S.BASE[7]]), None)
    return reg["entries"]


def _conflict_adjudicator(authority_quote):
    def respond(purpose, system, user, schema):
        import re
        c = re.findall(r"^(C\d+) \(noted", user, re.M)[0]
        lines = re.findall(r"^(E\d+) \|(.*)$", user.split("CANDIDATES:")[1], re.M)
        new = [i for i, rest in lines if "22 March" in rest]
        old = [i for i, rest in lines if "22 March" not in rest]
        return {"relationships": [{"candidate_id": c, "type": "EXPRESS_AMENDMENT", "prevailing_entry": new[0],
                                   "superseded_entries": old, "authority_quote": authority_quote,
                                   "authority_document": "", "issue": "deadline", "clarification_question": "When?",
                                   "implication": "uncertain deadline"}]}
    return ScriptedAnalyst(respond)


def test_precedence_needs_verifiable_authority():
    entries = _deadline_entries()
    out = cf.resolve(_conflict_adjudicator("The later document always prevails."), pkg(), entries, [], ledger())
    assert out["amendments"] == [] and out["conflicts"]       # recency alone never establishes precedence
    assert {e["applicability"] for e in entries if e["category"] == "DEADLINE"} == {"CONFLICTED"}


def test_express_amendment_supersedes_with_previous_value():
    entries = _deadline_entries()
    out = cf.resolve(_conflict_adjudicator("The submission deadline in Section 3 is amended to 22 March 2027"),
                     pkg(), entries, [], ledger())
    assert len(out["amendments"]) == 1
    old = next(e for e in entries if "15 March" in e["statement"])
    new = next(e for e in entries if "22 March" in e["statement"])
    assert old["applicability"] == "SUPERSEDED" and new["previous"][0]["entry_id"] == old["entry_id"]


# ── end-to-end and verification status ─────────────────────────────────────

def test_end_to_end_synthetic_run():
    r = pipeline.run(pkg(), roles(), ledger=ledger())
    assert r.record["status"] == "COMPLETE"
    assert r.record["verification"] == "SYNTHETIC"           # scripted output is never labelled intelligence
    assert r.composed["ledger"]["complete"]
    fast_text = str(r.composed["fast"])
    assert "A bid security of 2%" in fast_text                # single-analyst critical finding reaches FAST
    assert "1 April 2027" not in fast_text                    # unsupported summary figure dropped
    assert any("1 April 2027" in x["text"] for x in r.analysis["rejected"])
    brief = next(e for e in r.register["entries"] if "briefing" in e["statement"])
    assert brief["modality"] == "WILL"                        # 'will' was not turned into 'must'
    assert render(r.composed["fast"])[:4] == b"%PDF" and render(r.composed["full"])[:4] == b"%PDF"


class _Real(ScriptedAnalyst):
    """Scripted, but flagged as a real model, to test status computation only."""

    def __init__(self, responder, provider, name):
        super().__init__(responder, name=name, provider=provider, model=f"{provider}-model")
        self.synthetic = False


def test_unauthorized_independent_analyst_never_yields_verified(monkeypatch):
    monkeypatch.delenv("ENGINE_OPENAI_CLIENT_DATA_AUTHORIZED", raising=False)
    rl = pipeline.EngineRoles(primary=_Real(S.responder("A"), "anthropic", "A"),
                              independent=OpenAIAnalyst(model="any", api_key="x"),
                              adjudicator=_Real(S.adjudicator(), "anthropic", "adj"))
    r = pipeline.run(pkg("CLIENT"), rl, ledger=ledger())
    assert r.record["verification"] == "SINGLE_ANALYST"
    assert "ProviderNotAuthorized" == r.inventories["errors"]["B"]["kind"]
    assert r.composed["fast"]["verification"]["status"] == "SINGLE_ANALYST"


def test_dual_real_analysts_complete_package_is_verified():
    rl = pipeline.EngineRoles(primary=_Real(S.responder("A"), "anthropic", "A"),
                              independent=_Real(S.responder("B"), "openai", "B"),
                              adjudicator=_Real(S.adjudicator(), "anthropic", "adj"))
    r = pipeline.run(pkg("CLIENT"), rl, ledger=ledger())
    assert r.record["verification"] == "INDEPENDENTLY_VERIFIED", r.record["limitations"]


def test_failed_independent_pass_is_not_verified():
    def boom(*a):
        raise RuntimeError("provider down")
    rl = pipeline.EngineRoles(primary=_Real(S.responder("A"), "anthropic", "A"),
                              independent=_Real(boom, "openai", "B"),
                              adjudicator=_Real(S.adjudicator(), "anthropic", "adj"))
    r = pipeline.run(pkg("CLIENT"), rl, ledger=ledger())
    assert r.record["verification"] != "INDEPENDENTLY_VERIFIED"


def test_openai_refuses_client_documents_without_authorization(monkeypatch):
    monkeypatch.delenv("ENGINE_OPENAI_CLIENT_DATA_AUTHORIZED", raising=False)
    with pytest.raises(ProviderNotAuthorized):
        OpenAIAnalyst(model="m", api_key="k").check_allowed("CLIENT")
    monkeypatch.setenv("ENGINE_OPENAI_CLIENT_DATA_AUTHORIZED", "yes")
    OpenAIAnalyst(model="m", api_key="k").check_allowed("CLIENT")


def test_cost_ledger_prices_known_models_and_flags_unknown():
    lg = ledger()
    from engine.providers import Usage
    lg.add(Usage("anthropic", "claude-opus-5-5", "x", input_tokens=1_000_000, output_tokens=100_000))
    lg.add(Usage("openai", "unknown", "y", input_tokens=10))
    s = lg.summary()
    assert s["by_model"]["anthropic:claude-opus-5-5"]["cost_usd"] == 6.0
    assert s["cost_complete"] is False


def test_amendment_is_reported_with_the_provision_it_changes():
    entries = _deadline_entries()
    cf.resolve(_conflict_adjudicator("The submission deadline in Section 3 is amended to 22 March 2027"),
               pkg(), entries, [], ledger())
    new = next(e for e in entries if "22 March" in e["statement"])
    new["category"], new["materiality"] = "AMENDMENT", "MATERIAL"
    comp = reports.compose(entries, an={}, conflicts={}, readability={}, run_meta={})
    fast = next(s for s in comp["fast"]["sections"] if s["title"].startswith("Submission"))
    assert any(new["entry_id"] in it["entry_ids"] for it in fast["items"])
    assert comp["ledger"]["complete"]


def test_review_withdraws_overstated_analysis_point():
    an = {"points": [{"heading": "h", "analysis": "x", "entry_ids": ["E001", "E002"]},
                     {"heading": "k", "analysis": "y", "entry_ids": ["E003"]}], "rejected": []}
    entries = [{"entry_id": i} for i in ("E001", "E002", "E003")]
    from engine import review
    out = review.apply_corrections(pkg(), entries, [{"type": "MISLEADING_ANALYSIS", "entry_ids": ["E002"],
                                                     "description": "stronger than source"}], an)
    assert [p["heading"] for p in an["points"]] == ["k"] and out["applied"]


def test_near_empty_page_is_disclosed():
    p = build_package([{"name": "a.txt", "text": "[[SOURCE: a.txt | PAGE: 1]]\n" + "Bidders must register. " * 5 +
                        "\n[[SOURCE: a.txt | PAGE: 2]]\n", "meta": {}}])
    assert [x["status"] for x in p.readability()["problems"]] == ["NEAR_EMPTY"]


def test_failed_primary_extraction_never_reports_complete():
    def no_credit(purpose, system, user, schema):
        if purpose.startswith("extract"):
            raise RuntimeError("Your credit balance is too low")
        return S.responder("A")(purpose, system, user, schema)
    r = pipeline.run(pkg(), pipeline.EngineRoles(primary=ScriptedAnalyst(no_credit, name="A"), independent=None,
                                                 adjudicator=ScriptedAnalyst(S.adjudicator(), name="adj")),
                     ledger=ledger())
    assert r.record["status"] == "FAILED" and r.record["verification"] == "FAILED"
    assert "primary extraction failed" in r.record["error"]["message"]


def test_account_errors_stop_the_run():
    from engine.providers import _account_problem

    class E(Exception):
        def __init__(self, code, msg):
            super().__init__(msg)
            self.status_code = code
    assert _account_problem(E(400, "Your credit balance is too low to access the Anthropic API"))
    assert _account_problem(E(401, "invalid x-api-key"))
    assert not _account_problem(E(400, "prompt is too long"))
    assert not _account_problem(E(529, "overloaded"))


# ── OpenAI analyst interface (fake client; synthetic documents only) ───────

class _FakeResponses:
    def __init__(self, responder):
        self.responder, self.calls = responder, []

    def create(self, **kw):
        import json as _j
        from types import SimpleNamespace as NS
        self.calls.append(kw)
        purpose_hint = "package_review" if "YOUR FINDINGS" in kw["input"] else (
            "extract:U" if "SECTION_ID" in kw["input"] else "other")
        data = self.responder(purpose_hint, kw["instructions"], kw["input"], kw["text"]["format"]["schema"])
        return NS(id="resp_test", status="completed", output_text=_j.dumps(data),
                  usage=NS(input_tokens=1000, output_tokens=200, input_tokens_details=NS(cached_tokens=400)))


def _openai_fake(responder):
    from types import SimpleNamespace as NS
    fr = _FakeResponses(responder)
    return OpenAIAnalyst(model="test-model", client=NS(responses=fr), name="openai-independent", max_attempts=1), fr


def _openai_prices(monkeypatch):
    # the run cost cap refuses real-provider calls whose model has no price
    monkeypatch.setenv("ENGINE_OPENAI_PRICE_IN", "1.0")
    monkeypatch.setenv("ENGINE_OPENAI_PRICE_OUT", "4.0")


def test_openai_request_shape_and_usage_accounting(monkeypatch):
    _openai_prices(monkeypatch)
    oa, fr = _openai_fake(S.responder("B"))
    lg = ledger()
    inv = __import__("engine.extraction", fromlist=["x"]).extract(oa, pkg(), lg, tag="B")
    kw = fr.calls[0]
    assert kw["store"] is False                                   # no retention of package text
    assert kw["text"]["format"]["strict"] is True and kw["text"]["format"]["type"] == "json_schema"
    assert kw["model"] == "test-model" and isinstance(kw["input"], str)
    assert inv["findings"] and not inv["gaps"]
    s = lg.summary()["by_model"]["openai:test-model"]
    assert s["input_tokens"] == 600 * len(fr.calls) and s["cache_read_tokens"] == 400 * len(fr.calls)


def test_dual_provider_synthetic_run_with_openai_interface(monkeypatch):
    _openai_prices(monkeypatch)
    oa, _ = _openai_fake(S.responder("B"))
    rl = pipeline.EngineRoles(primary=ScriptedAnalyst(S.responder("A"), name="A"), independent=oa,
                              adjudicator=ScriptedAnalyst(S.adjudicator(), name="adj"))
    r = pipeline.run(pkg(), rl, ledger=ledger())
    assert r.record["status"] == "COMPLETE" and r.record["verification"] == "SYNTHETIC"
    assert any(e["status"] == "AGREED" for e in r.register["entries"])


def test_openai_client_documents_blocked_before_any_request(monkeypatch):
    monkeypatch.delenv("ENGINE_OPENAI_CLIENT_DATA_AUTHORIZED", raising=False)
    oa, fr = _openai_fake(S.responder("B"))
    with pytest.raises(ProviderNotAuthorized):
        oa.call_json("s", "u", {}, purpose="x", ledger=ledger(), data_class="CLIENT")
    assert fr.calls == []


def test_openai_strict_schemas_are_closed_and_fully_required():
    from engine import schema as sc

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
    for name in ("EXTRACTION_OUTPUT", "PACKAGE_REVIEW_OUTPUT", "ADJUDICATION_OUTPUT", "REVIEW_OUTPUT",
                 "ANALYSIS_OUTPUT"):
        walk(getattr(sc, name))


# ── fail-closed ────────────────────────────────────────────────────────────

def test_configured_independent_failure_fails_the_run():
    oa, fr = _openai_fake(S.responder("B"))

    def boom(**kw):
        raise RuntimeError("upstream error")
    fr.create = boom
    r = pipeline.run(pkg(), pipeline.EngineRoles(primary=ScriptedAnalyst(S.responder("A"), name="A"),
                                                 independent=oa,
                                                 adjudicator=ScriptedAnalyst(S.adjudicator(), name="adj")),
                     ledger=ledger())
    assert r.record["status"] == "FAILED" and r.record["verification"] == "FAILED"


def test_unconfigured_independent_is_single_analyst_not_failure(monkeypatch):
    monkeypatch.delenv("ENGINE_OPENAI_MODEL", raising=False)
    r = pipeline.run(pkg(), pipeline.EngineRoles(primary=_Real(S.responder("A"), "anthropic", "A"),
                                                 independent=OpenAIAnalyst(model="", api_key=""),
                                                 adjudicator=_Real(S.adjudicator(), "anthropic", "adj")),
                     ledger=ledger())
    assert r.record["status"] == "COMPLETE" and r.record["verification"] == "SINGLE_ANALYST"


def test_adjudication_failure_fails_the_run():
    base = S.adjudicator()

    def adj_fail(purpose, system, user, schema):
        if purpose.startswith("adjudicat"):
            raise RuntimeError("model error")
        return base(purpose, system, user, schema)
    r = pipeline.run(pkg(), roles(ScriptedAnalyst(adj_fail, name="adj")), ledger=ledger())
    assert r.record["status"] == "FAILED" and "adjudication failed" in r.record["error"]["message"]


def test_review_failure_fails_the_run():
    base = S.adjudicator()

    def rev_fail(purpose, system, user, schema):
        if purpose == "final_review":
            raise RuntimeError("model error")
        return base(purpose, system, user, schema)
    r = pipeline.run(pkg(), roles(ScriptedAnalyst(rev_fail, name="adj")), ledger=ledger())
    assert r.record["status"] == "FAILED" and "final review failed" in r.record["error"]["message"]


def test_every_category_has_a_full_report_section():
    from engine import schema
    # ENAB-47: required documents are reported in the Section 8 tick-box checklist (FULL_CHECKLIST)
    placed = {c for _, subs in reports.FULL_SECTIONS for _, cats in subs for c in cats} | set(reports.FULL_CHECKLIST)
    assert set(schema.CATEGORIES) <= placed, set(schema.CATEGORIES) - placed
