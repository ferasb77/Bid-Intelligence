from __future__ import annotations

from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from buyer_domain import CanonicalBuyer, GovernmentLevel, Jurisdiction, OrganizationType
from buyer_evidence import (
    AuthenticityStatus, BuyerEvidenceSet, EvidenceAuthority, EvidenceCitation,
    EvidenceDocument, EvidenceExtract, EvidenceFreshness, EvidenceScope,
    EvidenceSource, FreshnessStatus, LocatorType, ScopeType, SourceCategory,
)
from buyer_intelligence import (
    BuyerFact, BuyerIntelligenceAnalysis, BuyerInterpretation, BuyerLimitation,
    BuyerManagementQuestion, BuyerUnknown, Confidence, FactClass, FactKind,
    GovernedBuyerInputs, InterpretationKind, SupportStatus, UnknownKind,
    governed_input_digest, validate_buyer_intelligence,
)
from buyer_brief import build_buyer_brief, render_buyer_brief


OUT = Path(__file__).resolve().parent
EVIDENCE = OUT / "evidence"
BUYER_ID = "buyer:bank-of-canada"
OPPORTUNITY_ID = "opportunity:bank-of-canada-rfp-2026-026"
RETRIEVED = date(2026, 9, 8)


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def build() -> None:
    bank = EvidenceSource("source:bank-of-canada", "Bank of Canada", EvidenceAuthority.OFFICIAL_BUYER,
                          "https://www.bankofcanada.ca/", "Canada")
    justice = EvidenceSource("source:justice-canada", "Department of Justice Canada",
                             EvidenceAuthority.LEGISLATIVE_AUTHORITY,
                             "https://laws-lois.justice.gc.ca/", "Canada")
    scope = (EvidenceScope(ScopeType.ORGANIZATION, BUYER_ID, "Bank of Canada"),)
    current = EvidenceFreshness(FreshnessStatus.CURRENT, RETRIEVED)
    na = EvidenceFreshness(FreshnessStatus.NOT_APPLICABLE)
    specs = (
        ("document:bank-act", justice.source_id, SourceCategory.LEGISLATION, "Bank of Canada Act",
         "https://laws-lois.justice.gc.ca/PDF/B-2.pdf", "bank-of-canada-act.pdf", na, None),
        ("document:about", bank.source_id, SourceCategory.OFFICIAL_ORGANIZATIONAL_WEBSITE, "About the Bank of Canada",
         "https://www.bankofcanada.ca/about/", "bank-about.html", current, None),
        ("document:strategic-plan", bank.source_id, SourceCategory.STRATEGIC_PLAN, "2025-27 Strategic Plan",
         "https://www.bankofcanada.ca/about/governance-documents/the-bank-of-canadas-2025-27-strategic-plan/", "strategic-plan-2025-27.html", current, None),
        ("document:workforce-priority", bank.source_id, SourceCategory.STRATEGIC_PLAN, "Equipping our workforce for the future",
         "https://www.bankofcanada.ca/about/governance-documents/the-bank-of-canadas-2025-27-strategic-plan/equipping-our-workforce-for-the-future/", "workforce-priority.html", current, None),
        ("document:annual-report-2025", bank.source_id, SourceCategory.ANNUAL_REPORT, "Annual Report 2025",
         "https://www.bankofcanada.ca/2026/04/annual-report-2025/", "annual-report-2025.html", current, date(2026, 4, 27)),
        ("document:accessibility-plan", bank.source_id, SourceCategory.ACCESSIBILITY_STATEMENT, "2026-28 Accessibility Plan",
         "https://www.bankofcanada.ca/accessibility/2026-28-accessibility-plan/", "accessibility-plan-2026-28.html", current, None),
        ("document:procurement-policy", bank.source_id, SourceCategory.PROCUREMENT_POLICY, "Procurement Policy",
         "https://www.bankofcanada.ca/about/governance-documents/procurement-policy-statement/", "procurement-policy.html", current, date(2026, 4, 22)),
    )
    documents = tuple(EvidenceDocument(doc_id, src, category, title, url, "en-CA",
                                       AuthenticityStatus.VERIFIED, RETRIEVED, freshness, scope,
                                       publication_date=published, content_sha256=digest(EVIDENCE / filename))
                      for doc_id, src, category, title, url, filename, freshness, published in specs)
    extracts_data = (
        ("mandate", "document:bank-act", LocatorType.PAGE, "1", "promote the economic and financial welfare of Canada"),
        ("identity", "document:about", LocatorType.SECTION, "About us", "We are Canada’s central bank."),
        ("core-functions", "document:about", LocatorType.SECTION, "Our core functions", "We have five core functions."),
        ("plan", "document:strategic-plan", LocatorType.SECTION, "At a glance", "Our 2025–27 Strategic Plan outlines five themes."),
        ("workforce", "document:workforce-priority", LocatorType.SECTION, "Our workforce", "Our workforce continuously learns and adapts."),
        ("accessibility", "document:accessibility-plan", LocatorType.SECTION, "Procurement of goods, services and facilities", "Develop a medium-term accessible procurement strategy."),
        ("procurement", "document:procurement-policy", LocatorType.SECTION, "Statement", "The Bank is committed to a fair, open and transparent procurement process."),
        ("annual-report", "document:annual-report-2025", LocatorType.SECTION, "Strategic Plan", "The Bank continued to implement its 2025–27 Strategic Plan."),
    )
    citations = tuple(EvidenceCitation(f"citation:{name}", doc, kind, locator)
                      for name, doc, kind, locator, _ in extracts_data)
    extracts = tuple(EvidenceExtract(f"extract:{name}", doc, text, (f"citation:{name}",), "en-CA")
                     for name, doc, _, _, text in extracts_data)
    evidence = BuyerEvidenceSet("evidence-set:boc-demo-2026-09-08", BUYER_ID,
                                (bank, justice), documents, citations, extracts)
    buyer = CanonicalBuyer(
        BUYER_ID, "Bank of Canada", "CA", Jurisdiction("CA", "Canada"),
        GovernmentLevel.FEDERAL, OrganizationType.CENTRAL_BANK,
        ("extract:identity", "extract:mandate"), common_name="Bank of Canada",
        sector="Central banking", public_mandate="Promote Canada's economic and financial welfare.",
        official_website="https://www.bankofcanada.ca/", languages=("en-CA", "fr-CA"),
    )
    procurement_id = "procurement:rfp-2026-026-retained-package"
    package_files = sorted((ROOT / "tests/fixtures/local/bank_of_canada_2026_026").rglob("*"))
    package_hash = sha256("".join(digest(p) for p in package_files if p.is_file()).encode()).hexdigest()
    inputs = GovernedBuyerInputs(
        buyer, evidence, OPPORTUNITY_ID, "canonical-opportunity/1", "a" * 64,
        (OPPORTUNITY_ID, "requirement:services", "requirement:accessibility", "requirement:bilingual"),
        (procurement_id,), package_hash, "context:boc-briefing-pack-demo", RETRIEVED,
        "analysis:bank-of-canada-opportunity", "1.0.0",
    )
    buyer_facts = (
        BuyerFact("fact:mandate", FactClass.AUTHORITATIVE_BUYER_FACT, FactKind.MANDATE,
                  "Its statutory purpose includes promoting Canada's economic and financial welfare.", SupportStatus.SUPPORTED,
                  ("extract:mandate",)),
    )
    public_facts = (
        BuyerFact("fact:plan", FactClass.PUBLIC_ORGANIZATIONAL_INFORMATION, FactKind.PUBLISHED_PRIORITY,
                  "The current strategic plan is organized around five themes.", SupportStatus.SUPPORTED,
                  ("extract:plan", "extract:annual-report")),
        BuyerFact("fact:workforce", FactClass.PUBLIC_ORGANIZATIONAL_INFORMATION, FactKind.ORGANIZATIONAL_CAPABILITY,
                  "A strategic priority calls for a workforce that continuously learns and adapts.", SupportStatus.SUPPORTED,
                  ("extract:workforce",)),
        BuyerFact("fact:accessibility", FactClass.PUBLIC_ORGANIZATIONAL_INFORMATION, FactKind.ACCESSIBILITY_COMMITMENT,
                  "The accessibility plan includes development of a medium-term accessible procurement strategy.", SupportStatus.SUPPORTED,
                  ("extract:accessibility",)),
        BuyerFact("fact:procurement-governance", FactClass.PUBLIC_ORGANIZATIONAL_INFORMATION, FactKind.GOVERNANCE,
                  "The published procurement policy commits the Bank to fair, open and transparent procurement.", SupportStatus.SUPPORTED,
                  ("extract:procurement",)),
    )
    procurement_facts = (
        BuyerFact("fact:current-procurement", FactClass.VERIFIED_PROCUREMENT_CONTEXT, FactKind.CURRENT_PROCUREMENT_ROLE,
                  "The retained package identifies the Bank of Canada as issuer of RFP 2026-026.", SupportStatus.SUPPORTED,
                  (procurement_id,)),
    )
    interpretations = (
        BuyerInterpretation("interpretation:workforce-context", InterpretationKind.PUBLISHED_PRIORITY_CONTEXT,
                            "The requested talent, learning and organizational development services directly overlap with the published workforce priority.",
                            Confidence.HIGH, SupportStatus.SUPPORTED,
                            ("extract:workforce", procurement_id), (), ("requirement:services",)),
        BuyerInterpretation("interpretation:accessibility-context", InterpretationKind.ORGANIZATIONAL_CONTEXT,
                            "The RFP's accessibility requirements sit within a documented organization-wide accessibility program.",
                            Confidence.MODERATE, SupportStatus.SUPPORTED,
                            ("extract:accessibility", procurement_id), (), ("requirement:accessibility",)),
    )
    unknowns = (
        BuyerUnknown("unknown:owner", UnknownKind.AMBIGUOUS_ORGANIZATIONAL_OWNERSHIP,
                     "The public evidence does not establish the internal business owner for RFP 2026-026.",
                     "No retained source names an accountable organizational unit.", (procurement_id,)),
        BuyerUnknown("unknown:needs", UnknownKind.UNAVAILABLE_PUBLIC_INFORMATION,
                     "The internal demand profile, participant groups and expected call volume are not established.",
                     "The retained public evidence does not provide this operational information.", (procurement_id,)),
    )
    analysis = BuyerIntelligenceAnalysis(
        "analysis:buyer:boc-rfp-2026-026", BUYER_ID, OPPORTUNITY_ID,
        "context:boc-briefing-pack-demo", governed_input_digest(inputs),
        tuple(sorted({*(e.extract_id for e in extracts), procurement_id})), buyer_facts, public_facts,
        procurement_facts, (), interpretations, (), (), unknowns, (),
        (
            BuyerManagementQuestion("question:ownership", "Which Bank function owns the work and will govern demand?", (), ("unknown:owner",), ()),
            BuyerManagementQuestion("question:demand", "What participant groups, volumes and timing assumptions should the team validate?", (), ("unknown:needs",), ()),
            BuyerManagementQuestion("question:categories", "Which service categories will the proposal team pursue?", (procurement_id,), (), ()),
        ),
        (
            BuyerLimitation("limitation:public-only", "Buyer Intelligence uses only the retained procurement package and the official public evidence registered in this corpus."),
            BuyerLimitation("limitation:no-intent", "Public priorities do not establish evaluator preferences, hidden intent or an award outcome."),
            BuyerLimitation("limitation:master-rfp", "The retained package does not include the master RFP document; unresolved opportunity conflicts remain visible."),
        ),
    )
    validate_buyer_intelligence(inputs, analysis)
    brief = build_buyer_brief(inputs, analysis)
    rendered = render_buyer_brief(brief)

    (OUT / "buyer_evidence_corpus.json").write_text(evidence.to_json() + "\n", encoding="utf-8")
    (OUT / "buyer_intelligence_analysis.json").write_text(analysis.to_json() + "\n", encoding="utf-8")
    (OUT / "buyer_brief.json").write_text(brief.to_json() + "\n", encoding="utf-8")
    (OUT / "02_BUYER_BRIEF.md").write_text("# Buyer Brief\n\n" + rendered.split("\n", 1)[1], encoding="utf-8")
    manifest = {
        "evaluation_only": True,
        "retrieved_on": RETRIEVED.isoformat(),
        "source_count": len(evidence.sources),
        "document_count": len(evidence.documents),
        "extract_count": len(evidence.extracts),
        "documents": [{"document_id": d.document_id, "title": d.title, "url": d.canonical_url,
                       "sha256": d.content_sha256} for d in evidence.documents],
        "procurement_package": {"file_count": len([p for p in package_files if p.is_file()]), "aggregate_sha256": package_hash,
                                "master_rfp_present": False},
    }
    (OUT / "acquisition_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    build()
