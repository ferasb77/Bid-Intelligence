"""
CHECK-2D.1: durable data & presentation hygiene.

The persisted CHECK review reason is RAW DURABLE VALUE; every customer-facing
CHECK surface (CHECK-2C workspace, finding detail, attention list, CHECK-2D
report model and PDF) renders the ONE client-safe projection in
components/check_review_text.py. Two internal artifacts are normalized:

  * the CHECK-2B.1 replay-commissioning placeholder
    ("recorded live adjudication (reason text omitted from content-free fixture)")
  * internal status-routing notation ("... -> HUMAN_REVIEW_REQUIRED")

Fully deterministic: no live database, no live provider (every model /
adjudication / execution entry point poisoned; the recorded list must stay
empty). The reason strings below are copied verbatim from the live run-37
rows (bid 1360) so the real shapes are exercised; Calgary is the acceptance
case, never a special case in production code.
"""
from __future__ import annotations

import ast
import copy
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(__file__))

import check_assurance_report as car  # noqa: E402
import check_coverage as cc  # noqa: E402
import check_run_service as csr  # noqa: E402
import config  # noqa: E402
import full_analysis  # noqa: E402
import tenancy  # noqa: E402
import test_check2c_assurance_workspace as t2c  # noqa: E402
import test_check2d_assurance_report as t2d  # noqa: E402
from components import check_report_model as crm  # noqa: E402
from components import check_review_text as crt  # noqa: E402
from components import check_workspace_view as cwv  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BID, ORG, RUN = t2c.BID, t2c.ORG, t2c.RUN

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


PH = "recorded live adjudication (reason text omitted from content-free fixture)"
REQ5_ELEMENT = ("the solicitation is limited to the scope of services as defined in the RFP and does not include "
                "additional services such as coaching or psychometric assessments")
#: Verbatim run-37 ambiguity_or_review_reason values (live SELECT, bid 1360).
RUN37_REASONS = {
    "REQ-5": (f"{PH} | element needs review: {REQ5_ELEMENT} | element PARTIAL without valid evidence -> HUMAN_REVIEW: "
              "'the solicitation is limited to the scope of services as defined in the RFP and d' | "
              "PARTIALLY_ADDRESSED without an identified absent/partial buyer element -> HUMAN_REVIEW_REQUIRED"),
    "REQ-14": PH, "REQ-22": PH, "REQ-25": PH, "REQ-41": PH, "REQ-42": PH, "REQ-43": PH,
    "REQ-40": (f"{PH} | PARTIALLY_ADDRESSED -> ADDRESSED: the only missing element(s) were wording a buyer amendment "
               "deleted (REQ-22) and price properties the files cannot show (now NOT_VERIFIABLE elements); every "
               "file-verifiable element is addressed"),
    "REQ-44": f"{PH} | ADDRESSED but an element is absent/partial -> PARTIALLY_ADDRESSED",
    "CRIT-firm-experience": ("buyer sources state differing weights for this criterion: 20%, 30% (buyer metadata, not "
                             f"resolved by CHECK) | [REQ-14] {PH} | [REQ-41] {PH}"),
    "CRIT-key-personnel": f"[REQ-42] {PH}",
    "CRIT-other-personnel": f"[REQ-43] {PH}",
    "CRIT-2-2-other-personnel": f"[REQ-43] {PH}",
    "CRIT-team-experience": f"[REQ-42] {PH} | [REQ-43] {PH}",
    "CRIT-service-delivery": f"[REQ-44] {PH} | ADDRESSED but an element is absent/partial -> PARTIALLY_ADDRESSED",
    "CRIT-understanding": f"[REQ-44] {PH} | ADDRESSED but an element is absent/partial -> PARTIALLY_ADDRESSED",
}
#: Machine routing syntax: an arrow followed by a CHECK status token.
ROUTING_RE = re.compile(r"->\s*(HUMAN_REVIEW|ADDRESSED|PARTIALLY_ADDRESSED|NOT_ADDRESSED|NOT_VERIFIABLE|NOT_APPLICABLE)")
LEAK_RE = re.compile(r"content-free|reason text omitted|recorded live adjudication")


