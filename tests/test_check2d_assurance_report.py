"""
CHECK-2D: concise Proposal Assurance Report (deterministic, zero provider calls).

Every test is deterministic: no live database, no live provider. Every model /
adjudication / execution entry point is poisoned by the autouse
`provider_calls` fixture and tests assert the recorded list stays empty.

Fixtures reuse CHECK-2C's Calgary-shaped synthetic durable result (60 buyer
objects, 13 scoped criteria, real run-37 status distribution and B2 /
Appendix D / Appendix E / portal-native / human-review shapes) -- Calgary is
the acceptance case, never a special case in the report code.
"""
from __future__ import annotations

import ast
import copy
import io
import os
import re
import subprocess
import sys
import types
from pathlib import Path

import pypdf
import pytest

sys.path.insert(0, os.path.dirname(__file__))

import auth_session  # noqa: E402
import check_assurance_report as car  # noqa: E402
import check_coverage as cc  # noqa: E402
import check_run_service as csr  # noqa: E402
import config  # noqa: E402
import full_analysis  # noqa: E402
import tenancy  # noqa: E402
import test_check2c_assurance_workspace as t2c  # noqa: E402
from components import check_report_model as crm  # noqa: E402
from components import check_workspace_view as cwv  # noqa: E402
from pages import stage_check_assurance as page  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BID, ORG, RUN, SNAP = t2c.BID, t2c.ORG, t2c.RUN, t2c.SNAP

POISONED = ((cc, "run_check_coverage"), (cc, "plan_check_coverage"), (cc, "_default_model_call"),
            (full_analysis, "_call_model"), (config, "get_anthropic_client"), (config, "execute_messages_create"),
            (csr, "_execute_check_run"), (csr, "start_check_run"), (csr, "mark_check_run_stuck"))


@pytest.fixture(autouse=True)
def provider_calls(monkeypatch):
    calls = []
    for mod, name in POISONED:
        def boom(*a, _n=f"{mod.__name__}.{name}", **k):
            calls.append(_n)
            raise AssertionError(f"forbidden provider/adjudication/execution call: {_n}")
        monkeypatch.setattr(mod, name, boom)
    return calls


BIDROW = {"id": BID, "client": "The City of Calgary", "file_number": "26-1603",
          "title": "RFP 26-1603 - Design and Delivery Services"}


def run_row(status="COMPLETE"):
    return {"id": RUN, "bid_id": BID, "status": status, "source_package_snapshot_id": SNAP,
            "source_analysis_run_id": 34, "completed_at": "2026-09-27T15:38:25+00:00",
            "engine_version": "check-coverage-check-2a.1.0/durable-check-2b.1.0",
            "input_fingerprint": "48e9a2e172b2" + "0" * 52, "failure_reason": None}


def inputs():
    adjs = cwv.adjudications(t2c.calgary_result())
    pkg = t2c.calgary_package()
    index = cwv.build_evidence_index(pkg, BID, [e for a in adjs for e in cwv.cited_evidence_ids(a)])
    return adjs, index, cwv.submitted_files(pkg)


def model(status="COMPLETE", **kw):
    adjs, index, files = inputs()
    return crm.build_report_model(run=run_row(status), adjudications=kw.pop("adjs", adjs),
                                  evidence_index=kw.pop("index", index), files=files, bid=BIDROW, **kw)


def rendered(status="COMPLETE", **kw):
    adjs, index, files = inputs()
    return car.render_report(run=run_row(status), adjudications=adjs, evidence_index=index, files=files,
                             bid=BIDROW, **kw)


def text_of(pdf: bytes) -> str:
    r = pypdf.PdfReader(io.BytesIO(pdf))
    return re.sub(r"\s+", " ", " ".join(p.extract_text() or "" for p in r.pages))


@pytest.fixture(scope="module")
def complete_pdf():
    adjs, index, files = inputs()
    return car.render_report(run=run_row(), adjudications=adjs, evidence_index=index, files=files, bid=BIDROW)


