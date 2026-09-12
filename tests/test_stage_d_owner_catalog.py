"""Owner-scoped selectors must close before existing citation validation runs."""
import copy
import json
from unittest.mock import patch

import jsonschema
import pytest

import extractor
import stage_d_projection as proj
from test_stage_d_projection import facts, conflicts, ctx, supported_response, support_id, model_client


def scoped_response(projection):
    response = supported_response(projection)
    support = response["citations"][0]["supports"][0]
    owner = support["entity_id"]
    catalog = projection["prompt_context"]["owner_evidence_catalogs"][owner]
    response["citations"][0]["supports"][0] = {
        "support_id": support_id(projection, owner, support["field_pointer"]),
        "evidence_catalog_id": projection["prompt_context"]["evidence_catalog_id"],
        "evidence_selectors": [catalog.index(ref) + 1 for ref in support["evidence_refs"]],
    }
    return response


def test_complete_owner_catalog_and_local_expansion():
    p = proj.build_stage_d_synthesis_projection(facts(), conflicts())
    aliases = p["sidecar"]["prompt_aliases"]
    catalogs = p["prompt_context"]["owner_evidence_catalogs"]
    for owner, _ in proj._support_catalog(p["sidecar"]["support_pointer_sets"]).values():
        expected = {eid for eid, evidence in p["sidecar"]["evidence"].items()
                    if aliases[owner] in evidence["owners"]}
        assert {aliases[ref] for ref in catalogs[owner]} == expected
    response = scoped_response(p)
    result = proj.validate_stage_d_response(response, p, provider_contract=True)
    assert result["status"] == "VALIDATED"
    assert result["resolved_citations"] == proj.validate_stage_d_response(supported_response(p), p)["resolved_citations"]


@pytest.mark.parametrize("selector", [0, -1, 999999, True, 1.0, "e1", "E-invented", None, {}, []])
def test_unknown_evidence_selector_rejected(selector):
    p = proj.build_stage_d_synthesis_projection(facts(), [])
    response = scoped_response(p)
    response["citations"][0]["supports"][0]["evidence_selectors"] = [selector]
    with pytest.raises(proj.ProjectionValidationError, match="UNKNOWN_EVIDENCE_SELECTOR"):
        proj.validate_stage_d_response(response, p, provider_contract=True)


def test_foreign_evidence_cannot_be_selected_or_expanded():
    nf = facts()
    nf["deliverables"][0]["source_refs"] = [{"source_doc": "foreign.pdf", "excerpt": "Foreign evidence"}]
    p = proj.build_stage_d_synthesis_projection(nf, [])
    response = scoped_response(p)
    foreign = ctx(p)["facts"]["deliverables"][0]["evidence_refs"][0]
    response["citations"][0]["supports"][0]["evidence_selectors"] = [foreign]
    with pytest.raises(proj.ProjectionValidationError, match="UNKNOWN_EVIDENCE_SELECTOR"):
        proj.validate_stage_d_response(response, p, provider_contract=True)
    # Existing full ownership validation remains independently enforced on replay.
    legacy = supported_response(p)
    legacy["citations"][0]["supports"][0]["evidence_refs"] = [foreign]
    with pytest.raises(proj.ProjectionValidationError, match="WRONG_EVIDENCE_OWNER"):
        proj.validate_stage_d_response(legacy, p)


def test_stale_catalog_rejected_even_when_local_positions_still_exist():
    old = proj.build_stage_d_synthesis_projection(facts(), [])
    nf = facts()
    nf["requirements"][0]["source_refs"][0]["excerpt"] = "Changed evidence"
    current = proj.build_stage_d_synthesis_projection(nf, [])
    response = scoped_response(current)
    response["citations"][0]["supports"][0]["evidence_catalog_id"] = old["prompt_context"]["evidence_catalog_id"]
    with pytest.raises(proj.ProjectionValidationError, match="EVIDENCE_CATALOG_MISMATCH"):
        proj.validate_stage_d_response(response, current, provider_contract=True)


def test_duplicate_evidence_eliminated_without_losing_occurrences():
    nf = facts()
    nf["requirements"][0]["source_refs"] *= 2
    p = proj.build_stage_d_synthesis_projection(nf, [])
    owner = ctx(p)["requirements"][0]["requirement_id"]
    assert len(p["prompt_context"]["owner_evidence_catalogs"][owner]) == 1
    eid = p["sidecar"]["prompt_aliases"][p["prompt_context"]["owner_evidence_catalogs"][owner][0]]
    assert len(p["sidecar"]["evidence"][eid]["source_pointers"]) == 2
    response = scoped_response(p)
    expected = proj.validate_stage_d_response(response, p, provider_contract=True)
    response["citations"][0]["supports"][0]["evidence_selectors"] *= 3
    actual = proj.validate_stage_d_response(response, p, provider_contract=True)
    assert actual["resolved_citations"] == expected["resolved_citations"]


