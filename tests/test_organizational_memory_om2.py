"""
tests/test_organizational_memory_om2.py

Organizational Memory OM-2: source ingestion + human approval lifecycle.
Covers organizational_memory.split_source_into_chunks(), tenancy.py's
ingest_organizational_source_document_for_organization() /
approve_organizational_memory_item_for_organization(), and the new
migration 016 DDL additions (organizational_source_documents,
approve_organizational_memory_item() RPC, source_document_id column).

No live provider/embedding call anywhere in this file. extractor.py's real
(pure, offline) text extraction IS exercised for plain-text bytes, matching
this repo's existing convention of using the real deterministic extraction
path with synthetic in-memory bytes rather than mocking it. All Supabase/
db-layer calls are mocked via unittest.mock.patch.object, exactly like
tests/test_organizational_memory.py.
"""
import re
from pathlib import Path
from unittest.mock import patch

import pytest

import organizational_memory as om
import tenancy


_MIGRATION_016 = (Path(__file__).resolve().parents[1] / "migrations"
                  / "016_organizational_memory.sql").read_text(encoding="utf-8")

ORG_A = "11111111-1111-1111-1111-111111111111"
ORG_B = "22222222-2222-2222-2222-222222222222"


# ── Deterministic chunking ────────────────────────────────────────────────

class TestSplitSourceIntoChunks:

    def test_empty_text_yields_no_chunks(self):
        assert om.split_source_into_chunks("") == []

    def test_every_character_accounted_for_exactly_once(self):
        text = ("Paragraph one has some content.\n\n"
                "Paragraph two has more content here.\n\n"
                "Paragraph three wraps it up.")
        chunks = om.split_source_into_chunks(text, target_chunk_chars=40)
        # Reconstruct from chunk char_start/char_end and compare to original.
        rebuilt = "".join(text[c["char_start"]:c["char_end"]] for c in chunks)
        assert rebuilt == text

    def test_deterministic_same_text_same_boundaries(self):
        text = "A" * 50 + "\n\n" + "B" * 5000 + "\n\n" + "C" * 50
        chunks1 = om.split_source_into_chunks(text, target_chunk_chars=1000)
        chunks2 = om.split_source_into_chunks(text, target_chunk_chars=1000)
        assert chunks1 == chunks2

    def test_small_text_single_chunk(self):
        text = "Short capability statement."
        chunks = om.split_source_into_chunks(text, target_chunk_chars=4000)
        assert len(chunks) == 1
        assert chunks[0]["char_start"] == 0
        assert chunks[0]["char_end"] == len(text)
        assert chunks[0]["text"] == text

    def test_oversized_single_paragraph_is_windowed(self):
        text = "X" * 10000  # one giant paragraph, no blank-line breaks
        chunks = om.split_source_into_chunks(text, target_chunk_chars=3000)
        assert len(chunks) == 4  # 3000,3000,3000,1000
        for c in chunks:
            assert len(c["text"]) <= 3000
        assert sum(len(c["text"]) for c in chunks) == 10000

    def test_bounded_chunks_never_exceed_target_by_much(self):
        paragraphs = [f"Paragraph {i} " + ("word " * 20) for i in range(30)]
        text = "\n\n".join(paragraphs)
        chunks = om.split_source_into_chunks(text, target_chunk_chars=500)
        for c in chunks:
            # A single oversized paragraph can exceed target on its own,
            # but with these short paragraphs no chunk should blow past it.
            assert len(c["text"]) <= 500 + 200


# ── Ingestion: determinism, provenance, org isolation ────────────────────

