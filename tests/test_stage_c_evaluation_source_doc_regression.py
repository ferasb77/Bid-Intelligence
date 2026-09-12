"""Regression test for a Stage C defect found during Phase 3 commissioning:
`detect_document_conflicts()`'s EVALUATION CONFLICTS section read
`ec.get("source_doc", "Document")`, but `evaluation_hierarchy.
normalize_evaluation_criterion()` (Stage B) never populates a top-level
`source_doc` field on its output -- only validated `source_refs[]`. Every
evaluation criterion therefore fell back to the same literal string
"Document", making genuine cross-document weight conflicts misclassify as
spurious same-"document" internal inconsistencies (source_validity
SYNTHESIZED, permanently downgraded from TRUE_CONFLICT to REVIEW_ITEM by
the Final Source Validity Enforcement pass) -- for every single evaluation
criterion in every corpus, not just this one.

The fix derives s_doc from source_refs[0].source_doc, mirroring the pattern
the MANDATORY REQUIREMENT CONFLICTS section already used correctly.
"""
from extractor import detect_document_conflicts


def test_cross_document_evaluation_weight_conflict_is_true_conflict_not_spurious_internal():
    normalized = {
        "evaluation_criteria": [
            {"stage": "Corporate Profile", "weight": "10 points",
             "source_refs": [{"source_doc": "D1.docx", "section": "Header"}]},
            {"stage": "Corporate Profile", "weight": "5 points",
             "source_refs": [{"source_doc": "D2.docx", "section": "Header"}]},
        ],
    }
    conflicts = detect_document_conflicts(normalized, ["D1.docx", "D2.docx"])
    eval_conflicts = [c for c in conflicts if c.get("conflict_type") == "EVALUATION_CONFLICT"]
    assert len(eval_conflicts) == 1
    conflict = eval_conflicts[0]
    assert conflict["classification"] == "TRUE_CONFLICT"
    assert conflict["source_validity"] == "PHYSICAL_BOTH"
    assert {conflict["source_a"]["doc"], conflict["source_b"]["doc"]} == {"D1.docx", "D2.docx"}
    assert "Document" not in (conflict["source_a"]["doc"], conflict["source_b"]["doc"])


def test_same_document_weight_disagreement_still_reports_as_internal_review_item():
    # Two criteria genuinely from the SAME real document should still be
    # reported as an internal inconsistency, not upgraded to TRUE_CONFLICT.
    normalized = {
        "evaluation_criteria": [
            {"stage": "Corporate Profile", "weight": "10 points",
             "source_refs": [{"source_doc": "D1.docx", "section": "Header"}]},
            {"stage": "Corporate Profile", "weight": "5 points",
             "source_refs": [{"source_doc": "D1.docx", "section": "Body"}]},
        ],
    }
    conflicts = detect_document_conflicts(normalized, ["D1.docx"])
    eval_conflicts = [c for c in conflicts if c.get("conflict_type") == "EVALUATION_CONFLICT"]
    assert len(eval_conflicts) == 1
    assert eval_conflicts[0]["classification"] == "REVIEW_ITEM"
    assert eval_conflicts[0]["source_a"]["doc"] == eval_conflicts[0]["source_b"]["doc"] == "D1.docx"


def test_evaluation_criterion_missing_source_refs_falls_back_to_document_placeholder():
    # No source_refs at all (e.g. hand-built legacy input): falls back to
    # the same "Document" placeholder as before -- not fabricated, and
    # still correctly downgraded to REVIEW_ITEM rather than a false
    # TRUE_CONFLICT, since it cannot claim two distinct physical sources.
    normalized = {
        "evaluation_criteria": [
            {"stage": "Corporate Profile", "weight": "10 points"},
            {"stage": "Corporate Profile", "weight": "5 points"},
        ],
    }
    conflicts = detect_document_conflicts(normalized, [])
    eval_conflicts = [c for c in conflicts if c.get("conflict_type") == "EVALUATION_CONFLICT"]
    assert len(eval_conflicts) == 1
    assert eval_conflicts[0]["classification"] == "REVIEW_ITEM"
    assert eval_conflicts[0]["source_a"]["doc"] == eval_conflicts[0]["source_b"]["doc"] == "Document"
