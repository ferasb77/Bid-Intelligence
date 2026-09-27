"""
CHECK-2C: client-facing Proposal Assurance workspace.

Every test is deterministic: no live database, no live provider. Every
model / adjudication / execution entry point is poisoned by the autouse
`provider_calls` fixture and each test asserts the recorded count, so an
accidental call anywhere in the rendering path fails loudly.

Two fixture families:
  * a Calgary-shaped synthetic durable result (60 buyer objects, 13 scoped
    criteria, the real run-37 status distribution, weights/thresholds and
    B2 / Appendix D / Appendix E / portal-native / human-review shapes) --
    Calgary is the acceptance case, never a special case in the UI code;
  * the REAL CHECK-2B service + tests/check2b_fake_db.FakeCheckDB (the
    in-memory migration-022 contract), to prove the page reads through
    check_run_service's DB reconstruction and that "Run CHECK again" with
    identical inputs is REUSED_COMPLETE with zero provider calls.
"""
from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
import types
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

sys.path.insert(0, os.path.dirname(__file__))

import auth_session  # noqa: E402
import check_coverage as cc  # noqa: E402
import check_run_service as csr  # noqa: E402
import config  # noqa: E402
import full_analysis  # noqa: E402
import submission_package as sp  # noqa: E402
import tenancy  # noqa: E402
from components import check_workspace_view as cwv  # noqa: E402
from pages import stage_check_assurance as page  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BID, ORG = 1360, "org-calgary"
OTHER_BID = 9999
RUN, SNAP = 37, 9

# ═══════════════════════════════════════════════════════════════════════
# Zero-provider-call instrumentation (autouse)
# ═══════════════════════════════════════════════════════════════════════

POISONED = ((cc, "run_check_coverage"), (cc, "plan_check_coverage"), (cc, "_default_model_call"),
            (full_analysis, "_call_model"), (config, "get_anthropic_client"), (config, "execute_messages_create"),
            (csr, "_execute_check_run"))


def _reset_streamlit_globals():
    """Other suites may leave a form / delta-generator context on the
    process-global Streamlit stack (same isolation as test_password_recovery)."""
    import streamlit as st
    try:  # only this page's keys: other suites keep shared module-level session state here
        for key in [k for k in st.session_state.keys() if str(k).startswith("chk_")]:
            del st.session_state[key]
    except Exception:
        pass
    try:
        from streamlit.delta_generator_singletons import context_dg_stack, get_default_dg_stack_value
        context_dg_stack.set(get_default_dg_stack_value())
        st._main._form_data = None
    except Exception:
        pass


@pytest.fixture(autouse=True)
def isolated_streamlit():
    _reset_streamlit_globals()
    yield
    _reset_streamlit_globals()


@pytest.fixture(autouse=True)
def provider_calls(monkeypatch):
    calls = []
    for mod, name in POISONED:
        def boom(*a, _n=f"{mod.__name__}.{name}", **k):
            calls.append(_n)
            raise AssertionError(f"forbidden provider/adjudication call: {_n}")
        monkeypatch.setattr(mod, name, boom)
    return calls


# ═══════════════════════════════════════════════════════════════════════
# Calgary-shaped durable result (synthetic content, real shapes)
# ═══════════════════════════════════════════════════════════════════════

TP, PD, AE, B2 = "doc-tp", "doc-price", "doc-appe", "doc-b2"
TP_NAME = "Appendix C_Technical Proposal.pdf"
PD_NAME = "Appendix D_Price Form.xlsx"
AE_NAME = "APPENDIX E_Submission Form.pdf"
B2_NAME = "B2 Multi-Party Confirmation Form.pdf"


def _doc_row(did, name, role, ftype, i):
    return {"id": i, "bid_id": BID, "submission_document_id": did, "content_hash": f"h{i}", "filename": name,
            "package_path": f"pkg/{name}", "file_type": ftype, "lifecycle_status": "extracted", "included": True,
            "document_role": role, "role_confidence": "HIGH", "role_basis": "FILENAME", "parse_status": "PARSED",
            "page_count": 20 if ftype == "pdf" else None, "sheets": ["Price Form"] if ftype == "xlsx" else [],
            "evidence_count": 3, "logical_artifact_id": f"LA-{did}"}


def _ev(eid, did, role, kind, location, content, sv=None, name="", bid=BID):
    return {"evidence_id": eid, "bid_id": bid, "submission_document_id": did, "document_role": role, "kind": kind,
            "location": location, "content": content, "structured_value": sv,
            "provenance": {"filename": name, "locator": eid}}


def calgary_package(bid=BID):
    docs = [_doc_row(TP, TP_NAME, "TECHNICAL_PROPOSAL", "pdf", 1), _doc_row(PD, PD_NAME, "PRICING_FORM", "xlsx", 2),
            _doc_row(AE, AE_NAME, "SUBMISSION_FORM", "pdf", 3), _doc_row(B2, B2_NAME, "MULTI_PARTY_FORM", "pdf", 4)]
    for d in docs:
        d["bid_id"] = bid
    items = [
        _ev("EV-tp1", TP, "TECHNICAL_PROPOSAL", "SECTION_TEXT",
            {"page": 5, "section_number": "PART 4", "section_title": "TEAM EXPERIENCE"},
            "Name: A. Lead\nTitle: Account Manager\n\nExperience: 15+ years", name=TP_NAME, bid=bid),
        _ev("EV-tp2", TP, "TECHNICAL_PROPOSAL", "FORM_FIELD",
            {"page": 4, "section_title": "FIRM EXPERIENCE", "table_index": 0, "row_index": 1},
            "Company Name: Example Client", {"label": "Company Name:", "value": "Example Client"}, TP_NAME, bid),
        _ev("EV-tp3", TP, "TECHNICAL_PROPOSAL", "SECTION_TEXT", {"page": 9, "section_title": "Service Delivery"},
            "Methodology " * 120, name=TP_NAME, bid=bid),
        _ev("EV-pd1", PD, "PRICING_FORM", "SHEET_CELL", {"sheet": "Price Form", "cell": "D6", "row": 6},
            "Price Form!D6 = 48000", {"label": "Item 1 lump sum", "value": "$48,000"}, PD_NAME, bid),
        _ev("EV-pd2", PD, "PRICING_FORM", "SHEET_CELL", {"sheet": "Price Form", "cell": "D7", "row": 7},
            "Price Form!D7 = 52000", {"label": "Item 2 lump sum", "value": "$52,000"}, PD_NAME, bid),
        _ev("EV-pd3", PD, "PRICING_FORM", "SHEET_CELL", {"sheet": "Price Form", "cell": "D8", "row": 8},
            "Price Form!D8 = 3000", {"label": "Item 3 travel", "value": "$3,000"}, PD_NAME, bid),
        _ev("EV-ae1", AE, "SUBMISSION_FORM", "FORM_FIELD",
            {"page": 2, "section_title": "CONFLICTS OF INTEREST", "table_index": 1, "row_index": 0},
            "Conflict of interest: Not Applicable", {"label": "Conflict of interest", "value": "Not Applicable"},
            AE_NAME, bid),
        _ev("EV-ae2", AE, "SUBMISSION_FORM", "FORM_FIELD",
            {"page": 3, "section_title": "LEGAL ACTIONS", "table_index": 2, "row_index": 0},
            "Legal actions: Not Applicable", {"label": "Legal actions", "value": "Not Applicable"}, AE_NAME, bid),
        _ev("EV-b21", B2, "MULTI_PARTY_FORM", "SECTION_TEXT", {"page": 1}, "Multi-Party Confirmation Form",
            name=B2_NAME, bid=bid),
        _ev("EV-b22", B2, "MULTI_PARTY_FORM", "FORM_FIELD", {"page": 2, "section_title": "TEAM MEMBER"},
            "Per: Party One Signatory", {"label": "Per", "value": "Party One Signatory"}, B2_NAME, bid),
        _ev("EV-b23", B2, "MULTI_PARTY_FORM", "FORM_FIELD",
            {"page": 3, "section_title": "CONFIRMATION OF OTHER TEAM MEMBER(S)"},
            "Per: Party Two Signatory", {"label": "Per", "value": "Party Two Signatory"}, B2_NAME, bid),
    ]
    return sp.package_from_persisted_rows(bid, ORG, "pkg-digest", docs, items)


