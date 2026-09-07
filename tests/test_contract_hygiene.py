import copy
import json

import pytest

import contract_hygiene as hygiene
import database
import extractor
import stage_d_projection as projection


META = {"files": ["a.pdf", "b.pdf"], "doc_metadata": {}, "doc_texts": {}}


def verify(refs, _metadata):
    return [{**ref, "verified": ref.get("valid", True)} for ref in refs]


def ref(doc="a.pdf", page=1, excerpt="Supplier shall provide the report."):
    return {"source_doc": doc, "page": page, "excerpt": excerpt}


def deliverable(**changes):
    value = {
        "title": "Monthly report", "description": "Supplier shall provide a monthly report.",
        "obligation_state": "MANDATORY", "quantity": "1.0", "unit": "report",
        "frequency": "MONTHLY", "scope": {"lot": None, "phase": None, "component": None, "location": None},
        "due_milestone": None, "acceptance_criteria": None, "responsible_actor": "SUPPLIER",
        "conditions": [], "source_refs": [ref()],
    }
    value.update(changes)
    return value


def clause(kind="INTELLECTUAL_PROPERTY", **changes):
    value = {"clause_kind": kind, "topic": "Foreground IP",
             "source_fact": "Buyer owns foreground intellectual property.", "conditions": [],
             "scope": {}, "linked_observation_ids": [],
             "source_refs": [ref(excerpt="All foreground IP becomes property of the buyer.")]}
    value.update(changes)
    return value


@pytest.mark.parametrize("state", sorted(hygiene.OBLIGATION_STATES))
def test_deliverable_states_and_decimal_quantity(state):
    item = hygiene.normalize_deliverable_occurrence(deliverable(obligation_state=state), verify, META)
    assert item["obligation_state"] == state and item["quantity"] == "1"


@pytest.mark.parametrize("frequency", sorted(hygiene.FREQUENCIES))
def test_controlled_frequency(frequency):
    assert hygiene.normalize_deliverable_occurrence(deliverable(frequency=frequency), verify, META)["frequency"] == frequency


def test_scope_dimensions_prevent_logical_merge_and_quantity_conflict():
    items = [deliverable(scope={"lot": "A"}), deliverable(scope={"lot": "B"}, quantity="2")]
    result = hygiene.build_contract_hygiene(items, [], [], verify, META)
    assert len(result["deliverables"]) == 2
    assert hygiene.structured_deliverable_conflicts(result["deliverables"]) == []


def test_same_scope_different_quantity_conflicts_without_merging():
    result = hygiene.build_contract_hygiene([deliverable(), deliverable(quantity="2", source_refs=[ref("b.pdf")])], [], [], verify, META)
    assert len(result["deliverables"]) == 2
    assert len(hygiene.structured_deliverable_conflicts(result["deliverables"])) == 1


def test_exact_duplicate_across_documents_merges_and_keeps_occurrences():
    result = hygiene.build_contract_hygiene([deliverable(), deliverable(source_refs=[ref("b.pdf")])], [], [], verify, META)
    assert len(result["deliverables"]) == 1
    assert len(result["deliverables"][0]["occurrences"]) == 2
    assert {r["source_doc"] for r in result["deliverables"][0]["source_refs"]} == {"a.pdf", "b.pdf"}


def test_overlapping_chunk_same_physical_occurrence_collapses():
    item = deliverable()
    result = hygiene.build_contract_hygiene([item, copy.deepcopy(item)], [], [], verify, META)
    assert len(result["deliverables"][0]["occurrences"]) == 1


def test_fresh_unverified_fact_excluded_but_legacy_remains_visible():
    fresh = deliverable(source_refs=[])
    legacy = {"title": "Historical response document", "description": "Old extraction"}
    result = hygiene.build_contract_hygiene([fresh, legacy], [], [{"risk": "Old", "severity": "High"}], verify, META)
    deliverables, _, risks = hygiene.authoritative_sections(result)
    assert [d["title"] for d in deliverables] == ["Historical response document"]
    assert deliverables[0]["evidence_state"] == "UNVERIFIED"
    assert risks[0]["assessment_basis"] == "LEGACY_EXTRACTION"


def test_non_supplier_fresh_output_excluded_from_summary():
    result = hygiene.build_contract_hygiene([deliverable(responsible_actor="BUYER")], [], [], verify, META)
    assert hygiene.authoritative_sections(result)[0] == []


