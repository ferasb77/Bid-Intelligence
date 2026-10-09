# Lean Task Prompt Template (AI Engineering Canon v1.1)

Use this template for all subsequent Bid Intelligence engineering tasks. It eliminates
repetitive boilerplate and context flooding while establishing explicit, verifiable
outcomes and risk-tiered boundaries.

---

```markdown
# TASK: [Short Identifier — e.g. BI-VALUE-4: Synthesis Calibration]

## 1. Context & Baseline
- Branch: feature/bi-value-reset-v2
- Baseline HEAD: [Commit SHA or 'latest HEAD']
- Subsystem: [e.g. decision_brief.py, decision_brief_report.py]
- Reference Docs: [e.g. docs/current/YORK_P27_070_DECISION_BRIEF_BENCHMARK.md]

## 2. Desired Outcome
[2–4 sentences describing the user-facing outcome or business capability to achieve.
Focus on *what* the system must deliver, not micromanaged code syntax.]

## 3. Acceptance Criteria (Acceptance Triad)
1. **Positive Cases**:
   - [e.g., Calling synthesize_decision_brief() with full inputs yields valid DecisionBrief]
   - [e.g., Output renders all 8 required decision-brief sections]
2. **Negative Cases**:
   - [e.g., When buyer research is absent, brief renders explicit 'Research Unavailable' notice without raising KeyError]
   - [e.g., Unverified web domains or unauthenticated URLs are rejected from Buyer Intelligence]
3. **Boundary & Invariant Cases**:
   - [e.g., Strict tenant isolation: queries must filter by organization_id]
   - [e.g., Read-only benchmark Bid 1522 must receive 0 DB mutations or revisions]
   - [e.g., Output length strictly within 6–10 pages / 2,500–4,000 words]

## 4. Scope Boundaries
- **In Scope**: [List of files or packages authorized to edit]
- **Frozen / Out of Scope**: Do not touch frozen subsystems (bid deletion, migrations 024–026,
  Fast Analysis engine, Full Analysis core). Do not introduce database migrations unless
  explicitly approved.

## 5. Verification Tier
- **Tier**: [Tier 1 (Low) | Tier 2 (Medium) | Tier 3 (High) | Tier 4 (Release)]
- **Targeted Fast-Loop Command**: `python -m pytest tests/test_[subsystem].py -q`
- **Completion Check**: [e.g., Targeted suite + py_compile + git diff --check (Medium Risk)]
```

---

## Authoring Guidelines

1. **Outcome First (Principle 1)**: State the problem and target behavior. Avoid prescribing
   exact local variable names, regex patterns, or line-by-line implementations.
2. **Acceptance Triad (Principle 6 & Section 7)**: Always provide at least one positive,
   one negative (graceful failure/null-safety), and one boundary/invariant criterion.
3. **Reference Invariants Instead of Retyping**: Do not paste 60 lines of frozen
   subsystem descriptions. Reference `AGENTS.md` and `docs/current/SYSTEM_STATE.md`.
4. **Specify Verification Tier**: Explicitly name the tier so the agent does not default
   to running 3,954 regression tests during intermediate iterations.