# ═══════════════════════════════════════════════════════════════════════
# A. Report model
# ═══════════════════════════════════════════════════════════════════════

class TestReportModel:
    def test_same_input_same_model_digest_and_pdf(self):
        a, b = rendered(), rendered()
        assert a["model"] == b["model"] and a["digest"] == b["digest"]
        assert a["pdf"] == b["pdf"]                                      # invariant render

    def test_digest_ignores_generated_at_but_not_content(self):
        m = model()
        d = crm.model_digest(m)
        assert crm.model_digest(dict(m, generated_at="2099-01-01T00:00:00Z")) == d
        changed = copy.deepcopy(m)
        changed["criteria"][0]["status"] = crm.ADDRESSED
        assert crm.model_digest(changed) != d

    def test_status_counts_are_the_persisted_counts(self):
        ov = model()["overview"]
        counts = {c["status"]: c["count"] for c in ov["counts"]}
        assert counts == {crm.ADDRESSED: 18, crm.PARTIAL: 11, crm.NOT_ADDRESSED: 0, crm.NOT_VERIFIABLE: 6,
                          crm.HUMAN_REVIEW: 2}
        assert ov["non_submission"] == 23 and ov["total"] == 60 and ov["criteria"] == 13

    def test_all_criteria_retained_with_weights_and_thresholds(self):
        rows = model()["criteria"]
        assert len(rows) == 13
        assert {r["object_id"] for r in rows} == {c[0] for c in t2c.CRITERIA}
        firm = next(r for r in rows if r["object_id"] == "CRIT-firm-experience")
        assert firm["weight"] == "20% / 30%" and firm["threshold"] == "60%" and firm["weight_variants_differ"]
        item1 = next(r for r in rows if r["object_id"] == "CRIT-item-1")
        assert item1["weight"] == "55%" and item1["status"] == crm.ADDRESSED
        und = next(r for r in rows if r["object_id"] == "CRIT-understanding")
        assert und["weight"] is None                                     # never invented

    def test_attention_ordering_is_deterministic_and_explainable(self):
        att = model()["attention"]
        keys = [f["class_rank"] for f in att]
        assert keys == sorted(keys)
        first = att[0]
        assert first["class"] == ("criterion", crm.PARTIAL)
        # Highest buyer-stated weight first among criterion partials (30% via the 20%/30% variant).
        assert any(m["object_id"] == "CRIT-firm-experience" for m in first["applies_to"])
        classes = [f["class"] for f in att]
        assert classes.index(("criterion", crm.NOT_VERIFIABLE)) < classes.index(("mandatory", crm.HUMAN_REVIEW))
        assert [f["ref"] for f in att] == [f"A{i}" for i in range(1, len(att) + 1)]
        # Shuffling nothing: identical input twice -> identical refs.
        assert [f["unit_id"] for f in att] == [f["unit_id"] for f in model()["attention"]]

    def test_class_order_matches_specification(self):
        assert crm.ATTENTION_CLASSES[:4] == (("criterion", crm.PARTIAL), ("criterion", crm.HUMAN_REVIEW),
                                             ("criterion", crm.NOT_VERIFIABLE), ("criterion", crm.NOT_ADDRESSED))
        assert crm.ATTENTION_CLASSES[4:7] == (("mandatory", crm.PARTIAL), ("mandatory", crm.HUMAN_REVIEW),
                                              ("mandatory", crm.NOT_VERIFIABLE))

    def test_partial_elements_retained_verbatim(self):
        m = model()
        by_unit = {f["unit_id"]: f for f in m["attention"]}
        f41 = by_unit["REQ-41"]
        assert f41["status"] == crm.PARTIAL
        assert [e["element"] for e in f41["demonstrated"]] == ["REQ-41 element A", "REQ-41 element B"]
        assert [e["element"] for e in f41["not_demonstrated"]] == ["REQ-41 element C", "REQ-41 element D"]
        assert [e["coverage"] for e in f41["not_demonstrated"]] == ["ABSENT", "PARTIAL"]

    def test_derived_criterion_elements_shown_once_not_per_criterion(self):
        m = model()
        adjs, _, _ = inputs()
        att_ids = {a["buyer_object_id"] for a in adjs if a["status"] in crm.ATTENTION_STATUSES}
        covered = {x["object_id"] for f in m["attention"] for x in f["applies_to"]}
        assert covered == att_ids                                       # every attention object appears
        units = [f["unit_id"] for f in m["attention"]]
        assert len(units) == len(set(units))

    def test_human_review_retained_with_verbatim_reasons(self):
        m = model()
        hr = [f for f in m["attention"] if f["ref"] in m["human_review"]]
        assert {f["unit_id"] for f in hr} == {"REQ-5", "REQ-16"}
        f5 = next(f for f in hr if f["unit_id"] == "REQ-5")
        assert f5["reasons"] == ["element needs review: scope limitation cannot be read from a completed price"]
        assert f5["reviewer_checks"] == ["scope limitation cannot be read from a completed price"]
        f16 = next(f for f in hr if f["unit_id"] == "REQ-16")
        assert f16["reviewer_checks"] == []                              # nothing invented

    def test_reviewer_checks_only_from_persisted_metadata(self):
        a = {"ambiguity_or_review_reason": "the evidence is ambiguous", "unverifiable_elements": []}
        assert crm.reviewer_checks(a) == []

    def test_not_verifiable_retained_and_portal_native_kept_unverifiable(self):
        m = model()
        nv = {f["unit_id"]: f for f in m["attention"] if f["ref"] in m["not_verifiable"]}
        assert {"REQ-2", "REQ-3", "REQ-27", "REQ-38", "REQ-45"} <= set(nv)
        assert all(f["status"] == crm.NOT_VERIFIABLE for f in nv.values())
        assert nv["REQ-38"]["scope"] == "PORTAL_NATIVE" and nv["REQ-38"]["status"] == crm.NOT_VERIFIABLE
        assert "e-procurement portal" in nv["REQ-38"]["unverifiable_reasons"][0]
        social = next(r for r in m["criteria"] if r["object_id"] == "CRIT-social-procurement")
        assert social["status"] == crm.NOT_VERIFIABLE
        assert "Not verifiable from the submitted files" in social["conclusion"]

    def test_non_submission_separate_from_findings(self):
        m = model()
        ns_ids = {i for g in m["non_submission"] for i in g["ids"]}
        assert len(ns_ids) == 23
        in_findings = {x["object_id"] for f in m["attention"] for x in f["applies_to"]}
        in_mand = {r["object_id"] for r in m["mandatory_addressed"]}
        assert not (ns_ids & in_findings) and not (ns_ids & in_mand)
        assert m["not_addressed"] == []                                  # zero shown truthfully

    def test_replay_placeholder_not_repeated_but_row_untouched(self):
        adjs, index, files = inputs()
        a41 = next(a for a in adjs if a["buyer_object_id"] == "REQ-5")
        a41["ambiguity_or_review_reason"] = ("recorded live adjudication (reason text omitted from content-free "
                                             "fixture) | element needs review: X")
        original = a41["ambiguity_or_review_reason"]
        m = crm.build_report_model(run=run_row(), adjudications=adjs, evidence_index=index, files=files, bid=BIDROW)
        f = next(f for f in m["attention"] if f["unit_id"] == "REQ-5")
        assert f["reasons"] == ["element needs review: X"]
        assert a41["ambiguity_or_review_reason"] == original

    def test_model_module_is_pure(self):
        tree = ast.parse((ROOT / "components" / "check_report_model.py").read_text(encoding="utf-8"))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                names.add((node.module or "").split(".")[0])
        for bad in ("streamlit", "database", "tenancy", "reportlab", "anthropic", "config", "check_coverage",
                    "check_run_service", "full_analysis", "analysis_service", "submission_package"):
            assert bad not in names, bad


