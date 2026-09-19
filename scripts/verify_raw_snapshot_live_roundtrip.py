"""
scripts/verify_raw_snapshot_live_roundtrip.py

One-shot, disposable, zero-LLM-call live verification of the raw Fast
Analysis snapshot durability path (migration 012) against the actual
configured Supabase project. Creates one throwaway bid (never touches
Phoenix/bid 1083 or any other existing row), persists a synthetic
FastAnalysisResult snapshot through the NORMAL application persistence
path (database.create_analysis_result), reads it back through the NORMAL
application read path (analysis_service.load_raw_fast_analysis_result /
regenerate_report_from_raw_snapshot), and then deletes the throwaway bid
(cascades delete its analysis_runs/analysis_results rows too).

Makes NO Anthropic/model calls anywhere -- run_fast_analysis_corpus is
never imported or invoked.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import database as db
import analysis_service as svc
from fast_analysis import FastAnalysisResult, serialize_fast_analysis_result


def _rich_result() -> FastAnalysisResult:
    r = FastAnalysisResult()
    r.doc_metadata_by_doc = {
        "RFP.pdf": {"title": "Coaching Services RFP", "client": "Some Buyer", "file_number": "RFP-1"},
    }
    r.typed_observations = [
        {"family": "QUALIFICATION_MECHANISM", "semantic_kind": "REFERENCE_CHECK",
         "original_value": "At least two positive references required to remain eligible.",
         "source_refs": [{"doc": "RFP.pdf", "page": 12}], "rank": None},
        {"family": "TIE_BREAK_RULE", "semantic_kind": "TIE_BREAK_CRITERION",
         "original_value": "Account Management & Relationship score governs first.",
         "source_refs": [{"doc": "RFP.pdf", "page": 14}], "rank": 1},
        {"family": "TIE_BREAK_RULE", "semantic_kind": "TIE_BREAK_CRITERION",
         "original_value": "Approach & Methodology score governs next.",
         "source_refs": [{"doc": "RFP.pdf", "page": 14}], "rank": 2},
    ]
    r.evaluation_criteria = [
        {"criterion_label": "Approach and Methodology", "weight": "10 points",
         "threshold": "6 points", "evaluation_role": "Award Criterion",
         "source_refs": [{"doc": "RFP.pdf", "page": 9}]},
    ]
    r.requirements = [{"description": "Submit a completed Appendix B.", "source_refs": []}]
    r.commercial_clauses = [{"clause_type": "Term", "text": "2 years", "source_refs": []}]
    r.evaluation_occurrences = [{"criterion_label": "Approach", "weight": "10 points"}]
    r.pricing_occurrences = [{"line_item": "Hourly Rate", "weight": "15 points"}]
    r.focused_sections_found = {"rated_criteria": ["RFP.pdf"]}
    r.page_limits = {"RFP.pdf": 40}
    r.skipped_documents = ["Terms_and_Conditions_Boilerplate.pdf"]
    r.batched_documents = ["Appendix_C.pdf", "Appendix_D.pdf"]
    r.documents_by_route = {"ROUTE_IDENTITY_EVAL_REQ": ["RFP.pdf"]}
    r.ambiguities = {"OTHER_DATE": []}
    r.telemetry = [
        {"call_kind": "initial", "filename": "RFP.pdf", "input_tokens": 1000, "output_tokens": 200},
        {"call_kind": "recovery", "filename": "RFP.pdf", "input_tokens": 300, "output_tokens": 50},
    ]
    r.wall_seconds = 238.99
    r.deterministic_seconds = 1.23
    r.buyer_intelligence = {"buyer_identity": "Some Buyer", "source_refs": []}
    r.deterministic_service_scope = {
        "trigger_sentence": "The Services will include providing the following:",
        "items": ["Coaching", "Resources", "Group Sessions"],
        "source_page": 4,
    }
    r.deterministic_response_guidelines = [
        {"id": "RG1", "weight": "10", "minimum_score": "6",
         "evidence_prompts": ["Describe your approach."], "source_doc": "Appendix_B.docx"},
    ]
    return r


def main():
    print("=" * 70)
    print("LIVE RAW-SNAPSHOT ROUND-TRIP VERIFICATION -- disposable data only")
    print("Zero Anthropic/model calls. Never touches Phoenix (bid 1083) or any")
    print("other existing row.")
    print("=" * 70)

    bid_id = db.create_bid({"title": "DURABILITY_TEST_DISPOSABLE_DO_NOT_KEEP",
                            "client": "Synthetic Test Buyer", "stage": "Analysis"})
    assert bid_id, "failed to create disposable test bid"
    print(f"[1] Created disposable bid_id={bid_id}")

    try:
        run_row = db.create_analysis_run(bid_id, "FAST", "fast-analysis-v4", [], corpus_digest=None,
                                         created_by="durability-verification-script")
        assert run_row, "failed to create disposable analysis_run"
        run_id = run_row["id"]
        db.update_analysis_run(run_id, {"status": "COMPLETE"})
        print(f"[2] Created disposable analysis_run id={run_id}, marked COMPLETE")

        original = _rich_result()
        payload = serialize_fast_analysis_result(original, engine_version="fast-analysis-v4")
        print(f"[3] Serialized synthetic FastAnalysisResult -- schema_version={payload['schema_version']}")

        created = db.create_analysis_result(
            run_id, bid_id, structured_intelligence={"note": "disposable test row"},
            fact_origins={}, report_content_snapshot={"note": "disposable test row"},
            fast_analysis_result_snapshot=payload)
        assert created and created.get("fast_analysis_result_snapshot"), \
            "NORMAL persistence path did not durably store the snapshot"
        print("[4] Persisted via database.create_analysis_result() -- the NORMAL "
             "application persistence path")

        restored = svc.load_raw_fast_analysis_result(run_id)
        assert isinstance(restored, FastAnalysisResult), \
            f"expected a reconstructed FastAnalysisResult, got {restored!r}"
        print("[5] Read back and deserialized via "
             "analysis_service.load_raw_fast_analysis_result() -- the NORMAL "
             "application read path")

        checks = [
            ("doc_metadata_by_doc", restored.doc_metadata_by_doc == original.doc_metadata_by_doc),
            ("typed_observations (qualification+tie-break+rank+source_refs)",
             restored.typed_observations == original.typed_observations),
            ("evaluation_criteria (minimum_score/threshold)",
             restored.evaluation_criteria == original.evaluation_criteria),
            ("deterministic_service_scope",
             restored.deterministic_service_scope == original.deterministic_service_scope),
            ("deterministic_response_guidelines",
             restored.deterministic_response_guidelines == original.deterministic_response_guidelines),
            ("buyer_intelligence", restored.buyer_intelligence == original.buyer_intelligence),
            ("wall_seconds", restored.wall_seconds == original.wall_seconds),
            ("skipped_documents", restored.skipped_documents == original.skipped_documents),
        ]
        all_ok = True
        for label, ok in checks:
            print(f"    [{'OK' if ok else 'FAIL'}] {label}")
            all_ok = all_ok and ok
        assert all_ok, "semantic equality check failed for at least one field"
        print("[6] All analytical fields verified semantically equal after the live round trip")

        pdf_bytes = svc.regenerate_report_from_raw_snapshot(run_id)
        assert pdf_bytes.startswith(b"%PDF"), "regeneration did not produce a real PDF"
        print(f"[7] regenerate_report_from_raw_snapshot() produced a real PDF "
             f"({len(pdf_bytes)} bytes) -- run_fast_analysis_corpus was never imported "
             f"or called anywhere in this script")

        print("\nROUND TRIP: PASS")
    finally:
        db.delete_bid(bid_id)
        print(f"[8] Deleted disposable bid_id={bid_id} (cascades delete its "
             f"analysis_runs/analysis_results rows)")

        sb = db.get_client()
        remaining = sb.table("bids").select("id").eq("id", bid_id).execute().data
        remaining_run = sb.table("analysis_runs").select("id").eq("bid_id", bid_id).execute().data
        print(f"[9] Cleanup verification: bid rows remaining={len(remaining)}, "
             f"its analysis_runs rows remaining={len(remaining_run)}")


if __name__ == "__main__":
    main()