A, P, NA, NV, HR, NAD = (cc.STATUS_ADDRESSED, cc.STATUS_PARTIALLY_ADDRESSED, cc.STATUS_NOT_APPLICABLE,
                         cc.STATUS_NOT_VERIFIABLE, cc.STATUS_HUMAN_REVIEW, cc.STATUS_NOT_ADDRESSED)

#: (id, label, weight, variants, threshold, status, scope, evidence)
CRITERIA = [
    ("CRIT-2-2-other-personnel", "Evaluation Criteria 2 – Team Experience, subsection 2.2 – Other Personnel",
     "10%", (), None, P, "EVALUATION_RESPONSE", ["EV-tp1"]),
    ("CRIT-firm-experience", "Firm Experience", "20%", ("20%", "30%"), "60%", P, "EVALUATION_RESPONSE", ["EV-tp2"]),
    ("CRIT-item-1", "Item 1 - Cohort Program Development & Delivery", "55%", (), None, A, "EVALUATION_RESPONSE",
     ["EV-pd1"]),
    ("CRIT-item-2", "Item 2 - Cohort Program Development & Delivery", "35%", (), None, A, "EVALUATION_RESPONSE",
     ["EV-pd2"]),
    ("CRIT-item-3-travel-expenses", "Item 3 - Travel Expenses", "10%", (), None, A, "EVALUATION_RESPONSE", ["EV-pd3"]),
    ("CRIT-key-personnel", "Key Personnel Main point of contact", "10%", (), None, P, "EVALUATION_RESPONSE",
     ["EV-tp1"]),
    ("CRIT-other-personnel", "Other Personnel", "10%", (), None, P, "EVALUATION_RESPONSE", ["EV-tp1"]),
    ("CRIT-price", "Price", "10%", (), None, A, "EVALUATION_RESPONSE", ["EV-pd1", "EV-pd2", "EV-pd3"]),
    ("CRIT-pricing", "Pricing", "10%", (), None, A, "EVALUATION_RESPONSE", ["EV-pd1", "EV-pd2", "EV-pd3"]),
    ("CRIT-service-delivery", "Service Delivery", "30%", (), None, P, "EVALUATION_RESPONSE", ["EV-tp3"]),
    ("CRIT-social-procurement", "Social Procurement", "10%", (), None, NV, "PORTAL_NATIVE", []),
    ("CRIT-team-experience", "Team Experience and Qualifications", "20%", (), None, P, "EVALUATION_RESPONSE",
     ["EV-tp1"]),
    ("CRIT-understanding", "Understanding of the Services", None, (), None, P, "EVALUATION_RESPONSE", ["EV-tp3"]),
]
REQ_ADDRESSED = {4: ["EV-pd1"], 6: ["EV-pd3"], 8: ["EV-tp1"], 10: ["EV-pd1"], 14: ["EV-tp2"], 17: ["EV-pd1"],
                 18: ["EV-tp1"], 22: ["EV-pd2"], 25: ["EV-pd1"], 33: ["EV-ae1"], 37: ["EV-ae2"], 40: ["EV-pd1"],
                 46: ["EV-b21", "EV-b22", "EV-b23"]}
REQ_PARTIAL = {41: ["EV-tp2"], 42: ["EV-tp1"], 43: ["EV-tp1"], 44: ["EV-tp3"]}
REQ_NV = {2: "SUBMISSION_EVIDENCE_REQUIRED", 3: "SUBMISSION_RESPONSE_REQUIRED", 27: "SUBMISSION_EVIDENCE_REQUIRED",
          38: "PORTAL_NATIVE", 45: "PORTAL_NATIVE"}
REQ_HR = {5: "SUBMISSION_EVIDENCE_REQUIRED", 16: "HUMAN_REVIEW_REQUIRED"}
NA_SCOPES = ("BUYER_PROCESS", "POST_AWARD_OBLIGATION", "INFORMATIONAL", "DEEMED_BY_SUBMISSION")
PORTAL_REASON = ("response is completed in the buyer's e-procurement portal; the uploaded files cannot prove "
                 "whether it was completed")
SRC = {"source_docs": ["RFP 26-1603.docx"],
       "source_refs": [{"source_doc": "RFP 26-1603.docx", "section": "APPENDIX C - EVALUATION", "page": 40,
                        "sheet": None, "excerpt": "Buyer source excerpt."}]}


def _el(text, cov, ids=(), src=None, note=""):
    d = {"element": text, "coverage": cov, "evidence_ids": list(ids), "note": note}
    if src:
        d["source_object_id"] = src
    return d


