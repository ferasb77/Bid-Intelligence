"""Regression coverage for the conflict-identity remediation.

Bank of Canada RFP 2026-026 Executive Opportunity Brief commissioning
(post provenance-granularity remediation) failed at "Opportunity Intelligence
Support Binding Derivation" because Stage C's `reconcile_package_facts()`
output is a flat concatenation of two structurally unrelated conflict
populations:

  1. canonical_opportunity.py's own FIELD_KINDS conflicts (title/client/
     file_number/contract_term/headline_value/opportunity_type/
     procurement_model), each carrying one deterministic, content-derived
     `conf_<sha256>` identity that Canonical Opportunity Publication
     genuinely publishes as a governed CONFLICT object under that exact id.
  2. extractor.detect_document_conflicts() / contract_hygiene.structured_*_
     conflicts()'s own ordinal, Stage-C-local advisory review items
     (CONF-DATE-N, CONF-EVAL-N, CONF-SUB-N, CONF-MAND-N, CONF-COMM-N,
     CONF-SCOPE-N, CONF-HYGIENE-N, CONF-CLAUSE-N) -- a single counter
     incremented across every family in a fixed processing order, never
     derived from conflict content, and never published as a governed
     object anywhere in the architecture.

opportunity_intelligence.py used to cite BOTH populations uniformly as
FUTURE_ENTITY evidence_used support requiring a governed reference,
which population (2) can never provide. This file covers: (A) the
opportunity_intelligence.py / opportunity_intelligence_publication.py fix
that separates "citable as governed support" from "counted as an unresolved
uncertainty" without dropping any conflict from visibility; and (B) direct,
fixture-level proof of the two identity systems' actual stability
properties (canonical_opportunity._conflict()'s hash is deterministic,
order-invariant, and content-sensitive; extractor.detect_document_conflicts()'s
ordinal ids are not).

See BANK_OF_CANADA_CONFLICT_IDENTITY_REMEDIATION_REPORT.md.
"""
import pytest

from canonical_opportunity import _conflict
from decision_intelligence import ContractValidationError, SupportedEntityType
from extractor import detect_document_conflicts
from opportunity_intelligence import analyze_opportunity, validate_opportunity_analysis


# --- Section A: opportunity_intelligence.py governed/advisory split -------

def _facts(governed_conflicts=(), extra_resolved=None):
    return {
        "requirements": [], "evaluation_criteria": [], "submission_rules": [],
        "dates": [], "deliverables": [], "commercial_clauses": [],
        "_canonical_opportunity": {
            "observations": [],
            "resolved": extra_resolved or {},
            "conflicts": list(governed_conflicts),
        },
    }


GOVERNED = {"conflict_id": "conf_abc123", "state": "ACTIVE", "semantic_kind": "OPPORTUNITY_TITLE",
            "affected_fields": ["/resolved/title"], "affected_observation_ids": [],
            "incompatible_values": ["a", "b"]}
ADVISORY = {"conflict_id": "CONF-EVAL-1", "conflict_type": "EVALUATION_CONFLICT",
            "classification": "REVIEW_ITEM", "topic": "Internal Discrepancy for Methodology"}


def test_only_governed_conflicts_become_citable_future_entity_support():
    value = _facts(governed_conflicts=[GOVERNED])
    result = analyze_opportunity(value, [GOVERNED, ADVISORY], context_id="opportunity-1")
    cited_conflict_entity_ids = {item.entity_id for item in result.evidence_used
                                 if item.entity_type == SupportedEntityType.FUTURE_ENTITY}
    assert cited_conflict_entity_ids == {"conf_abc123"}


def test_unresolved_conflict_ids_still_lists_both_governed_and_advisory_conflicts():
    # Zero information loss: the advisory conflict is not citable support,
    # but it must remain fully visible as an uncertainty signal.
    value = _facts(governed_conflicts=[GOVERNED])
    result = analyze_opportunity(value, [GOVERNED, ADVISORY], context_id="opportunity-1")
    assert set(result.unknowns.unresolved_conflict_ids) == {"conf_abc123", "CONF-EVAL-1"}


def test_total_conflicts_counts_governed_and_advisory_alike():
    value = _facts(governed_conflicts=[GOVERNED])
    result = analyze_opportunity(value, [GOVERNED, ADVISORY], context_id="opportunity-1")
    total = next(item for item in result.computed_facts if item.statement_id == "oi-computed-total_conflicts")
    assert total.statement == "total_conflicts=2"