# ═══════════════════════════════════════════════════════════════════════
# B. Evidence and provenance
# ═══════════════════════════════════════════════════════════════════════

def _all_refs(m) -> set:
    refs = set()
    for f in m["attention"]:
        refs |= set(f["evidence"])
        for g in ("demonstrated", "not_demonstrated", "unverifiable"):
            for e in f[g]:
                refs |= set(e["cites"])
    for r in m["criteria"]:
        refs |= set(r["evidence"])
    for r in m["mandatory_addressed"]:
        refs |= set(r["evidence"])
    return refs


class TestEvidence:
    def test_every_citation_resolves_in_this_bids_registry(self):
        m = model()
        _, index, _ = inputs()
        cited = {c["ref"]: c for c in m["citations"]}
        assert _all_refs(m) == set(cited)
        assert all(c["evidence_id"] in index for c in m["citations"])
        assert m["unresolved_evidence"] == []
        assert [c["ref"] for c in m["citations"]] == [f"E{i}" for i in range(1, len(cited) + 1)]

    def test_unknown_evidence_id_never_cited_or_fabricated(self):
        adjs, index, files = inputs()
        a = next(a for a in adjs if a["buyer_object_id"] == "REQ-46")
        a["evidence_ids"] = ["EV-does-not-exist"] + list(a["evidence_ids"])
        m = crm.build_report_model(run=run_row(), adjudications=adjs, evidence_index=index, files=files, bid=BIDROW)
        assert "EV-does-not-exist" in m["unresolved_evidence"]
        assert all(c["evidence_id"] != "EV-does-not-exist" for c in m["citations"])

    def test_spreadsheet_locator(self):
        m = model()
        pd1 = next(c for c in m["citations"] if c["evidence_id"] == "EV-pd1")
        assert pd1["role_label"] == "Pricing form"
        assert "Sheet Price Form" in pd1["location"] and "cell D6" in pd1["location"]
        assert pd1["text"] == "Item 1 lump sum: $48,000"

    def test_form_and_document_locators(self):
        m = model()
        b22 = next(c for c in m["citations"] if c["evidence_id"] == "EV-b22")
        assert b22["role_label"] == "Multi-party form" and "p. 2" in b22["location"]
        assert "section TEAM MEMBER" in b22["location"]
        assert b22["text"] == "Per: Party One Signatory"
        ae = next(c for c in m["citations"] if c["evidence_id"] == "EV-ae1")
        assert ae["role_label"] == "Submission form" and "p. 2" in ae["location"]

    def test_multiple_evidence_refs_and_req46_b2(self):
        m = model()
        r46 = next(r for r in m["mandatory_addressed"] if r["object_id"] == "REQ-46")
        assert len(r46["evidence"]) == 2 and r46["more_evidence"] == 1
        labels = {c["ref"]: c for c in m["citations"]}
        assert all(labels[r]["role_label"] == "Multi-party form" for r in r46["evidence"])
        assert "B2 Multi-Party Confirmation Form" in (r46["summary"] or "")

    def test_buyer_provenance_retained(self):
        m = model()
        f = m["attention"][0]
        assert f["buyer_sources"][0]["document"] == "RFP 26-1603.docx"
        assert f["buyer_sources"][0]["page"] == 40
        assert "RFP 26-1603.docx" in crm.source_line(f["buyer_sources"][0])

    def test_appendix_lists_submitted_artifacts(self):
        m = model()
        roles = {f["role"] for f in m["files"]}
        assert roles == {"TECHNICAL_PROPOSAL", "PRICING_FORM", "SUBMISSION_FORM", "MULTI_PARTY_FORM"}

    def test_tidy_excerpt_only_removes_rules(self):
        assert crm.tidy_excerpt("+------+ | OPERATIONAL MATRIX | +-----+") == "| OPERATIONAL MATRIX |"
        assert crm.tidy_excerpt("cost $1,000 - 2 days") == "cost $1,000 - 2 days"


