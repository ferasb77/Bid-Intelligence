"""Static contract checks for the forward-only raw-snapshot privilege fix."""
from pathlib import Path
import re


SQL = (Path(__file__).parent.parent / "migrations" /
       "028_restrict_analysis_results_snapshot_select.sql").read_text(encoding="utf-8").lower()
EXECUTABLE_SQL = re.sub(r"--[^\n]*", "", SQL)


def test_028_revokes_broad_anon_and_authenticated_select_before_narrow_grant():
    revoke = "revoke select on table public.analysis_results from anon, authenticated;"
    assert revoke in EXECUTABLE_SQL
    assert EXECUTABLE_SQL.index(revoke) < EXECUTABLE_SQL.index("grant select (")


def test_028_grants_only_authenticated_safe_projection_not_internal_payloads():
    for column in ("id", "run_id", "bid_id", "structured_intelligence", "fact_origins", "report_content_snapshot"):
        assert column in EXECUTABLE_SQL
    for internal in ("fast_analysis_result_snapshot", "full_analysis_result", "check_coverage_result"):
        assert internal not in EXECUTABLE_SQL.split("grant select", 1)[1]
    assert "to authenticated;" in EXECUTABLE_SQL
    assert "to anon;" not in EXECUTABLE_SQL


def test_028_explicitly_revokes_internal_column_grants_as_drift_defense():
    for internal in ("fast_analysis_result_snapshot", "full_analysis_result", "check_coverage_result", "created_at"):
        assert internal in EXECUTABLE_SQL.split("revoke select (", 1)[1].split(") on table", 1)[0]


def test_028_does_not_change_rls_or_service_role_permissions():
    for forbidden in ("create policy", "drop policy", "alter table", "service_role", "insert into", "update ", "delete from"):
        assert forbidden not in EXECUTABLE_SQL


def test_028_harness_unit_suite_passes():
    import subprocess
    script = Path(__file__).parent.parent / "scripts" / "test_postgres_analysis_results_snapshot_data_api.test.js"
    res = subprocess.run(["node", str(script)], capture_output=True, text=True, check=False)
    assert res.returncode == 0, f"Harness unit suite failed:\n{res.stderr}\n{res.stdout}"
    assert re.search(r"ALL \d+ HARNESS UNIT TESTS PASSED", res.stdout) is not None
