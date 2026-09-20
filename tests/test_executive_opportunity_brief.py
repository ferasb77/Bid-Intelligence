from dataclasses import FrozenInstanceError, fields, replace
from datetime import datetime, timezone

import pytest

from decision_analyst import (
    AnalystReasoning, AnalystUnknowns, DecisionAnalysis, ManagementQuestion,
    SupportStatus,
)
from decision_intelligence import (
    Confidence, ContractValidationError, DecisionStatement, EvidenceSupport,
    ReasoningStatus, SourceType, StatementSource, StatementType,
    SupportedEntityType,
)
from executive_opportunity_brief import (
    BRIEF_VERSION, ExecutiveOpportunityBrief, build_executive_opportunity_brief,
    render_executive_opportunity_brief,
)
from executive_opportunity_understanding import (
    ExecutiveUnderstandingInput, SECTION_ORDER,
    build_executive_opportunity_understanding,
)
from governed_reference_resolution import (
    AuthorityClass, GovernedObjectReference as LowLevelGovernedObjectReference,
    GovernedRelationship, RelationshipKind, ResolutionRequest, SemanticField,
    SemanticValue, SemanticValueKind, create_governed_object, create_governed_snapshot,
    create_resolution_context, reference_to, resolve_governed_reference,
)
from opportunity_intelligence import ANALYST_VERSION
from opportunity_intelligence_publication import (
    OpportunitySupportBinding, publish_opportunity_intelligence,
)


def _understanding():
    fact = create_governed_object(
        owner_domain="canonical-opportunity", owner_contract="canonical-opportunity",
        contract_version="1.0.0", object_class="canonical-fact",
        object_id="canonical-1", authority=AuthorityClass.CANONICAL_FACT,
        semantic_fields=(SemanticField(
            "value", SemanticValue(SemanticValueKind.STRING, "Known fact")),),
    )
    evidence = create_governed_object(
        owner_domain="canonical-opportunity", owner_contract="canonical-opportunity",
        contract_version="1.0.0", object_class="evidence", object_id="evidence-1",
        authority=AuthorityClass.EVIDENCE,
        semantic_fields=(SemanticField(
            "locator", SemanticValue(SemanticValueKind.STRING, "page 1")),),
    )
    snapshot = create_governed_snapshot(
        owner_domain="canonical-opportunity", owner_contract="canonical-opportunity",
        contract_version="1.0.0", snapshot_id="canonical-snapshot-1",
        objects=(fact, evidence),
    )
    context = create_resolution_context(
        context_id="authoritative-context-1", context_version="1.0.0",
        snapshots=(snapshot,),
    )
    support = EvidenceSupport(
        SupportedEntityType.CANONICAL_FACT, "canonical-1", ("evidence-1",))
    binding = OpportunitySupportBinding(
        support, reference_to(snapshot, "canonical-fact", "canonical-1"),
        (reference_to(snapshot, "evidence", "evidence-1"),),
    )
    computed = DecisionStatement(
        "computed-1", StatementType.COMPUTED_FACT, "requirement_count=4",
        StatementSource(SourceType.DETERMINISTIC_COMPUTATION, "test/count"),
        None, ReasoningStatus.VALIDATED, support.evidence_ids,
        (support.entity_id,), (support,),
    )
    inference = DecisionStatement(
        "inference-1", StatementType.AI_INFERENCE,
        "The documented structure contains an effort consideration.",
        StatementSource(SourceType.SPECIALIST_ANALYST, "opportunity-intelligence"),
        Confidence.MODERATE, ReasoningStatus.PROPOSED, support.evidence_ids,
        (computed.statement_id,), (support,),
    )
    analysis = DecisionAnalysis(
        "analysis-1", "opportunity-intelligence",
        datetime(2030, 1, 1, 12, tzinfo=timezone.utc), Confidence.MODERATE,
        (support,), (computed,),
        (AnalystReasoning(inference, SupportStatus.PARTIALLY_SUPPORTED),),
        (), (), ("Analysis is limited to supplied evidence.",), (),
        (ManagementQuestion("question-1", "What requires human judgment?",
                            (inference.statement_id,)),),
        AnalystUnknowns(ambiguous_observation_ids=(support.entity_id,)),
    )
    publication = publish_opportunity_intelligence(
        analysis, analyst_version=ANALYST_VERSION,
        authoritative_context=context, support_bindings=(binding,),
    )
    return build_executive_opportunity_understanding(
        ExecutiveUnderstandingInput("opportunity-1", publication))