class TestIngestionDeterminism:

    def test_same_bytes_same_content_hash_and_chunks(self):
        file_bytes = b"Case study one.\n\nWe delivered results for a federal client.\n\nSecond paragraph of detail."

        created_docs = []
        created_items = []

        def fake_create_doc(doc):
            row = {"id": len(created_docs) + 1, **doc}
            created_docs.append(row)
            return row

        def fake_list_docs(organization_id):
            return [d for d in created_docs if d["organization_id"] == organization_id]

        def fake_create_item(payload):
            row = {"id": len(created_items) + 1, **payload}
            created_items.append(row)
            return row

        with patch.object(tenancy.db, "create_organizational_source_document", side_effect=fake_create_doc), \
             patch.object(tenancy.db, "list_organizational_source_documents", side_effect=fake_list_docs), \
             patch.object(tenancy.db, "create_organizational_memory_item", side_effect=fake_create_item), \
             patch.object(tenancy.db, "list_organizational_memory_items", return_value=[]):
            result1 = tenancy.ingest_organizational_source_document_for_organization(
                ORG_A, "case_study.txt", file_bytes, created_by_user_id="user-1")

        doc1 = result1["document"]
        items1 = result1["items"]
        assert doc1["content_hash"] == __import__("hashlib").sha256(file_bytes).hexdigest()
        assert len(items1) >= 1
        for item in items1:
            assert item["memory_class"] == "SOURCE_MEMORY"
            assert item["source_content_hash"] == doc1["content_hash"]
            assert item["source_filename"] == "case_study.txt"
            assert item["source_document_id"] == doc1["id"]
            assert re.match(r"^chars:\d+-\d+$", item["source_locator"])

    def test_reingesting_same_file_reuses_existing_document(self):
        file_bytes = b"Identical resume content for dedup test."
        existing_doc = {"id": 7, "organization_id": ORG_A, "filename": "resume.txt",
                         "content_hash": __import__("hashlib").sha256(file_bytes).hexdigest()}
        existing_item = {"id": 99, "organization_id": ORG_A, "memory_class": "SOURCE_MEMORY",
                          "source_document_id": 7, "title": "resume.txt chunk"}

        with patch.object(tenancy.db, "list_organizational_source_documents", return_value=[existing_doc]), \
             patch.object(tenancy.db, "list_organizational_memory_items", return_value=[existing_item]), \
             patch.object(tenancy.db, "create_organizational_source_document") as fake_create_doc, \
             patch.object(tenancy.db, "create_organizational_memory_item") as fake_create_item:
            result = tenancy.ingest_organizational_source_document_for_organization(
                ORG_A, "resume.txt", file_bytes, created_by_user_id="user-1")

        assert result["reused_existing"] is True
        assert result["document"] == existing_doc
        assert result["items"] == [existing_item]
        fake_create_doc.assert_not_called()
        fake_create_item.assert_not_called()

    def test_ingestion_requires_organization_id(self):
        with pytest.raises(ValueError):
            tenancy.ingest_organizational_source_document_for_organization("", "f.txt", b"data")

    def test_organization_isolation_across_ingested_documents(self):
        """A document listing scoped to ORG_A must never see an ORG_B
        document, even with identical bytes -- content_hash matching is
        performed only against documents already filtered to the caller's
        own organization."""
        file_bytes = b"Shared boilerplate paragraph text used by two orgs coincidentally."
        content_hash = __import__("hashlib").sha256(file_bytes).hexdigest()
        org_b_doc = {"id": 1, "organization_id": ORG_B, "filename": "f.txt", "content_hash": content_hash}

        def fake_list_docs(organization_id):
            # Simulate real DB behavior: list is already organization-scoped.
            return [org_b_doc] if organization_id == ORG_B else []

        created = []

        def fake_create_doc(doc):
            row = {"id": 42, **doc}
            created.append(row)
            return row

        def fake_create_item(payload):
            return {"id": 1, **payload}

        with patch.object(tenancy.db, "list_organizational_source_documents", side_effect=fake_list_docs), \
             patch.object(tenancy.db, "create_organizational_source_document", side_effect=fake_create_doc), \
             patch.object(tenancy.db, "create_organizational_memory_item", side_effect=fake_create_item), \
             patch.object(tenancy.db, "list_organizational_memory_items", return_value=[]):
            result = tenancy.ingest_organizational_source_document_for_organization(
                ORG_A, "f.txt", file_bytes, created_by_user_id="user-1")

        assert result["reused_existing"] is False
        assert created[0]["organization_id"] == ORG_A


