"""
Editable content source for the Bank of Canada RFP 2026-026 Bid Intelligence
Preview (client-facing PDF, product-feedback prototype).

Every factual statement here was verified against the validated 16-document
concurrency run `stagea-concurrency2-full-boc-2026-026-20260913T054732Z-48564b`,
its deterministic Stage B -> Stage C -> Canonical Opportunity shadow, and the
raw Stage A document facts for the same run. No pipeline/engineering
terminology, record counts, hashes, or internal diagnostics are referenced
here -- this is pure report content, editable without touching PDF layout
code (see build_boc_bid_intelligence_preview_pdf.py).

Where the underlying analysis found a genuine, unresolved ambiguity in the
source RFP, it is preserved here rather than silently resolved.
"""

TITLE = "Bid Intelligence Preview"
SUBTITLE_1 = "Bank of Canada — RFP 2026-026"
SUBTITLE_2 = "Talent, Learning and Organizational Development Services"
COVER_FOOTER = "Prototype analysis for product-feedback purposes"

# ---------------------------------------------------------------------------
# 2. Executive Opportunity Snapshot
# ---------------------------------------------------------------------------
SNAPSHOT_FACTS = [
    ("Buyer", "Bank of Canada"),
    ("Solicitation Number", "RFP 2026-026"),
    ("Opportunity", "Talent, Learning and Organizational Development Services"),
    ("Submission Deadline", "September 30, 2026, 11:59 PM EST — via MERX (electronic only)"),
    ("Clarification / Questions Deadline", "September 10, 2026"),
    ("Procurement Model", "Multi-vendor call-off — the Bank may qualify more than one supplier "
                          "and issue individual engagements as needs arise, rather than a single "
                          "fixed-scope award"),
    ("Contract Term", "3 years, with two optional 1-year extensions (subject to Bank satisfaction "
                       "and mutual agreement)"),
    ("Service Categories", "3 — Learning & Development, HR Advisory, Facilitation & Team Effectiveness"),
]

SNAPSHOT_CATEGORY_CARDS = [
    ("Category 1", "Learning & Development Programs", "Response form D1 · 15-page limit · Presentation stage applies"),
    ("Category 2", "HR Advisory Services", "Response form D2 · 12-page limit · No presentation stage"),
    ("Category 3", "Facilitation & Team Effectiveness", "Response form D3 · 10-page limit · Presentation stage applies"),
]

SNAPSHOT_NOTE = (
    "A small number of internal references use slightly different wording for the buyer name and "
    "opportunity title (e.g. “the Bank” vs. “Bank of Canada”) — this is ordinary "
    "drafting variation, not a substantive discrepancy. Genuine, material ambiguities are addressed "
    "separately in Section 8."
)

# ---------------------------------------------------------------------------
# 2. Buyer Intelligence
# ---------------------------------------------------------------------------
BUYER_INTEL_INTRO = (
    "This section profiles Bank of Canada as an organization, drawing on the Bank's own published "
    "materials. It is organized in three tiers — objective facts, publicly observable signals, and "
    "interpretation — kept explicitly separate so a reader can tell exactly how confident to be in "
    "each statement. Nothing here should be read as a statement of the Bank's evaluation intentions; "
    "the RFP documents (Sections 4–7) remain the only authoritative source on how this "
    "procurement will actually be judged."
)

VERIFIED_BUYER_FACTS = [
    ("Legal status & mandate", "A special federal Crown corporation established under the Bank of "
     "Canada Act, with a statutory purpose to regulate credit and currency in the best interests of "
     "Canada's economic life. Operates independently of government within that mandate.",
     "Bank of Canada Act; “About the Bank of Canada”"),
    ("Core functions", "Five core functions: monetary policy, financial system stability, currency "
     "design/issuance/distribution, funds and foreign-reserves management, and oversight of payment "
     "and financial-market infrastructure.", "“About the Bank of Canada”"),
    ("Governance structure", "Governing Council (Governor, Senior Deputy Governor, Deputy Governors) "
     "sets monetary policy; a Board of Directors oversees planning, finance, risk, staffing and "
     "internal policy; an Executive Council is the primary management decision-making body.",
     "“About the Bank of Canada”"),
    ("Current strategic plan", "Operating under a 2025–27 strategic plan, “Canadians Count on Us,” "
     "organized around five published themes: Sharpening our insights, Amplifying our impact, "
     "Focusing our innovation, Sustaining our resilience, and Equipping our workforce for the "
     "future.", "2025–27 Strategic Plan; Annual Report 2025"),
    ("Cost-reduction commitment", "Has committed to reducing core operating expenses by 15% by the "
     "end of 2028, in line with the federal government's Comprehensive Expenditure Review, with "
     "cost-saving measures already reflected in the 2026 budget.", "Annual Report 2025"),
    ("Procurement policy", "Published procurement policy commits the Bank to fair, open, and "
     "transparent procurement.", "Procurement Policy Statement"),
    ("Accessibility commitments", "The 2026–28 Accessibility Plan commits to a medium-term strategy "
     "for accessibility in procurement (Action 22) and Bank-wide disability/ableism-awareness "
     "education for employees and leaders (Action 4). The Bank reports its disability-hiring rate "
     "rose from 5.6% (2022) to 9.2% (2024).", "2026–28 Accessibility Plan"),
]

