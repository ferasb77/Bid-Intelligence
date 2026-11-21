# Bid Intelligence — Constraints

## 1. Non-Negotiable Prohibitions (Never Do)
- Never generate, draft, or rewrite proposal narrative; proposal authoring is strictly a human activity.
- Never output a numeric score, grade, readiness rating, or win-probability percentage.
- Never let AI-derived analysis write to or silently repair canonical procurement truth.
- Never mix raw evidence, canonical procurement truth, and AI-derived intelligence.
- Never hardcode client names, RFP-specific filenames, or fixed category structures (e.g., Bank of Canada, York, LAU).
- Never mutate Bid 1522 (York University P27-070), its runs, or governed revisions.
- Never alter protected historical runs, raw snapshots, or historical exports.
- Never treat a synthetic fixture as commissioning or acceptance evidence.
- Never bypass organization/tenant isolation in queries or mutations.
- Never send the raw proposal or full registry to package-level CHECK reasoning; use the bounded ledger only.
- Never execute database DDL as an agent or rewrite a numbered migration.
- Never merge `main` or deploy to production without explicit task authorization.

## 2. Spend & Execution Caps
- Hard API-dollar ceiling per run: `$2.0` (must fail before provider calls if projected spend exceeds cap).
- CHECK model-adjudication target: 10 calls; hard ceiling: 12 calls (must fail before any provider call if exceeded).
- CHECK model adjudication permits 1 call per batch and 0 retries.
- CHECK retrieval is bounded to 70 items per object and 110 items per batch.
- Remediation/retry limit outside CHECK: **Max 2 attempts per task or bug.** If a fix fails twice, halt immediately and escalate to the human owner.

## 3. Verified Stack & Operational Boundaries
- Product identity: **Evidence & Misalignment Engine** — compares user-uploaded human proposals against RFP requirements to surface verbatim-grounded misalignments, omissions, and contradictions.
- Product lifecycle: `UNDERSTAND → DECIDE → BUILD → CHECK → SUBMIT`.
- UI stages are Streamlit pages under `pages/stage_*.py`.
- `tenancy.py` and `database.py` enforce the authentication and persistence boundary.
- Database migrations live in `migrations/` and are applied manually via the Supabase dashboard; a file in `migrations/` is not evidence it is live.
- Full Analysis is the sole customer-facing opportunity-analysis path; Fast Analysis is advisory only and never writes canonical procurement truth.
- Future win/loss intelligence must rely strictly on recorded historical tender outcomes and organizational memory—never synthetic predictive scoring. Do not build Phase 2 organizational-memory retrieval or ML layers unless explicitly authorized.

## 4. Human Approval Gates
Explicit human sign-off is required before any agent may:
- Add new dependencies or external services.
- Change system architecture, data schemas, or add/remove pipeline layers.
- Apply a database migration or perform any destructive database/stored-data operation.
- Merge to `main` or deploy to production.

## 5. Definition of Done
- Any change affecting extraction, comparison, or reporting must be verified against at least one **real RFP** (and real uploaded proposal where applicable) for business accuracy—passing unit tests alone is not Done.
- Customer-facing Briefs are deterministic, use completed analysis plus governed facts, and make zero provider calls during export.
- A COMPLETE CHECK run requires complete run integrity, every planned batch COMPLETE, and recorded batch count matching the plan.
- PARTIAL CHECK exports must disclose non-complete batches; FAILED, RUNNING, and QUEUED runs are never exportable.
- Source ambiguities remain clarification questions and are never fabricated into procurement facts.
- Completed outputs retain verbatim source provenance and keep advisory intelligence visibly separate from procurement facts.

## 6. Multi-Agent Governance & Audit Rules
- **Least-Privileged Access:** Only `BI Builder` has write access to the repository. `The Constraint Red-Teamer` and `Output Grader` are strictly read-only (0 file edits, 0 commits).
- **Independent Audit Required:** `BI Builder` is strictly prohibited from auditing, reviewing, or approving its own diffs.
- **No Substitute Auditor:** If `The Constraint Red-Teamer` fails, times out, or is unavailable, leave the issue in `WAITING` for human resolution. Never reassign an audit to the implementer.
- **Honest Assessment:** Auditors must report `NOT ASSESSED` (never `PASS`) for any check that was not directly tested or inspected.
- **Human-Only Closure:** Agents must halt at `In Review` and never auto-transition an issue to `Done` or auto-reassign failed tickets.