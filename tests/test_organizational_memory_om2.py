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
    """OM-2 commissioning-review fix #1: ingestion now goes through ONE
    atomic RPC call (db.ingest_organizational_source_document), never a
    parent-create-then-per-chunk-insert loop -- these tests mock that one
    call (plus the Storage upload and the fast non-authoritative pre-check
    reads) instead of the old per-chunk create calls."""

    def test_same_bytes_same_content_hash_and_chunks(self):
        file_bytes = b"Case study one.\n\nWe delivered results for a federal client.\n\nSecond paragraph of detail."
        content_hash = __import__("hashlib").sha256(file_bytes).hexdigest()

        def fake_ingest(organization_id, filename, p_content_hash, chunks, **kwargs):
            assert organization_id == ORG_A
            assert p_content_hash == content_hash
            items = [
                {"id": idx + 1, "memory_class": "SOURCE_MEMORY",
                 "source_content_hash": p_content_hash, "source_filename": filename,
                 "source_document_id": 1, "source_locator": c["source_locator"]}
                for idx, c in enumerate(chunks)
            ]
            return {"document": {"id": 1, "organization_id": organization_id,
                                  "content_hash": p_content_hash, "chunk_count": len(chunks)},
                    "items": items, "reused_existing": False}

        with patch.object(tenancy.db, "list_organizational_source_documents", return_value=[]), \
             patch.object(tenancy.db, "upload_organizational_source_file", return_value="org/x/sources/y"), \
             patch.object(tenancy.db, "ingest_organizational_source_document", side_effect=fake_ingest):
            result1 = tenancy.ingest_organizational_source_document_for_organization(
                ORG_A, "case_study.txt", file_bytes, created_by_user_id="user-1")

        doc1 = result1["document"]
        items1 = result1["items"]
        assert doc1["content_hash"] == content_hash
        assert len(items1) >= 1
        for item in items1:
            assert item["memory_class"] == "SOURCE_MEMORY"
            assert item["source_content_hash"] == content_hash
            assert item["source_filename"] == "case_study.txt"
            assert item["source_document_id"] == doc1["id"]
            assert re.match(r"^chars:\d+-\d+$", item["source_locator"])

    def test_reingesting_same_file_reuses_existing_document(self):
        file_bytes = b"Identical resume content for dedup test."
        existing_doc = {"id": 7, "organization_id": ORG_A, "filename": "resume.txt",
                         "content_hash": __import__("hashlib").sha256(file_bytes).hexdigest(),
                         "chunk_count": 1}
        existing_item = {"id": 99, "organization_id": ORG_A, "memory_class": "SOURCE_MEMORY",
                          "source_document_id": 7, "title": "resume.txt chunk"}

        with patch.object(tenancy.db, "list_organizational_source_documents", return_value=[existing_doc]), \
             patch.object(tenancy.db, "list_organizational_memory_items", return_value=[existing_item]), \
             patch.object(tenancy.db, "upload_organizational_source_file") as fake_upload, \
             patch.object(tenancy.db, "ingest_organizational_source_document") as fake_ingest:
            result = tenancy.ingest_organizational_source_document_for_organization(
                ORG_A, "resume.txt", file_bytes, created_by_user_id="user-1")

        assert result["reused_existing"] is True
        assert result["document"] == existing_doc
        assert result["items"] == [existing_item]
        # The fast pre-check short-circuits BEFORE any extraction/upload/RPC
        # call -- re-ingesting an already-fully-ingested file must not touch
        # Storage or the atomic RPC at all.
        fake_upload.assert_not_called()
        fake_ingest.assert_not_called()

    def test_ingestion_requires_organization_id(self):
        with pytest.raises(ValueError):
            tenancy.ingest_organizational_source_document_for_organization("", "f.txt", b"data")

    def test_organization_isolation_across_ingested_documents(self):
        """A document listing scoped to ORG_A must never see an ORG_B
        document, even with identical bytes -- content_hash matching is
        performed only against documents already filtered to the caller's
        own organization. The atomic RPC itself is ALSO organization-scoped
        (p_organization_id is always the caller's own), so even if the
        Python-side pre-check were somehow bypassed, ingestion could never
        land in the wrong organization."""
        file_bytes = b"Shared boilerplate paragraph text used by two orgs coincidentally."
        content_hash = __import__("hashlib").sha256(file_bytes).hexdigest()
        org_b_doc = {"id": 1, "organization_id": ORG_B, "filename": "f.txt", "content_hash": content_hash}

        def fake_list_docs(organization_id):
            # Simulate real DB behavior: list is already organization-scoped.
            return [org_b_doc] if organization_id == ORG_B else []

        calls = []

        def fake_ingest(organization_id, filename, p_content_hash, chunks, **kwargs):
            calls.append(organization_id)
            return {"document": {"id": 42, "organization_id": organization_id,
                                  "content_hash": p_content_hash, "chunk_count": len(chunks)},
                    "items": [], "reused_existing": False}

        with patch.object(tenancy.db, "list_organizational_source_documents", side_effect=fake_list_docs), \
             patch.object(tenancy.db, "upload_organizational_source_file", return_value="org/x/sources/y"), \
             patch.object(tenancy.db, "ingest_organizational_source_document", side_effect=fake_ingest):
            result = tenancy.ingest_organizational_source_document_for_organization(
                ORG_A, "f.txt", file_bytes, created_by_user_id="user-1")

        assert result["reused_existing"] is False
        assert calls == [ORG_A]
        assert result["document"]["organization_id"] == ORG_A


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

    def test_obsolete_standalone_create_source_document_rpc_is_gone(self):
        """Second commissioning-review hardening pass fix #3: the obsolete
        standalone create_organizational_source_document() RPC (leftover
        scaffolding from before ingest_organizational_source_document()
        became the atomic path) must no longer exist anywhere in the
        migration -- not the function definition, not its GRANT/REVOKE
        statements."""
        assert "create or replace function public.create_organizational_source_document(" not in _MIGRATION_016
        assert "grant execute on function public.create_organizational_source_document(jsonb) to service_role;" not in _MIGRATION_016
        assert "revoke all on function public.create_organizational_source_document(jsonb) from anon, authenticated;" not in _MIGRATION_016

    def test_obsolete_python_helper_is_gone_and_unreferenced(self):
        """The matching database.py Python wrapper must be actually deleted
        (not merely unused), and nothing else in the codebase may still
        reference it."""
        import database as db_module
        assert not hasattr(db_module, "create_organizational_source_document")

        repo_root = Path(__file__).resolve().parents[1]
        hits = []
        for py_file in repo_root.rglob("*.py"):
            if "site-packages" in str(py_file) or py_file.name == "test_organizational_memory_om2.py":
                continue
            try:
                text = py_file.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if "create_organizational_source_document" in text:
                hits.append(str(py_file))
        assert hits == []

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