def run37_result() -> cc.CheckCoverageResult:
    """CHECK-2C's Calgary-shaped durable result with the real run-37 reasons."""
    res = t2c.calgary_result()
    for a in res.adjudications:
        if a.buyer_object_id in RUN37_REASONS:
            a.ambiguity_or_review_reason = RUN37_REASONS[a.buyer_object_id]
    return res


def run37_adjs() -> list:
    return cwv.adjudications(run37_result())


def by_id(adjs, oid):
    return next(a for a in adjs if a["buyer_object_id"] == oid)


def run37_index(adjs):
    return cwv.build_evidence_index(t2c.calgary_package(), BID, [e for a in adjs for e in cwv.cited_evidence_ids(a)])


def assert_clean(text: str):
    assert not LEAK_RE.search(text), LEAK_RE.search(text)
    assert not ROUTING_RE.search(text), ROUTING_RE.search(text)


# ═══════════════════════════════════════════════════════════════════════
# A. The shared projection
# ═══════════════════════════════════════════════════════════════════════

class TestPlaceholder:
    def test_exact_placeholder_suppressed(self):
        assert crt.client_safe_review_notes(PH, cc.STATUS_ADDRESSED) == []
        assert crt.client_safe_review_notes(f"[REQ-43] {PH}", cc.STATUS_PARTIALLY_ADDRESSED) == []
        assert crt.is_commissioning_placeholder(PH) and crt.is_commissioning_placeholder(f"[REQ-14] {PH}")
        assert crt.COMMISSIONING_PLACEHOLDER == PH

    def test_placeholder_removed_other_segments_kept(self):
        out = crt.client_safe_review_notes(RUN37_REASONS["CRIT-firm-experience"], cc.STATUS_PARTIALLY_ADDRESSED)
        assert out == ["buyer sources state differing weights for this criterion: 20%, 30% (buyer metadata, not "
                       "resolved by CHECK)"]

    def test_no_unsupported_replacement_narrative(self):
        # Non-human-review: nothing is substituted at all.
        for st in (cc.STATUS_ADDRESSED, cc.STATUS_PARTIALLY_ADDRESSED, cc.STATUS_NOT_VERIFIABLE):
            assert crt.client_safe_review_notes(PH, st) == []
        # Human review with nothing left: the fixed neutral sentence only.
        assert crt.client_safe_review_notes(PH, cc.STATUS_HUMAN_REVIEW) == [crt.NEUTRAL_REVIEW_REASON]
        assert "no additional narrative reason was preserved" in crt.NEUTRAL_REVIEW_REASON
        for word in ("missing", "fail", "weak", "deficien", "absent", "not provided"):
            assert word not in crt.NEUTRAL_REVIEW_REASON.lower()

    def test_neutral_only_when_nothing_truthful_remains(self):
        out = crt.client_safe_review_notes(RUN37_REASONS["REQ-5"], cc.STATUS_HUMAN_REVIEW)
        assert crt.NEUTRAL_REVIEW_REASON not in out                    # structured reasons exist
        assert out[0] == f"element needs review: {REQ5_ELEMENT}"


