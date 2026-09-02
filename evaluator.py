"""
evaluator.py — Deterministic Submission State Evaluator

Pure deterministic business logic for Stage 5 (SUBMIT) readiness evaluation.
Decoupled completely from Streamlit, database, and LLM calls.
Single authoritative source for:
- Gate status ("NOT_READY", "READY_WITH_WARNINGS", "READY_TO_SUBMIT")
- Submission enablement (can_submit)
- Blocker and warning lists
- Detailed requirement, document, and attestation counts
"""
from typing import Any

READY_DOC_STATUSES = frozenset({"Uploaded", "Approved", "Complete", "Submitted"})

ATTESTATION_KEYS = (
    "proposal_separation",
    "mandatory_criteria_pass",
    "addenda_acknowledged",
    "executive_signoff",
)

ATTESTATION_LABELS = {
    "proposal_separation": "Technical/Financial proposal separation verification unchecked",
    "mandatory_criteria_pass": "Mandatory qualification criteria confirmation unchecked",
    "addenda_acknowledged": "Tender addenda & bulletins acknowledgement unchecked",
    "executive_signoff": "Executive sign-off confirmation unchecked",
}


def evaluate_submission_state(
    requirements: list[dict[str, Any]] | None,
    documents: list[dict[str, Any]] | None,
    attestations: dict[str, bool] | None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    """
    Evaluate Stage 5 SUBMIT readiness deterministically.

    Invariants enforced:
    - If blockers:
        status = "NOT_READY"
        can_submit = False
    - Elif warnings:
        status = "READY_WITH_WARNINGS"
        can_submit = True
    - Else:
        status = "READY_TO_SUBMIT"
        can_submit = True

    Blockers:
    A. Mandatory requirement with qual_status == "FAIL".
    B. Mandatory requirement with qual_status == "CONCERN" (requires resolution before submission).
    C. Mandatory requirement with qual_status in ("UNKNOWN", None, "") or missing qual_status.
    D. Required submission document not in READY_DOC_STATUSES ("Uploaded", "Approved", "Complete", "Submitted").
    E. Submission document with mandatory status UNKNOWN (mandatory is None).
    F. Any required attestation that is unchecked (False).
    """
    req_list = requirements or []
    doc_list = documents or []
    att_dict = attestations or {}

    blockers: list[str] = []
    warn_list: list[str] = list(warnings) if warnings else []

    # 1. Requirements evaluation
    mand_reqs = [r for r in req_list if r.get("category") == "Mandatory"]
    m_pass = 0
    m_concern = 0
    m_fail = 0
    m_unknown = 0

    for r in mand_reqs:
        qs = r.get("qual_status")
        if qs == "PASS":
            m_pass += 1
        elif qs == "CONCERN":
            m_concern += 1
        elif qs == "FAIL":
            m_fail += 1
        else:
            # UNKNOWN, None, missing, or unverified
            m_unknown += 1

    if m_fail > 0:
        blockers.append(f"{m_fail} Mandatory Qualification Gate(s) marked as FAIL")
    if m_concern > 0:
        blockers.append(f"{m_concern} Mandatory Qualification Gate(s) remain CONCERN and require resolution")
    if m_unknown > 0:
        blockers.append(f"{m_unknown} Mandatory Qualification Gate(s) remain UNKNOWN (Unverified)")

    # 2. Documents evaluation
    # Filter submission/financial package documents
    sub_docs = [d for d in doc_list if d.get("doc_type") in ("Submission", "Financial")]
    req_docs_ready = 0
    req_docs_missing = 0
    req_docs_total = 0
    unknown_doc_mand = 0

    for d in sub_docs:
        mand_val = d.get("mandatory")
        if mand_val in (1, True, "1", "true"):
            req_docs_total += 1
            if d.get("status") in READY_DOC_STATUSES:
                req_docs_ready += 1
            else:
                req_docs_missing += 1
        elif mand_val in (0, False, "0", "false"):
            # Optional document -- does not block even if not uploaded
            pass
        else:
            # mandatory is None/missing -> UNKNOWN
            unknown_doc_mand += 1

    if req_docs_missing > 0:
        blockers.append(f"{req_docs_missing} Required Submission Document(s) missing or not ready")

    if unknown_doc_mand > 0:
        blockers.append(f"{unknown_doc_mand} Submission Document(s) have UNKNOWN mandatory status (review required)")

    # 3. Attestations evaluation
    unchecked_attestations = 0
    for key in ATTESTATION_KEYS:
        if not att_dict.get(key, False):
            unchecked_attestations += 1
            blockers.append(ATTESTATION_LABELS.get(key, f"Attestation '{key}' unchecked"))

    # 4. Status determination & invariants
    if blockers:
        status = "NOT_READY"
        can_submit = False
    elif warn_list:
        status = "READY_WITH_WARNINGS"
        can_submit = True
    else:
        status = "READY_TO_SUBMIT"
        can_submit = True

    return {
        "status": status,
        "can_submit": can_submit,
        "blockers": blockers,
        "warnings": warn_list,
        "counts": {
            "mandatory_requirements": len(mand_reqs),
            "mandatory_pass": m_pass,
            "mandatory_concern": m_concern,
            "mandatory_fail": m_fail,
            "mandatory_unknown": m_unknown,
            "required_documents": req_docs_total,
            "required_documents_ready": req_docs_ready,
            "required_documents_missing": req_docs_missing,
            "unknown_document_mandatory": unknown_doc_mand,
            "unchecked_attestations": unchecked_attestations,
        },
    }