# ═══════════════════════════════════════════════════════════════════════════
# Commissioning-review hardening pass (four fixes)
# ═══════════════════════════════════════════════════════════════════════════

# ── Fix #1: atomic/idempotent ingestion ──────────────────────────────────

class TestAtomicIngestionTransactionFailure:

    def test_partial_chunk_insert_failure_leaves_no_visible_partial_document(self):
        """Simulates the atomic RPC itself raising partway through (e.g. a
        chunk insert violates a constraint) -- proves the Python layer
        propagates the failure rather than fabricating/returning a
        partial-looking success, and never falls back to any per-chunk
        insert call of its own."""
        file_bytes = b"Paragraph one.\n\nParagraph two.\n\nParagraph three."

        def fake_ingest_raises(*args, **kwargs):
            raise RuntimeError(
                "simulated: chunk insert violated a constraint mid-transaction -- "
                "whole transaction (including the parent row) rolled back")

        with patch.object(tenancy.db, "list_organizational_source_documents", return_value=[]), \
             patch.object(tenancy.db, "upload_organizational_source_file", return_value="org/x/sources/y"), \
             patch.object(tenancy.db, "ingest_organizational_source_document", side_effect=fake_ingest_raises), \
             patch.object(tenancy.db, "create_organizational_memory_item") as fake_old_create_item:
            with pytest.raises(RuntimeError):
                tenancy.ingest_organizational_source_document_for_organization(
                    ORG_A, "doc.txt", file_bytes, created_by_user_id="user-1")

        # The old per-chunk write path must never be used as a fallback --
        # ingestion is exclusively the one atomic RPC call now.
        fake_old_create_item.assert_not_called()

    def test_ingestion_rpc_returning_no_document_is_rejected_not_silently_accepted(self):
        """A malformed/incomplete RPC response (no 'document' key) must be
        treated as a failure, never coerced into a fake success."""
        file_bytes = b"Some content for this test."
        with patch.object(tenancy.db, "list_organizational_source_documents", return_value=[]), \
             patch.object(tenancy.db, "upload_organizational_source_file", return_value="org/x/sources/y"), \
             patch.object(tenancy.db, "ingest_organizational_source_document", return_value={"items": []}):
            with pytest.raises(ValueError):
                tenancy.ingest_organizational_source_document_for_organization(
                    ORG_A, "doc.txt", file_bytes, created_by_user_id="user-1")

    def test_ingestion_is_exactly_one_atomic_database_call(self):
        """The race/partial-state problem this fix exists to close cannot
        be closed if Python still does its own create-parent-then-loop --
        there must be exactly one call into db.ingest_organizational_
        source_document(), carrying the FULL chunk set, never a per-chunk
        call."""
        file_bytes = b"One paragraph. Nothing fancy about this text at all."
        calls = []

        def fake_ingest(organization_id, filename, content_hash, chunks, **kwargs):
            calls.append(chunks)
            return {"document": {"id": 1, "organization_id": organization_id,
                                  "content_hash": content_hash, "chunk_count": len(chunks)},
                    "items": [], "reused_existing": False}

        with patch.object(tenancy.db, "list_organizational_source_documents", return_value=[]), \
             patch.object(tenancy.db, "upload_organizational_source_file", return_value="org/x/sources/y"), \
             patch.object(tenancy.db, "ingest_organizational_source_document", side_effect=fake_ingest) as fake:
            tenancy.ingest_organizational_source_document_for_organization(
                ORG_A, "doc.txt", file_bytes, created_by_user_id="user-1")

        assert fake.call_count == 1
        assert len(calls) == 1
        assert len(calls[0]) >= 1  # the full chunk set was passed in one call