def test_analysis_with_advisory_only_conflict_still_validates():
    # The advisory conflict is absent from evidence_used but still present
    # in unresolved_conflict_ids -- validate_opportunity_analysis's own
    # "never resolve or omit a conflict" invariant (checked against
    # unresolved_conflict_ids, not evidence_used) must still be satisfied.
    value = _facts(governed_conflicts=[])
    result = analyze_opportunity(value, (ADVISORY,), context_id="opportunity-1")
    assert "CONF-EVAL-1" in result.unknowns.unresolved_conflict_ids
    assert not any(item.entity_id == "CONF-EVAL-1" for item in result.evidence_used)


def test_advisory_only_analysis_passes_validate_opportunity_analysis():
    from decision_intelligence import AnalystContext
    from opportunity_intelligence import OpportunityAnalysisContext, OpportunityIntelligenceAnalyst
    value = _facts(governed_conflicts=[])
    context = OpportunityAnalysisContext(
        AnalystContext("opportunity-1", ("opportunity-1",)), value, (ADVISORY,))
    output = OpportunityIntelligenceAnalyst().analyze(context)
    validate_opportunity_analysis(context, output)  # must not raise


def test_governed_and_advisory_mixed_analysis_passes_validate_opportunity_analysis():
    from decision_intelligence import AnalystContext
    from opportunity_intelligence import OpportunityAnalysisContext, OpportunityIntelligenceAnalyst
    value = _facts(governed_conflicts=[GOVERNED])
    context = OpportunityAnalysisContext(
        AnalystContext("opportunity-1", ("opportunity-1",)), value, (GOVERNED, ADVISORY))
    output = OpportunityIntelligenceAnalyst().analyze(context)
    validate_opportunity_analysis(context, output)  # must not raise


# --- Section B: opportunity_intelligence_publication.py leniency ----------

from datetime import datetime, timezone

from decision_analyst import AnalystUnknowns, DecisionAnalysis
from decision_intelligence import (
    Confidence, DecisionStatement, EvidenceSupport, ReasoningStatus, SourceType, StatementSource, StatementType,
)
from governed_reference_resolution import (
    AuthorityClass, SemanticField, SemanticValue, SemanticValueKind,
    create_governed_object, create_governed_snapshot, create_resolution_context, reference_to,
)
from opportunity_intelligence import ANALYST_VERSION
from opportunity_intelligence_publication import (
    OpportunityPublicationError, OpportunitySupportBinding, publish_opportunity_intelligence,
)


def _context_with_one_governed_fact():
    canonical = create_governed_object(
        owner_domain="canonical-opportunity", owner_contract="canonical-opportunity",
        contract_version="1.0.0", object_class="canonical-fact", object_id="canonical-1",
        authority=AuthorityClass.CANONICAL_FACT,
        semantic_fields=(SemanticField("value", SemanticValue(SemanticValueKind.STRING, "Known fact")),))
    snapshot = create_governed_snapshot(
        owner_domain="canonical-opportunity", owner_contract="canonical-opportunity",
        contract_version="1.0.0", snapshot_id="canonical-snapshot-1", objects=(canonical,))
    context = create_resolution_context(
        context_id="authoritative-context-1", context_version="1.0.0", snapshots=(snapshot,))
    root_support = EvidenceSupport(SupportedEntityType.CANONICAL_FACT, "canonical-1")
    root_binding = OpportunitySupportBinding(root_support, reference_to(snapshot, "canonical-fact", "canonical-1"))
    return context, snapshot, root_support, root_binding


def _minimal_analysis(*, evidence_used, unknowns):
    root_support = evidence_used[0]
    computed = DecisionStatement(
        "computed-1", StatementType.COMPUTED_FACT, "total_conflicts=1",
        StatementSource(SourceType.DETERMINISTIC_COMPUTATION, "opportunity-intelligence/1.0.0:total_conflicts"),
        None, ReasoningStatus.VALIDATED, root_support.evidence_ids, (root_support.entity_id,), (root_support,))
    return DecisionAnalysis(
        "analysis-1", "opportunity-intelligence", datetime(2030, 1, 1, tzinfo=timezone.utc),
        Confidence.UNKNOWN, tuple(evidence_used), (computed,), (), (), (), (), (), (), unknowns)


