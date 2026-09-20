"""Deterministic presentation adapter over Executive Opportunity Understanding."""
from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from enum import Enum
from hashlib import sha256
import json

from decision_intelligence import ContractValidationError
from executive_opportunity_understanding import (
    CONTRACT_VERSION as UNDERSTANDING_CONTRACT_VERSION,
    CoverageDisposition, CoverageRecord, ExecutiveOpportunityUnderstanding,
    ExecutiveSection, GovernedObjectReference, SECTION_ORDER,
    validate_executive_opportunity_understanding,
)
from governed_reference_resolution import (
    GovernedResolutionError, ResolutionRequest, ResolutionResult, SemanticValue,
    SemanticValueKind, resolve_governed_reference,
)

BRIEF_VERSION = "executive-opportunity-brief/2.0.0"
PRESENTATION_FORMAT_VERSION = "markdown/1.0.0"

_SECTION_HEADINGS = {
    ExecutiveSection.OPPORTUNITY_IDENTITY: "Opportunity Identity",
    ExecutiveSection.REQUESTED_WORK: "Requested Work",
    ExecutiveSection.EVALUATION_AND_SUCCESS_STRUCTURE: "Evaluation and Success Structure",
    ExecutiveSection.RESPONSE_AND_SUBMISSION_STRUCTURE: "Response and Submission Structure",
    ExecutiveSection.TIMELINE: "Timeline",
    ExecutiveSection.DELIVERY_STRUCTURE: "Delivery Structure",
    ExecutiveSection.COMMERCIAL_AND_CONTRACT_STRUCTURE: "Commercial and Contract Structure",
    ExecutiveSection.MEASURED_CHARACTERISTICS: "Measured Characteristics",
    ExecutiveSection.ANALYST_FINDINGS: "Analyst Findings",
    ExecutiveSection.ASSUMPTIONS_AND_ALTERNATIVES: "Assumptions and Alternatives",
    ExecutiveSection.CONFLICTS_UNKNOWNS_AND_EVIDENCE_GAPS: "Conflicts, Unknowns, and Evidence Gaps",
    ExecutiveSection.MANAGEMENT_DELIBERATION: "Management Deliberation",
    ExecutiveSection.LIMITATIONS_AND_COVERAGE: "Limitations and Coverage",
}


def _canonical(value):
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {item.name: _canonical(getattr(value, item.name)) for item in fields(value)
                if item.metadata.get("semantic", True)}
    if isinstance(value, tuple):
        return [_canonical(item) for item in value]
    if isinstance(value, dict):
        return {key: _canonical(value[key]) for key in sorted(value)}
    return value


def _json(value) -> str:
    return json.dumps(_canonical(value), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


@dataclass(frozen=True, slots=True)
class BriefSection:
    section: ExecutiveSection
    heading: str
    object_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.section, ExecutiveSection):
            raise ContractValidationError("brief section is invalid")
        if self.heading != _SECTION_HEADINGS[self.section]:
            raise ContractValidationError("brief section heading is not the fixed presentation label")
        if (not isinstance(self.object_ids, tuple)
                or any(not isinstance(value, str) or not value for value in self.object_ids)
                or len(self.object_ids) != len(set(self.object_ids))):
            raise ContractValidationError("brief section object IDs are invalid")


@dataclass(frozen=True, slots=True)
class ExecutiveOpportunityBrief:
    """Immutable presentation plan; semantic values remain in their owner domains."""
    brief_id: str
    brief_version: str
    presentation_format_version: str
    understanding_id: str
    understanding_digest: str
    publication_id: str
    publication_snapshot_id: str
    publication_snapshot_digest: str
    sections: tuple[BriefSection, ...]
    detail_register: tuple[GovernedObjectReference, ...]
    coverage_ledger: tuple[CoverageRecord, ...]
    understanding: ExecutiveOpportunityUnderstanding = field(
        compare=False, repr=False, metadata={"semantic": False})

    def __post_init__(self) -> None:
        validate_executive_opportunity_brief(self)

    def to_dict(self) -> dict:
        return _canonical(self)

    def to_json(self) -> str:
        return _json(self)


def _presentation_identity(understanding: ExecutiveOpportunityUnderstanding) -> str:
    payload = {
        "brief_version": BRIEF_VERSION,
        "presentation_format_version": PRESENTATION_FORMAT_VERSION,
        "understanding_id": understanding.understanding_id,
        "understanding_digest": understanding.digest,
    }
    return "executive-brief-" + sha256(_json(payload).encode("utf-8")).hexdigest()


def _resolve(reference: GovernedObjectReference,
             understanding: ExecutiveOpportunityUnderstanding) -> ResolutionResult:
    request = ResolutionRequest(
        reference.source_reference, understanding.context_id,
        understanding.context_digest, reference.authority_class, (),
        tuple(sorted({relationship.kind for relationship in reference.relationships},
                     key=lambda value: value.value)),
    )
    try:
        result = resolve_governed_reference(request, understanding.resolution_context)
    except GovernedResolutionError as exc:
        raise ContractValidationError(
            f"brief reference {reference.object_id} failed governed resolution: "
            f"{exc.code.value}") from exc
    if result.root.relationships != reference.relationships:
        raise ContractValidationError("brief reference relationship identity changed")
    return result