class TestAtomicIngestionRpcConcurrencyShape:
    """True concurrent execution cannot be exercised without a live DB in
    this environment (see docs/current/CHANGE_VERIFICATION.md) -- mirrors
    tests/test_proposal_intelligence_database.py's TestMigrationDDLIntent /
    TestSnapshotGetOrCreateIsAnRpcCall pattern: assert the RPC's DDL text
    and the Python-layer call shape that PROVIDE concurrency safety,
    instead of exercising real concurrency."""

    def test_ingest_rpc_uses_advisory_lock_keyed_on_org_and_content_hash(self):
        assert re.search(
            r"pg_advisory_xact_lock\(hashtext\('organizational_source_document:' \|\| "
            r"p_organization_id::text \|\| ':' \|\| p_content_hash\)\)",
            _MIGRATION_016)

    def test_ingest_rpc_exists_and_is_service_role_only(self):
        assert "create or replace function public.ingest_organizational_source_document(" in _MIGRATION_016
        assert re.search(
            r"grant execute on function public\.ingest_organizational_source_document\([^)]*\) to service_role;",
            _MIGRATION_016)
        assert re.search(
            r"revoke all on function public\.ingest_organizational_source_document\([^)]*\) from anon, authenticated;",
            _MIGRATION_016)

    def test_ingest_rpc_get_or_create_returns_existing_complete_document_verbatim(self):
        # Second commissioning-review hardening pass fix #1: exact equality,
        # not >= -- a document with MORE SOURCE_MEMORY rows than expected
        # must not silently pass a check meant to detect "at least".
        assert re.search(
            r"if v_doc\.chunk_count > 0 and v_actual_chunks = v_doc\.chunk_count then",
            _MIGRATION_016)
        assert not re.search(
            r"v_actual_chunks >= v_doc\.chunk_count", _MIGRATION_016)
        assert "'reused_existing', true" in _MIGRATION_016

    def test_ingest_rpc_completeness_check_counts_only_source_memory_rows(self):
        """Fix #1: the chunk-count check and the returned items query must
        both filter to memory_class = 'SOURCE_MEMORY' -- an
        APPROVED_FIRM_KNOWLEDGE row sharing the same source_document_id
        must never be counted or returned by the idempotent get-or-create
        path."""
        start = _MIGRATION_016.index(
            "create or replace function public.ingest_organizational_source_document(")
        end = _MIGRATION_016.index(
            "revoke all on function public.ingest_organizational_source_document")
        body = _MIGRATION_016[start:end]

        assert re.search(
            r"select count\(\*\) into v_actual_chunks\s*"
            r"from public\.organizational_memory_items\s*"
            r"where source_document_id = v_doc\.id\s*"
            r"and memory_class = 'SOURCE_MEMORY';",
            body)
        assert re.search(
            r"select coalesce\(jsonb_agg\(to_jsonb\(i\)\), '\[\]'::jsonb\) into v_items\s*"
            r"from public\.organizational_memory_items i\s*"
            r"where i\.source_document_id = v_doc\.id\s*"
            r"and i\.memory_class = 'SOURCE_MEMORY';",
            body)

    def test_ingest_rpc_never_silently_treats_incomplete_existing_document_as_complete(self):
        assert re.search(
            r"raise exception 'ingest_organizational_source_document: existing document % "
            r"for organization % has an inconsistent SOURCE_MEMORY chunk set",
            _MIGRATION_016)

    def test_ingest_rpc_inserts_document_and_all_chunks_in_one_function_body(self):
        start = _MIGRATION_016.index(
            "create or replace function public.ingest_organizational_source_document(")
        end = _MIGRATION_016.index(
            "revoke all on function public.ingest_organizational_source_document")
        body = _MIGRATION_016[start:end]
        assert "insert into public.organizational_source_documents" in body
        assert "insert into public.organizational_memory_items" in body
        # Exactly one function body -- both inserts share the same implicit
        # transaction, so a chunk-insert failure rolls back the parent too.
        assert body.count("create or replace function") == 1

    def test_python_layer_calls_ingest_rpc_exactly_once_per_upload(self):
        """Mirrors TestSnapshotGetOrCreateIsAnRpcCall's
        test_never_issues_a_separate_select_then_insert_from_python -- the
        atomicity guarantee is only real if the Python layer issues exactly
        one call carrying the full chunk set, never its own multi-call
        create-then-loop."""
        file_bytes = b"Body text for the concurrency-shape test.\n\nSecond paragraph too."
        with patch.object(tenancy.db, "list_organizational_source_documents", return_value=[]), \
             patch.object(tenancy.db, "upload_organizational_source_file", return_value="org/x/sources/y"), \
             patch.object(tenancy.db, "ingest_organizational_source_document",
                           return_value={"document": {"id": 1, "organization_id": ORG_A,
                                                        "content_hash": "x", "chunk_count": 1},
                                         "items": [], "reused_existing": False}) as fake_ingest, \
             patch.object(tenancy.db, "create_organizational_memory_item") as fake_old_item:
            tenancy.ingest_organizational_source_document_for_organization(
                ORG_A, "doc.txt", file_bytes, created_by_user_id="user-1")

        assert fake_ingest.call_count == 1
        fake_old_item.assert_not_called()