# ═══════════════════════════════════════════════════════════════════════
# C. Product boundaries (rendered PDF)
# ═══════════════════════════════════════════════════════════════════════

FORBIDDEN = (r"overall score", r"compliance score", r"readiness score", r"quality score", r"proposal score",
             r"estimated score", r"predicted score", r"win probability", r"probability of win", r"\d+\s*/\s*100",
             r"\bscore:\s*\d", r"\d+(\.\d+)?\s*%\s*(compliant|compliance|ready|readiness)", r"recommendations?\b")


class TestProductBoundaries:
    def test_no_score_percentage_or_probability(self, complete_pdf):
        text = text_of(complete_pdf["pdf"]).lower()
        for pat in FORBIDDEN:
            assert not re.search(pat, text), pat

    def test_model_has_no_score_fields(self):
        flat = repr(model()).lower()
        for key in ("'score'", "percentage'", "probability", "readiness", "'recommendation"):
            assert key not in flat, key

    def test_no_generated_prose_path(self):
        for path in ("check_assurance_report.py", "components/check_report_model.py"):
            src = (ROOT / path).read_text(encoding="utf-8")
            for token in ("anthropic", "messages.create", "get_anthropic_client", "_call_model",
                          "execute_messages_create", "run_check_coverage", "adjudicate"):
                assert token not in src, (path, token)

    def test_renderer_is_pure_presentation(self):
        tree = ast.parse((ROOT / "check_assurance_report.py").read_text(encoding="utf-8"))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                names.add((node.module or "").split(".")[0])
        for bad in ("streamlit", "database", "tenancy", "anthropic", "config", "check_coverage",
                    "check_run_service", "full_analysis", "analysis_service"):
            assert bad not in names, bad


