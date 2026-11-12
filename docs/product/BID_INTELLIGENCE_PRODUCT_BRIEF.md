# Bid Intelligence — Product Brief (Phoenix Beta)

| Field | Value |
|---|---|
| Product | Bid Intelligence, developed by Enable My Growth |
| Current beta client | Phoenix Consulting (isolated Phoenix Beta on Oracle) |
| Purpose of this brief | The business source of truth for user workflows, intelligence and reports in the Phoenix Beta. Read it before changing any of them. |
| Relationship to doctrine | Narrows, for the current beta, the long-term doctrine in [`PRODUCT_VISION.md`](PRODUCT_VISION.md), [`PRODUCT_PRINCIPLES.md`](PRODUCT_PRINCIPLES.md), [`CUSTOMER_WORKFLOW.md`](CUSTOMER_WORKFLOW.md) and [`CUSTOMER_PERSONAS.md`](CUSTOMER_PERSONAS.md) (see §10). |
| Last verified against code | 12 November 2026, branch `feature/super-admin-mvp` |

## 1. Purpose and value proposition

Bid Intelligence is an AI-enabled procurement intelligence platform. It helps consulting and professional-services firms, and their management teams, to do four things:
- understand procurement opportunities;
- examine the requirements the buyer has issued;
- research the issuing organization;
- organize the factual information needed for an informed bid/no-bid decision.

**The value is not extracting more information from documents. It is making complex procurement information easier to understand, navigate, verify and use in a human decision.**

*Bid Intelligence supplies reliable intelligence. Phoenix makes the decision.*

## 2. Primary users and their information needs

| User | Needs |
|---|---|
| Consultants and bid managers | Understand the opportunity quickly. Find the relevant requirements, examine the buyer, and prepare information for management. |
| Phoenix management / decision-makers | Concise, factual intelligence: requirements, commitments, the evaluation framework, commercial conditions and the issuing organization. |
| Phoenix Account Owner (`admin`/`owner` role) | Manages the account and its users. Makes permitted manual corrections, such as the effective submission deadline, which is labelled as user-entered wherever it appears. |

## 3. Current Phoenix Beta scope and workflow

**Implemented today:**
1. **Upload** (New Bid Ingestion). Upload the procurement package only; the title and client are identified by FAST.
2. **FAST — Understand.**
   - Identifies the opportunity and produces the *Opportunity Snapshot* PDF.
   - The Understand page has five tabs. It also holds the deadline panel, which only the owner can edit.
3. **FULL — Deepen intelligence** (Full Bid Intelligence page).
   - Six specialist analyses and reconciliation run behind the scenes.
   - Targeted external buyer research runs in the background; its results appear only when the quoted source text is found on the cited page.
   - The page has six tabs: Overview, Requirements, Evaluation, Commercial, Buyer Intelligence and Detailed Findings.
   - It produces the *Bid Opportunity Assessment* PDF.
4. **Decide.** Phoenix users review the intelligence and record their own decision.
5. **Update the opportunity.**
   - Add addenda, clarifications, revised forms or pricing workbooks to the existing bid, then use "Update Analysis".
   - Changes are labelled New/Updated, and earlier versions are retained.

**Outside the Phoenix Beta interface:** Build, Check and Submit, proposal writing, and the organizational-learning features described in the long-term doctrine.

## 4. FAST and FULL report purposes

| | FAST — Opportunity Snapshot | FULL — Bid Opportunity Assessment |
|---|---|---|
| Business purpose | A fast, reliable understanding of what the buyer is procuring | Deeper factual understanding of the opportunity *and* the buyer, for management |
| Reader learns | What is requested and who issues it; scope and principal deliverables; mandatory conditions and evaluation; submission and commercial essentials | What exactly is procured; delivery commitments; eligibility and evaluation; commercial obligations; verified buyer facts; New/Updated information; decision-relevant facts |
| Length | About 2 pages for a small RFP, without dropping relevant information | Concise; independently readable; must add intelligence beyond FAST |
| Never | Reproduce the RFP | Repeat FAST, reproduce the RFP, or include internal AI terminology |

## 5. FULL report requirements and rationale