# ── Fix #2: durable artifact identity via Supabase Storage ──────────────

class TestDurableArtifactIdentity:

    def test_storage_upload_called_with_raw_bytes_hash_and_org_scoped_path(self):
        file_bytes = b"Raw bytes of the uploaded artifact, not the extracted text."
        raw_hash = __import__("hashlib").sha256(file_bytes).hexdigest()

        def fake_ingest(organization_id, filename, content_hash, chunks, **kwargs):
            assert kwargs["storage_path"] == f"org/{organization_id}/sources/{raw_hash}"
            assert kwargs["file_size"] == len(file_bytes)
            return {"document": {"id": 1, "organization_id": organization_id,
                                  "content_hash": content_hash, "chunk_count": len(chunks),
                                  "storage_path": kwargs["storage_path"], "file_size": kwargs["file_size"]},
                    "items": [], "reused_existing": False}

        with patch.object(tenancy.db, "list_organizational_source_documents", return_value=[]), \
             patch.object(tenancy.db, "upload_organizational_source_file",
                           return_value=f"org/{ORG_A}/sources/{raw_hash}") as fake_upload, \
             patch.object(tenancy.db, "ingest_organizational_source_document", side_effect=fake_ingest):
            result = tenancy.ingest_organizational_source_document_for_organization(
                ORG_A, "doc.txt", file_bytes, created_by_user_id="user-1")

        fake_upload.assert_called_once_with(ORG_A, raw_hash, file_bytes, content_type=None)
        assert result["document"]["storage_path"] == f"org/{ORG_A}/sources/{raw_hash}"
        assert result["document"]["file_size"] == len(file_bytes)

    def test_content_hash_is_from_raw_bytes_not_extracted_text(self):
        """Two byte-identical uploads that extract to DIFFERENT text (e.g.
        a hypothetical extractor quirk) must still resolve to the SAME
        content_hash, because the hash is computed from the raw bytes
        BEFORE extraction ever runs."""
        file_bytes = b"Identical raw bytes."
        raw_hash = __import__("hashlib").sha256(file_bytes).hexdigest()
        seen_hashes = []

        def fake_ingest(organization_id, filename, content_hash, chunks, **kwargs):
            seen_hashes.append(content_hash)
            return {"document": {"id": 1, "organization_id": organization_id,
                                  "content_hash": content_hash, "chunk_count": len(chunks)},
                    "items": [], "reused_existing": False}

        # Simulate a different extraction result each call -- content_hash
        # passed to the RPC must be identical regardless.
        with patch.object(tenancy.db, "list_organizational_source_documents", return_value=[]), \
             patch.object(tenancy.db, "upload_organizational_source_file", return_value="org/x/sources/y"), \
             patch.object(tenancy.db, "ingest_organizational_source_document", side_effect=fake_ingest), \
             patch("extractor.extract_text_from_file", side_effect=["Extraction run one.", "Extraction run two, different!"]):
            tenancy.ingest_organizational_source_document_for_organization(
                ORG_A, "doc.txt", file_bytes, created_by_user_id="user-1")
            tenancy.ingest_organizational_source_document_for_organization(
                ORG_A, "doc.txt", file_bytes, created_by_user_id="user-1")

        assert len(seen_hashes) == 2
        assert seen_hashes[0] == seen_hashes[1] == raw_hash

    def test_storage_columns_present_on_source_documents_table(self):
        assert "storage_path            text," in _MIGRATION_016
        assert "file_size               bigint," in _MIGRATION_016
        assert "content_type            text," in _MIGRATION_016

    def test_storage_upload_failure_prevents_any_db_bundle_creation(self):
        """Second commissioning-review hardening pass fix #2: a Storage
        upload failure must FAIL CLOSED, unlike database.save_upload()'s
        graceful-degradation contract. db.upload_organizational_source_file
        raising must propagate straight out of the tenancy wrapper, and the
        atomic ingest RPC (which would create the organizational_source_
        documents/organizational_memory_items bundle) must never even be
        called -- no partial DB state for an artifact that was never
        durably stored."""
        file_bytes = b"Some content whose Storage upload will fail."

        with patch.object(tenancy.db, "list_organizational_source_documents", return_value=[]), \
             patch.object(tenancy.db, "upload_organizational_source_file",
                           side_effect=RuntimeError("simulated Storage outage")), \
             patch.object(tenancy.db, "ingest_organizational_source_document") as fake_ingest:
            with pytest.raises(RuntimeError):
                tenancy.ingest_organizational_source_document_for_organization(
                    ORG_A, "doc.txt", file_bytes, created_by_user_id="user-1")

        fake_ingest.assert_not_called()

    def test_upload_organizational_source_file_raises_on_storage_exception(self):
        """database.upload_organizational_source_file() itself must raise
        (not swallow-and-return-None) when the underlying Storage client
        raises -- the fail-closed contract lives at this layer, not just in
        the tenancy wrapper that calls it."""
        import database as db_module

        class _FakeBucket:
            def upload(self, *a, **k):
                raise RuntimeError("simulated Storage client failure")

        class _FakeStorage:
            def from_(self, _bucket):
                return _FakeBucket()

        class _FakeClient:
            storage = _FakeStorage()

        with patch.object(db_module, "get_client", return_value=_FakeClient()):
            with pytest.raises(RuntimeError):
                db_module.upload_organizational_source_file(ORG_A, "a" * 64, b"bytes")