def _adj(oid, otype, scope, status, wording, **kw):
    return cc.CheckAdjudication(buyer_object_id=oid, buyer_object_type=otype, assurance_scope=scope,
                                scope_basis=kw.pop("scope_basis", "basis"), status=status,
                                buyer_expectation=wording, source_provenance=kw.pop("source_provenance", SRC), **kw)


def calgary_result() -> cc.CheckCoverageResult:
    adjs = []
    for i in range(47):
        rid = f"REQ-{i}"
        if i in REQ_ADDRESSED:
            ids = REQ_ADDRESSED[i]
            kw = dict(evidence_ids=tuple(ids), addressed_elements=[_el(f"element of {rid}", "ADDRESSED", ids)],
                      deterministic_or_model="DETERMINISTIC", buyer_category="Mandatory",
                      expected_evidence_roles=("TECHNICAL_PROPOSAL",))
            wording = f"Proponents must provide {rid} content."
            if i == 46:
                wording = ("Each proposal submitted by a Multi-Party Team must include a Multi-Party Confirmation "
                           "Form completed and signed by all Team Members.")
                kw.update(applicability="SUBMISSION_WIDE", expected_evidence_roles=("MULTI_PARTY_FORM",),
                          evidence_summary="submitted as 'B2 Multi-Party Confirmation Form.pdf'; parties identified",
                          addressed_elements=[_el("Multi-Party Confirmation Form included", "ADDRESSED", ["EV-b21"]),
                                              _el("executed (signed) by all team members", "ADDRESSED",
                                                  ["EV-b22", "EV-b23"])],
                          source_provenance={**SRC, "required_form": "Multi-Party Confirmation Form"})
            if i in (33, 37):
                kw.update(expected_evidence_roles=("SUBMISSION_FORM",))
            adjs.append(_adj(rid, cc.OBJECT_REQUIREMENT, "SUBMISSION_EVIDENCE_REQUIRED", A, wording, **kw))
        elif i in REQ_PARTIAL:
            ids = REQ_PARTIAL[i]
            adjs.append(_adj(rid, cc.OBJECT_REQUIREMENT, "EVALUATION_RESPONSE", P,
                             f"{rid}: provide A, B, C, D and E.", buyer_category="Rated", evidence_ids=tuple(ids),
                             deterministic_or_model="MODEL", batch_id="B1",
                             addressed_elements=[_el(f"{rid} element A", "ADDRESSED", ids),
                                                 _el(f"{rid} element B", "ADDRESSED", ids)],
                             missing_elements=[_el(f"{rid} element C", "ABSENT"),
                                               _el(f"{rid} element D", "PARTIAL", ids)],
                             expected_evidence_roles=("TECHNICAL_PROPOSAL",)))
        elif i in REQ_NV:
            scope = REQ_NV[i]
            reason = PORTAL_REASON if scope == "PORTAL_NATIVE" else \
                "a completed price is present, but a lump-sum price does not disclose its pricing assumption"
            adjs.append(_adj(rid, cc.OBJECT_REQUIREMENT, scope, NV, f"{rid} buyer wording.",
                             ambiguity_or_review_reason=reason, buyer_category="Mandatory",
                             deterministic_or_model="SCOPE_GATE" if scope == "PORTAL_NATIVE" else "DETERMINISTIC",
                             unverifiable_elements=[] if scope == "PORTAL_NATIVE" else
                             [_el(f"{rid} pricing assumption", "NOT_VERIFIABLE", ["EV-pd1"], note=reason)]))
        elif i in REQ_HR:
            adjs.append(_adj(rid, cc.OBJECT_REQUIREMENT, REQ_HR[i], HR, "" if i == 16 else f"{rid} buyer wording.",
                             ambiguity_or_review_reason=("canonical requirement carries no buyer wording; nothing "
                                                         "to check") if i == 16 else
                             "element needs review: scope limitation cannot be read from a completed price",
                             buyer_category="Mandatory", deterministic_or_model="SCOPE_GATE" if i == 16 else "MODEL",
                             batch_id=None if i == 16 else "B1"))
        else:
            adjs.append(_adj(rid, cc.OBJECT_REQUIREMENT, NA_SCOPES[i % 4], NA, f"{rid} informational wording.",
                             ambiguity_or_review_reason="not a submission obligation", buyer_category="Supporting",
                             deterministic_or_model="SCOPE_GATE"))
    for oid, label, w, variants, thr, status, scope, ids in CRITERIA:
        kw = dict(buyer_label=label, buyer_weight=w, buyer_weight_variants=tuple(variants), buyer_threshold=thr,
                  evidence_ids=tuple(ids), deterministic_or_model="DERIVED_FROM_LINKED_REQUIREMENTS",
                  expected_evidence_roles=("TECHNICAL_PROPOSAL",))
        if status == A:
            kw["addressed_elements"] = [_el(f"{label} priced", "ADDRESSED", ids)]
            kw["deterministic_or_model"] = "DETERMINISTIC"
        elif status == P:
            kw["addressed_elements"] = [_el(f"{label}: demonstrated element", "ADDRESSED", ids, "REQ-41")]
            kw["missing_elements"] = [_el(f"{label}: key outcomes achieved for the client", "ABSENT", (), "REQ-41"),
                                      _el(f"{label}: examples from the past five years", "PARTIAL", ids, "REQ-41")]
        else:
            kw["ambiguity_or_review_reason"] = "[REQ-45] " + PORTAL_REASON
        adjs.append(_adj(oid, cc.OBJECT_CRITERION, scope, status, f"{label}\n[REQ-44] criterion wording.", **kw))
    return cc.CheckCoverageResult(bid_id=BID, contract_version="check-2a.1.0", buyer_package_digest="b",
                                  submission_package_digest="s", adjudications=adjs, provider_calls=0, batches=[])


def status_dict(status="COMPLETE", run_id=RUN, **kw):
    return {"run_id": run_id, "bid_id": BID, "status": status, "is_terminal": status in cwv.TERMINAL_RUN,
            "source_analysis_run_id": 34, "source_package_snapshot_id": SNAP,
            "created_at": "2026-09-27T15:38:11+00:00", "started_at": "2026-09-27T15:38:12+00:00",
            "completed_at": "2026-09-27T15:38:25+00:00" if status in ("COMPLETE", "PARTIAL") else None,
            "failed_at": "2026-09-27T16:00:00+00:00" if status == "FAILED" else None,
            "failure_reason": kw.get("failure_reason"), "stuck": {"stuck": kw.get("stuck", False)},
            "progress": {"semantic_batches_total": 4, "semantic_batches_complete": 1}}