def _validate_and_resolve(
        brief: ExecutiveOpportunityBrief) -> tuple[ExecutiveOpportunityBrief, dict[str, ResolutionResult]]:
    """Shared body for validate/render: resolve every declared reference
    exactly once. Rendering previously called the public validate function
    (one resolution pass over `brief.detail_register`) and then resolved
    the same references again to build its own lookup table -- doubling
    the governed-resolution work with zero effect on the rendered bytes.
    Both callers below now run this single pass and reuse its result."""
    if not isinstance(brief, ExecutiveOpportunityBrief):
        raise ContractValidationError("ExecutiveOpportunityBrief is required")
    if brief.brief_version != BRIEF_VERSION:
        raise ContractValidationError("unsupported Executive Opportunity Brief version")
    if brief.presentation_format_version != PRESENTATION_FORMAT_VERSION:
        raise ContractValidationError("unsupported Executive Opportunity Brief format")
    if not isinstance(brief.understanding, ExecutiveOpportunityUnderstanding):
        raise ContractValidationError("brief requires ExecutiveOpportunityUnderstanding")
    understanding = validate_executive_opportunity_understanding(brief.understanding)
    if understanding.contract_version != UNDERSTANDING_CONTRACT_VERSION:
        raise ContractValidationError("unsupported Executive Opportunity Understanding version")
    if (brief.understanding_id, brief.understanding_digest) != (
            understanding.understanding_id, understanding.digest):
        raise ContractValidationError("brief understanding binding is inconsistent")
    if (brief.publication_id, brief.publication_snapshot_id,
            brief.publication_snapshot_digest) != (
            understanding.publication_id, understanding.publication_snapshot_id,
            understanding.publication_snapshot_digest):
        raise ContractValidationError("brief publication binding is inconsistent")
    expected_sections = tuple(BriefSection(item.section, _SECTION_HEADINGS[item.section],
                                           item.object_ids)
                              for item in understanding.executive_index)
    if brief.sections != expected_sections or tuple(
            item.section for item in brief.sections) != SECTION_ORDER:
        raise ContractValidationError("brief section order differs from the executive index")
    if brief.detail_register != understanding.detail_register.references():
        raise ContractValidationError("brief detail order differs from the understanding")
    if brief.coverage_ledger != understanding.coverage_ledger:
        raise ContractValidationError("brief coverage differs from the understanding")
    if brief.brief_id != _presentation_identity(understanding):
        raise ContractValidationError("brief presentation identity is invalid")
    resolved = {reference.object_id: _resolve(reference, understanding)
               for reference in brief.detail_register}
    return brief, resolved


def validate_executive_opportunity_brief(
        brief: ExecutiveOpportunityBrief) -> ExecutiveOpportunityBrief:
    return _validate_and_resolve(brief)[0]


def build_executive_opportunity_brief(
        understanding: ExecutiveOpportunityUnderstanding) -> ExecutiveOpportunityBrief:
    """Create a presentation plan from one validated governed understanding."""
    if not isinstance(understanding, ExecutiveOpportunityUnderstanding):
        raise ContractValidationError(
            "source must be a validated ExecutiveOpportunityUnderstanding")
    validate_executive_opportunity_understanding(understanding)
    sections = tuple(BriefSection(item.section, _SECTION_HEADINGS[item.section],
                                  item.object_ids)
                     for item in understanding.executive_index)
    return ExecutiveOpportunityBrief(
        _presentation_identity(understanding), BRIEF_VERSION,
        PRESENTATION_FORMAT_VERSION, understanding.understanding_id,
        understanding.digest, understanding.publication_id,
        understanding.publication_snapshot_id,
        understanding.publication_snapshot_digest, sections,
        understanding.detail_register.references(), understanding.coverage_ledger,
        understanding,
    )


def _semantic_text(value: SemanticValue) -> str:
    if value.kind == SemanticValueKind.NULL:
        return "null"
    if value.kind == SemanticValueKind.BOOLEAN:
        return "true" if value.scalar else "false"
    if value.kind in {
            SemanticValueKind.STRING, SemanticValueKind.INTEGER,
            SemanticValueKind.DECIMAL, SemanticValueKind.DATE,
            SemanticValueKind.DATETIME, SemanticValueKind.IDENTIFIER,
            SemanticValueKind.ENUM}:
        return str(value.scalar)
    if value.kind == SemanticValueKind.ARRAY:
        return "[" + "; ".join(_semantic_text(item) for item in value.items) + "]"
    return "{" + "; ".join(
        f"{item.name}: {_semantic_text(item.value)}" for item in value.fields) + "}"


