"""Deterministic, fail-closed composition of independently governed brief
artifacts into one Executive Briefing Pack, per
EXECUTIVE_BRIEFING_PACK_ARCHITECTURE.md.

This module performs no retrieval, resolution, analysis, interpretation,
reasoning, summarization, or decision-making. It admits exactly the two
volumes the v1.0.0 pack contract requires -- one validated
ExecutiveOpportunityBrief and one validated BuyerBrief -- and binds them
into one immutable pack, preserving every member's identity, revision,
digest, evidence cutoff, references, provenance, coverage, and limitations
exactly as its own contract already established them. No brief content is
copied, rewritten, summarized, or regenerated; each member object is held
by reference, unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from datetime import date
from enum import Enum
from hashlib import sha256
import json
from typing import Any

from executive_opportunity_brief import BRIEF_VERSION as EOB_CONTRACT_VERSION, ExecutiveOpportunityBrief
from buyer_brief import BUYER_BRIEF_VERSION as BUYER_BRIEF_CONTRACT_VERSION, BuyerBrief

PACK_CONTRACT_NAME = "executive-briefing-pack"
PACK_CONTRACT_VERSION = "1.0.0"
PACK_EDITION = "two-volume-executive"

SLOT_EXECUTIVE_OPPORTUNITY_BRIEF = "executive_opportunity_brief"
SLOT_BUYER_BRIEF = "buyer_brief"
VOLUME_CLASS_EXECUTIVE_OPPORTUNITY_BRIEF = "EXECUTIVE_OPPORTUNITY_BRIEF"
VOLUME_CLASS_BUYER_BRIEF = "BUYER_BRIEF"
# Fixed contract-defined order (EXECUTIVE_BRIEFING_PACK_ARCHITECTURE.md §12).
REQUIRED_SLOTS = (SLOT_EXECUTIVE_OPPORTUNITY_BRIEF, SLOT_BUYER_BRIEF)


class PackFailureCode(str, Enum):
    MISSING_MEMBER = "MISSING_MEMBER"
    DUPLICATE_MEMBER = "DUPLICATE_MEMBER"
    UNSUPPORTED_MEMBER = "UNSUPPORTED_MEMBER"
    UNSUPPORTED_MEMBER_VERSION = "UNSUPPORTED_MEMBER_VERSION"
    UNSUPPORTED_PACK_VERSION = "UNSUPPORTED_PACK_VERSION"
    INVALID_MEMBER = "INVALID_MEMBER"
    DIGEST_MISMATCH = "DIGEST_MISMATCH"
    REVISION_MISMATCH = "REVISION_MISMATCH"
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
    EVIDENCE_CUTOFF_INCOMPATIBLE = "EVIDENCE_CUTOFF_INCOMPATIBLE"
    NON_DETERMINISTIC = "NON_DETERMINISTIC"
    INVALID_PACK = "INVALID_PACK"


class ExecutiveBriefingPackError(ValueError):
    """Controlled fail-closed Executive Briefing Pack composition failure."""

    def __init__(self, code: PackFailureCode, slot: str | None, message: str) -> None:
        self.code = code
        self.slot = slot
        super().__init__(f"[{slot or 'pack'}] {code.value}: {message}")


def _fail(code: PackFailureCode, slot: str | None, message: str):
    raise ExecutiveBriefingPackError(code, slot, message)


def _canonical(value):
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, date):
        return value.isoformat()
    if is_dataclass(value):
        return {item.name: _canonical(getattr(value, item.name)) for item in fields(value)
                if item.metadata.get("semantic", True)}
    if isinstance(value, tuple):
        return [_canonical(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _canonical(value[key]) for key in sorted(value)}
    return value


def _json(value) -> str:
    try:
        return json.dumps(_canonical(value), ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        _fail(PackFailureCode.INVALID_PACK, None, f"pack composition material is not serializable: {exc}")


def _sha(value) -> str:
    return sha256(_json(value).encode("utf-8")).hexdigest()


def _member_digest(brief) -> str:
    """The member's own deterministic content digest, computed from its own
    already-canonical serialization (`to_json`) -- never recomputed from
    scratch or reinterpreted; the pack trusts each member's own contract to
    have already produced deterministic, semantic-only serialization
    (`ExecutiveOpportunityBrief`/`BuyerBrief` both already exclude their own
    non-semantic fields from `to_json`).
    """
    return sha256(brief.to_json().encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class PackMember:
    """One membership-manifest entry. Holds only composition metadata --
    never a copy, summary, or reinterpretation of the member's own content.
    """
    slot: str
    volume_class: str
    contract_version: str
    artifact_id: str
    revision_id: str
    artifact_digest: str
    opportunity_id: str
    buyer_id: str | None
    evidence_cutoff: date | None
    evidence_cutoff_governed_absence: bool


@dataclass(frozen=True, slots=True)
class ExecutiveBriefingPackManifest:
    pack_contract_name: str
    pack_contract_version: str
    edition: str
    opportunity_id: str
    buyer_id: str
    members: tuple[PackMember, ...]
    manifest_digest: str


@dataclass(frozen=True, slots=True)
class ExecutiveBriefingPack:
    pack_id: str
    pack_revision_id: str
    pack_digest: str
    manifest: ExecutiveBriefingPackManifest
    executive_opportunity_brief: ExecutiveOpportunityBrief = field(
        compare=False, repr=False, metadata={"semantic": False})
    buyer_brief: BuyerBrief = field(compare=False, repr=False, metadata={"semantic": False})

    def __post_init__(self) -> None:
        validate_executive_briefing_pack(self)

    def to_dict(self) -> dict[str, Any]:
        return _canonical(self)

    def to_json(self) -> str:
        return _json(self)


def _build_member(slot: str, volume_class: str, contract_version: str, artifact_id: str,
                  revision_id: str, artifact_digest: str, opportunity_id: str,
                  buyer_id: str | None, evidence_cutoff: date | None,
                  evidence_cutoff_governed_absence: bool) -> PackMember:
    return PackMember(slot, volume_class, contract_version, artifact_id, revision_id,
                      artifact_digest, opportunity_id, buyer_id, evidence_cutoff,
                      evidence_cutoff_governed_absence)


def _validate_membership(members: tuple[PackMember, ...]) -> None:
    """Reject duplicate or undeclared membership before anything else is
    computed from it. Exercised on every real composition; also callable
    directly to test the invariant, since the strongly-typed two-argument
    public API cannot itself construct two members in the same slot.
    """
    slots = tuple(item.slot for item in members)
    if len(slots) != len(set(slots)):
        _fail(PackFailureCode.DUPLICATE_MEMBER, None, "duplicate volume slot in membership manifest")
    artifact_ids = tuple(item.artifact_id for item in members)
    if len(artifact_ids) != len(set(artifact_ids)):
        _fail(PackFailureCode.DUPLICATE_MEMBER, None, "duplicate artifact identity across members")
    if set(slots) != set(REQUIRED_SLOTS):
        missing = set(REQUIRED_SLOTS) - set(slots)
        extra = set(slots) - set(REQUIRED_SLOTS)
        if missing:
            _fail(PackFailureCode.MISSING_MEMBER, next(iter(missing)),
                  f"required volume slot is missing: {sorted(missing)}")
        _fail(PackFailureCode.UNSUPPORTED_MEMBER, next(iter(extra)),
              f"unsupported or undeclared volume slot: {sorted(extra)}")


def build_executive_briefing_pack(
        executive_opportunity_brief: ExecutiveOpportunityBrief, *,
        buyer_brief: BuyerBrief,
        ) -> ExecutiveBriefingPack:
    """Compose one immutable Executive Briefing Pack from two already
    validated, unchanged brief artifacts. Neither argument is copied,
    rewritten, or reinterpreted -- both are held by reference in the
    returned pack exactly as supplied.
    """
    if not isinstance(executive_opportunity_brief, ExecutiveOpportunityBrief):
        _fail(PackFailureCode.INVALID_MEMBER, SLOT_EXECUTIVE_OPPORTUNITY_BRIEF,
              "an ExecutiveOpportunityBrief is required")
    if executive_opportunity_brief.brief_version != EOB_CONTRACT_VERSION:
        _fail(PackFailureCode.UNSUPPORTED_MEMBER_VERSION, SLOT_EXECUTIVE_OPPORTUNITY_BRIEF,
              f"unsupported Executive Opportunity Brief version: {executive_opportunity_brief.brief_version!r}")
    if not isinstance(buyer_brief, BuyerBrief):
        _fail(PackFailureCode.INVALID_MEMBER, SLOT_BUYER_BRIEF, "a BuyerBrief is required")
    if buyer_brief.brief_version != BUYER_BRIEF_CONTRACT_VERSION:
        _fail(PackFailureCode.UNSUPPORTED_MEMBER_VERSION, SLOT_BUYER_BRIEF,
              f"unsupported Buyer Brief version: {buyer_brief.brief_version!r}")

    eob_opportunity_id = executive_opportunity_brief.understanding.opportunity_id
    if buyer_brief.opportunity_id != eob_opportunity_id:
        _fail(PackFailureCode.IDENTITY_MISMATCH, SLOT_BUYER_BRIEF,
              "Buyer Brief does not bind the same opportunity identity as the "
              "Executive Opportunity Brief")
    if not isinstance(buyer_brief.evidence_cutoff_date, date):
        _fail(PackFailureCode.EVIDENCE_CUTOFF_INCOMPATIBLE, SLOT_BUYER_BRIEF,
              "Buyer Brief evidence cutoff is missing or malformed")

    members = (
        _build_member(
            SLOT_EXECUTIVE_OPPORTUNITY_BRIEF, VOLUME_CLASS_EXECUTIVE_OPPORTUNITY_BRIEF,
            executive_opportunity_brief.brief_version, executive_opportunity_brief.brief_id,
            executive_opportunity_brief.brief_id, _member_digest(executive_opportunity_brief),
            eob_opportunity_id, None, None, True,
            # Executive Opportunity Brief's own contract has no evidence-cutoff
            # concept -- an explicit, contract-governed absence
            # (EXECUTIVE_BRIEFING_PACK_ARCHITECTURE.md §9), never invented.
        ),
        _build_member(
            SLOT_BUYER_BRIEF, VOLUME_CLASS_BUYER_BRIEF, buyer_brief.brief_version,
            buyer_brief.brief_id, buyer_brief.brief_id, _member_digest(buyer_brief),
            buyer_brief.opportunity_id, buyer_brief.buyer_id,
            buyer_brief.evidence_cutoff_date, False,
        ),
    )
    _validate_membership(members)

    manifest_without_digest = {
        "pack_contract_name": PACK_CONTRACT_NAME, "pack_contract_version": PACK_CONTRACT_VERSION,
        "edition": PACK_EDITION, "opportunity_id": eob_opportunity_id, "buyer_id": buyer_brief.buyer_id,
        "members": members,
    }
    manifest_digest = _sha(manifest_without_digest)
    manifest = ExecutiveBriefingPackManifest(
        PACK_CONTRACT_NAME, PACK_CONTRACT_VERSION, PACK_EDITION, eob_opportunity_id,
        buyer_brief.buyer_id, members, manifest_digest)

    pack_id = "pack-" + _sha({
        "pack_contract_name": PACK_CONTRACT_NAME, "pack_contract_major_version": PACK_CONTRACT_VERSION.split(".")[0],
        "opportunity_id": eob_opportunity_id, "buyer_id": buyer_brief.buyer_id, "edition": PACK_EDITION,
    })
    pack_revision_id = "pack-revision-" + _sha({
        "pack_id": pack_id, "pack_contract_version": PACK_CONTRACT_VERSION, "manifest_digest": manifest_digest,
    })
    pack_digest = "pack-digest-" + _sha({
        "pack_id": pack_id, "pack_revision_id": pack_revision_id, "manifest_digest": manifest_digest,
    })

    return ExecutiveBriefingPack(
        pack_id, pack_revision_id, pack_digest, manifest,
        executive_opportunity_brief, buyer_brief)


def validate_executive_briefing_pack(pack: ExecutiveBriefingPack) -> ExecutiveBriefingPack:
    if not isinstance(pack, ExecutiveBriefingPack):
        _fail(PackFailureCode.INVALID_PACK, None, "ExecutiveBriefingPack is required")
    manifest = pack.manifest
    if not isinstance(manifest, ExecutiveBriefingPackManifest):
        _fail(PackFailureCode.INVALID_PACK, None, "pack manifest is invalid")
    if (manifest.pack_contract_name, manifest.pack_contract_version, manifest.edition) != (
            PACK_CONTRACT_NAME, PACK_CONTRACT_VERSION, PACK_EDITION):
        _fail(PackFailureCode.UNSUPPORTED_PACK_VERSION, None, "unsupported pack contract, version, or edition")
    _validate_membership(manifest.members)

    by_slot = {item.slot: item for item in manifest.members}
    eob_member, bb_member = by_slot[SLOT_EXECUTIVE_OPPORTUNITY_BRIEF], by_slot[SLOT_BUYER_BRIEF]

    if not isinstance(pack.executive_opportunity_brief, ExecutiveOpportunityBrief):
        _fail(PackFailureCode.INVALID_MEMBER, SLOT_EXECUTIVE_OPPORTUNITY_BRIEF,
              "an ExecutiveOpportunityBrief is required")
    if not isinstance(pack.buyer_brief, BuyerBrief):
        _fail(PackFailureCode.INVALID_MEMBER, SLOT_BUYER_BRIEF, "a BuyerBrief is required")
    if eob_member.contract_version != EOB_CONTRACT_VERSION or bb_member.contract_version != BUYER_BRIEF_CONTRACT_VERSION:
        _fail(PackFailureCode.UNSUPPORTED_MEMBER_VERSION, None, "manifest member contract version is unsupported")
    if pack.executive_opportunity_brief.brief_version != eob_member.contract_version:
        _fail(PackFailureCode.UNSUPPORTED_MEMBER_VERSION, SLOT_EXECUTIVE_OPPORTUNITY_BRIEF,
              "embedded member version differs from the manifest")
    if pack.buyer_brief.brief_version != bb_member.contract_version:
        _fail(PackFailureCode.UNSUPPORTED_MEMBER_VERSION, SLOT_BUYER_BRIEF,
              "embedded member version differs from the manifest")

    if eob_member.artifact_id != pack.executive_opportunity_brief.brief_id:
        _fail(PackFailureCode.IDENTITY_MISMATCH, SLOT_EXECUTIVE_OPPORTUNITY_BRIEF,
              "manifest artifact identity differs from the embedded member")
    if bb_member.artifact_id != pack.buyer_brief.brief_id:
        _fail(PackFailureCode.IDENTITY_MISMATCH, SLOT_BUYER_BRIEF,
              "manifest artifact identity differs from the embedded member")
    if eob_member.revision_id != pack.executive_opportunity_brief.brief_id:
        _fail(PackFailureCode.REVISION_MISMATCH, SLOT_EXECUTIVE_OPPORTUNITY_BRIEF,
              "manifest revision identity differs from the embedded member's own revision")
    if bb_member.revision_id != pack.buyer_brief.brief_id:
        _fail(PackFailureCode.REVISION_MISMATCH, SLOT_BUYER_BRIEF,
              "manifest revision identity differs from the embedded member's own revision")
    if eob_member.artifact_digest != _member_digest(pack.executive_opportunity_brief):
        _fail(PackFailureCode.DIGEST_MISMATCH, SLOT_EXECUTIVE_OPPORTUNITY_BRIEF,
              "manifest digest differs from the embedded member's real content")
    if bb_member.artifact_digest != _member_digest(pack.buyer_brief):
        _fail(PackFailureCode.DIGEST_MISMATCH, SLOT_BUYER_BRIEF,
              "manifest digest differs from the embedded member's real content")

    eob_opportunity_id = pack.executive_opportunity_brief.understanding.opportunity_id
    if eob_member.opportunity_id != eob_opportunity_id or bb_member.opportunity_id != pack.buyer_brief.opportunity_id:
        _fail(PackFailureCode.IDENTITY_MISMATCH, None, "manifest opportunity binding differs from a real member")
    if eob_opportunity_id != pack.buyer_brief.opportunity_id:
        _fail(PackFailureCode.IDENTITY_MISMATCH, SLOT_BUYER_BRIEF,
              "Buyer Brief does not bind the same opportunity identity as the Executive Opportunity Brief")
    if manifest.opportunity_id != eob_opportunity_id:
        _fail(PackFailureCode.IDENTITY_MISMATCH, None, "pack opportunity identity differs from its members")
    if manifest.buyer_id != pack.buyer_brief.buyer_id:
        _fail(PackFailureCode.IDENTITY_MISMATCH, None, "pack buyer identity differs from its member")

    if not eob_member.evidence_cutoff_governed_absence or eob_member.evidence_cutoff is not None:
        _fail(PackFailureCode.EVIDENCE_CUTOFF_INCOMPATIBLE, SLOT_EXECUTIVE_OPPORTUNITY_BRIEF,
              "Executive Opportunity Brief evidence cutoff must be an explicit governed absence")
    if bb_member.evidence_cutoff_governed_absence or not isinstance(bb_member.evidence_cutoff, date):
        _fail(PackFailureCode.EVIDENCE_CUTOFF_INCOMPATIBLE, SLOT_BUYER_BRIEF,
              "Buyer Brief evidence cutoff must be an explicit, valid date")
    if bb_member.evidence_cutoff != pack.buyer_brief.evidence_cutoff_date:
        _fail(PackFailureCode.EVIDENCE_CUTOFF_INCOMPATIBLE, SLOT_BUYER_BRIEF,
              "manifest evidence cutoff differs from the embedded member")

    expected_manifest_digest = _sha({
        "pack_contract_name": manifest.pack_contract_name,
        "pack_contract_version": manifest.pack_contract_version, "edition": manifest.edition,
        "opportunity_id": manifest.opportunity_id, "buyer_id": manifest.buyer_id,
        "members": manifest.members,
    })
    if manifest.manifest_digest != expected_manifest_digest:
        _fail(PackFailureCode.NON_DETERMINISTIC, None, "manifest digest does not match its own content")
    expected_pack_id = "pack-" + _sha({
        "pack_contract_name": PACK_CONTRACT_NAME,
        "pack_contract_major_version": PACK_CONTRACT_VERSION.split(".")[0],
        "opportunity_id": manifest.opportunity_id, "buyer_id": manifest.buyer_id, "edition": PACK_EDITION,
    })
    if pack.pack_id != expected_pack_id:
        _fail(PackFailureCode.NON_DETERMINISTIC, None, "pack identity does not match its own composition material")
    expected_revision_id = "pack-revision-" + _sha({
        "pack_id": pack.pack_id, "pack_contract_version": manifest.pack_contract_version,
        "manifest_digest": manifest.manifest_digest,
    })
    if pack.pack_revision_id != expected_revision_id:
        _fail(PackFailureCode.NON_DETERMINISTIC, None, "pack revision identity does not match its own manifest")
    expected_digest = "pack-digest-" + _sha({
        "pack_id": pack.pack_id, "pack_revision_id": pack.pack_revision_id,
        "manifest_digest": manifest.manifest_digest,
    })
    if pack.pack_digest != expected_digest:
        _fail(PackFailureCode.NON_DETERMINISTIC, None, "pack digest does not match its own identity")

    if tuple(item.slot for item in manifest.members) != REQUIRED_SLOTS:
        _fail(PackFailureCode.INVALID_PACK, None, "member order does not match the fixed contract order")
    return pack


__all__ = [
    "PACK_CONTRACT_NAME", "PACK_CONTRACT_VERSION", "PACK_EDITION",
    "REQUIRED_SLOTS", "SLOT_BUYER_BRIEF", "SLOT_EXECUTIVE_OPPORTUNITY_BRIEF",
    "VOLUME_CLASS_BUYER_BRIEF", "VOLUME_CLASS_EXECUTIVE_OPPORTUNITY_BRIEF",
    "ExecutiveBriefingPack", "ExecutiveBriefingPackError",
    "ExecutiveBriefingPackManifest", "PackFailureCode", "PackMember",
    "build_executive_briefing_pack", "validate_executive_briefing_pack",
]