class TestRoutingNotation:
    def test_human_review_routing_normalized_and_meaning_retained(self):
        out = crt.client_safe_review_notes(RUN37_REASONS["REQ-5"], cc.STATUS_HUMAN_REVIEW)
        assert out == [f"element needs review: {REQ5_ELEMENT}",
                       "The evidence cited for an element could not be validated, so that element needs human review.",
                       "No specific absent or partly demonstrated buyer element was identified, so a person should "
                       "confirm it."]
        assert not any(ROUTING_RE.search(x) or "HUMAN_REVIEW" in x for x in out)

    def test_substantive_reason_after_marker_retained(self):
        out = crt.client_safe_review_notes(RUN37_REASONS["REQ-40"], cc.STATUS_ADDRESSED)
        assert out == ["Treated as addressed: the only missing element(s) were wording a buyer amendment deleted "
                       "(REQ-22) and price properties the files cannot show (now not verifiable elements); every "
                       "file-verifiable element is addressed"]

    def test_partial_downgrade_normalized(self):
        for oid in ("REQ-44", "CRIT-service-delivery", "CRIT-understanding"):
            out = crt.client_safe_review_notes(RUN37_REASONS[oid], cc.STATUS_PARTIALLY_ADDRESSED)
            assert out == ["At least one requested element is absent or only partly demonstrated."], oid

    @pytest.mark.parametrize("raw", [
        "NOT_ADDRESSED -> HUMAN_REVIEW_REQUIRED: CHECK-1 does not permit an absence claim for this form",
        "element ADDRESSED without valid evidence -> HUMAN_REVIEW: 'x'",
        "unknown status 'MAYBE' -> HUMAN_REVIEW_REQUIRED",
        "ADDRESSED without valid bidder evidence -> HUMAN_REVIEW_REQUIRED",
        "ADDRESSED but an element lost its evidence -> HUMAN_REVIEW_REQUIRED",
        "PARTIALLY_ADDRESSED without valid bidder evidence -> HUMAN_REVIEW_REQUIRED",
        "NOT_ADDRESSED on a non-response scope -> NOT_VERIFIABLE_FROM_FILES",
        "NOT_ADDRESSED where CHECK-1 artifact status is POSSIBLY_PORTAL_NATIVE -> NOT_VERIFIABLE_FROM_FILES",
        "NOT_ADDRESSED while citing supporting evidence -> HUMAN_REVIEW_REQUIRED",
        "NOT_ADDRESSED contradicted by package artifacts (Form A.pdf) -> HUMAN_REVIEW_REQUIRED",
        "some future rule on ADDRESSED -> NOT_APPLICABLE: because the buyer says so",
    ])
    def test_every_check_coverage_template_leaves_no_routing_syntax(self, raw):
        out = crt.client_safe_review_notes(raw, cc.STATUS_HUMAN_REVIEW)
        assert out and all(not ROUTING_RE.search(x) and "->" not in x for x in out), out

    def test_template_coverage_tracks_check_coverage_source(self):
        """Every routed downgrade literal check_coverage can persist is known here."""
        src = (ROOT / "check_coverage.py").read_text(encoding="utf-8")
        routed = set(re.findall(r'"([^"\n]*-> ?(?:HUMAN_REVIEW|PARTIALLY_ADDRESSED|NOT_VERIFIABLE_FROM_FILES|ADDRESSED)'
                                r'[^"\n]*)"', src))
        assert routed, "no routed templates found -- the source moved"
        for lit in routed:
            sample = lit.replace("{frag[:80]!r}", "'x'").replace("{cov}", "PARTIAL")
            sample = re.sub(r"\{[^}]*\}", "X", sample)
            for out in crt.client_safe_review_notes(sample, cc.STATUS_HUMAN_REVIEW):
                assert not ROUTING_RE.search(out), (lit, out)

    def test_ordinary_arrows_and_text_not_destroyed(self):
        raw = "buyer flow Stage 1 -> Stage 2 | see A -> B | element needs review: Proposal -> ADDRESSED form"
        out = crt.client_safe_review_notes(raw, cc.STATUS_HUMAN_REVIEW)
        assert out == ["buyer flow Stage 1 -> Stage 2", "see A -> B",
                       "element needs review: Proposal -> ADDRESSED form"]   # buyer wording verbatim
        assert crt.normalize_routing("price -> total") == "price -> total"
        assert crt.client_safe_review_notes("canonical requirement carries no buyer wording; nothing to check",
                                            cc.STATUS_HUMAN_REVIEW) == [
            "canonical requirement carries no buyer wording; nothing to check"]