def test_future_entity_conflict_absent_from_evidence_used_publishes_without_relationship():
    # Mirrors the real, fixed shape: an advisory conflict id sits in
    # unresolved_conflict_ids but was never linked as citable evidence_used
    # support (opportunity_intelligence.py only links governed conflicts).
    # Publication must succeed and simply omit a relationship for it,
    # rather than fail closed.
    context, snapshot, root_support, root_binding = _context_with_one_governed_fact()
    unknowns = AnalystUnknowns(unresolved_conflict_ids=("CONF-EVAL-1",))
    analysis = _minimal_analysis(evidence_used=(root_support,), unknowns=unknowns)
    publication = publish_opportunity_intelligence(
        analysis, analyst_version=ANALYST_VERSION, authoritative_context=context,
        support_bindings=(root_binding,))
    unknowns_obj = next(item for item in publication.snapshot.objects if item.object_class == "unknowns")
    targets = {rel.target.object_id for rel in unknowns_obj.relationships}
    assert "CONF-EVAL-1" not in targets


def test_future_entity_conflict_with_supplied_binding_still_gets_relationship():
    context, snapshot, root_support, root_binding = _context_with_one_governed_fact()
    conflict_object = create_governed_object(
        owner_domain="canonical-opportunity", owner_contract="canonical-opportunity",
        contract_version="1.0.0", object_class="conflict", object_id="conf_governed",
        authority=AuthorityClass.CONFLICT,
        semantic_fields=(SemanticField("state", SemanticValue(SemanticValueKind.STRING, "ACTIVE")),))
    conflict_snapshot = create_governed_snapshot(
        owner_domain="canonical-opportunity", owner_contract="canonical-opportunity",
        contract_version="1.0.0", snapshot_id="canonical-snapshot-2", objects=(conflict_object,))
    full_context = create_resolution_context(
        context_id="authoritative-context-2", context_version="1.0.0",
        snapshots=(snapshot, conflict_snapshot))
    conflict_support = EvidenceSupport(SupportedEntityType.FUTURE_ENTITY, "conf_governed")
    conflict_binding = OpportunitySupportBinding(
        conflict_support, reference_to(conflict_snapshot, "conflict", "conf_governed"))
    unknowns = AnalystUnknowns(unresolved_conflict_ids=("conf_governed",))
    analysis = _minimal_analysis(evidence_used=(root_support, conflict_support), unknowns=unknowns)
    publication = publish_opportunity_intelligence(
        analysis, analyst_version=ANALYST_VERSION, authoritative_context=full_context,
        support_bindings=(root_binding, conflict_binding))
    unknowns_obj = next(item for item in publication.snapshot.objects if item.object_class == "unknowns")
    targets = {rel.target.object_id for rel in unknowns_obj.relationships}
    assert "conf_governed" in targets


