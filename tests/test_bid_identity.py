"""Phoenix Beta upload-only New Bid Ingestion: bid identity (title /
issuing organization) filled from a completed FAST run, grounded in the
uploaded text, never invented, never overwriting a user-entered value."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import bid_identity as bi

CORPUS = ["REQUEST FOR PROPOSALS RFP 2026-014\nThe City of Calgary invites proposals for\n"
          "Leadership   Development and Coaching Services.\nClosing: 2026-12-01"]


def test_grounded_title_and_client_are_used():
    out = bi.grounded_identity({"title": "Leadership Development and Coaching Services",
                                "client": "The City of Calgary"}, CORPUS)
    assert out == {"title": "Leadership Development and Coaching Services", "client": "The City of Calgary"}


def test_client_not_in_text_is_rejected_never_invented():
    out = bi.grounded_identity({"title": "Leadership Development and Coaching Services",
                                "client": "Government of Alberta"}, CORPUS)
    assert out["client"] is None and out["title"]


def test_title_mostly_absent_from_text_is_uncertain():
    out = bi.grounded_identity({"title": "Enterprise Cloud Migration Program", "client": None}, CORPUS)
    assert out == {"title": None, "client": None}


def test_missing_or_placeholder_values_yield_none():
    assert bi.grounded_identity({}, CORPUS) == {"title": None, "client": None}
    assert bi.grounded_identity({"title": bi.PLACEHOLDER_TITLE, "client": bi.PLACEHOLDER_CLIENT},
                                CORPUS + [bi.PLACEHOLDER_TITLE, bi.PLACEHOLDER_CLIENT]) == {"title": None, "client": None}
    assert bi.grounded_identity({"title": "  ", "client": 42}, CORPUS) == {"title": None, "client": None}


def test_resolve_uses_existing_fast_identity_merge_no_model_call():
    result = SimpleNamespace(doc_metadata_by_doc={
        "RFP.pdf": {"title": "Leadership Development and Coaching Services", "client": "The City of Calgary"}})
    with patch("config.get_anthropic_client", side_effect=AssertionError("no model call")):
        out = bi.resolve_from_fast_result(result, CORPUS)
    assert out["client"] == "The City of Calgary"
    assert out["title"] == "Leadership Development and Coaching Services"


def test_db_fill_only_replaces_placeholder_values():
    import database
    sb = MagicMock()
    with patch.object(database, "get_client", return_value=sb):
        database.fill_placeholder_bid_identity(7, "T", None, bi.PLACEHOLDER_TITLE, bi.PLACEHOLDER_CLIENT)
    sb.table.return_value.update.assert_called_once_with({"title": "T"})
    upd = sb.table.return_value.update.return_value
    upd.eq.assert_called_once_with("id", 7)
    upd.eq.return_value.eq.assert_called_once_with("title", bi.PLACEHOLDER_TITLE)
