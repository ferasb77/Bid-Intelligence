"""Regression tests for the Phase 3 Stage C hardening investigation:

1. Stage B's submission_rules cross-document merge previously used only
   the canonical item text as its dedup key, silently merging generically-
   worded, per-service-category response-form instructions (e.g. each of
   Appendix D1/D2/D3's own "Rated Criteria Response Form" page-limit
   statement) into ONE record -- discarding every value but the first
   document's. Fixed by adding an appendix-scope component (derived from
   the source filename, mirroring the scope signal Stage C's own
   PAGE_LIMIT conflict dimension already trusts) to the merge key.

2. Structured (verified) commercial_clauses previously had no dedicated
   Stage C conflict detector at all (unlike structured deliverables).
   `contract_hygiene.structured_commercial_clause_conflicts()` closes this
   gap with the same conservative, deterministic, no-LLM discipline as its
   deliverable counterpart: only same clause_kind + same normalized topic
   + same explicit scope are ever compared, and only when both sides state
   an extractable quantified value (dollar/percent/day/week/month/year)
   that actually differs.
"""
import contract_hygiene as hygiene
from extractor import normalize_package_facts


def _facts(**overrides):
    base = {"doc_metadata": {}, "requirements": [], "dates": [], "evaluation_criteria": [],
            "submission_rules": [], "deliverables": [], "commercial_clauses": [], "contract_risks": []}
    base.update(overrides)
    return base


PDF_META = {"files": ["D1.docx", "D2.docx", "D3.docx"],
            "doc_metadata": {"D1.docx": {}, "D2.docx": {}, "D3.docx": {}},
            "doc_texts": {"D1.docx": "text", "D2.docx": "text", "D3.docx": "text"}}


def _sr(item, source_doc, details="", fmt=""):
    return {"item": item, "format": fmt, "details": details, "mandatory": 1, "source_doc": source_doc,
            "source_refs": [{"source_doc": source_doc, "section": "Header", "excerpt": "irrelevant"}]}


# --- 1 & 2: submission_rules scope-aware merge -----------------------------

def test_same_wording_different_appendix_scope_preserves_both_page_limits_no_merge():
    facts = _facts(submission_rules=[
        _sr("Rated Criteria Response Form", "D1.docx", "Maximum 15 pages"),
        _sr("Rated Criteria Response Form", "D2.docx", "Maximum 12 pages"),
    ])
    normalized = normalize_package_facts([facts], PDF_META)
    matching = [r for r in normalized["submission_rules"] if r["item"] == "Rated Criteria Response Form"]
    assert len(matching) == 2, "D1 and D2's own per-category page limits must not silently merge into one record"
    details = {r["details"] for r in matching}
    assert details == {"Maximum 15 pages", "Maximum 12 pages"}
    for r in matching:
        assert len(r["source_refs"]) == 1  # no cross-appendix ref bleed


def test_same_wording_and_same_appendix_scope_still_merges_as_corroboration():
    # Two distinct chunks/mentions that both genuinely resolve to the SAME
    # appendix scope (both filenames contain "d1") should still merge and
    # accumulate both physical references -- the fix only separates
    # DIFFERENT appendices, not repeated mentions of the same one.
    meta = {"files": ["D1-part-a.docx", "D1-part-b.docx"],
            "doc_metadata": {"D1-part-a.docx": {}, "D1-part-b.docx": {}},
            "doc_texts": {"D1-part-a.docx": "text", "D1-part-b.docx": "text"}}
    facts = _facts(submission_rules=[
        _sr("Rated Criteria Response Form", "D1-part-a.docx", "Maximum 15 pages"),
    ])
    doc2 = _facts(submission_rules=[
        _sr("Rated Criteria Response Form", "D1-part-b.docx", "Maximum 15 pages"),
    ])
    normalized = normalize_package_facts([facts, doc2], meta)
    matching = [r for r in normalized["submission_rules"] if r["item"] == "Rated Criteria Response Form"]
    assert len(matching) == 1
    assert len(matching[0]["source_refs"]) == 2


def test_no_appendix_signal_in_filename_merges_as_before_unaffected():
    facts = _facts(submission_rules=[
        _sr("Cover Letter", "abstract.pdf", "One page maximum"),
    ])
    meta = {"files": ["abstract.pdf"], "doc_metadata": {"abstract.pdf": {}}, "doc_texts": {"abstract.pdf": "text"}}
    normalized = normalize_package_facts([facts], meta)
    assert len(normalized["submission_rules"]) == 1


