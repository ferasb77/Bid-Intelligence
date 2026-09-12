from dataclasses import FrozenInstanceError, fields, replace
from datetime import date, datetime, timezone

import pytest

from buyer_brief import BuyerBrief, build_buyer_brief
from buyer_domain import CanonicalBuyer, GovernmentLevel, Jurisdiction, OrganizationType
from buyer_evidence import (
    AuthenticityStatus, BuyerEvidenceSet, EvidenceAuthority, EvidenceCitation,
    EvidenceDocument, EvidenceExtract, EvidenceFreshness, EvidenceScope,
    EvidenceSource, FreshnessStatus, LocatorType, ScopeType, SourceCategory,
)
from buyer_intelligence import (
    BuyerFact, BuyerIntelligenceAnalysis, FactClass, FactKind,
    GovernedBuyerInputs, SupportStatus, governed_input_digest,
)
from decision_analyst import (
    AnalystReasoning, AnalystUnknowns, DecisionAnalysis, ManagementQuestion,
    SupportStatus as AnalystSupportStatus,
)
from decision_intelligence import (
    Confidence, DecisionStatement, EvidenceSupport, ReasoningStatus, SourceType,
    StatementSource, StatementType, SupportedEntityType,
)
from executive_briefing_pack import (
    PACK_CONTRACT_NAME, PACK_CONTRACT_VERSION, PACK_EDITION,
    SLOT_BUYER_BRIEF, SLOT_EXECUTIVE_OPPORTUNITY_BRIEF,
    VOLUME_CLASS_BUYER_BRIEF, VOLUME_CLASS_EXECUTIVE_OPPORTUNITY_BRIEF,
    ExecutiveBriefingPack, ExecutiveBriefingPackError, PackFailureCode,
    build_executive_briefing_pack, validate_executive_briefing_pack,
)
from executive_opportunity_brief import build_executive_opportunity_brief
from executive_opportunity_understanding import (
    ExecutiveUnderstandingInput, build_executive_opportunity_understanding,
)
from governed_reference_resolution import (
    AuthorityClass, SemanticField, SemanticValue, SemanticValueKind,
    create_governed_object, create_governed_snapshot, create_resolution_context,
    reference_to,
)
from opportunity_intelligence import ANALYST_VERSION
from opportunity_intelligence_publication import (
    OpportunitySupportBinding, publish_opportunity_intelligence,
)

BUYER_ID = "buyer:bank-of-canada"


def _understanding(opportunity_id):
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
        (AnalystReasoning(inference, AnalystSupportStatus.PARTIALLY_SUPPORTED),),
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
        ExecutiveUnderstandingInput(opportunity_id, publication))


def _eob(opportunity_id="opportunity:pack-under-test"):
    return build_executive_opportunity_brief(_understanding(opportunity_id))


def _governed_buyer_inputs(opportunity_id="opportunity:pack-under-test"):
    source = EvidenceSource("source:buyer", "Bank of Canada",
                            EvidenceAuthority.OFFICIAL_BUYER,
                            "https://www.bankofcanada.ca/")
    document = EvidenceDocument(
        "document:plan", source.source_id, SourceCategory.STRATEGIC_PLAN,
        "Strategic Plan", "https://www.bankofcanada.ca/plan", "en-CA",
        AuthenticityStatus.VERIFIED, date(2030, 2, 2),
        EvidenceFreshness(FreshnessStatus.CURRENT, date(2030, 2, 2)),
        (EvidenceScope(ScopeType.ORGANIZATION, BUYER_ID),), date(2030, 1, 1),
    )
    citation = EvidenceCitation("citation:mandate", document.document_id,
                                LocatorType.SECTION, "Mandate")
    extract = EvidenceExtract("extract:mandate", document.document_id,
                              "The Bank has a statutory mandate.",
                              ("citation:mandate",), "en-CA")
    evidence = BuyerEvidenceSet("evidence-set:buyer", BUYER_ID, (source,),
                                (document,), (citation,), (extract,))
    buyer = CanonicalBuyer(
        BUYER_ID, "Bank of Canada", "CA", Jurisdiction("CA", "Canada"),
        GovernmentLevel.FEDERAL, OrganizationType.CENTRAL_BANK, ("extract:mandate",),
    )
    return GovernedBuyerInputs(
        buyer, evidence, opportunity_id, "canonical-opportunity/1", "a" * 64,
        (opportunity_id,), ("procurement:notice",), "b" * 64, "context:buyer",
        date(2030, 2, 2), "analysis:opportunity", "1.0.0",
    )


def _buyer_brief(opportunity_id="opportunity:pack-under-test"):
    inputs = _governed_buyer_inputs(opportunity_id)
    mandate = BuyerFact("fact:mandate", FactClass.AUTHORITATIVE_BUYER_FACT,
                        FactKind.MANDATE, "The Bank has a statutory mandate.",
                        SupportStatus.SUPPORTED, ("extract:mandate",))
    analysis = BuyerIntelligenceAnalysis(
        "analysis:buyer", BUYER_ID, opportunity_id, "context:buyer",
        governed_input_digest(inputs), ("extract:mandate", "citation:mandate"),
        (mandate,), (), (), (), (), (), (), (), (), (), (),
    )
    return build_buyer_brief(inputs, analysis)