BUYER_FACTS_NOTE = (
    "The Bank does not publish a current total employee headcount on its own site; third-party "
    "estimates vary widely and are not used here, consistent with preferring the Bank's own primary "
    "sources over external summaries."
)

RELEVANT_BUYER_SIGNALS = [
    ("New leadership program & refreshed competencies", "Under “Equipping our workforce for the "
     "future,” the Bank states it is building a new leadership program and refreshing its core and "
     "leadership competencies, explicitly to help leaders “navigate change and empower their staff "
     "to succeed.”"),
    ("Renewed talent management & updated EDI strategy", "The Bank states it is adopting renewed "
     "talent management practices and implementing an updated equity, diversity and inclusion "
     "strategy with new targets."),
    ("Culture vision & engagement measurement", "The Bank states it is defining its organizational "
     "culture vision with implementation steps, and renewing how it measures employee engagement."),
    ("Updated bilingualism policy & training", "The Bank states it is updating its bilingualism "
     "policy and training strategy."),
    ("Training for emerging capabilities", "The Bank states it is introducing training for emerging "
     "capabilities and fostering continuous learning engagement among staff."),
    ("Cost-conscious operating posture", "A published, dated commitment to a 15% operating-cost "
     "reduction by 2028 under a federal expenditure review, with savings already built into the "
     "2026 budget."),
]

BID_RELEVANCE_ITEMS = [
    ("New leadership program & refreshed competencies →",
     "Category 1 (Learning & Development, including leadership/management development) may be one "
     "channel the Bank uses to deliver on this stated commitment. A response that speaks concretely "
     "to leadership-competency work and change-navigation skills is consistent with this signal — "
     "the RFP itself does not confirm the link."),
    ("Renewed talent management & EDI strategy →",
     "HR Advisory responses (Category 2) that address workforce planning, succession planning, and "
     "EDI-aware talent practices align with a publicly stated direction. The RFP does not name EDI "
     "as a scored evaluation criterion."),
    ("Culture vision & engagement measurement →",
     "Facilitation & Team Effectiveness responses (Category 3) that speak to culture conversations "
     "and engagement follow-through are consistent with a stated institutional priority — again, "
     "not a confirmed evaluation weighting."),
    ("Updated bilingualism policy & training →",
     "Reinforces why bilingual (English/French) delivery capability is a mandatory RFP requirement "
     "(Section 6) rather than a discretionary extra — treat it as core delivery capability."),
    ("Cost-conscious operating posture →",
     "Consistent with — though not proof of — why this opportunity is structured as a flexible, "
     "as-required call-off arrangement rather than fixed headcount. Price competitiveness and "
     "demonstrable cost efficiency may carry weight beyond the stated Stage 4 pricing score."),
    ("Accessibility & disability-awareness commitments →",
     "Reinforces why the RFP's WCAG/EN 301 549 accessibility requirement for digital learning "
     "content (Section 6) is likely to matter operationally, not just at proposal-compliance "
     "stage."),
]

