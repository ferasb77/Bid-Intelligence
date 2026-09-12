"""Regression tests for the Phase 2 Stage B provenance remediation:

1. `dates` and `evaluation_criteria` now receive physical-provenance
   validation, matching the principle already applied to `requirements`
   and `submission_rules` (extractor.normalize_package_facts).
2. A source-derived `deliverables`/`commercial_clauses` record with zero
   valid physical references is never silently admitted (deliverables'
   prior behavior) nor silently dropped (commercial_clauses' prior
   behavior) -- both are now quarantined into `_provenance_rejections`
   with the original record and its checked source_refs preserved.
3. contract_hygiene._verified_refs() no longer imposes an excerpt-non-empty
   requirement beyond what validate_source_refs() itself considers valid,
   fixing the root cause of one of the two clauses previously silently
   dropped in real commissioning (a real document+section citation with no
   quotable excerpt is a genuine physical location, not fabricated).

No test here fabricates a page/section/sheet the parser never produced;
every "valid" fixture below matches package_metadata exactly.
"""
from extractor import normalize_package_facts


def _facts(**overrides):
    base = {"doc_metadata": {}, "requirements": [], "dates": [], "evaluation_criteria": [],
            "submission_rules": [], "deliverables": [], "commercial_clauses": [], "contract_risks": []}
    base.update(overrides)
    return base


PDF_META = {"files": ["RFP.pdf"], "doc_metadata": {"RFP.pdf": {"page_count": 5}},
            "doc_texts": {"RFP.pdf": "irrelevant body text"}}
XLSX_META = {"files": ["Criteria.xlsx"],
             "doc_metadata": {"Criteria.xlsx": {"sheets": ["Evaluation"]}},
             "doc_texts": {"Criteria.xlsx": "irrelevant body text"}}


def _rejections(normalized, family):
    return [item for item in normalized["_provenance_rejections"] if item["family"] == family]


# 1. valid PDF date provenance passes
def test_valid_pdf_date_provenance_passes():
    facts = _facts(dates=[{"milestone": "Submission deadline", "date": "2030-01-15", "source_doc": "RFP.pdf"}])
    normalized = normalize_package_facts([facts], PDF_META)
    assert len(normalized["dates"]) == 1
    assert normalized["dates"][0]["source_refs"][0]["verified"] is True
    assert normalized["dates"][0]["source_refs"][0]["source_doc"] == "RFP.pdf"
    assert _rejections(normalized, "dates") == []


# 2. invalid PDF date provenance is rejected/fails closed
def test_invalid_date_source_document_fails_closed():
    facts = _facts(dates=[{"milestone": "Submission deadline", "date": "2030-01-15",
                          "source_doc": "DoesNotExist.pdf"}])
    normalized = normalize_package_facts([facts], PDF_META)
    assert normalized["dates"] == []
    rejected = _rejections(normalized, "dates")
    assert len(rejected) == 1
    assert rejected[0]["reason"] == "ZERO_VALID_PROVENANCE"
    assert rejected[0]["record"]["milestone"] == "Submission deadline"
    assert rejected[0]["source_refs"][0]["verified"] is False


def test_date_with_no_source_doc_is_rejected_not_admitted_unflagged():
    facts = _facts(dates=[{"milestone": "Undated milestone", "date": None, "source_doc": None}])
    normalized = normalize_package_facts([facts], PDF_META)
    assert normalized["dates"] == []
    assert len(_rejections(normalized, "dates")) == 1


# 3. valid XLSX evaluation criterion provenance passes
def test_valid_xlsx_evaluation_criterion_provenance_passes():
    facts = _facts(evaluation_criteria=[{
        "stage": "Technical", "weight": "40%", "weight_basis": "Overall",
        "source_refs": [{"source_doc": "Criteria.xlsx", "sheet": "Evaluation"}],
    }])
    normalized = normalize_package_facts([facts], XLSX_META)
    assert len(normalized["evaluation_criteria"]) == 1
    refs = normalized["evaluation_criteria"][0]["source_refs"]
    assert refs[0]["verified"] is True
    assert refs[0]["sheet"] == "Evaluation"
    assert _rejections(normalized, "evaluation_criteria") == []