# --- 3: revised-D2-style genuine amendment change IS detected ---------------

def test_genuine_cross_document_page_limit_disagreement_in_same_appendix_scope_is_true_conflict():
    # Simulates what an actual original-vs-revised D2 change WOULD look
    # like if the page limit had genuinely changed (it did not, in the
    # real corpus -- see the hardening report) -- both candidates carry
    # the same D2 appendix-scope signal (both filenames contain "d2"), so
    # this is exactly the "revised D2" case: same scope, different value.
    from extractor import detect_document_conflicts
    normalized = {
        "submission_rules": [
            _sr("Rated Criteria Response Form", "OriginalRevision/Appendix D2.docx", "Maximum 15 pages"),
            _sr("Rated Criteria Response Form", "Amendment1/Appendix D2 REVISED.docx", "Maximum 12 pages"),
        ],
    }
    conflicts = detect_document_conflicts(normalized, ["OriginalRevision/Appendix D2.docx",
                                                        "Amendment1/Appendix D2 REVISED.docx"])
    page_conflicts = [c for c in conflicts if c.get("conflict_type") == "SUBMISSION_RULE_CONFLICT"]
    assert len(page_conflicts) == 1
    assert page_conflicts[0]["classification"] == "TRUE_CONFLICT"


def test_different_appendix_scope_page_limits_are_not_manufactured_into_a_conflict():
    from extractor import detect_document_conflicts
    normalized = {
        "submission_rules": [
            _sr("Rated Criteria Response Form", "OriginalRevision/Appendix D1.docx", "Maximum 15 pages"),
            _sr("Rated Criteria Response Form", "OriginalRevision/Appendix D2.docx", "Maximum 12 pages"),
        ],
    }
    conflicts = detect_document_conflicts(normalized, ["OriginalRevision/Appendix D1.docx",
                                                        "OriginalRevision/Appendix D2.docx"])
    page_conflicts = [c for c in conflicts if c.get("conflict_type") == "SUBMISSION_RULE_CONFLICT"]
    assert len(page_conflicts) == 0


# --- 4: compatible duplicate commercial-clause wording -> no conflict ------

def test_commercial_clause_same_kind_topic_scope_no_extractable_value_is_not_flagged():
    # Mirrors the real corpus's "Accessible Canada Act (ACA) Compliance"
    # pair restated (compatibly, with no numbers) across two appendices.
    a = {"clause_kind": "REGULATORY_COMPLIANCE", "topic": "Accessible Canada Act (ACA) Compliance",
         "source_fact": "As a Crown corporation, the Bank is required to comply with the Accessible Canada Act.",
         "conditions": [], "scope": {}, "linked_observation_ids": [],
         "source_refs": [{"source_doc": "B1.xlsx", "excerpt": "As a Crown corporation..."}]}
    b = {"clause_kind": "REGULATORY_COMPLIANCE", "topic": "Accessible Canada Act (ACA) Compliance",
         "source_fact": "As a Crown corporation, the Bank is required to comply with the Accessible Canada Act.",
         "conditions": [], "scope": {}, "linked_observation_ids": [],
         "source_refs": [{"source_doc": "B3.xlsx", "excerpt": "As a Crown corporation..."}]}
    def verify(refs, _metadata):
        return [{**ref, "verified": True} for ref in refs]
    result = hygiene.build_contract_hygiene([], [a, b], [], verify, {"files": ["B1.xlsx", "B3.xlsx"],
                                                                       "doc_metadata": {}, "doc_texts": {}})
    conflicts = hygiene.structured_commercial_clause_conflicts(result["clauses"])
    assert conflicts == []


# --- 5-10: structured_commercial_clause_conflicts direct tests -------------

def _verify(refs, _metadata):
    return [{**ref, "verified": True} for ref in refs]


def _built_clauses(*raws):
    result = hygiene.build_contract_hygiene([], list(raws), [], _verify,
                                            {"files": ["A.pdf", "B.pdf"], "doc_metadata": {}, "doc_texts": {}})
    return result["clauses"]