BID_TEAM_PANEL_TITLE = "What This Means for the Bid Team"
BID_TEAM_PANEL_ITEMS = [
    "Frame leadership-development content (Category 1) around change-navigation and competency "
    "refresh — language the Bank itself is using publicly.",
    "In HR Advisory responses (Category 2), connect workforce/succession-planning capability to the "
    "Bank's stated talent-management renewal, without asserting EDI is a scored criterion.",
    "Treat bilingual delivery as a genuine operating requirement, not paperwork — it echoes a "
    "current Bank policy update, not just an RFP checkbox.",
    "Expect cost-consciousness to matter beyond the pricing form itself, given the Bank's public "
    "15%-by-2028 expense-reduction commitment.",
    "Take the digital-accessibility requirement seriously in actual content design, not only in the "
    "proposal response — it sits inside a broader, dated Bank-wide accessibility program.",
    "None of the above is stated or implied to be an evaluation criterion by the RFP itself — use it "
    "to inform tone and emphasis, not to guess at hidden scoring weight.",
]

BUYER_INTEL_SOURCES_NOTE = (
    "Sources: bankofcanada.ca — “About the Bank of Canada,” the Bank of Canada Act, the 2025–27 "
    "Strategic Plan and its “Equipping our workforce for the future” page, Annual Report 2025, the "
    "Procurement Policy Statement, and the 2026–28 Accessibility Plan. All retrieved directly from "
    "bankofcanada.ca. Full citations are in the accompanying validation note."
)

# ---------------------------------------------------------------------------
# 3. What Is Being Procured?
# ---------------------------------------------------------------------------
PROCURED_INTRO = (
    "Bank of Canada is seeking one or more qualified service providers to deliver talent, learning, "
    "and organizational development services on an as-required basis over a multi-year term. "
    "Suppliers may bid for one, two, or all three service categories below — each is evaluated, "
    "priced, and awarded independently."
)

SERVICE_CATEGORIES = [
    ("Learning & Development Programs", "Category 1 · Response Form D1",
     "Leadership and management development (emerging, mid-level, and senior levels), employee "
     "competency and professional-skills programs, off-the-shelf or tailored learning solutions, "
     "custom curriculum and instructional design, and leadership, skills, and psychometric "
     "assessments."),
    ("HR Advisory Services", "Category 2 · Response Form D2",
     "Strategic HR consulting including workforce planning, succession planning, competency "
     "framework development, culture and engagement strategy, HR strategy consulting, and change "
     "management and change-strategy execution support."),
    ("Facilitation & Team Effectiveness", "Category 3 · Response Form D3",
     "Team visioning, norming, and effectiveness sessions; strategic planning and problem-solving "
     "facilitation; retreat and off-site design and delivery; culture conversations; cross-functional "
     "workshops; and follow-up team or individual coaching."),
]

PROCURED_STRUCTURE = (
    "Each category has its own dedicated mandatory-criteria form, minimum-qualification form, and "
    "rated-criteria response form, evaluated on its own scoring table. Categories 1 and 3 also carry "
    "a pass/fail presentation stage with the Bank's Evaluation Committee; Category 2 does not. "
    "Bidders must clearly identify which category or categories they are submitting for and may not "
    "combine pricing across categories — each is priced and evaluated separately."
)

PROCURED_MODEL_NOTE = (
    "The engagement model is a call-off arrangement: award does not guarantee any minimum volume of "
    "work. Individual engagements are issued against the umbrella agreement as the Bank's needs "
    "arise — for example, the RFP references a specific HR Advisory engagement scoped at roughly "
    "12 weeks as an illustrative pricing scenario, sitting within the broader 3-year (+2x1-year) "
    "contract term."
)

# ---------------------------------------------------------------------------
# 4. Critical Dates & Bid Mechanics
# ---------------------------------------------------------------------------
KEY_DATES = [
    ("September 10, 2026", "Deadline for clarification questions"),
    ("September 30, 2026, 11:59 PM EST", "Proposal submission deadline (via MERX)"),
    ("October 26, 2026", "Presentation / demonstration — Category 1 (Learning & Development)"),
    ("November 2, 2026", "Presentation / demonstration — Category 3 (Facilitation & Team Effectiveness)"),
]

BID_MECHANICS = [
    "Submissions are accepted electronically through MERX only — no other submission method will "
    "be accepted. Proponents must register and hold an active MERX account in advance, with the "
    "software interface needed to access RFP documents and submit a proposal.",
    "Timeliness is determined solely by MERX's own recorded time and date — proposals cannot be "
    "submitted after the deadline for any reason.",
    "Proponents should monitor MERX regularly for addenda, revisions, or amendments to the RFP.",
    "If the Bank selects a top-ranked proponent, it intends to conclude contract negotiations within "
    "30 calendar days of the negotiation invitation.",
]