@pytest.mark.parametrize("kind", sorted(hygiene.CLAUSE_KINDS))
def test_clause_taxonomy(kind):
    assert hygiene.normalize_clause_occurrence(clause(kind), verify, META)["clause_kind"] == kind


def test_unknown_clause_kind_maps_other_and_scoped_clauses_stay_separate():
    values = [clause("NOVEL", scope={"lot": "A"}), clause("NOVEL", scope={"lot": "B"})]
    result = hygiene.build_contract_hygiene([], values, [], verify, META)
    assert len(result["clauses"]) == 2
    assert {c["clause_kind"] for c in result["clauses"]} == {"OTHER"}


def test_exact_clause_dedup_preserves_occurrences_and_links():
    values = [clause(linked_observation_ids=["obs_rate"]), clause(linked_observation_ids=["obs_rate"], source_refs=[ref("b.pdf")])]
    result = hygiene.build_contract_hygiene([], values, [], verify, META)
    assert len(result["clauses"]) == 1 and len(result["clauses"][0]["occurrences"]) == 2
    assert result["clauses"][0]["linked_observation_ids"] == ["obs_rate"]


def test_assessment_authority_and_links():
    result = hygiene.build_contract_hygiene([], [clause()], [], verify, META)
    cid = result["clauses"][0]["clause_id"]
    accepted = hygiene.validate_assessments([{"clause_ids": [cid], "assessment_state": "REVIEW",
        "interpretation_code": "REVIEW_CLAUSE_TERMS", "assessment_basis": "AI_ASSISTED", "user_decision": None}], result["clauses"])
    assert accepted[0]["assessment_state"] == "REVIEW" and "severity" not in accepted[0]
    for bad in [
        {"clause_ids": [cid], "assessment_state": "MATERIAL", "interpretation_code": "REVIEW_CLAUSE_TERMS", "user_decision": None},
        {"clause_ids": ["clause_unknown"], "assessment_state": "UNKNOWN", "interpretation_code": "INSUFFICIENT_CONTEXT", "user_decision": None},
        {"clause_ids": [cid], "assessment_state": "REVIEW", "interpretation_code": "REVIEW_CLAUSE_TERMS", "user_decision": "accept"},
    ]:
        with pytest.raises(ValueError):
            hygiene.validate_assessments([bad], result["clauses"])


def test_projection_clause_alias_and_authoritative_source_fact_immutability():
    result = hygiene.build_contract_hygiene([deliverable()], [clause()], [], verify, META)
    nf = {"doc_metadata": {}, "requirements": [], "dates": [], "evaluation_criteria": [],
          "submission_rules": [], "deliverables": result["deliverables"],
          "commercial_clauses": result["clauses"], "contract_risks": [],
          "_canonical_opportunity": {}, "_contract_hygiene": result}
    projected = projection.build_stage_d_synthesis_projection(nf, [])
    assert projected["sidecar"]["clause_aliases"] == {"x1": result["clauses"][0]["clause_id"]}
    response = {"synthesis": {"bid": {"title": None, "client": None, "file_number": None,
        "owner": None, "sensitivity": "Standard", "submission_deadline": None,
        "clarification_deadline": None, "value_cad": None, "notes": None},
        "brief": {"executive_summary": None, "opportunity_type": None, "contract_term": "Not stated",
                  "procurement_model": None, "scope_categories": []}, "outline": [],
        "risk_assessments": [{"clause_ids": ["x1"], "assessment_state": "REVIEW",
            "clause_kind": "INTELLECTUAL_PROPERTY",
            "interpretation_code": "REVIEW_CLAUSE_TERMS", "assessment_basis": "AI_ASSISTED", "user_decision": None}]},
        "citations": []}
    validated = projection.validate_stage_d_response(response, projected)
    final = extractor.apply_stage_d_authoritative_sections(validated["synthesis"], nf)
    assert final["brief"]["contract_risks"][0]["source_fact"] == clause()["source_fact"]
    assert final["brief"]["deliverables_summary"][0]["source_refs"]
    assert "severity" not in final["brief"]["contract_risks"][0]


