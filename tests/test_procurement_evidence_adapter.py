from dataclasses import FrozenInstanceError
from hashlib import sha256

import pytest

from evidence import EvidenceObjectClass, LocatorKind
from procurement_evidence_adapter import (
    ProcurementEvidenceAdapterError,
    adapt_procurement_corpus,
)


def _inputs():
    payload = b"pdf"
    digest = sha256(payload).hexdigest()
    files = [("folder/rfp.pdf", payload)]
    metadata = {
        "files": ["folder/rfp.pdf"],
        "doc_metadata": {"folder/rfp.pdf": {"type": "pdf"}},
        "doc_texts": {"folder/rfp.pdf": (
            "[[SOURCE: folder/rfp.pdf | PAGE: 1]]\nFirst page\n"
            "[[SOURCE: folder/rfp.pdf | PAGE: 2]]\nSecond page")},
    }
    corpus = {
        "corpus_id": "corpus-1", "language": "English",
        "files": [{"path": "folder/rfp.pdf", "bytes": 3,
                   "sha256": digest, "role": "MASTER_RFP"}],
    }
    aggregate = sha256(digest.encode("ascii")).hexdigest()
    acquisition = {"retrieved_on": "2030-01-02", "procurement_package": {
        "aggregate_sha256": aggregate}}
    source = {"source_id": "source:buyer", "publisher_name": "Buyer",
              "base_url": "https://buyer.example/"}
    return files, metadata, corpus, acquisition, source


def test_translation_is_deterministic_immutable_and_preserves_fragments():
    first = adapt_procurement_corpus(*_inputs())
    second = adapt_procurement_corpus(*_inputs())
    assert first == second
    assert first.to_json() == second.to_json()
    assert first.snapshot_id == second.snapshot_id
    classes = [item.object_class for item in first.objects]
    assert classes.count(EvidenceObjectClass.SOURCE) == 1
    assert classes.count(EvidenceObjectClass.ARTIFACT) == 1
    assert classes.count(EvidenceObjectClass.OCCURRENCE) == 2
    assert classes.count(EvidenceObjectClass.EXTRACT) == 2
    extracts = [item for item in first.objects if item.object_class is EvidenceObjectClass.EXTRACT]
    assert sorted((item.locator_kind.value, item.locator, item.content) for item in extracts) == [
        (LocatorKind.PAGE.value, "page:1", "First page"),
        (LocatorKind.PAGE.value, "page:2", "Second page"),
    ]
    with pytest.raises(FrozenInstanceError):
        first.snapshot_id = "changed"


def test_section_table_and_sheet_hierarchy_is_preserved_without_interpretation():
    files, metadata, corpus, acquisition, source = _inputs()
    metadata["doc_texts"]["folder/rfp.pdf"] = (
        "[[SOURCE: folder/rfp.pdf | SECTION: Scope]]\nBody\n"
        "[[SOURCE: folder/rfp.pdf | TABLE]] Row\n"
        "[[SOURCE: folder/rfp.pdf | SHEET: Rates | ROWS: 2-4]]\nCells")
    snapshot = adapt_procurement_corpus(files, metadata, corpus, acquisition, source)
    extracts = [item for item in snapshot.objects if item.object_class is EvidenceObjectClass.EXTRACT]
    assert {(item.locator_kind, item.locator) for item in extracts} == {
        (LocatorKind.SECTION, "section:Scope"),
        (LocatorKind.OTHER_EXACT, "exact:TABLE"),
        (LocatorKind.RECORD, "record:sheet=Rates;rows=2-4"),
    }


def test_attributable_empty_marker_is_an_occurrence_but_not_an_extract():
    files, metadata, corpus, acquisition, source = _inputs()
    metadata["doc_texts"]["folder/rfp.pdf"] = (
        "[[SOURCE: folder/rfp.pdf | SECTION: Header]]\n"
        "[[SOURCE: folder/rfp.pdf | SECTION: Body]]\nText")
    snapshot = adapt_procurement_corpus(files, metadata, corpus, acquisition, source)
    classes = [item.object_class for item in snapshot.objects]
    assert classes.count(EvidenceObjectClass.OCCURRENCE) == 2
    assert classes.count(EvidenceObjectClass.EXTRACT) == 1


@pytest.mark.parametrize("mutation", ["missing-date", "bad-hash", "missing-marker", "path-mismatch"])
def test_adapter_fails_closed_without_repair_or_fallback(mutation):
    files, metadata, corpus, acquisition, source = _inputs()
    if mutation == "missing-date":
        acquisition.pop("retrieved_on")
    elif mutation == "bad-hash":
        corpus["files"][0]["sha256"] = "0" * 64
    elif mutation == "missing-marker":
        metadata["doc_texts"]["folder/rfp.pdf"] = "unattributed"
    else:
        metadata["doc_texts"]["folder/rfp.pdf"] = "[[SOURCE: other.pdf | PAGE: 1]]\nText"
    with pytest.raises(ProcurementEvidenceAdapterError):
        adapt_procurement_corpus(files, metadata, corpus, acquisition, source)


def test_duplicate_paths_and_unsupported_roles_fail_closed():
    files, metadata, corpus, acquisition, source = _inputs()
    with pytest.raises(ProcurementEvidenceAdapterError):
        adapt_procurement_corpus(files + files, metadata, corpus, acquisition, source)
    corpus["files"][0]["role"] = "INFER_THIS"
    with pytest.raises(ProcurementEvidenceAdapterError):
        adapt_procurement_corpus(files, metadata, corpus, acquisition, source)
