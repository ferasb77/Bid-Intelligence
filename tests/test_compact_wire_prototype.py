"""
tests/test_compact_wire_prototype.py

BI Token Optimization Program, Phase 5D: compact provenance wire PROTOTYPE.
Zero provider calls -- everything here is pure Python over already-
persisted historical artifacts or hand-built synthetic fixtures. This
prototype is NOT wired into fast_analysis.py/extractor.py; these tests
guard against that ever happening silently (no import of this module
from any production file) and prove the round-trip contract that would
need to hold before any future live activation.
"""
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import compact_wire_prototype as cwp  # noqa: E402

_V4_FACTS = (Path(__file__).resolve().parents[1] / "evaluation" / "bank_of_canada_briefing_pack"
            / "fast_analysis" / "fastanalysis-v4-boc-2026-026-20260914T130015Z-e0720d"
            / "fast_analysis_facts.json")
_STAGE_A_FACTS = (Path(__file__).resolve().parents[1] / "evaluation" / "bank_of_canada_briefing_pack"
                  / "performance_telemetry" / "stagea-perf-boc-2026-026-20260912T224533Z-cf5a4d"
                  / "stage_a_document_facts.json")

requires_v4 = pytest.mark.skipif(not _V4_FACTS.exists(), reason="real V4 artifact not present locally")
requires_stage_a = pytest.mark.skipif(not _STAGE_A_FACTS.exists(), reason="real Stage A artifact not present locally")


@pytest.fixture(autouse=True)
def zero_inference_guard():
    with patch("anthropic.Anthropic", side_effect=AssertionError(
            "zero-inference guard: no Anthropic client may be constructed in Phase 5D tests")):
        yield


def _ref(source_doc, page=None, sheet=None, section=None, excerpt=None, **extra):
    d = {"source_doc": source_doc, "page": page, "sheet": sheet, "section": section}
    if excerpt is not None:
        d["excerpt"] = excerpt
    d.update(extra)
    return d


class TestCanonicalSourceIdentity:

    def test_same_marker_same_identity(self):
        a = _ref("f.pdf", page=3, excerpt="text one")
        b = _ref("f.pdf", page=3, excerpt="different quote")
        assert cwp.canonical_source_identity(a) == cwp.canonical_source_identity(b)

    def test_different_page_different_identity(self):
        a = _ref("f.pdf", page=3)
        b = _ref("f.pdf", page=4)
        assert cwp.canonical_source_identity(a) != cwp.canonical_source_identity(b)

    def test_different_sheet_different_identity(self):
        a = _ref("f.xlsx", sheet="Sheet1")
        b = _ref("f.xlsx", sheet="Sheet2")
        assert cwp.canonical_source_identity(a) != cwp.canonical_source_identity(b)

    def test_different_filename_different_identity(self):
        a = _ref("a.pdf", page=1)
        b = _ref("b.pdf", page=1)
        assert cwp.canonical_source_identity(a) != cwp.canonical_source_identity(b)

    def test_excerpt_excluded_from_identity(self):
        a = _ref("f.pdf", page=1, excerpt="X")
        assert "excerpt" not in zip(cwp._IDENTITY_FIELDS, cwp.canonical_source_identity(a))
        assert len(cwp.canonical_source_identity(a)) == 4


class TestSourceRegistry:

    def test_same_marker_gets_same_id(self):
        reg = cwp.SourceRegistry()
        a = _ref("f.pdf", page=1)
        b = _ref("f.pdf", page=1)
        assert reg.register(a) == reg.register(b)

    def test_different_marker_gets_different_id(self):
        reg = cwp.SourceRegistry()
        id1 = reg.register(_ref("f.pdf", page=1))
        id2 = reg.register(_ref("f.pdf", page=2))
        assert id1 != id2

    def test_no_collisions_across_many_distinct_markers(self):
        reg = cwp.SourceRegistry()
        ids = {reg.register(_ref(f"f{i}.pdf", page=i)) for i in range(500)}
        assert len(ids) == 500

    def test_ordering_deterministic_across_runs(self):
        markers = [_ref("a.pdf", page=1), _ref("b.pdf", page=2), _ref("a.pdf", page=1)]
        reg1, reg2 = cwp.SourceRegistry(), cwp.SourceRegistry()
        ids1 = [reg1.register(m) for m in markers]
        ids2 = [reg2.register(m) for m in markers]
        assert ids1 == ids2

    def test_registry_round_trip_lossless(self):
        reg = cwp.SourceRegistry()
        marker = _ref("f.pdf", page=5, sheet=None, section="Terms")
        sid = reg.register(marker)
        identity = reg.identity_for(sid)
        assert dict(zip(cwp._IDENTITY_FIELDS, identity)) == {
            "source_doc": "f.pdf", "page": 5, "sheet": None, "section": "Terms"}

    def test_unknown_id_resolves_to_none_not_a_guess(self):
        reg = cwp.SourceRegistry()
        reg.register(_ref("f.pdf", page=1))
        assert reg.identity_for("S999") is None