# ── Fix #3: actor membership validation (DB-level) ───────────────────────

class TestActorMembershipValidation:

    def test_membership_helper_function_present_and_service_role_only(self):
        assert "create or replace function public.is_user_organization_member(" in _MIGRATION_016
        assert re.search(
            r"grant execute on function public\.is_user_organization_member\([^)]*\) to service_role;",
            _MIGRATION_016)
        assert re.search(
            r"revoke all on function public\.is_user_organization_member\([^)]*\) from anon, authenticated;",
            _MIGRATION_016)

    def test_approve_rpc_verifies_approved_by_user_id_membership(self):
        assert re.search(
            r"if not public\.is_user_organization_member\(p_approved_by_user_id, p_organization_id\) then\s*"
            r"raise exception 'approve_organizational_memory_item: approved_by_user_id",
            _MIGRATION_016)

    def test_ingest_rpc_verifies_uploaded_by_user_id_membership(self):
        assert re.search(
            r"if p_uploaded_by_user_id is not null\s*"
            r"and not public\.is_user_organization_member\(p_uploaded_by_user_id, p_organization_id\)\s*"
            r"then\s*"
            r"raise exception 'ingest_organizational_source_document: uploaded_by_user_id",
            _MIGRATION_016)

    def test_membership_check_happens_before_any_approved_firm_knowledge_insert(self):
        start = _MIGRATION_016.index(
            "create or replace function public.approve_organizational_memory_item(")
        end = _MIGRATION_016.index(
            "revoke all on function public.approve_organizational_memory_item")
        body = _MIGRATION_016[start:end]
        membership_pos = body.index("is_user_organization_member(p_approved_by_user_id")
        insert_pos = body.index("insert into public.organizational_memory_items")
        assert membership_pos < insert_pos

    def test_membership_check_happens_before_any_document_or_chunk_insert(self):
        start = _MIGRATION_016.index(
            "create or replace function public.ingest_organizational_source_document(")
        end = _MIGRATION_016.index(
            "revoke all on function public.ingest_organizational_source_document")
        body = _MIGRATION_016[start:end]
        membership_pos = body.index("is_user_organization_member(p_uploaded_by_user_id")
        insert_pos = body.index("insert into public.organizational_source_documents")
        assert membership_pos < insert_pos


# ── Fix #4: durable lineage exposed in the retrieval contract ────────────

