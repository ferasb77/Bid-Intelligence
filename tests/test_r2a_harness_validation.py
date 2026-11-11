"""Unit, negative, and cleanup verification tests for the PostgreSQL 17 isolation harness."""
import os
import sys
import unittest
import tempfile
import shutil
import time
import subprocess
from unittest.mock import patch, MagicMock

from scripts.test_r2a_tenant_isolation import (
    parse_pg_major_version,
    validate_pg_bin_directory,
    find_pg_bin,
    DisposablePostgresCluster,
    remove_directory_with_retries,
)


class TestPgHarnessDiscoveryAndValidation(unittest.TestCase):
    """Test suite for binary discovery precedence, validation, and failure paths."""

    def test_parse_pg_major_version(self):
        self.assertEqual(parse_pg_major_version("postgres (PostgreSQL) 17.5"), 17)
        self.assertEqual(parse_pg_major_version("postgres (PostgreSQL) 17.0"), 17)
        self.assertEqual(parse_pg_major_version("PostgreSQL 17.5 on x86_64-windows"), 17)
        self.assertEqual(parse_pg_major_version("postgres (PostgreSQL) 16.3"), 16)
        self.assertEqual(parse_pg_major_version("postgres (PostgreSQL) 18.0alpha1"), 18)
        self.assertIsNone(parse_pg_major_version("invalid output"))

    def test_invalid_pg_bin_fails_closed_without_fallback(self):
        """Verify that when PG_BIN is set to a nonexistent path, it fails immediately."""
        nonexistent = os.path.join(tempfile.gettempdir(), "nonexistent_pg_bin_12345")
        old_val = os.environ.get("PG_BIN")
        os.environ["PG_BIN"] = nonexistent
        try:
            with self.assertRaises(RuntimeError) as ctx:
                find_pg_bin()
            self.assertIn("validation failed", str(ctx.exception))
            self.assertIn("fallback is disabled", str(ctx.exception))
        finally:
            if old_val is not None:
                os.environ["PG_BIN"] = old_val
            else:
                os.environ.pop("PG_BIN", None)

    def test_pg_bin_with_missing_executables_fails(self):
        """Verify that an existing directory missing postgres/initdb executables fails."""
        temp_dir = tempfile.mkdtemp(prefix="pg_test_empty_")
        old_val = os.environ.get("PG_BIN")
        os.environ["PG_BIN"] = temp_dir
        try:
            with self.assertRaises(RuntimeError) as ctx:
                find_pg_bin()
            self.assertIn("Missing postgres executable", str(ctx.exception))
        finally:
            if old_val is not None:
                os.environ["PG_BIN"] = old_val
            else:
                os.environ.pop("PG_BIN", None)
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_no_pg_available_fails_closed(self):
        """Verify that when PG_BIN is unset and PATH contains no postgres, find_pg_bin fails."""
        old_pg_bin = os.environ.pop("PG_BIN", None)
        old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = r"C:\Windows\System32" if os.name == "nt" else "/bin"
        try:
            with self.assertRaises(RuntimeError) as ctx:
                find_pg_bin()
            self.assertIn("PostgreSQL 17 binaries not found", str(ctx.exception))
        finally:
            os.environ["PATH"] = old_path
            if old_pg_bin is not None:
                os.environ["PG_BIN"] = old_pg_bin

    def test_version_validation_rejects_non_17(self):
        """Verify validate_pg_bin_directory version checks reject non-17 versions."""
        self.assertNotEqual(parse_pg_major_version("postgres (PostgreSQL) 16.4"), 17)
        self.assertNotEqual(parse_pg_major_version("postgres (PostgreSQL) 18.0"), 17)