# 4. invalid evaluation criterion provenance is rejected/fails closed
def test_invalid_evaluation_criterion_sheet_fails_closed():
    facts = _facts(evaluation_criteria=[{
        "stage": "Technical", "weight": "40%", "weight_basis": "Overall",
        "source_refs": [{"source_doc": "Criteria.xlsx", "sheet": "NoSuchSheet"}],
    }])
    normalized = normalize_package_facts([facts], XLSX_META)
    assert normalized["evaluation_criteria"] == []
    rejected = _rejections(normalized, "evaluation_criteria")
    assert len(rejected) == 1
    assert rejected[0]["source_refs"][0]["verified"] is False
    assert "does not exist" in rejected[0]["source_refs"][0]["validation_error"]


# 5. multi-source evaluation criterion preserves valid provenance union
def test_multi_source_evaluation_criterion_preserves_valid_provenance_union():
    meta = {"files": ["A.pdf", "B.pdf"],
            "doc_metadata": {"A.pdf": {"page_count": 3}, "B.pdf": {"page_count": 3}},
            "doc_texts": {"A.pdf": "text", "B.pdf": "text"}}
    doc1 = _facts(evaluation_criteria=[{"stage": "Technical", "weight": "40%", "weight_basis": "Overall",
                                        "source_refs": [{"source_doc": "A.pdf", "page": 1}]}])
    doc2 = _facts(evaluation_criteria=[{"stage": "Technical", "weight": "40%", "weight_basis": "Overall",
                                        "source_refs": [{"source_doc": "B.pdf", "page": 2}]}])
    normalized = normalize_package_facts([doc1, doc2], meta)
    assert len(normalized["evaluation_criteria"]) == 1
    refs = normalized["evaluation_criteria"][0]["source_refs"]
    assert {r["source_doc"] for r in refs} == {"A.pdf", "B.pdf"}
    assert all(r["verified"] is True for r in refs)


def test_evaluation_criterion_partial_provenance_survives_on_one_valid_ref():
    # One valid + one invalid reference: the record is admitted (>=1 valid),
    # and the invalid reference stays visible inline rather than vanishing.
    meta = {"files": ["A.pdf"], "doc_metadata": {"A.pdf": {"page_count": 3}}, "doc_texts": {"A.pdf": "text"}}
    facts = _facts(evaluation_criteria=[{
        "stage": "Technical", "weight": "40%", "weight_basis": "Overall",
        "source_refs": [{"source_doc": "A.pdf", "page": 1}, {"source_doc": "Missing.pdf", "page": 1}],
    }])
    normalized = normalize_package_facts([facts], meta)
    assert len(normalized["evaluation_criteria"]) == 1
    refs = normalized["evaluation_criteria"][0]["source_refs"]
    assert sorted(r["verified"] for r in refs) == [False, True]


# 6. commercial clause with valid provenance survives
def test_commercial_clause_with_valid_provenance_survives():
    facts = _facts(commercial_clauses=[{
        "clause_kind": "CONFIDENTIALITY", "topic": "Confidentiality", "conditions": [], "scope": {},
        "linked_observation_ids": [], "source_fact": "All information is confidential.",
        "source_refs": [{"source_doc": "RFP.pdf", "section": "Header",
                         "excerpt": "irrelevant body text"}],
    }])
    normalized = normalize_package_facts([facts], PDF_META)
    assert len(normalized["commercial_clauses"]) == 1
    assert normalized["commercial_clauses"][0]["evidence_state"] == "VERIFIED"
    assert _rejections(normalized, "commercial_clauses") == []