class TestRawVsPresentation:
    def test_raw_notes_verbatim(self):
        raw = crt.raw_review_notes(RUN37_REASONS["REQ-5"])
        assert raw[0] == PH and len(raw) == 4 and any("-> HUMAN_REVIEW" in x for x in raw)
        a = {"ambiguity_or_review_reason": RUN37_REASONS["REQ-5"], "status": cc.STATUS_HUMAN_REVIEW}
        assert cwv.raw_review_notes(a) == raw

    def test_projection_never_mutates_input(self):
        adjs = run37_adjs()
        before = copy.deepcopy(adjs)
        for a in adjs:
            cwv.review_notes(a)
            crm.substantive_reasons(a)
        crm.build_report_model(run=t2d.run_row(), adjudications=adjs, evidence_index=run37_index(adjs),
                               files=[], bid=t2d.BIDROW)
        assert adjs == before

    def test_projection_differs_only_where_required(self):
        for a in run37_adjs():
            raw, safe = cwv.raw_review_notes(a), cwv.review_notes(a)
            if a["buyer_object_id"] not in RUN37_REASONS:
                assert safe == raw, a["buyer_object_id"]              # untouched rows render verbatim
            else:
                kept = [s for s in raw if not crt.is_commissioning_placeholder(s) and not ROUTING_RE.search(s)]
                assert [s for s in safe if s in raw] == kept           # clean segments verbatim, in order

    def test_durable_reconstruction_path_unchanged(self):
        row = {"buyer_object_id": "REQ-5", "buyer_object_type": cc.OBJECT_REQUIREMENT,
               "assurance_scope": "SUBMISSION_EVIDENCE_REQUIRED", "status": cc.STATUS_HUMAN_REVIEW,
               "buyer_expectation": "w", "ambiguity_or_review_reason": RUN37_REASONS["REQ-5"],
               "adjudication_method": "MODEL"}
        assert csr.adjudication_from_row(row).ambiguity_or_review_reason == RUN37_REASONS["REQ-5"]


class TestStatusIntegrity:
    def test_statuses_unchanged_through_every_surface(self):
        adjs = run37_adjs()
        raw_status = {a["buyer_object_id"]: a["status"] for a in adjs}
        m = crm.build_report_model(run=t2d.run_row(), adjudications=adjs, evidence_index=run37_index(adjs),
                                   files=[], bid=t2d.BIDROW)
        counts = {c["status"]: c["count"] for c in m["overview"]["counts"]}
        assert counts == {crm.ADDRESSED: 18, crm.PARTIAL: 11, crm.NOT_ADDRESSED: 0, crm.NOT_VERIFIABLE: 6,
                          crm.HUMAN_REVIEW: 2}
        for f in m["attention"]:
            for x in f["applies_to"]:
                assert x["status"] == raw_status[x["object_id"]]
        hr = {f["unit_id"] for f in m["attention"] if f["ref"] in m["human_review"]}
        nv = {f["unit_id"] for f in m["attention"] if f["ref"] in m["not_verifiable"]}
        pa = {f["unit_id"] for f in m["attention"] if f["ref"] in m["partials"]}
        assert hr == {"REQ-5", "REQ-16"} and not (hr & nv) and not (hr & pa) and not (nv & pa)
        assert by_id(adjs, "REQ-5")["status"] == cc.STATUS_HUMAN_REVIEW
        assert by_id(adjs, "REQ-40")["status"] == cc.STATUS_ADDRESSED     # routing text never re-routes status

    def test_workspace_status_pill_unchanged(self):
        adjs = run37_adjs()
        html = cwv.render_card(by_id(adjs, "REQ-5"), run37_index(adjs))
        assert "Human review required" in html
        html = cwv.render_card(by_id(adjs, "REQ-44"), run37_index(adjs))
        assert "Partially addressed" in html and "Human review required" not in html


# ═══════════════════════════════════════════════════════════════════════
# B. Surfaces
# ═══════════════════════════════════════════════════════════════════════