# ═══════════════════════════════════════════════════════════════════════
# D. PDF structure (synthetic)
# ═══════════════════════════════════════════════════════════════════════

class TestPdf:
    def test_structure_and_content(self, complete_pdf):
        pdf = complete_pdf["pdf"]
        assert pdf.startswith(b"%PDF") and len(pdf) > 10_000
        pages = len(pypdf.PdfReader(io.BytesIO(pdf)).pages)
        assert 5 <= pages <= 15
        text = text_of(pdf)
        for heading in ("Assurance Overview", "Evaluation Criteria Overview", "Findings Requiring Attention",
                        "Human Review Required", "Not Verifiable from the Submitted Files", "Not Addressed (0)",
                        "Addressed Mandatory Requirements", "Outside Proposal-Assurance Scope",
                        "Evidence Appendix", "Methodology & Status Definitions"):
            assert heading in text, heading
        assert "The City of Calgary" in text and "26-1603" in text and "CHECK run 37" in text
        for _, label, *_ in t2c.CRITERIA:
            first = label.split()[0]
            assert first in text
        assert "$48,000" in text                                         # dollar values survive
        assert complete_pdf["filename"] == "Proposal_Assurance_Report_26-1603.pdf"
        assert "PARTIAL" not in text.split("CHECK run status:")[1][:30]

    def test_unicode_is_font_safe(self):
        assert car.safe("round‑trip ● ── →") == "round-trip • -- ->"
        assert "‑" not in car.safe("a‑b")

    def test_partial_run_truthfully_labelled(self):
        out = rendered("PARTIAL", partial_lines=["Semantic batch B3 is PARTIAL: output truncated"])
        text = text_of(out["pdf"])
        assert "PARTIAL PROPOSAL ASSURANCE REPORT" in text
        assert "PARTIAL CHECK RUN" in text and "NOT COMPLETE ASSURANCE" in text
        assert "Semantic batch B3 is PARTIAL" in text
        assert out["filename"].startswith("Partial_Proposal_Assurance_Report_")
        assert out["model"]["title"] == crm.PARTIAL_REPORT_TITLE

    @pytest.mark.parametrize("status", ["FAILED", "RUNNING", "QUEUED", None])
    def test_failed_or_live_run_not_exportable(self, status):
        with pytest.raises(crm.ReportNotExportableError):
            rendered(status)

    def test_digest_not_verified_is_disclosed(self):
        text = text_of(rendered(digest_verified=False)["pdf"])
        assert "INTEGRITY CHECK NOT PASSED" in text