def test_commercial_clause_with_valid_section_only_reference_survives_no_excerpt_required():
    # Root-cause fix: a real document+section citation with no excerpt is a
    # genuine physical location (validate_source_refs itself accepts it);
    # contract_hygiene must not impose a stricter, inconsistent extra bar.
    facts = _facts(commercial_clauses=[{
        "clause_kind": "LIABILITY_INDEMNITY", "topic": "Rights on termination", "conditions": [],
        "scope": {}, "linked_observation_ids": [],
        "source_fact": "Termination does not deprive the Bank of remedies.",
        "source_refs": [{"source_doc": "RFP.pdf", "section": "Header", "page": None, "sheet": None}],
    }])
    normalized = normalize_package_facts([facts], PDF_META)
    assert len(normalized["commercial_clauses"]) == 1
    assert normalized["commercial_clauses"][0]["evidence_state"] == "VERIFIED"
    assert normalized["commercial_clauses"][0]["source_refs"][0]["section"] == "Header"


# 7. commercial clause with zero valid provenance cannot disappear silently
def test_commercial_clause_with_zero_valid_provenance_is_quarantined_not_dropped():
    facts = _facts(commercial_clauses=[{
        "clause_kind": "CONFIDENTIALITY", "topic": "Confidentiality", "conditions": [], "scope": {},
        "linked_observation_ids": [], "source_fact": "All information is confidential.",
        "source_refs": [{}],
    }])
    normalized = normalize_package_facts([facts], PDF_META)
    assert normalized["commercial_clauses"] == []
    rejected = _rejections(normalized, "commercial_clauses")
    assert len(rejected) == 1
    assert rejected[0]["reason"] == "ZERO_VALID_PROVENANCE"
    assert rejected[0]["record"]["topic"] == "Confidentiality"
    # The clause is still visible in the full diagnostic ledger too.
    assert len(normalized["_contract_hygiene"]["clauses"]) == 1
    assert normalized["_contract_hygiene"]["clauses"][0]["evidence_state"] == "UNVERIFIED"


# 8. deliverable and commercial-clause zero-provenance behavior is consistent
def test_deliverable_and_clause_zero_provenance_behavior_is_consistent():
    facts = _facts(
        deliverables=[{
            "title": "Undocumented Deliverable", "description": "A deliverable with no citation.",
            "obligation_state": "MANDATORY", "quantity": None, "unit": None, "frequency": "ONE_TIME",
            "scope": {}, "due_milestone": None, "acceptance_criteria": None,
            "responsible_actor": "SUPPLIER", "conditions": [], "source_refs": [],
        }],
        commercial_clauses=[{
            "clause_kind": "CONFIDENTIALITY", "topic": "Undocumented Clause", "conditions": [],
            "scope": {}, "linked_observation_ids": [], "source_fact": "A clause with no citation.",
            "source_refs": [],
        }],
    )
    normalized = normalize_package_facts([facts], PDF_META)
    assert normalized["deliverables"] == []
    assert normalized["commercial_clauses"] == []
    assert len(_rejections(normalized, "deliverables")) == 1
    assert len(_rejections(normalized, "commercial_clauses")) == 1
    for rejected in (_rejections(normalized, "deliverables")[0], _rejections(normalized, "commercial_clauses")[0]):
        assert rejected["reason"] == "ZERO_VALID_PROVENANCE"
        assert rejected["source_refs"] == []