# ── Approval authorization / lineage ─────────────────────────────────────

class TestApprovalAuthorizationAndLineage:

    def _source_row(self, **overrides):
        row = {
            "id": 5, "organization_id": ORG_A, "memory_class": "SOURCE_MEMORY",
            "title": "Federal coaching case study", "content": "We delivered coaching to 40 executives.",
            "source_file_id": "omsrc:abc", "source_content_hash": "a" * 64,
            "source_filename": "case.pdf", "source_package_path": None,
            "source_locator": "chars:0-100", "source_bid_id": None, "source_document_id": 3,
        }
        row.update(overrides)
        return row

    def test_approve_requires_organization_id(self):
        with pytest.raises(ValueError):
            tenancy.approve_organizational_memory_item_for_organization("", 5, "user-1")

    def test_approve_requires_source_item_id(self):
        with pytest.raises(ValueError):
            tenancy.approve_organizational_memory_item_for_organization(ORG_A, None, "user-1")

    def test_approve_requires_approved_by_user_id(self):
        with pytest.raises(ValueError):
            tenancy.approve_organizational_memory_item_for_organization(ORG_A, 5, "")

    def test_approve_rejects_missing_parent(self):
        with patch.object(tenancy.db, "get_organizational_memory_item", return_value=None):
            with pytest.raises(ValueError):
                tenancy.approve_organizational_memory_item_for_organization(ORG_A, 999, "user-1")

    def test_approve_rejects_parent_from_different_organization(self):
        parent = self._source_row(organization_id=ORG_B)
        with patch.object(tenancy.db, "get_organizational_memory_item", return_value=parent), \
             patch.object(tenancy.db, "approve_organizational_memory_item") as fake_rpc:
            with pytest.raises(ValueError):
                tenancy.approve_organizational_memory_item_for_organization(ORG_A, 5, "user-1")
            fake_rpc.assert_not_called()

    def test_approve_rejects_non_source_memory_parent(self):
        parent = self._source_row(memory_class="PROPOSAL_MEMORY")
        with patch.object(tenancy.db, "get_organizational_memory_item", return_value=parent), \
             patch.object(tenancy.db, "approve_organizational_memory_item") as fake_rpc:
            with pytest.raises(ValueError):
                tenancy.approve_organizational_memory_item_for_organization(ORG_A, 5, "user-1")
            fake_rpc.assert_not_called()

    def test_approve_rejects_already_approved_parent(self):
        parent = self._source_row(memory_class="APPROVED_FIRM_KNOWLEDGE")
        with patch.object(tenancy.db, "get_organizational_memory_item", return_value=parent), \
             patch.object(tenancy.db, "approve_organizational_memory_item") as fake_rpc:
            with pytest.raises(ValueError):
                tenancy.approve_organizational_memory_item_for_organization(ORG_A, 5, "user-1")
            fake_rpc.assert_not_called()

    def test_approve_success_calls_rpc_with_server_derived_fields_only(self):
        parent = self._source_row()

        def fake_rpc(source_item_id, organization_id, approved_by_user_id, fact_title, fact_content):
            assert source_item_id == 5
            assert organization_id == ORG_A
            assert approved_by_user_id == "user-1"
            return {
                "id": 55, "organization_id": ORG_A, "memory_class": "APPROVED_FIRM_KNOWLEDGE",
                "title": fact_title, "content": fact_content,
                "source_file_id": parent["source_file_id"],
                "source_content_hash": parent["source_content_hash"],
                "source_filename": parent["source_filename"],
                "source_document_id": parent["source_document_id"],
                "approved_by_user_id": approved_by_user_id, "approved_at": "2026-01-01T00:00:00+00:00",
                "derived_from_item_id": 5,
            }

        with patch.object(tenancy.db, "get_organizational_memory_item", return_value=parent), \
             patch.object(tenancy.db, "approve_organizational_memory_item", side_effect=fake_rpc):
            approved = tenancy.approve_organizational_memory_item_for_organization(
                ORG_A, 5, "user-1", fact_title="Tightened title", fact_content="Tightened fact text.")

        assert approved["memory_class"] == "APPROVED_FIRM_KNOWLEDGE"
        assert approved["derived_from_item_id"] == 5
        assert approved["source_content_hash"] == parent["source_content_hash"]
        assert approved["source_filename"] == parent["source_filename"]
        assert approved["source_document_id"] == parent["source_document_id"]
        assert approved["approved_by_user_id"] == "user-1"
        # Caller never supplied approved_at -- the fake RPC (standing in for
        # the DB's own now()) is the only source of that value.
        assert approved["approved_at"] == "2026-01-01T00:00:00+00:00"

    def test_approve_never_mutates_parent_row(self):
        """The parent dict fetched from the (mocked) DB layer must be left
        untouched by the approval call -- approval creates a new row, it
        does not edit the one it read."""
        parent = self._source_row()
        parent_snapshot = dict(parent)

        with patch.object(tenancy.db, "get_organizational_memory_item", return_value=parent), \
             patch.object(tenancy.db, "approve_organizational_memory_item",
                           return_value={"id": 55, "memory_class": "APPROVED_FIRM_KNOWLEDGE",
                                         "derived_from_item_id": 5}):
            tenancy.approve_organizational_memory_item_for_organization(ORG_A, 5, "user-1")

        assert parent == parent_snapshot


