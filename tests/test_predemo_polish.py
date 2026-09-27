"""
Targeted tests for Pre-Demo Polish Pass on Bid Intelligence.
Covers:
  - Issue A: Removal of internal benchmark/developer text from UNDERSTAND summary.
  - Issue B: Single customer-facing CHECK navigation entry in sidebar.
  - Issue C: Canonical closing-date presentation from procurement data without hard-coding.
  - Zero model/provider calls throughout.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pages.stage_understand as understand

ROOT = Path(__file__).resolve().parent.parent


def test_internal_benchmark_text_filter():
    """_is_internal_benchmark_text correctly identifies developer/benchmark terms."""
    forbidden = [
        "CHECK-1.1 canonical CHECK benchmark bid",
        "Held only as submission evidence (migration 021)",
        "Migration 022 check runs commissioning",
        "Test fixture for holdout run 6",
        "Commissioning run 37 complete",
        "Benchmark bid for Calgary RFP 26-1603",
    ]
    for text in forbidden:
        assert understand._is_internal_benchmark_text(text) is True, f"Failed to flag: {text}"

    clean = [
        "The City of Calgary is procuring Design and Delivery Services for Leadership Learning and Development.",
        "Comprehensive leadership training program across municipal tiers.",
        "RFP 26-1603 consulting services.",
    ]
    for text in clean:
        assert understand._is_internal_benchmark_text(text) is False, f"Erroneously flagged: {text}"


def test_customer_safe_summary_resolution_suppresses_benchmark_text():
    """Summary resolver replaces internal benchmark copy with clean procurement intelligence."""
    bid = {
        "title": "RFP 26-1603 - Design and Delivery Services for Leadership Learning and Development",
        "client": "The City of Calgary",
        "file_number": "26-1603",
        "notes": "CHECK-1.1 canonical CHECK benchmark bid. Held as submission evidence (migration 021).",
    }
    brief_row = {
        "executive_summary": "Test fixture summary referencing CHECK-1 commissioning."
    }
    analysis_result = {
        "structured_intelligence": {
            "procurement_scope": {
                "intro": "The City of Calgary is procuring 1 service type: Team Experience and Qualifications."
            }
        },
        "report_content_snapshot": {
            "PROCURED_INTRO": "The City of Calgary is procuring 1 service type: Team Experience and Qualifications."
        }
    }

    # When both brief_row and notes have benchmark terms, it falls back to procurement_scope intro
    summary = understand._resolve_customer_safe_summary(bid, brief_row, analysis_result)
    assert "CHECK" not in summary
    assert "migration" not in summary
    assert "fixture" not in summary
    assert "The City of Calgary is procuring" in summary


def test_customer_safe_summary_resolution_uses_clean_notes_when_available():
    """Summary resolver uses notes when notes contain clean, factual procurement information."""
    bid = {
        "title": "RFP 26-1603 - Design and Delivery Services for Leadership Learning and Development",
        "client": "The City of Calgary",
        "file_number": "26-1603",
        "notes": "The City of Calgary is procuring Design and Delivery Services for Leadership Learning and Development.",
    }
    brief_row = {}
    summary = understand._resolve_customer_safe_summary(bid, brief_row, None)
    assert summary == "The City of Calgary is procuring Design and Delivery Services for Leadership Learning and Development."


def test_single_check_sidebar_navigation_entry():
    """Sidebar exposes exactly one CHECK entry point with sequence number 4."""
    src = (ROOT / "app.py").read_text(encoding="utf-8")

    # Verify app routes
    assert "from pages.stage_check_assurance import page_check_assurance" in src
    assert '"🛡️  4. CHECK: Proposal Assurance": "stage_check_assurance"' in src
    assert '"🔍  4. CHECK":      "stage_check"' not in src
    assert '"🛡️  CHECK: Proposal Assurance": "stage_check_assurance"' not in src

    # Verify both route names dispatch to Proposal Assurance
    assert 'elif page in ("stage_check_assurance", "stage_check", "compliance", "proposal_analyzer"):' in src
    assert 'page_check_assurance(bid_id)' in src


def test_canonical_closing_date_resolution():
    """_resolve_canonical_deadlines pulls canonical dates without hard-coding."""
    bid = {"submission_deadline": None, "clarification_deadline": None}
    brief_row = {}
    analysis_result = {
        "fast_analysis_result_snapshot": {
            "result": {
                "doc_metadata_by_doc": {
                    "Addendum Four.pdf": {"submission_deadline": "2026-07-16", "clarification_deadline": "2026-07-15"},
                    "RFP.docx": {"submission_deadline": "2026-07-07", "clarification_deadline": "2026-07-03"},
                },
                "canonical_milestones": [
                    {"label": "SUBMISSION_DEADLINE", "normalized_date_start": "2026-07-16"},
                    {"label": "CLARIFICATION_DEADLINE", "normalized_date_start": "2026-07-15"},
                ]
            }
        }
    }

    sub_dl, clar_dl = understand._resolve_canonical_deadlines(bid, brief_row, analysis_result)
    assert sub_dl == "2026-07-16"
    assert clar_dl == "2026-07-15"


def test_canonical_closing_date_dynamic_variation():
    """Changing canonical date in analysis_result changes resolved date (no hardcoding)."""
    bid = {"submission_deadline": None, "clarification_deadline": None}
    brief_row = {}
    analysis_result = {
        "fast_analysis_result_snapshot": {
            "result": {
                "doc_metadata_by_doc": {
                    "Addendum Nine.pdf": {"submission_deadline": "2026-09-01", "clarification_deadline": "2026-08-25"},
                },
                "canonical_milestones": [
                    {"label": "SUBMISSION_DEADLINE", "normalized_date_start": "2026-09-01"},
                    {"label": "CLARIFICATION_DEADLINE", "normalized_date_start": "2026-08-25"},
                ]
            }
        }
    }

    sub_dl, clar_dl = understand._resolve_canonical_deadlines(bid, brief_row, analysis_result)
    assert sub_dl == "2026-09-01"
    assert clar_dl == "2026-08-25"


def test_award_date_is_not_fabricated():
    """Ensure no fabricated Award Date exists in stage_understand UI code."""
    src = (ROOT / "pages" / "stage_understand.py").read_text(encoding="utf-8")
    assert "metric_card(\"Award Date\"" not in src
    assert "Award Date" not in src