def test_stage_d_rejects_mismatched_clause_kind_and_source_fact_is_not_output():
    result = hygiene.build_contract_hygiene([], [clause()], [], verify, META)
    nf = {"doc_metadata": {}, "requirements": [], "dates": [], "evaluation_criteria": [],
          "submission_rules": [], "deliverables": [], "commercial_clauses": result["clauses"],
          "contract_risks": [], "_canonical_opportunity": {}, "_contract_hygiene": result}
    projected = projection.build_stage_d_synthesis_projection(nf, [])
    response = {"synthesis": {"bid": {"title": None, "client": None, "file_number": None,
        "owner": None, "sensitivity": "Standard", "submission_deadline": None,
        "clarification_deadline": None, "value_cad": None, "notes": None},
        "brief": {"executive_summary": None, "opportunity_type": None, "contract_term": "Not stated",
                  "procurement_model": None, "scope_categories": []}, "outline": [],
        "risk_assessments": [{"clause_ids": ["x1"], "clause_kind": "INSURANCE",
            "assessment_state": "UNKNOWN", "interpretation_code": "INSUFFICIENT_CONTEXT",
            "assessment_basis": "AI_ASSISTED", "user_decision": None}]}, "citations": []}
    with pytest.raises(projection.ProjectionValidationError, match="CLAUSE_KIND_MISMATCH"):
        projection.validate_stage_d_response(response, projected)
    schema_fields = projection.stage_d_output_config(projected)["format"]["schema"]
    assert "source_fact" not in json.dumps(schema_fields).split('"risk_assessments"', 1)[1]


def test_nested_bid_brief_json_round_trip():
    value = {"contract_risks": [{"source_refs": [ref()], "assessment": [{"assessment_state": "REVIEW"}]}]}
    stored = database.format_bid_brief_payload(value, ["contract_risks"])
    assert json.loads(stored["contract_risks"]) == value["contract_risks"]


def test_stage_a_prompt_removes_fresh_risk_schema_and_forbids_consequences():
    prompt = extractor.STAGE_A_FACT_EXTRACTION_PROMPT
    schema_part = prompt.split("TYPED OBSERVATION RULES:", 1)[0]
    assert '"contract_risks"' not in schema_part
    assert "Do not emit contract_risks, severity" in prompt
    assert "supplier-produced outputs during contract execution" in prompt


@pytest.mark.parametrize("clause_kind,observation_id", [
    ("PRICING_ESCALATION", "obs_rate_cap"),
    ("PRICING_ESCALATION", "obs_framework_ceiling"),
    ("OTHER", "obs_no_guaranteed_volume"),
    ("PRICING_ESCALATION", "obs_extension_pricing"),
    ("PAYMENT_WITHHOLDING_SETOFF", "obs_payment_terms"),
    ("INSURANCE", "obs_insurance_amount"),
])
def test_clause_links_do_not_overwrite_canonical_authority(clause_kind, observation_id):
    item = clause(clause_kind, linked_observation_ids=[observation_id])
    result = hygiene.build_contract_hygiene([], [item], [], verify, META)
    canonical = {"resolved": {"estimated_value": {"status": "RESOLVED", "value": "5000000"},
                              "procurement_model": {"status": "RESOLVED", "value": "Framework"}}}
    before = copy.deepcopy(canonical)
    normalized = {"doc_metadata": {}, "requirements": [], "dates": [], "evaluation_criteria": [],
                  "submission_rules": [], "deliverables": [], "commercial_clauses": result["clauses"],
                  "contract_risks": [], "_canonical_opportunity": canonical, "_contract_hygiene": result}
    extractor.apply_stage_d_authoritative_sections({}, normalized)
    assert normalized["_canonical_opportunity"] == before
    assert result["clauses"][0]["linked_observation_ids"] == [observation_id]


def test_absence_of_clause_does_not_create_risk():
    result = hygiene.build_contract_hygiene([], [], [], verify, META)
    assert hygiene.authoritative_sections(result)[2] == []


@pytest.mark.parametrize("source_refs", [
    [],
    [{"source_doc": "missing.pdf", "page": 1, "excerpt": "Liability is capped."}],
    [{"source_doc": "a.pdf", "page": 1, "excerpt": "Liability is capped.", "verified": False}],
])
def test_unverified_fresh_clause_is_diagnostic_only_and_projection_safe(source_refs):
    raw = clause("LIABILITY_INDEMNITY", source_fact="Liability is capped.", source_refs=source_refs)
    metadata = {"files": ["a.pdf"], "doc_metadata": {"a.pdf": {"page_count": 1}},
                "doc_texts": {"a.pdf": "Liability is capped."}}
    facts = {"doc_metadata": {}, "requirements": [], "dates": [], "evaluation_criteria": [],
             "submission_rules": [], "deliverables": [], "commercial_clauses": [raw],
             "contract_risks": [], "typed_observations": []}
    normalized = extractor.normalize_package_facts([facts], metadata)
    assert normalized["commercial_clauses"] == []
    diagnostic = normalized["_contract_hygiene"]["clauses"][0]
    assert diagnostic["evidence_state"] == "UNVERIFIED"
    projected = projection.build_stage_d_synthesis_projection(normalized, [])
    assert projection.expand_prompt_context(projected["prompt_context"])["facts"]["commercial_clauses"] == []
    assert projected["sidecar"]["authoritative_inputs"]["normalized_facts"]["_contract_hygiene"]["clauses"][0]["clause_id"] == diagnostic["clause_id"]