DATES_NOTE = (
    "Categories 1 and 3 each carry their own presentation date; Category 2 (HR Advisory) has no "
    "presentation stage at all. Confirm the date applicable to your category before scheduling "
    "internal resources."
)

# ---------------------------------------------------------------------------
# 5. Evaluation
# ---------------------------------------------------------------------------
EVAL_STAGES = [
    ("Stage 1", "Mandatory Submission Requirements", "Pass / fail — complete, signed, and properly formatted submission"),
    ("Stage 2", "Mandatory Criteria & Minimum Qualifications", "Pass / fail — must answer “yes” to every minimum-qualification question to proceed"),
    ("Stage 2 (cont.)", "Rated Criteria", "Scored — category-specific weighting (below)"),
    ("Stage 3", "Presentation / Demonstration", "Pass / fail — Categories 1 & 3 only; no pricing may be disclosed"),
    ("Stage 4", "Pricing", "Scored — standardized pricing scenario per category"),
    ("Stage 5", "Cumulative Score & Reference Checks", "Final ranking; successful reference checks required"),
]

GATE_EXAMPLES = [
    "Learning & Development: minimum 5 years' organizational experience with at least 3 prior "
    "engagements of similar scope for organizations of 1,000+ employees.",
    "HR Advisory: confirmed strategic HR consulting experience and senior advisory resource "
    "availability (yes/no confirmation).",
    "Facilitation & Team Effectiveness: minimum 10 facilitation engagements and 3 team-effectiveness "
    "or strategic-planning engagements in the past 3 years.",
]

# Weight tables per category, as stated in the category-specific rated-criteria sections.
EVAL_WEIGHTS = {
    "Category 1 — Learning & Development (Form D1)": [
        ("Corporate Profile", "5 pts"), ("Key Personnel & Roster", "15 pts"),
        ("Curriculum & Program Design", "35 pts"), ("Measurement Approach", "5 pts"),
        ("Relationship Management", "5 pts"), ("Value-add", "5 pts"),
        ("Relevant Experience & References", "5 pts"),
    ],
    "Category 2 — HR Advisory (Form D2)": [
        ("Corporate Profile", "5 pts"), ("Key Personnel & Roster", "15 pts"),
        ("Methodology & Advisory Approach", "35 pts"), ("Thought Leadership & Innovation", "5 pts"),
        ("Relationship Management", "5 pts"),
    ],
    "Category 3 — Facilitation & Team Effectiveness (Form D3)": [
        ("Corporate Profile", "10 pts"), ("Key Personnel & Roster", "20 pts"),
        ("Facilitation Methodology", "30 pts"), ("Value-add", "5 pts"),
        ("Relevant Experience & References", "10 pts"), ("Price", "25 pts"),
    ],
}

EVAL_WEIGHT_NOTE = (
    "Category 3's table includes Price within its 100-point total; Categories 1 and 2 show technical "
    "scoring only, with pricing evaluated separately at Stage 4. The RFP also contains additional "
    "scoring language elsewhere that does not fully match these tables — see Ambiguity 1 in "
    "Section 8 before finalizing how much proposal effort to allocate per section."
)

# ---------------------------------------------------------------------------
# 6. Response Requirements (checklist)
# ---------------------------------------------------------------------------
RESPONSE_CHECKLIST = [
    ("Appendix A", "Submission Form", "Signed by an authorized representative; confirms addenda received, no undisclosed conflict of interest, subcontractor list"),
    ("Appendix B1 / B2 / B3", "Mandatory Criteria", "One per category being bid; pass/fail gate"),
    ("Appendix C1 / C2 / C3", "Minimum Qualification Requirements", "One per category being bid; every question must be answered “yes”"),
    ("Appendix D1", "Rated Criteria Response — Learning & Development", "15-page limit · 8.5″×11″ · min. 10-pt font"),
    ("Appendix D2", "Rated Criteria Response — HR Advisory", "12-page limit · 8.5″×11″ · min. 10-pt font"),
    ("Appendix D3", "Rated Criteria Response — Facilitation & Team Effectiveness", "10-page limit · 8.5″×11″ · min. 10-pt font"),
    ("Appendix E", "Pricing Form", "Standardized scenario, Years 1–3 · all-inclusive pricing · no pricing anywhere else in the proposal"),
    ("Appendix F", "ESG Questionnaire", "Mandatory — every question answered"),
    ("Appendix G", "Form of Agreement", "Signed, mandatory"),
]

