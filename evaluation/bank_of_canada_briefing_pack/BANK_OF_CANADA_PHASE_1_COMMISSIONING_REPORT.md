# Bank of Canada RFP 2026-026 — Phase 1 Commissioning Report (16-Document Authoritative Corpus)

This report documents a fresh, real production run of **Phase 1** (corpus discovery → document parsing/preprocessing → Procurement Evidence Adapter → Evidence Publication → Stage A per-document fact extraction) against the authoritative 16-document Bank of Canada RFP 2026-026 corpus — the corpus including the previously-missing master RFP document. It stops at the end of Stage A. Stage B, Stage C, Stage D, Canonical Opportunity, Opportunity Intelligence, Buyer Brief, Executive Opportunity Brief, and Executive Briefing Pack were **not** run.

Every field, count, and record shown below is read directly from the real artifacts this run produced — none of it is reconstructed, paraphrased, or reinterpreted. Where a record is shown, it is the actual serialized production object (or its `source_refs`/fields verbatim), not a prose description of it.

## A. Run identity and metadata

| Field | Value |
|---|---|
| Fresh run ID | `phase1-boc-2026-026-corrected16-20260912T080929Z-9fd9e5` |
| Timestamp (UTC) | 2026-09-12T08:09:31.692481+00:00 |
| Git commit | `7e797830f42d06ff08745648585de0e26557addb` |
| Git working tree | dirty — 113 changed files (pre-existing uncommitted work from this session; unrelated to this run) |
| Production entry point | `scripts/commission_phase1_bank_of_canada.py`, calling `extract_document_with_metadata`, `adapt_procurement_corpus`, `publish_evidence`, `validate_evidence_publication`, `extract_document_facts` directly — the same functions `scripts/commission_original_bank_of_canada.py` uses for its own Procurement Corpus → Stage A boundaries |
| Stage A model | `claude-haiku-4-5-20251001`, temperature 0.0 |
| Corpus path | `evaluation/bank_of_canada_briefing_pack/corrected_procurement_corpus` |
| Corpus identifier | `bank-of-canada-rfp-2026-026-corrected-16doc` |
| Document count | 16 |
| Total page count (PDF pages only; DOCX/XLSX have no page concept in this pipeline) | 6 (abstract.pdf) + 21 (master RFP) = 27 pages with a `page_count` field |
| Evidence acquisition date (`retrieved_on`) | 2026-09-08 |
| Evidence snapshot ID | `esnap-83a01d08405490c862b39aad6e54dbd2930e539f2afdc9f397dcd945534d640a` |
| Evidence publication ID | `evidence-publication-record-f1d11d2ca5dbe96377b0b98dbb544a326e9709b9b4357d5c68c8c92c4dbc6790` |
| Total elapsed time | 2250.724 s (≈ 37.5 minutes); Stage A alone: 2245.556 s (≈ 37.4 minutes) |
| Token usage | **Unavailable.** `extract_document_facts`/`_extract_chunk_facts` in `extractor.py` call `client.messages.create(...)` but this run's code path does not read or log `response.usage`; not fabricated. |
| API cost | **Unavailable**, for the same reason — no usage/cost telemetry is captured by the production code called here. |
| Cache-bypass measures taken | 1) `CHECKPOINT_MODE=off` — the repository's opt-in checkpoint/resume system (`stage_d_checkpoints.py`) was never invoked; `resume_procurement_checkpoint()`/`load_verified_checkpoint()` were never called. 2) A brand-new, timestamp+random-suffixed output directory was used; nothing was read from `evaluation/bank_of_canada_briefing_pack/corrected_pipeline/` (the historical evaluation-harness outputs) or from `tests/fixtures/local/bank_of_canada_2026_026` (the superseded 15-document corpus). 3) `extract_document_facts`/`_extract_chunk_facts` were read in `extractor.py` before this run: every call reaches `client.messages.create(...)` unconditionally — there is no memoization or response cache in that code path, so every one of this run's calls was a genuine live request. |

## B. Corpus gate

```
CORPUS GATE: PASS — 16/16 authoritative source documents present.
```

All 16 files, with freshly computed SHA-256 digests (not read from any manifest):