class TestWorkspaceSurfaces:
    def test_placeholder_and_routing_cannot_reach_workspace_html(self):
        adjs = run37_adjs()
        index = run37_index(adjs)
        parts = [cwv.render_attention(cwv.attention_items(adjs))]
        for a in adjs:
            parts.append(cwv.render_card(a, index))
            for inc in (True, False):
                detail, overflow = cwv.render_detail(a, index, include_elements=inc)
                parts += [detail, overflow]
        text = "".join(parts)
        assert_clean(text)
        assert "Why CHECK cannot safely determine coverage" in text     # human judgment still flagged
        assert "no additional narrative reason" not in text              # REQ-5 has structured reasons

    def test_page_renders_clean_with_zero_calls(self, monkeypatch, provider_calls):
        t2c.install(monkeypatch, t2c.FakeService(result=run37_result()))
        app = t2c.run_app()
        assert not app.exception
        text = "\n".join(m.value for m in app.markdown)
        assert "REQ-5" in text
        assert_clean(text)
        assert provider_calls == []


class TestReportSurfaces:
    def test_model_fields_clean(self):
        adjs = run37_adjs()
        m = crm.build_report_model(run=t2d.run_row(), adjudications=adjs, evidence_index=run37_index(adjs),
                                   files=[], bid=t2d.BIDROW)
        assert_clean(repr(m))
        f5 = next(f for f in m["attention"] if f["unit_id"] == "REQ-5")
        assert f5["status"] == crm.HUMAN_REVIEW
        assert f5["reasons"][0] == f"element needs review: {REQ5_ELEMENT}"
        assert f5["reviewer_checks"] == [REQ5_ELEMENT]                  # only persisted metadata

    def test_pdf_clean_with_zero_calls(self, provider_calls):
        adjs = run37_adjs()
        out = car.render_report(run=t2d.run_row(), adjudications=adjs, evidence_index=run37_index(adjs),
                                files=[], bid=t2d.BIDROW)
        text = t2d.text_of(out["pdf"])
        assert_clean(text)
        assert "HUMAN REVIEW REQUIRED" in text or "Human review required" in text
        assert provider_calls == []

    def test_export_through_tenancy_clean_zero_calls(self, monkeypatch, provider_calls):
        result = run37_result()
        import database as db

        def get_result(bid_id, run_id=None):
            return {"run": t2d.run_row(), "result": result, "result_payload": {"semantic_batches": []},
                    "semantic_batches": [], "is_complete": True, "result_digest_verified": True}
        monkeypatch.setattr(csr, "get_check_run_result", get_result)
        monkeypatch.setattr(tenancy, "get_bid_for_organization", lambda b, o: {"id": b} if o == ORG else None)
        monkeypatch.setattr(tenancy, "load_submission_evidence_package_for_organization",
                            lambda b, o, s: t2c.calgary_package())
        monkeypatch.setattr(db, "get_bid", lambda b: dict(t2d.BIDROW))
        before = [a.to_dict() for a in result.adjudications]
        out = tenancy.export_check_assurance_report_for_organization(BID, ORG, RUN)
        assert out["pdf"].startswith(b"%PDF")
        assert_clean(t2d.text_of(out["pdf"]))
        assert [a.to_dict() for a in result.adjudications] == before    # raw durable values untouched
        assert provider_calls == []


class TestPurity:
    def test_helper_module_is_pure(self):
        tree = ast.parse((ROOT / "components" / "check_review_text.py").read_text(encoding="utf-8"))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                names.add((node.module or "").split(".")[0])
        assert names <= {"__future__", "re"}, names

    def test_single_projection_shared_by_both_surfaces(self):
        src_view = (ROOT / "components" / "check_workspace_view.py").read_text(encoding="utf-8")
        src_model = (ROOT / "components" / "check_report_model.py").read_text(encoding="utf-8")
        assert "crt.client_safe_review_notes(" in src_view
        assert "ambiguity_or_review_reason" not in src_model             # the model only reads via cwv
        page_src = (ROOT / "pages" / "stage_check_assurance.py").read_text(encoding="utf-8")
        report_src = (ROOT / "check_assurance_report.py").read_text(encoding="utf-8")
        assert "ambiguity_or_review_reason" not in page_src and "ambiguity_or_review_reason" not in report_src