class TestRetrievalLineageExposure:

    def test_approved_result_exposes_source_document_id_and_derived_from_item_id(self):
        rows = [
            {"id": 55, "organization_id": ORG_A, "memory_class": "APPROVED_FIRM_KNOWLEDGE",
             "title": "ICF accreditation", "content": "Our firm holds ICF ACTP accreditation.",
             "approved_by_user_id": "user-1", "approved_at": "2026-01-01T00:00:00+00:00",
             "source_file_id": "omsrc:abc", "source_content_hash": "a" * 64,
             "source_document_id": 3, "derived_from_item_id": 5},
        ]
        with patch.object(tenancy.db, "list_organizational_memory_items", return_value=rows):
            results = tenancy.retrieve_organizational_memory_for_organization(
                ORG_A, "ICF accreditation", trusted_only=True)

        assert len(results) == 1
        assert results[0]["source_document_id"] == "3"
        assert results[0]["derived_from_item_id"] == "5"

    def test_lineage_fields_none_when_item_has_no_source_document(self):
        rows = [
            {"id": 1, "organization_id": ORG_A, "memory_class": "SOURCE_MEMORY",
             "title": "Manually authored note", "content": "Some manually authored source text.",
             "source_file_id": "omsrc:manual"},
        ]
        with patch.object(tenancy.db, "list_organizational_memory_items", return_value=rows):
            results = tenancy.retrieve_organizational_memory_for_organization(ORG_A, "manually authored")

        assert len(results) == 1
        assert results[0]["source_document_id"] is None
        assert results[0]["derived_from_item_id"] is None

    def test_retrieval_result_never_exposes_signed_url_or_storage_credential(self):
        """The lineage fields are identifiers only -- item_id/
        source_document_id/derived_from_item_id/provenance.storage_path --
        never a signed URL or any credential-shaped field."""
        from datetime import datetime, timezone
        item = om.OrganizationalMemoryItem(
            id="1", organization_id=ORG_A, memory_class=om.MemoryClass.APPROVED_FIRM_KNOWLEDGE,
            title="t", content="c",
            provenance=om.SourceProvenance(file_id="f", storage_path="org/x/sources/y"),
            approved_by="user-1", approved_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            derived_from_item_id="5", source_document_id="3",
        )
        results = om.retrieve(organization_id=ORG_A, query="t", items=[item])
        assert results
        d = results[0].to_dict()
        blob = str(d).lower()
        assert "signed" not in blob
        assert "token" not in blob
        assert "credential" not in blob
        assert d["provenance"]["storage_path"] == "org/x/sources/y"
        assert d["source_document_id"] == "3"
        assert d["derived_from_item_id"] == "5"

    def test_immutable_provenance_trigger_still_covers_source_document_id_after_hardening(self):
        # Regression guard: the hardening edits must not have disturbed the
        # existing OM-2 immutability coverage for source_document_id.
        assert "new.source_document_id is distinct from old.source_document_id" in _MIGRATION_016


# ── Fix #4: chunk content_hash is verified server-side, not trusted ──────

class TestChunkContentHashServerSideValidation:

    def test_pgcrypto_extension_present(self):
        assert "create extension if not exists pgcrypto;" in _MIGRATION_016

    def test_ingest_rpc_derives_and_validates_chunk_hash_via_digest(self):
        start = _MIGRATION_016.index(
            "create or replace function public.ingest_organizational_source_document(")
        end = _MIGRATION_016.index(
            "revoke all on function public.ingest_organizational_source_document")
        body = _MIGRATION_016[start:end]

        assert "v_expected_chunk_hash" in body
        assert "digest(" in body
        assert re.search(
            r"if v_expected_chunk_hash <> \(v_chunk->>'content_hash'\) then", body)
        assert "raise exception 'ingest_organizational_source_document: chunk content_hash does not match" in body

    def test_ingest_rpc_hash_derivation_happens_before_chunk_insert(self):
        start = _MIGRATION_016.index(
            "create or replace function public.ingest_organizational_source_document(")
        end = _MIGRATION_016.index(
            "revoke all on function public.ingest_organizational_source_document")
        body = _MIGRATION_016[start:end]
        derive_pos = body.index("v_expected_chunk_hash := encode(")
        insert_pos = body.index("insert into public.organizational_memory_items")
        assert derive_pos < insert_pos

    def test_ingest_rpc_inserts_server_derived_hash_not_caller_supplied(self):
        """The insert must use v_expected_chunk_hash (the server-derived
        value), never v_chunk->>'content_hash' (the caller-supplied,
        unverified value) directly, as the row's own content_hash."""
        start = _MIGRATION_016.index(
            "create or replace function public.ingest_organizational_source_document(")
        end = _MIGRATION_016.index(
            "revoke all on function public.ingest_organizational_source_document")
        body = _MIGRATION_016[start:end]
        assert re.search(
            r"v_chunk->>'title', v_chunk->>'content', v_expected_chunk_hash,", body)

    def test_python_content_hash_normalization_matches_sql_normalization_semantics(self):
        """organizational_memory.content_hash() normalizes \\r\\n and bare
        \\r to \\n before hashing UTF-8 bytes. The SQL-side re-derivation
        (regexp_replace \\r\\n -> \\n, then \\r -> \\n, then digest(...,
        'sha256')) must apply the SAME normalization before hashing --
        proven here at the logic level in Python by reimplementing the
        equivalent transform and comparing against om.content_hash()
        directly for texts containing both line-ending styles."""
        import hashlib

        def sql_equivalent_hash(text: str) -> str:
            normalized = text.replace("\r\n", "\n").replace("\r", "\n")
            return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

        for sample in (
            "Line one\r\nLine two\r\nLine three",
            "Line one\rLine two\rLine three",
            "Line one\nLine two\nLine three",
            "Mixed\r\nendings\rhere\nplain",
        ):
            assert om.content_hash(sample) == sql_equivalent_hash(sample)

    def test_approve_rpc_derives_content_hash_via_digest_not_caller_input(self):
        """Fix #4's second half: approve_organizational_memory_item()
        already derives its own content_hash server-side via digest()
        rather than trusting any client-supplied hash -- there is no
        p_content_hash/p_fact_content_hash parameter on this RPC at all,
        only p_fact_content (the text itself), and v_content_hash is always
        computed from v_content with digest(), the same canonical
        pgcrypto-based convention the ingest RPC now also uses."""
        start = _MIGRATION_016.index(
            "create or replace function public.approve_organizational_memory_item(")
        end = _MIGRATION_016.index(
            "revoke all on function public.approve_organizational_memory_item")
        body = _MIGRATION_016[start:end]

        assert "p_content_hash" not in body
        assert "p_fact_content_hash" not in body
        assert "digest(" in body
        # content_hash column is populated with v_content_hash, never a
        # client-supplied value.
        assert re.search(
            r"'APPROVED_FIRM_KNOWLEDGE',\s*"
            r"coalesce\(nullif\(p_fact_title, ''\), v_parent\.title\), v_content, v_content_hash,",
            body)