| # | Filename | Bytes | SHA-256 |
|---|---|---:|---|
| 1 | abstract.pdf | 119,394 | `4a83ab43744a41e46665e8df458719813476204a43b8a71951b92767f0fd5d25` |
| 2 | Amendment1/RFP 2026-026 - Appendix D2 - Rated Criteria Response REVISED.docx | 50,745 | `1edfeceefbd76957744d5da4a02b879a06028b103fba5acef6e2010f84372f64` |
| 3 | OriginalRevision/DP 2026-026 - Annexe F - Questionnaire ESG.xlsx | 28,985 | `8816b920bbc0dda66bc20e19dcebb8f25e413de7b3df1f90ab4f6ac222a1fd54` |
| 4 | OriginalRevision/RFP 2026-026 - Appendix A - Submission Form.docx | 48,269 | `4c03455236a93c7438e42267eedae6f18a95c34b79986d71f5049f4dfbd1c3e2` |
| 5 | OriginalRevision/RFP 2026-026 - Appendix B1 - Mandatory criteria.xlsx | 14,247 | `3d04e1d8cb3a91ae7bac52f2b1495fdc32c01148a4e68a09e60fca0e64ebbab6` |
| 6 | OriginalRevision/RFP 2026-026 - Appendix B2 - Mandatory criteria.xlsx | 13,999 | `11dd8111c3645e42288bf374a8c664205c5d7d6726fb7c1fe0abe5c4b473afbc` |
| 7 | OriginalRevision/RFP 2026-026 - Appendix B3 - Mandatory criteria.xlsx | 14,240 | `87a263293fc149a9c439274e9cd42d8b2990caa94f064c7d1251c7fc52f514d0` |
| 8 | OriginalRevision/RFP 2026-026 - Appendix C1 - Minimum qualification requirements.xlsx | 14,007 | `cdef962a4510aa76b0f05b08d046e8a4be06c0a9fb2fef0fa667727a78eb9438` |
| 9 | OriginalRevision/RFP 2026-026 - Appendix C2 - Minimum qualification requirements.xlsx | 14,104 | `c223bf290702b0efb701eee5d4ca6ba7574b92030671018af311c36345bfec24` |
| 10 | OriginalRevision/RFP 2026-026 - Appendix C3 - Minimum qualification requirement.xlsx | 13,965 | `d304c2ce0cb1a4a78af1785ffb08731294e9746fc29f7a2b84dc80ded7c06cca` |
| 11 | OriginalRevision/RFP 2026-026 - Appendix D1 - Rated criteria response form.docx | 58,679 | `0f0a7443f4aa601dcbc710b64eb40b3773d3e013c4451f9605d151daf8659fc5` |
| 12 | OriginalRevision/RFP 2026-026 - Appendix D2 - Rated Criteria Response Form.docx | 55,852 | `fe04b69ae9a5d73d250483ef85a403cfdd466cf502e265bb23e65b9384e517d9` |
| 13 | OriginalRevision/RFP 2026-026 - Appendix D3 - Rated Criteria Response Form.docx | 52,110 | `748973104e4233c6ae7ce63e9c8e8069e1453c1711557fc6803f992238723823` |
| 14 | OriginalRevision/RFP 2026-026 - Appendix E - Pricing Form.xlsx | 44,836 | `97bfc8832613c5756da05542d5cdb612d948b6ff7b9ab788a2bd7058b00d6d46` |
| 15 | OriginalRevision/RFP 2026-06 - Appendix G - Form of Agreement.docx | 67,727 | `3fedc955dd1e3473814a1d7dc9d577dc4b4a840961b7c2bfa8c9c4bfe0a28cbd` |
| **16** | **RFP 2026-026 - Talent, Learning and Organizational Development Services.pdf** | **376,615** | **`78d96ef927e19fa431c187f9287777b755bd80603f42734c69e0c2603f035ee4`** — **MASTER RFP** |

- Master RFP digest matches the authoritative identity exactly.
- 16 unique SHA-256 digests among 16 discovered files — no duplicate (the byte-identical Outlook-cache copy referenced in `corrected_corpus_manifest.json` lives outside this directory and was never scanned or counted).
- Solicitation number `2026-026` confirmed present across corpus filenames and, independently, inside the master RFP's own extracted text (`doc_metadata.file_number = "2026-026"`, "Request for Proposals No.: 2026-026" on page 1).
- The master RFP was passed through `adapt_procurement_corpus()`/`extract_document_facts()` identically to the other 15 files — same role-map dispatch (`MASTER_RFP` → `ArtifactKind.DOCUMENT`, a pre-existing role in `procurement_evidence_adapter.py`, not added for this run), same `extract_document_with_metadata()` call, same `extract_document_facts()` call. No Bank-of-Canada-specific or master-RFP-specific branch exists in the production code.

## C. Evidence boundary (Procurement Evidence Adapter → Evidence Publication)

```
EVIDENCE BOUNDARY: PASS
```

| Object class | Count |
|---|---:|
| `EVIDENCE_SOURCE` | 1 |
| `EVIDENCE_ARTIFACT` | 16 |
| `EVIDENCE_OCCURRENCE` | 68 |
| `EVIDENCE_EXTRACT` | 65 |
| **Total** | **150** |

Evidence Publication re-published all 150 objects with 150 governed references, and `validate_evidence_publication()` passed.

## D. Document parsing → evidence → Stage A: 16-document inventory

