# Decision Brief Reconstruction Architecture Note (BI-VALUE-3 Phase B)

## 1. Current Brief Pipeline Flow
```
analysis_service.export_bid_intelligence_brief_pdf(run_id)
  ├── load_raw_fast_analysis_result(run_id) / snapshot -> FastAnalysisResult
  ├── db.get_analysis_result(run_id) -> full_analysis_result (dict)
  ├── understand_brief.build_bid_intelligence_brief(result, full_result, analysis_partial) -> BidIntelligenceBrief
  └── understand_brief_report.render_report(brief) -> PDF bytes
```

## 2. Available vs Ignored Analysis Outputs
- **Full Analysis Reconciled Findings**: Run 57 produced 58 reconciled findings and 13 cross-domain risks across 6 specialist domains (`SCOPE_DELIVERABLES`, `SCHEDULE_SUBMISSION`, `PROCUREMENT_STRUCTURE`, `COMMERCIAL_CONTRACTUAL`, `EVALUATION_INTELLIGENCE`, `REQUIREMENTS_COMPLIANCE`). The legacy `understand_brief.py` ignored all of these, only extracting a few clarification items from ambiguities/contradictions.
- **Canonical Requirements**: `FastAnalysisResult.requirements` contains 13 rich requirements for York P27-070. `understand_brief.py:_scope()` actively stripped them using regex patterns (`^(provide|proponents? must|describe|submit|complete...)` and `(?:credential|certif|ethical...)`), causing the primary brief to lose critical technical requirements (Canadian SME ecosystem, deep bench, named CVs, 3 references, sample training framework).
- **Evaluation Intelligence**: `FastAnalysisResult.evaluation_criteria` accurately captures the 80/20 written split (Methodology 45, Qualifications 35, Financial 20) and the conditional +20 point Shortlist Presentation. The legacy brief flattened occurrences, produced duplicate criteria names, and lacked substantive response prompts.
- **Governed Buyer Research**: Governed buyer research under `buyer-research/2` and `source-authority-policy/3` is persisted in `buyer_research_runs` (or cached/queryable), but was never wired into `understand_brief.py`.

## 3. Epistemic Separation & Source Priority
1. **Governed Canonical Procurement Truth** (`requirements`, `procurement_revision`)
2. **Buyer-Issued Document Evidence** (`FastAnalysisResult.requirements`, `evaluation_criteria`, `commercial_clauses`, source document text)
3. **Verified External Buyer Facts** (`buyer_research_runs` verified signals under `source-authority-policy/3+`, `yorku.ca`)
4. **Validated Full Analysis Specialist Findings** (`full_analysis_result.reconciled_findings`, `cross_domain_risks`)
5. **Bounded Bid Intelligence Interpretation & Recommendations** (`BID INTELLIGENCE INTERPRETATION`, `BID STRATEGY / PROOF RECOMMENDATION`)

## 4. Leakage & Defense Checklist
- **Internal IDs**: Strip any `REQ-\d+`, `SPECIALIST_[A-Z0-9_:]+`, `OBL-\d+`, `IDENT-\d+`, run IDs, token counts, or model names from customer-facing text.
- **Predictive Claims**: Reject claims about evaluator psychology ("evaluators will reject/penalize", "massive scoring edge").
- **Invented Thresholds**: Prohibit stating any minimum passing score when none is specified in the RFP.
- **Proof Separation**: Strictly distinguish mandatory buyer-required evidence (RFP FACT) from recommended proof strategy (RECOMMENDATION).
- **Claim Validation**: Every claim in the brief must reference its underlying evidence locator or requirement ID.