def _pack(opportunity_id="opportunity:pack-under-test"):
    return build_executive_briefing_pack(_eob(opportunity_id), buyer_brief=_buyer_brief(opportunity_id))


def test_successful_deterministic_composition_preserves_every_member_property():
    eob, bb = _eob(), _buyer_brief()
    pack = build_executive_briefing_pack(eob, buyer_brief=bb)
    validate_executive_briefing_pack(pack)
    assert pack.executive_opportunity_brief is eob
    assert pack.buyer_brief is bb
    eob_member = pack.manifest.members[0]
    bb_member = pack.manifest.members[1]
    assert eob_member.artifact_id == eob.brief_id == eob_member.revision_id
    assert bb_member.artifact_id == bb.brief_id == bb_member.revision_id
    assert eob_member.evidence_cutoff is None and eob_member.evidence_cutoff_governed_absence
    assert bb_member.evidence_cutoff == bb.evidence_cutoff_date
    assert not bb_member.evidence_cutoff_governed_absence
    assert pack.manifest.opportunity_id == eob.understanding.opportunity_id == bb.opportunity_id
    assert pack.manifest.buyer_id == bb.buyer_id
    assert pack.manifest.pack_contract_name == PACK_CONTRACT_NAME
    assert pack.manifest.pack_contract_version == PACK_CONTRACT_VERSION
    assert pack.manifest.edition == PACK_EDITION


def test_missing_member_fails_closed():
    pack = _pack()
    bad_manifest = replace(pack.manifest, members=(pack.manifest.members[0],))
    with pytest.raises(ExecutiveBriefingPackError) as excinfo:
        replace(pack, manifest=bad_manifest)
    assert excinfo.value.code == PackFailureCode.MISSING_MEMBER
    assert excinfo.value.slot == SLOT_BUYER_BRIEF


def test_missing_executive_opportunity_brief_member_fails_closed():
    # The mirror image of test_missing_member_fails_closed -- both required
    # slots must be independently proven to fail closed when absent, not
    # just the one already covered.
    pack = _pack()
    bad_manifest = replace(pack.manifest, members=(pack.manifest.members[1],))
    with pytest.raises(ExecutiveBriefingPackError) as excinfo:
        replace(pack, manifest=bad_manifest)
    assert excinfo.value.code == PackFailureCode.MISSING_MEMBER
    assert excinfo.value.slot == SLOT_EXECUTIVE_OPPORTUNITY_BRIEF


def test_executive_opportunity_brief_evidence_cutoff_must_be_a_governed_absence():
    # Executive Opportunity Brief's own contract has no evidence-cutoff
    # concept at all -- an explicit, contract-governed absence
    # (EXECUTIVE_BRIEFING_PACK_ARCHITECTURE.md §9). A manifest claiming a
    # real cutoff date for this slot is fabricating a fact the member's own
    # contract never asserts and must fail closed.
    pack = _pack()
    tampered = replace(pack.manifest.members[0], evidence_cutoff=date(2026, 1, 1),
                       evidence_cutoff_governed_absence=False)
    bad_manifest = replace(pack.manifest, members=(tampered, pack.manifest.members[1]))
    with pytest.raises(ExecutiveBriefingPackError) as excinfo:
        replace(pack, manifest=bad_manifest)
    assert excinfo.value.code == PackFailureCode.EVIDENCE_CUTOFF_INCOMPATIBLE
    assert excinfo.value.slot == SLOT_EXECUTIVE_OPPORTUNITY_BRIEF


def test_buyer_brief_evidence_cutoff_cannot_be_claimed_as_a_governed_absence():
    # The inverse: Buyer Brief's own contract always carries a real,
    # explicit evidence cutoff date -- claiming a "governed absence" for it
    # would hide a real evidence date the member contract actually asserts.
    pack = _pack()
    tampered = replace(pack.manifest.members[1], evidence_cutoff=None,
                       evidence_cutoff_governed_absence=True)
    bad_manifest = replace(pack.manifest, members=(pack.manifest.members[0], tampered))
    with pytest.raises(ExecutiveBriefingPackError) as excinfo:
        replace(pack, manifest=bad_manifest)
    assert excinfo.value.code == PackFailureCode.EVIDENCE_CUTOFF_INCOMPATIBLE
    assert excinfo.value.slot == SLOT_BUYER_BRIEF


def test_swapped_member_types_are_rejected_not_duck_typed():
    # A real BuyerBrief offered where an ExecutiveOpportunityBrief is
    # required (and vice versa) must be rejected by isinstance, never
    # accepted merely because both are dataclasses with a brief_version /
    # brief_id-shaped surface.
    eob, bb = _eob(), _buyer_brief()
    with pytest.raises(ExecutiveBriefingPackError) as excinfo:
        build_executive_briefing_pack(bb, buyer_brief=eob)
    assert excinfo.value.code == PackFailureCode.INVALID_MEMBER