`page_count` is populated only for the two PDFs (PyMuPDF-based extraction); DOCX/XLSX carry `sections`/`tables_count`/`sheets` instead — these are the real, distinct metadata shapes each format's parser returns, not a missing value.

| # | Filename | Role | Page count | Parsed chars | Evidence occurrences | Evidence extracts | Stage A status | Stage A records | Warnings |
|---|---|---|---:|---:|---:|---:|---|---:|---|
| 1 | abstract.pdf | NOTICE_AND_DOCUMENT_INVENTORY | 6 | 7,733 | 6 | 6 | RECOVERED_TRUNCATED | 76 | yes |
| 2 | Amendment1/…Appendix D2 REVISED.docx | AMENDMENT | — | 5,323 | 1 | 1 | VERIFIED_ADEQUATE | 22 | — |
| 3 | OriginalRevision/…Annexe F ESG.xlsx | PROCUREMENT_ATTACHMENT | — | 2,077 | 1 | 1 | VERIFIED_ADEQUATE | 3 | — |
| 4 | OriginalRevision/…Appendix A Submission Form.docx | PROCUREMENT_ATTACHMENT | — | 6,505 | 17 | 14 | VERIFIED_ADEQUATE | 18 | — |
| 5 | OriginalRevision/…Appendix B1.xlsx | PROCUREMENT_ATTACHMENT | — | 1,161 | 1 | 1 | VERIFIED_ADEQUATE | 15 | — |
| 6 | OriginalRevision/…Appendix B2.xlsx | PROCUREMENT_ATTACHMENT | — | 757 | 1 | 1 | VERIFIED_ADEQUATE | 9 | — |
| 7 | OriginalRevision/…Appendix B3.xlsx | PROCUREMENT_ATTACHMENT | — | 1,144 | 1 | 1 | VERIFIED_ADEQUATE | 15 | — |
| 8 | OriginalRevision/…Appendix C1.xlsx | PROCUREMENT_ATTACHMENT | — | 962 | 1 | 1 | VERIFIED_ADEQUATE | 8 | — |
| 9 | OriginalRevision/…Appendix C2.xlsx | PROCUREMENT_ATTACHMENT | — | 1,108 | 1 | 1 | VERIFIED_ADEQUATE | 10 | — |
| 10 | OriginalRevision/…Appendix C3.xlsx | PROCUREMENT_ATTACHMENT | — | 865 | 1 | 1 | VERIFIED_ADEQUATE | 9 | — |
| 11 | OriginalRevision/…Appendix D1.docx | PROCUREMENT_ATTACHMENT | — | 6,159 | 1 | 1 | RECOVERED_TRUNCATED | 73 | yes |
| 12 | OriginalRevision/…Appendix D2.docx | PROCUREMENT_ATTACHMENT | — | 5,326 | 1 | 1 | VERIFIED_ADEQUATE | 23 | — |
| 13 | OriginalRevision/…Appendix D3.docx | PROCUREMENT_ATTACHMENT | — | 4,648 | 1 | 1 | VERIFIED_ADEQUATE | 24 | — |
| 14 | OriginalRevision/…Appendix E Pricing Form.xlsx | PROCUREMENT_ATTACHMENT | — | 18,457 | 9 | 9 | VERIFIED_ADEQUATE | 76 | — |
| 15 | OriginalRevision/…Appendix G Form of Agreement.docx | PROCUREMENT_ATTACHMENT | — | 32,452 | 4 | 4 | RECOVERED_TRUNCATED | 247 | yes |
| **16** | **RFP 2026-026 - Talent, Learning and Organizational Development Services.pdf** | **MASTER RFP** | **21** | **52,145** | **21** | **21** | RECOVERED_TRUNCATED | **288** | yes |
| | **TOTAL** | | **27** | **147,822** | **68** | **65** | | **916** | **4 documents** |

```
CORPUS CHECK: 16/16 INCLUDED
```

All 16 documents reached Stage A. Zero documents produced zero output. **STAGE A: PASS.**

## E. What Stage A actually produces (real production schema)

Stage A's real output is not a typed dataclass — it is the raw JSON dict `extract_document_facts()` returns, built from the exact schema specified in `STAGE_A_FACT_EXTRACTION_PROMPT` (`extractor.py`, lines 37–256) and lightly post-processed by `_extract_chunk_facts()`/`aggregate_stage_a_facts()`. Per document, the dict contains:

- **`doc_metadata`**: `title`, `client`, `file_number`, `submission_deadline`, `clarification_deadline`, `notes` — document-level identity fields, one per document.
- **`requirements[]`**: `req_id`, `category` (Mandatory/Rated/Financial/Supporting), `requirement_type` (controlled enum: Supplier Qualification / Technical Specification / Submission Compliance / Delivery-SLA / Commercial-Contractual / Evaluation-Scored / General Compliance), `description`, `rfso_ref`, `weight`, `evidence`, `source_refs[]`.
- **`dates[]`**: `milestone`, `date`, `source_doc`.
- **`evaluation_criteria[]`**: `stage`, `parent_stage`, `hierarchy_level`, `evaluation_role` (controlled enum), `weight`, `weight_unit`, `weight_basis`, `threshold`, `notes`, `source_refs[]`.
- **`submission_rules[]`**: `item`, `artifact_type` (controlled enum), `file_format`, `submission_channel`, `format`, `details`, `mandatory`, `source_refs[]`.
- **`deliverables[]`**: `title`, `description`, `obligation_state`, `quantity`, `unit`, `frequency` (controlled enum), `frequency_raw`, `scope{lot,phase,component,location}`, `due_milestone`, `acceptance_criteria`, `responsible_actor`, `conditions[]`, `source_refs[]`.
- **`commercial_clauses[]`**: `clause_kind` (large controlled enum), `topic`, `source_fact`, `conditions[]`, `scope{...}`, `linked_observation_ids[]`, `source_refs[]`.
- **`typed_observations[]`**: `family` (IDENTITY/MILESTONE/CONTRACT_TERM/MONETARY/PROCUREMENT_MECHANIC/DOCUMENT_ROLE), `semantic_kind`, `original_value`, `source_doc`, `source_refs[]`, `scope{...}`, plus family-specific fields (`date`,`amount`,`currency`,`duration`,`document_role`, …) and an optional `supersession{basis,target_family,target_semantic_kind,old_value,new_value,scope,source_refs}` block.
- **Provenance/evidence-reference field, present on every record type**: `source_refs[]` — each entry has `source_doc`, `page` (int or null), `sheet` (str or null), `section` (str or null), `excerpt` (verbatim quote). This is Stage A's evidence-linkage mechanism; there is no separate "confidence" field on individual facts (Stage A does not assign confidence — that is explicitly an Opportunity Intelligence/decision-layer concept, out of scope here).
- **Identity/revision/digest**: Stage A dict objects carry no independent object ID or digest of their own (they are pre-canonical, per-document JSON, not governed objects yet). The governed identity/digest layer exists one level down, in the Evidence objects (`object_id`, `object_digest` — see Section C) which the Stage A step does not touch.
- **Status/diagnostic fields** (top-level, one per document): `_parse_status` (chunk-level; `null` at the aggregate level once multiple chunks are merged), `_extraction_diagnostic: {status, recovery_attempts, has_recovered_truncation, note}` — the real, only diagnostic/validation signal Stage A exposes. Observed values in this run: `VERIFIED_ADEQUATE` (12 documents) and `RECOVERED_TRUNCATED` (4 documents, see Section I).

Complete per-document raw dumps: `stage_a_documents/01-*.json` … `16-*.json` (Section G).

## F. Representative Stage A records (one per populated category, for every document)

All records below are copied verbatim from the real Stage A output files in `stage_a_documents/`. Full JSON for every record is in those files.

### 1. abstract.pdf (NOTICE_AND_DOCUMENT_INVENTORY)
```json
{
  "req_id": "M1", "category": "Mandatory", "requirement_type": "Submission Compliance",
  "description": "Appendix A - Submission form must be completed and submitted",
  "rfso_ref": "Appendix A", "evidence": "Completed Appendix A submission form",
  "source_refs": [{"source_doc": "abstract.pdf", "page": 1, "section": "Bid Documents List - Envelope 1",
                    "sheet": null, "excerpt": "Appendix A - Submission form - Mandatory"}]
}
```
Typed observation: `{"family": "IDENTITY", "semantic_kind": "OPPORTUNITY_TITLE", "original_value": "RFP 2026-026 - Talent, Learning and Organizational Development Services", "source_refs": [{"page": 1, "section": "Notice", "excerpt": "Title - RFP 2026-026 - Talent, Learning and Organizational Development Services"}]}`

### 2. Amendment1/…Appendix D2 REVISED.docx (AMENDMENT)
```json
{
  "req_id": "R1", "category": "Rated", "requirement_type": "Submission Compliance",
  "description": "Responses must not exceed twelve (12) pages (excluding resumes or professional profiles, and work or product samples requested herein). Page size must be 8½ x 11 inches, with standard margins and a minimum font size of 10 points.",
  "rfso_ref": "Header / Instructions", "evidence": "Rated Criteria Response Form submission",
  "source_refs": [{"source_doc": "Amendment1/RFP 2026-026 - Appendix D2 - Rated Criteria Response REVISED.docx",
                    "page": null, "section": "Header",
                    "excerpt": "Responses must not exceed twelve (12) pages (excluding resumes or professional profiles, and work or product samples requested herein) Page size must be 8½ x 11 inches, with standard margins and a minimum font size of 10 points."}]
}
```