def test_accepts_only_validated_executive_opportunity_understanding():
    understanding = _understanding()
    brief = build_executive_opportunity_brief(understanding)
    assert isinstance(brief, ExecutiveOpportunityBrief)
    assert brief.brief_version == BRIEF_VERSION
    with pytest.raises(ContractValidationError, match="ExecutiveOpportunityUnderstanding"):
        build_executive_opportunity_brief({})


def test_preserves_index_detail_coverage_and_identity_bindings():
    understanding = _understanding()
    brief = build_executive_opportunity_brief(understanding)
    assert tuple(item.section for item in brief.sections) == SECTION_ORDER
    assert tuple(item.object_ids for item in brief.sections) == tuple(
        item.object_ids for item in understanding.executive_index)
    assert brief.detail_register == understanding.detail_register.references()
    assert brief.coverage_ledger == understanding.coverage_ledger
    assert brief.publication_id == understanding.publication_id
    assert brief.publication_snapshot_id == understanding.publication_snapshot_id
    assert brief.publication_snapshot_digest == understanding.publication_snapshot_digest


def test_rendering_uses_resolved_owner_values_and_preserves_provenance():
    brief = build_executive_opportunity_brief(_understanding())
    rendered = render_executive_opportunity_brief(brief)
    assert "requirement_count=4" in rendered
    assert "The documented structure contains an effort consideration." in rendered
    assert "canonical-opportunity/canonical-opportunity/1.0.0/evidence/evidence-1" in rendered
    assert "EVIDENCE_SUPPORT" in rendered
    assert brief.publication_snapshot_id in rendered


def test_rendering_fails_closed_for_a_stale_bound_context():
    brief = build_executive_opportunity_brief(_understanding())
    with pytest.raises(ContractValidationError):
        replace(brief.understanding, context_digest="0" * 64)


def test_identical_understanding_produces_identical_brief_and_bytes():
    understanding = _understanding()
    first = build_executive_opportunity_brief(understanding)
    second = build_executive_opportunity_brief(understanding)
    assert first == second
    assert first.to_json() == second.to_json()
    assert render_executive_opportunity_brief(first) == render_executive_opportunity_brief(second)


def test_render_resolves_each_reference_exactly_once():
    """Phase 5A offline-profiling finding: render() used to validate (one
    governed-resolution pass over detail_register) and then build its own
    resolved-lookup table (a second, identical pass) -- doubling resolution
    work with zero effect on the rendered bytes. Guards against that
    regressing; the double-computation would also double the effective
    cost of the ~1,000-relationship-per-object rendering this brief type
    produces on a real Bank of Canada-sized document set."""
    import executive_opportunity_brief as eob

    brief = build_executive_opportunity_brief(_understanding())
    calls = []
    original = eob._resolve

    def counting_resolve(reference, understanding):
        calls.append(reference.object_id)
        return original(reference, understanding)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(eob, "_resolve", counting_resolve)
        render_executive_opportunity_brief(brief)

    assert len(calls) == len(brief.detail_register)
    assert sorted(calls) == sorted(item.object_id for item in brief.detail_register)


def test_brief_is_immutable_and_contains_no_semantic_value_or_upstream_fields():
    brief = build_executive_opportunity_brief(_understanding())
    with pytest.raises(FrozenInstanceError):
        brief.brief_id = "changed"
    names = {item.name for item in fields(brief)}
    assert not names & {
        "analysis", "decision_analysis", "normalized_facts", "stage_d",
        "synthesis", "semantic_values", "recommendations", "score", "decision",
    }
    assert "understanding" not in brief.to_dict()
    assert "semantic_fields" not in brief.to_json()


def test_section_order_is_executive_index_order_and_repeated_values_render_once():
    brief = build_executive_opportunity_brief(_understanding())
    rendered = render_executive_opportunity_brief(brief)
    headings = [f"## {item.heading}" for item in brief.sections]
    assert [rendered.index(value) for value in headings] == sorted(
        rendered.index(value) for value in headings)
    assert rendered.count("The documented structure contains an effort consideration.") == 1


def test_every_detail_object_has_exactly_one_coverage_record_and_is_presented():
    brief = build_executive_opportunity_brief(_understanding())
    detail_ids = tuple(item.object_id for item in brief.detail_register)
    coverage_ids = tuple(item.object_id for item in brief.coverage_ledger)
    assert set(detail_ids) == set(coverage_ids)
    assert len(coverage_ids) == len(set(coverage_ids))
    rendered = render_executive_opportunity_brief(brief)
    assert all(object_id in rendered for object_id in detail_ids)


