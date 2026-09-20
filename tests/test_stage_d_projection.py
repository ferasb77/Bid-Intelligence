"""Deterministic projection, boundary, authority, and private recovery tests."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import contract_hygiene
import extractor
import stage_d_checkpoints as cp
import stage_d_projection as proj


@pytest.fixture(autouse=True)
def checkpoint_off(monkeypatch):
    monkeypatch.setenv("CHECKPOINT_MODE", "off")
    monkeypatch.delenv("CHECKPOINT_ROOT", raising=False)


@pytest.fixture(autouse=True)
def no_live_telemetry_client(monkeypatch):
    """Phase 4 (BI Context & Token Optimization Program): Stage D's
    execute_messages_create call site now carries a telemetry_context, so
    a mocked-away model call would otherwise still try to construct a real
    database.get_client() when this file's tests don't mock database.py at
    all. Keep it a true no-op here (this file already asserts nothing
    about telemetry -- tests/test_model_telemetry.py owns that)."""
    monkeypatch.setattr("database.create_model_usage_event", lambda event: None, raising=False)


def ctx(projection):
    return proj.expand_prompt_context(projection["prompt_context"])


def facts():
    return {
        "doc_metadata": {"title": "Service tender", "client": "Buyer"},
        "requirements": [{"req_id": "M1", "category": "Mandatory",
                          "requirement_type": "Delivery / SLA", "description": "Provide support.",
                          "evidence": "Submit a support procedure.", "qual_status": "UNKNOWN",
                          "evidence_status": "MISSING", "source_refs": [
                              {"source_doc": "scope.pdf", "page": 2, "excerpt": "Provide support.",
                               "verified": True, "cells": "A2:A4"}]}],
        "dates": [{"milestone": "Closing", "date": None}],
        "evaluation_criteria": [{"stage": "Technical", "parent_stage": None, "weight": "70 points",
                                 "weight_basis": "Overall", "threshold": "50 points", "source_refs": []}],
        "submission_rules": [{"item": "Response", "details": "Upload the response.", "format": "PDF",
                              "artifact_type": "Proposal / Response", "mandatory": 1,
                              "mandatory_observations": [1, 0], "mandatory_conflict": True}],
        "deliverables": [{"title": "Support", "description": "Operate support services."}],
        "commercial_clauses": [{"topic": "Term", "details": "One year."}],
        "contract_risks": [{"risk": "Liability", "details": "Uncapped liability."}],
    }


def conflicts():
    return [{"conflict_id": "CONF-DATE-1", "conflict_type": "DATE_CONFLICT",
             "classification": "TRUE_CONFLICT", "source_validity": "PHYSICAL_BOTH",
             "source_a": {"doc": "a.pdf", "ref": "Closing", "text": "Close on 1 October."},
             "source_b": {"doc": "b.pdf", "ref": "Closing", "text": "Close on 3 October."}}]


def empty_response():
    return {"synthesis": {
        "bid": {"title": None, "client": None, "file_number": None, "owner": None,
                "sensitivity": "Standard", "submission_deadline": None, "clarification_deadline": None,
                "value_cad": None, "notes": None},
        "brief": {"executive_summary": None, "opportunity_type": None, "contract_term": "Not stated",
                  "procurement_model": None, "scope_categories": []}, "outline": [],
        "risk_assessments": []}, "citations": []}


def supported_response(projection):
    response = empty_response()
    req = ctx(projection)["requirements"][0]
    response["synthesis"]["brief"]["executive_summary"] = "The buyer requires support."
    response["citations"] = [{"output_pointer": "/brief/executive_summary", "supports": [
        {"entity_id": req["requirement_id"], "field_pointer": "/description", "evidence_refs": req["evidence_refs"]}]}]
    return response


def support_id(projection, entity_id, field_pointer):
    catalog = proj._support_catalog(projection["prompt_context"]["support_pointer_sets"])
    return next(key for key, pair in catalog.items() if pair == (entity_id, field_pointer))


def model_client(response=None, stop_reason="end_turn"):
    client = MagicMock()
    client.with_options.return_value = client
    raw = json.dumps(empty_response() if response is None else response)
    client.messages.create.return_value = SimpleNamespace(
        content=[SimpleNamespace(type="text", text=raw)], stop_reason=stop_reason)
    return client


def canonical_mechanic_facts():
    from canonical_opportunity import build_canonical_opportunity, resolve_canonical_opportunity
    nf = facts()
    text = "[[SOURCE: mechanics.pdf | PAGE: 1]]\nRequest for advisory support through an RFP."
    raw = [{"typed_observations": [{"family": "PROCUREMENT_MECHANIC", "semantic_kind": "RFP",
        "original_value": "RFP", "source_doc": "mechanics.pdf",
        "source_refs": [{"source_doc": "mechanics.pdf", "page": 1, "excerpt": "RFP"}]}]}]
    nf["_canonical_opportunity"] = resolve_canonical_opportunity(build_canonical_opportunity(raw,
        {"files": ["mechanics.pdf"], "doc_metadata": {"mechanics.pdf": {"page_count": 1}}, "doc_texts": {"mechanics.pdf": text}}))
    return nf


def canonical_tier2_response(projection):
    response = empty_response()
    mechanic = ctx(projection)["canonical_opportunity"]["observations"][0]
    response["synthesis"]["brief"]["opportunity_type"] = "Advisory"
    response["citations"] = [{"output_pointer": "/brief/opportunity_type", "supports": [{
        "entity_id": mechanic["observation_id"], "field_pointer": "/original_value",
        "evidence_refs": mechanic["evidence_refs"]}]}]
    return response


def test_canonical_mechanic_observation_is_citable_for_tier2():
    p = proj.build_stage_d_synthesis_projection(canonical_mechanic_facts(), [])
    assert proj.validate_stage_d_response(canonical_tier2_response(p), p)["status"] == "VALIDATED"


def test_unknown_canonical_alias_is_rejected():
    p = proj.build_stage_d_synthesis_projection(canonical_mechanic_facts(), [])
    response = canonical_tier2_response(p); response["citations"][0]["supports"][0]["entity_id"] = "o999"
    with pytest.raises(proj.ProjectionValidationError, match="UNKNOWN_ENTITY_ID"):
        proj.validate_stage_d_response(response, p)


def test_canonical_wrong_owner_and_hidden_pointer_are_rejected():
    p = proj.build_stage_d_synthesis_projection(canonical_mechanic_facts(), [])
    response = canonical_tier2_response(p)
    requirement = ctx(p)["requirements"][0]
    response["citations"][0]["supports"][0]["evidence_refs"] = requirement["evidence_refs"]
    with pytest.raises(proj.ProjectionValidationError, match="WRONG_EVIDENCE_OWNER"):
        proj.validate_stage_d_response(response, p)
    response = canonical_tier2_response(p); response["citations"][0]["supports"][0]["field_pointer"] = "/document_role_basis"
    with pytest.raises(proj.ProjectionValidationError, match="UNPUBLISHED_SUPPORT_POINTER"):
        proj.validate_stage_d_response(response, p)


def test_tier2_cannot_be_supported_only_by_unrelated_requirement():
    p = proj.build_stage_d_synthesis_projection(canonical_mechanic_facts(), [])
    response = empty_response(); requirement = ctx(p)["requirements"][0]
    response["synthesis"]["brief"]["opportunity_type"] = "Advisory"
    response["citations"] = [{"output_pointer": "/brief/opportunity_type", "supports": [{"entity_id": requirement["requirement_id"],
        "field_pointer": "/description", "evidence_refs": requirement["evidence_refs"]}]}]
    with pytest.raises(proj.ProjectionValidationError, match="UNSUPPORTED_TIER2_CLASSIFICATION"):
        proj.validate_stage_d_response(response, p)


def test_mechanic_contradiction_disables_stage_d_tier2_schema():
    from canonical_opportunity import build_canonical_opportunity, resolve_canonical_opportunity
    nf = facts()
    text = "[[SOURCE: mechanics.pdf | PAGE: 1]]\nsingle supplier and multiple supplier"
    raw = [{"typed_observations": [{"family": "PROCUREMENT_MECHANIC", "semantic_kind": kind,
        "original_value": value, "source_doc": "mechanics.pdf",
        "source_refs": [{"source_doc": "mechanics.pdf", "page": 1, "excerpt": value}]}
        for kind, value in (("SINGLE_SUPPLIER_AWARD", "single supplier"), ("MULTIPLE_SUPPLIER_AWARD", "multiple supplier"))]}]
    nf["_canonical_opportunity"] = resolve_canonical_opportunity(build_canonical_opportunity(raw,
        {"files": ["mechanics.pdf"], "doc_metadata": {"mechanics.pdf": {"page_count": 1}}, "doc_texts": {"mechanics.pdf": text}}))
    p = proj.build_stage_d_synthesis_projection(nf, nf["_canonical_opportunity"]["conflicts"])
    assert nf["_canonical_opportunity"]["resolved"]["procurement_model"]["status"] == "CONFLICTED"
    schema = proj.stage_d_output_config(p)["format"]["schema"]
    assert schema["properties"]["synthesis"]["properties"]["brief"]["properties"]["procurement_model"] == {"type": "null"}


def test_canonical_date_conflict_projects_structured_values_losslessly():
    text = "[[SOURCE: dates.pdf | PAGE: 1]]\n2030-10-01 and 2030-10-03"
    raw = [{"typed_observations": [{"family": "MILESTONE", "semantic_kind": "SUBMISSION_DEADLINE",
        "original_value": value, "date": value, "precision": "DATE", "source_doc": "dates.pdf",
        "source_refs": [{"source_doc": "dates.pdf", "page": 1, "excerpt": value}]} for value in ("2030-10-01", "2030-10-03")]}]
    metadata = {"files": ["dates.pdf"], "doc_metadata": {"dates.pdf": {"page_count": 1}}, "doc_texts": {"dates.pdf": text}}
    nf = extractor.normalize_package_facts(raw, metadata)
    conflicts = extractor.reconcile_package_facts(nf, ["dates.pdf"])
    canonical_conflict = next(c for c in conflicts if c.get("affected_fields") == ["/resolved/submission_deadline"])
    p = proj.build_stage_d_synthesis_projection(nf, conflicts)
    expanded = proj.expand_prompt_context(p["prompt_context"])
    projected = next(c for c in expanded["detected_conflicts"] if c["incompatible_values"] == canonical_conflict["incompatible_values"])
    assert projected["incompatible_values"] == [
        {"date": "2030-10-01", "precision": "DATE", "time": None, "timezone": None},
        {"date": "2030-10-03", "precision": "DATE", "time": None, "timezone": None},
    ]


def test_canonical_money_conflict_projects_structured_values_losslessly():
    from canonical_opportunity import build_canonical_opportunity, resolve_canonical_opportunity
    text = "[[SOURCE: money.pdf | PAGE: 1]]\nCAD 100 exclusive and USD 200 inclusive"
    raw = [{"typed_observations": [{"family": "MONETARY", "semantic_kind": "ESTIMATED_CONTRACT_VALUE",
        "original_value": amount, "amount": amount, "currency": currency, "tax_basis": tax, "source_doc": "money.pdf",
        "source_refs": [{"source_doc": "money.pdf", "page": 1, "excerpt": excerpt}]}
        for amount, currency, tax, excerpt in (("100", "CAD", "EXCLUSIVE", "CAD 100 exclusive"), ("200", "USD", "INCLUSIVE", "USD 200 inclusive"))]}]
    nf = facts(); nf["_canonical_opportunity"] = resolve_canonical_opportunity(build_canonical_opportunity(raw,
        {"files": ["money.pdf"], "doc_metadata": {"money.pdf": {"page_count": 1}}, "doc_texts": {"money.pdf": text}}))
    conflicts = nf["_canonical_opportunity"]["conflicts"]
    p = proj.build_stage_d_synthesis_projection(nf, conflicts)
    expanded = proj.expand_prompt_context(p["prompt_context"])
    assert expanded["detected_conflicts"][0]["incompatible_values"] == conflicts[0]["incompatible_values"]
    assert all(isinstance(value, dict) for value in expanded["detected_conflicts"][0]["incompatible_values"])


def test_unsupported_nested_conflict_value_fails_closed():
    bad = conflicts()[0]
    bad["incompatible_values"] = [{"date": {"nested": "forbidden"}}]
    with pytest.raises(proj.ProjectionValidationError, match="INVALID_FIELD_TYPE"):
        proj.build_stage_d_synthesis_projection(facts(), [bad])


def test_canonical_evidence_source_pointers_resolve_exactly_and_deterministically():
    nf = canonical_mechanic_facts()
    p = proj.build_stage_d_synthesis_projection(nf, [])
    pointers = []
    for evidence in p["sidecar"]["evidence"].values():
        for pointer in evidence["source_pointers"]:
            if "/_canonical_opportunity/observations/" not in pointer:
                continue
            pointers.append(pointer)
            actual = proj.resolve_pointer(p["sidecar"]["authoritative_inputs"], pointer)
            tokens = pointer.split("/")
            observation = nf["_canonical_opportunity"]["observations"][int(tokens[4])]
            assert actual == observation["source_refs"][int(tokens[-1])]
    assert pointers and all("/observations/obs_" not in pointer for pointer in pointers)
    with pytest.raises(proj.ProjectionValidationError, match="MISSING_POINTER"):
        proj.resolve_pointer(p["sidecar"]["authoritative_inputs"], "/normalized_facts/_canonical_opportunity/observations/999/source_refs/0")

    from canonical_opportunity import build_canonical_opportunity, resolve_canonical_opportunity
    text = "[[SOURCE: mechanics.pdf | PAGE: 1]]\nRFP rate card"
    observations = [{"family": "PROCUREMENT_MECHANIC", "semantic_kind": kind, "original_value": value,
                     "source_doc": "mechanics.pdf", "source_refs": [{"source_doc": "mechanics.pdf", "page": 1, "excerpt": value}]}
                    for kind, value in (("RFP", "RFP"), ("RATE_CARD", "rate card"))]
    meta = {"files": ["mechanics.pdf"], "doc_metadata": {"mechanics.pdf": {"page_count": 1}}, "doc_texts": {"mechanics.pdf": text}}
    projections = []
    for ordered in (observations, list(reversed(observations))):
        candidate = facts()
        candidate["_canonical_opportunity"] = resolve_canonical_opportunity(build_canonical_opportunity(
            [{"typed_observations": ordered}], meta))
        projections.append(proj.build_stage_d_synthesis_projection(candidate, []))
    assert projections[0]["sidecar"]["authoritative_inputs"]["normalized_facts"]["_canonical_opportunity"]["observations"] == projections[1]["sidecar"]["authoritative_inputs"]["normalized_facts"]["_canonical_opportunity"]["observations"]
    pointer_sets = [sorted(pointer for evidence in projection["sidecar"]["evidence"].values() for pointer in evidence["source_pointers"]
                           if "/_canonical_opportunity/observations/" in pointer) for projection in projections]
    assert pointer_sets[0] == pointer_sets[1]


def test_occurrence_bijection_duplicates_and_original_ids():
    nf = facts()
    nf["requirements"] *= 3
    before = copy.deepcopy(nf)
    result = proj.build_stage_d_synthesis_projection(nf, [])
    reqs = ctx(result)["requirements"]
    assert len(reqs) == 3
    assert len({r["requirement_id"] for r in reqs}) == 3
    assert {r["req_id"] for r in reqs} == {"M1"}
    assert sorted(int(result["sidecar"]["prompt_aliases"][r["requirement_id"]].rsplit("-", 1)[1]) for r in reqs) == [1, 2, 3]
    for key, record in result["sidecar"]["requirements"].items():
        assert proj.resolve_pointer(result["sidecar"]["authoritative_inputs"], record["source_pointer"]) == before["requirements"][0]
    assert nf == before


def test_source_refs_shared_owners_and_exact_snapshot():
    nf = facts()
    nf["requirements"].append({**copy.deepcopy(nf["requirements"][0]), "description": "Supply another service."})
    projection = proj.build_stage_d_synthesis_projection(nf, [])
    assert all("source_refs" not in r for r in ctx(projection)["requirements"])
    evidence = list(projection["sidecar"]["evidence"].values())
    assert len(evidence) == 1 and len(evidence[0]["owners"]) == 2
    assert evidence[0]["original"] == nf["requirements"][0]["source_refs"][0]
    assert len(evidence[0]["source_pointers"]) == 2
    assert projection["sidecar"]["authoritative_inputs"]["normalized_facts"] == nf


def test_already_inline_has_no_second_excerpt():
    result = proj.build_stage_d_synthesis_projection(facts(), [])
    inline = next(iter(ctx(result)["evidence_context"].values()))
    assert inline["excerpt_mode"] == "ALREADY_INLINE" and "text" not in inline
    owner = next(r for r in ctx(result)["requirements"] if r["requirement_id"] == inline["owner_id"])
    assert proj.resolve_pointer(owner, inline["field_pointer"]) == "Provide support."


def test_full_excerpt_preserves_final_negation():
    nf = facts()
    excerpt = "Long contractual context. " * 100 + "This does NOT apply to public holidays."
    nf["requirements"][0]["source_refs"][0]["excerpt"] = excerpt
    result = proj.build_stage_d_synthesis_projection(nf, [])
    inline = next(iter(ctx(result)["evidence_context"].values()))
    assert inline["excerpt_mode"] == "FULL" and inline["text"] == excerpt


@pytest.mark.parametrize("ref", [{"source_doc": "a.pdf"}, {"source_doc": "a.pdf", "excerpt": None}, {}])
def test_unavailable_does_not_invent_provenance(ref):
    nf = facts()
    nf["requirements"][0]["source_refs"] = [ref]
    p = proj.build_stage_d_synthesis_projection(nf, [])
    ev = next(iter(ctx(p)["evidence_context"].values()))
    assert ev["excerpt_mode"] == "UNAVAILABLE" and ev["verified"] is None
    assert "page" not in ev and "text" not in ev


def test_reordering_and_refs_order_preserve_ids_and_missing_fields():
    nf = facts()
    nf["requirements"].append({"description": "Other requirement", "source_refs": []})
    nf["requirements"][0]["source_refs"].append({"source_doc": "other.pdf"})
    p1 = proj.build_stage_d_synthesis_projection(nf, [])
    nf["requirements"].reverse()
    nf["requirements"][1]["source_refs"].reverse()
    p2 = proj.build_stage_d_synthesis_projection(nf, [])
    assert {r["requirement_id"] for r in ctx(p1)["requirements"]} == {r["requirement_id"] for r in ctx(p2)["requirements"]}
    assert any("req_id" not in r and "requirement_type" not in r for r in ctx(p2)["requirements"])


@pytest.mark.parametrize("refs", [None, {}, "x", ["bad"], [{"excerpt": 12}], [{"source_doc": []}], [{"page": {"value": 2}}]])
def test_malformed_source_refs_fail(refs):
    nf = facts()
    nf["requirements"][0]["source_refs"] = refs
    with pytest.raises(proj.ProjectionValidationError):
        proj.build_stage_d_synthesis_projection(nf, [])


@pytest.mark.parametrize("section", ["requirements", *proj.FACT_SECTIONS])
def test_unknown_substantive_fields_fail(section):
    nf = facts()
    nf[section][0]["new_obligation"] = "Must not disappear"
    with pytest.raises(proj.ProjectionValidationError, match="UNCLASSIFIED_PROJECTION_FIELD"):
        proj.build_stage_d_synthesis_projection(nf, [])


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), {1: "not a JSON key"}, {1, 2}])
def test_non_json_values_fail(bad):
    with pytest.raises(proj.ProjectionValidationError):
        proj.canonical_json(bad)


def test_collision_fails_hard():
    with patch.object(proj, "digest", return_value="0" * 64):
        with pytest.raises(proj.ProjectionValidationError, match="HASH_COLLISION"):
            proj.build_stage_d_synthesis_projection(facts(), [])


def test_evaluation_and_submission_content_preserved():
    nf = facts()
    nf["evaluation_criteria"][0]["weight_observations"] = [
        {"raw_weight": "70 points", "value": 70, "unit": "Points", "basis": "Overall", "source_refs": [{"source_doc": "eval.pdf", "excerpt": "70 points"}]}]
    nf["evaluation_criteria"][0]["role_observations"] = ["Award Criterion"]
    nf["evaluation_criteria"][0]["weight_conflict"] = True
    p = proj.build_stage_d_synthesis_projection(nf, [])
    for section in ("evaluation_criteria", "submission_rules"):
        out = ctx(p)["facts"][section][0]
        for key, value in nf[section][0].items():
            if key not in ("source_refs", "weight_observations"):
                assert out[key] == value
    observation = ctx(p)["facts"]["evaluation_criteria"][0]["weight_observations"][0]
    assert observation["value"] == 70 and "source_refs" not in observation and observation["evidence_refs"]
    assert p["sidecar"]["authoritative_inputs"]["normalized_facts"] == nf


def test_conflicts_remain_unresolved_and_full():
    c = conflicts()
    p = proj.build_stage_d_synthesis_projection(facts(), c)
    out = ctx(p)["detected_conflicts"][0]
    assert out["resolution_state"] == "UNRESOLVED"
    assert out["source_a"]["text"] == c[0]["source_a"]["text"]
    assert p["sidecar"]["authoritative_inputs"]["conflicts"] == c
    assert {p["sidecar"]["prompt_aliases"][e] for e in out["evidence_refs"]} <= p["sidecar"]["evidence"].keys()


def test_valid_field_citation():
    p = proj.build_stage_d_synthesis_projection(facts(), [])
    response = supported_response(p)
    result = proj.validate_stage_d_response(json.dumps(response), p)
    assert result["status"] == "VALIDATED" and result["citations"] == response["citations"]


@pytest.mark.parametrize("change,error", [
    ({"entity_id": "R-invented"}, "UNKNOWN_ENTITY_ID"),
    ({"evidence_refs": ["E-invented"]}, "UNKNOWN_EVIDENCE_ID"),
    ({"field_pointer": "/source_refs/0/excerpt"}, "UNPUBLISHED_SUPPORT_POINTER"),
    ({"field_pointer": "/requirement_id"}, "NON_SUBSTANTIVE_SUPPORT_FIELD"),
])
def test_invalid_citations(change, error):
    p = proj.build_stage_d_synthesis_projection(facts(), [])
    r = supported_response(p)
    r["citations"][0]["supports"][0].update(change)
    with pytest.raises(proj.ProjectionValidationError, match=error):
        proj.validate_stage_d_response(r, p)


def test_projection_publishes_exact_deterministic_support_pointer_sets():
    first = proj.build_stage_d_synthesis_projection(facts(), conflicts())
    second = proj.build_stage_d_synthesis_projection(copy.deepcopy(facts()), copy.deepcopy(conflicts()))
    pointer_sets = first["sidecar"]["support_pointer_sets"]
    assert pointer_sets == second["sidecar"]["support_pointer_sets"]
    assert pointer_sets
    aliases = [alias for group in pointer_sets for alias in group["entity_ids"]]
    assert len(aliases) == len(set(aliases))
    assert all(group["field_pointers"] == sorted(set(group["field_pointers"])) for group in pointer_sets)
    assert proj.finalize_stage_d_request(first, "instructions")["request_text"] == \
        proj.finalize_stage_d_request(second, "instructions")["request_text"]


def test_native_schema_accepts_only_published_entity_pointer_pairs():
    import jsonschema
    p = proj.build_stage_d_synthesis_projection(facts(), [])
    schema = proj.stage_d_output_config(p)["format"]["schema"]
    response = supported_response(p)
    legacy = response["citations"][0]["supports"][0]
    response["citations"][0]["supports"][0] = {
        "support_id": support_id(p, legacy["entity_id"], legacy["field_pointer"]),
        "evidence_catalog_id": p["prompt_context"]["evidence_catalog_id"],
        "evidence_selectors": [1],
    }
    jsonschema.validate(response, schema)
    assert proj.validate_stage_d_response(response, p)["status"] == "VALIDATED"
    response["citations"][0]["supports"][0]["support_id"] = 999999
    with pytest.raises(proj.ProjectionValidationError, match="UNKNOWN_SUPPORT_ID"):
        proj.validate_stage_d_response(response, p)


def test_unknown_missing_and_stale_support_pointers_fail_closed():
    p = proj.build_stage_d_synthesis_projection(facts(), [])
    for pointer, error in (("/unknown_field", "UNPUBLISHED_SUPPORT_POINTER"),
                           ("/value", "UNPUBLISHED_SUPPORT_POINTER")):
        response = supported_response(p)
        response["citations"][0]["supports"][0]["field_pointer"] = pointer
        with pytest.raises(proj.ProjectionValidationError, match=error):
            proj.validate_stage_d_response(response, p)
    response = supported_response(p)
    del response["citations"][0]["supports"][0]["field_pointer"]
    with pytest.raises(proj.ProjectionValidationError, match="INVALID_RESPONSE_SCHEMA"):
        proj.validate_stage_d_response(response, p)


def test_cross_owner_evidence_rejected():
    nf = facts()
    nf["deliverables"][0]["source_refs"] = [{"source_doc": "other.pdf", "excerpt": "Other scope"}]
    p = proj.build_stage_d_synthesis_projection(nf, [])
    r = supported_response(p)
    r["citations"][0]["supports"][0]["evidence_refs"] = ctx(p)["facts"]["deliverables"][0]["evidence_refs"]
    with pytest.raises(proj.ProjectionValidationError, match="WRONG_EVIDENCE_OWNER"):
        proj.validate_stage_d_response(r, p)


def test_required_proof_does_not_set_bidder_capability():
    nf = facts()
    p = proj.build_stage_d_synthesis_projection(nf, [])
    r = supported_response(p)
    r["synthesis"]["brief"]["executive_summary"] = "The buyer requires a support procedure."
    r["citations"][0]["supports"][0]["field_pointer"] = "/evidence"
    accepted = proj.validate_stage_d_response(r, p)
    final = extractor._assemble_procurement_result(extractor.apply_stage_d_authoritative_sections(accepted["synthesis"], nf), nf, [])
    assert final["requirements"][0]["qual_status"] == "UNKNOWN"
    assert final["requirements"][0]["evidence_status"] == "MISSING"
    r["synthesis"]["bid"]["qual_status"] = "PASS"
    with pytest.raises(proj.ProjectionValidationError, match="INVALID_RESPONSE_SCHEMA"):
        proj.validate_stage_d_response(r, p)


@pytest.mark.parametrize("raw", ['{}', '{"synthesis":{},"synthesis":{}}', '{"synthesis":', '```json\n{}\n```'])
def test_partial_or_invalid_output_rejected(raw):
    with pytest.raises(proj.ProjectionValidationError):
        proj.validate_stage_d_response(raw, proj.build_stage_d_synthesis_projection(facts(), []))


def test_uncited_output_and_authoritative_overwrite_rejected():
    p = proj.build_stage_d_synthesis_projection(facts(), [])
    r = empty_response()
    r["synthesis"]["brief"]["executive_summary"] = "Unsupported assertion"
    with pytest.raises(proj.ProjectionValidationError, match="UNCITED_OUTPUT_FIELD"):
        proj.validate_stage_d_response(r, p)
    r = empty_response()
    r["synthesis"]["brief"]["qualification_gates"] = []
    with pytest.raises(proj.ProjectionValidationError, match="INVALID_RESPONSE_SCHEMA"):
        proj.validate_stage_d_response(r, p)


def test_conflicting_deadline_selection_rejected():
    nf = facts()
    nf["doc_metadata"]["submission_deadline"] = "2026-10-01"
    p = proj.build_stage_d_synthesis_projection(nf, conflicts())
    f = next(f for f in ctx(p)["facts"]["metadata"] if f["key"] == "submission_deadline")
    r = empty_response()
    r["synthesis"]["bid"]["submission_deadline"] = f["value"]
    r["citations"] = [{"output_pointer": "/bid/submission_deadline", "supports": [{"entity_id": f["fact_id"], "field_pointer": "/value", "evidence_refs": []}]}]
    with pytest.raises(proj.ProjectionValidationError, match="UNRESOLVED_CONFLICT_SELECTION"):
        proj.validate_stage_d_response(r, p)


def test_proposal_outline_and_separate_notes_support():
    p = proj.build_stage_d_synthesis_projection(facts(), [])
    r = empty_response()
    r["synthesis"]["outline"] = [{"sort_order": 9, "section_num": "9", "title": "Support approach", "owner": None, "word_limit": None, "status": "Not Started", "notes": None}]
    r["citations"] = [{"section_index": 0, "kind": "proposal", "supports": [ctx(p)["requirements"][0]["requirement_id"]]}]
    accepted = proj.validate_stage_d_response(r, p)
    assert accepted["synthesis"]["outline"][0]["notes"] == "Suggested proposal structure."
    assert accepted["synthesis"]["outline"][0]["sort_order"] == 0
    r["synthesis"]["outline"][0]["notes"] = "Bidder is qualified."
    with pytest.raises(proj.ProjectionValidationError, match="UNCITED_OUTPUT_FIELD"):
        proj.validate_stage_d_response(r, p)


def test_seven_authoritative_sections_and_final_assembly():
    nf, c = facts(), conflicts()
    client = model_client()
    with patch("extractor.get_anthropic_client", return_value=client):
        actual = extractor.synthesize_bid_brief(nf, c, "not-a-key")
    expected = extractor.apply_stage_d_authoritative_sections({}, copy.deepcopy(nf))
    for key in proj.AUTHORITATIVE_SECTIONS:
        assert actual["brief"][key] == expected["brief"][key]
    final = extractor._assemble_procurement_result(actual, nf, c)
    assert final["requirements"] == nf["requirements"]
    assert final["documents"] == extractor.build_submission_documents(nf["submission_rules"], submission_deadline=None)
    assert final["brief"]["document_conflicts"] == c
    client.with_options.assert_called_once_with(max_retries=0)


@pytest.mark.parametrize("total,allowed", [(580000, True), (580001, False)])
def test_exact_guard_dispatch_boundary(total, allowed):
    nf = facts()
    p = proj.build_stage_d_synthesis_projection(nf, [])
    base = proj.finalize_stage_d_request(p, "")["diagnostics"]["total_prompt_chars"]
    instruction = "x" * (total - base)
    client = model_client()
    with patch("extractor.STAGE_D_SYNTHESIS_PROMPT", instruction), patch("extractor.get_anthropic_client", return_value=client):
        if allowed:
            extractor.synthesize_bid_brief(nf, [], "not-a-key")
            request = client.messages.create.call_args.kwargs["messages"][0]["content"][0]["text"]
            assert len(request) + len(proj.canonical_json(client.messages.create.call_args.kwargs["output_config"])) == 580000
        else:
            with pytest.raises(extractor.StageDContextTooLargeError):
                extractor.synthesize_bid_brief(nf, [], "not-a-key")
            client.messages.create.assert_not_called()


def test_unicode_sizes_and_digests_exact():
    nf = facts()
    nf["requirements"][0]["description"] = "مرحبا 世界 🌍"
    p = proj.build_stage_d_synthesis_projection(nf, [])
    before = copy.deepcopy(p)
    r = proj.finalize_stage_d_request(p, "日本語")
    d = r["diagnostics"]
    serialized = r["request_text"] + proj.canonical_json(r["output_config"])
    assert d["total_prompt_chars"] == len(serialized)
    assert d["total_prompt_utf8_bytes"] == len(serialized.encode("utf-8")) > d["total_prompt_chars"]
    assert sum(d["size_by_section"].values()) == d["prompt_context_chars"]
    assert d["prompt_digest"] == proj.text_digest(serialized)
    assert d["sidecar_digest"] == proj.digest(p["sidecar"])
    assert d["total_prompt_tokens"] is None and p == before


def test_native_schema_preserves_contract_and_required_citation_keys():
    import jsonschema
    schema = proj.stage_d_output_config()["format"]["schema"]
    jsonschema.Draft202012Validator.check_schema(schema)
    response = empty_response()
    jsonschema.validate(response, schema)
    response["citations"] = [{"output_pointer": "/brief/executive_summary", "supports": [
        {"entity_id": "r1", "field_pointer": "/description", "evidence_refs": []}]}]
    jsonschema.validate(response, schema)
    del response["citations"][0]["supports"][0]["evidence_refs"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(response, schema)


def test_native_schema_enforces_existing_alias_and_conflict_constraints():
    import jsonschema
    p = proj.build_stage_d_synthesis_projection(facts(), conflicts())
    schema = proj.stage_d_output_config(p)["format"]["schema"]
    response = empty_response()
    jsonschema.validate(response, schema)
    response["synthesis"]["bid"]["clarification_deadline"] = "2026-01-01"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(response, schema)
    response = empty_response()
    response["citations"] = [{"section_index": 0, "kind": "proposal", "supports": ["r999999"]}]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(response, schema)
    response = empty_response()
    response["synthesis"]["brief"]["procurement_model"] = "Invented model"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(response, schema)


def test_empty_statistics_and_tampered_projection():
    p = proj.build_stage_d_synthesis_projection({}, [])
    assert p["diagnostics"]["average_projected_requirement_size"] is None
    p["prompt_context"]["requirements"].append({})
    with pytest.raises(proj.ProjectionValidationError, match="PROJECTION_INTEGRITY_FAILURE"):
        proj.validate_stage_d_response(empty_response(), p)


def test_null_category_is_preserved_without_inference():
    nf = {"requirements": [{"description": "An obligation", "category": None}]}
    p = proj.build_stage_d_synthesis_projection(nf, [])
    assert ctx(p)["requirements"][0]["category"] is None
    assert p["diagnostics"]["counts_by_category"] == {"": 1}


def test_finalizer_rejects_changed_projection_before_request():
    p = proj.build_stage_d_synthesis_projection(facts(), [])
    p["prompt_context"]["requirements"][0]["description"] = "Changed"
    with pytest.raises(proj.ProjectionValidationError, match="PROJECTION_INTEGRITY_FAILURE"):
        proj.finalize_stage_d_request(p, "instructions")


def test_evaluation_points_cannot_become_outline_word_limit():
    nf = facts()
    nf["evaluation_criteria"][0]["weight_value"] = 70
    p = proj.build_stage_d_synthesis_projection(nf, [])
    r = empty_response()
    eid = ctx(p)["facts"]["evaluation_criteria"][0]["fact_id"]
    r["synthesis"]["outline"] = [{"sort_order": 0, "section_num": "1", "title": "Approach", "owner": None,
                                   "word_limit": 70, "status": "Not Started", "notes": None}]
    r["citations"] = [{"section_index": 0, "kind": "proposal", "supports": [eid]},
                      {"output_pointer": "/outline/0/word_limit", "supports": [
                          {"entity_id": eid, "field_pointer": "/weight_value", "evidence_refs": []}]}]
    with pytest.raises(proj.ProjectionValidationError, match="UNSUPPORTED_EXACT_VALUE"):
        proj.validate_stage_d_response(r, p)


@pytest.mark.parametrize("mode,blocks", [("off", False), ("best_effort", False), ("required", True)])
def test_checkpoint_modes_control_next_expensive_stage(mode, blocks, tmp_path, monkeypatch):
    monkeypatch.setenv("CHECKPOINT_MODE", mode)
    monkeypatch.setenv("CHECKPOINT_ROOT", str(tmp_path))
    with patch.object(cp, "_atomic_write", side_effect=OSError("disk full")) as write, patch("extractor.extract_document_with_metadata", return_value=("text", {})), patch("extractor.extract_document_facts", return_value={}) as stage_a, patch("extractor.normalize_package_facts", return_value=facts()), patch("extractor.reconcile_package_facts", return_value=[]), patch("extractor.get_anthropic_client", return_value=model_client()):
        if blocks:
            with pytest.raises(cp.CheckpointError):
                extractor.extract_procurement_package([("a.txt", b"source")], "secret-key")
            stage_a.assert_not_called()
        else:
            result, _ = extractor.extract_procurement_package([("a.txt", b"source")], "secret-key")
            assert result["requirements"] == facts()["requirements"]
            stage_a.assert_called_once()
        if mode == "off":
            write.assert_not_called()


def test_required_stage_a_write_failure_stops_next_document(tmp_path):
    original = cp._atomic_write
    def fail_document(path, raw):
        if path.name == "document-0001.json":
            raise OSError("disk full")
        return original(path, raw)
    with cp.checkpoint_run([("a.txt", b"a"), ("b.txt", b"b")], mode="required", root=tmp_path), patch.object(cp, "_atomic_write", side_effect=fail_document), patch("extractor.extract_document_with_metadata", return_value=("text", {})), patch("extractor.extract_document_facts", return_value={}) as stage_a:
        with pytest.raises(cp.CheckpointError):
            extractor.extract_procurement_package([("a.txt", b"a"), ("b.txt", b"b")], "secret")
        assert stage_a.call_count == 1


def test_diagnostics_and_failure_saved_before_dispatch(tmp_path):
    with cp.checkpoint_run(mode="required", root=tmp_path) as store, patch("extractor._STAGE_D_CONTEXT_CHAR_LIMIT", 1), patch("extractor.get_anthropic_client") as client:
        with pytest.raises(extractor.StageDContextTooLargeError):
            extractor.synthesize_bid_brief(facts(), [], "secret-key")
        client.assert_not_called()
        d = json.loads((store.root / "stage-d/size-diagnostics.json").read_text())
        assert d["dispatch_allowed"] is False
        assert (store.root / "stage-d/sidecar.json").exists()
        request = (store.root / "stage-d/request.txt").read_text(encoding="utf-8")
        config = json.loads((store.root / "stage-d/output-config.json").read_text(encoding="utf-8"))
        assert len(request) + len(proj.canonical_json(config)) == d["total_prompt_chars"]
        assert "secret-key" not in "".join(p.read_text(encoding="utf-8") for p in store.root.rglob("*.json"))


def test_response_checkpoint_captures_token_usage_without_changing_result(tmp_path):
    """Diagnostic token-usage capture is additive: identical result with or
    without checkpointing, and the persisted response.json carries the raw
    text, stop_reason, and token counts needed to diagnose an empty
    narrative layer without another API call."""
    raw = json.dumps(empty_response())
    usage = SimpleNamespace(input_tokens=12345, output_tokens=67)
    client = MagicMock()
    client.with_options.return_value = client
    client.messages.create.return_value = SimpleNamespace(
        content=[SimpleNamespace(type="text", text=raw)], stop_reason="end_turn", usage=usage)
    with patch("extractor.get_anthropic_client", return_value=client):
        baseline = extractor.synthesize_bid_brief(facts(), [], "secret-key")
    with cp.checkpoint_run(mode="required", root=tmp_path) as store, patch("extractor.get_anthropic_client", return_value=client):
        instrumented = extractor.synthesize_bid_brief(facts(), [], "secret-key")
    assert instrumented == baseline
    response = json.loads((store.root / "stage-d/attempt-01/response.json").read_text(encoding="utf-8"))
    assert response["text"] == raw
    assert response["stop_reason"] == "end_turn"
    assert response["input_tokens"] == 12345
    assert response["output_tokens"] == 67


def test_response_checkpoint_tolerates_missing_usage_attribute(tmp_path):
    """Older/mocked SDK responses without a .usage attribute must not break
    checkpointing; token fields degrade to null rather than raising."""
    client = model_client()
    with cp.checkpoint_run(mode="required", root=tmp_path) as store, patch("extractor.get_anthropic_client", return_value=client):
        extractor.synthesize_bid_brief(facts(), [], "secret-key")
    response = json.loads((store.root / "stage-d/attempt-01/response.json").read_text(encoding="utf-8"))
    assert response["input_tokens"] is None
    assert response["output_tokens"] is None


def test_one_retry_same_facts_and_strict_stop_reason(tmp_path):
    client = model_client()
    bad = SimpleNamespace(content=[SimpleNamespace(type="text", text="{}")], stop_reason="max_tokens")
    client.messages.create.side_effect = [bad, client.messages.create.return_value]
    with cp.checkpoint_run(mode="required", root=tmp_path) as store, patch("extractor.get_anthropic_client", return_value=client):
        extractor.synthesize_bid_brief(facts(), [], "secret-key")
        assert client.messages.create.call_count == 2
        requests = [c.kwargs["messages"][0]["content"][0]["text"] for c in client.messages.create.call_args_list]
        assert requests[0].split(proj.REQUEST_SEPARATOR)[1] == requests[1].split(proj.REQUEST_SEPARATOR)[1]
        assert (store.root / "stage-d/attempt-01/validation.json").exists()
        assert (store.root / "stage-d/attempt-02/validation.json").exists()


def test_two_failures_raise_without_third_attempt():
    client = model_client({})
    with patch("extractor.get_anthropic_client", return_value=client), pytest.raises(proj.ProjectionValidationError):
        extractor.synthesize_bid_brief(facts(), [], "secret")
    assert client.messages.create.call_count == 2


def test_api_error_then_validation_error_share_retry_budget():
    import anthropic
    import httpx
    client = model_client({})
    error = anthropic.APIConnectionError(request=httpx.Request("POST", "https://example.invalid"))
    client.messages.create.side_effect = [error, client.messages.create.return_value]
    with patch("extractor.get_anthropic_client", return_value=client), pytest.raises(proj.ProjectionValidationError):
        extractor.synthesize_bid_brief(facts(), [], "secret")
    assert client.messages.create.call_count == 2


def test_authoritative_invariant_failure_is_not_retried(tmp_path):
    client = model_client()
    original = extractor.apply_stage_d_authoritative_sections
    def divergent(synthesis, normalized):
        result = original(synthesis, normalized)
        if synthesis:
            result["brief"]["key_dates"] = [{"invented": True}]
        return result
    with cp.checkpoint_run(mode="required", root=tmp_path) as store, patch("extractor.get_anthropic_client", return_value=client), patch("extractor.apply_stage_d_authoritative_sections", side_effect=divergent):
        with pytest.raises(proj.ProjectionValidationError, match="AUTHORITATIVE_INVARIANT"):
            extractor.synthesize_bid_brief(facts(), [], "secret")
        assert (store.root / "stage-d/attempt-01/assembly-validation.json").exists()
    assert client.messages.create.call_count == 1


def make_checkpoint(tmp_path):
    sources = [("a.txt", b"source")]
    store = cp.CheckpointStore(sources, mode="required", root=tmp_path)
    store.write("stage-a/document-facts.json", [{}])
    store.write("stage-b/normalized-facts.json", facts())
    store.write("stage-c/conflicts.json", [])
    return store, sources


def test_d_only_replay_zero_stage_a_calls(tmp_path):
    store, sources = make_checkpoint(tmp_path)
    with patch("extractor.extract_document_facts") as stage_a, patch("extractor.normalize_package_facts") as stage_b, patch("extractor.reconcile_package_facts") as stage_c, patch("extractor.get_anthropic_client", return_value=model_client()):
        final, _ = cp.resume_procurement_checkpoint(store.root, sources, "secret", checkpoint_root=tmp_path)
        assert final["requirements"] == facts()["requirements"]
        stage_a.assert_not_called()
        stage_b.assert_not_called()
        stage_c.assert_not_called()


def test_d_only_replay_filters_unverified_logical_clause_before_aliasing(tmp_path):
    def verify(refs, _metadata):
        return [{**ref, "verified": True} for ref in refs]

    raw_clauses = [
        {"clause_kind": "OTHER", "topic": f"Clause {index}",
         "source_fact": f"Clause text {index}.", "conditions": [], "scope": {},
         "linked_observation_ids": [], "source_refs": [
             {"source_doc": "a.txt", "section": f"Clause {index}",
              "excerpt": f"Clause text {index}."}]}
        for index in range(3)
    ]
    hygiene = contract_hygiene.build_contract_hygiene(
        [], raw_clauses, [], verify,
        {"files": ["a.txt"], "doc_metadata": {}, "doc_texts": {}},
    )
    hygiene["clauses"][2]["evidence_state"] = "UNVERIFIED"
    normalized = {"doc_metadata": {}, "requirements": [], "dates": [],
                  "evaluation_criteria": [], "submission_rules": [], "deliverables": [],
                  "commercial_clauses": copy.deepcopy(hygiene["clauses"]),
                  "contract_risks": [], "_canonical_opportunity": {},
                  "_contract_hygiene": hygiene}
    sources = [("a.txt", b"source")]
    store = cp.CheckpointStore(sources, mode="required", root=tmp_path)
    store.write("stage-b/normalized-facts.json", normalized)
    store.write("stage-c/conflicts.json", [])
    with patch("extractor.extract_document_facts") as stage_a, \
            patch("extractor.normalize_package_facts") as stage_b, \
            patch("extractor.reconcile_package_facts") as stage_c, \
            patch("extractor.get_anthropic_client", return_value=model_client()):
        final, _ = cp.resume_procurement_checkpoint(
            store.root, sources, "secret", checkpoint_root=tmp_path,
        )
    assert len(final["brief"]["commercial_structure"]) == 2
    stage_a.assert_not_called()
    stage_b.assert_not_called()
    stage_c.assert_not_called()


def test_partial_stage_a_resume_extracts_only_missing_document(tmp_path):
    sources = [("a.txt", b"a"), ("b.txt", b"b")]
    store = cp.CheckpointStore(sources, mode="required", root=tmp_path)
    metadata = {"files": ["a.txt", "b.txt"], "doc_texts": {"a.txt": "text-a", "b.txt": "text-b"}, "doc_metadata": {}}
    store.write("preprocessed-inputs.json", cp.pack_preprocessed(metadata))
    store.write("stage-a/document-0001.json", {"requirements": []})
    with patch("extractor.extract_document_facts", return_value={}) as stage_a, patch("extractor.normalize_package_facts", return_value=facts()) as stage_b, patch("extractor.reconcile_package_facts", return_value=[]), patch("extractor.get_anthropic_client", return_value=model_client()):
        cp.resume_procurement_checkpoint(store.root, sources, "secret", checkpoint_root=tmp_path)
        stage_a.assert_called_once_with("text-b", "b.txt", "secret")
        assert stage_b.call_args.args[0] == [{"requirements": []}, {}]


def test_complete_pipeline_required_bundle_has_all_boundaries(tmp_path):
    sources = [("a.txt", b"a")]
    with cp.checkpoint_run(sources, mode="required", root=tmp_path) as store, patch("extractor.extract_document_with_metadata", return_value=("text", {})), patch("extractor.extract_document_facts", return_value={}), patch("extractor.normalize_package_facts", return_value=facts()), patch("extractor.reconcile_package_facts", return_value=[]), patch("extractor.get_anthropic_client", return_value=model_client()):
        extractor.extract_procurement_package(sources, "secret")
        assert {"preprocessed-inputs.json", "stage-a/document-0001.json", "stage-a/document-facts.json",
                "stage-b/normalized-facts.json", "stage-c/conflicts.json", "stage-d/projection.json",
                "stage-d/sidecar.json", "stage-d/request.txt", "stage-d/size-diagnostics.json",
                "stage-d/attempt-01/response.json", "stage-d/attempt-01/validation.json",
                "stage-d/final-result.json"} <= store.manifest["artifacts"].keys()
        assert cp.load_verified_checkpoint(store.root, sources)["artifacts"]["stage-b/normalized-facts.json"] == facts()


@pytest.mark.parametrize("corruption", ["source", "checksum", "version", "missing", "traversal"])
def test_resume_rejects_stale_or_corrupt_checkpoint(tmp_path, corruption):
    store, sources = make_checkpoint(tmp_path)
    versions = cp.runtime_versions()
    if corruption == "source":
        sources = [("a.txt", b"changed")]
    elif corruption == "checksum":
        (store.root / "stage-c/conflicts.json").write_text("[{}]")
    elif corruption == "version":
        versions["upstream_code_digest"] = "changed"
    elif corruption == "missing":
        (store.root / "stage-b/normalized-facts.json").unlink()
    else:
        manifest = json.loads((store.root / "manifest.json").read_text())
        manifest["artifacts"]["../../outside.json"] = manifest["artifacts"]["stage-c/conflicts.json"]
        (store.root / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(cp.CheckpointError):
        cp.load_verified_checkpoint(store.root, sources, versions=versions)


def test_d_version_change_reuses_only_verified_upstream(tmp_path):
    store, sources = make_checkpoint(tmp_path)
    versions = cp.runtime_versions()
    versions["projection_version"] = "stage-d-projection/future"
    versions["code_sha"] = "next-commit"
    verified = cp.load_verified_checkpoint(store.root, sources, versions=versions)
    assert verified["stage_d_rebuild_required"] and verified["stage_d_version_changed"]
    assert verified["code_sha_changed"]


def test_checkpoint_forbids_repository_destination():
    with pytest.raises(cp.CheckpointError):
        cp.CheckpointStore([], mode="required", root=cp.REPOSITORY / "private-checkpoints")


def test_preprocessing_roundtrip_preserves_types():
    metadata = {"pages": {1: "text"}, "rows_per_sheet": {"A": (1, 3, {1, 3})}}
    assert cp.unpack_preprocessed(json.loads(json.dumps(cp.pack_preprocessed(metadata)))) == metadata


def synthetic_large_facts(count=559):
    """Generic mechanical fixture, not British Council acceptance."""
    common = "Apply the documented service requirements. " * 8 + "Exceptions require written approval."
    refs = [{"source_doc": f"service-schedule-{i}.pdf", "page": i + 1, "section": "Service conditions", "excerpt": common, "verified": True} for i in range(4)]
    return {"requirements": [
        {"req_id": f"M{i}", "category": "Mandatory", "requirement_type": "Delivery / SLA",
         "description": f"Service obligation {i}: " + "Provide monitored support and document escalation procedures. " * 4,
         "evidence": "Provide the service procedure and escalation records.", "qual_status": "UNKNOWN",
         "evidence_status": "MISSING", "source_refs": copy.deepcopy(refs)} for i in range(count)]}


def test_synthetic_559_mechanical_scalability():
    nf = synthetic_large_facts()
    p = proj.build_stage_d_synthesis_projection(nf, [])
    d = proj.finalize_stage_d_request(p, extractor.STAGE_D_SYNTHESIS_PROMPT)["diagnostics"]
    old = len(extractor.LEGACY_STAGE_D_SYNTHESIS_PROMPT + "\n\nNORMALIZED PROCUREMENT FACTS MODEL:\n" + json.dumps(extractor.build_stage_d_context(nf, []), indent=2))
    assert d["requirement_count"] == 559 and d["omitted_requirement_count"] == 0
    assert d["evidence_id_count"] == 4
    assert all(len(e["owners"]) == 559 for e in p["sidecar"]["evidence"].values())
    assert d["total_prompt_chars"] < 580000 and d["total_prompt_chars"] < old * .75


@pytest.mark.parametrize("prefix", ["boc_2026_026", "bc_ir67tvet42026_attempt2"])
def test_retained_frozen_authority_regression(prefix):
    root = Path(__file__).parent / "acceptance" / "results"
    source = root / (prefix + "_normalized_facts.json")
    if not source.exists():
        pytest.skip("Optional local retained fixture is unavailable")
    nf = json.loads(source.read_text(encoding="utf-8"))
    c = json.loads((root / (prefix + "_conflicts.json")).read_text(encoding="utf-8"))
    before = copy.deepcopy(nf)
    p = proj.build_stage_d_synthesis_projection(nf, c)
    accepted = proj.validate_stage_d_response(empty_response(), p)
    actual = extractor.apply_stage_d_authoritative_sections(accepted["synthesis"], copy.deepcopy(nf))
    expected = extractor.apply_stage_d_authoritative_sections({}, copy.deepcopy(nf))
    assert {k: actual["brief"][k] for k in proj.AUTHORITATIVE_SECTIONS} == {k: expected["brief"][k] for k in proj.AUTHORITATIVE_SECTIONS}
    final = extractor._assemble_procurement_result(actual, nf, c)
    assert final["requirements"] == before["requirements"] and nf == before
    assert final["brief"]["document_conflicts"] == c
    assert final["documents"] == extractor.build_submission_documents(before["submission_rules"], submission_deadline=None)


def test_prompt_aliases_are_bijective_and_resolved_citations_keep_full_ids():
    nf = facts()
    nf["requirements"] *= 2
    p = proj.build_stage_d_synthesis_projection(nf, conflicts())
    aliases = p["sidecar"]["prompt_aliases"]
    assert len(set(aliases.values())) == len(aliases)
    assert set(aliases.values()) == set().union(*(p["sidecar"][k] for k in ("requirements", "facts", "conflicts", "evidence")))
    for alias, full in aliases.items():
        assert alias[0].upper() == full[0]
        assert len(full.split("-")[1]) == 64
    response = supported_response(p)
    accepted = proj.validate_stage_d_response(response, p)
    supplied = response["citations"][0]["supports"][0]
    resolved = accepted["resolved_citations"][0]["supports"][0]
    assert resolved["entity_id"] == aliases[supplied["entity_id"]]
    assert resolved["evidence_refs"] == [aliases[e] for e in supplied["evidence_refs"]]


def test_full_sidecar_id_is_not_a_prompt_alias():
    p = proj.build_stage_d_synthesis_projection(facts(), [])
    r = supported_response(p)
    support = r["citations"][0]["supports"][0]
    support["entity_id"] = p["sidecar"]["prompt_aliases"][support["entity_id"]]
    with pytest.raises(proj.ProjectionValidationError, match="UNKNOWN_ENTITY_ID"):
        proj.validate_stage_d_response(r, p)


def test_alias_map_tampering_fails_integrity():
    p = proj.build_stage_d_synthesis_projection(facts(), [])
    p["sidecar"]["prompt_aliases"]["r1"] = "R-" + "0" * 64 + "-1"
    with pytest.raises(proj.ProjectionValidationError, match="PROJECTION_INTEGRITY_FAILURE"):
        proj.validate_stage_d_response(empty_response(), p)


def test_table_roundtrip_preserves_missing_null_and_long_text():
    rows = [{"description": "A full obligation. " * 40, "evidence": "Proof", "category": "Mandatory", "rfso_ref": None}
            for _ in range(100)]
    del rows[0]["rfso_ref"]
    rows[1]["evidence"] = None
    packed = proj._pack_records(rows)
    assert isinstance(packed, dict)
    assert proj._unpack_records(packed) == rows
    assert "rfso_ref" not in proj._unpack_records(packed)[0]
    assert proj._unpack_records(packed)[1]["rfso_ref"] is None


def test_shared_required_proof_is_exact_and_descriptions_remain_direct():
    nf = facts()
    proof = "Provide the complete procedure and supporting documentation. " * 8
    nf["requirements"] = [{"description": f"Obligation {i}: r1 e1 f1 are literal source text.", "evidence": proof} for i in range(40)]
    p = proj.build_stage_d_synthesis_projection(nf, [])
    assert list(p["prompt_context"]["required_proof_text"].values()) == [proof]
    for r in ctx(p)["requirements"]:
        original = proj.resolve_pointer(p["sidecar"]["authoritative_inputs"], p["sidecar"]["requirements"][p["sidecar"]["prompt_aliases"][r["requirement_id"]]]["source_pointer"])
        assert r["description"] == original["description"] and r["evidence"] == proof
    wire_rows = proj._unpack_records(p["prompt_context"]["requirements"])
    assert all(isinstance(r["description"], str) and isinstance(r["evidence"], dict) for r in wire_rows)


def test_locator_navigation_remains_in_sidecar_with_source_identity_inline():
    nf = facts()
    p = proj.build_stage_d_synthesis_projection(nf, [])
    alias, inline = next(iter(ctx(p)["evidence_context"].items()))
    original = p["sidecar"]["evidence"][p["sidecar"]["prompt_aliases"][alias]]
    assert ctx(p)["sources"][inline["source_id"]] == original["source_doc"]
    assert inline["verified"] is True
    assert "page" not in inline and "cells" not in inline
    assert original["page"] == 2 and original["cells"] == "A2:A4"


def test_high_cardinality_559_capacity_preserves_every_occurrence():
    from scripts.measure_stage_d_projection import synthetic_high_cardinality_facts
    nf, c = synthetic_high_cardinality_facts()
    p = proj.build_stage_d_synthesis_projection(nf, c)
    logical = ctx(p)
    d = proj.finalize_stage_d_request(p, extractor.STAGE_D_SYNTHESIS_PROMPT)["diagnostics"]
    assert d["requirement_count"] == 559 and d["omitted_requirement_count"] == 0
    assert d["evidence_id_count"] == 1061 and d["total_prompt_chars"] <= 580000
    assert len({r["evidence"] for r in nf["requirements"]}) == 559  # No favorable proof sharing in this stress.
    assert "required_proof_text" not in p["prompt_context"]
    assert sum(len(r["source_refs"]) for r in nf["requirements"]) == 839
    assert sum(len(e["source_pointers"]) for e in p["sidecar"]["evidence"].values() if e["origin_kind"] == "source_ref") == 1053
    for r in logical["requirements"]:
        full = p["sidecar"]["prompt_aliases"][r["requirement_id"]]
        original = proj.resolve_pointer(p["sidecar"]["authoritative_inputs"], p["sidecar"]["requirements"][full]["source_pointer"])
        for key in original.keys() - {"source_refs"}:
            assert r[key] == original[key]
        for e in r["evidence_refs"]:
            assert full in p["sidecar"]["evidence"][p["sidecar"]["prompt_aliases"][e]]["owners"]
    accepted = proj.validate_stage_d_response(empty_response(), p)
    actual = extractor.apply_stage_d_authoritative_sections(accepted["synthesis"], copy.deepcopy(nf))
    expected = extractor.apply_stage_d_authoritative_sections({}, copy.deepcopy(nf))
    assert {k: actual["brief"][k] for k in proj.AUTHORITATIVE_SECTIONS} == {k: expected["brief"][k] for k in proj.AUTHORITATIVE_SECTIONS}
    final = extractor._assemble_procurement_result(actual, nf, c)
    assert final["requirements"] == nf["requirements"] and final["brief"]["document_conflicts"] == c
    assert final["documents"] == extractor.build_submission_documents(nf["submission_rules"], submission_deadline=None)
