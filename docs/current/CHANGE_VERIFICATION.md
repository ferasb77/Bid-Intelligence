# Change Verification Runbook

This document defines the risk-tiered change verification framework for the
Bid Intelligence repository, aligned with **AI Engineering Canon v1.1**
(Verification Pyramid, Section 7).

Reference this runbook; do not copy repetitive verification instructions into task prompts.

## 1. Before work

- **Deterministic preflight**: Always run `python scripts/agent_context.py` at task start.
  It reports branch, HEAD, working-tree status, migration head, and key entry points with
  zero model calls.
- **Inspect working tree**: `git status --short`. If untracked or uncommitted work exists
  that was not created by your task, leave it alone. Never use `git reset --hard` or
  `git clean -fd` over pre-existing files without explicit human authorization.

## 2. Risk-tiered verification framework

Rather than running the full monolithic test suite (~4.5 minutes, 3,954 tests) for every
minor adjustment, select the verification tier corresponding to the highest risk touched:

### Tier 1: Low Risk
- **Qualifying Changes**: Documentation, prompt templates, comments, UI copy, isolated formatting changes, leaf helper functions with no side effects.
- **Verification Protocol**:
  1. `python -m py_compile <touched .py files>`
  2. `git diff --check`
  3. Targeted unit tests (e.g., `python -m pytest tests/test_leaf.py -q`).
- **Standard**: Fast iteration loop (sub-5 seconds). Do NOT run the full regression suite.

### Tier 2: Medium Risk
- **Qualifying Changes**: Synthesis logic, data extraction transformers, report generation, schema serialization adapters, business rules.
- **Verification Protocol**:
  1. `python -m py_compile <touched .py files>`
  2. `git diff --check`
  3. **Acceptance Triad Tests**:
     - **Positive**: Valid inputs produce expected structured models and outputs.
     - **Negative**: Missing, null, or malformed inputs degrade gracefully without unhandled exceptions or hallucinated claims.
     - **Boundary / Invariant**: Field limits, sorting orders, and tenant filters hold.
  4. Targeted subsystem integration suite (e.g., `python -m pytest tests/test_decision_brief*.py -q`).

### Tier 3: High Risk
- **Qualifying Changes**: Tenancy boundaries (`tenancy.py`), authentication, database layer (`database.py`), migration scripts (`migrations/*.sql`), or benchmark bid handling.
- **Verification Protocol**:
  1. `python -m py_compile <touched .py files>`
  2. `git diff --check`
  3. Dedicated tenant isolation suite: `python -m pytest tests/test_tenancy.py -q`.
  4. Benchmark immutability check: verify Bid 1522 rows, runs, and revisions are completely unchanged.
  5. **Full regression suite once**: `python -m pytest -q` (all 3,954+ tests).

### Tier 4: Release / Commissioning
- **Qualifying Changes**: Production release candidate, live telemetry gate, external provider acceptance.
- **Verification Protocol**:
  1. Full regression suite once.
  2. Follow `.agents/skills/release-acceptance/SKILL.md`:
     - Exactly one real attempt against external provider.
     - Smallest viable payload.
     - No automatic retry loops upon failure; document genuine outcome immediately.

### On running the full suite twice
Default is **once** for high-risk or release tasks. Run it a second time only when:
- The task is an acceptance/commissioning deliverable that explicitly requires determinism proof.
- The first run revealed an ordering-sensitive or flaky test that requires confirmation before diagnosis.

## 3. Database & migration discipline

- Never rewrite an already-numbered migration file, whether applied or unapplied.
- A migration file in `migrations/` is **not** evidence that it is applied to any live database.
- Agents must never execute DDL. Migrations are applied manually via the Supabase dashboard.
- Do not apply a migration without explicit task authorization.

## 4. Deployment discipline

- Never merge `main` unless explicitly instructed for that specific task.
- Never deploy production unless explicitly instructed for that specific task. Prior approvals do not carry forward.

## 5. Acceptance reporting

- Report only verified facts.
- Mark inferences as inferences and estimates as estimates.
- If data is unavailable, state `UNAVAILABLE` rather than guessing.
- Never report `PASS` on an unchecked criterion.
