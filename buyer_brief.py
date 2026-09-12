"""Deterministic presentation of a validated Buyer Intelligence analysis."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from enum import Enum
from hashlib import sha256
import json
from typing import Any

from buyer_domain import CanonicalBuyer
from buyer_evidence import (
    EvidenceCitation, EvidenceDocument, EvidenceExtract, EvidenceSource,
)
from buyer_intelligence import (
    BuyerAssumption, BuyerConflict, BuyerFact, BuyerHypothesis,
    BuyerIntelligenceAnalysis, BuyerIntelligenceValidationError,
    BuyerInterpretation, BuyerLimitation, BuyerManagementQuestion, BuyerUnknown,
    ComputedFact, FactKind, GovernedBuyerInputs, InterpretationKind,
    validate_buyer_intelligence,
)


BUYER_BRIEF_VERSION = "buyer-brief/1"
SECTION_ORDER = (
    "Buyer at a Glance",
    "Mandate and Operating Context",
    "Relevant Organizational Context",
    "Published Priorities in Context",
    "Opportunity-to-Organization Context",
    "Current Procurement Context",
    "Questions for the Proposal Kickoff",
    "Known Unknowns and Assumptions",
    "Evidence Register",
    "Limitations",
)


@dataclass(frozen=True, slots=True)
class IdentityItem:
    label: str
    value: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BuyerAtAGlance:
    identity: tuple[IdentityItem, ...]
    facts: tuple[BuyerFact, ...]

    def __post_init__(self) -> None:
        if len(self.identity) + len(self.facts) > 6:
            raise BuyerIntelligenceValidationError("Buyer at a Glance cannot exceed six items")


@dataclass(frozen=True, slots=True)
class FactSection:
    facts: tuple[BuyerFact, ...]
    computed_facts: tuple[ComputedFact, ...] = ()


@dataclass(frozen=True, slots=True)
class ContextSection:
    facts: tuple[BuyerFact, ...]
    interpretations: tuple[BuyerInterpretation, ...]


@dataclass(frozen=True, slots=True)
class InterpretationSection:
    interpretations: tuple[BuyerInterpretation, ...]
    hypotheses: tuple[BuyerHypothesis, ...]


@dataclass(frozen=True, slots=True)
class UncertaintySection:
    unknowns: tuple[BuyerUnknown, ...]
    conflicts: tuple[BuyerConflict, ...]
    assumptions: tuple[BuyerAssumption, ...]


@dataclass(frozen=True, slots=True)
class EvidenceRegisterEntry:
    marker: str
    evidence_id: str
    source_class: str
    source: EvidenceSource | None = None
    document: EvidenceDocument | None = None
    citation: EvidenceCitation | None = None
    extract: EvidenceExtract | None = None


@dataclass(frozen=True, slots=True)
class BuyerBrief:
    brief_id: str
    brief_version: str
    analysis_id: str
    buyer_id: str
    opportunity_id: str
    evidence_cutoff_date: date
    section_order: tuple[str, ...]
    buyer_at_a_glance: BuyerAtAGlance
    mandate_and_operating_context: FactSection
    relevant_organizational_context: ContextSection
    published_priorities_in_context: ContextSection
    opportunity_to_organization_context: InterpretationSection
    current_procurement_context: FactSection
    questions_for_proposal_kickoff: tuple[BuyerManagementQuestion, ...]
    known_unknowns_and_assumptions: UncertaintySection
    evidence_register: tuple[EvidenceRegisterEntry, ...]
    limitations: tuple[BuyerLimitation, ...]

    def __post_init__(self) -> None:
        if self.brief_version != BUYER_BRIEF_VERSION:
            raise BuyerIntelligenceValidationError("unsupported Buyer Brief version")
        if self.section_order != SECTION_ORDER:
            raise BuyerIntelligenceValidationError("Buyer Brief section order is invalid")
        if type(self.evidence_cutoff_date) is not date:
            raise BuyerIntelligenceValidationError("evidence_cutoff_date must be a date")
        markers = tuple(item.marker for item in self.evidence_register)
        evidence_ids = tuple(item.evidence_id for item in self.evidence_register)
        if len(markers) != len(set(markers)) or len(evidence_ids) != len(set(evidence_ids)):
            raise BuyerIntelligenceValidationError("evidence register identities must be unique")
        if markers != tuple(f"E{i}" for i in range(1, len(markers) + 1)):
            raise BuyerIntelligenceValidationError("evidence markers must be consecutive")

    def to_dict(self) -> dict[str, Any]:
        return _primitives(asdict(self))

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"))


def _identity_items(buyer: CanonicalBuyer) -> tuple[IdentityItem, ...]:
    jurisdiction = buyer.jurisdiction.name
    if buyer.jurisdiction.subdivision_code:
        jurisdiction += f" ({buyer.jurisdiction.subdivision_code})"
    values = (
        ("Legal name", buyer.legal_name),
        ("Common name", buyer.common_name),
        ("Organization type", buyer.organization_type.value.replace("_", " ").title()),
        ("Jurisdiction", jurisdiction),
        ("Government level", buyer.government_level.value.replace("_", " ").title()),
        ("Public mandate", buyer.public_mandate),
    )
    return tuple(IdentityItem(label, value, buyer.evidence_ids)
                 for label, value in values if value is not None)


def _evidence_register(inputs: GovernedBuyerInputs,
                       analysis: BuyerIntelligenceAnalysis) -> tuple[EvidenceRegisterEntry, ...]:
    sources = {item.source_id: item for item in inputs.evidence.sources}
    documents = {item.document_id: item for item in inputs.evidence.documents}
    citations = {item.citation_id: item for item in inputs.evidence.citations}
    extracts = {item.extract_id: item for item in inputs.evidence.extracts}
    entries = []
    for index, evidence_id in enumerate(analysis.evidence_used, 1):
        source = sources.get(evidence_id)
        document = documents.get(evidence_id)
        citation = citations.get(evidence_id)
        extract = extracts.get(evidence_id)
        if citation:
            document = documents[citation.document_id]
        elif extract:
            citation = citations[extract.citation_ids[0]]
            document = documents[extract.document_id]
        if document and source is None:
            source = sources[document.source_id]
        source_class = ("CURRENT_PROCUREMENT_SOURCE" if evidence_id in inputs.procurement_evidence_ids
                        else "AUTHORITATIVE_BUYER_SOURCE")
        entries.append(EvidenceRegisterEntry(f"E{index}", evidence_id, source_class,
                                             source, document, citation, extract))
    return tuple(entries)


def build_buyer_brief(inputs: GovernedBuyerInputs,
                      analysis: BuyerIntelligenceAnalysis) -> BuyerBrief:
    """Project validated analysis into the governed Buyer Brief sections."""
    validate_buyer_intelligence(inputs, analysis)
    buyer = inputs.buyer
    if not set(buyer.evidence_ids).issubset(set(analysis.evidence_used)):
        raise BuyerIntelligenceValidationError("displayed Canonical Buyer identity evidence is absent from evidence_used")

    identity_facts = tuple(item for item in analysis.buyer_facts
                           if item.fact_kind == FactKind.IDENTITY)
    mandate_kinds = {FactKind.MANDATE, FactKind.RESPONSIBILITY, FactKind.GOVERNANCE}
    mandate = tuple(item for item in (*analysis.buyer_facts,
                                      *analysis.public_organizational_information)
                     if item.fact_kind in mandate_kinds)
    organizational_kinds = {
        FactKind.ORGANIZATIONAL_FUNCTION, FactKind.ORGANIZATIONAL_CAPABILITY,
        FactKind.ACCESSIBILITY_COMMITMENT, FactKind.PUBLIC_INITIATIVE,
        FactKind.ORGANIZATIONAL_RELATIONSHIP,
    }
    organizational = tuple(item for item in (*analysis.buyer_facts,
                                               *analysis.public_organizational_information)
                           if item.fact_kind in organizational_kinds)
    priorities = tuple(item for item in analysis.public_organizational_information
                       if item.fact_kind == FactKind.PUBLISHED_PRIORITY)
    function_interpretations = tuple(item for item in analysis.interpretations
                                     if item.kind == InterpretationKind.RELEVANT_ORGANIZATIONAL_FUNCTION)
    priority_interpretations = tuple(item for item in analysis.interpretations
                                     if item.kind == InterpretationKind.PUBLISHED_PRIORITY_CONTEXT)
    reserved = set(function_interpretations + priority_interpretations)
    relationship_interpretations = tuple(item for item in analysis.interpretations
                                         if item not in reserved)

    identity_payload = {
        "version": BUYER_BRIEF_VERSION,
        "analysis": analysis.to_dict(),
        "buyer": buyer.to_dict(),
        "evidence_cutoff": inputs.source_date.isoformat(),
    }
    digest = sha256(json.dumps(identity_payload, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":")).encode("utf-8")).hexdigest()
    return BuyerBrief(
        "buyer-brief:" + digest,
        BUYER_BRIEF_VERSION,
        analysis.analysis_id,
        analysis.buyer_id,
        analysis.opportunity_id,
        inputs.source_date,
        SECTION_ORDER,
        BuyerAtAGlance(_identity_items(buyer), identity_facts),
        FactSection(mandate, analysis.computed_facts),
        ContextSection(organizational, function_interpretations),
        ContextSection(priorities, priority_interpretations),
        InterpretationSection(relationship_interpretations,
                              analysis.competing_hypotheses),
        FactSection(analysis.verified_procurement_context),
        analysis.management_questions,
        UncertaintySection(analysis.unknowns, analysis.conflicts,
                           analysis.assumptions),
        _evidence_register(inputs, analysis),
        analysis.limitations,
    )


def render_buyer_brief(brief: BuyerBrief) -> str:
    """Render the immutable brief without adding content or interpretation."""
    if not isinstance(brief, BuyerBrief):
        raise BuyerIntelligenceValidationError("brief must be a BuyerBrief")
    markers = {item.evidence_id: item.marker for item in brief.evidence_register}
    assumptions = {item.assumption_id: item.statement
                   for item in brief.known_unknowns_and_assumptions.assumptions}

    def refs(evidence_ids: tuple[str, ...]) -> str:
        return " ".join(f"[{markers[item]}]" for item in evidence_ids)

    def fact_lines(items: tuple[BuyerFact, ...]) -> list[str]:
        return [f"- {item.statement} {refs(item.evidence_ids)}" for item in items]

    def interpretation_lines(items: tuple[BuyerInterpretation, ...]) -> list[str]:
        result = []
        for item in items:
            result.append(f"- **Interpretation ({item.confidence.value.title()} confidence):** "
                          f"{item.statement} {refs(item.supporting_evidence_ids)}")
            if item.contradicting_evidence_ids:
                result.append(f"  - **Contradicting evidence:** {refs(item.contradicting_evidence_ids)}")
            if item.assumption_ids:
                result.append("  - **Assumptions:** " + "; ".join(
                    assumptions[assumption_id] for assumption_id in item.assumption_ids))
        return result

    buyer_name = next((item.value for item in brief.buyer_at_a_glance.identity
                       if item.label == "Legal name"), "Buyer")
    lines = ["# Buyer Brief", "",
             f"**Buyer:** {buyer_name}",
             f"**Evidence cutoff:** {brief.evidence_cutoff_date.isoformat()}",
             f"**Document revision:** {brief.brief_version}"]

    lines += ["", "## Buyer at a Glance"]
    lines += ([f"- **{item.label}:** {item.value} {refs(item.evidence_ids)}"
               for item in brief.buyer_at_a_glance.identity] +
              fact_lines(brief.buyer_at_a_glance.facts)) or ["- No validated identity information available."]

    lines += ["", "## Mandate and Operating Context"]
    lines += fact_lines(brief.mandate_and_operating_context.facts) or ["- No validated mandate or operating-context facts available."]
    if brief.mandate_and_operating_context.computed_facts:
        lines += ["", "### Deterministic Computations"]
        lines += [f"- **{item.computation}:** {item.value}"
                  for item in brief.mandate_and_operating_context.computed_facts]

    lines += ["", "## Relevant Organizational Context"]
    lines += fact_lines(brief.relevant_organizational_context.facts)
    lines += interpretation_lines(brief.relevant_organizational_context.interpretations)
    if not (brief.relevant_organizational_context.facts or brief.relevant_organizational_context.interpretations):
        lines.append("- No validated relevant organizational context available.")

    lines += ["", "## Published Priorities in Context"]
    lines += [f"- **Published statement:** {item.statement} {refs(item.evidence_ids)}"
              for item in brief.published_priorities_in_context.facts]
    lines += interpretation_lines(brief.published_priorities_in_context.interpretations)
    if not (brief.published_priorities_in_context.facts or brief.published_priorities_in_context.interpretations):
        lines.append("- No validated published-priority context available.")

    lines += ["", "## Opportunity-to-Organization Context"]
    lines += interpretation_lines(brief.opportunity_to_organization_context.interpretations)
    for item in brief.opportunity_to_organization_context.hypotheses:
        lines.append(f"- **Alternative interpretation ({item.confidence.value.title()} confidence):** "
                     f"{item.statement} {refs(item.supporting_evidence_ids)}")
        if item.contradicting_evidence_ids:
            lines.append(f"  - **Contradicting evidence:** {refs(item.contradicting_evidence_ids)}")
    if not (brief.opportunity_to_organization_context.interpretations or
            brief.opportunity_to_organization_context.hypotheses):
        lines.append("- No validated opportunity-to-organization interpretations available.")

    lines += ["", "## Current Procurement Context"]
    lines += fact_lines(brief.current_procurement_context.facts) or ["- No validated current-procurement context available."]

    lines += ["", "## Questions for the Proposal Kickoff"]
    lines += [f"- {item.question}" for item in brief.questions_for_proposal_kickoff] or ["- No validated management questions available."]

    uncertainty = brief.known_unknowns_and_assumptions
    lines += ["", "## Known Unknowns and Assumptions", "", "### Unknowns"]
    lines += [f"- {item.statement} **Why unresolved:** {item.unresolved_reason}"
              for item in uncertainty.unknowns] or ["- None identified in the validated analysis."]
    lines += ["", "### Ambiguity or Conflict"]
    lines += [f"- {item.subject} {refs(tuple(eid for group in item.opposing_evidence for eid in group))}"
              for item in uncertainty.conflicts] or ["- None identified in the validated analysis."]
    lines += ["", "### Assumptions"]
    lines += [f"- {item.statement} **Evidence gap:** {item.evidence_gap}"
              for item in uncertainty.assumptions] or ["- None used by the validated analysis."]

    lines += ["", "## Evidence Register"]
    for item in brief.evidence_register:
        lines += ["", f"### [{item.marker}] {item.evidence_id}",
                  f"- **Source class:** {item.source_class.replace('_', ' ').title()}"]
        if item.source:
            lines += [f"- **Institutional owner:** {item.source.publisher_name}",
                      f"- **Authority:** {item.source.authority.value.replace('_', ' ').title()}"]
        if item.document:
            publication = item.document.publication_date.isoformat() if item.document.publication_date else "Not stated"
            lines += [f"- **Title:** {item.document.title}",
                      f"- **Publication date:** {publication}",
                      f"- **Retrieval date:** {item.document.retrieval_date.isoformat()}",
                      f"- **Language:** {item.document.language}",
                      f"- **Freshness:** {item.document.freshness.status.value.replace('_', ' ').title()}",
                      f"- **Authenticity:** {item.document.authenticity.value.title()}",
                      f"- **Location:** {item.document.canonical_url}"]
        if item.citation:
            lines.append(f"- **Exact locator:** {item.citation.locator_type.value.title()} — {item.citation.locator}")
        if not item.document:
            lines.append("- **Metadata:** Retained in the authoritative procurement package.")

    lines += ["", "## Limitations"]
    lines += [f"- {item.statement}" for item in brief.limitations] or ["- No limitations recorded in the validated analysis."]
    return "\n".join(lines) + "\n"


def _primitives(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _primitives(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_primitives(item) for item in value]
    return value
