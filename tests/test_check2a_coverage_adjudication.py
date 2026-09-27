"""CHECK-2A: Requirement & Evaluation Coverage Adjudication.

Synthetic, deterministic tests (sections A-G) build the canonical buyer
package through the REAL full_analysis.build_canonical_package and a bidder
SubmissionPackage directly from CHECK-1 EvidenceItems -- no files, no
database. Every model call is a fake `adjudicate_fn`; every Anthropic entry
point is poisoned for the whole module (zero live provider calls).

Section H is the REAL Calgary 26-1603 (bid 1360) regression: the real run 34
raw snapshot + real buyer/bidder ZIPs (skipped, never faked, when the ZIPs
are absent) replaying the content-free record of the live CHECK-2A
acceptance run (tests/fixtures/calgary_26_1603_check2a_replay.json).
"""
from __future__ import annotations

import json
import os
import re
import sys
import zipfile

import pytest

sys.path.insert(0, os.path.dirname(__file__))

import check_coverage as cc  # noqa: E402
import fast_analysis  # noqa: E402
import full_analysis  # noqa: E402
import section_drafting as sd  # noqa: E402
import submission_package as sp  # noqa: E402

BID, ORG = 7001, "org-test"
HERE = os.path.dirname(__file__)


@pytest.fixture(autouse=True)
def _no_provider_calls(monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError("CHECK-2A tests must never reach a model provider")
    import config
    for mod in (config, fast_analysis, full_analysis):
        for attr in ("get_anthropic_client", "execute_messages_create"):
            if hasattr(mod, attr):
                monkeypatch.setattr(mod, attr, refuse)
    monkeypatch.setattr(full_analysis, "_call_model", refuse)
    monkeypatch.setattr(cc, "_default_model_call", refuse)


# ═══════════════════════════════════════════════════════════════════════
# Builders
# ═══════════════════════════════════════════════════════════════════════

def _doc(did, filename, role, *, secondary=(), sections=(), file_type="pdf", page_count=4):
    return sp.SubmissionDocument(
        submission_document_id=did, content_hash="h" + did, filename=filename, package_path=filename,
        file_type=file_type, lifecycle_status="extracted", included=True,
        role=sp.RoleClassification(role, "HIGH", "FILENAME", tuple(secondary)), parse_status="PARSED",
        parser="test", page_count=page_count, sections=tuple(sections),
        logical_artifact_id="LA-" + did)


def _item(did, role, kind, locator, content, location=None, sv=None, *, filename="f", bid=BID):
    return sp.EvidenceItem(
        evidence_id=sp.derive_evidence_id(bid, did, kind, locator), bid_id=bid, submission_document_id=did,
        document_role=role, kind=kind, location=dict(location or {}), content=content, structured_value=sv,
        provenance={"filename": filename, "file_id": did, "content_hash": "h" + did, "locator": locator})


def _sec(label_num, title, page, sid, parent=None):
    return sp.ProposalSection(sid, label_num, title, 1 if parent is None else 2, parent, page, page)


def _loc(page, sid, num, title, path=None):
    return {"page": page, "section_id": sid, "section_number": num, "section_title": title,
            "section_path": path or [f"{num} {title}".strip()]}


TECH, PRICE, SUBF, MP = "doc-tech", "doc-price", "doc-subform", "doc-mp"


def build_package(*, with_pricing=True, blank_price_cell=False, with_multiparty=True, with_subform=True,
                  tech_pages=4, bid=BID) -> sp.SubmissionPackage:
    docs, items = [], []
    tech_secs = (_sec("PART 1", "FIRM EXPERIENCE", 1, "S1"), _sec("PART 2", "TEAM EXPERIENCE", 2, "S2"),
                 _sec("PART 3", "SERVICE DELIVERY", 3, "S3"), _sec("PART 4", "PRICING", 4, "S4"),
                 _sec("PART 5", "CONSORTIUM", 4, "S5"))
    docs.append(_doc(TECH, "Technical Proposal.pdf", sp.ROLE_TECHNICAL_PROPOSAL,
                     secondary=(sp.ROLE_PRICING_FORM, sp.ROLE_MULTI_PARTY_FORM), sections=tech_secs,
                     page_count=tech_pages))
    t = lambda loc, content, page, sid, num, title, kind=sp.EVIDENCE_KIND_SECTION_TEXT, sv=None: items.append(
        _item(TECH, sp.ROLE_TECHNICAL_PROPOSAL, kind, loc, content, _loc(page, sid, num, title), sv,
              filename="Technical Proposal.pdf", bid=bid))
    t("p1b1", "Example 1: Acme Utility cohort leadership programme, 2024, CAD 90,000. Overview of objectives, "
              "content, delivery methods and duration. Outcomes: 92% completion, promotion rate up 15%.",
      1, "S1", "PART 1", "FIRM EXPERIENCE")
    t("p1b2", "Example 2: Northwind Health cohort programme, 2023. Overview of services and delivery methods. "
              "Challenges: remote shift workers; mitigated with evening virtual sessions.",
      1, "S1", "PART 1", "FIRM EXPERIENCE")
    t("p2b1", "Jane Doe, Account Manager, 15 years in HR consulting; main point of contact for the City.",
      2, "S2", "PART 2", "TEAM EXPERIENCE")
    t("p3b1", "Our six-stage delivery methodology: prepare, learn, apply, reinforce, integrate, sustain. "
              "City requests are acknowledged within one business day.", 3, "S3", "PART 3", "SERVICE DELIVERY")
    t("p4b1", "Pricing is provided in the separate price form.", 4, "S4", "PART 4", "PRICING")
    t("p4b2", "Acme and Beta Corp have formed a consortium.", 4, "S5", "PART 5", "CONSORTIUM")
    t("p4b9", "P a g e 4 | 4", 4, "S5", "PART 5", "CONSORTIUM")
    if with_pricing:
        docs.append(_doc(PRICE, "Price Form - Completed.xlsx", sp.ROLE_PRICING_FORM, file_type="xlsx",
                         page_count=None))
        p = lambda kind, loc, content, location, sv: items.append(
            _item(PRICE, sp.ROLE_PRICING_FORM, kind, loc, content, location, sv,
                  filename="Price Form - Completed.xlsx", bid=bid))
        rows = [(6, 1, "Cohort programme scenario A", "LS /per cohort", 25000),
                (7, 2, "Cohort programme scenario B", "LS /per cohort", None if blank_price_cell else 20000),
                (8, 3, "Travel Expenses incl. airfare", "Fixed fee", 2000)]
        for r, n, desc, uom, cost in rows:
            p(sp.EVIDENCE_KIND_SHEET_ROW, f"Price!R{r}", f"Price row {r}: {n} | {desc} | {uom} | {cost}",
              {"sheet": "Price", "row": r}, {"cells": [{"cell": f"A{r}", "value": n}, {"cell": f"B{r}", "value": desc},
                                                       {"cell": f"C{r}", "value": uom},
                                                       {"cell": f"D{r}", "value": cost}]})
            p(sp.EVIDENCE_KIND_SHEET_CELL, f"Price!D{r}", f"Price!D{r} [{uom}] (Cost) = {cost}",
              {"sheet": "Price", "cell": f"D{r}", "row": r, "column": "D"},
              {"value": cost, "label": uom, "column_header": "Cost", "is_input_cell": True, "is_formula": False,
               "completed": cost is not None})
    if with_subform:
        docs.append(_doc(SUBF, "Submission Form.pdf", sp.ROLE_SUBMISSION_FORM))
        s = lambda kind, loc, content, sv=None: items.append(
            _item(SUBF, sp.ROLE_SUBMISSION_FORM, kind, loc, content, _loc(1, "S1", "APPENDIX E", "SUBMISSION FORM"),
                  sv, filename="Submission Form.pdf", bid=bid))
        s(sp.EVIDENCE_KIND_FORM_FIELD, "p1t0f0", "Full Legal Name of Proponent: Acme Consulting",
          {"label": "Full Legal Name of Proponent:", "value": "Acme Consulting", "completed": True,
           "source": "pdf_form_table"})
        s(sp.EVIDENCE_KIND_SECTION_TEXT, "p1b5", "Conflicts of Interest (if any)")
        s(sp.EVIDENCE_KIND_SECTION_TEXT, "p1b6", "Instructions to complete the table below:")
        s(sp.EVIDENCE_KIND_TABLE_ROW, "p1t1r1", "Not Applicable | Not Applicable",
          {"columns": {"Name of Party": "Not Applicable", "Details": "Not Applicable"}, "completed": True})
        s(sp.EVIDENCE_KIND_SECTION_TEXT, "p1b9", "Legal actions, claims, lawsuits, or proceedings that could impact")
        s(sp.EVIDENCE_KIND_TABLE_ROW, "p1t2r1", "None | None",
          {"columns": {"Name of Party": "None", "Details": "None"}, "completed": True})
    if with_multiparty:
        docs.append(_doc(MP, "Multi-Party Confirmation Form.pdf", sp.ROLE_MULTI_PARTY_FORM))
        m = lambda kind, loc, content, sid, title, sv=None: items.append(
            _item(MP, sp.ROLE_MULTI_PARTY_FORM, kind, loc, content,
                  {"page": 1, "section_id": sid, "section_title": title, "section_path": [title]}, sv,
                  filename="Multi-Party Confirmation Form.pdf", bid=bid))
        m(sp.EVIDENCE_KIND_SECTION_TEXT, "p1b1", "MULTI-PARTY CONFIRMATION FORM", "S0", "")
        m(sp.EVIDENCE_KIND_SECTION_TEXT, "p1b3", "Beta Corp", "S1", "IDENTITY OF TEAM MEMBERS")
        m(sp.EVIDENCE_KIND_SECTION_TEXT, "p1b4", "2026-07-16 Acme Consulting", "S2", "LEAD TEAM MEMBER")
        m(sp.EVIDENCE_KIND_FORM_FIELD, "p1b5", "Per: Ann Lead", "S2", "LEAD TEAM MEMBER",
          {"label": "Per", "value": "Ann Lead", "completed": True})
        m(sp.EVIDENCE_KIND_SECTION_TEXT, "p1b6", "2026-07-16 Beta Corp Inc", "S3", "CONFIRMATION OF OTHER TEAM MEMBER")
        m(sp.EVIDENCE_KIND_FORM_FIELD, "p1b7", "Per: Bob Member", "S3", "CONFIRMATION OF OTHER TEAM MEMBER",
          {"label": "Per", "value": "Bob Member", "completed": True})
    return sp.SubmissionPackage(bid_id=bid, organization_id=ORG, package_digest="digest-" + str(bid),
                                documents=tuple(docs), registry=sp.SubmissionEvidenceRegistry(bid, items),
                                manifest=())


RFP = "RFP Main Document.docx"
ACK = "Proponent Acknowledgements.docx"

REQS = {
    "post_award": {"category": "Mandatory", "source_doc": RFP,
                   "description": "The Consultant shall provide post-facilitation support to participants during the "
                                  "term of the Agreement."},
    "buyer_process": {"category": "Supporting", "source_doc": RFP,
                      "description": "Pricing-calculation formula: Total weighted cost = 0.55 x item 1 + 0.45 x item 2."},
    "portal": {"category": "Rated", "source_doc": RFP,
               "description": "Social Procurement - Weight: 10%: Complete the 'Social Procurement Questionnaire' as "
                              "requested as a prerequisite of this RFP."},
    "pricing_form": {"category": "Mandatory", "source_doc": RFP,
                     "description": "Pricing must be provided in lump sum format for each cohort using the sample "
                                    "scenarios provided in the Excel spreadsheet."},
    "travel": {"category": "Mandatory", "source_doc": RFP,
               "description": "Travel costs must be captured within the Price Form."},
    "multi_party": {"category": "Mandatory", "source_doc": RFP,
                    "description": "Each proposal that is submitted on behalf of a Multi-Party Team must include a "
                                   "Multi-Party Confirmation Form completed and signed by all Team Members.",
                    "applicability_condition": "Each proposal that is submitted on behalf of a Multi-Party Team"},
    "coi_table": {"category": "Mandatory", "source_doc": ACK,
                  "description": "Proponent must provide complete Conflicts of Interest table in Submission Form "
                                 "(Appendix E), or confirm table is blank if no conflict of interest exists.",
                  "source_refs": [{"excerpt": "the Conflicts of Interest table in our Submission Form (Appendix E) "
                                              "includes a complete list of Conflicts of Interest"}]},
    "deemed": {"category": "Mandatory", "source_doc": ACK,
               "description": "Proponent must acknowledge receipt, examination, and understanding of the RFP and all "
                              "Addenda.",
               "source_refs": [{"excerpt": "We have received, examined, and understand the RFP and that all "
                                           "Addenda are part of the RFP."}]},
    "page_limit": {"category": "Supporting", "source_doc": RFP,
                   "description": "Maximum submission length is 20 pages."},
    "firm_experience": {"category": "Rated", "source_doc": RFP,
                        "description": "Provide two (2) examples where your firm delivered comparable services. "
                                       "At a minimum each example should provide: An overview of the services "
                                       "provided. Key outcomes or results achieved. Challenges and how they were "
                                       "mitigated."},
    "service": {"category": "Rated", "source_doc": RFP,
                "description": "3.1 Understanding of the Services: Describe your firm's methodology and approach. "
                               "Details should include: response times to City requests for urgent matters."},
    "empty": {"category": "Mandatory", "source_doc": RFP, "description": None},
}
ORDER = list(REQS)
EVAL = [
    {"stage": "Firm Experience", "weight": "30%", "threshold": "60%", "source_doc": RFP,
     "source_refs": [{"excerpt": "1 | Firm Experience | 30% | 60%"}]},
    {"stage": "Firm Experience", "weight": "20%", "source_doc": "QA Log.xlsx",
     "source_refs": [{"excerpt": "Under 1. Firm Experience the RFP asks proponents to provide two (2) examples "
                                 "where your firm delivered comparable services; weighting 20%"}]},
    {"stage": "Service Delivery", "weight": "30%", "source_doc": RFP,
     "source_refs": [{"excerpt": "3 | Service Delivery | 30% | N/A"}]},
    {"stage": "Price", "weight": "10%", "source_doc": RFP, "source_refs": [{"excerpt": "Price | 10% | N/A"}]},
    {"stage": "Item 3 - Travel Expenses", "weight": "10%", "source_doc": "Addendum Five.pdf",
     "source_refs": [{"excerpt": "Item 3 Travel Expenses Fixed fee $1,000.00 10% $100.00"}]},
]
BUYER_DOCS = [(ACK, "Proponent Acknowledgements\nBy submitting a proposal in response to the RFP, we (the "
                    "proponent) acknowledge and confirm the following.\nWe have received, examined, and understand "
                    "the RFP and that all Addenda are part of the RFP.\nTo the best of our knowledge, the Conflicts of "
                    "Interest table in our Submission Form (Appendix E) includes a complete list of Conflicts of "
                    "Interest."),
              (RFP, "Main RFP text without any deeming statement.")]


def canonical(reqs=None, evals=None, bid=BID):
    raw = [dict(REQS[k]) for k in (reqs or ORDER)]
    result = fast_analysis.FastAnalysisResult(requirements=raw, evaluation_criteria=list(evals if evals is not None
                                                                                          else EVAL))
    return full_analysis.build_canonical_package(result, bid_id=bid, analysis_run_id=1), raw


def req_id(key, reqs=None):
    return f"REQ-{(reqs or ORDER).index(key)}"


class FakeModel:
    """Records every call; answers from a per-object script. Aliases (PE#)
    are resolved from the batch the harness hands in."""

    def __init__(self, script=None, default=None):
        self.script = script or {}
        self.default = default
        self.calls = []

    def __call__(self, prompt, batch):
        self.calls.append({"prompt": prompt, "batch": batch})
        eid_to_alias = {v: k for k, v in batch["alias_to_eid"].items()}
        rows = []
        for t in batch["tasks"]:
            fn = self.script.get(t.obj.object_id, self.default)
            if fn is None:
                continue
            row = fn(t, eid_to_alias, batch)
            if row is not None:
                rows.append(dict(row, object_id=t.obj.object_id))
        return {"adjudications": rows}


def _alias_by_content(pkg, eid_to_alias, needle):
    for eid, alias in eid_to_alias.items():
        if needle.lower() in pkg.registry.get(eid, bid_id=pkg.bid_id).content.lower():
            return alias
    raise AssertionError(f"no issued evidence containing {needle!r}")


def run(pkg=None, reqs=None, evals=None, model=None, buyer_docs=BUYER_DOCS, **kw):
    pkg = pkg or build_package()
    cpkg, raw = canonical(reqs, evals)
    model = model or FakeModel()
    res = cc.run_check_coverage(cpkg, pkg, raw_requirements=raw, buyer_documents=buyer_docs,
                                adjudicate_fn=model, **kw)
    return res, model, pkg


# ═══════════════════════════════════════════════════════════════════════
# A. Scope gate (section 3)
# ═══════════════════════════════════════════════════════════════════════

class TestScopeGate:
    def test_post_award_obligation_is_never_a_proposal_gap(self):
        model = FakeModel(default=lambda t, a, b: {"status": "NOT_ADDRESSED", "requested_elements": [],
                                                  "evidence_ids": [], "reason": "not found"})
        res, model, _ = run(model=model)
        a = res.by_id()[req_id("post_award")]
        assert a.assurance_scope == cc.SCOPE_POST_AWARD
        assert a.status == cc.STATUS_NOT_APPLICABLE and a.deterministic_or_model == cc.METHOD_SCOPE_GATE
        assert all(req_id("post_award") not in [t.obj.object_id for t in c["batch"]["tasks"]] for c in model.calls)

    def test_buyer_process_item_is_not_a_proposal_gap(self):
        res, _, _ = run()
        a = res.by_id()[req_id("buyer_process")]
        assert a.assurance_scope == cc.SCOPE_BUYER_PROCESS and a.status == cc.STATUS_NOT_APPLICABLE

    def test_portal_native_item_is_not_verifiable_from_files(self):
        res, _, _ = run()
        a = res.by_id()[req_id("portal")]
        assert a.assurance_scope == cc.SCOPE_PORTAL_NATIVE
        assert a.status == cc.STATUS_NOT_VERIFIABLE and "portal" in a.ambiguity_or_review_reason

    def test_actual_submission_obligations_remain_checkable(self):
        res, _, _ = run()
        by = res.by_id()
        for key in ("pricing_form", "travel", "multi_party", "coi_table", "page_limit", "firm_experience"):
            assert by[req_id(key)].assurance_scope in cc.CHECKABLE_SCOPES, key

    def test_deemed_acknowledgement_uses_the_buyers_own_deeming_sentence(self):
        res, _, _ = run()
        a = res.by_id()[req_id("deemed")]
        assert a.assurance_scope == cc.SCOPE_DEEMED_BY_SUBMISSION and a.status == cc.STATUS_NOT_APPLICABLE
        assert "by submitting a proposal" in a.scope_basis
        # an artifact-anchored obligation from the SAME deeming document stays checkable
        assert res.by_id()[req_id("coi_table")].assurance_scope == cc.SCOPE_SUBMISSION_EVIDENCE
        # without the buyer corpus nothing is deemed (never guessed)
        res2, _, _ = run(buyer_docs=None)
        assert res2.by_id()[req_id("deemed")].assurance_scope == cc.SCOPE_SUBMISSION_RESPONSE

    def test_empty_buyer_wording_goes_to_human_review(self):
        res, _, _ = run()
        a = res.by_id()[req_id("empty")]
        assert a.status == cc.STATUS_HUMAN_REVIEW and a.assurance_scope == cc.SCOPE_HUMAN_REVIEW


# ═══════════════════════════════════════════════════════════════════════
# B. Deterministic adjudication (section 6)
# ═══════════════════════════════════════════════════════════════════════

class TestDeterministic:
    def test_completed_pricing_workbook(self):
        res, model, pkg = run()
        a = res.by_id()[req_id("pricing_form")]
        assert a.deterministic_or_model == cc.METHOD_DETERMINISTIC and a.status == cc.STATUS_ADDRESSED
        roles = {pkg.registry.get(e, bid_id=BID).document_role for e in a.evidence_ids}
        assert roles == {sp.ROLE_PRICING_FORM}
        cells = {pkg.registry.get(e, bid_id=BID).location.get("cell") for e in a.evidence_ids} - {None}
        assert {"D6", "D7", "D8"} <= cells
        assert all(req_id("pricing_form") not in [t.obj.object_id for t in c["batch"]["tasks"]] for c in model.calls)

    def test_blank_pricing_input_cell_is_partial_with_the_exact_cell(self):
        res, _, _ = run(pkg=build_package(blank_price_cell=True))
        a = res.by_id()[req_id("pricing_form")]
        assert a.status in (cc.STATUS_PARTIALLY_ADDRESSED, cc.STATUS_HUMAN_REVIEW)
        assert any("D7" in e["note"] for e in a.missing_elements)

    def test_travel_row(self):
        res, _, pkg = run()
        a = res.by_id()[req_id("travel")]
        assert a.status == cc.STATUS_ADDRESSED
        assert any("travel" in pkg.registry.get(e, bid_id=BID).content.lower() for e in a.evidence_ids)

    def test_required_multi_party_form_with_parties_and_signatures(self):
        res, _, pkg = run()
        a = res.by_id()[req_id("multi_party")]
        assert a.deterministic_or_model == cc.METHOD_DETERMINISTIC and a.status == cc.STATUS_ADDRESSED
        mp_ids = {i.evidence_id for i in pkg.registry.for_document(MP)}
        assert set(a.evidence_ids) & mp_ids
        names = " ".join(e["note"] for e in a.addressed_elements)
        assert "Acme Consulting" in names and "Beta Corp" in names
        assert any("signed" in e["element"] for e in a.addressed_elements)

    def test_explicit_declaration_table_value(self):
        res, _, pkg = run()
        a = res.by_id()[req_id("coi_table")]
        assert a.status == cc.STATUS_ADDRESSED and a.deterministic_or_model == cc.METHOD_DETERMINISTIC
        contents = [pkg.registry.get(e, bid_id=BID).content for e in a.evidence_ids]
        assert "Conflicts of Interest (if any)" in contents and "Not Applicable | Not Applicable" in contents
        assert all(pkg.registry.get(e, bid_id=BID).document_role == sp.ROLE_SUBMISSION_FORM for e in a.evidence_ids)

    def test_page_limit_from_parsed_page_count(self):
        res, _, _ = run()
        assert res.by_id()[req_id("page_limit")].status == cc.STATUS_ADDRESSED
        res2, _, _ = run(pkg=build_package(tech_pages=25))
        assert res2.by_id()[req_id("page_limit")].status == cc.STATUS_HUMAN_REVIEW

    def test_wrong_role_document_does_not_satisfy_role_specific_requirement(self):
        """The technical proposal's embedded CONSORTIUM section is NOT a
        multi-party confirmation form, and its embedded PRICING section is
        not a completed price form."""
        res, _, _ = run(pkg=build_package(with_multiparty=False, with_pricing=False))
        by = res.by_id()
        assert by[req_id("multi_party")].status == cc.STATUS_HUMAN_REVIEW
        assert by[req_id("pricing_form")].status == cc.STATUS_HUMAN_REVIEW
        for key in ("multi_party", "pricing_form"):
            assert by[req_id(key)].status not in (cc.STATUS_ADDRESSED, cc.STATUS_NOT_ADDRESSED)

    def test_absent_artifact_is_not_addressed_only_with_a_whole_package_search_basis(self):
        pkg = build_package(with_pricing=False)
        # remove the embedded pricing role so the absence is genuine
        docs = tuple(sp.SubmissionDocument(**{**d.__dict__, "role": sp.RoleClassification(
            d.role.role, d.role.confidence, d.role.basis, tuple(r for r in d.role.secondary_roles
                                                                 if r != sp.ROLE_PRICING_FORM))})
                     for d in pkg.documents)
        pkg = sp.SubmissionPackage(BID, ORG, pkg.package_digest, docs, pkg.registry, ())
        res, _, _ = run(pkg=pkg, reqs=["travel"])
        a = res.by_id()["REQ-0"]
        assert a.status == cc.STATUS_NOT_ADDRESSED
        assert a.search_basis["artifact_status"] == sp.MISSING_FROM_PACKAGE
        assert {d["document_role"] for d in a.search_basis["documents_searched"]} >= {
            sp.ROLE_TECHNICAL_PROPOSAL, sp.ROLE_SUBMISSION_FORM, sp.ROLE_MULTI_PARTY_FORM}
        assert a.search_basis["expected_roles"] == [sp.ROLE_PRICING_FORM]


class TestStructurallyUnverifiable:
    """Found on the real Calgary run: sentences the files can never prove
    must not be sent to the model and must never become a gap."""

    def _one(self, description, category="Mandatory", source_doc=RFP):
        REQS["_tmp"] = {"category": category, "source_doc": source_doc, "description": description}
        try:
            res, model, pkg = run(reqs=["_tmp"], evals=[])
        finally:
            REQS.pop("_tmp")
        return res.by_id()["REQ-0"], model, pkg

    def test_prescribed_pricing_assumption_is_not_verifiable_not_missing(self):
        a, model, pkg = self._one(
            "The Consultant shall provide post-facilitation support per participant. Support may include, but is "
            "not limited to: answering questions that may be required for the class. For the purposes of the "
            "Pricing Form; Pricing shall be based on three (3) hours per participant. 25 participants X 3 hours = "
            "75 hours")
        assert a.deterministic_or_model == cc.METHOD_DETERMINISTIC and not model.calls
        assert a.status == cc.STATUS_NOT_VERIFIABLE
        assert {pkg.registry.get(e, bid_id=BID).document_role for e in a.evidence_ids} == {sp.ROLE_PRICING_FORM}
        assert len(a.unverifiable_elements) == 1          # the lead-in fragment is merged, not double-counted

    def test_legal_status_without_a_proof_request_is_not_verifiable(self):
        a, model, _ = self._one("Proponents must be registered in the provincial registry to carry on business.")
        assert a.status == cc.STATUS_NOT_VERIFIABLE and not model.calls
        b, model2, _ = self._one("Proponents must be registered and must provide proof of registration with "
                                 "the proposal.")
        assert b.deterministic_or_model == cc.METHOD_MODEL and model2.calls

    def test_wording_deleted_by_a_buyer_amendment_is_not_a_missing_element(self):
        REQS["rfp_rates"] = {"category": "Mandatory", "source_doc": RFP,
                             "description": "Pricing Form requirement: Complete the pricing table by providing "
                                            "proposed hourly rates. All prices must be flat rate only."}
        REQS["addendum"] = {"category": "Mandatory", "source_doc": "Addendum One.pdf",
                            "description": "Pricing Form Instructions: Instruction #1: Delete hourly rate and "
                                           "replace it with price."}
        try:
            def rates(t, al, b):
                cell = _alias_by_content(rates.pkg, al, "Price!D6")
                return {"status": "PARTIALLY_ADDRESSED", "evidence_ids": [cell], "requested_elements": [
                    {"element": "Complete the pricing table by providing proposed hourly rates", "coverage": "PARTIAL",
                     "evidence_ids": [cell]},
                    {"element": "All prices must be flat rate only", "coverage": "ADDRESSED", "evidence_ids": [cell]}]}
            pkg = build_package()
            rates.pkg = pkg
            cpkg, raw = canonical(["rfp_rates", "addendum"], [])
            model = FakeModel({"REQ-0": rates, "REQ-1": lambda t, al, b: None})
            res = cc.run_check_coverage(cpkg, pkg, raw_requirements=raw, adjudicate_fn=model)
            a = res.by_id()["REQ-0"]
            assert a.status == cc.STATUS_ADDRESSED and not a.missing_elements
            sup = a.validation["superseded_elements"]
            assert sup and sup[0]["superseded_by"] == "REQ-1" and sup[0]["deleted"] == "hourly rate"
            assert "amendments_in_force" in model.calls[0]["prompt"]
        finally:
            REQS.pop("rfp_rates")
            REQS.pop("addendum")

    def test_exact_buyer_phrase_retrieval_prefers_rare_phrases(self):
        pkg = build_package()
        extra = _item(TECH, sp.ROLE_TECHNICAL_PROPOSAL, sp.EVIDENCE_KIND_SECTION_TEXT, "p3b7",
                      "A designated Account Manager serves as the single point of contact for the client.",
                      _loc(3, "S3", "PART 3", "SERVICE DELIVERY"))
        boiler = [_item(MP, sp.ROLE_MULTI_PARTY_FORM, sp.EVIDENCE_KIND_SECTION_TEXT, f"bp{n}",
                        f"The Lead Team Member confirms clause {n} on behalf of each team member.", {"page": 2})
                  for n in range(6)]
        pkg = sp.SubmissionPackage(BID, ORG, "d", pkg.documents,
                                   sp.SubmissionEvidenceRegistry(BID, boiler + list(pkg.registry) + [extra]), ())
        got = cc.phrase_matches("Identify the team member that will serve as the main point of contact.", pkg)
        assert extra.evidence_id in got
        # a rare exact buyer phrase outranks boilerplate repeating a common one,
        # even though the boilerplate comes first in reading order
        assert all(got.index(extra.evidence_id) < got.index(b.evidence_id) for b in boiler if b.evidence_id in got)


# ═══════════════════════════════════════════════════════════════════════
# C. Semantic (model) adjudication (section 7)
# ═══════════════════════════════════════════════════════════════════════

FE_ELEMENTS = ["An overview of the services provided", "Key outcomes or results achieved",
               "Challenges and how they were mitigated"]


def _fe(statuses, status):
    def fn(t, alias, batch):
        pkg = fn.pkg
        overview = _alias_by_content(pkg, alias, "Example 1")
        chall = _alias_by_content(pkg, alias, "Challenges: remote")
        els = []
        for el, cov in zip(FE_ELEMENTS, statuses):
            ids = [] if cov == "ABSENT" else [overview if "Challenges" not in el else chall]
            els.append({"element": el, "coverage": cov, "evidence_ids": ids, "note": "n"})
        return {"status": status, "requested_elements": els, "evidence_ids": [overview],
                "evidence_summary": "two examples", "reason": "outcomes missing" if status != "ADDRESSED" else ""}
    return fn


class TestSemantic:
    def _run_fe(self, statuses, status):
        pkg = build_package()
        fn = _fe(statuses, status)
        fn.pkg = pkg
        res, model, _ = run(pkg=pkg, reqs=["firm_experience", "service"], evals=[],
                            model=FakeModel({"REQ-0": fn}))
        return res.by_id()["REQ-0"], model

    def test_all_requested_elements_present_is_addressed(self):
        a, _ = self._run_fe(["ADDRESSED"] * 3, "ADDRESSED")
        assert a.status == cc.STATUS_ADDRESSED and a.deterministic_or_model == cc.METHOD_MODEL
        assert [e["element"] for e in a.addressed_elements] == FE_ELEMENTS

    def test_some_elements_absent_is_partial_with_exact_missing_elements(self):
        a, _ = self._run_fe(["ADDRESSED", "ABSENT", "ADDRESSED"], "PARTIALLY_ADDRESSED")
        assert a.status == cc.STATUS_PARTIALLY_ADDRESSED
        assert [e["element"] for e in a.missing_elements] == ["Key outcomes or results achieved"]

    def test_model_addressed_with_an_absent_element_is_structurally_downgraded(self):
        a, _ = self._run_fe(["ADDRESSED", "ABSENT", "ADDRESSED"], "ADDRESSED")
        assert a.status == cc.STATUS_PARTIALLY_ADDRESSED
        assert any("-> PARTIALLY_ADDRESSED" in d for d in a.validation["downgrades"])

    def test_no_material_response_after_search_is_not_addressed(self):
        fn = lambda t, a, b: {"status": "NOT_ADDRESSED", "requested_elements": [
            {"element": "Key outcomes or results achieved", "coverage": "ABSENT", "evidence_ids": []}],
            "evidence_ids": [], "reason": "no example describes outcomes"}
        res, _, _ = run(reqs=["firm_experience"], evals=[], model=FakeModel({"REQ-0": fn}))
        a = res.by_id()["REQ-0"]
        assert a.status == cc.STATUS_NOT_ADDRESSED
        assert a.search_basis["candidates_considered"] and a.search_basis["documents_searched"]
        assert a.missing_elements[0]["element"] == "Key outcomes or results achieved"

    def test_ambiguous_evidence_is_human_review(self):
        fn = lambda t, a, b: {"status": "HUMAN_REVIEW_REQUIRED", "requested_elements": [],
                              "evidence_ids": [], "reason": "examples conflict on dates"}
        res, _, _ = run(reqs=["firm_experience"], evals=[], model=FakeModel({"REQ-0": fn}))
        a = res.by_id()["REQ-0"]
        assert a.status == cc.STATUS_HUMAN_REVIEW and "conflict" in a.ambiguity_or_review_reason

    def test_skipped_or_failed_objects_fail_closed(self):
        res, _, _ = run(reqs=["firm_experience", "service"], evals=[], model=FakeModel({}))
        assert {res.by_id()[i].status for i in ("REQ-0", "REQ-1")} == {cc.STATUS_HUMAN_REVIEW}

        def boom(prompt, batch):
            raise RuntimeError("provider down")
        cpkg, raw = canonical(["firm_experience"], [])
        r = cc.run_check_coverage(cpkg, build_package(), raw_requirements=raw, adjudicate_fn=boom)
        assert r.by_id()["REQ-0"].status == cc.STATUS_HUMAN_REVIEW and r.provider_calls == 1
        assert "provider down" in r.by_id()["REQ-0"].ambiguity_or_review_reason

    def test_model_receives_only_the_bounded_batch(self):
        res, model, pkg = run()
        assert model.calls
        for c in model.calls:
            prompt = c["prompt"]
            issued = set(c["batch"]["alias_to_eid"].values())
            assert len(issued) <= cc.MAX_EVIDENCE_PER_BATCH and len(issued) < len(pkg.registry)
            for item in pkg.registry:
                if item.evidence_id not in issued and len(item.content) > 30:
                    assert item.content not in prompt
            assert "P a g e 4 | 4" not in prompt          # page furniture is never sent
            assert not re.search(r"\bEV-[0-9a-f]{20}\b", prompt)   # only short PE ids are issued


# ═══════════════════════════════════════════════════════════════════════
# D. Evidence-id integrity (section 10)
# ═══════════════════════════════════════════════════════════════════════

class TestIntegrity:
    def _one(self, row, reqs=("firm_experience",), pkg=None):
        res, model, pkg = run(pkg=pkg, reqs=list(reqs), evals=[],
                              model=FakeModel({"REQ-0": lambda t, a, b: row(t, a, b)}))
        return res.by_id()["REQ-0"], pkg

    def test_hallucinated_evidence_id_is_rejected(self):
        a, _ = self._one(lambda t, al, b: {"status": "ADDRESSED", "requested_elements": [],
                                           "evidence_ids": ["PE999", "EV-00000000000000000000"]})
        assert a.status == cc.STATUS_HUMAN_REVIEW and not a.evidence_ids
        reasons = {r["reason"] for r in a.validation["rejected_evidence_ids"]}
        assert reasons == {cc.REJECT_NOT_ISSUED, cc.REJECT_CROSS_BID}

    def test_buyer_source_id_cannot_masquerade_as_bidder_evidence(self):
        a, _ = self._one(lambda t, al, b: {"status": "ADDRESSED", "requested_elements": [],
                                           "evidence_ids": ["CE1", "REQ-0", "CRIT-price"]})
        assert a.status == cc.STATUS_HUMAN_REVIEW and not a.evidence_ids
        assert {r["reason"] for r in a.validation["rejected_evidence_ids"]} == {cc.REJECT_BUYER_SOURCE}

    def test_cross_bid_evidence_is_rejected(self):
        other = build_package(bid=BID + 1)
        foreign = next(iter(other.registry)).evidence_id
        a, _ = self._one(lambda t, al, b: {"status": "ADDRESSED", "requested_elements": [],
                                           "evidence_ids": [foreign]})
        assert a.status == cc.STATUS_HUMAN_REVIEW
        assert a.validation["rejected_evidence_ids"][0]["reason"] == cc.REJECT_CROSS_BID
        cpkg, raw = canonical(["firm_experience"], [], bid=BID)
        with pytest.raises(sp.CrossBidEvidenceError):
            cc.plan_check_coverage(cpkg, other, raw_requirements=raw)

    def test_wrong_artifact_evidence_is_rejected_where_role_is_material(self):
        req = {"category": "Mandatory", "source_doc": RFP,
               "description": "Proponents must provide pricing based only on the scenarios outlined in the pricing "
                              "form."}
        REQS["pricing_semantic"] = req
        try:
            def row(t, al, b):
                # an ISSUED alias whose item is neither the price form nor
                # the technical proposal's embedded PRICING section
                wrong = [k for k, v in b["alias_to_eid"].items()
                         if row.pkg.registry.get(v, bid_id=BID).submission_document_id != PRICE
                         and "separate price form" not in row.pkg.registry.get(v, bid_id=BID).content]
                assert wrong, "fixture must issue at least one other-artifact candidate"
                return {"status": "ADDRESSED", "requested_elements": [], "evidence_ids": wrong[:1]}
            pkg = build_package()
            row.pkg = pkg
            cpkg, raw = canonical(["pricing_semantic"], [])
            model = FakeModel({"REQ-0": row})
            res = cc.run_check_coverage(cpkg, pkg, raw_requirements=raw, adjudicate_fn=model)
            a = res.by_id()["REQ-0"]
            assert a.status == cc.STATUS_HUMAN_REVIEW
            assert any(r["reason"] == cc.REJECT_WRONG_ARTIFACT for r in a.validation["rejected_evidence_ids"])
        finally:
            REQS.pop("pricing_semantic")

    def test_duplicate_evidence_does_not_inflate_coverage(self):
        pkg = build_package()
        ids = [i.evidence_id for i in pkg.registry.for_document(TECH)][:2]
        assert cc.distinct_evidence([ids[0], ids[0], ids[1], ids[0]], pkg) == ids
        # a content-identical second item never counts twice
        dup = _item(TECH, sp.ROLE_TECHNICAL_PROPOSAL, sp.EVIDENCE_KIND_FORM_FIELD, "dup",
                    pkg.registry.get(ids[0], bid_id=BID).content, {"page": 1})
        pkg2 = sp.SubmissionPackage(BID, ORG, "d", pkg.documents,
                                    sp.SubmissionEvidenceRegistry(BID, list(pkg.registry) + [dup]), ())
        assert cc.distinct_evidence([ids[0], dup.evidence_id], pkg2) == [ids[0]]
        a, _ = self._one(lambda t, al, b: {"status": "ADDRESSED", "requested_elements": [],
                                           "evidence_ids": ["PE1", "PE1", "PE1"]})
        assert len(a.evidence_ids) == 1

    def test_non_verbatim_requested_element_is_dropped(self):
        a, _ = self._one(lambda t, al, b: {"status": "PARTIALLY_ADDRESSED", "evidence_ids": ["PE1"],
                                           "requested_elements": [
                                               {"element": "ISO 9001 certification", "coverage": "ABSENT",
                                                "evidence_ids": []}]})
        assert a.status == cc.STATUS_HUMAN_REVIEW       # no genuine buyer element remains missing
        assert any("not verbatim" in d for d in a.validation["downgrades"])

    def test_model_not_addressed_contradicted_by_package_artifacts_is_rejected(self):
        req = {"category": "Mandatory", "source_doc": RFP,
               "description": "Proponents must provide pricing based only on the scenarios outlined in the pricing "
                              "form."}
        REQS["pricing_semantic"] = req
        try:
            cpkg, raw = canonical(["pricing_semantic"], [])
            model = FakeModel({"REQ-0": lambda t, a, b: {"status": "NOT_ADDRESSED", "requested_elements": [],
                                                         "evidence_ids": [], "reason": "price form missing"}})
            res = cc.run_check_coverage(cpkg, build_package(), raw_requirements=raw, adjudicate_fn=model)
            a = res.by_id()["REQ-0"]
            assert a.status == cc.STATUS_HUMAN_REVIEW
            assert any("contradicted by package" in d for d in a.validation["downgrades"])
            assert cc.artifact_blind_regression_screen(res, build_package()) == []
        finally:
            REQS.pop("pricing_semantic")

    def test_reuses_section_drafting_registry_and_reconciliation(self, monkeypatch):
        seen = {"registry": 0, "claims": 0, "structured": 0}
        for name, key in (("evidence_id_registry", "registry"), ("reconcile_material_claims", "claims"),
                          ("reconcile_structured_result", "structured")):
            orig = getattr(sd, name)

            def wrap(*a, _orig=orig, _key=key, **k):
                seen[_key] += 1
                return _orig(*a, **k)
            monkeypatch.setattr(sd, name, wrap)
        pkg = build_package()
        fn = _fe(["ADDRESSED"] * 3, "ADDRESSED")
        fn.pkg = pkg
        run(pkg=pkg, reqs=["firm_experience"], evals=[], model=FakeModel({"REQ-0": fn}))
        assert all(v > 0 for v in seen.values()), seen


# ═══════════════════════════════════════════════════════════════════════
# E. Evaluation criteria (section 11 / 12)
# ═══════════════════════════════════════════════════════════════════════

class TestCriteria:
    def _res(self, fe_statuses=("ADDRESSED", "ABSENT", "ADDRESSED"), fe_status="PARTIALLY_ADDRESSED"):
        pkg = build_package()
        fn = _fe(list(fe_statuses), fe_status)
        fn.pkg = pkg
        svc = lambda t, al, b: {"status": "ADDRESSED", "evidence_ids": [_alias_by_content(pkg, al, "six-stage")],
                                "requested_elements": [
                                    {"element": "response times to City requests for urgent matters",
                                     "coverage": "ADDRESSED", "evidence_ids": [_alias_by_content(pkg, al, "six-stage")]}]}
        res, model, _ = run(pkg=pkg, reqs=["firm_experience", "service", "travel"],
                            model=FakeModel({"REQ-0": fn, "REQ-1": svc}))
        return res, pkg

    def test_weight_threshold_and_weight_variants_retained(self):
        res, _ = self._res()
        fe = res.by_id()["CRIT-firm-experience"]
        assert fe.buyer_weight == "30%" and fe.buyer_threshold == "60%"
        assert set(fe.buyer_weight_variants) == {"30%", "20%"}
        assert "differing weights" in fe.ambiguity_or_review_reason

    def test_partial_criterion_lists_exact_missing_elements_with_their_buyer_source(self):
        res, _ = self._res()
        fe = res.by_id()["CRIT-firm-experience"]
        assert fe.deterministic_or_model == cc.METHOD_DERIVED and fe.linked_requirement_ids == ("REQ-0",)
        assert fe.status == cc.STATUS_PARTIALLY_ADDRESSED
        assert fe.missing_elements == [dict(res.by_id()["REQ-0"].missing_elements[0], source_object_id="REQ-0")]
        assert set(fe.evidence_ids) == set(res.by_id()["REQ-0"].evidence_ids)   # shared, not duplicated

    def test_numbered_criterion_links_to_its_numbered_prompt(self):
        res, _ = self._res()
        sd_ = res.by_id()["CRIT-service-delivery"]
        assert sd_.linked_requirement_ids == ("REQ-1",) and sd_.status == cc.STATUS_ADDRESSED

    def test_pricing_criteria_use_the_price_form_not_the_narrative(self):
        res, pkg = self._res()
        for cid in ("CRIT-price", "CRIT-item-3-travel-expenses"):
            a = res.by_id()[cid]
            assert a.status == cc.STATUS_ADDRESSED and a.deterministic_or_model == cc.METHOD_DETERMINISTIC
            assert {pkg.registry.get(e, bid_id=BID).document_role for e in a.evidence_ids} == {sp.ROLE_PRICING_FORM}
        assert "price level is not assessed" in res.by_id()["CRIT-price"].evidence_summary

    def test_no_predicted_score_anywhere(self):
        res, _ = self._res()
        blob = json.dumps(res.to_dict())
        for key in ("score", "points", "percent", "rating", "predicted", "readiness", "recommend", "strength",
                    "weakness"):
            assert not re.search(rf'"[a-z_]*{key}[a-z_]*"\s*:', blob), key
        assert not re.search(r"\b\d{1,3}\s*/\s*\d{2,3}\b", " ".join(a.evidence_summary for a in res.adjudications))
        # a percentage only ever appears as buyer-stated metadata / buyer wording
        for a in res.adjudications:
            d = a.to_dict()
            for k in ("status", "evidence_summary"):
                assert "%" not in str(d[k]) or k == "evidence_summary" and "%" in a.buyer_expectation

    def test_every_criterion_gets_an_independent_record(self):
        res, _ = self._res()
        crits = [a for a in res.adjudications if a.buyer_object_type == cc.OBJECT_CRITERION]
        assert len(crits) == len(canonical()[0].scoped_criteria)
        assert all(a.status in cc.STATUSES for a in crits)


# ═══════════════════════════════════════════════════════════════════════
# F. Call discipline (section 8)
# ═══════════════════════════════════════════════════════════════════════

class TestCallDiscipline:
    def test_one_call_per_coherent_batch_not_per_requirement(self):
        res, model, _ = run()
        model_objects = [a for a in res.adjudications if a.deterministic_or_model == cc.METHOD_MODEL]
        assert res.provider_calls == len(model.calls) == len(res.batches) <= cc.MODEL_CALL_TARGET
        assert len(model_objects) >= res.provider_calls

    def test_hard_ceiling_is_enforced_before_any_call(self):
        def task(i, dom):
            obj = cc.BuyerObject(object_id=f"REQ-{i}", object_type=cc.OBJECT_REQUIREMENT, wording="x")
            ee = sp.ExpectedEvidence((sp.ROLE_TECHNICAL_PROPOSAL,), "TECHNICAL_RESPONSE", "NOT_STATED", True, False, "")
            ev = [f"EV-{i:020d}"] * 1
            return cc.ModelTask(obj, cc.ScopeDecision(cc.SCOPE_EVALUATION_RESPONSE, ""), ee, None,
                                [f"EV-{i}-{k}" for k in range(cc.MAX_EVIDENCE_PER_BATCH)], dom)
        tasks = [task(i, f"D{i}") for i in range(cc.MODEL_CALL_HARD_CEILING + 1)]
        with pytest.raises(cc.BatchPlanningError):
            cc.plan_model_batches(tasks)
        small = [cc.ModelTask(t.obj, t.scope, t.expected, None, [f"E{i}"], f"D{i}") for i, t in enumerate(tasks)]
        planned = cc.plan_model_batches(small)
        assert len(planned) <= cc.MODEL_CALL_TARGET
        assert sum(len(b["tasks"]) for b in planned) == len(small)

    def test_nothing_is_persisted(self, monkeypatch):
        import database
        for name in dir(database):
            if name.startswith(("create_", "get_or_create_", "insert_", "update_", "upsert_", "delete_")):
                monkeypatch.setattr(database, name, lambda *a, **k: (_ for _ in ()).throw(
                    AssertionError("CHECK-2A must not write")), raising=False)
        res, _, _ = run()
        assert res.adjudications


# ═══════════════════════════════════════════════════════════════════════
# H. REAL Calgary 26-1603 (bid 1360) regression
# ═══════════════════════════════════════════════════════════════════════

RUN34 = os.path.join(HERE, "fixtures", "calgary_26_1603_run34_raw_snapshot.json")
REPLAY = os.path.join(HERE, "fixtures", "calgary_26_1603_check2a_replay.json")
BIDDER_ZIP = os.getenv("CHECK11_BIDDER_ZIP", r"C:\Users\feras\Downloads\OneDrive_2_9-27-2026.zip")
BUYER_ZIP = os.getenv("CHECK11_BUYER_ZIP", r"C:\Users\feras\Downloads\Calgary RFP.zip")
needs_real = pytest.mark.skipif(not (os.path.exists(BUYER_ZIP) and os.path.exists(BIDDER_ZIP)
                                     and os.path.exists(REPLAY)),
                                reason="real Calgary ZIPs / live CHECK-2A replay record not on this machine")


@pytest.fixture(scope="module")
def calgary():
    import extractor
    with open(RUN34, encoding="utf-8") as fh:
        result = fast_analysis.deserialize_fast_analysis_result(json.load(fh))
    documents = []
    with zipfile.ZipFile(BUYER_ZIP) as z:
        for n in z.namelist():
            if not n.endswith("/"):
                base = n.rsplit("/", 1)[-1]
                documents.append((base, extractor.extract_document_with_metadata(z.read(n), base)[0]))
    cpkg = full_analysis.build_canonical_package(result, bid_id=1360, analysis_run_id=34, documents=documents)
    with open(BIDDER_ZIP, "rb") as fh:
        bidder = sp.build_submission_package([(os.path.basename(BIDDER_ZIP), fh.read())], bid_id=1360,
                                             organization_id="org-calgary")
    with open(REPLAY, encoding="utf-8") as fh:
        replay = json.load(fh)

    def replay_fn(prompt, batch):
        rec = replay["batches"][batch["batch_id"]]
        assert sorted(t.obj.object_id for t in batch["tasks"]) == sorted(rec["objects"])
        eid_to_alias = {v: k for k, v in batch["alias_to_eid"].items()}
        rows = []
        for r in rec["adjudications"]:
            rows.append({"object_id": r["object_id"], "status": r["status"],
                         "evidence_ids": [eid_to_alias.get(e, e) for e in r["evidence_ids"]],
                         "requested_elements": [{"element": e["element"], "coverage": e["coverage"],
                                                 "evidence_ids": [eid_to_alias.get(x, x) for x in e["evidence_ids"]]}
                                                for e in r["requested_elements"]],
                         "reason": "recorded live adjudication (reason text omitted from content-free fixture)"})
        return {"adjudications": rows}

    res = cc.run_check_coverage(cpkg, bidder, raw_requirements=result.requirements, buyer_documents=documents,
                                adjudicate_fn=replay_fn)
    return {"cpkg": cpkg, "bidder": bidder, "result": res, "replay": replay}


@needs_real
class TestRealCalgary:
    def test_counts_and_call_budget(self, calgary):
        res = calgary["result"]
        assert len(res.adjudications) == 60
        assert sum(a.buyer_object_type == cc.OBJECT_CRITERION for a in res.adjudications) == 13
        assert res.provider_calls == len(calgary["replay"]["batches"]) <= cc.MODEL_CALL_TARGET

    def test_replay_reproduces_the_live_final_statuses(self, calgary):
        live = calgary["replay"]["final"]
        got = {a.buyer_object_id: a.status for a in calgary["result"].adjudications}
        assert got == {k: v["status"] for k, v in live.items()}
        for a in calgary["result"].adjudications:
            assert sorted(a.evidence_ids) == sorted(live[a.buyer_object_id]["evidence_ids"]), a.buyer_object_id

    def test_all_13_scoped_criteria_have_traceable_adjudications(self, calgary):
        bidder = calgary["bidder"]
        for a in calgary["result"].adjudications:
            if a.buyer_object_type != cc.OBJECT_CRITERION:
                continue
            assert a.status in cc.STATUSES and a.source_provenance["authoritative_source"]
            for e in a.evidence_ids:
                assert bidder.registry.get(e, bid_id=1360)
            if a.status in (cc.STATUS_ADDRESSED, cc.STATUS_PARTIALLY_ADDRESSED):
                assert a.evidence_ids

    def test_req46_uses_the_real_b2_form(self, calgary):
        a = calgary["result"].by_id()["REQ-46"]
        b2 = calgary["bidder"].documents_with_roles([sp.ROLE_MULTI_PARTY_FORM], include_secondary=False)[0]
        assert a.status == cc.STATUS_ADDRESSED and a.deterministic_or_model == cc.METHOD_DETERMINISTIC
        b2_ids = {i.evidence_id for i in calgary["bidder"].registry.for_document(b2.submission_document_id)}
        assert set(a.evidence_ids) & b2_ids
        notes = " ".join(e["note"] for e in a.addressed_elements)
        assert "Phoenix Consulting Canada" in notes and "Inquisitive Talent" in notes

    def test_real_price_workbook_and_appendix_e_are_used(self, calgary):
        bidder, by = calgary["bidder"], calgary["result"].by_id()
        price = bidder.documents_with_roles([sp.ROLE_PRICING_FORM], include_secondary=False)[0]
        subf = bidder.documents_with_roles([sp.ROLE_SUBMISSION_FORM], include_secondary=False)[0]
        price_ids = {i.evidence_id for i in bidder.registry.for_document(price.submission_document_id)}
        subf_ids = {i.evidence_id for i in bidder.registry.for_document(subf.submission_document_id)}
        for cid in ("CRIT-price", "CRIT-pricing"):
            assert by[cid].status == cc.STATUS_ADDRESSED and set(by[cid].evidence_ids) <= price_ids
        for rid in ("REQ-4", "REQ-6"):
            assert by[rid].status == cc.STATUS_ADDRESSED and set(by[rid].evidence_ids) & price_ids
        for rid in ("REQ-33", "REQ-37"):
            assert by[rid].status == cc.STATUS_ADDRESSED and set(by[rid].evidence_ids) <= subf_ids

    def test_old_artifact_blind_false_missing_findings_do_not_recur(self, calgary):
        res, bidder = calgary["result"], calgary["bidder"]
        assert cc.artifact_blind_regression_screen(res, bidder) == []
        for claim in ("Price Form missing", "Submission declarations missing",
                      "Multi-party confirmation not provided"):
            assert sp.screen_absence_claim(claim, bidder)["verdict"] == sp.ABSENCE_CONTRADICTED_BY_PACKAGE
        pricing_like = [a for a in res.adjudications if sp.ROLE_PRICING_FORM in a.expected_evidence_roles
                        or a.buyer_object_id.startswith("CRIT-item") or a.buyer_object_id in ("CRIT-price",
                                                                                              "CRIT-pricing")]
        assert pricing_like and all(a.status != cc.STATUS_NOT_ADDRESSED for a in pricing_like)

    def test_non_submission_objects_are_excluded_not_gaps(self, calgary):
        for a in calgary["result"].adjudications:
            if a.assurance_scope in cc.EXCLUDED_SCOPES:
                assert a.status == cc.STATUS_NOT_APPLICABLE
            if a.assurance_scope == cc.SCOPE_PORTAL_NATIVE:
                assert a.status == cc.STATUS_NOT_VERIFIABLE