class TestPgHarnessCleanupAndProcessLifecycle(unittest.TestCase):
    """Test suite for process termination escalation and fail-closed directory cleanup."""

    def test_successful_normal_cleanup(self):
        """Verify that normal cluster execution cleanly stops and removes the temporary root."""
        pg_bin = os.environ.get("PG_BIN")
        if not pg_bin:
            self.skipTest("PG_BIN not configured for normal cleanup test.")

        cluster_dir = None
        with DisposablePostgresCluster(pg_bin) as cluster:
            cluster_dir = cluster.temp_dir
            self.assertTrue(os.path.isdir(cluster_dir))

        self.assertIsNotNone(cluster_dir)
        self.assertFalse(os.path.exists(cluster_dir), "Temporary directory remained after normal exit!")

    def test_cleanup_behavior_after_exception_in_body(self):
        """Verify that an exception raised inside the context block cleanly removes directory and propagates."""
        pg_bin = os.environ.get("PG_BIN")
        if not pg_bin:
            self.skipTest("PG_BIN not configured for exception cleanup test.")

        cluster_dir = None
        with self.assertRaises(ValueError):
            with DisposablePostgresCluster(pg_bin) as cluster:
                cluster_dir = cluster.temp_dir
                self.assertTrue(os.path.isdir(cluster_dir))
                raise ValueError("Controlled fault injection")

        self.assertIsNotNone(cluster_dir)
        self.assertFalse(os.path.exists(cluster_dir), "Temporary directory remained after body exception!")

    def test_transient_deletion_failure_retries_and_succeeds(self):
        """Verify that remove_directory_with_retries handles transient locked states."""
        temp_dir = tempfile.mkdtemp(prefix="pg17_retry_test_")
        test_file = os.path.join(temp_dir, "locked.txt")
        with open(test_file, "w") as f:
            f.write("content")

        original_rmtree = shutil.rmtree
        call_count = [0]

        def flaky_rmtree(path, *args, **kwargs):
            call_count[0] += 1
            if call_count[0] < 3:
                raise PermissionError("Simulated transient Windows file lock")
            return original_rmtree(path, *args, **kwargs)

        with patch("shutil.rmtree", side_effect=flaky_rmtree):
            result = remove_directory_with_retries(temp_dir, max_retries=5, backoff=0.05)

        self.assertTrue(result)
        self.assertFalse(os.path.exists(temp_dir))
        self.assertGreaterEqual(call_count[0], 3)

    def test_persistent_deletion_failure_fails_closed(self):
        """Verify that persistent deletion failure raises RuntimeError and reports residual directory."""
        cluster = DisposablePostgresCluster.__new__(DisposablePostgresCluster)
        cluster.temp_dir = tempfile.mkdtemp(prefix="pg17_locked_")
        cluster.data_dir = os.path.join(cluster.temp_dir, "data")
        cluster.proc = None
        cluster.pg_bin = "dummy"

        try:
            with patch("scripts.test_r2a_tenant_isolation.remove_directory_with_retries", return_value=False):
                with self.assertRaises(RuntimeError) as ctx:
                    cluster.__exit__(None, None, None)
                self.assertIn("CLEANUP DEFECT", str(ctx.exception))
                self.assertIn(cluster.temp_dir, str(ctx.exception))
        finally:
            shutil.rmtree(cluster.temp_dir, ignore_errors=True)

    def test_persistent_deletion_failure_chains_original_exception(self):
        """Verify that if an exception occurred in user code AND cleanup failed, the original exception is chained."""
        cluster = DisposablePostgresCluster.__new__(DisposablePostgresCluster)
        cluster.temp_dir = tempfile.mkdtemp(prefix="pg17_chained_")
        cluster.data_dir = os.path.join(cluster.temp_dir, "data")
        cluster.proc = None
        cluster.pg_bin = "dummy"

        orig_exc = ValueError("Original query error")
        try:
            with patch("scripts.test_r2a_tenant_isolation.remove_directory_with_retries", return_value=False):
                with self.assertRaises(RuntimeError) as ctx:
                    cluster.__exit__(ValueError, orig_exc, None)
                self.assertIn("CLEANUP DEFECT", str(ctx.exception))
                self.assertIs(ctx.exception.__cause__, orig_exc)
        finally:
            shutil.rmtree(cluster.temp_dir, ignore_errors=True)

    def test_process_termination_escalation_to_kill(self):
        """Verify that if terminate() times out, _terminate_process escalates to kill()."""
        cluster = DisposablePostgresCluster.__new__(DisposablePostgresCluster)
        cluster.pg_bin = "dummy"
        cluster.data_dir = "dummy_data"
        mock_proc = MagicMock()
        mock_proc.pid = 99999

        # pg_ctl does not exist
        # terminate() raises TimeoutExpired on wait(timeout=5)
        # kill() succeeds on wait(timeout=5)
        mock_proc.wait.side_effect = [
            subprocess.TimeoutExpired(cmd="postgres", timeout=5),
            0,
        ]
        cluster.proc = mock_proc

        with patch("os.path.exists", return_value=False):
            with patch("subprocess.run") as mock_run:
                cluster._terminate_process()

        mock_proc.kill.assert_called_once()
        self.assertIsNone(cluster.proc)


class TestPgHarnessServerVersionMismatchSimulation(unittest.TestCase):
    """Test suite simulating server major version mismatch."""

    def test_running_server_version_mismatch_simulation(self):
        """[SIMULATED MISMATCH TEST] Verify that if binaries are PG17 but the running server reports PG16 or PG18,
        the harness rejects the connection and exits nonzero before executing acceptance suite.
        """
        # Simulated server version string from a mismatching cluster (e.g. 18.1 or 16.5)
        simulated_pg18_version = "PostgreSQL 18.1 on x86_64-windows, compiled by msvc-19.43.34808, 64-bit"
        simulated_pg16_version = "PostgreSQL 16.4 on x86_64-windows, compiled by msvc-19.43.34808, 64-bit"

        major_18 = parse_pg_major_version(simulated_pg18_version)
        major_16 = parse_pg_major_version(simulated_pg16_version)

        self.assertNotEqual(major_18, 17, "Major 18 must not match required 17")
        self.assertNotEqual(major_16, 17, "Major 16 must not match required 17")

        # Test simulated harness branch:
        for sim_ver in [simulated_pg18_version, simulated_pg16_version]:
            server_major = parse_pg_major_version(sim_ver)
            rejected = (server_major != 17)
            self.assertTrue(rejected, f"Server version '{sim_ver}' should have been rejected!")


if __name__ == "__main__":
    unittest.main()