class FakeService:
    """Stands in for tenancy's CHECK-2B read wrappers (reads counted)."""

    def __init__(self, status="COMPLETE", result=None, package=None, payload=None, prior=None):
        self.status = status_dict(status) if isinstance(status, str) else status
        self.result = result if result is not None else calgary_result()
        self.package = package if package is not None else calgary_package()
        self.payload = payload or {"semantic_batches": []}
        self.prior = prior               # (run_id, status) returned for run_id=None (service default)
        self.reads = {"status": 0, "result": 0, "package": 0}
        self.starts = []

    def get_status(self, bid_id, organization_id, run_id=None, *, after_sequence=0):
        self.reads["status"] += 1
        return self.status

    def get_result(self, bid_id, organization_id, run_id=None):
        self.reads["result"] += 1
        if run_id is None:
            if not self.prior:
                return None
            rid, rst = self.prior
        else:
            rid, rst = run_id, self.status["status"] if self.status else "COMPLETE"
        run = {"id": rid, "bid_id": BID, "status": rst, "source_package_snapshot_id": SNAP,
               "completed_at": "2026-09-27T15:38:25+00:00"}
        return {"run": run, "result": self.result, "result_payload": self.payload, "semantic_batches": [],
                "is_complete": rst == "COMPLETE", "result_digest_verified": True}

    def load_package(self, bid_id, organization_id, package_snapshot_id):
        self.reads["package"] += 1
        return self.package

    def start(self, bid_id, organization_id, **kw):
        self.starts.append(kw)
        return {"outcome": "REUSED_COMPLETE", "run": {"id": RUN}}


@pytest.fixture
def svc(monkeypatch):
    s = FakeService()
    install(monkeypatch, s)
    return s


def install(monkeypatch, s):
    monkeypatch.setattr(tenancy, "get_check_run_status_for_organization", s.get_status)
    monkeypatch.setattr(tenancy, "get_check_run_result_for_organization", s.get_result)
    monkeypatch.setattr(tenancy, "load_submission_evidence_package_for_organization", s.load_package)
    monkeypatch.setattr(tenancy, "start_check_run_for_organization", s.start)
    monkeypatch.setattr(tenancy, "get_bid_authenticated",
                        lambda token, bid_id: {"id": bid_id, "client": "The City of Calgary", "file_number": "26-1603",
                                               "title": "RFP 26-1603 - Design and Delivery Services"})
    monkeypatch.setattr(auth_session, "current_session", lambda: {"access_token": "t"})
    monkeypatch.setattr(auth_session, "current_auth_context",
                        lambda: types.SimpleNamespace(organization_id=ORG, user_id="u1"))


SCRIPT = f"""
from pages.stage_check_assurance import page_check_assurance
page_check_assurance({BID})
"""


def run_app():
    return AppTest.from_string(SCRIPT, default_timeout=60).run()


def page_text(app) -> str:
    """Rendered markdown, excluding the injected <style> block."""
    return "\n".join(m.value for m in app.markdown if not m.value.lstrip().startswith("<style>"))


def adjs():
    return cwv.adjudications(calgary_result())


def index():
    return cwv.build_evidence_index(calgary_package(), BID, [e for a in adjs() for e in cwv.cited_evidence_ids(a)])


def by_id(oid):
    return next(a for a in adjs() if a["buyer_object_id"] == oid)


# ═══════════════════════════════════════════════════════════════════════
# A. Existing durable run
# ═══════════════════════════════════════════════════════════════════════

class TestExistingDurableRun:
    def test_opening_renders_latest_complete_run_with_zero_calls(self, svc, provider_calls):
        app = run_app()
        assert not app.exception
        text = page_text(app)
        assert "Run 37" in text and "Complete" in text and "The City of Calgary" in text and "26-1603" in text
        assert provider_calls == [] and svc.starts == []
        assert svc.reads["result"] == 1 and svc.reads["package"] == 1

    def test_page_never_starts_a_run_on_open(self, svc):
        run_app()
        run_app()
        assert svc.starts == []

    def test_status_comes_from_durable_run_not_result_rows(self, svc):
        svc.status = status_dict("RUNNING")
        app = run_app()
        text = page_text(app)
        assert "is running" in text and "Addressed" not in text          # rows are never rendered for a live run
        assert svc.reads["result"] == 0


