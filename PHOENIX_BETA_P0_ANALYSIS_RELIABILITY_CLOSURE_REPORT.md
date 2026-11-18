# Phoenix Beta P0 — Core Analysis Reliability: Closure Report

| | |
|---|---|
| Status | **CLOSED** (2026-11-18) |
| Incident | FAST and FULL produced incorrect, incomplete and poorly classified procurement intelligence on real Phoenix RFPs (8-page LAU RFP, 189-page 2B OPCO ITB) |
| Branch | `feature/super-admin-mvp` (not merged to `main`) |
| Final commit | `ee003db` (preceded by `e6259a8`, `6632910`) |
| Deployed image | `emg/bid-intelligence:phoenix-beta-p0-facts-4` as `bid-intelligence-beta` (Phoenix Beta only) |
| Rollback | container `bid-intelligence-beta-prev-p0-facts-3` (image `phoenix-beta-p0-facts-3`, commit `6632910`); source backup `source.6632910-built` |
| Model | unchanged: `claude-haiku-4-5-20251001` |

This is a historical operational record. Current behaviour is summarised in
`docs/current/SYSTEM_STATE.md` ("Phoenix Beta FAST/FULL reporting baseline").

## Root causes

1. **Keyword-driven report assembly.** The Snapshot and Assessment assigned meaning (location, synopsis, deliverables, qualifications, submission method, guarantees …) by keyword/regex classification over extracted text. That bypassed most of what the model actually understood. It produced, for example, a contact email reported as the submission method, an address reported as the delivery location, guarantees listed as qualifications, table-of-contents text used as the synopsis, and invented evaluation weights.
2. **Evidence validation checked text overlap, not meaning.** A statement passed if its words occurred in the source. Changed numbers, dropped negations, conditions, alternatives and qualifiers were not detected.
3. **FULL specialists lacked verified procurement context.** They worked from coarse canonical objects. As a result they reported "missing" information that the documents state and contradicted verified facts.
4. **FULL specialist findings did not reach the Assessment PDF.** The Assessment re-presented FAST facts and added no specialist intelligence.

## Corrections

| Correction | Where | Commit |
|---|---|---|
| AI extraction of source-supported, meaning-classified procurement facts. Each fact is classified into a defined category (e.g. submission method ≠ contact, delivery location ≠ buyer address, guarantee ≠ qualification, proposal content ≠ deliverable) and carries verbatim quotes and pages. It runs alongside FAST and is stored additively in the snapshot (schema 1.4, `report_facts`). | `procurement_facts.py`, `analysis_service.py`, `fast_analysis.py` | `e6259a8` |
| Deterministic verification at report time. Quotes are matched as ordered token sequences, so a changed figure fails. Statements must keep the quote's numbers, emails and qualifiers; negations, conditions, exceptions and alternatives cannot be reversed or dropped. | `procurement_facts.py` | `e6259a8`, `6632910` |
| Reports built from verified facts ("facts" mode). Bids without facts keep the earlier "digest" rendering byte-for-byte. | `phoenix_reports.py` | `e6259a8` |
| Relevant verified facts supplied to the FULL specialists (conditional contract additions; the FULL input fingerprint changes only for runs with facts — an accepted change). | `full_analysis.py` and related | `6632910` |
| Verified specialist findings in the Assessment ("Specialist Analysis", labelled as analysis, not as document statements). Findings are withheld when they are ungrounded, contradict a verified fact, repeat facts, or overstate their cited evidence. Overstatement covers: added or firmed-up consequences, approximations made exact, absolutes, possibilities stated as requirements, and added negations. Withheld counts are disclosed. | `procurement_facts.py`, `phoenix_reports.py` | `6632910`, `ee003db` |
| Report structure and pagination: the closing notes never sit alone on a final page. | `phoenix_reports.py` | `ee003db` |

All corrections are general-purpose. There are no buyer-, title- or document-specific rules and no fixed answers.

## Validation

### Independently re-verified at closure (2026-11-18, read-only)

