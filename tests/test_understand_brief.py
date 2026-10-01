from pathlib import Path

from fast_analysis import FastAnalysisResult
from understand_brief import BriefModelError, build_bid_intelligence_brief, model_digest
from understand_brief_report import render_pdf


def _result():
    r = FastAnalysisResult()
    name = "RFP 26-1610 - One on One Coaching Services.pdf"
    r.doc_metadata_by_doc[name] = {
        "client": "City of Calgary", "file_number": "26-1610",
        "title": "One on One Coaching Services for Executive Leadership Team",
        "submission_deadline": "22 October 2026, 16:00:59 Mountain Time",
        "clarification_deadline": "19 October 2026, before 16:00:59 MST",
        "budget": "CAD 150,000-200,000 per year",
    }
    r.documents_by_route = {"IDENTITY": [name, "Appendix D Price Form.xlsx", "Appendix E Submission Form.docx"]}
    r.typed_observations = [
        {"family": "PROCUREMENT_MECHANIC", "semantic_kind": "SUBMISSION_CHANNEL", "original_value": "SAP Ariba"},
        {"family": "MILESTONE", "semantic_kind": "SUBMISSION_DEADLINE", "original_value": "22 October 2026, 16:00:59 Mountain Time"},
    ]
    r.evaluation_occurrences = [
        {"criterion_label": "Firm Experience & Capabilities", "weight": "30%", "minimum_score": "70%"},
        {"criterion_label": "Service Delivery", "weight": "30%"},
        {"criterion_label": "Price", "weight": "20%"},
    ]
    r.deterministic_criterion_response_prompts = {
        "Firm Experience & Capabilities": {"response_prompt": "Provide three comparable projects completed in the last five years."},
        "Service Delivery": {"response_prompt": "Describe intake, coach matching, service levels and reporting."},
    }
    r.category_scope_items = {"coaching": [{"text": "Evidence-based one-on-one coaching for senior leaders."}]}
    r.requirements = [
        {"category": "submission", "description": "Complete Appendix E Submission Form and Appendix D Price Form."},
        {"category": "scope", "description": "Provide ICF-certified coaches and measurement of coaching impact."},
        {"category": "post-award", "description": "Send invoices to accounts payable after award."},
    ]
    r.commercial_clauses = [
        {"topic": "Insurance", "source_fact": "Commercial general liability insurance of CAD 5,000,000 is required."},
        {"topic": "Intellectual Property", "source_fact": "The City owns newly created intellectual property in Deliverables."},
    ]
    r.ambiguities = {"evaluation_weight_conflicts": [], "pricing_stage_ambiguity": [], "category_date_distinctions": []}
    return r


def test_same_durable_input_has_same_model_digest():
    r = _result()
    assert model_digest(build_bid_intelligence_brief(r)) == model_digest(build_bid_intelligence_brief(r))


def test_identity_evaluation_scope_and_commercial_are_customer_safe():
    brief = build_bid_intelligence_brief(_result())
    assert brief.opportunity.startswith("One on One Coaching")
    assert brief.solicitation == "26-1610"
    assert [c.weight for c in brief.criteria] == ["30%", "30%", "20%"]
    assert brief.criteria[0].minimum == "70%"
    assert "comparable projects" in brief.criteria[0].response_expectation.lower()
    assert all("invoice" not in " ".join(row).lower() for row in brief.submission)
    assert any(topic == "Insurance" for topic, _ in brief.commercial)
    assert len(brief.priorities) <= 7


def test_ordinary_verbs_do_not_become_service_categories():
    r = _result()
    r.category_scope_items = {}
    r.deterministic_service_scope = None
    r.requirements = [{"category": "submission", "description": "Proponents must submit, sign and upload the response."}]
    assert build_bid_intelligence_brief(r).service_scope == ()


def test_explicit_source_scope_requirement_is_available_to_older_snapshots():
    r = _result()
    r.category_scope_items = {}
    r.deterministic_service_scope = None
    r.requirements = [{
        "category": "Mandatory",
        "semantic_type": "CONTRACTUAL_OBLIGATION",
        "description": "Service scope includes confidential executive coaching and impact measurement.",
    }]
    assert build_bid_intelligence_brief(r).service_scope == (
        "Service scope includes confidential executive coaching and impact measurement.",
    )


def test_customer_language_containing_ident_is_not_internal_noise():
    r = _result()
    r.category_scope_items = {"coaching": [{"text": "Confidential coaching for senior leaders."}]}
    assert build_bid_intelligence_brief(r).service_scope == (
        "Confidential coaching for senior leaders.",
    )


def test_objective_fragments_and_timetable_facts_are_customer_readable():
    r = _result()
    r.deterministic_procurement_facts = [
        {"family": "OBJECTIVE", "value": "Support leaders in aligning personal purpose with"},
        {"family": "OBJECTIVE", "value": "organizational goals."},
        {"semantic_kind": "RFP_ISSUE_DATE", "value": "2026 September 25"},
        {"semantic_kind": "RECTIFICATION_PERIOD", "value": "Three (3) Business Days"},
    ]
    brief = build_bid_intelligence_brief(r)
    assert brief.buyer_intent == ("Support leaders in aligning personal purpose with organizational goals.",)
    assert "RFP issue date: 2026 September 25" in brief.key_dates
    assert brief.submission_distinction and "Three (3) Business Days" in brief.submission_distinction


def test_form_title_is_rejected_as_procurement_identity():
    r = _result()
    for metadata in r.doc_metadata_by_doc.values():
        metadata["title"] = "Proponent Acknowledgements"
    try:
        build_bid_intelligence_brief(r)
    except BriefModelError:
        pass
    else:
        raise AssertionError("form title must not be exported as the opportunity")


def test_rendered_pdf_is_nonempty_and_has_no_internal_noise(tmp_path):
    output = tmp_path / "brief.pdf"
    render_pdf(build_bid_intelligence_brief(_result()), output)
    assert output.read_bytes().startswith(b"%PDF")
    # Customer strings are constrained at the model boundary before PDF creation.
    text = str(build_bid_intelligence_brief(_result()).to_dict()).lower()
    assert not any(token in text for token in ("crit-", "obl-", "max_tokens", "migration", "product-feedback"))