def test_duplicate_member_fails_closed():
    pack = _pack()
    eob_member = pack.manifest.members[0]
    duplicated = replace(eob_member, slot=SLOT_BUYER_BRIEF)
    bad_manifest = replace(pack.manifest, members=(eob_member, duplicated))
    with pytest.raises(ExecutiveBriefingPackError) as excinfo:
        replace(pack, manifest=bad_manifest)
    assert excinfo.value.code == PackFailureCode.DUPLICATE_MEMBER


def test_digest_mismatch_fails_closed():
    pack = _pack()
    tampered = replace(pack.manifest.members[0], artifact_digest="0" * 64)
    bad_manifest = replace(pack.manifest, members=(tampered, pack.manifest.members[1]))
    with pytest.raises(ExecutiveBriefingPackError) as excinfo:
        replace(pack, manifest=bad_manifest)
    assert excinfo.value.code == PackFailureCode.DIGEST_MISMATCH
    assert excinfo.value.slot == SLOT_EXECUTIVE_OPPORTUNITY_BRIEF


def test_revision_mismatch_fails_closed():
    pack = _pack()
    tampered = replace(pack.manifest.members[1], revision_id="buyer-brief:" + "f" * 64)
    bad_manifest = replace(pack.manifest, members=(pack.manifest.members[0], tampered))
    with pytest.raises(ExecutiveBriefingPackError) as excinfo:
        replace(pack, manifest=bad_manifest)
    assert excinfo.value.code == PackFailureCode.REVISION_MISMATCH
    assert excinfo.value.slot == SLOT_BUYER_BRIEF


def test_authority_mismatch_between_members_fails_closed():
    eob = _eob("opportunity:volume-a")
    bb = _buyer_brief("opportunity:volume-b")
    with pytest.raises(ExecutiveBriefingPackError) as excinfo:
        build_executive_briefing_pack(eob, buyer_brief=bb)
    assert excinfo.value.code == PackFailureCode.IDENTITY_MISMATCH
    assert excinfo.value.slot == SLOT_BUYER_BRIEF


def test_incompatible_publication_contract_version_fails_closed():
    # BuyerBrief.__post_init__ already refuses to construct an unsupported
    # version normally (its own contract is self-enforcing); bypass that
    # constructor to prove the pack layer independently fail-closes too,
    # as defense in depth against any member that carries an incompatible
    # contract version.
    eob = _eob()
    bb = _buyer_brief()
    unsupported_bb = object.__new__(BuyerBrief)
    for item in fields(bb):
        object.__setattr__(unsupported_bb, item.name, getattr(bb, item.name))
    object.__setattr__(unsupported_bb, "brief_version", "buyer-brief/999")
    with pytest.raises(ExecutiveBriefingPackError) as excinfo:
        build_executive_briefing_pack(eob, buyer_brief=unsupported_bb)
    assert excinfo.value.code == PackFailureCode.UNSUPPORTED_MEMBER_VERSION
    assert excinfo.value.slot == SLOT_BUYER_BRIEF


def test_ordering_is_fixed_executive_opportunity_brief_then_buyer_brief():
    pack = _pack()
    assert [item.slot for item in pack.manifest.members] == [
        SLOT_EXECUTIVE_OPPORTUNITY_BRIEF, SLOT_BUYER_BRIEF]
    assert [item.volume_class for item in pack.manifest.members] == [
        VOLUME_CLASS_EXECUTIVE_OPPORTUNITY_BRIEF, VOLUME_CLASS_BUYER_BRIEF]


def test_replay_determinism_produces_identical_pack_and_bytes():
    eob, bb = _eob(), _buyer_brief()
    first = build_executive_briefing_pack(eob, buyer_brief=bb)
    second = build_executive_briefing_pack(eob, buyer_brief=bb)
    assert first.pack_id == second.pack_id
    assert first.pack_revision_id == second.pack_revision_id
    assert first.pack_digest == second.pack_digest
    assert first.manifest.manifest_digest == second.manifest.manifest_digest
    assert first.to_json() == second.to_json()


def test_fail_closed_rejects_wrong_types_and_is_immutable():
    with pytest.raises(ExecutiveBriefingPackError) as excinfo:
        build_executive_briefing_pack(object(), buyer_brief=_buyer_brief())
    assert excinfo.value.code == PackFailureCode.INVALID_MEMBER
    with pytest.raises(ExecutiveBriefingPackError) as excinfo:
        build_executive_briefing_pack(_eob(), buyer_brief=object())
    assert excinfo.value.code == PackFailureCode.INVALID_MEMBER
    pack = _pack()
    with pytest.raises(FrozenInstanceError):
        pack.pack_id = "changed"


def test_pack_never_copies_rewrites_or_regenerates_member_content():
    import pathlib

    text = (pathlib.Path(__file__).resolve().parents[1] / "executive_briefing_pack.py").read_text(
        encoding="utf-8").casefold()
    for forbidden in ("requests", "urllib.request", "anthropic", "openai", "extractor", "stage_d"):
        assert forbidden not in text
