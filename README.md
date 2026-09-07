# Document Metadata

| Field | Value |
|---|---|
| Document | `README.md` |
| Title | Bid Intelligence Repository Introduction |
| Authority Level | Level 6 — Introduction and Guidance |
| Version | 2.0.0 |
| Status | Current |
| Purpose | Introduce Bid Intelligence and direct contributors to its governing documents. |
| Higher Authority | [`MANIFESTO.md`](MANIFESTO.md) |
| Governed Documents | None. |
| Related Documents | [`AGENT.md`](AGENT.md), [`GOVERNANCE.md`](GOVERNANCE.md), [`ANTI_GOALS.md`](ANTI_GOALS.md) |

# Bid Intelligence

Bid Intelligence is a **Decision Preparation Platform** for Capability Development, Leadership Development, Learning & Development, HR Consulting, Organizational Development, Executive Education, and Boutique Consulting Firms.

It helps experienced professionals understand opportunities, understand buyers, verify proposals, and learn from historical bids. It organizes authoritative evidence and transparent analysis so that consequential decisions can be made with greater clarity.

**The platform prepares decisions. Humans make decisions. Human judgment is sovereign.**

## Start here

Before reading architecture or changing implementation, read:

1. [`MANIFESTO.md`](MANIFESTO.md) — the Level 1 Constitution and highest authority.
2. [`GOVERNANCE.md`](GOVERNANCE.md) — hierarchy, ownership, amendments, versioning, and conflict rules.
3. [`ANTI_GOALS.md`](ANTI_GOALS.md) — product forms the platform intentionally refuses to become.
4. [`AGENT.md`](AGENT.md) — mandatory conduct for AI contributors and review discipline for human contributors.

Architecture, specifications, code, tests, prompts, and reports derive their authority from this layer.

## The problem and product

Professional services firms rarely lack writing capability. Their harder problems are establishing what an opportunity requires, separating evidence from interpretation, checking whether a proposal answers the request, and retaining what the organization learns after submission.

Bid Intelligence addresses those problems through four pillars:

- **Opportunity Intelligence:** understand the opportunity.
- **Buyer Intelligence:** understand the buyer.
- **Proposal Compliance Intelligence:** verify the proposal.
- **Organizational Intelligence:** learn from historical bids.

## Product boundary

Bid Intelligence complements ChatGPT, Claude, Gemini, and similar writing tools. Proposal generation is outside its competitive focus. It is not a generic procurement platform, autonomous bidding engine, win-probability engine, executive decision maker, or black-box AI system. [`ANTI_GOALS.md`](ANTI_GOALS.md) defines these exclusions.

## Repository structure

- Root constitutional documents govern product purpose and contribution behavior.
- Root architecture, specification, and implementation reports describe major platform contracts and completed work.
- `docs/` contains target architecture, audits, and migration planning.
- Root application modules implement extraction, canonical opportunity handling, decision intelligence, analysis, workspace presentation, and supporting workflows.
- `pages/` contains Streamlit views.
- `tests/` contains unit, integration, smoke, acceptance, and regression coverage.
- `migrations/` and `supabase_schema.sql` contain database definitions governed by compatibility rules.

## Local setup

```bash
pip install -r requirements.txt
streamlit run app.py
```

The application is available at `http://localhost:8501` by default. Contributors should begin with [`MANIFESTO.md`](MANIFESTO.md), then read the architecture and contracts relevant to their work.