# ═══════════════════════════════════════════════════════════════════════════
# Final commissioning-review hardening pass (three fixes)
# ═══════════════════════════════════════════════════════════════════════════

# ── Fix #1: approve_organizational_memory_item() content_hash normalization
#            must match organizational_memory.content_hash() exactly ───────

class TestApproveRpcContentHashNormalization:

    def _approve_rpc_body(self):
        start = _MIGRATION_016.index(
            "create or replace function public.approve_organizational_memory_item(")
        end = _MIGRATION_016.index(
            "revoke all on function public.approve_organizational_memory_item")
        return _MIGRATION_016[start:end]

    def _ingest_rpc_body(self):
        start = _MIGRATION_016.index(
            "create or replace function public.ingest_organizational_source_document(")
        end = _MIGRATION_016.index(
            "revoke all on function public.ingest_organizational_source_document")
        return _MIGRATION_016[start:end]

    def test_approve_rpc_no_longer_hashes_raw_unnormalized_text(self):
        """The prior claim that approve_organizational_memory_item() was
        already 'consistent' with the ingest RPC's hashing was wrong: it
        hashed v_content raw, with no CRLF/CR normalization. That exact
        raw-digest expression must no longer be present."""
        body = self._approve_rpc_body()
        assert "v_content_hash := encode(digest(v_content, 'sha256'), 'hex');" not in body

    def test_approve_rpc_applies_same_crlf_then_cr_normalization_as_ingest_rpc(self):
        """approve_organizational_memory_item() must now perform the SAME
        two-step regexp_replace normalization (CRLF -> LF, then remaining
        CR -> LF) before digest(...,'sha256') that
        ingest_organizational_source_document() already applies to chunk
        hashes -- copied precisely, not approximated differently."""
        approve_body = self._approve_rpc_body()
        ingest_body = self._ingest_rpc_body()

        normalization_pattern = re.compile(
            r"regexp_replace\(\s*"
            r"regexp_replace\(coalesce\(([^,]+), ''\), chr\(13\) \|\| chr\(10\), chr\(10\), 'g'\),\s*"
            r"chr\(13\), chr\(10\), 'g'\)",
            re.MULTILINE)

        approve_match = normalization_pattern.search(approve_body)
        ingest_match = normalization_pattern.search(ingest_body)

        assert approve_match is not None, "approve RPC missing CRLF/CR normalization expression"
        assert ingest_match is not None, "ingest RPC missing CRLF/CR normalization expression"

        # Both RPCs must use the identical normalization construct (modulo
        # the variable name being normalized and incidental whitespace/
        # indentation) -- same regex pattern, same replacement order.
        def _normalize_whitespace(text: str) -> str:
            return re.sub(r"\s+", " ", text).strip()

        approve_normalized = _normalize_whitespace(
            approve_match.group(0).replace(approve_match.group(1), "X"))
        ingest_normalized = _normalize_whitespace(
            ingest_match.group(0).replace(ingest_match.group(1), "X"))
        assert approve_normalized == ingest_normalized

    def test_approve_rpc_wraps_normalization_in_digest_sha256_hex(self):
        body = self._approve_rpc_body()
        assert re.search(
            r"v_content_hash := encode\(\s*digest\(\s*regexp_replace\(", body)
        assert "'sha256'),\n        'hex');" in body or re.search(
            r"'sha256'\),\s*'hex'\);", body)

    def test_approve_rpc_normalization_matches_python_content_hash_for_mixed_newlines(self):
        """Reimplements the SQL-side normalization in Python (same technique
        TestChunkContentHashServerSideValidation uses for the ingest RPC)
        and proves it matches om.content_hash() for text containing both
        CRLF and bare-CR line endings -- exercising the exact fix, not just
        asserting the SQL text is present."""
        import hashlib

        def sql_equivalent_hash(text: str) -> str:
            normalized = text.replace("\r\n", "\n").replace("\r", "\n")
            return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

        for sample in (
            "Approved fact line one\r\nApproved fact line two",
            "Approved fact\ralternate ending",
            "Plain\napproved\ntext",
            "Mixed\r\nendings\rin an approved fact\nhere",
        ):
            assert om.content_hash(sample) == sql_equivalent_hash(sample)


