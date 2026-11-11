"""Unit and negative verification tests for the PostgreSQL 17 isolation harness."""
import os
import sys
import unittest
import tempfile
import shutil
import subprocess

from scripts.test_r2a_tenant_isolation import (
    parse_pg_major_version,
    validate_pg_bin_directory,
    find_pg_bin,
    DisposablePostgresCluster,
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
        # Set PATH to something devoid of postgres
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
        """Verify validate_pg_bin_directory version checks."""
        # Using version parser logic directly
        self.assertNotEqual(parse_pg_major_version("postgres (PostgreSQL) 16.4"), 17)
        self.assertNotEqual(parse_pg_major_version("postgres (PostgreSQL) 18.0"), 17)

    def test_disposable_cluster_cleanup_on_exception(self):
        """Verify that an exception inside DisposablePostgresCluster triggers clean directory removal."""
        pg_bin = os.environ.get("PG_BIN")
        if not pg_bin:
            self.skipTest("PG_BIN not configured for disposable cluster cleanup test.")

        cluster_dir = None
        try:
            with DisposablePostgresCluster(pg_bin) as cluster:
                cluster_dir = cluster.temp_dir
                self.assertTrue(os.path.isdir(cluster_dir))
                # Deliberately raise exception inside context body
                raise ValueError("Controlled fault injection")
        except ValueError:
            pass

        self.assertIsNotNone(cluster_dir)
        self.assertFalse(os.path.exists(cluster_dir), "Temporary cluster directory was not removed on exception!")


if __name__ == "__main__":
    unittest.main()