- Repository: branch `feature/super-admin-mvp`; HEAD `ee003db` = `origin/feature/super-admin-mvp`; no uncommitted tracked changes.
- Deployment: `bid-intelligence-beta` runs `phoenix-beta-p0-facts-4`. `/app/.deployed_commit` is `ee003db`, and the deployed `procurement_facts.py` / `phoenix_reports.py` hashes equal the committed files. Restart policy `unless-stopped`; port `127.0.0.1:8502`; health `200`; no tracebacks in the container log. The admin container is untouched.
- Rollback: container `bid-intelligence-beta-prev-p0-facts-3` and its image are present (stopped).
- Records: bids 19–24 are present. All analysis runs 20–30 are `COMPLETE`. The original 2B OPCO FAST runs 21/22 keep their 18 Nov 10:55/10:57 completion times. This work wrote nothing to the database.
- In-app FAST → FULL on LAU: bid 24, FAST run 28 then FULL run 29, both `COMPLETE` through the Beta app. Run 28 holds 79 report facts, all verified, no coverage gaps; run 29 holds 63 specialist findings with the facts contract.

### Previously reported (during the incident work, not repeated at closure)

- **Rendered PDFs from runs 28/29**, using code identical to `ee003db` and reading the database without writing: the Snapshot is 3 pages and the Assessment 7.
  - Delivery location and both permitted submission methods (email and hard copy) are correct.
  - Award alternatives are kept and no weights are invented.
  - The four reviewer-reported specialist overstatements no longer appear ("automatic disqualification", "unlimited revisions", "strictly capped at 20 minutes", "price alone").
  - 16 verified specialist points add information beyond FAST, such as payment timing, the post-submission change prohibition, password handling and multi-award discretion.
  - The last page carries content.
- **Independent review of the LAU FAST and core FULL sections:** "materially accurate". The four specialist overstatements it found are corrected in `ee003db`.
- **Regression checks:**
  - focused tests `tests/test_procurement_facts.py`: 50 passed;
  - full suite (excluding live smoke tests): 4,007 passed, 27 skipped, 6 failed — the six existing freeze-check failures (`test_check2b_durable_runs` ×3, `test_check2c_assurance_workspace` ×1, `test_check2d_assurance_report` ×2), unchanged by this work;
  - digest-mode reports byte-identical to the pre-change baseline;
  - 2B OPCO, Arabic and synthetic saved-result replays render without errors.
- **Paid model usage** for the whole incident: ≈ $1.35 (Haiku 4.5). There were no paid runs at closure.

### Observed, not validated

- FULL run 30 on bid 21 (2B OPCO) was started in the app by a Phoenix user at 21:21 on the previous image (`p0-facts-3`). It completed; its output was not reviewed as part of this closure.

## Closure criteria

| # | Criterion | Result |
|---|---|---|
| 1 | Identified defects corrected | Met — root causes 1–4 each addressed (see Corrections) |
| 2 | FAST and FULL materially accurate and source-supported on LAU | Met — independent review plus re-rendered run 28/29 PDFs |
| 3 | FULL adds specialist intelligence beyond FAST | Met — 16 verified specialist points in the in-app Assessment |
| 4 | Actual Beta FAST → FULL completed | Met — runs 28 → 29 |
| 5 | No known material factual errors in validated LAU outputs | Met — the four reported overstatements are removed; nothing else is known |
| 6 | Healthy deployment with rollback | Met — verified at closure |
| 7 | Client records and history preserved | Met — verified at closure |

## Residual limitations (non-blocking)

- Rule-based semantic checks cannot guarantee that every misinterpretation is detected.
- Conservative validation withholds some legitimate specialist findings. The withheld count is shown in the report.
- Model output varies between runs. For example, an award alternative was captured in one probe and omitted in another.
- Bids analysed before the deployment keep their earlier (digest-mode) reports until explicitly re-analysed. Nothing is re-analysed automatically.
- Generalisation across unfamiliar RFPs needs continued real-world validation. 2B OPCO served only as a secondary check, and about 10% of statements fall back to verbatim source text.
- The facts pass adds roughly 60–85 s and about $0.05 to FAST on an 8-page RFP; it runs in parallel with the engine.

Phoenix Beta returns to controlled validation on this baseline. No `main` merge and no operational deployment were made.