### 3. OriginalRevision/…Annexe F ESG.xlsx (PROCUREMENT_ATTACHMENT)
```json
{
  "req_id": "S1", "category": "Supporting", "requirement_type": "Submission Compliance",
  "description": "Respond to ESG questionnaire section with yes/no answers to questions on Indigenous enterprise status, accessibility strategy, and environmental/sustainability practices.",
  "rfso_ref": "Annexe F, ESG Sheet, Rows 2-17",
  "source_refs": [{"sheet": "ESG", "page": null, "section": null,
                    "excerpt": "Les réponses à cette section sont fournies à des fins de collecte de renseignements seulement et ne seront pas utilisées pour évaluer la proposition..."}]
}
```

### 4. OriginalRevision/…Appendix A Submission Form.docx (PROCUREMENT_ATTACHMENT)
```json
{
  "req_id": "M1", "category": "Mandatory", "requirement_type": "Submission Compliance",
  "description": "Proponent must acknowledge that the RFP process is governed by the Terms of Reference set out in the RFP, and that the procurement process does not constitute a legally binding bidding process...",
  "rfso_ref": "Section 2. Acknowledgement of Terms of Reference",
  "source_refs": [{"section": "2. Acknowledgement of Terms of Reference", "page": null, "sheet": null,
                    "excerpt": "The proponent acknowledges that this RFP process will be governed by the specific Terms of Reference set out in this RFP..."}]
}
```

### 5–7. Appendix B1/B2/B3 - Mandatory criteria.xlsx (PROCUREMENT_ATTACHMENT)
Identical bilingualism mandatory-criterion pattern, one per service category:
```json
{
  "req_id": "M1", "category": "Mandatory", "requirement_type": "Submission Compliance",
  "description": "Each proposal must provide written confirmation of the ability to provide all services, materials and solutions in both English and French.",
  "rfso_ref": "Appendix B1, Mandatory Criteria (a) - Bilingualism",
  "source_refs": [{"sheet": "Mandatory Criteria", "page": null, "section": null,
                    "excerpt": "Each proposal must provide written confirmation of the ability to provide all services, materials and solutions in both English and French."}]
}
```

### 8–10. Appendix C1/C2/C3 - Minimum qualification requirements.xlsx (PROCUREMENT_ATTACHMENT)
```json
{
  "req_id": "M1", "category": "Mandatory", "requirement_type": "Supplier Qualification",
  "description": "Proponent must confirm that it is an established firm and has delivered at least three (3) organization-wide learning and development engagements of similar scope and complexity within the last five (5) years for organizations with a minimum of 1,000 employees.",
  "rfso_ref": "Appendix C1, Row 4",
  "source_refs": [{"sheet": "Minimum qualification", "page": null, "section": null,
                    "excerpt": "Organizational Experience (Minimum Five (5) Years) Proponent must confirm that it is an established firm..."}]
}
```

### 11–13. Appendix D1/D2/D3 - Rated criteria response forms (PROCUREMENT_ATTACHMENT)
```json
{
  "req_id": "R1", "category": "Rated", "requirement_type": "Submission Compliance",
  "description": "Responses must not exceed 15 pages (excluding resumes or professional profiles, and work or product samples requested herein).",
  "rfso_ref": "Header / Instructions",
  "source_refs": [{"section": "Header", "page": null, "sheet": null,
                    "excerpt": "Responses must not exceed 15 pages (excluding resumes or professional profiles, and work or product samples requested herein)."}]
}
```

### 14. OriginalRevision/…Appendix E Pricing Form.xlsx (PROCUREMENT_ATTACHMENT)
```json
{
  "title": "Workforce Planning Assessment", "obligation_state": "MANDATORY", "quantity": "1", "unit": "document",
  "responsible_actor": "SUPPLIER", "due_milestone": "Within 12-week engagement period",
  "description": "A comprehensive assessment document summarizing key findings, risks, opportunities, and observations from the discovery and assessment phase, including review of up to twenty (20) Bank documents, workforce datasets, and fifteen (15) stakeholder interviews.",
  "acceptance_criteria": "Document must summarize key findings, risks, opportunities, and observations from discovery and assessment activities",
  "source_refs": [{"sheet": "HR Advisory pricing scenario", "page": null, "section": null,
                    "excerpt": "Develop a workforce planning assessment summarizing key findings, risks, opportunities, and observations."}]
}
```

