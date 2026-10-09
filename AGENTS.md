# Bid Intelligence — Codex & Agent Instructions

Short on purpose. Full product-philosophy doctrine lives in
`MANIFESTO.md` / `GOVERNANCE.md` / `ANTI_GOALS.md` / `AGENT.md` — read
those only when a task actually needs that depth, not by default.
Development workflow follows AI Engineering Canon v1.1.

## Start every task

1. `python scripts/agent_context.py` — branch, HEAD, working-tree status,
   migration state, entry points. Read-only, deterministic startup check.
2. `docs/current/SYSTEM_STATE.md` — what the system currently is.
3. `docs/current/NAVIGATION.md` — where to look for the subsystem the task
   touches, before any broad repo exploration.

## Standing safeguards & invariants

- **Benchmark immutability**: Bid 1522 (York University P27-070) is the
  canonical read-only benchmark. Never mutate its database rows, runs, or
  governed revisions.
- **Frozen boundaries**: Frozen subsystems (bid deletion, migrations 024–026,
  auto procurement identity, governed buyer research, Full Analysis engine)
  are documented in `docs/current/SYSTEM_STATE.md` — never reopen for
  speculative polishing.
- **Epistemic separation & provenance**: Keep evidence (raw extracted text),
  canonical procurement truth (`requirements`), and AI-derived intelligence
  strictly separate. Never invent a requirement or silently repair a procurement
  fact. Only verified source authority is admitted.
- **Tenant isolation**: Multi-tenant and organizational boundaries are strictly
  enforced in every query and mutation (`tenancy.py`, `database.py`).
- **Database & migration discipline**: A migration file in `migrations/` is not
  the same as it being applied to a live database. Migrations are applied manually
  via the Supabase dashboard; agents never execute DDL. Never rewrite numbered
  migrations.
- **Deployment discipline**: Never merge `main` or deploy production unless the
  current task explicitly authorizes it.
- **Historical record discipline**: Root `*_REPORT.md` / `*_AUDIT.md` files are
  historical records, not current architecture (see `docs/current/ROOT_DOC_INVENTORY.json`).

## Risk-proportionate verification

Use `.agents/skills/change-verification/SKILL.md` (or `docs/current/CHANGE_VERIFICATION.md`)
for tiered verification. Do not run the full 3,954-test suite when targeted verification
suffices:
- **Low risk** (docs, prompt templates, formatting, isolated leaf functions):
  `py_compile`, `git diff --check`, targeted test module (sub-5s).
- **Medium risk** (synthesis, business logic, schema adapters):
  static checks, targeted tests + affected integration suite (Acceptance Triad: positive, negative, boundary).
- **High risk** (tenancy, auth, persistence, migrations):
  static checks, security/isolation checks, full test suite once (`pytest`).
- **Release / Commissioning**:
  full test suite once + live acceptance procedure (`.agents/skills/release-acceptance/SKILL.md`).

## Lean task prompts

Prompts define outcomes, boundaries, and acceptance criteria rather than
micromanaging syntax or repeating static rules. See `docs/current/TASK_PROMPT_TEMPLATE.md`.