def test_mixed_clause_verification_projects_only_verified_and_keeps_both_diagnostics():
    good = clause(source_refs=[ref()])
    bad = clause("INSURANCE", topic="Insurance", source_fact="Insurance is required.", source_refs=[])
    result = hygiene.build_contract_hygiene([], [good, bad], [], verify, META)
    normalized = {"doc_metadata": {}, "requirements": [], "dates": [], "evaluation_criteria": [],
                  "submission_rules": [], "deliverables": [],
                  "commercial_clauses": [c for c in result["clauses"] if c["evidence_state"] == "VERIFIED"],
                  "contract_risks": [], "_canonical_opportunity": {}, "_contract_hygiene": result}
    projected = projection.build_stage_d_synthesis_projection(normalized, [])
    assert len(projection.expand_prompt_context(projected["prompt_context"])["facts"]["commercial_clauses"]) == 1
    assert len(projected["sidecar"]["authoritative_inputs"]["normalized_facts"]["_contract_hygiene"]["clauses"]) == 2


def test_legacy_replay_has_no_clause_alias_requirement():
    legacy = {"doc_metadata": {}, "requirements": [], "dates": [], "evaluation_criteria": [],
              "submission_rules": [], "deliverables": [{"title": "Old", "description": "Old output"}],
              "commercial_clauses": [{"topic": "Old term", "details": "Old wording"}],
              "contract_risks": [{"risk": "Old risk", "severity": "High", "details": "Old model output"}],
              "_canonical_opportunity": {}}
    projected = projection.build_stage_d_synthesis_projection(legacy, [])
    assert projected["sidecar"].get("clause_aliases") == {}
    final = extractor.apply_stage_d_authoritative_sections({}, legacy)
    assert final["brief"]["contract_risks"][0]["severity"] == "High"


def test_public_nested_contract_is_explicitly_versioned():
    result = hygiene.build_contract_hygiene([deliverable()], [clause()], [], verify, META)
    deliveries, clauses, risks = hygiene.authoritative_sections(result)
    assert all(item["contract_hygiene_version"] == hygiene.VERSION for item in deliveries + clauses + risks)


@pytest.mark.parametrize("mutation", [
    {"why_it_matters": "This guarantees imprisonment and termination."},
    {"interpretation_code": "GUARANTEED_PENALTY"},
    {"interpretation_code": "INSUFFICIENT_CONTEXT", "assessment_state": "REVIEW"},
])
def test_unsupported_interpretation_contract_is_rejected(mutation):
    result = hygiene.build_contract_hygiene([], [clause()], [], verify, META)
    nf = {"doc_metadata": {}, "requirements": [], "dates": [], "evaluation_criteria": [],
          "submission_rules": [], "deliverables": [], "commercial_clauses": result["clauses"],
          "contract_risks": [], "_canonical_opportunity": {}, "_contract_hygiene": result}
    projected = projection.build_stage_d_synthesis_projection(nf, [])
    item = {"clause_ids": ["x1"], "clause_kind": "INTELLECTUAL_PROPERTY",
            "assessment_state": "REVIEW", "interpretation_code": "REVIEW_CLAUSE_TERMS",
            "assessment_basis": "AI_ASSISTED", "user_decision": None}
    item.update(mutation)
    response = {"synthesis": {"bid": {"title": None, "client": None, "file_number": None,
        "owner": None, "sensitivity": "Standard", "submission_deadline": None,
        "clarification_deadline": None, "value_cad": None, "notes": None},
        "brief": {"executive_summary": None, "opportunity_type": None, "contract_term": "Not stated",
                  "procurement_model": None, "scope_categories": []}, "outline": [],
        "risk_assessments": [item]}, "citations": []}
    with pytest.raises(projection.ProjectionValidationError):
        projection.validate_stage_d_response(response, projected)