### 15. OriginalRevision/…Appendix G Form of Agreement.docx (PROCUREMENT_ATTACHMENT)
```json
{
  "clause_kind": "INTELLECTUAL_PROPERTY", "topic": "Assignment of Copyright and Intellectual Property Rights",
  "source_fact": "The Service Provider assigns and transfers to the Bank the worldwide copyright and all other intellectual property rights in and to any material produced or developed for the Bank in the performance of the Services. The Service Provider waives or obtains waiver of all moral rights in such material.",
  "conditions": ["Assignment applies to all material produced or developed for the Bank in performance of Services",
                 "Service Provider must waive or obtain waiver of moral rights as applicable"],
  "source_refs": [{"section": "Property Rights", "page": null, "sheet": null,
                    "excerpt": "The Service Provider hereby assigns and transfers to the Bank the worldwide copyright and all other intellectual property rights..."}]
}
```

### 16. MASTER RFP — see the dedicated Section G below.

Complete per-document per-category samples (every populated category, all 16 documents): `_representative_samples.json`.

## G. Master RFP dedicated section

| Metric | Value |
|---|---|
| Parsed character count (this run) | **52,145** |
| Historical corrected-run comparison | 52,145 (`CORRECTED_CORPUS_REGENERATION_REPORT.md`: "master produced 52,145 extracted characters") — **exact match** |
| Stage A status | `RECOVERED_TRUNCATED` (`has_recovered_truncation: true`, `recovery_attempts: 0`) |
| Stage A record count | 288 |
| Percentage of total Stage A output (288 / 916) | **31.4%** |
| Evidence occurrences | 21 (one per PDF page) |
| Evidence extracts | 21 (one per occurrence — 1:1, no gap) |
| Pages with a Stage A evidence occurrence+extract | all 21 (1–21) |
| Pages with at least one Stage A **record** citing them via `source_refs[].page` | 20 of 21 — pages 1, 3–21 |
| Page with zero Stage A records | **page 2** |
| Record categories present | requirements (107), dates (11), evaluation_criteria (55), submission_rules (32), deliverables (6), commercial_clauses (20), typed_observations (57) |
| Validation warnings | `RECOVERED_TRUNCATED` (see Section I) |