def _render_reference(reference: GovernedObjectReference,
                      resolved: ResolutionResult,
                      detail_register_by_id: dict) -> list[str]:
    root = resolved.root
    lines = [
        f"- **{root.object_class} · {root.object_id}**",
        f"  - Owner: `{root.owner_domain}/{root.owner_contract}`",
        f"  - Contract version: `{root.contract_version}`",
        f"  - Snapshot: `{reference.source_reference.snapshot_id}`",
        f"  - Snapshot digest: `{reference.source_reference.snapshot_digest}`",
        f"  - Object digest: `{root.object_digest}`",
        f"  - Authority: `{root.authority.value}`",
        f"  - Detail: `{reference.detail_pointer}`",
    ]
    lines.extend(f"  - {item.name}: {_semantic_text(item.value)}"
                 for item in root.semantic_fields)
    lines.append("  - Relationships:")
    if not resolved.relationships:
        lines.append("    - None declared.")
    else:
        for item in resolved.relationships:
            target = item.target
            target_entry = detail_register_by_id.get(target.object_id)
            if target_entry is not None and target_entry.object_class == target.object_class:
                # This target's full identity (owner/contract/version/
                # snapshot/digests) is separately rendered in full
                # elsewhere in THIS SAME document, at target_entry's own
                # detail_pointer. That rendering is guaranteed byte-
                # identical to inlining it here again: this brief is
                # scoped to exactly one publication snapshot (see
                # validate_executive_opportunity_understanding's
                # publication-snapshot completeness check), and
                # governed_reference_resolution.resolve_governed_reference
                # resolves every relationship target from that same
                # snapshot's object graph the detail register itself is
                # built from -- never a different snapshot of the "same"
                # object. Pointing to it instead of re-embedding the full
                # identity here preserves full traceability with no
                # information loss (see
                # tests/test_executive_opportunity_brief.py's compaction-
                # equivalence tests).
                lines.append(
                    f"    - `{item.kind.value}` / `{item.role}` / {item.ordinal}: "
                    f"see `{target_entry.detail_pointer}` for full identity "
                    f"(same snapshot, same digests).")
            else:
                lines.append(
                    f"    - `{item.kind.value}` / `{item.role}` / {item.ordinal}: "
                    f"`{target.owner_domain}/{target.owner_contract}/"
                    f"{target.contract_version}/{target.object_class}/{target.object_id}` "
                    f"(snapshot `{target.snapshot_id}`, snapshot digest "
                    f"`{target.snapshot_digest}`, object digest `{target.object_digest}`)")
    return lines


def render_executive_opportunity_brief(brief: ExecutiveOpportunityBrief) -> str:
    """Resolve owner-declared values and render the immutable presentation plan."""
    brief, resolved = _validate_and_resolve(brief)
    reference_by_id = {item.object_id: item for item in brief.detail_register}
    rendered_ids: set[str] = set()
    lines = ["# Executive Opportunity Brief", "",
             f"Understanding: `{brief.understanding_id}`",
             f"Publication: `{brief.publication_id}`",
             f"Publication snapshot: `{brief.publication_snapshot_id}`"]
    for section in brief.sections:
        lines.extend(("", f"## {section.heading}"))
        if not section.object_ids:
            lines.append("- No indexed objects.")
            continue
        for object_id in section.object_ids:
            reference = reference_by_id[object_id]
            if object_id in rendered_ids:
                lines.append(f"- `{object_id}` — see `{reference.detail_pointer}`.")
                continue
            lines.extend(_render_reference(reference, resolved[object_id], reference_by_id))
            rendered_ids.add(object_id)

    detail_only = tuple(item for item in brief.detail_register
                        if item.object_id not in rendered_ids)
    lines.extend(("", "## Complete Detail Register"))
    for reference in detail_only:
        lines.extend(_render_reference(reference, resolved[reference.object_id], reference_by_id))
        rendered_ids.add(reference.object_id)
    if not detail_only:
        lines.append("- All detail objects are displayed in the executive index.")

    lines.extend(("", "## Coverage Ledger"))
    for item in brief.coverage_ledger:
        sections = ", ".join(section.value for section in item.section_keys) or "DETAIL_ONLY"
        suffix = (f"; reason: {item.ineligibility_reason}"
                  if item.disposition == CoverageDisposition.INELIGIBLE else "")
        lines.append(
            f"- `{item.object_class}/{item.object_id}`: `{item.disposition.value}`; "
            f"rule `{item.rule_id}`; sections `{sections}`; detail "
            f"`{item.detail_pointer}`{suffix}")
    return "\n".join(lines) + "\n"


__all__ = [
    "BRIEF_VERSION", "PRESENTATION_FORMAT_VERSION", "BriefSection",
    "ExecutiveOpportunityBrief", "build_executive_opportunity_brief",
    "render_executive_opportunity_brief", "validate_executive_opportunity_brief",
]