| Section | Content | Why |
|---|---|---|
| 1. Executive Intelligence Summary | The opportunity and its most material requirements, in a few rows | Management may read only this |
| 2. Opportunity and Delivery Requirements | Consolidated scope, deliverables, obligations, capabilities and commitments, as compact summary tables with references | Shows what a bid commits Phoenix to, without copying the RFP |
| 3. Buyer Intelligence | Targeted external facts relevant to *this* opportunity: programmes, published priorities, partnerships, funding and comparable activities. Dated, sourced and verified against the page content | Shows something the RFP does not |
| 4. Evaluation and Commercial Intelligence | Published criteria and weights (with the hierarchy rendered correctly), pricing requirements, commercial and contractual obligations, and supporting workbooks | Shows how bids are judged and what they cost |
| 5. Material Information and Amendments | New Information and Updated Information (with the previous value and the superseding source), and other material facts. Empty sections are omitted | Shows how the package evolved |
| 6. Management Decision Reference | Submission logistics, user-entered values and open items. No repetition and no recommendations | A factual checklist for the decision meeting |

## 6. Factual-reporting and Buyer Intelligence principles

- **Evidence.**
  - Every material statement comes from an uploaded document, a verified external source, or clearly identified authorized user input.
  - Summaries, organization and calculations directly supported by the source are allowed, e.g. "Technical 60% = 25+15+10+10". Speculation is not.
- **No AI decision-making.** No bid/no-bid recommendation, win probability, attractiveness score or suitability judgment.
- **No false omissions.** An empty AI-extracted field does not mean the RFP lacks the information. Report only what is located in the documents.
- **Evaluation weights.**
  - Keep the buyer's hierarchy and terminology.
  - When sub-criteria add up to the parent's weight, they are shares of the total score.
  - Ambiguous weightings are shown exactly as published, not reinterpreted.
- **Location.** Programme or organizational geography is not the assignment's delivery location unless the documents say so.
- **Buyer Intelligence.**
  - A valid URL is not evidence; the quoted source text must support the fact.
  - Separate historical facts from current ones, and never imply that older funding or partnerships apply to the current programme.
  - Do not repeat what the RFP already says except for brief context.
  - Prefer facts relevant to this opportunity over generic profiles.
- **Specialist output.** Specialist interpretations, risk claims and gap claims are working notes. They are never presented as verified facts.

## 7. Evolving procurement packages

- **New Information** is information a later document adds. **Updated Information** is an explicit revision; it keeps the previous value and records which document superseded it.
- Unresolved conflicts are labelled as such, not silently repaired.
- Workbooks and forms:
  - Identify each one's purpose from its contents.
  - Link its sheets, quantities and formulas to the RFP or addendum that references it.
  - Never invent prices or complete proposal forms.
- Analyse the current package as published; a missing detail is not a defect.

## 8. Out of scope

Bid Intelligence is not:
- a generic summarizer;
- a substitute for reading the RFP;
- an AI decision-maker or win predictor;
- a source of invented competitive advantages or buyer preferences;
- a proposal writer (in this beta);
- an exhaustive compliance audit.

## 9. Product-quality acceptance principles

A change to workflows, intelligence or reports is acceptable only if all of the following hold:
1. Every statement in its output can be traced to a document page or sheet, a verified URL with a date, or a labelled user entry.
2. The INJAZ golden case still holds:
   - correct weights;
   - email submission to the documented recipients;
   - the four document categories;
   - the six-session programme for youth aged 18–28;
   - quotation based on 5 days × 3 hours.
3. Addendum handling still produces New/Updated labels, keeps prior values, shows each condition once, and adds no invented prices.
4. The rendered PDF pages have been inspected for repetition, verbatim excess, pagination and decision-neutral language.
5. FAST and FULL remain distinct, and FULL adds buyer and commercial depth.

## 10. Relationship to the long-term doctrine (where this brief narrows it)

- **Scope.** The doctrine's Proposal Compliance and Organizational Intelligence capabilities are not part of the Phoenix Beta interface.
- **Unknowns.** "Unknowns remain visible" (Principle 5) applies only to unknowns *verified* against the documents. The beta never reports an empty AI field as missing information.
- **Inference.** The doctrine allows labelled inference. The beta reports present facts and source-supported calculations only. Specialist inference stays in Detailed Findings working notes, which are restricted to findings backed by canonical evidence.