def test_commercial_clause_same_kind_scope_same_value_no_conflict():
    a = {"clause_kind": "LIABILITY_INDEMNITY", "topic": "Commercial General Liability Insurance",
         "source_fact": "Minimum coverage of $3,000,000.00 per occurrence.", "conditions": [], "scope": {},
         "linked_observation_ids": [], "source_refs": [{"source_doc": "A.pdf", "excerpt": "x"}]}
    b = {**a, "source_refs": [{"source_doc": "B.pdf", "excerpt": "x"}]}
    conflicts = hygiene.structured_commercial_clause_conflicts(_built_clauses(a, b))
    assert conflicts == []


def test_commercial_clause_same_kind_scope_incompatible_value_is_conflict():
    a = {"clause_kind": "LIABILITY_INDEMNITY", "topic": "Commercial General Liability Insurance",
         "source_fact": "Minimum coverage of $3,000,000.00 per occurrence.", "conditions": [], "scope": {},
         "linked_observation_ids": [], "source_refs": [{"source_doc": "A.pdf", "excerpt": "x"}]}
    b = {"clause_kind": "LIABILITY_INDEMNITY", "topic": "Commercial General Liability Insurance",
         "source_fact": "Minimum coverage of $5,000,000.00 per occurrence.", "conditions": [], "scope": {},
         "linked_observation_ids": [], "source_refs": [{"source_doc": "B.pdf", "excerpt": "y"}]}
    conflicts = hygiene.structured_commercial_clause_conflicts(_built_clauses(a, b))
    assert len(conflicts) == 1
    assert conflicts[0]["classification"] == "TRUE_CONFLICT"
    assert conflicts[0]["conflict_type"] == "COMMERCIAL_TERM_CONFLICT"


def test_commercial_clause_same_kind_different_scope_no_conflict():
    a = {"clause_kind": "TERMINATION", "topic": "Termination for Convenience",
         "source_fact": "Ten (10) business days written notice required.", "conditions": [],
         "scope": {"lot": "Lot A"}, "linked_observation_ids": [],
         "source_refs": [{"source_doc": "A.pdf", "excerpt": "x"}]}
    b = {"clause_kind": "TERMINATION", "topic": "Termination for Convenience",
         "source_fact": "Thirty (30) business days written notice required.", "conditions": [],
         "scope": {"lot": "Lot B"}, "linked_observation_ids": [],
         "source_refs": [{"source_doc": "B.pdf", "excerpt": "y"}]}
    conflicts = hygiene.structured_commercial_clause_conflicts(_built_clauses(a, b))
    assert conflicts == []


def test_commercial_clause_conflict_preserves_physical_provenance_for_all_candidates():
    a = {"clause_kind": "PAYMENT_WITHHOLDING_SETOFF", "topic": "Payment Period",
         "source_fact": "Payment due within 30 days of invoice.", "conditions": [], "scope": {},
         "linked_observation_ids": [], "source_refs": [{"source_doc": "A.pdf", "excerpt": "x"}]}
    b = {"clause_kind": "PAYMENT_WITHHOLDING_SETOFF", "topic": "Payment Period",
         "source_fact": "Payment due within 45 days of invoice.", "conditions": [], "scope": {},
         "linked_observation_ids": [], "source_refs": [{"source_doc": "B.pdf", "excerpt": "y"}]}
    conflicts = hygiene.structured_commercial_clause_conflicts(_built_clauses(a, b))
    assert len(conflicts) == 1
    candidates = conflicts[0]["candidates"]
    assert len(candidates) == 2
    assert {c["source_refs"][0]["source_doc"] for c in candidates} == {"A.pdf", "B.pdf"}
    assert all(c["source_refs"] for c in candidates)


def test_unresolved_commercial_conflict_has_no_winner():
    a = {"clause_kind": "PAYMENT_WITHHOLDING_SETOFF", "topic": "Payment Period",
         "source_fact": "Payment due within 30 days of invoice.", "conditions": [], "scope": {},
         "linked_observation_ids": [], "source_refs": [{"source_doc": "A.pdf", "excerpt": "x"}]}
    b = {"clause_kind": "PAYMENT_WITHHOLDING_SETOFF", "topic": "Payment Period",
         "source_fact": "Payment due within 45 days of invoice.", "conditions": [], "scope": {},
         "linked_observation_ids": [], "source_refs": [{"source_doc": "B.pdf", "excerpt": "y"}]}
    conflicts = hygiene.structured_commercial_clause_conflicts(_built_clauses(a, b))
    assert "winner" not in conflicts[0]
    assert "resolution_basis" not in conflicts[0] or conflicts[0].get("resolution_basis") is None


