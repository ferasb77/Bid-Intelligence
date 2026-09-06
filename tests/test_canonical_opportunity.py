import copy
import itertools

from canonical_opportunity import (
    SCHEMA_VERSION, apply_authoritative_values, build_canonical_opportunity,
    compact_stage_d_summary, resolve_canonical_opportunity,
)


def metadata(*names):
    texts = {}
    for name in names:
        texts[name] = f"[[SOURCE: {name} | PAGE: 1]]\nTender Alpha Buyer Corp SOL-7 2030-01-02 2030-01-01 CAD 1000"
    return {"files": list(names), "doc_metadata": {n: {"page_count": 1} for n in names}, "doc_texts": texts}


def obs(kind, value, doc="a.pdf", family="IDENTITY", **extra):
    return {"family": family, "semantic_kind": kind, "original_value": value, "source_doc": doc,
            "source_refs": [{"source_doc": doc, "page": 1, "excerpt": str(value)}], **extra}


def resolved(facts, meta=None):
    meta = meta or metadata("a.pdf")
    return resolve_canonical_opportunity(build_canonical_opportunity(facts, meta))


def test_schema_and_repeated_agreement_preserve_both_sources():
    facts = [{"typed_observations": [obs("OPPORTUNITY_TITLE", "Tender Alpha", "a.pdf")]},
             {"typed_observations": [obs("OPPORTUNITY_TITLE", "Tender Alpha", "b.pdf")]}]
    c = resolved(facts, metadata("a.pdf", "b.pdf"))
    assert c["schema_version"] == SCHEMA_VERSION
    assert len(c["observations"]) == 2
    assert c["resolved"]["title"]["status"] == "RESOLVED"
    assert len(c["resolved"]["title"]["observation_ids"]) == 2


def test_document_title_and_reference_number_are_excluded():
    c = resolved([{"typed_observations": [obs("DOCUMENT_TITLE", "Tender Alpha"), obs("DOCUMENT_REFERENCE_NUMBER", "SOL-7")]}])
    assert c["resolved"]["title"]["status"] == "MISSING"
    assert c["resolved"]["file_number"]["status"] == "MISSING"


def test_conflicting_title_is_field_linked():
    c = resolved([{"typed_observations": [obs("OPPORTUNITY_TITLE", "Tender Alpha"), obs("OPPORTUNITY_TITLE", "Buyer Corp")]}])
    assert c["resolved"]["title"]["status"] == "CONFLICTED"
    assert c["conflicts"][0]["affected_fields"] == ["/resolved/title"]


def test_order_permutations_are_canonical():
    groups = [
        {"typed_observations": [obs("OPPORTUNITY_TITLE", "Tender Alpha", "a.pdf")]},
        {"typed_observations": [obs("BUYER_NAME", "Buyer Corp", "b.pdf")]},
        {"typed_observations": [obs("SOLICITATION_NUMBER", "SOL-7", "c.pdf")]},
    ]
    outputs = []
    for permutation in itertools.permutations(groups):
        outputs.append(resolved(list(permutation), metadata("a.pdf", "b.pdf", "c.pdf")))
    assert all(item == outputs[0] for item in outputs)


def test_same_deadline_agrees_and_distinct_deadlines_are_independent():
    facts = [{"typed_observations": [
        obs("SUBMISSION_DEADLINE", "2030-01-02", family="MILESTONE", date="2030-01-02"),
        obs("CLARIFICATION_DEADLINE", "2030-01-01", family="MILESTONE", date="2030-01-01"),
    ]}]
    c = resolved(facts)
    assert c["resolved"]["submission_deadline"]["value"]["date"] == "2030-01-02"
    assert c["resolved"]["clarification_deadline"]["value"]["date"] == "2030-01-01"