**Page 2 finding.** Page 2's own extracted evidence content (`content` field of its `EvidenceExtract`) is the RFP's **Table of Contents** — a list of section titles and page numbers with no independent procurement facts of its own (verified directly from the extract's real content, first 300 characters: `"TABLE OF CONTENTS \n1. INTRODUCTION AND SUBMISSION INSTRUCTIONS ... 1 \n1.1 Invitation ... 1 \n1.2 RFP timetable ... 2 \n1.3 Submission instructions ... 2 ..."`). Zero Stage A records citing page 2 is consistent with a table of contents producing no extractable procurement facts. This is an observation about the page's actual content, not an inference about *why* the model behaved a certain way.

**Was the master RFP merely processed or was its substantive content actually extracted?** The record evidence indicates substantive extraction, not pass-through: 288 real records were produced, spanning 7 of 7 Stage A categories, citing 12 distinct pages (1, 3–21 excluding 2) with page-anchored `source_refs`, and including facts that only exist in the master RFP's own governing text (submission deadline, MERX portal mechanics, five-stage evaluation process, confidentiality/IP/subcontracting clauses, indicative demand volumes) rather than facts merely re-derived from the smaller appendices.

Representative master-RFP records spanning multiple pages (complete set of samples across all 7 categories: `_master_rfp_samples.json`):

```json
// page 4 — requirement
{"req_id": "M1", "category": "Mandatory", "requirement_type": "Submission Compliance",
 "description": "Proponents must submit proposals electronically through the MERX Canadian public tenders electronic bidding system. Submissions by other methods will not be accepted.",
 "source_refs": [{"page": 4, "section": "1.3 Submission instructions",
                   "excerpt": "Proponents must submit their proposals electronically through the MERX Canadian public tenders electronic bidding system accessible at https://www.merx.com/ (MERX). Submissions by other methods will not be accepted."}]}

// page 9 — evaluation_criteria
{"stage": "Stage 1. Mandatory submission requirements", "evaluation_role": "Qualification / Gate",
 "notes": "Review to determine compliance with all mandatory submission requirements. Proponents may be issued a rectification notice to cure deficiencies within a rectification period.",
 "source_refs": [{"page": 9, "section": "3.1 Evaluation of proposals, Stage 1",
                   "excerpt": "Stage 1 will consist of a review to determine which proposals comply with all the mandatory submission requirements..."}]}

// page 12 — deliverable
{"title": "Custom Workshops (Category 1)", "obligation_state": "CONDITIONAL", "quantity": "10", "unit": "workshops",
 "frequency": "AS_REQUESTED", "responsible_actor": "SUPPLIER",
 "scope": {"lot": "Category 1: Learning & Development Programs and Assessments"},
 "source_refs": [{"page": 12, "section": "4.1 Category 1: Learning & Development Programs and Assessments",
                   "excerpt": "The Bank anticipates a requirement for up to 10 custom workshops and one possible larger scale curriculum design and delivery over the term of the agreement."}]}

// page 8 — commercial clause
{"clause_kind": "CONFIDENTIALITY", "topic": "RFP Process Confidentiality and Information Protection",
 "source_fact": "The RFP process is confidential in nature. All information provided by or obtained from the Bank of Canada in any form in connection with the RFP is the sole property of the Bank of Canada and must be treated as confidential.",
 "source_refs": [{"page": 8, "excerpt": "the RFP process is confidential in nature..."}]}

// page 1 — typed observation (identity)
{"family": "IDENTITY", "semantic_kind": "SOLICITATION_NUMBER", "original_value": "2026-026",
 "source_refs": [{"page": 1, "excerpt": "Request for Proposals No.: 2026-026"}]}
```

## H. Explanation: 68 evidence occurrences vs. 65 extracts

Three `EvidenceOccurrence` objects have no corresponding `EvidenceExtract`. All three come from one document:

| Occurrence ID | Source document | Locator kind | Locator |
|---|---|---|---|
| `eocc-77049a29dd1b691c88091d5b80a4a2abcaa7ac61659d6f671b5995de6e3a81e4` | OriginalRevision/RFP 2026-026 - Appendix A - Submission Form.docx | SECTION | `section:Header` |
| `eocc-c572b484ba3bc5c08e3a3515790cd584cbebf0bc34e5e224b51e0e707a2dae79` | OriginalRevision/RFP 2026-026 - Appendix A - Submission Form.docx | SECTION | `section:APPENDIX A. SUBMISSION FORM` |
| `eocc-f84d293fa3e3bb68a3cf2be04e669bf2ebe9525fad1d19b93eeb5a190a761bc4` | OriginalRevision/RFP 2026-026 - Appendix A - Submission Form.docx | SECTION | `section:1.\tProponent information` |

**Reason, read directly from `procurement_evidence_adapter.py`'s `_fragments()` function (lines 103–118):** an `EvidenceOccurrence` is created for every `[[SOURCE: ...]]` marker found in a document's extracted text; an `EvidenceExtract` is created only `if content is not None` — and `content` is set to `None` precisely when the text between that marker and the next marker, after stripping, is empty (`content or None`). All three occurrences above are `SECTION` (heading) markers in the DOCX parser's output (`extract_docx_with_metadata`, which emits a `[[SOURCE: ... | SECTION: <heading>]]` marker immediately before each heading, then the following paragraph text). These three headings ("Header", "APPENDIX A. SUBMISSION FORM", "1. Proponent information") are each immediately followed by another marker with no body paragraph text in between — a real, verifiable structural fact of this DOCX's heading layout, not an inferred explanation.

**Is this expected production behavior or an anomaly?** Expected. `_fragments()`'s `content or None` branch is deliberate, existing code — the adapter always registers the *location* of a marker as an occurrence (so nothing is silently dropped from provenance) but only manufactures an extract when there is actual bounded text to quote. Not a defect in this run.

## I. Coverage / anomaly analysis

| Anomaly type | Found in this run | Detail |
|---|---|---|
| Zero-output document | **None** — `zero_output_documents: []` in `phase1_validation_anomalies.json` | All 16 documents produced ≥ 3 Stage A records |
| Documents with `_extraction_diagnostic.status != VERIFIED_ADEQUATE` | **4 of 16** | abstract.pdf, Appendix D1, Appendix G, Master RFP — all `RECOVERED_TRUNCATED` |
| Parse failures (`_extraction_diagnostic.status == PARSE_FAILURE`) | None | — |
| `SUSPICIOUS_UNDER_COVERAGE` diagnostic | None | — |
| Pages with evidence but zero Stage A records | 1 — Master RFP page 2 (Table of Contents; see Section G) | — |
| Occurrences with no extract | 3 (see Section H) — expected behavior, not an anomaly | — |
| Dangling evidence references | None — `validate_evidence_publication()` passed; `create_evidence_snapshot()`'s own provenance checks (every relationship target inside the snapshot, every artifact/occurrence/extract's parent chain intact) passed with no exception raised | — |
| Duplicate identities | None — `create_evidence_snapshot()` raises `DUPLICATE_IDENTITY` on any collision; no exception was raised | — |
| Malformed objects / rejected records | None observed — the Stage A JSON schema validator (`_safe_parse_json_with_status`) reported `_parse_status` per chunk; no chunk was reported as unrecoverable `FAILED` after the built-in bounded retry | — |
| Truncated input / LLM truncation-recovery events | 4 documents entered the bounded truncation-recovery path (`RECOVERED_TRUNCATED`); the code's own retry logic (chunk re-split, retry, and merge — `extractor.py` lines ~2818–2896) ran and completed without raising, but the resulting diagnostic still flags the document as recovered-not-verified rather than clean | — |
| Records rejected by validators | None distinct from the above — `_extraction_diagnostic` is the only validator this boundary exposes | — |
| Unexpectedly low-output documents | Appendix B2.xlsx (9 records) and Appendix C1.xlsx (8 records) are the two lowest of the 16, but both are consistent with their genuinely small source content (757 and 962 parsed characters respectively — the smallest two documents in the corpus by character count) | Not flagged as anomalous — output count tracks source size |

