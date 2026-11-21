# Bid Intelligence — Testable Specification (SPEC.md)

*Governed by `CONSTRAINTS.md`. If any conflict arises, `CONSTRAINTS.md` takes precedence.*

## 1. Core Workflow (Current Build Scope)
Bid Intelligence operates as an **Evidence & Misalignment Engine** across four bounded steps:
1. **Ingest RFP (`UNDERSTAND`):** Parse raw RFP/tender documents into canonical, source-anchored requirements, deadlines, eligibility gates, and buyer conditions. Ambiguities are logged as clarification questions—never fabricated into facts.
2. **Upload Human Proposal (`BUILD` / `CHECK`):** Accept user-uploaded, human-authored proposal drafts (PDF/DOCX) and index them into a bounded ledger with page/section citations.
3. **Compare & Surface Misalignments (`CHECK`):** Cross-check the uploaded proposal ledger against canonical RFP requirements within the hard call and spend ceilings.
4. **Export & Log Outcome (`SUBMIT`):** Generate a deterministic Misalignment Report (zero provider calls during export) and passively capture final tender outcome fields (`outcome`: Won/Lost/No-Bid, `outcome_date`, `debrief_notes`).

## 2. Misalignment Output Contract
Every finding surfaced in a Misalignment Report MUST be classified into one of four types and contain all six mandatory fields. **No numeric scores, grades, or win-probability percentages may appear anywhere.**

- **Allowed Types:** `OMISSION` (required by RFP, missing in proposal) | `CONTRADICTION` (proposal conflicts with RFP constraint) | `SCOPE_MISMATCH` (partial or misaligned deliverable/condition) | `UNSUPPORTED_CLAIM` (proposal makes a claim lacking required evidence).
- **Mandatory Fields per Finding:**
  1. `misalignment_type` (one of the 4 allowed types)
  2. `rfp_quote` (exact verbatim substring from the RFP)
  3. `rfp_location` (filename + page/section)
  4. `proposal_quote` (exact verbatim substring from the proposal, or `NOT_FOUND` for omissions)
  5. `proposal_location` (filename + page/section, or `N/A`)
  6. `factual_gap` (1–2 sentence objective statement of the mismatch; zero rewritten proposal prose)

## 3. Black-Box Acceptance Criteria (Golden Benchmark)
A build is **DONE** only when it passes **all 6 checks** on a real RFP + real human proposal pair (never synthetic fixtures):

| # | Check | Pass Condition |
|---|---|---|
| 1 | **Real-Gap Recall** | Surfaces the known critical omissions, deadlines, and compliance traps present in the benchmark pair. |
| 2 | **Verbatim Grounding** | 100% of `rfp_quote` and non-empty `proposal_quote` strings exist verbatim in the source documents. Zero hallucinated clauses. |
| 3 | **Zero Scoring / Zero Writing** | Output contains 0 numeric scores, 0 win-probability ratings, and 0 AI-generated proposal rewrites. |
| 4 | **Spend & Call Compliance** | Total API spend is strictly under `$2.0`; CHECK adjudication stays at or below 12 calls with 0 retries. |
| 5 | **Export Integrity** | Export makes 0 provider calls; PARTIAL runs explicitly disclose incomplete batches; FAILED/RUNNING/QUEUED runs are blocked from export. |
| 6 | **Regression Safety** | Protected historical runs (including Bid 1522) and tenant isolation remain completely untouched. |

## 4. Explicitly Out of Scope (Do Not Build Yet)
- AI proposal drafting, rewriting, or narrative generation.
- Predictive win/loss scoring or readiness dashboards.
- Phase 2 Organizational Memory retrieval/ML layers (capture the 3 passive outcome fields only until explicitly authorized).