class TestRealServiceReconstruction:
    """The page reads through the real tenancy -> check_run_service path
    (DB-row reconstruction), using the CHECK-2B in-memory migration-022
    contract (FakeCheckDB)."""

    @pytest.fixture
    def durable(self, monkeypatch):
        import test_check2b_durable_runs as t2b
        from check2b_fake_db import FakeCheckDB
        f = FakeCheckDB()
        f.add_fast_run(t2b.BID, t2b.FAST_RUN)
        pkg = t2b.build_package(bid=t2b.BID)
        f.add_snapshot(t2b.BID, t2b.SNAPSHOT, [i.evidence_id for i in pkg.registry])
        f.install(monkeypatch.setattr)
        inputs = t2b.make_inputs()
        # Execution is permitted ONLY for this one setup run (injected adjudicator, no provider).
        poisoned = {"_execute_check_run": csr._execute_check_run, "run_check_coverage": cc.run_check_coverage,
                    "plan_check_coverage": cc.plan_check_coverage}
        monkeypatch.setattr(csr, "_execute_check_run", _REAL_EXECUTE)
        monkeypatch.setattr(cc, "run_check_coverage", _REAL_RUN)
        monkeypatch.setattr(cc, "plan_check_coverage", _REAL_PLAN)
        out = csr.start_check_run(t2b.BID, t2b.ORG, inputs_loader=t2b.loader_for(inputs),
                                  adjudicate_fn=t2b.EchoModel(), execution=csr.EXECUTION_INLINE)
        assert out["outcome"] == "CREATED"
        monkeypatch.setattr(csr, "_execute_check_run", poisoned["_execute_check_run"])
        monkeypatch.setattr(cc, "run_check_coverage", poisoned["run_check_coverage"])
        monkeypatch.setattr(cc, "plan_check_coverage", poisoned["plan_check_coverage"])
        monkeypatch.setattr(tenancy, "get_bid_for_organization",
                            lambda bid_id, org: {"id": bid_id} if org == t2b.ORG else None)
        monkeypatch.setattr(tenancy, "load_submission_evidence_package_for_organization",
                            lambda bid_id, org, snap: pkg if int(bid_id) == t2b.BID else None)
        return types.SimpleNamespace(fake=f, t2b=t2b, run_id=out["run"]["id"], inputs=inputs, pkg=pkg)

    def test_bundle_is_the_db_reconstruction(self, durable, monkeypatch, provider_calls):
        spy = []
        real = csr.reconstruct_result
        monkeypatch.setattr(csr, "reconstruct_result", lambda stored, rows: spy.append(len(rows)) or real(stored, rows))
        t2b = durable.t2b
        status = page.load_status(t2b.BID, t2b.ORG)["status"]
        assert status["status"] == "COMPLETE" and status["run_id"] == durable.run_id
        bundle = page.load_bundle(t2b.BID, t2b.ORG, status["run_id"], {})
        assert bundle["error"] is None and bundle["digest_verified"] is True
        assert spy == [len(durable.fake.adjudications)] and len(bundle["adjs"]) == len(durable.fake.adjudications)
        persisted = sorted(r["buyer_object_id"] for r in durable.fake.adjudications)
        assert sorted(a["buyer_object_id"] for a in bundle["adjs"]) == persisted
        cited = {e for a in bundle["adjs"] for e in cwv.cited_evidence_ids(a)}
        assert cited and cited <= set(bundle["index"])                 # every cited id resolved in THIS bid
        assert provider_calls == []

    def test_run_check_again_identical_inputs_is_reused_complete_zero_calls(self, durable, monkeypatch,
                                                                             provider_calls):
        t2b = durable.t2b
        monkeypatch.setattr(csr, "load_check_inputs", t2b.loader_for(durable.inputs))
        runs_before = len(durable.fake.runs)
        session = {}
        out = page.request_start(t2b.BID, t2b.ORG, "sk-test", session)
        assert out["outcome"] == "REUSED_COMPLETE" and out["run"]["id"] == durable.run_id
        assert len(durable.fake.runs) == runs_before and provider_calls == []
        assert session["chk_outcome_" + str(t2b.BID)] == "REUSED_COMPLETE"

    def test_cross_org_cannot_render(self, durable):
        t2b = durable.t2b
        with pytest.raises(tenancy.AccessDeniedError):
            page.load_status(t2b.BID, "org-evil")
        with pytest.raises(tenancy.AccessDeniedError):
            page.load_bundle(t2b.BID, "org-evil", durable.run_id, {})

    def test_foreign_bid_run_id_cannot_render(self, durable, monkeypatch):
        t2b = durable.t2b
        monkeypatch.setattr(tenancy, "get_bid_for_organization", lambda bid_id, org: {"id": bid_id})
        with pytest.raises(tenancy.AccessDeniedError):
            page.load_bundle(t2b.OTHER_BID, t2b.ORG, durable.run_id, {})


_REAL_EXECUTE = csr._execute_check_run
_REAL_RUN = cc.run_check_coverage
_REAL_PLAN = cc.plan_check_coverage


# ═══════════════════════════════════════════════════════════════════════
# B. Overview
# ═══════════════════════════════════════════════════════════════════════

class TestOverview:
    def test_status_counts_match_persisted_statuses(self):
        ov = cwv.overview(adjs())
        assert dict(ov["counts"]) == {A: 18, P: 11, NAD: 0, NV: 6, HR: 2}
        assert ov["excluded"] == 23 and ov["total"] == 60 and ov["criteria"] == 13 and ov["requirements"] == 47

    def test_excluded_count_is_separate_and_not_a_deficiency(self):
        html = cwv.render_counts(cwv.overview(adjs()))
        assert "23 buyer objects classified as non-submission / informational" in html
        assert "not proposal gaps" in html
        assert len(re.findall(r'class="ck-count[ "]', html)) == 5 and 'data-status="NOT_APPLICABLE"' not in html

    def test_no_overall_numeric_score_anywhere(self, svc):
        app = run_app()
        text = page_text(app)
        chrome = (cwv.render_counts(cwv.overview(adjs())) + cwv.render_legend()
                  + cwv.render_header({"client": "c", "title": "t", "file_number": "1"},
                                      cwv.run_view(status_dict()), []))
        assert "%" not in chrome
        for banned in ("score", "readiness", "probability", "compliant", "/10", "win "):
            assert banned not in chrome.lower(), banned
        low = text.lower()
        for banned in ("estimated score", "predicted score", "readiness", "win probability", "% compliant",
                       "overall score", "quality score"):
            assert banned not in low, banned

    def test_every_percentage_on_the_page_is_buyer_stated(self, svc):
        text = page_text(run_app())
        stated = {w for c in CRITERIA for w in ([c[2]] + list(c[3]) + [c[4]]) if w}
        found = set(re.findall(r"\d+(?:\.\d+)?%", text))
        assert found and found <= stated, found - stated


# ═══════════════════════════════════════════════════════════════════════
# C. Criteria
# ═══════════════════════════════════════════════════════════════════════

class TestCriteria:
    def test_all_13_criteria_represented_in_attention_first_order(self):
        crits = cwv.criteria(adjs())
        assert len(crits) == 13
        statuses = [c["status"] for c in crits]
        assert statuses[:7] == [P] * 7 and statuses[7] == NV and statuses[8:] == [A] * 5
        partial_names = [c["buyer_label"] for c in crits[:3]]
        # highest stated weight first (Firm Experience states 20% / 30%), ties in persisted order
        assert partial_names == ["Firm Experience", "Service Delivery", "Team Experience and Qualifications"]

    def test_all_13_rendered_on_the_page_with_weights_and_thresholds(self, svc):
        text = page_text(run_app())
        for oid, label, w, variants, thr, *_ in CRITERIA:
            assert f'data-object="{oid}"' in text, oid
        assert "Buyer weight 20% / 30%" in text and "Minimum threshold 60%" in text
        assert "Buyer weight 55%" in text and "Buyer weight 30%" in text

    def test_weight_is_buyer_metadata_never_a_predicted_mark(self):
        html = cwv.render_card(by_id("CRIT-service-delivery"), index())
        assert "Buyer weight 30%" in html
        assert not re.search(r"\d+\s*/\s*30", html) and "estimated" not in html.lower()

    def test_partial_missing_elements_rendered_concretely(self):
        html = cwv.render_card(by_id("CRIT-firm-experience"), index())
        assert "✓ Demonstrated (1)" in html and "◐ Not demonstrated (2)" in html
        assert "Firm Experience: key outcomes achieved for the client" in html
        assert "Not found in the submitted files" in html and "Only partly demonstrated" in html
        assert "from REQ-41" in html
        assert "asks for 3 recorded elements. The submission demonstrates 1; 2 are not demonstrated" in html
        for vague in ("could be improved", "weak response", "needs more detail"):
            assert vague not in html.lower()

    def test_addressed_is_compact_with_strongest_evidence(self):
        html = cwv.render_card(by_id("CRIT-item-1"), index())
        assert "t-ok" in html and PD_NAME in html and "Cell D6" in html
        assert "Demonstrated (" not in html and "Buyer asked" not in html

    def test_concise_expectation_drops_repeated_label(self):
        a = by_id("CRIT-service-delivery")
        assert cwv.concise_expectation(a) == "[REQ-44] criterion wording."