def test_legacy_multi_input_construction_path_is_removed():
    with pytest.raises(TypeError):
        build_executive_opportunity_brief({}, {}, object())


# ---------------------------------------------------------------------------
# Phase 5B: relationship-rendering compaction. Phase 5A found ~1,000
# relationships per object in a real Bank of Canada brief, each re-embedding
# the target's full owner/contract/version/snapshot/digest identity inline
# even when that same target is ALSO separately rendered in full elsewhere
# in the same document. Domain-contract review of governed_reference_
# resolution.py (this phase) proved that's always redundant when true: a
# brief is scoped to exactly one publication snapshot (validate_executive_
# opportunity_understanding's completeness check), and
# resolve_governed_reference resolves every relationship target from that
# same snapshot's object graph the detail register itself is built from --
# so a relationship's target and that object's own detail-register entry
# always carry identical owner/contract/version/snapshot_id/snapshot_digest/
# object_digest. These tests exercise _render_reference directly against
# real governed_reference_resolution.py machinery (not a duck-typed stub)
# to prove the compacted form drops no information and the uncompacted
# fallback is unchanged when a target is NOT independently detail-registered.
# ---------------------------------------------------------------------------

def _two_object_snapshot_with_relationship():
    """OBSERVATION obs-a --CONFLICT_MEMBER--> OBSERVATION obs-b, both in one
    snapshot. Mirrors the real relationship kind Phase 5A found dominating
    the oversized brief (CONFLICT_MEMBER / affected-observation)."""
    owner_domain, owner_contract, contract_version = "test-domain", "test-contract", "1.0.0"
    snapshot_id = "snap-1"
    placeholder_target = LowLevelGovernedObjectReference(
        owner_domain, owner_contract, contract_version, snapshot_id,
        "0" * 64,  # patched to the real snapshot digest by create_governed_snapshot
        "OBSERVATION", "obs-b", "0" * 64,  # patched below via obs_b's own real digest
    )
    obs_b = create_governed_object(
        owner_domain=owner_domain, owner_contract=owner_contract,
        contract_version=contract_version, object_class="OBSERVATION", object_id="obs-b",
        authority=AuthorityClass.OBSERVATION,
        semantic_fields=(SemanticField("summary", SemanticValue(SemanticValueKind.STRING, "B")),),
    )
    obs_a = create_governed_object(
        owner_domain=owner_domain, owner_contract=owner_contract,
        contract_version=contract_version, object_class="OBSERVATION", object_id="obs-a",
        authority=AuthorityClass.OBSERVATION,
        semantic_fields=(SemanticField("summary", SemanticValue(SemanticValueKind.STRING, "A")),),
        relationships=(GovernedRelationship(
            RelationshipKind.CONFLICT_MEMBER, "affected-observation",
            replace(placeholder_target, object_digest=obs_b.object_digest), 0),),
    )
    snapshot = create_governed_snapshot(
        owner_domain=owner_domain, owner_contract=owner_contract,
        contract_version=contract_version, snapshot_id=snapshot_id, objects=(obs_a, obs_b))
    context = create_resolution_context(
        context_id="ctx-1", context_version="1.0.0", snapshots=(snapshot,))
    ref_a = reference_to(snapshot, "OBSERVATION", "obs-a")
    ref_b = reference_to(snapshot, "OBSERVATION", "obs-b")
    resolved_a = resolve_governed_reference(
        ResolutionRequest(ref_a, context.context_id, context.context_digest,
                          AuthorityClass.OBSERVATION, (), (RelationshipKind.CONFLICT_MEMBER,)),
        context)
    resolved_b = resolve_governed_reference(
        ResolutionRequest(ref_b, context.context_id, context.context_digest,
                          AuthorityClass.OBSERVATION), context)
    return ref_a, ref_b, resolved_a, resolved_b


class _FakeHighLevelReference:
    """Duck-types only what _render_reference actually reads off a
    high-level (executive_opportunity_understanding) GovernedObjectReference
    -- avoids constructing the full publication/understanding pipeline just
    to exercise the rendering function directly."""
    def __init__(self, low_level_ref, detail_pointer, object_class):
        self.source_reference = low_level_ref
        self.detail_pointer = detail_pointer
        self.object_class = object_class


