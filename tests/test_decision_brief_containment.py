"""Regression tests for the temporary P0 Decision Brief containment guard."""

from __future__ import annotations

from unittest.mock import patch

import pytest

import analysis_service
import tenancy


def test_decision_brief_public_service_paths_fail_closed_without_loading_a_snapshot():
    """Neither interactive construction nor PDF export may reach unsafe assembly."""
    with patch("database.get_analysis_run") as get_run, patch(
        "decision_brief.build_decision_brief_from_analysis"
    ) as build_brief, patch(
        "decision_brief_report.render_decision_brief_bytes"
    ) as render_pdf, patch(
        "understand_brief.build_bid_intelligence_brief"
    ) as build_legacy_brief:
        for operation in (
            lambda: analysis_service.load_decision_brief_for_run(61),
            lambda: analysis_service.generate_bid_intelligence_brief_from_raw_snapshot(61),
            lambda: analysis_service._render_brief_snapshot_impl(61),
        ):
            with pytest.raises(
                analysis_service.DecisionBriefUnavailableError,
                match="temporarily unavailable while its source evidence is being validated",
            ):
                operation()

    get_run.assert_not_called()
    build_brief.assert_not_called()
    render_pdf.assert_not_called()
    build_legacy_brief.assert_not_called()


def test_tenancy_decision_brief_and_export_paths_cannot_bypass_containment():
    """Ownership checks remain in place, then both public tenancy paths fail closed."""
    run = {"id": 61, "bid_id": 1675, "status": "COMPLETE"}
    with patch("tenancy.require_bid_access") as require_access, patch(
        "database.get_analysis_run", return_value=run
    ):
        for operation in (
            lambda: tenancy.get_decision_brief_for_organization(1675, 61, "org-test"),
            lambda: tenancy.export_bid_intelligence_brief_for_organization(1675, 61, "org-test"),
        ):
            with pytest.raises(analysis_service.DecisionBriefUnavailableError):
                operation()

    assert require_access.call_count == 2