# ═══════════════════════════════════════════════════════════════════════
# E. Export through tenancy (authorization, zero calls, no mutation)
# ═══════════════════════════════════════════════════════════════════════

@pytest.fixture
def export_env(monkeypatch):
    state = {"status": "COMPLETE", "result_reads": 0, "package_reads": 0}
    result = t2c.calgary_result()

    def get_result(bid_id, run_id=None):
        state["result_reads"] += 1
        if run_id != RUN or int(bid_id) != BID:
            raise csr.RunNotFoundError("no such CHECK run for this bid")
        return {"run": run_row(state["status"]), "result": result,
                "result_payload": {"semantic_batches": [{"batch_id": "B3", "effective_status": "PARTIAL",
                                                         "failure_reason": "output truncated"}]
                                   if state["status"] == "PARTIAL" else []},
                "semantic_batches": [], "is_complete": state["status"] == "COMPLETE",
                "result_digest_verified": True}

    def load_package(bid_id, organization_id, package_snapshot_id):
        state["package_reads"] += 1
        tenancy.require_bid_access(bid_id, organization_id)
        return t2c.calgary_package()

    import database as db
    monkeypatch.setattr(csr, "get_check_run_result", get_result)
    monkeypatch.setattr(tenancy, "get_bid_for_organization", lambda b, o: {"id": b} if o == ORG else None)
    monkeypatch.setattr(tenancy, "load_submission_evidence_package_for_organization", load_package)
    monkeypatch.setattr(db, "get_bid", lambda b: dict(BIDROW))
    for name in ("start_check_run", "record_check_run_event", "finalize_check_run", "create_analysis_run",
                 "update_analysis_run", "create_analysis_result"):
        if hasattr(db, name):
            monkeypatch.setattr(db, name, lambda *a, _n=name, **k: (_ for _ in ()).throw(
                AssertionError(f"write path {_n} called during export")))
    state["result"] = result
    return state


class TestExport:
    def test_complete_export_zero_provider_calls_and_repeatable(self, export_env, provider_calls):
        before = [a.to_dict() for a in export_env["result"].adjudications]
        a = tenancy.export_check_assurance_report_for_organization(BID, ORG, RUN)
        b = tenancy.export_check_assurance_report_for_organization(BID, ORG, RUN)
        assert a["pdf"].startswith(b"%PDF") and a["pdf"] == b["pdf"] and a["digest"] == b["digest"]
        assert a["filename"] == "Proposal_Assurance_Report_26-1603.pdf"
        assert provider_calls == []
        assert [x.to_dict() for x in export_env["result"].adjudications] == before   # persisted result untouched

    def test_partial_export_labelled(self, export_env):
        export_env["status"] = "PARTIAL"
        out = tenancy.export_check_assurance_report_for_organization(BID, ORG, RUN)
        text = text_of(out["pdf"])
        assert out["filename"].startswith("Partial_") and "PARTIAL PROPOSAL ASSURANCE REPORT" in text
        assert "Semantic batch B3 is PARTIAL" in text

    def test_failed_run_not_exported_as_complete(self, export_env):
        export_env["status"] = "FAILED"
        with pytest.raises(crm.ReportNotExportableError):
            tenancy.export_check_assurance_report_for_organization(BID, ORG, RUN)
        assert export_env["package_reads"] == 0

    def test_cross_org_cannot_export(self, export_env):
        with pytest.raises(tenancy.AccessDeniedError):
            tenancy.export_check_assurance_report_for_organization(BID, "org-evil", RUN)
        assert export_env["result_reads"] == 0 and export_env["package_reads"] == 0

    def test_foreign_run_id_cannot_export(self, export_env):
        with pytest.raises(tenancy.AccessDeniedError):
            tenancy.export_check_assurance_report_for_organization(BID, ORG, 999)