def test_relationship_to_a_detail_registered_object_is_compacted():
    import executive_opportunity_brief as eob

    ref_a, ref_b, resolved_a, resolved_b = _two_object_snapshot_with_relationship()
    high_a = _FakeHighLevelReference(ref_a, "/detail_register/observations/0", "OBSERVATION")
    high_b = _FakeHighLevelReference(ref_b, "/detail_register/observations/1", "OBSERVATION")
    detail_register_by_id = {"obs-a": high_a, "obs-b": high_b}

    lines = eob._render_reference(high_a, resolved_a, detail_register_by_id)
    relationship_lines = [line for line in lines if "CONFLICT_MEMBER" in line]
    assert len(relationship_lines) == 1
    assert "see `/detail_register/observations/1`" in relationship_lines[0]
    # No re-embedded full identity for the target in the compacted form.
    assert "test-domain/test-contract" not in relationship_lines[0]
    assert resolved_a.relationships[0].target.object_digest not in relationship_lines[0]


def test_compacted_reference_loses_no_information_vs_the_targets_own_block():
    """The core equivalence proof: every identity field the compacted line
    omits is recoverable, byte-for-byte, from the target's own rendered
    block via the detail_pointer the compacted line points to."""
    import executive_opportunity_brief as eob

    ref_a, ref_b, resolved_a, resolved_b = _two_object_snapshot_with_relationship()
    high_a = _FakeHighLevelReference(ref_a, "/detail_register/observations/0", "OBSERVATION")
    high_b = _FakeHighLevelReference(ref_b, "/detail_register/observations/1", "OBSERVATION")
    detail_register_by_id = {"obs-a": high_a, "obs-b": high_b}

    target = resolved_a.relationships[0].target
    b_own_block = "\n".join(eob._render_reference(high_b, resolved_b, detail_register_by_id))

    assert f"Snapshot: `{target.snapshot_id}`" in b_own_block
    assert f"Snapshot digest: `{target.snapshot_digest}`" in b_own_block
    assert f"Object digest: `{target.object_digest}`" in b_own_block
    assert f"Owner: `{target.owner_domain}/{target.owner_contract}`" in b_own_block
    assert f"Contract version: `{target.contract_version}`" in b_own_block


def test_relationship_to_a_non_detail_registered_object_stays_fully_inline():
    """When the target is NOT independently detail-registered (e.g. an
    evidence object referenced only via relationship -- the case every
    pre-existing test in this file already exercises), the full identity
    must still be embedded inline; nothing may be silently dropped."""
    import executive_opportunity_brief as eob

    ref_a, ref_b, resolved_a, resolved_b = _two_object_snapshot_with_relationship()
    high_a = _FakeHighLevelReference(ref_a, "/detail_register/observations/0", "OBSERVATION")
    detail_register_by_id = {"obs-a": high_a}  # obs-b deliberately absent

    lines = eob._render_reference(high_a, resolved_a, detail_register_by_id)
    relationship_lines = [line for line in lines if "CONFLICT_MEMBER" in line]
    assert len(relationship_lines) == 1
    target = resolved_a.relationships[0].target
    assert f"{target.owner_domain}/{target.owner_contract}/{target.contract_version}" in relationship_lines[0]
    assert target.snapshot_id in relationship_lines[0]
    assert target.snapshot_digest in relationship_lines[0]
    assert target.object_digest in relationship_lines[0]
    assert "see `" not in relationship_lines[0]


def test_relationship_to_object_class_mismatch_falls_back_to_full_inline():
    """Defense in depth: even if some future object_id collides across
    object_classes, a class mismatch must never trigger compaction."""
    import executive_opportunity_brief as eob

    ref_a, ref_b, resolved_a, resolved_b = _two_object_snapshot_with_relationship()
    high_a = _FakeHighLevelReference(ref_a, "/detail_register/observations/0", "OBSERVATION")
    # obs-b is present in the detail register, but under a DIFFERENT object_class --
    # must not be treated as the same object.
    wrong_class_b = _FakeHighLevelReference(ref_b, "/detail_register/other/0", "SOME_OTHER_CLASS")
    detail_register_by_id = {"obs-a": high_a, "obs-b": wrong_class_b}

    lines = eob._render_reference(high_a, resolved_a, detail_register_by_id)
    relationship_lines = [line for line in lines if "CONFLICT_MEMBER" in line]
    assert "see `" not in relationship_lines[0]
    target = resolved_a.relationships[0].target
    assert target.object_digest in relationship_lines[0]