def test_commercial_clause_conflict_cannot_contain_a_fabricated_value():
    a = {"clause_kind": "PAYMENT_WITHHOLDING_SETOFF", "topic": "Payment Period",
         "source_fact": "Payment due within 30 days of invoice.", "conditions": [], "scope": {},
         "linked_observation_ids": [], "source_refs": [{"source_doc": "A.pdf", "excerpt": "x"}]}
    b = {"clause_kind": "PAYMENT_WITHHOLDING_SETOFF", "topic": "Payment Period",
         "source_fact": "Payment due within 45 days of invoice.", "conditions": [], "scope": {},
         "linked_observation_ids": [], "source_refs": [{"source_doc": "B.pdf", "excerpt": "y"}]}
    conflicts = hygiene.structured_commercial_clause_conflicts(_built_clauses(a, b))
    assessment = conflicts[0]["assessment"]
    assert "30 days" in assessment and "45 days" in assessment
    # every value shown is one of the two real extracted sets -- nothing else
    assert "60 days" not in assessment and "90 days" not in assessment


def test_commercial_clause_without_extractable_value_never_flagged():
    a = {"clause_kind": "CONFIDENTIALITY", "topic": "Non-Disclosure",
         "source_fact": "Confidential information must not be disclosed to third parties.", "conditions": [],
         "scope": {}, "linked_observation_ids": [], "source_refs": [{"source_doc": "A.pdf", "excerpt": "x"}]}
    b = {"clause_kind": "CONFIDENTIALITY", "topic": "Non-Disclosure",
         "source_fact": "Confidential information shall remain confidential at all times.", "conditions": [],
         "scope": {}, "linked_observation_ids": [], "source_refs": [{"source_doc": "B.pdf", "excerpt": "y"}]}
    conflicts = hygiene.structured_commercial_clause_conflicts(_built_clauses(a, b))
    assert conflicts == []


# --- 11 & 12: pre-existing behavior unchanged -------------------------------

def test_existing_evaluation_conflict_behavior_unchanged_after_hardening():
    from extractor import detect_document_conflicts
    normalized = {
        "evaluation_criteria": [
            {"stage": "Methodology", "weight": "20 points", "source_refs": [{"source_doc": "A.pdf"}]},
            {"stage": "Methodology", "weight": "30 points", "source_refs": [{"source_doc": "B.pdf"}]},
        ],
    }
    conflicts = detect_document_conflicts(normalized, ["A.pdf", "B.pdf"])
    eval_conflicts = [c for c in conflicts if c.get("conflict_type") == "EVALUATION_CONFLICT"]
    assert len(eval_conflicts) == 1
    assert eval_conflicts[0]["classification"] == "TRUE_CONFLICT"


def test_existing_canonical_opportunity_conflict_behavior_unchanged_after_hardening():
    from canonical_opportunity import build_canonical_opportunity, resolve_canonical_opportunity
    doc_facts = [{"typed_observations": [
        {"family": "IDENTITY", "semantic_kind": "BUYER_NAME", "original_value": "Acme Corp",
         "source_doc": "A.pdf",
         "source_refs": [{"source_doc": "A.pdf", "page": 1, "excerpt": "Acme Corp"}]},
        {"family": "IDENTITY", "semantic_kind": "BUYER_NAME", "original_value": "Beta Inc",
         "source_doc": "B.pdf",
         "source_refs": [{"source_doc": "B.pdf", "page": 1, "excerpt": "Beta Inc"}]},
    ]}]
    meta = {"files": ["A.pdf", "B.pdf"],
            "doc_texts": {"A.pdf": "[[SOURCE: A.pdf | PAGE: 1]]\nAcme Corp",
                          "B.pdf": "[[SOURCE: B.pdf | PAGE: 1]]\nBeta Inc"}}
    canonical = build_canonical_opportunity(doc_facts, meta)
    resolved = resolve_canonical_opportunity(canonical)
    assert resolved["resolved"]["client"]["status"] == "CONFLICTED"
    assert len(resolved["conflicts"]) == 1