def test_submission_conflict_does_not_suppress_clarification():
    facts = [{"typed_observations": [
        obs("SUBMISSION_DEADLINE", "2030-01-02", family="MILESTONE", date="2030-01-02"),
        obs("SUBMISSION_DEADLINE", "2030-01-01", family="MILESTONE", date="2030-01-01"),
        obs("CLARIFICATION_DEADLINE", "2030-01-01", family="MILESTONE", date="2030-01-01"),
    ]}]
    c = resolved(facts)
    assert c["resolved"]["submission_deadline"]["status"] == "CONFLICTED"
    assert c["resolved"]["clarification_deadline"]["status"] == "RESOLVED"


def test_component_and_lot_deadlines_do_not_compete_for_headline():
    facts = [{"typed_observations": [
        obs("SUBMISSION_DEADLINE", "2030-01-02", family="MILESTONE", date="2030-01-02"),
        obs("SUBMISSION_DEADLINE", "2030-01-03", family="MILESTONE", date="2030-01-03", component="Pricing"),
        obs("SUBMISSION_DEADLINE", "2030-01-04", family="MILESTONE", date="2030-01-04", lot="Lot 2"),
    ]}]
    c = resolved(facts)
    assert c["resolved"]["submission_deadline"]["status"] == "RESOLVED"
    assert c["resolved"]["submission_deadline"]["value"]["date"] == "2030-01-02"
    assert len(c["observations"]) == 3


def test_fabricated_excerpt_is_retained_but_not_promoted():
    bad = obs("OPPORTUNITY_TITLE", "Fabricated words")
    c = resolved([{"typed_observations": [bad]}])
    assert len(c["observations"]) == 1
    assert c["observations"][0]["provenance_status"] == "PARTIAL"
    assert c["resolved"]["title"]["status"] == "UNVERIFIED"


def test_fabricated_locator_is_not_verified():
    bad = obs("OPPORTUNITY_TITLE", "Tender Alpha")
    bad["source_refs"][0]["page"] = 9
    c = resolved([{"typed_observations": [bad]}])
    assert c["observations"][0]["provenance_status"] != "VERIFIED"


def test_money_keeps_ceiling_separate_and_currency_neutral():
    facts = [{"typed_observations": [
        obs("ESTIMATED_CONTRACT_VALUE", "1000", family="MONETARY", amount="1000", currency="CAD", tax_basis="EXCLUSIVE"),
        obs("FRAMEWORK_CEILING", "1000", family="MONETARY", amount="1000", currency="USD"),
        obs("EVALUATION_SCENARIO_VALUE", "1000", family="MONETARY", amount="1000", currency="CAD"),
    ]}]
    c = resolved(facts)
    assert c["resolved"]["headline_value"]["value"]["currency"] == "CAD"
    out = apply_authoritative_values({"bid": {"value_cad": 7}, "brief": {}}, c)
    assert out["bid"]["value_cad"] is None
    assert len([o for o in c["observations"] if o["family"] == "MONETARY"]) == 3


def test_mechanics_are_atomic_and_tier_one_conservative():
    facts = [{"typed_observations": [
        obs("FRAMEWORK", "Framework", family="PROCUREMENT_MECHANIC"),
        obs("MULTIPLE_SUPPLIER_AWARD", "multiple", family="PROCUREMENT_MECHANIC"),
        obs("CALL_OFF", "call off", family="PROCUREMENT_MECHANIC"),
        obs("NO_GUARANTEED_VOLUME", "no guaranteed volume", family="PROCUREMENT_MECHANIC"),
    ]}]
    meta = metadata("a.pdf")
    meta["doc_texts"]["a.pdf"] += " Framework multiple call off no guaranteed volume"
    c = resolved(facts, meta)
    assert c["resolved"]["opportunity_type"]["status"] == "NOT_CLASSIFIED"
    assert c["resolved"]["procurement_model"]["value"] == "Multi-vendor Call-off"
    assert len(compact_stage_d_summary(c)["verified_mechanics"]) == 4


def test_duplicate_physical_occurrence_collapses_with_occurrences():
    item = obs("OPPORTUNITY_TITLE", "Tender Alpha")
    c = resolved([{"typed_observations": [copy.deepcopy(item), copy.deepcopy(item)]}])
    assert len(c["observations"]) == 1
    assert len(c["observations"][0]["extraction_occurrences"]) == 2