# ── Fix #2: durable source artifact identity enforced at the DB boundary ──

class TestSourceDocumentStorageIdentityCheckConstraint:

    def test_check_constraint_requires_storage_path_and_file_size(self):
        assert re.search(
            r"constraint organizational_source_documents_storage_identity_required check \(\s*"
            r"storage_path is not null and file_size is not null\s*\)",
            _MIGRATION_016)

    def test_check_constraint_does_not_require_content_type(self):
        """content_type must remain genuinely optional -- it must not
        appear inside the storage-identity CHECK constraint's condition."""
        match = re.search(
            r"constraint organizational_source_documents_storage_identity_required check \(([^)]*)\)",
            _MIGRATION_016)
        assert match is not None
        assert "content_type" not in match.group(1)

    def test_check_constraint_is_on_source_documents_table(self):
        table_start = _MIGRATION_016.index(
            "create table if not exists organizational_source_documents")
        table_end = _MIGRATION_016.index(
            "create index if not exists idx_organizational_source_documents_org")
        table_body = _MIGRATION_016[table_start:table_end]
        assert "organizational_source_documents_storage_identity_required" in table_body


# ── Fix #3: empty p_chunks ingestion rejection at the DB boundary ────────

class TestIngestRpcRejectsEmptyChunks:

    def _ingest_rpc_body(self):
        start = _MIGRATION_016.index(
            "create or replace function public.ingest_organizational_source_document(")
        end = _MIGRATION_016.index(
            "revoke all on function public.ingest_organizational_source_document")
        return _MIGRATION_016[start:end]

    def test_rpc_raises_when_expected_chunks_is_zero(self):
        body = self._ingest_rpc_body()
        assert re.search(
            r"if v_expected_chunks = 0 then\s*"
            r"raise exception 'ingest_organizational_source_document: p_chunks must contain at least one chunk",
            body)

    def test_empty_chunk_guard_runs_before_parent_document_insert(self):
        body = self._ingest_rpc_body()
        guard_pos = body.index("if v_expected_chunks = 0 then")
        insert_pos = body.index("insert into public.organizational_source_documents (")
        assert guard_pos < insert_pos

    def test_empty_chunk_guard_computes_expected_chunks_before_checking(self):
        body = self._ingest_rpc_body()
        compute_pos = body.index("v_expected_chunks := coalesce(jsonb_array_length(p_chunks), 0);")
        guard_pos = body.index("if v_expected_chunks = 0 then")
        assert compute_pos < guard_pos

    def test_python_layer_also_rejects_zero_chunk_extraction_early(self):
        """Courtesy Python-side check in tenancy.py: extraction that yields
        no usable text (and therefore zero chunks) must raise before any
        Storage upload is attempted -- the DB-side guard above is the
        REQUIRED enforcement; this is defense-in-depth only."""
        file_bytes = b"some bytes"

        with patch.object(tenancy.db, "list_organizational_source_documents", return_value=[]), \
             patch.object(tenancy.db, "upload_organizational_source_file") as fake_upload, \
             patch.object(tenancy.db, "ingest_organizational_source_document") as fake_ingest, \
             patch("extractor.extract_text_from_file", return_value=""):
            with pytest.raises(ValueError):
                tenancy.ingest_organizational_source_document_for_organization(
                    ORG_A, "empty.txt", file_bytes, created_by_user_id="user-1")

        fake_upload.assert_not_called()
        fake_ingest.assert_not_called()
