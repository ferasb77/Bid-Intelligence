"""Regression coverage for durable, server-named document uploads."""
import unittest
from unittest.mock import MagicMock, patch

import database


class TestStorageUploadFailureHandling(unittest.TestCase):
    def _failing_storage_client(self):
        client = MagicMock()
        client.storage.from_.return_value.upload.side_effect = Exception("storage unavailable")
        return client

    @patch("database.get_client")
    def test_storage_failure_fails_closed_before_document_write(self, mock_get_client):
        client = self._failing_storage_client()
        mock_get_client.return_value = client

        with self.assertRaises(database.StorageUploadError) as raised:
            database.save_upload(42, "proposal.pdf", b"document bytes")

        self.assertEqual(
            str(raised.exception),
            "Document storage is temporarily unavailable. The upload was not saved; please try again.",
        )
        client.table.assert_not_called()

    @patch("database.get_client")
    def test_traversal_filenames_never_become_storage_object_paths(self, mock_get_client):
        for filename in ("../../outside.pdf", "..\\..\\outside.pdf", "/tmp/outside.pdf"):
            with self.subTest(filename=filename):
                client = self._failing_storage_client()
                mock_get_client.return_value = client

                with self.assertRaises(database.StorageUploadError):
                    database.save_upload(42, filename, b"document bytes")

                storage_path = client.storage.from_.return_value.upload.call_args.args[0]
                self.assertRegex(storage_path, r"^42/[0-9a-f]{32}\.pdf$")
                self.assertNotIn("..", storage_path)
                self.assertNotIn("\\", storage_path)
                self.assertNotIn("/tmp", storage_path)
                client.table.assert_not_called()

    def test_server_generated_object_name_uses_only_a_safe_extension(self):
        for filename, expected in (
            ("report.PDF", ".pdf"),
            ("../../report.xlsx", ".xlsx"),
            ("report.bad-extension!", ""),
            ("report." + "a" * 20, ""),
        ):
            with self.subTest(filename=filename):
                self.assertEqual(database._storage_upload_extension(filename), expected)

    def test_source_has_no_container_local_upload_fallback(self):
        source = open("database.py", encoding="utf-8").read()
        save_upload = source[source.index("def save_upload("):source.index("def download_file(")]
        self.assertNotIn('"uploads"', save_upload)
        self.assertNotIn("open(local_path", save_upload)
        self.assertNotIn("os.makedirs", save_upload)


if __name__ == "__main__":
    unittest.main()
