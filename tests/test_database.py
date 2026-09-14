"""
tests/test_database.py

Deterministic tests for database.py's update_bid() partial-update fix
(post-commissioning data-integrity fix). No live Supabase connection --
database.get_client() is mocked, same pattern as
tests/test_submit_state_consistency.py's test_L_document_mandatory_resolution_persistence.

Root cause being regression-tested: update_bid() used to build its update
payload from every whitelisted column via dict.get(), so any column the
caller didn't include in `data` was written as NULL instead of being left
alone. Every real call site in the app already worked around this by
spreading the full existing bid row (`{**bid, "stage": x}`) before calling
update_bid(), but a caller that (like a one-off diagnostic script during
Phase 3 commissioning) passed only the field it meant to change would
silently null out every other column.
"""
import unittest
from unittest.mock import MagicMock, patch

import database


class TestUpdateBidPartialUpdate(unittest.TestCase):

    @patch("database.get_client")
    def test_one_field_partial_update_writes_only_that_field(self, mock_get_client):
        """A single-field update must not touch any other column."""
        mock_sb = MagicMock()
        mock_get_client.return_value = mock_sb

        database.update_bid(8, {"stage": "Identified"})

        mock_sb.table("bids").update.assert_called_once_with({"stage": "Identified"})

    @patch("database.get_client")
    def test_multi_field_partial_update_preserves_unspecified_fields(self, mock_get_client):
        """Several fields at once, but not all nine -- only those given may
        appear in the write."""
        mock_sb = MagicMock()
        mock_get_client.return_value = mock_sb

        database.update_bid(8, {
            "submission_deadline": "2026-09-30",
            "clarification_deadline": "2026-09-10",
        })

        called_with = mock_sb.table("bids").update.call_args[0][0]
        self.assertEqual(called_with, {
            "submission_deadline": "2026-09-30",
            "clarification_deadline": "2026-09-10",
        })
        for untouched in ("title", "client", "file_number", "stage", "sensitivity",
                         "owner", "value_cad", "notes"):
            self.assertNotIn(untouched, called_with)

    @patch("database.get_client")
    def test_explicit_none_clears_a_field_when_the_key_is_present(self, mock_get_client):
        """Established app semantics (the Edit Bid form in app.py) rely on
        passing a whitelisted key with value None to intentionally clear
        it -- e.g. 'value_cad': val or None when the user empties the
        field. A key that IS present must be written even if its value is
        None; this must remain possible after the fix."""
        mock_sb = MagicMock()
        mock_get_client.return_value = mock_sb

        database.update_bid(8, {"value_cad": None, "stage": "Qualifying"})

        called_with = mock_sb.table("bids").update.call_args[0][0]
        self.assertEqual(called_with, {"value_cad": None, "stage": "Qualifying"})
        self.assertIn("value_cad", called_with)
        self.assertIsNone(called_with["value_cad"])

    @patch("database.get_client")
    def test_unknown_fields_are_ignored(self, mock_get_client):
        """Non-whitelisted keys (e.g. 'id', 'created_at', or a typo) must
        never reach the update payload."""
        mock_sb = MagicMock()
        mock_get_client.return_value = mock_sb

        database.update_bid(8, {
            "id": 8, "created_at": "2026-01-01T00:00:00Z", "updated_at": "x",
            "not_a_real_column": "whatever",
            "stage": "In Progress",
        })

        called_with = mock_sb.table("bids").update.call_args[0][0]
        self.assertEqual(called_with, {"stage": "In Progress"})

    @patch("database.get_client")
    def test_full_field_update_still_works_unchanged(self, mock_get_client):
        """The existing '{**bid, "stage": x}' pattern every real call site
        (app.py, stage_submit.py, stage_decide.py, stage_debrief.py) uses --
        spreading the full current row plus an override -- must still write
        every one of those fields exactly as given, matching the pre-fix
        full-update behavior for this already-safe calling convention."""
        mock_sb = MagicMock()
        mock_get_client.return_value = mock_sb

        full_bid_like_dict = {
            "id": 8, "title": "RFP 2026-026", "client": "Bank of Canada",
            "file_number": "RFP 2026-026",
            "stage": "Submitted",  # the override, matching {**bid, "stage": "Submitted"}
            "sensitivity": "Standard", "owner": None, "value_cad": None,
            "submission_deadline": "2026-09-30", "clarification_deadline": "2026-09-10",
            "notes": "some notes", "created_at": "x", "updated_at": "y",
        }
        database.update_bid(8, full_bid_like_dict)

        called_with = mock_sb.table("bids").update.call_args[0][0]
        self.assertEqual(called_with, {
            "title": "RFP 2026-026", "client": "Bank of Canada",
            "file_number": "RFP 2026-026", "stage": "Submitted",
            "sensitivity": "Standard", "owner": None, "value_cad": None,
            "submission_deadline": "2026-09-30", "clarification_deadline": "2026-09-10",
            "notes": "some notes",
        })

    @patch("database.get_client")
    def test_empty_data_is_a_no_op_and_never_calls_the_client(self, mock_get_client):
        mock_sb = MagicMock()
        mock_get_client.return_value = mock_sb

        database.update_bid(8, {})

        mock_sb.table.assert_not_called()

    @patch("database.get_client")
    def test_targets_the_correct_bid_id(self, mock_get_client):
        mock_sb = MagicMock()
        mock_get_client.return_value = mock_sb

        database.update_bid(42, {"stage": "Won"})

        mock_sb.table("bids").update({"stage": "Won"}).eq.assert_called_with("id", 42)


class TestCreateBidUnchanged(unittest.TestCase):
    """Regression guard: this fix must not silently change create_bid()'s
    behavior (instruction: 'do not silently change create behavior')."""

    @patch("database.get_client")
    def test_create_bid_still_defaults_missing_fields_to_none(self, mock_get_client):
        mock_sb = MagicMock()
        mock_get_client.return_value = mock_sb
        mock_sb.table("bids").insert({}).execute.return_value = MagicMock(data=[{"id": 99}])

        database.create_bid({"title": "New Bid", "client": "Some Buyer"})

        called_with = mock_sb.table("bids").insert.call_args[0][0]
        self.assertEqual(called_with, {
            "title": "New Bid", "client": "Some Buyer", "file_number": None,
            "stage": None, "sensitivity": None, "owner": None, "value_cad": None,
            "submission_deadline": None, "clarification_deadline": None, "notes": None,
        })


if __name__ == "__main__":
    unittest.main()
