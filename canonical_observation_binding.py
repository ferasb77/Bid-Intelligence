"""Fail-closed derivation of Canonical Opportunity observation bindings.

This adapter adds no procurement meaning and invents no evidence or
provenance. It matches each canonical observation's already-validated
source_refs to the exact EvidenceOccurrence and, where an excerpt is
present, EvidenceExtract objects that Evidence acquisition derived from the
identical source-marker coordinates for the same corpus -- or, failing an
exact locator match, to a coarser real occurrence whose extract
independently, unambiguously proves the excerpt verbatim (see
evidence_grounding.match_refs' "Model 2 / hierarchical" fallback). A
binding is produced only when every one of an observation's refs resolves
to exactly one occurrence (and, when an excerpt is present, exactly one
extract whose content contains that excerpt verbatim).

An observation whose Canonical Opportunity provenance_status is VERIFIED
must achieve this closure; failure to do so raises ObservationBindingError,
since that would contradict an already-established fact. An observation
already declared PARTIAL or UNVERIFIED by Canonical Opportunity's own,
independent provenance check is permitted to publish with an explicit,
empty evidence/provenance binding when this adapter also cannot establish
closure -- the absence is published honestly, matching the observation's
own already-visible provenance_status, rather than blocking publication of
every other, fully-grounded observation over one already-declared weak one.
Nothing is ever omitted, approximated, or guessed to construct a binding
that fails to prove itself.

The actual locator/excerpt matching algorithm is shared with
opportunity_structure_binding.py via evidence_grounding.py -- see that
module's docstring for why the duplication this file used to carry was
itself a demonstrated defect source.
"""
from __future__ import annotations

from typing import Mapping

from canonical_opportunity_publication import CanonicalObservationBinding
from evidence import EvidenceSnapshot
from evidence_publication import EvidencePublication
from evidence_grounding import build_locator_index, match_refs


class ObservationBindingError(ValueError):
    """The canonical observation ledger cannot be bound to Evidence without inventing provenance."""


def _fail(observation_id: str, reason: str):
    raise ObservationBindingError(f"{observation_id}: {reason}")


def build_observation_bindings(
        canonical: Mapping, evidence_snapshot: EvidenceSnapshot,
        evidence_publication: EvidencePublication,
        ) -> tuple[CanonicalObservationBinding, ...]:
    """Derive one CanonicalObservationBinding per canonical observation.

    canonical: the real, live _canonical_opportunity mapping (Stage B/C output).
    evidence_snapshot: the real EvidenceSnapshot built by
        procurement_evidence_adapter.adapt_procurement_corpus for the SAME corpus.
    evidence_publication: the real, validated EvidencePublication published
        from that exact evidence_snapshot.
    """
    if evidence_publication.source_snapshot_digest != evidence_snapshot.snapshot_digest:
        raise ObservationBindingError(
            "Evidence publication does not attest the supplied Evidence snapshot "
            "(source_snapshot_digest mismatch); refusing to derive bindings against "
            "an unrelated or stale publication.")

    try:
        index = build_locator_index(evidence_snapshot)
    except ValueError as exc:
        raise ObservationBindingError(str(exc)) from exc

    ref_by_object_id = {}
    for governed_object, reference in zip(evidence_publication.snapshot.objects, evidence_publication.references):
        if governed_object.object_id in ref_by_object_id:
            raise ObservationBindingError(
                f"Evidence publication declares duplicate object_id {governed_object.object_id!r}")
        ref_by_object_id[governed_object.object_id] = reference

    def resolve_references(observation_id: str, object_ids: set[str]):
        out = []
        for object_id in object_ids:
            reference = ref_by_object_id.get(object_id)
            if reference is None:
                _fail(observation_id, f"publication reference could not be resolved for {object_id}")
            out.append(reference)
        return tuple(sorted(out, key=lambda item: item.identity_key))

    observations = canonical.get("observations") or []
    bindings = []
    for observation in observations:
        oid = observation["observation_id"]
        refs = observation.get("source_refs") or []
        extraction_occurrences = observation.get("extraction_occurrences") or []
        has_source = bool(refs or extraction_occurrences)

        if not has_source:
            bindings.append(CanonicalObservationBinding(oid, (), ()))
            continue

        try:
            if not refs:
                _fail(oid, "observation has extraction_occurrences but no source_refs to derive real provenance from")
            matched_extract_ids, matched_occurrence_ids = match_refs(oid, refs, index, _fail)
            evidence_references = resolve_references(oid, matched_extract_ids)
            provenance_references = resolve_references(oid, matched_occurrence_ids)
        except ObservationBindingError:
            if observation.get("provenance_status") not in ("PARTIAL", "UNVERIFIED"):
                # Canonical Opportunity's own independent check declared this
                # observation VERIFIED, or provenance_status is missing or
                # unrecognized. Either way there is no explicit, already-
                # governed declaration of weak provenance to fall back to --
                # silence is not a governed absence. Preserve the strict
                # failure; a binding failure here is a genuine anomaly.
                raise
            # Canonical Opportunity already declared this observation's
            # provenance PARTIAL or UNVERIFIED. This adapter's inability to
            # demonstrate full evidence/provenance closure is consistent with
            # that declaration, not a new fact. Publish an explicit, honest
            # absence of evidence and provenance relationships rather than
            # inventing one or blocking the entire publication over an
            # already-declared, already-visible weak observation.
            evidence_references, provenance_references = (), ()

        bindings.append(CanonicalObservationBinding(oid, evidence_references, provenance_references))

    return tuple(sorted(bindings, key=lambda item: item.observation_id))


__all__ = ["ObservationBindingError", "build_observation_bindings"]