# 9. deduplicated records remain distinguishable from provenance-rejected records
def test_deduplicated_records_are_distinguishable_from_rejected_records():
    doc1 = _facts(requirements=[{"description": "Proponents must sign the form.",
                                 "source_refs": [{"source_doc": "RFP.pdf", "page": 1,
                                                  "excerpt": "irrelevant body text"}]}])
    doc2 = _facts(requirements=[{"description": "Proponents must sign the form.",
                                 "source_refs": [{"source_doc": "RFP.pdf", "page": 2,
                                                  "excerpt": "irrelevant body text"}]}],
                  dates=[{"milestone": "Q&A deadline", "date": "2030-02-01", "source_doc": "Nonexistent.pdf"}])
    normalized = normalize_package_facts([doc1, doc2], PDF_META)
    # Deduplicated: one requirement, citing both pages -- not a rejection.
    assert len(normalized["requirements"]) == 1
    assert len(normalized["requirements"][0]["source_refs"]) == 2
    assert normalized["_provenance_rejections"] == [
        item for item in normalized["_provenance_rejections"] if item["family"] != "requirements"
    ]
    # Provenance-rejected: the date with an unresolvable source document.
    assert normalized["dates"] == []
    rejected_dates = _rejections(normalized, "dates")
    assert len(rejected_dates) == 1
    assert rejected_dates[0]["record"]["milestone"] == "Q&A deadline"


# 10. no fabricated page/section/sheet is introduced
def test_no_fabricated_locator_is_introduced_for_any_family():
    facts = _facts(
        dates=[{"milestone": "Deadline", "date": "2030-01-01", "source_doc": "RFP.pdf"}],
        evaluation_criteria=[{"stage": "Technical", "weight": "10%",
                              "source_refs": [{"source_doc": "RFP.pdf"}]}],
    )
    normalized = normalize_package_facts([facts], PDF_META)
    date_ref = normalized["dates"][0]["source_refs"][0]
    assert date_ref["page"] is None and date_ref["sheet"] is None and date_ref["section"] is None
    eval_ref = normalized["evaluation_criteria"][0]["source_refs"][0]
    assert eval_ref["page"] is None and eval_ref["sheet"] is None and eval_ref["section"] is None


# 11. existing valid requirement provenance behavior remains unchanged
def test_existing_valid_requirement_provenance_behavior_is_unchanged():
    facts = _facts(requirements=[{"description": "Proponents must submit a signed form.",
                                  "source_refs": [{"source_doc": "RFP.pdf", "page": 1,
                                                   "excerpt": "irrelevant body text"}]}])
    normalized = normalize_package_facts([facts], PDF_META)
    assert len(normalized["requirements"]) == 1
    assert normalized["requirements"][0]["source_refs"][0]["verified"] is True
    assert _rejections(normalized, "requirements") == []


def test_requirement_with_invalid_reference_still_admitted_inline_flagged_unchanged():
    # Requirements/submission_rules were not part of this remediation's new
    # whole-record admission gate (DEFECT 1/2 scoped this to dates,
    # evaluation_criteria, deliverables, and commercial_clauses only); a
    # requirement whose only reference is invalid keeps its pre-existing
    # behavior of being admitted with the reference flagged inline.
    facts = _facts(requirements=[{"description": "Unverifiable requirement.",
                                  "source_refs": [{"source_doc": "Nonexistent.pdf", "page": 1}]}])
    normalized = normalize_package_facts([facts], PDF_META)
    assert len(normalized["requirements"]) == 1
    assert normalized["requirements"][0]["source_refs"][0]["verified"] is False


# 12. existing valid submission-rule provenance behavior remains unchanged
def test_existing_valid_submission_rule_provenance_behavior_is_unchanged():
    facts = _facts(submission_rules=[{"item": "Appendix A", "format": "DOCX", "mandatory": 1,
                                      "source_refs": [{"source_doc": "RFP.pdf", "page": 1,
                                                       "excerpt": "irrelevant body text"}]}])
    normalized = normalize_package_facts([facts], PDF_META)
    assert len(normalized["submission_rules"]) == 1
    assert normalized["submission_rules"][0]["source_refs"][0]["verified"] is True


def test_recovered_truncated_upstream_diagnostic_is_not_a_stage_b_field():
    # Stage B's schema was intentionally not given a diagnostic-lineage field;
    # RECOVERED_TRUNCATED lineage stays a commissioning-report-only concern.
    facts = _facts()
    normalized = normalize_package_facts([facts], PDF_META)
    assert "_extraction_diagnostic" not in normalized
    assert "recovered_truncated" not in {key.lower() for key in normalized}
