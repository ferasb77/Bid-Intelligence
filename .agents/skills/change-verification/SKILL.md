---
name: change-verification
description: >-
  The standard risk-tiered before/after-work checklist for changes to this
  repository: branch/HEAD verification, py_compile, git diff --check,
  risk-tiered test scope (low/medium/high/release), and migration/deployment
  discipline. Use this whenever starting or finishing a code change, instead
  of re-deriving the checklist from a task prompt.
---

# Change Verification

Full detail lives in
[`docs/current/CHANGE_VERIFICATION.md`](../../../docs/current/CHANGE_VERIFICATION.md)
— this file is the progressive-disclosure entry point; consult the linked
runbook when additional background is needed.

## 1. Before work

- Deterministic preflight: `python scripts/agent_context.py` (or `git branch --show-current`,
  `git rev-parse HEAD`, `git status --short`).
- Working-tree safety: leave any pre-existing uncommitted or untracked files alone.
  Never run destructive git operations (`reset`, `clean -fd`, `checkout --`) without
  explicit human authorization.

## 2. Risk-tiered verification after changes

Select the verification tier matching the highest risk of touched components:

### Tier 1: Low Risk
*Scope: Documentation, prompt templates, formatting, isolated leaf functions, UI copy.*
1. Static syntax check: `python -m py_compile <touched .py files>`
2. Hygiene check: `git diff --check`
3. Targeted test: Run specific test file (e.g. `python -m pytest tests/test_foo.py -q`).
   *Expected duration: sub-5 seconds. Do NOT run full 3,954-test suite.*

### Tier 2: Medium Risk
*Scope: Synthesis pipelines, business logic, data transformers, report generation, schema adapters.*
1. Static checks: `py_compile <touched>` and `git diff --check`.
2. Acceptance Triad targeted tests:
   - **Positive**: Proves intended functionality works under expected inputs.
   - **Negative**: Proves missing, malformed, or unavailable data is handled gracefully (no crashes or hallucinations).
   - **Boundary / Invariant**: Proves edge cases and constraints hold.
3. Affected subsystem integration tests (e.g. `python -m pytest tests/test_decision_brief*.py -q`).

### Tier 3: High Risk
*Scope: Tenancy, auth boundaries, persistence/database layer, migrations, benchmark Bid 1522.*
1. Static checks: `py_compile <touched>` and `git diff --check`.
2. Security & isolation checks: Verify tenant isolation tests pass (`pytest tests/test_tenancy.py`).
3. Benchmark integrity check: Verify Bid 1522 rows/runs are completely untouched.
4. Full regression suite **once**: `python -m pytest -q` (3,954 tests).

### Tier 4: Release / Commissioning
*Scope: External provider acceptance, live telemetry gates, production readiness.*
1. Full regression suite once.
2. Follow `.agents/skills/release-acceptance/SKILL.md`:
   - Single real attempt (no retry loops).
   - Real provider call with smallest viable payload.
   - Genuine failure or success recorded without redaction or backfilling.

## 3. Database & deployment discipline

- Never rewrite an already-numbered migration file.
- A migration file existing in `migrations/` is **not** applied to any live database.
- Agent-executed DDL is forbidden; migrations are applied manually via Supabase dashboard.
- Never merge `main` or deploy production without explicit task authorization.

## 4. Truthful reporting

- State only what was actually verified.
- Mark estimates as estimates; state "unavailable" rather than approximating.
- Never declare PASS on a claim that was not directly checked.