def test_catalog_generation_and_serialized_replay_are_deterministic():
    p = proj.build_stage_d_synthesis_projection(facts(), conflicts())
    reordered = dict(reversed(list(facts().items())))
    again = proj.build_stage_d_synthesis_projection(reordered, copy.deepcopy(conflicts()))
    assert proj.canonical_json(p) == proj.canonical_json(again)
    serialized = json.loads(proj.canonical_json(p))
    response = scoped_response(p)
    assert proj.validate_stage_d_response(response, p, provider_contract=True) == \
        proj.validate_stage_d_response(json.dumps(response), serialized, provider_contract=True)
    assert proj.finalize_stage_d_request(p, extractor.STAGE_D_SYNTHESIS_PROMPT) == \
        proj.finalize_stage_d_request(serialized, extractor.STAGE_D_SYNTHESIS_PROMPT)


def test_provider_schema_and_production_reject_free_evidence_references():
    p = proj.build_stage_d_synthesis_projection(facts(), [])
    schema = proj.stage_d_output_config(p)["format"]["schema"]
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(scoped_response(p), schema)
    legacy = supported_response(p)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(legacy, schema)
    with pytest.raises(proj.ProjectionValidationError, match="INVALID_RESPONSE_SCHEMA"):
        proj.validate_stage_d_response(legacy, p, provider_contract=True)
    stale = scoped_response(p)
    stale["citations"][0]["supports"][0]["evidence_catalog_id"] = "invented"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(stale, schema)


def test_tampered_owner_catalog_fails_closed():
    p = proj.build_stage_d_synthesis_projection(facts(), [])
    response = scoped_response(p)
    p["prompt_context"]["owner_evidence_catalogs"]["r1"].append("e999")
    with pytest.raises(proj.ProjectionValidationError, match="PROJECTION_INTEGRITY_FAILURE"):
        proj.validate_stage_d_response(response, p, provider_contract=True)


def test_first_failure_mode_does_not_retry_or_assemble(monkeypatch):
    monkeypatch.setenv("CHECKPOINT_MODE", "off")
    client = model_client({})
    with patch("extractor.get_anthropic_client", return_value=client), \
         patch("extractor.apply_stage_d_authoritative_sections") as assembly:
        with pytest.raises(proj.ProjectionValidationError):
            extractor.synthesize_bid_brief(facts(), [], "test", fail_on_first_error=True)
    assert client.messages.create.call_count == 1
    assembly.assert_not_called()


def test_empty_owner_catalog_cannot_select_foreign_evidence():
    p = proj.build_stage_d_synthesis_projection(facts(), [])
    response = scoped_response(p)
    empty_owner = next(owner for owner, refs in p["prompt_context"]["owner_evidence_catalogs"].items()
                       if not refs)
    selector = next(key for key, (owner, _) in proj._support_catalog(
        p["sidecar"]["support_pointer_sets"]).items() if owner == empty_owner)
    response["citations"][0]["supports"][0]["support_id"] = selector
    with pytest.raises(proj.ProjectionValidationError, match="UNKNOWN_EVIDENCE_SELECTOR"):
        proj.validate_stage_d_response(response, p, provider_contract=True)
    response["citations"][0]["supports"][0]["evidence_selectors"] = []
    assert proj.validate_stage_d_response(response, p, provider_contract=True)["status"] == "VALIDATED"


def test_stage_a_first_failure_does_not_accept_repaired_json():
    client = model_client()
    client.messages.create.return_value.content[0].text = '{"requirements": ['
    with patch("extractor.get_anthropic_client", return_value=client):
        with pytest.raises(ValueError, match="Stage A incomplete provider JSON"):
            extractor.extract_document_facts("text", "source.pdf", "test", fail_on_first_error=True)
    assert client.messages.create.call_count == 1


def test_stage_a_first_failure_does_not_recover_undercoverage():
    client = model_client({})
    with patch("extractor.get_anthropic_client", return_value=client), \
         patch("extractor.inspect_stage_a_coverage", return_value={"is_suspicious": True}):
        with pytest.raises(ValueError, match="Stage A suspicious under-coverage"):
            extractor.extract_document_facts("text", "source.pdf", "test", fail_on_first_error=True)
    assert client.messages.create.call_count == 1