RESPONSE_OTHER_REQUIREMENTS = [
    "Written confirmation of the ability to deliver all services, materials, and solutions in both "
    "English and French.",
    "Reliability security clearance for every delivery resource (fingerprints, criminal record "
    "check, credit check, and potentially a screening interview).",
    "Digital learning content must meet CAN/ASC EN 301 549 (2024) and WCAG accessibility standards.",
    "External links are not treated as evaluated content — unless stated otherwise, information "
    "reached only via an outside link will not be considered part of the response.",
]

# ---------------------------------------------------------------------------
# 7. Commercial & Contractual Considerations
# ---------------------------------------------------------------------------
COMMERCIAL_POINTS = [
    ("Pricing Structure", "A standardized, all-inclusive pricing scenario is required per category "
     "(fees, licences, access costs, onboarding, and all other delivery costs), with separate "
     "entries for Years 1, 2, and 3. The scenario is for evaluation purposes only and creates no "
     "minimum-volume commitment."),
    ("Abnormally Low Pricing", "The Bank may require a detailed explanation if pricing appears "
     "abnormally low, and may require contract security in the form of a performance bond if that "
     "explanation is not satisfactory."),
    ("Contract Term & Extensions", "3-year base term with two optional 1-year extensions, subject to "
     "Bank satisfaction and mutual agreement. Individual call-off engagements run within that "
     "umbrella on their own, typically shorter, timelines."),
    ("Insurance", "Commercial General Liability (minimum $3,000,000), Errors & Omissions Liability, "
     "and Workplace Safety & Insurance coverage are required throughout performance of the "
     "agreement."),
    ("Intellectual Property", "Work-product copyright and related IP developed under the agreement "
     "is assigned to the Bank."),
    ("Confidentiality & Media", "Standard mutual confidentiality obligations apply; proponents may "
     "not discuss the RFP or any resulting contract with media without the Bank's written "
     "permission."),
    ("Security, Data & Personnel", "Cybersecurity and data-protection obligations apply; all "
     "delivery personnel require Reliability clearance; background-check requirements extend to "
     "subcontractors."),
    ("Termination, Change Control & Subcontracting", "Standard termination and change-control "
     "provisions apply; any subcontractors used to complete the contract must be disclosed in the "
     "proposal."),
    ("Ethical Supply Chain", "Proponents and subcontractors must confirm they do not use forced or "
     "child labour and comply with the Fighting Against Forced Labour and Child Labour in Supply "
     "Chains Act (SC 2023, c 9)."),
    ("Post-Award Diligence", "Selected proponent(s) may be required to complete a third-party vendor "
     "risk assessment before or alongside contract negotiations."),
]

# ---------------------------------------------------------------------------
# 8. Important Ambiguities / Items to Clarify
# ---------------------------------------------------------------------------
AMBIGUITIES = [
    {
        "issue": "The RFP contains more than one point value for similarly named evaluation criteria.",
        "why": "“Corporate Profile” appears as both 5 and 10 points in different parts of the "
               "document; “Key Personnel / Team Experience” appears as 15, 20, and 100 points; "
               "“Methodology” appears as 5, 30, and 35 points. Proposal effort should be "
               "allocated according to whichever table actually governs scoring — misjudging this "
               "could mean over- or under-investing in the wrong sections.",
        "source": "RFP 2026-026 — Talent, Learning and Organizational Development Services.pdf, "
                  "multiple internal scoring tables.",
        "question": "Please confirm which evaluation-weighting table governs scoring for each of the "
                    "three service categories, given that the document contains more than one point "
                    "allocation for similarly labeled criteria.",
    },
    {
        "issue": "A “Price” line item appears inside one category's 100-point rated-criteria "
                 "table, while the RFP's overall structure also names Stage 4 (“Pricing”) as a "
                 "separate evaluation stage.",
        "why": "Bidders need to know whether price is scored once (within the category table) or "
               "twice (there, and again at Stage 4) to understand how heavily price weighs in the "
               "final outcome.",
        "source": "RFP 2026-026, Facilitation & Team Effectiveness rated-criteria table and Stage "
                  "4 (“Pricing”) evaluation-structure description.",
        "question": "Please confirm whether Stage 4 pricing evaluation is the sole pricing "
                    "assessment, or whether the category tables that include a Price line item apply "
                    "pricing on top of it.",
    },
    {
        "issue": "Presentation/demonstration dates differ by service category, under a shared "
                 "“Presentation Date” label.",
        "why": "Category 1 shows October 26, 2026; Category 3 shows November 2, 2026. This most "
               "likely reflects genuinely separate, category-specific scheduling rather than a true "
               "conflict — but a bid team tracking only one date could miss the correct one for "
               "its category.",
        "source": "RFP 2026-026, “Presentations — Service Category 1” and "
                  "“Presentations — Service Category 3.”",
        "question": "Please confirm the presentation date applicable to each service category, and "
                    "whether Category 2 is correctly understood to have no presentation stage.",
    },
]