# ── Retrieval after approval ──────────────────────────────────────────────

class TestRetrievalAfterApproval:

    def test_approved_item_retrievable_and_labeled_trusted(self):
        rows = [
            {"id": 55, "organization_id": ORG_A, "memory_class": "APPROVED_FIRM_KNOWLEDGE",
             "title": "ICF accreditation", "content": "Our firm holds ICF ACTP accreditation.",
             "approved_by_user_id": "user-1", "approved_at": "2026-01-01T00:00:00+00:00",
             "source_file_id": "omsrc:abc", "source_content_hash": "a" * 64,
             "derived_from_item_id": 5},
        ]
        with patch.object(tenancy.db, "list_organizational_memory_items", return_value=rows):
            results = tenancy.retrieve_organizational_memory_for_organization(
                ORG_A, "ICF accreditation", trusted_only=True)
        assert len(results) == 1
        assert results[0]["memory_class"] == "APPROVED_FIRM_KNOWLEDGE"
        assert results[0]["is_trusted_fact"] is True
        assert results[0]["provenance"]["content_hash"] == "a" * 64


# ── Generic-path regression guard (still rejects APPROVED_FIRM_KNOWLEDGE) ─

class TestGenericPathStillRejectsApprovedFirmKnowledgeAfterOM2:

    def test_generic_create_path_still_rejects_approved_firm_knowledge(self):
        with patch.object(tenancy.db, "create_organizational_memory_item") as fake_create:
            with pytest.raises(ValueError):
                tenancy.create_organizational_memory_item_for_organization(
                    ORG_A,
                    {"memory_class": "APPROVED_FIRM_KNOWLEDGE", "title": "t", "content": "c"},
                    created_by_user_id="user-1",
                )
            fake_create.assert_not_called()


# ── Embedding-failure fallback (reuses OM-1's proven pattern) ────────────