def test_ambiguous_future_entity_conflict_still_fails_even_though_conflict_ids_are_lenient():
    # Two distinct EvidenceSupport objects sharing the same entity_id, each
    # bound to a DIFFERENT governed object, is a genuine identity collision.
    # The unresolved_conflict_ids leniency covers a missing target, never an
    # ambiguous one -- ambiguity must keep failing closed unconditionally.
    context, snapshot, root_support, root_binding = _context_with_one_governed_fact()
    conflict_a = create_governed_object(
        owner_domain="canonical-opportunity", owner_contract="canonical-opportunity",
        contract_version="1.0.0", object_class="conflict", object_id="conf_dup",
        authority=AuthorityClass.CONFLICT,
        semantic_fields=(SemanticField("state", SemanticValue(SemanticValueKind.STRING, "ACTIVE")),))
    conflict_b = create_governed_object(
        owner_domain="opportunity-structure", owner_contract="opportunity-structure",
        contract_version="1.0.0", object_class="conflict", object_id="conf_dup",
        authority=AuthorityClass.CONFLICT,
        semantic_fields=(SemanticField("state", SemanticValue(SemanticValueKind.STRING, "ACTIVE")),))
    evidence_a = create_governed_object(
        owner_domain="canonical-opportunity", owner_contract="canonical-opportunity",
        contract_version="1.0.0", object_class="evidence", object_id="evidence-a",
        authority=AuthorityClass.EVIDENCE,
        semantic_fields=(SemanticField("locator", SemanticValue(SemanticValueKind.STRING, "page 1")),))
    evidence_b = create_governed_object(
        owner_domain="opportunity-structure", owner_contract="opportunity-structure",
        contract_version="1.0.0", object_class="evidence", object_id="evidence-b",
        authority=AuthorityClass.EVIDENCE,
        semantic_fields=(SemanticField("locator", SemanticValue(SemanticValueKind.STRING, "page 2")),))
    snap_a = create_governed_snapshot(
        owner_domain="canonical-opportunity", owner_contract="canonical-opportunity",
        contract_version="1.0.0", snapshot_id="snap-a", objects=(conflict_a, evidence_a))
    snap_b = create_governed_snapshot(
        owner_domain="opportunity-structure", owner_contract="opportunity-structure",
        contract_version="1.0.0", snapshot_id="snap-b", objects=(conflict_b, evidence_b))
    full_context = create_resolution_context(
        context_id="authoritative-context-3", context_version="1.0.0",
        snapshots=(snapshot, snap_a, snap_b))
    support_a = EvidenceSupport(SupportedEntityType.FUTURE_ENTITY, "conf_dup", ("evidence-a",))
    support_b = EvidenceSupport(SupportedEntityType.FUTURE_ENTITY, "conf_dup", ("evidence-b",))
    binding_a = OpportunitySupportBinding(support_a, reference_to(snap_a, "conflict", "conf_dup"),
                                          (reference_to(snap_a, "evidence", "evidence-a"),))
    binding_b = OpportunitySupportBinding(support_b, reference_to(snap_b, "conflict", "conf_dup"),
                                          (reference_to(snap_b, "evidence", "evidence-b"),))
    unknowns = AnalystUnknowns(unresolved_conflict_ids=("conf_dup",))
    analysis = _minimal_analysis(evidence_used=(root_support, support_a, support_b), unknowns=unknowns)
    with pytest.raises(OpportunityPublicationError, match="ambiguous"):
        publish_opportunity_intelligence(
            analysis, analyst_version=ANALYST_VERSION, authoritative_context=full_context,
            support_bindings=(root_binding, binding_a, binding_b))


def test_missing_evidence_requirement_with_no_binding_still_fails_closed():
    # missing_evidence (REQUIREMENT-typed) carries no "may never be
    # governed" exception -- requirements are always published by
    # Opportunity Structure Publication. Leniency must not leak here.
    context, snapshot, root_support, root_binding = _context_with_one_governed_fact()
    unknowns = AnalystUnknowns(missing_evidence=("req-missing-1",))
    analysis = _minimal_analysis(evidence_used=(root_support,), unknowns=unknowns)
    with pytest.raises(OpportunityPublicationError, match="no exact governed target"):
        publish_opportunity_intelligence(
            analysis, analyst_version=ANALYST_VERSION, authoritative_context=context,
            support_bindings=(root_binding,))


def test_ambiguous_observation_id_with_no_binding_still_fails_closed():
    context, snapshot, root_support, root_binding = _context_with_one_governed_fact()
    unknowns = AnalystUnknowns(ambiguous_observation_ids=("obs-ambiguous-1",))
    analysis = _minimal_analysis(evidence_used=(root_support,), unknowns=unknowns)
    with pytest.raises(OpportunityPublicationError, match="no exact governed target"):
        publish_opportunity_intelligence(
            analysis, analyst_version=ANALYST_VERSION, authoritative_context=context,
            support_bindings=(root_binding,))


# --- Section C: canonical_opportunity._conflict() hash-identity properties --

def _conflict_obs(oid, scope=None):
    return {"observation_id": oid, "semantic_kind": "OPPORTUNITY_TITLE", "scope": scope or {},
            "source_refs": []}


def test_governed_conflict_id_is_deterministic_across_identical_rebuilds():
    obs = [_conflict_obs("obs_a"), _conflict_obs("obs_b")]
    first = _conflict("title", obs, ["a", "b"])
    second = _conflict("title", obs, ["a", "b"])
    assert first["conflict_id"] == second["conflict_id"]


def test_governed_conflict_id_is_invariant_to_observation_order():
    forward = _conflict("title", [_conflict_obs("obs_a"), _conflict_obs("obs_b")], ["a", "b"])
    reversed_ = _conflict("title", [_conflict_obs("obs_b"), _conflict_obs("obs_a")], ["a", "b"])
    assert forward["conflict_id"] == reversed_["conflict_id"]


