# Bid Intelligence — Claude Code Instructions

This file is intentionally short. It does not duplicate `MANIFESTO.md`,
`GOVERNANCE.md`, `ANTI_GOALS.md`, or `AGENT.md` — read those only when a
task actually requires constitutional/product-philosophy context (see
below), not by default.

## Start every task

1. Run `python scripts/agent_context.py` — branch, HEAD, working-tree
   status, migration state, entry points. No model calls, no side effects.
2. Read `docs/current/SYSTEM_STATE.md` — what the system currently is.
3. Read `docs/current/NAVIGATION.md` before any broad repo exploration —
   it tells you which specific files to open for the subsystem the task
   touches. Don't grep/read broadly before checking it.

## Standing rules

- Do not treat a root-level `*_REPORT.md` / `*_AUDIT.md` /
  `*_COMMISSIONING_REPORT.md` as current architecture. These are
  historical operational records (see `docs/current/ROOT_DOC_INVENTORY.json`
  for a deterministic classification). Read one only when the task
  specifically needs historical evidence.
- Preserve the evidence / canonical-procurement-truth / intelligence
  separation. Never invent a procurement requirement, silently repair a
  procurement fact, or convert advisory AI reasoning into stated fact.
- A migration file existing in `migrations/` is not the same as it being
  applied to any live database. Check explicitly; never assume.
- Do not merge `main` or deploy production unless the current task
  explicitly says so — a prior task's approval does not carry forward.
- Follow `docs/current/CHANGE_VERIFICATION.md` for the standard
  before/after-work checklist (branch/HEAD verification, `py_compile`,
  `git diff --check`, test scope, migration/deployment discipline). Don't
  re-derive it per task.
- Keep tool output compact — targeted test runs and `-q` by default; full
  suite once after a substantive change, twice only when a task explicitly
  needs determinism proof (reasoning in `CHANGE_VERIFICATION.md`).

## When constitutional depth is actually needed

Reading `MANIFESTO.md` → `GOVERNANCE.md` → `ANTI_GOALS.md` → `AGENT.md` in
full is for proposing, reviewing, or implementing work that touches
product philosophy, authority boundaries, or anti-goals — not for an
ordinary bounded bug fix, test addition, or doc update. Use judgment.
