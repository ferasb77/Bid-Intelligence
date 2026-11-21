# Skill: constraint-red-team

## Purpose
Perform an adversarial, read-only audit of a `git diff` and execution evidence strictly against `CONSTRAINTS.md` and `SPEC.md`.

## Hard Rules (STRICTLY READ-ONLY)
- Read `CONSTRAINTS.md` and `SPEC.md` in the repository root first.
- Make **0 file edits**, **0 commits**, and **0 external LLM API calls**.
- Do NOT critique code style, suggest nice-to-have improvements, or propose new architecture/refactors.
- If you did not directly test or inspect a requirement (e.g., live API spend or database state), mark it `NOT ASSESSED`—never `PASS`.

## Required Output (Pass/Fail Checklist Only — Post as Issue Comment and STOP)
1. **Hardcoding check** (any client/RFP-specific logic?): `PASS` / `FAIL` / `NOT ASSESSED` + exact line
2. **No-scoring / No-proposal-writing check**: `PASS` / `FAIL` / `NOT ASSESSED` + exact line
3. **Spend & call-cap compliance** (within USD cap, 0 provider calls during compose/export, CHECK <= 12 calls): `PASS` / `FAIL` / `NOT ASSESSED`
4. **Protected data & tenancy check** (Bid 1522 untouched, `.engine_runs` unmodified unless authorized, tenant isolation intact, no DDL): `PASS` / `FAIL` / `NOT ASSESSED`
5. **Scope creep check** (only authorized files modified, no unapproved dependencies or pipeline layers): `PASS` / `FAIL` / `NOT ASSESSED`
6. **FINAL VERDICT:** `APPROVE` or `REJECT` (if `REJECT`, list the exact violating lines and STOP—never auto-reassign).