# ═══════════════════════════════════════════════════════════════════════
# D. Detail
# ═══════════════════════════════════════════════════════════════════════

class TestDetail:
    def test_buyer_and_bidder_sides_are_distinct(self):
        html, _ = cwv.render_detail(by_id("REQ-46"), index())
        assert '<div class="ck-side buyer">' in html and '<div class="ck-side bidder">' in html
        assert html.index("What the buyer asked for") < html.index("What the bidder submitted") \
            < html.index("CHECK conclusion")

    def test_buyer_provenance(self):
        html, _ = cwv.render_detail(by_id("REQ-46"), index())
        assert "RFP 26-1603.docx" in html and "section APPENDIX C - EVALUATION" in html and "page 40" in html
        assert "Required form" in html and "Multi-Party Confirmation Form" in html
        assert "submission wide" in html

    def test_req46_backed_by_b2_with_multiple_evidence_items(self):
        html, _ = cwv.render_detail(by_id("REQ-46"), index())
        assert html.count(B2_NAME) == 3 and "Multi-party form" in html
        assert "Page 2" in html and "Section CONFIRMATION OF OTHER TEAM MEMBER(S)" in html
        assert "Party Two Signatory" in html and "Supports: executed (signed) by all team members" in html

    def test_pricing_backed_by_appendix_d_cells(self):
        html, _ = cwv.render_detail(by_id("CRIT-price"), index())
        assert html.count(PD_NAME) == 3 and "Pricing form" in html and "Worksheet cell" in html
        assert "Sheet Price Form" in html and "Cell D7" in html and "&#36;52,000" in html   # '$' never raw

    def test_declarations_backed_by_appendix_e(self):
        for rid in ("REQ-33", "REQ-37"):
            html, _ = cwv.render_detail(by_id(rid), index())
            assert AE_NAME in html and "Submission form" in html and "Not Applicable" in html

    def test_excerpts_are_bounded(self):
        html, _ = cwv.render_detail(by_id("CRIT-service-delivery"), index())
        assert "Methodology " * 60 not in html and "…" in html
        ev = index()["EV-tp3"]
        assert len(ev["excerpt"]) <= cwv.EXCERPT_CHARS + 1

    def test_newlines_never_break_the_markdown_html_block(self):
        html, _ = cwv.render_detail(by_id("CRIT-key-personnel"), index())
        assert "\n\n" not in html and "\n" not in html

    def test_evidence_overflow_is_split_out(self):
        a = dict(by_id("REQ-46"))
        html, overflow = cwv.render_detail(a, index(), max_evidence=1)
        assert html.count('class="ck-ev"') == 1 and overflow.count('class="ck-ev"') == 2
        assert "2 more cited evidence item(s) below" in html

    def test_human_review_explains_ask_evidence_reason_and_what_to_verify(self):
        html, _ = cwv.render_detail(by_id("REQ-5"), index())
        assert "Why CHECK cannot safely determine coverage" in html
        assert "What a person should verify" in html and "element needs review" in html

    def test_unverifiable_is_explained_not_a_failure(self):
        html, _ = cwv.render_detail(by_id("REQ-38"), index())
        assert "Why this cannot be verified from the submitted files" in html
        assert "e-procurement portal" in html and "Not verifiable from files" in html
        assert "Not addressed" not in html


# ═══════════════════════════════════════════════════════════════════════
# E. Status honesty
# ═══════════════════════════════════════════════════════════════════════

class TestStatusHonesty:
    def test_partial_run_is_visibly_partial(self, svc):
        svc.status = status_dict("PARTIAL")
        svc.payload = {"semantic_batches": [{"batch_id": "B2", "effective_status": "PARTIAL",
                                             "failure_reason": "OUTPUT_TRUNCATED: provider stop_reason=max_tokens"}]}
        text = page_text(run_app())
        assert "Partial CHECK: some adjudication stages did not complete" in text
        assert "not complete assurance" in text and "Semantic batch B2 is PARTIAL" in text
        assert "Complete. Every adjudication stage finished." not in text

    def test_failed_run_without_prior_result_is_never_rendered_as_complete(self, svc):
        svc.status = status_dict("FAILED", failure_reason="adjudicator error")
        app = run_app()
        text = page_text(app)
        assert "failed" in text and "No complete or partial CHECK result exists" in text
        assert "ck-count" not in text and "Complete. Every" not in text

    def test_failed_latest_run_falls_back_to_prior_complete_labelled(self, svc):
        svc.status = status_dict("FAILED", run_id=38, failure_reason="x")
        svc.prior = (37, "COMPLETE")
        text = page_text(run_app())
        assert "The latest CHECK run (38) failed" in text and "Showing the most recent saved complete run (37)" in text

    def test_not_verifiable_distinct_from_not_addressed(self):
        nv, nad = cwv.STATUS_META[NV], cwv.STATUS_META[NAD]
        assert nv["label"] != nad["label"] and nv["mark"] != nad["mark"] and nv["tone"] != nad["tone"]
        assert cwv.status_pill(NV).count("Not verifiable from files") == 1

    def test_human_review_distinct_from_partial(self):
        hr, p = cwv.STATUS_META[HR], cwv.STATUS_META[P]
        assert hr["label"] != p["label"] and hr["mark"] != p["mark"] and hr["tone"] != p["tone"]

    def test_state_is_never_colour_only(self):
        for s in cwv.STATUSES:
            pill = cwv.status_pill(s)
            assert cwv.STATUS_META[s]["label"] in pill and cwv.STATUS_META[s]["mark"] in pill

    def test_portal_native_cases_stay_not_verifiable(self):
        portal = [a for a in adjs() if a["assurance_scope"] == "PORTAL_NATIVE"]
        assert len(portal) == 3 and {a["status"] for a in portal} == {NV}

    def test_stuck_run_offers_explicit_stop_only(self, svc):
        svc.status = status_dict("RUNNING", stuck=True)
        app = run_app()
        assert "stopped reporting progress" in page_text(app)
        assert any(b.label == "Mark this run as stopped" for b in app.button) and svc.starts == []

    def test_vocabulary_matches_check_coverage(self):
        assert set(cwv.STATUSES) == set(cc.STATUSES)
        assert cwv.OBJECT_CRITERION == cc.OBJECT_CRITERION and cwv.OBJECT_REQUIREMENT == cc.OBJECT_REQUIREMENT
        assert set(cwv.SCOPE_LABEL) == set(cc.ASSURANCE_SCOPES)
        assert set(cwv.METHOD_LABEL) == {cc.METHOD_SCOPE_GATE, cc.METHOD_DETERMINISTIC, cc.METHOD_MODEL,
                                         cc.METHOD_DERIVED}
        assert (cwv.RUN_COMPLETE, cwv.RUN_PARTIAL, cwv.RUN_FAILED) == csr.TERMINAL_RUN_STATUSES