class TestEmbeddingFailureFallbackAfterIngestionAndApproval:

    def test_retrieve_degrades_to_keyword_when_embed_fn_raises(self):
        rows = [
            {"id": 1, "organization_id": ORG_A, "memory_class": "SOURCE_MEMORY",
             "title": "Case study", "content": "We delivered leadership coaching for a federal client.",
             "source_file_id": "omsrc:xyz"},
        ]

        def failing_embed(_query):
            raise RuntimeError("simulated Voyage outage -- never a live call in this test")

        with patch.object(tenancy.db, "list_organizational_memory_items", return_value=rows):
            results = tenancy.retrieve_organizational_memory_for_organization(
                ORG_A, "leadership coaching federal", embed_fn=failing_embed)
        assert len(results) == 1
        assert results[0]["relevance_signal"] == "KEYWORD"


# ── Migration DDL-intent assertions (OM-2 additions) ──────────────────────

class TestMigrationDDLIntentOM2:

    def test_source_documents_table_present(self):
        assert "create table if not exists organizational_source_documents" in _MIGRATION_016

    def test_source_documents_has_org_content_hash_unique_constraint(self):
        assert re.search(
            r"unique \(organization_id, content_hash\)", _MIGRATION_016)

    def test_source_documents_has_rls_select_policy(self):
        assert "organizational_source_documents_select_org_member" in _MIGRATION_016
        assert re.search(
            r"create policy organizational_source_documents_select_org_member\s*"
            r"on public\.organizational_source_documents for select to authenticated",
            _MIGRATION_016)

    def test_memory_items_has_source_document_id_column_and_composite_fk(self):
        assert "add column if not exists source_document_id bigint" in _MIGRATION_016
        assert "organizational_memory_items_source_document_org_fk" in _MIGRATION_016
        assert re.search(
            r"foreign key \(source_document_id, organization_id\)\s*"
            r"references organizational_source_documents \(id, organization_id\)",
            _MIGRATION_016)

    def test_immutable_provenance_trigger_covers_source_document_id(self):
        assert "new.source_document_id is distinct from old.source_document_id" in _MIGRATION_016

    def test_create_organizational_source_document_rpc_is_service_role_only(self):
        assert "create_organizational_source_document" in _MIGRATION_016
        assert "grant execute on function public.create_organizational_source_document(jsonb) to service_role;" in _MIGRATION_016
        assert "revoke all on function public.create_organizational_source_document(jsonb) from anon, authenticated;" in _MIGRATION_016

    def test_approve_organizational_memory_item_rpc_present_and_locked_down(self):
        assert "create or replace function public.approve_organizational_memory_item(" in _MIGRATION_016
        assert re.search(
            r"grant execute on function public\.approve_organizational_memory_item\([^)]*\) to service_role;",
            _MIGRATION_016)
        assert re.search(
            r"revoke all on function public\.approve_organizational_memory_item\([^)]*\) from anon, authenticated;",
            _MIGRATION_016)

    def test_approve_rpc_verifies_source_memory_class_server_side(self):
        assert re.search(
            r"if v_parent\.memory_class <> 'SOURCE_MEMORY' then", _MIGRATION_016)

    def test_approve_rpc_sets_approved_at_via_now_never_from_input(self):
        # The RPC signature takes no p_approved_at parameter at all, and the
        # insert uses now() literally.
        assert "p_approved_at" not in _MIGRATION_016
        assert re.search(
            r"p_approved_by_user_id, now\(\), v_parent\.id,", _MIGRATION_016)

    def test_approve_rpc_copies_provenance_from_parent_row(self):
        assert re.search(
            r"v_parent\.source_file_id, v_parent\.source_content_hash, v_parent\.source_filename,\s*"
            r"v_parent\.source_package_path, v_parent\.source_locator, v_parent\.source_bid_id, v_parent\.source_document_id,",
            _MIGRATION_016)

    def test_generic_create_rpc_still_rejects_approved_firm_knowledge(self):
        # Regression guard: the OM-1 RPC-level rejection must still be
        # present verbatim after the OM-2 edits.
        assert "APPROVED_FIRM_KNOWLEDGE creation is reserved for the explicit human-approval flow" in _MIGRATION_016