def test_governed_conflict_id_differs_for_different_field():
    title = _conflict("title", [_conflict_obs("obs_a"), _conflict_obs("obs_b")], ["a", "b"])
    client = _conflict("client", [_conflict_obs("obs_a"), _conflict_obs("obs_b")], ["a", "b"])
    assert title["conflict_id"] != client["conflict_id"]


def test_governed_conflict_id_differs_for_different_values():
    first = _conflict("title", [_conflict_obs("obs_a"), _conflict_obs("obs_b")], ["a", "b"])
    second = _conflict("title", [_conflict_obs("obs_a"), _conflict_obs("obs_b")], ["a", "c"])
    assert first["conflict_id"] != second["conflict_id"]


def test_governed_conflict_id_differs_for_different_participating_observations():
    # Different scopes in real production data mean different participating
    # observations (the resolver groups by scope before calling _conflict),
    # so a scope change is reflected as an observation-set change here.
    first = _conflict("contract_term", [_conflict_obs("obs_a"), _conflict_obs("obs_b")], ["a", "b"])
    second = _conflict("contract_term", [_conflict_obs("obs_c"), _conflict_obs("obs_d")], ["a", "b"])
    assert first["conflict_id"] != second["conflict_id"]


def test_governed_conflict_object_carries_no_ordinal_or_positional_identity():
    conflict = _conflict("title", [_conflict_obs("obs_a"), _conflict_obs("obs_b")], ["a", "b"])
    assert conflict["conflict_id"].startswith("conf_")
    assert len(conflict["conflict_id"]) == len("conf_") + 64  # sha256 hex digest


# --- Section D: extractor.detect_document_conflicts ordinal instability ----

def _eval_criteria(weight_a, weight_b, doc="a.pdf", criterion_id="CR1"):
    ref = [{"source_doc": doc}]
    return [
        {"criterion_id": criterion_id, "weight": weight_a, "source_refs": ref},
        {"criterion_id": criterion_id, "weight": weight_b, "source_refs": ref},
    ]


def _dates(doc="a.pdf"):
    return [
        {"milestone": "Question Deadline", "date": "2030-01-01", "source_doc": doc},
        {"milestone": "Question Deadline", "date": "2030-01-02", "source_doc": doc},
    ]


def test_conf_eval_ordinal_id_shifts_when_an_earlier_family_conflict_is_inserted():
    package_files = ["a.pdf"]
    eval_only = detect_document_conflicts(
        {"evaluation_criteria": _eval_criteria("10 points", "5 points")}, package_files)
    assert eval_only[0]["conflict_id"] == "CONF-EVAL-1"

    with_earlier_date_conflict = detect_document_conflicts(
        {"dates": _dates(), "evaluation_criteria": _eval_criteria("10 points", "5 points")}, package_files)
    eval_entry = next(c for c in with_earlier_date_conflict if c["conflict_type"] == "EVALUATION_CONFLICT")
    # The SAME semantic evaluation conflict now carries a DIFFERENT ordinal
    # id purely because an unrelated, earlier-processed family produced a
    # conflict first -- direct, code-level proof the id is positional, not
    # content-derived, and must never be treated as a durable identity.
    assert eval_entry["conflict_id"] == "CONF-EVAL-2"
    assert eval_entry["conflict_id"] != "CONF-EVAL-1"


def test_conf_eval_ordinal_id_is_not_derived_from_semantic_content():
    package_files = ["a.pdf"]
    first_run = detect_document_conflicts(
        {"evaluation_criteria": _eval_criteria("10 points", "5 points", criterion_id="CR1")}, package_files)
    second_run = detect_document_conflicts(
        {"evaluation_criteria": _eval_criteria("30 points", "20 points", criterion_id="TC1")}, package_files)
    # Two entirely unrelated evaluation-weight discrepancies -- different
    # criterion, different values -- receive the identical ordinal id
    # because both happen to be the first conflict detected in their own
    # independent run. The id string alone carries zero semantic meaning.
    assert first_run[0]["conflict_id"] == second_run[0]["conflict_id"] == "CONF-EVAL-1"
    assert first_run[0]["source_a"] != second_run[0]["source_a"]


def test_conf_eval_ordinal_ids_have_no_relationship_to_any_governed_conflict_id_format():
    package_files = ["a.pdf"]
    conflicts = detect_document_conflicts(
        {"evaluation_criteria": _eval_criteria("10 points", "5 points")}, package_files)
    assert not conflicts[0]["conflict_id"].startswith("conf_")
    assert not conflicts[0]["conflict_id"].startswith("struct_conf_")
