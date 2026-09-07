"""A deterministic, evidence-linked briefing for proposal-team kickoff."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Mapping

from decision_analyst import DecisionAnalysis
from decision_intelligence import ContractValidationError, EvidenceSupport, SupportedEntityType
from decision_workspace import build_decision_workspace

BRIEF_VERSION = "executive-opportunity-brief/2"


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
class FunctionalPreparation:
    owner: str
    items: tuple[BriefObservation, ...]


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
    opportunity_at_a_glance: tuple[BriefFact, ...]
    engagement_workstreams: tuple[BriefFact, ...]
    opportunity_characteristics: tuple[BriefFact, ...]
    opportunity_timeline: tuple[BriefFact, ...]
    executive_attention_areas: tuple[BriefObservation, ...]
    preparation_by_owner: tuple[FunctionalPreparation, ...]
    kickoff_questions: tuple[BriefQuestion, ...]
    clarification_candidates: tuple[ClarificationCandidate, ...]
    known_unknowns: KnownUnknowns
    limitations: tuple[str, ...]

    def __post_init__(self):
        if self.brief_version != BRIEF_VERSION:
            raise ContractValidationError("unsupported Executive Opportunity Brief version")
        observations = (*self.executive_attention_areas,
                        *(item for group in self.preparation_by_owner for item in group.items))
        ids = [item.observation_id for item in observations]
        ids += [item.question_id for item in self.kickoff_questions]
        ids += [item.candidate_id for item in self.clarification_candidates]
        if len(ids) != len(set(ids)):
            raise ContractValidationError("brief item IDs must be unique")
        facts = (*self.opportunity_at_a_glance, *self.engagement_workstreams,
                 *self.opportunity_characteristics, *self.opportunity_timeline)
        if any(not item.evidence for item in (*facts, *observations)):
            raise ContractValidationError("brief facts and observations require evidence")


def _text(value):
    value = None if value is None else str(value).strip()
    return value or None


def _record_id(section, item, index):
    keys = {"requirements": ("requirement_id", "req_id"), "conflicts": ("conflict_id",)}.get(section, ())
    for key in keys:
        if _text(item.get(key)):
            return str(item[key])
    raw = json.dumps(item, sort_keys=True, separators=(",", ":"), default=str)
    return f"brief-{section}-" + sha256(f"{index}:{raw}".encode()).hexdigest()


def _evidence_ids(item):
    ids = {str(item["evidence_id"])} if _text(item.get("evidence_id")) else set()
    ids.update(str(ref["evidence_id"]) for ref in item.get("source_refs", []) or []
               if isinstance(ref, Mapping) and _text(ref.get("evidence_id")))
    return tuple(sorted(ids))


def _metric_map(analysis):
    result = {}
    for fact in analysis.computed_facts:
        if fact.statement_id.startswith("oi-computed-") and "=" in fact.statement:
            result[fact.statement_id.removeprefix("oi-computed-")] = (fact.statement.split("=", 1)[1], fact.evidence_support)
    return result


def build_executive_opportunity_brief(normalized_facts: Mapping, synthesized_brief: Mapping,
                                      analysis: DecisionAnalysis, *, conflicts=None):
    if not isinstance(normalized_facts, Mapping) or not isinstance(synthesized_brief, Mapping):
        raise ContractValidationError("normalized facts and synthesized brief must be mappings")
    build_decision_workspace((analysis,))
    bid, source = synthesized_brief.get("bid") or {}, synthesized_brief.get("brief") or {}
    if not isinstance(bid, Mapping) or not isinstance(source, Mapping):
        raise ContractValidationError("synthesized bid and brief must be mappings")
    canonical = tuple(x for x in analysis.evidence_used if x.entity_type == SupportedEntityType.CANONICAL_FACT)
    if not canonical:
        raise ContractValidationError("analysis must declare canonical evidence")

    glance_values = (("Opportunity", bid.get("title")), ("Buyer", bid.get("client")),
                     ("Reference", bid.get("file_number")), ("Purpose", source.get("executive_summary")),
                     ("Contract term", source.get("contract_term")), ("Procurement model", source.get("procurement_model")))
    glance = tuple(BriefFact(k, str(v), canonical) for k, v in glance_values if _text(v))
    workstreams = tuple(BriefFact("Workstream", str(v), canonical)
                        for v in source.get("scope_categories", []) or [] if _text(v))
    timeline_values = (("Clarification deadline", bid.get("clarification_deadline")),
                       ("Submission deadline", bid.get("submission_deadline")))
    timeline = tuple(BriefFact(k, str(v), canonical) for k, v in timeline_values if _text(v))

    metrics = _metric_map(analysis)
    characteristic_labels = (
        ("total_requirements", "Documented requirements"),
        ("weighted_criteria", "Weighted evaluation criteria"),
        ("threshold_count", "Evaluation thresholds"),
        ("submission_artifact_count", "Submission artifacts"),
        ("submission_pathway_count", "Submission pathways"),
        ("deliverable_count", "Documented deliverables"),
    )
    characteristics = tuple(BriefFact(label, metrics[key][0], metrics[key][1])
                            for key, label in characteristic_labels if key in metrics)
    attention = []
    for finding in analysis.inferences:
        wording = finding.statement.statement
        if finding.statement.statement_id == "oi-inference-proposal-effort":
            requirement_count = metrics.get("total_requirements", ("an extensive set of", ()))[0]
            artifact_count = metrics.get("submission_artifact_count", ("multiple", ()))[0]
            wording = (f"The response will require coordinated preparation across {requirement_count} "
                       f"documented requirements and {artifact_count} submission artifacts.")
        attention.append(BriefObservation(finding.statement.statement_id, wording,
                                          finding.statement.evidence_support))
    attention = tuple(attention)

    requirements = normalized_facts.get("requirements", []) or []
    if not isinstance(requirements, list) or any(not isinstance(x, Mapping) for x in requirements):
        raise ContractValidationError("requirements must contain mappings")
    ownership = (
        ("Bid Team", ("case stud", "reference", "submission", "form")),
        ("Commercial", ("price", "pricing", "rate", "fee", "commercial")),
        ("Subject Matter Experts", ("method", "approach", "delivery model", "work plan")),
        ("People / HR", ("cv", "résumé", "resume", "personnel", "credential", "availability")),
        ("Legal", ("contract", "agreement", "liability", "insurance", "intellectual property")),
        ("Operations", ("resource", "schedule", "location", "technology", "security")),
    )
    owner_language = {
        "Bid Team": "Assemble and validate the required forms, case studies, project references, and submission material.",
        "Commercial": "Prepare category pricing, rate information, commercial assumptions, exclusions, and cost dependencies.",
        "Subject Matter Experts": "Provide the delivery approach, methodology, relevant experience, and supporting examples.",
        "People / HR": "Confirm proposed personnel, credentials, roles, and availability.",
        "Legal": "Review agreement terms, declarations, liability, insurance, and intellectual-property obligations.",
        "Operations": "Confirm delivery resources, scheduling, locations, security, and operational dependencies.",
    }
    groups = []
    used = set()
    for owner, terms in ownership:
        items = []
        for index, req in enumerate(requirements):
            rid = _record_id("requirements", req, index)
            content = str(req.get("description") or req.get("requirement") or "")
            if rid not in used and any(term in content.casefold() for term in terms):
                link = EvidenceSupport(SupportedEntityType.REQUIREMENT, rid, _evidence_ids(req))
                items.append((rid, link))
                used.add(rid)
        if items:
            groups.append(FunctionalPreparation(owner, (BriefObservation(
                "brief-preparation-" + sha256(owner.encode()).hexdigest(), owner_language[owner],
                tuple(link for _, link in items)),)))

    conflict_values = normalized_facts.get("conflicts", []) if conflicts is None else conflicts
    conflict_values = list(conflict_values or [])
    if any(not isinstance(x, Mapping) for x in conflict_values):
        raise ContractValidationError("conflicts must contain mappings")
    candidates = tuple(ClarificationCandidate(
        _record_id("conflicts", item, i),
        _text(item.get("topic")) or _text(item.get("conflict_type")) or "Unresolved source wording",
        _text(item.get("reason")) or "The source record remains ambiguous or internally inconsistent.",
        (EvidenceSupport(SupportedEntityType.FUTURE_ENTITY, _record_id("conflicts", item, i), _evidence_ids(item)),))
        for i, item in enumerate(conflict_values))

    by_id = {_record_id("requirements", item, i): item for i, item in enumerate(requirements)}
    missing_records = [by_id[x] for x in analysis.unknowns.missing_evidence if x in by_id]
    missing_themes = []
    for owner, terms in ownership:
        if any(any(term in str(item.get("description") or item.get("requirement") or "").casefold()
                   for term in terms) for item in missing_records):
            missing_themes.append(owner)
    missing = (() if not missing_records else
               (f"Team evidence remains outstanding for {len(missing_records)} documented "
                f"{'requirement' if len(missing_records) == 1 else 'requirements'}"
                + (f" across {', '.join(missing_themes)}." if missing_themes else "."),))
    unresolved = tuple(f"{x.subject}: {x.reason}" for x in candidates)
    unknowns = KnownUnknowns(missing, unresolved,
        tuple(sorted((*analysis.unknowns.unavailable_datasets, *analysis.unknowns.unavailable_history))),
        tuple(sorted("An authoritative observation remains ambiguous."
                     for _ in analysis.unknowns.ambiguous_observation_ids)))
    questions = tuple(BriefQuestion(
        x.question_id,
        "Which unresolved requirements, source conflicts, or missing inputs need an owner before proposal planning begins?",
        x.related_analysis_ids) for x in analysis.unanswered_questions)
    identity = json.dumps({"version": BRIEF_VERSION, "analysis": analysis.analysis_id, "glance": glance_values,
                           "workstreams": source.get("scope_categories", []), "conflicts": conflict_values},
                          sort_keys=True, separators=(",", ":"), default=str)
    return ExecutiveOpportunityBrief("executive-brief-" + sha256(identity.encode()).hexdigest(),
        BRIEF_VERSION, analysis.analysis_id, glance, workstreams, characteristics, timeline,
        attention, tuple(groups), questions, candidates, unknowns, tuple(analysis.limitations))


def render_executive_opportunity_brief(brief):
    if not isinstance(brief, ExecutiveOpportunityBrief):
        raise ContractValidationError("brief must be an ExecutiveOpportunityBrief")
    lines = ["# Executive Opportunity Brief"]
    fact_sections = (("Opportunity at a Glance", brief.opportunity_at_a_glance),
                     ("Engagement Workstreams", brief.engagement_workstreams),
                     ("Opportunity Characteristics", brief.opportunity_characteristics),
                     ("Opportunity Timeline", brief.opportunity_timeline))
    for title, items in fact_sections:
        lines += ["", f"## {title}"] + ([f"- **{x.label}:** {x.value}" for x in items] or ["- None stated in the available evidence."])
    lines += ["", "## Executive Attention Areas"] + ([f"- {x.text}" for x in brief.executive_attention_areas] or ["- None identified by the available analysis."])
    lines += ["", "## Preparation by Owner"]
    for group in brief.preparation_by_owner:
        lines += ["", f"### {group.owner}"] + [f"- {x.text}" for x in group.items]
    lines += ["", "## Kickoff Questions"] + ([f"- {x.text}" for x in brief.kickoff_questions] or ["- No management questions identified."])
    lines += ["", "## Clarification Candidates"] + ([f"- **{x.subject}:** {x.reason}" for x in brief.clarification_candidates] or ["- None identified."])
    lines += ["", "## Known Unknowns"]
    for label, values in (("Missing information or evidence", brief.known_unknowns.missing_evidence),
                          ("Unresolved source issues", brief.known_unknowns.unresolved_conflicts),
                          ("Unavailable information", brief.known_unknowns.unavailable_information),
                          ("Ambiguity", brief.known_unknowns.ambiguity)):
        lines.append(f"- **{label}:** " + ("; ".join(values) if values else "None identified."))
    lines += ["", "## Limitations"] + [f"- {x}" for x in brief.limitations]
    return "\n".join(lines) + "\n"