# ---------------------------------------------------------------------------
# 9. Bid Team Attention Points
# ---------------------------------------------------------------------------
ATTENTION_POINTS = [
    "Decide category scope early. Each of the three categories has its own form, page limit, and "
    "(for two of the three) presentation stage — bidding for more than one category multiplies "
    "the response workload.",
    "Confirm the authoritative evaluation weighting before drafting Appendix D responses (Ambiguity "
    "1) — do not guess which scoring table governs.",
    "Manage page limits deliberately: 15 pages (D1), 12 pages (D2), and 10 pages (D3), all at "
    "8.5″×11″ with a 10-point minimum font — dense category content needs to fit "
    "without relying on external links, which are not treated as evaluated content.",
    "Build the standardized pricing scenario carefully: all-inclusive, Years 1–3, on Appendix E "
    "only — pricing appearing anywhere else in the proposal is a stated non-compliance risk.",
    "Confirm presentation-stage exposure per category (Ambiguity 3) and calendar the applicable date "
    "once clarified.",
    "Line up mandatory compliance items early — Reliability security clearance, bilingual "
    "(English/French) delivery confirmation, and digital-accessibility compliance are pass/fail, "
    "not merely scored, and can disqualify a proposal on their own if missed.",
    "Assign clear ownership for the ESG Questionnaire (Appendix F) and Form of Agreement (Appendix "
    "G) — both are mandatory and often sit between commercial and legal teams without a clear "
    "owner.",
    "Model the contract structure in two layers: the 3-year (+2×1-year) umbrella term, and "
    "shorter individual call-off engagements issued within it (e.g. a specific HR Advisory "
    "engagement scenario referenced at roughly 12 weeks).",
]

# ---------------------------------------------------------------------------
# 10. Source Map / Reference Appendix
# ---------------------------------------------------------------------------
SOURCE_DOCUMENTS = [
    ("RFP main document", "Full solicitation: instructions, terms of reference, evaluation criteria, contract-negotiation process"),
    ("Appendix A", "Submission Form"),
    ("Appendix B1 / B2 / B3", "Mandatory Criteria response forms (one per category)"),
    ("Appendix C1 / C2 / C3", "Minimum Qualification Requirements response forms (one per category)"),
    ("Appendix D1 / D2 / D3 (+ Amendment 1 revision to D2)", "Rated Criteria Response forms — Learning & Development, HR Advisory, Facilitation & Team Effectiveness"),
    ("Appendix E / F / G", "Pricing Form; ESG Questionnaire; Form of Agreement"),
    ("Opportunity abstract", "Short overview document summarizing the RFP"),
]

SOURCE_REF_TABLE = [
    ("Submission deadline", "RFP main document, p. 3 — “1.2 RFP Timetable”"),
    ("Category 1 / 2 / 3 scope", "RFP main document, pp. 12–13 — “4.1 Category 1/2/3”"),
    ("D1 / D2 / D3 page limits (15 / 12 / 10 pages)", "Appendix D1 / D2 / D3, each form's Header / Instructions"),
]

VALIDATION_FOOTER_NOTE = (
    "Procurement-specific figures and statements in this preview are drawn from a deterministic, "
    "source-traceable reading of the RFP 2026-026 document set. Buyer Intelligence (Section 2) "
    "draws on the Bank of Canada's own published materials, kept clearly separate from — and never "
    "presented as — the RFP's evaluation criteria. Where the source material itself was "
    "inconsistent, that inconsistency is preserved and flagged rather than silently resolved."
)