# ═══════════════════════════════════════════════════════════════════════
# F. Attention ordering
# ═══════════════════════════════════════════════════════════════════════

class TestAttention:
    def test_documented_deterministic_ordering(self):
        items = cwv.attention_items(adjs())
        ids = [a["buyer_object_id"] for a in items]
        assert ids[0] == "CRIT-firm-experience"                            # criterion, 30% variant + threshold
        assert ids[1] == "CRIT-service-delivery"                           # criterion, 30%, no threshold
        assert all(a["buyer_object_type"] == cc.OBJECT_CRITERION for a in items[:8])
        assert ids.index("CRIT-understanding") == 7                         # criterion with no stated weight last
        assert {a["status"] for a in items} <= {P, NV, HR, NAD}
        assert cwv.attention_items(adjs()) == items                        # deterministic

    def test_mandatory_before_other_requirements_then_status(self):
        reqs = [a for a in cwv.attention_items(adjs()) if a["buyer_object_type"] == cc.OBJECT_REQUIREMENT]
        mand = [cwv.is_mandatory(a) for a in reqs]
        assert mand == sorted(mand, reverse=True)
        first_mand = [a for a in reqs if cwv.is_mandatory(a)]
        assert [a["status"] for a in first_mand][:2] == [HR, HR]

    def test_facts_only_no_hidden_score(self):
        chips = cwv.fact_chips(by_id("CRIT-firm-experience"))
        assert chips == ["Evaluation criterion", "Buyer weight 20% / 30%", "Minimum threshold 60%"]
        assert len(cwv.ATTENTION_ORDERING) == 6


# ═══════════════════════════════════════════════════════════════════════
# G. Interaction -- zero provider calls everywhere
# ═══════════════════════════════════════════════════════════════════════

class TestInteractionZeroCalls:
    def test_filtering_zero_calls_and_no_reread(self, svc, provider_calls):
        app = run_app()
        app.multiselect(key=f"chk_f_status_{BID}").set_value([A]).run()
        assert not app.exception
        assert 'data-object="REQ-46"' in page_text(app)
        app.selectbox(key=f"chk_f_type_{BID}").set_value("Evaluation criteria").run()
        app.multiselect(key=f"chk_f_role_{BID}").set_value(["PRICING_FORM"]).run()
        app.checkbox(key=f"chk_f_mand_{BID}").check().run()
        app.multiselect(key=f"chk_f_scope_{BID}").set_value(["EVALUATION_RESPONSE"]).run()
        assert not app.exception
        assert provider_calls == [] and svc.starts == []
        assert svc.reads["result"] == 1 and svc.reads["package"] == 1      # cached immutable run

    def test_filter_function(self):
        rows = cwv.filter_findings(adjs(), statuses=[A], object_types=[cc.OBJECT_REQUIREMENT],
                                   roles=["SUBMISSION_FORM"])
        assert [a["buyer_object_id"] for a in rows] == ["REQ-33", "REQ-37"]
        assert len(cwv.filter_findings(adjs())) == 60
        assert all(cwv.is_mandatory(a) for a in cwv.filter_findings(adjs(), mandatory_only=True))

    def test_default_filter_surfaces_useful_statuses(self, svc):
        app = run_app()
        assert set(app.multiselect(key=f"chk_f_status_{BID}").value) == {P, NV, HR}

    def test_detail_and_evidence_rendered_without_calls(self, svc, provider_calls):
        app = run_app()
        text = page_text(app)
        assert "What the bidder submitted" in text and PD_NAME in text and TP_NAME in text
        assert len(app.expander) >= 13 and provider_calls == []

    def test_navigating_tabs_and_refresh_zero_calls(self, svc, provider_calls):
        app = run_app()
        for _ in range(3):
            app.run()                                                     # refresh / rerun
        assert not app.exception and provider_calls == [] and svc.starts == []
        assert svc.reads["result"] == 1 and svc.reads["status"] == 4      # status re-read, result cached

    def test_new_browser_session_reconstructs_from_service(self, svc):
        run_app()
        run_app()
        assert svc.reads["result"] == 2                                   # nothing trusted from a prior session

    def test_run_check_again_is_explicit_and_uses_service(self, svc, provider_calls, monkeypatch):
        monkeypatch.setattr(config, "api_key_configured", lambda: True)
        monkeypatch.setattr(page, "api_key_configured", lambda: True)
        monkeypatch.setattr(page, "get_api_key", lambda: "sk-test")
        app = run_app()
        assert svc.starts == []
        app.button(key=f"chk_again_{BID}").click().run()
        assert len(svc.starts) == 1 and svc.starts[0]["retry"] is False
        assert "Nothing has changed since the last complete CHECK" in page_text(app)
        assert provider_calls == []

    def test_partial_rerun_is_labelled_explicit_retry(self):
        cta = cwv.rerun_cta("PARTIAL")
        assert cta["retry"] is True and "12 bounded model calls" in cta["caption"]
        assert cwv.rerun_cta("COMPLETE")["retry"] is False

    def test_duplicate_click_while_in_flight(self, svc):
        session = {"chk_start_inflight_1360": True}
        assert page.request_start(BID, ORG, "k", session) == {"outcome": "IN_FLIGHT"} and svc.starts == []

    def test_every_start_outcome_has_a_note(self):
        assert set(cwv.START_OUTCOME_NOTES) == {csr.OUTCOME_CREATED, csr.OUTCOME_ACTIVE_RUN_EXISTS,
                                                csr.OUTCOME_REUSED_COMPLETE, csr.OUTCOME_EXISTING_FAILED,
                                                csr.OUTCOME_EXISTING_PARTIAL}

    def test_no_run_yet_offers_explicit_run_only(self, svc):
        svc.status = None
        app = run_app()
        assert "No CHECK has run for this bid yet" in page_text(app)
        assert svc.starts == [] and any(b.label == "Run CHECK" for b in app.button)