class TestModelCannotInventIds:

    def test_expand_rejects_id_not_in_registry(self):
        reg = cwp.SourceRegistry()
        reg.register(_ref("f.pdf", page=1))
        with pytest.raises(cwp.CompactWireError, match="unknown source id"):
            cwp.expand_compact_ref({"s": "S999"}, reg)

    def test_expand_rejects_unknown_evidence_id(self):
        reg = cwp.SourceRegistry()
        reg.register(_ref("f.pdf", page=1))
        ev = cwp.EvidenceRegistry()
        with pytest.raises(cwp.CompactWireError, match="unknown evidence id"):
            cwp.expand_compact_ref({"s": "S1", "eid": "E999"}, reg, ev)

    def test_expand_rejects_malformed_shape_missing_s(self):
        reg = cwp.SourceRegistry()
        with pytest.raises(cwp.CompactWireError):
            cwp.expand_compact_ref({"eid": "E1"}, reg)

    def test_expand_rejects_unexpected_keys(self):
        reg = cwp.SourceRegistry()
        reg.register(_ref("f.pdf", page=1))
        with pytest.raises(cwp.CompactWireError):
            cwp.expand_compact_ref({"s": "S1", "bogus_field": "x"}, reg)

    def test_expand_rejects_both_inline_and_dictionary_evidence(self):
        reg = cwp.SourceRegistry()
        reg.register(_ref("f.pdf", page=1))
        with pytest.raises(cwp.CompactWireError, match="both inline and dictionary"):
            cwp.expand_compact_ref({"s": "S1", "e": "text", "eid": "E1"}, reg)


class TestCompactExpandRoundTripSynthetic:

    def test_simple_ref_round_trips_exactly(self):
        reg = cwp.SourceRegistry()
        original = _ref("f.pdf", page=1, sheet=None, section=None, excerpt="quoted text")
        reg.register(original)
        compact = cwp.compact_source_ref(original, reg)
        expanded = cwp.expand_compact_ref(compact, reg)
        assert expanded == original

    def test_sparse_ref_missing_keys_round_trips_exactly(self):
        """Real historical data (V4) has refs that omit page/sheet/section/
        excerpt ENTIRELY rather than nulling them -- this is the exact bug
        this test guards against regressing."""
        reg = cwp.SourceRegistry()
        original = {"source_doc": "f.pdf"}  # no page/sheet/section/excerpt keys at all
        reg.register(original)
        compact = cwp.compact_source_ref(original, reg)
        expanded = cwp.expand_compact_ref(compact, reg)
        assert expanded == original
        assert "page" not in expanded

    def test_partially_sparse_ref_round_trips_exactly(self):
        reg = cwp.SourceRegistry()
        original = {"source_doc": "f.docx", "page": None, "sheet": None, "section": "Header"}  # no excerpt key
        reg.register(original)
        compact = cwp.compact_source_ref(original, reg)
        expanded = cwp.expand_compact_ref(compact, reg)
        assert expanded == original
        assert "excerpt" not in expanded

    def test_evidence_dictionary_round_trips_exactly(self):
        reg = cwp.SourceRegistry()
        ev = cwp.EvidenceRegistry()
        a = _ref("f.pdf", page=1, excerpt="Submit a signed declaration.")
        b = _ref("f.pdf", page=2, excerpt="Submit a signed declaration.")
        for r in (a, b):
            reg.register(r)
        ev.register("Submit a signed declaration.")
        for original in (a, b):
            compact = cwp.compact_source_ref(original, reg, ev)
            assert "eid" in compact  # duplicated text -> dictionary reference used
            expanded = cwp.expand_compact_ref(compact, reg, ev)
            assert expanded == original

    def test_full_facts_structure_round_trips_exactly(self):
        original = {
            "requirements": [
                {"req_id": "R1", "description": "Deliver on time",
                 "source_refs": [_ref("f.pdf", page=1, excerpt="Deliver on time per schedule.")]},
                {"req_id": "R2", "description": "Provide references",
                 "source_refs": [_ref("f.pdf", page=1, excerpt="Deliver on time per schedule."),
                                 {"source_doc": "f.pdf"}]},  # sparse, no other keys
            ],
            "evaluation_criteria": [
                {"stage": "Technical", "weight": "40%", "source_refs": []},
            ],
        }
        expanded, is_exact, report = cwp.round_trip(original)
        assert is_exact is True
        assert expanded == original
        assert report["source_identities"] == 2  # (f.pdf,1,None,None) and (f.pdf,None,None,None)


class TestNoFullTextLeak:

    def test_alias_study_never_echoes_document_content(self):
        secret = "PROPRIETARY RFP CLAUSE TEXT " * 20
        obj = {"description": secret}
        result = cwp.alias_savings_study(obj, {"description": "d"})
        assert secret not in json.dumps(result)


@requires_v4
class TestRealV4RoundTrip:

    def test_v4_facts_round_trip_exactly(self):
        original = json.loads(_V4_FACTS.read_text(encoding="utf-8"))
        expanded, is_exact, report = cwp.round_trip(original)
        assert is_exact is True
        assert expanded == original

    def test_v4_reduction_is_measured_and_positive(self):
        original = json.loads(_V4_FACTS.read_text(encoding="utf-8"))
        _, is_exact, report = cwp.round_trip(original)
        assert is_exact is True
        assert report["compact_total_bytes"] < report["original_bytes"]

    def test_v4_source_identity_count_matches_phase_5c_finding(self):
        original = json.loads(_V4_FACTS.read_text(encoding="utf-8"))
        registry = cwp.build_registry_from_facts(original)
        assert len(registry) == 40  # Phase 5C/5D-verified: 40 unique identities, 239 occurrences


@requires_stage_a
class TestRealStageARoundTrip:

    def test_stage_a_facts_round_trip_exactly(self):
        original = json.loads(_STAGE_A_FACTS.read_text(encoding="utf-8"))
        expanded, is_exact, report = cwp.round_trip(original)
        assert is_exact is True
        assert expanded == original


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
