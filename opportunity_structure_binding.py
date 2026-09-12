"""Fail-closed derivation of Opportunity Structure record bindings.

Mirrors ``canonical_observation_binding.py`` exactly, adapted from Canonical
Opportunity's observation shape to Opportunity Structure's record shape --
both now share the identical matching algorithm via evidence_grounding.py,
rather than carrying independently-evolving copies of it. This adapter adds
no procurement meaning and invents no evidence or provenance. It matches
each structure record's already-validated source_refs to the exact
EvidenceOccurrence and, where an excerpt is present, EvidenceExtract
objects that Evidence acquisition derived from the identical source-marker
coordinates for the same corpus -- or, failing an exact locator match, to a
coarser real occurrence whose extract independently, unambiguously proves
the excerpt verbatim (see evidence_grounding.match_refs' "Model 2 /
hierarchical" fallback). A binding is produced only when every one of a
record's refs resolves to exactly one occurrence (and, when an excerpt is
present, exactly one extract whose content contains that excerpt
verbatim).

A record whose Opportunity Structure provenance_status is VERIFIED must
achieve this closure; failure to do so raises StructureBindingError, since
that would contradict an already-established fact. A record already
declared PARTIAL or UNVERIFIED by Opportunity Structure's own, independent
provenance check is permitted to publish with an explicit, empty
evidence/provenance binding when this adapter also cannot establish
closure -- the absence is published honestly, matching the record's own
already-visible provenance_status, rather than blocking publication of
every other, fully-grounded record over one already-declared weak one.
Nothing is ever omitted, approximated, or guessed to construct a binding
that fails to prove itself.
"""
from __future__ import annotations

from typing import Mapping

from evidence import EvidenceSnapshot
from evidence_publication import EvidencePublication
from evidence_grounding import build_locator_index, match_refs
from opportunity_structure_publication import OpportunityStructureRecordBinding


class StructureBindingError(ValueError):
    """The opportunity structure ledger cannot be bound to Evidence without inventing provenance."""


def _fail(record_id: str, reason: str):
    raise StructureBindingError(f"{record_id}: {reason}")


def build_structure_bindings(
        structure: Mapping, evidence_snapshot: EvidenceSnapshot,
        evidence_publication: EvidencePublication,
        ) -> tuple[OpportunityStructureRecordBinding, ...]:
    """Derive one OpportunityStructureRecordBinding per structure record.

    structure: the real, live opportunity_structure ledger mapping (Stage
        B/C's requirements/evaluation_criteria/commercial_clauses/
        deliverables/submission_rules sections, reconciled by
        opportunity_structure.build_opportunity_structure).
    evidence_snapshot: the real EvidenceSnapshot built by
        procurement_evidence_adapter.adapt_procurement_corpus for the SAME corpus.
    evidence_publication: the real, validated EvidencePublication published
        from that exact evidence_snapshot.
    """
    if evidence_publication.source_snapshot_digest != evidence_snapshot.snapshot_digest:
        raise StructureBindingError(
            "Evidence publication does not attest the supplied Evidence snapshot "
            "(source_snapshot_digest mismatch); refusing to derive bindings against "
            "an unrelated or stale publication.")

    try:
        index = build_locator_index(evidence_snapshot)
    except ValueError as exc:
        raise StructureBindingError(str(exc)) from exc

    ref_by_object_id = {}
    for governed_object, reference in zip(evidence_publication.snapshot.objects, evidence_publication.references):
        if governed_object.object_id in ref_by_object_id:
            raise StructureBindingError(
                f"Evidence publication declares duplicate object_id {governed_object.object_id!r}")
        ref_by_object_id[governed_object.object_id] = reference

    def resolve_references(record_id: str, object_ids: set[str]):
        out = []
        for object_id in object_ids:
            reference = ref_by_object_id.get(object_id)
            if reference is None:
                _fail(record_id, f"publication reference could not be resolved for {object_id}")
            out.append(reference)
        return tuple(sorted(out, key=lambda item: item.identity_key))

    records = structure.get("records") or []
    bindings = []
    for record in records:
        record_id = record["record_id"]
        refs = record.get("source_refs") or []
        has_source = bool(refs)

        if not has_source:
            bindings.append(OpportunityStructureRecordBinding(record_id, (), ()))
            continue

        try:
            matched_extract_ids, matched_occurrence_ids = match_refs(record_id, refs, index, _fail)
            evidence_references = resolve_references(record_id, matched_extract_ids)
            provenance_references = resolve_references(record_id, matched_occurrence_ids)
        except StructureBindingError:
            if record.get("provenance_status") not in ("PARTIAL", "UNVERIFIED"):
                # Opportunity Structure's own independent check declared
                # this record VERIFIED, or provenance_status is missing or
                # unrecognized. Either way there is no explicit, already-
                # governed declaration of weak provenance to fall back to --
                # silence is not a governed absence. Preserve the strict
                # failure; a binding failure here is a genuine anomaly.
                raise
            # Opportunity Structure already declared this record's
            # provenance PARTIAL or UNVERIFIED. This adapter's inability to
            # demonstrate full evidence/provenance closure is consistent
            # with that declaration, not a new fact. Publish an explicit,
            # honest absence of evidence and provenance relationships
            # rather than inventing one or blocking the entire publication
            # over an already-declared, already-visible weak record.
            evidence_references, provenance_references = (), ()

        bindings.append(OpportunityStructureRecordBinding(record_id, evidence_references, provenance_references))

    return tuple(sorted(bindings, key=lambda item: item.record_id))


__all__ = ["StructureBindingError", "build_structure_bindings"]