# ═══════════════════════════════════════════════════════════════════════
# H. Security
# ═══════════════════════════════════════════════════════════════════════

class TestSecurity:
    def test_cross_org_page_shows_denial_and_no_data(self, svc, monkeypatch):
        def deny(*a, **k):
            raise tenancy.AccessDeniedError("no")
        monkeypatch.setattr(tenancy, "get_check_run_status_for_organization", deny)
        app = run_app()
        assert any("do not have access" in e.value for e in app.error)
        assert svc.reads["result"] == 0 and "ck-count" not in page_text(app)

    def test_cross_bid_evidence_never_renders(self):
        foreign = calgary_package(bid=OTHER_BID)
        assert cwv.build_evidence_index(foreign, BID, ["EV-b21", "EV-pd1"]) == {}
        html, _ = cwv.render_detail(by_id("REQ-46"), {})
        assert B2_NAME not in html and "could not be resolved in this bid's submission registry" in html

    def test_unknown_evidence_id_is_reported_not_fabricated(self):
        a = dict(by_id("REQ-46"))
        a["evidence_ids"] = ["EV-b21", "EV-does-not-exist"]
        a["addressed_elements"] = []
        html, _ = cwv.render_detail(a, index())
        assert "1 cited evidence reference(s) could not be resolved" in html

    def test_bundle_rejects_a_foreign_bid_run_row(self, svc, monkeypatch):
        real = svc.get_result

        def foreign(*a, **k):
            out = real(*a, **k)
            out["run"]["bid_id"] = OTHER_BID
            return out
        monkeypatch.setattr(tenancy, "get_check_run_result_for_organization", foreign)
        with pytest.raises(tenancy.AccessDeniedError):
            page.load_bundle(BID, ORG, RUN, {})

    def test_html_is_escaped(self):
        a = dict(by_id("REQ-4"))
        a["buyer_expectation"] = "<script>alert(1)</script>"
        html = cwv.render_card(dict(a, status=P), {}) + cwv.render_detail(a, {})[0]
        assert "<script>" not in html and "&lt;script&gt;" in html


# ═══════════════════════════════════════════════════════════════════════
# I. Architecture guards & regression
# ═══════════════════════════════════════════════════════════════════════

class TestArchitecture:
    @pytest.mark.parametrize("path", ["components/check_workspace_view.py", "pages/stage_check_assurance.py"])
    def test_presentation_never_imports_adjudication_execution_or_provider(self, path):
        tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                names.add(node.module or "")
        forbidden = {"check_coverage", "check_run_service", "full_analysis", "full_analysis_service", "anthropic",
                     "analysis_service", "database", "submission_package"}
        assert not (names & forbidden), names & forbidden
        src = (ROOT / path).read_text(encoding="utf-8")
        for token in ("run_check_coverage", "plan_check_coverage", "_call_model", "get_anthropic_client",
                      "execute_messages_create", "messages.create", "_execute_check_run"):
            assert token not in src, token

    def test_single_explicit_start_path(self):
        src = (ROOT / "pages" / "stage_check_assurance.py").read_text(encoding="utf-8")
        assert src.count("tenancy.start_check_run_for_organization(") == 1
        assert "retry=True" not in src                                    # retry comes only from rerun_cta

    def test_export_only_through_check2d_read_only_wrapper(self):
        # CHECK-2C shipped with no export; CHECK-2D added exactly one read-only
        # export path (the durable run rendered as the Proposal Assurance
        # Report). No other document format or report generator is reachable.
        src = (ROOT / "pages" / "stage_check_assurance.py").read_text(encoding="utf-8")
        assert src.count("tenancy.export_check_assurance_report_for_organization(") == 1
        assert src.count("st.download_button(") == 1
        low = src.lower()
        for token in ("docx", "xlsx", "reportlab", "import check_assurance_report", "full_analysis_report"):
            assert token not in low, token

    def test_app_routes_and_nav_entry(self):
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        assert "from pages.stage_check_assurance import page_check_assurance" in src
        assert '"stage_check_assurance"' in src and "page_check_assurance(bid_id)" in src
        assert "CHECK: Proposal Assurance" in src
        assert '"chk_"' in src                                             # cleared on logout

    def test_understand_and_full_bid_intelligence_unaffected(self):
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        assert "page_understand(bid_id)" in src and "page_full_analysis(bid_id)" in src
        assert '"🧬  Full Bid Intelligence": "stage_full_analysis"' in src
        assert '"💡  1. UNDERSTAND": "stage_understand"' in src

    def test_existing_check_page_only_links(self):
        src = (ROOT / "pages" / "stage_check.py").read_text(encoding="utf-8")
        assert 'st.session_state.page = "stage_check_assurance"' in src
        assert "start_check_run" not in src

    def test_check2b_backend_frozen_at_e76e103(self):
        try:
            out = subprocess.run(["git", "diff", "--quiet", "e76e103", "--", "check_coverage.py",
                                  "check_run_service.py", "migrations/022_check_runs.sql", "submission_package.py",
                                  "canonical_procurement.py", "procurement_normalization.py"],
                                 cwd=ROOT, capture_output=True, timeout=30)
        except Exception:
            pytest.skip("git unavailable")
        if out.returncode not in (0, 1):
            pytest.skip("commit e76e103 not available in this checkout")
        assert out.returncode == 0, "CHECK backend changed since e76e103"

    def test_check2b_durable_semantics_unchanged(self):
        assert (csr.OUTCOME_CREATED, csr.OUTCOME_ACTIVE_RUN_EXISTS, csr.OUTCOME_REUSED_COMPLETE,
                csr.OUTCOME_EXISTING_FAILED, csr.OUTCOME_EXISTING_PARTIAL) == (
            "CREATED", "ACTIVE_RUN_EXISTS", "REUSED_COMPLETE", "EXISTING_FAILED", "EXISTING_PARTIAL")