**No recoverable warning has been suppressed.** The 4 `RECOVERED_TRUNCATED` documents (abstract.pdf, Appendix D1, Appendix G, and the master RFP) are exactly the 4 documents whose Stage A JSON responses required this run's bounded-retry recovery path at least once; this is visible, unaltered, in each document's own `stage_a_documents/*.json` `_extraction_diagnostic` field.

## J. Complete raw artifacts (this fresh run only)

All paths below are relative to the repository root, under:
`evaluation/bank_of_canada_briefing_pack/phase1_commissioning/phase1-boc-2026-026-corrected16-20260912T080929Z-9fd9e5/`

| File | Type | Producer | Notes |
|---|---|---|---|
| `phase1_source_manifest.json` | JSON | this run | Freshly computed 16-file manifest (path, bytes, sha256, role) |
| `run_metadata.json` | JSON | this run | Run identity, model, cache-bypass measures |
| `boundaries.json` | JSON | this run | Full boundary-by-boundary PASS/FAIL log with timings |
| `completion.json` | JSON | this run | Final PASS status + elapsed time |
| `phase1_document_parsing.json` | JSON | this run | Per-document parse metadata (page_count/sections/tables/sheets, character counts, head/tail excerpts) |
| `master_rfp_extracted_text.txt` | Plain text | this run | Full 52,145-character parsed text of the master RFP, verbatim, with `[[SOURCE: ... | PAGE: N]]` markers intact |
| `phase1_evidence_snapshot.json` | JSON | `EvidenceSnapshot.to_dict()` (production serializer, `evidence.py`) | All 150 Evidence objects + manifest (object_class/object_id/object_digest per object) |
| `phase1_evidence_publication.json` | JSON | `EvidencePublication.to_dict()` (production serializer, `evidence_publication.py`) | Governed snapshot + manifest + 150 references |
| `phase1_stage_a_document_facts.json` | JSON | this run | All 16 raw Stage A dicts, list-aligned to corpus order |
| `phase1_stage_a_report.json` | JSON | this run | Per-document Stage A status/record-count summary |
| `phase1_validation_anomalies.json` | JSON | this run | The 4 `RECOVERED_TRUNCATED` documents; empty zero-output list |
| `stage_a_documents/01-abstract.pdf.json` … `16-RFP_2026-026_..._Services.pdf.json` | JSON, 16 files | this run | Individual per-document raw Stage A output, complete and non-truncated |
| `_derived_evidence_analysis.json` | JSON | derived (this report's preparation) | Per-document occurrence/extract counts, the 3 unmatched occurrences, master-RFP page coverage — computed directly from `phase1_evidence_snapshot.json`, no new data |
| `_representative_samples.json` | JSON | derived | One record per populated category, all 16 documents |
| `_master_rfp_samples.json` | JSON | derived | Up to 3 page-diverse records per category, master RFP only |

Historical (different run, different tool, **not** part of this fresh commissioning — referenced for comparison only, not reused as input): `evaluation/bank_of_canada_briefing_pack/corrected_pipeline/*`, `CORRECTED_CORPUS_REGENERATION_REPORT.md`.

## K. Historical comparison (informational only — not used to influence this run)

| Metric | Historical corrected run (`CORRECTED_CORPUS_REGENERATION_REPORT.md`) | This fresh commissioning run |
|---|---:|---:|
| Documents | 16 | 16 |
| Master RFP parsed characters | 52,145 | 52,145 (exact match) |
| Stage A document extractions | 16 | 16 |
| Stage A structurally comparable beyond document count | Not reported per-record in the historical report (only downstream Stage B totals: 413 normalized requirements) | 916 raw per-document Stage A records (pre-normalization/pre-deduplication — **not** comparable to the historical 413, since that figure is a Stage B output and this run stops before Stage B) |

No Stage B/C/D was run for either side of this comparison in this exercise. The two runs used different code entry points (this run: `scripts/commission_phase1_bank_of_canada.py`, direct production functions; historical run: `evaluation/bank_of_canada_briefing_pack/run_corrected_evaluation.py`, a separate evaluation harness) — both call the same underlying `extract_document_facts`/`adapt_procurement_corpus` production functions, but the harnesses around them differ, so exact record-for-record identity between the two runs is not asserted or expected (temperature 0 makes the model deterministic given identical chunk input, but chunking boundaries, retry paths, and any harness-side pre/post-processing can differ).