# ═══════════════════════════════════════════════════════════════════════
# F. Workspace integration
# ═══════════════════════════════════════════════════════════════════════

class TestWorkspace:
    def test_prepare_export_caches_and_never_starts(self, monkeypatch, provider_calls):
        calls = []

        def fake_export(bid_id, org, run_id):
            calls.append(run_id)
            return {"pdf": b"%PDF-x", "filename": "f.pdf", "digest": "d"}

        monkeypatch.setattr(tenancy, "export_check_assurance_report_for_organization", fake_export)
        monkeypatch.setattr(tenancy, "start_check_run_for_organization",
                            lambda *a, **k: (_ for _ in ()).throw(AssertionError("start during export")))
        session = {}
        assert page.prepare_export(BID, ORG, RUN, "COMPLETE", session)["filename"] == "f.pdf"
        assert page.prepare_export(BID, ORG, RUN, "COMPLETE", session)["filename"] == "f.pdf"
        assert calls == [RUN] and all(k.startswith(page.SESSION_PREFIX) for k in session)
        assert "error" in page.prepare_export(BID, ORG, 38, "FAILED", session)
        assert "error" in page.prepare_export(BID, ORG, 39, "RUNNING", session)
        assert calls == [RUN] and provider_calls == []

    def test_prepare_export_access_denied(self, monkeypatch):
        def deny(*a):
            raise tenancy.AccessDeniedError("x")
        monkeypatch.setattr(tenancy, "export_check_assurance_report_for_organization", deny)
        session = {}
        assert "error" in page.prepare_export(BID, "org-evil", RUN, "COMPLETE", session)
        assert not session

    def test_labels(self):
        assert page.export_labels("COMPLETE")["download"] == "Download Proposal Assurance Report"
        assert page.export_labels("PARTIAL")["download"] == "Download Partial Proposal Assurance Report"
        assert page.export_labels("FAILED") is None and page.export_labels("RUNNING") is None

    def test_workspace_shows_export_action_without_building_it(self, monkeypatch, provider_calls):
        t2c._reset_streamlit_globals()
        s = t2c.FakeService()
        t2c.install(monkeypatch, s)
        built = []
        monkeypatch.setattr(tenancy, "export_check_assurance_report_for_organization",
                            lambda *a: built.append(a) or {"pdf": b"%PDF", "filename": "f.pdf", "digest": "d"})
        app = t2c.run_app()
        assert not app.exception
        labels = [b.label for b in app.button]
        assert "Prepare Proposal Assurance Report (PDF)" in labels
        assert built == [] and s.starts == [] and provider_calls == []   # opening never builds or runs
        t2c._reset_streamlit_globals()


# ═══════════════════════════════════════════════════════════════════════
# G. Regression / discipline
# ═══════════════════════════════════════════════════════════════════════

class TestDiscipline:
    def test_check_backend_frozen_at_e76e103(self):
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

    def test_no_new_migration(self):
        migs = sorted(p.name for p in (ROOT / "migrations").glob("*.sql"))
        assert migs[-1] == "022_check_runs.sql"

    def test_status_vocabulary_pinned_to_check_coverage(self):
        assert (crm.ADDRESSED, crm.PARTIAL, crm.NOT_ADDRESSED, crm.NOT_VERIFIABLE, crm.HUMAN_REVIEW,
                crm.NOT_APPLICABLE) == (cc.STATUS_ADDRESSED, cc.STATUS_PARTIALLY_ADDRESSED, cc.STATUS_NOT_ADDRESSED,
                                        cc.STATUS_NOT_VERIFIABLE, cc.STATUS_HUMAN_REVIEW, cc.STATUS_NOT_APPLICABLE)

    def test_report_reuses_shared_report_stack(self):
        src = (ROOT / "check_assurance_report.py").read_text(encoding="utf-8")
        assert "import scripts.build_boc_bid_intelligence_preview_pdf as base" in src
        assert "import full_analysis_report as far" in src
