"""Executive Opportunity Brief: a deterministic customer deliverable.

This module presents existing authoritative opportunity data and validated
Opportunity Intelligence. It performs no extraction, recommendation, scoring,
conflict resolution, or executive decision-making.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Mapping

from decision_analyst import DecisionAnalysis
from decision_intelligence import ContractValidationError, EvidenceSupport, SupportedEntityType
from decision_workspace import build_decision_workspace


BRIEF_VERSION = "executive-opportunity-brief/1"


@dataclass(frozen=True, slots=True)
class BriefFact:
    label: str
    value: str
    evidence: tuple[EvidenceSupport, ...]


@dataclass(frozen=True, slots=True)
class BriefObservation:
    observation_id: str
    text: str
    evidence: tuple[EvidenceSupport, ...]


@dataclass(frozen=True, slots=True)
class BriefQuestion:
    question_id: str
    text: str
    related_analysis_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ClarificationCandidate:
    candidate_id: str
    subject: str
    reason: str
    evidence: tuple[EvidenceSupport, ...]


@dataclass(frozen=True, slots=True)
class KnownUnknowns:
    missing_evidence: tuple[str, ...]
    unresolved_conflicts: tuple[str, ...]
    unavailable_information: tuple[str, ...]
    ambiguity: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ExecutiveOpportunityBrief:
    brief_id: str
    brief_version: str
    analysis_id: str
    executive_snapshot: tuple[BriefFact, ...]
    opportunity_structure: tuple[BriefFact, ...]
    key_observations: tuple[BriefObservation, ...]
    management_questions: tuple[BriefQuestion, ...]
    information_required_from_team: tuple[BriefObservation, ...]
    clarification_candidates: tuple[ClarificationCandidate, ...]
    known_unknowns: KnownUnknowns
    limitations: tuple[str, ...]

    def __post_init__(self):
        if self.brief_version != BRIEF_VERSION:
            raise ContractValidationError("unsupported Executive Opportunity Brief version")
        ids = [item.observation_id for item in self.key_observations]
        ids += [item.observation_id for item in self.information_required_from_team]
        ids += [item.question_id for item in self.management_questions]
        ids += [item.candidate_id for item in self.clarification_candidates]
        if len(ids) != len(set(ids)):
            raise ContractValidationError("brief item IDs must be unique")
        if any(not item.evidence for item in (*self.executive_snapshot,
                                               *self.opportunity_structure,
                                               *self.key_observations,
                                               *self.information_required_from_team)):
            raise ContractValidationError("brief facts and observations require evidence")


def _text(value) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    return result or None


def _entity_id(section: str, item: Mapping, index: int) -> str:
    keys = {
        "requirements": ("requirement_id", "req_id"),
        "deliverables": ("deliverable_id",),
        "conflicts": ("conflict_id",),
    }.get(section, ())
    for key in keys:
        if _text(item.get(key)):
            return str(item[key])
    payload = json.dumps(item, sort_keys=True, separators=(",", ":"), default=str)
    return f"brief-{section}-" + sha256(f"{index}:{payload}".encode()).hexdigest()


def _link(entity_type, entity_id, item=None):
    evidence_ids = set()
    if isinstance(item, Mapping):
        if _text(item.get("evidence_id")):
            evidence_ids.add(str(item["evidence_id"]))
        for ref in item.get("source_refs", []) or []:
            if isinstance(ref, Mapping) and _text(ref.get("evidence_id")):
                evidence_ids.add(str(ref["evidence_id"]))
    return EvidenceSupport(entity_type, entity_id, tuple(sorted(evidence_ids)))


def build_executive_opportunity_brief(normalized_facts: Mapping, synthesized_brief: Mapping,
                                      analysis: DecisionAnalysis, *, conflicts=None) -> ExecutiveOpportunityBrief:
    """Build a lossless presentation from existing authoritative outputs."""
    if not isinstance(normalized_facts, Mapping) or not isinstance(synthesized_brief, Mapping):
        raise ContractValidationError("normalized facts and synthesized brief must be mappings")
    build_decision_workspace((analysis,))  # Reapply the validated-analysis boundary.
    bid = synthesized_brief.get("bid") or {}
    source_brief = synthesized_brief.get("brief") or {}
    if not isinstance(bid, Mapping) or not isinstance(source_brief, Mapping):
        raise ContractValidationError("synthesized bid and brief must be mappings")
    canonical_evidence = tuple(link for link in analysis.evidence_used
                               if link.entity_type == SupportedEntityType.CANONICAL_FACT)
    if not canonical_evidence:
        raise ContractValidationError("analysis must declare canonical evidence")

    snapshot_fields = (
        ("Opportunity", bid.get("title")), ("Buyer", bid.get("client")),
        ("Reference", bid.get("file_number")), ("Opportunity type", source_brief.get("opportunity_type")),
        ("Purpose", source_brief.get("executive_summary")), ("Contract term", source_brief.get("contract_term")),
        ("Procurement model", source_brief.get("procurement_model")),
        ("Clarification deadline", bid.get("clarification_deadline")),
        ("Submission deadline", bid.get("submission_deadline")),
    )
    snapshot = tuple(BriefFact(label, str(value), canonical_evidence) for label, value in snapshot_fields if _text(value))
    structure = tuple(BriefFact("Capability area", str(value), canonical_evidence)
                      for value in source_brief.get("scope_categories", []) or [] if _text(value))

    observations = tuple(BriefObservation(
        item.statement.statement_id, item.statement.statement, item.statement.evidence_support)
        for item in analysis.inferences)
    questions = tuple(BriefQuestion(item.question_id, item.question, item.related_analysis_ids)
                      for item in analysis.unanswered_questions)

    requirements = normalized_facts.get("requirements", []) or []
    if not isinstance(requirements, list) or any(not isinstance(item, Mapping) for item in requirements):
        raise ContractValidationError("requirements must contain mappings")
    needs = {
        "CVs and personnel credentials": ("cv", "résumé", "resume", "personnel", "credential"),
        "Case studies and project references": ("case stud", "reference", "experience"),
        "Resource availability": ("availability", "capacity", "resource"),
        "Commercial assumptions and pricing inputs": ("price", "pricing", "rate", "fee", "commercial"),
        "Delivery model and methodology": ("method", "approach", "delivery model", "work plan"),
    }
    required = []
    for label, terms in needs.items():
        matches = [(index, item) for index, item in enumerate(requirements)
                   if any(term in str(item.get("description") or item.get("requirement") or "").casefold()
                          for term in terms)]
        if matches:
            links = tuple(_link(SupportedEntityType.REQUIREMENT,
                                _entity_id("requirements", item, index), item)
                          for index, item in matches)
            required.append(BriefObservation("brief-team-" + sha256(label.encode()).hexdigest(), label, links))

    conflicts = normalized_facts.get("conflicts", []) if conflicts is None else conflicts
    conflicts = list(conflicts or [])
    if any(not isinstance(item, Mapping) for item in conflicts):
        raise ContractValidationError("conflicts must contain mappings")
    candidates = tuple(ClarificationCandidate(
        _entity_id("conflicts", item, index),
        _text(item.get("topic")) or _text(item.get("conflict_type")) or "Unresolved source conflict",
        _text(item.get("reason")) or "The authoritative record contains unresolved or ambiguous information.",
        (_link(SupportedEntityType.FUTURE_ENTITY, _entity_id("conflicts", item, index), item),),
    ) for index, item in enumerate(conflicts))

    unknowns = analysis.unknowns
    known_unknowns = KnownUnknowns(
        tuple(sorted(unknowns.missing_evidence)),
        tuple(sorted(set((*unknowns.unresolved_conflict_ids,
                          *(_entity_id("conflicts", item, i) for i, item in enumerate(conflicts)))))),
        tuple(sorted((*unknowns.unavailable_datasets, *unknowns.unavailable_history))),
        tuple(sorted(unknowns.ambiguous_observation_ids)),
    )
    identity = json.dumps({"analysis": analysis.analysis_id, "snapshot": snapshot_fields,
                           "structure": source_brief.get("scope_categories", []),
                           "conflicts": conflicts}, sort_keys=True, separators=(",", ":"), default=str)
    result = ExecutiveOpportunityBrief(
        "executive-brief-" + sha256(identity.encode()).hexdigest(), BRIEF_VERSION,
        analysis.analysis_id, snapshot, structure, observations, questions,
        tuple(required), candidates, known_unknowns, tuple(analysis.limitations),
    )
    declared = set(analysis.evidence_used)
    analysis_links = {link for item in observations for link in item.evidence}
    if not analysis_links.issubset(declared):
        raise ContractValidationError("brief observation references unknown analysis evidence")
    return result


def render_executive_opportunity_brief(brief: ExecutiveOpportunityBrief) -> str:
    if not isinstance(brief, ExecutiveOpportunityBrief):
        raise ContractValidationError("brief must be an ExecutiveOpportunityBrief")
    lines = ["# Executive Opportunity Brief", "", "## Executive Opportunity Snapshot"]
    lines += [f"- **{item.label}:** {item.value}" for item in brief.executive_snapshot]
    sections = (
        ("Opportunity Structure", (item.value for item in brief.opportunity_structure)),
        ("Key Observations", (item.text for item in brief.key_observations)),
        ("Management Questions", (item.text for item in brief.management_questions)),
        ("Information Required From Our Team", (item.text for item in brief.information_required_from_team)),
        ("Clarification Candidates", (f"{item.subject}: {item.reason}" for item in brief.clarification_candidates)),
    )
    for title, values in sections:
        lines += ["", f"## {title}"]
        material = tuple(values)
        lines += [f"- {value}" for value in material] or ["- None identified from the available evidence."]
    lines += ["", "## Known Unknowns"]
    for label, values in (("Missing evidence", brief.known_unknowns.missing_evidence),
                          ("Unresolved conflicts", brief.known_unknowns.unresolved_conflicts),
                          ("Unavailable information", brief.known_unknowns.unavailable_information),
                          ("Ambiguity", brief.known_unknowns.ambiguity)):
        lines.append(f"- **{label}:** " + (", ".join(values) if values else "None identified."))
    lines += ["", "## Limitations"] + [f"- {value}" for value in brief.limitations]
    return "\n".join(lines) + "\n"
