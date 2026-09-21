"""
tests/test_organizational_memory.py

Organizational Memory OM-1: the retrieval contract (organizational_memory.py)
and its tenancy.py wiring (tenancy.create_organizational_memory_item_for_
organization / list_organizational_memory_for_organization /
retrieve_organizational_memory_for_organization).

No live provider/embedding call anywhere in this file -- every embedding is
either omitted (deterministic keyword fallback) or a hand-built mock
function, never a real or mocked Voyage/Anthropic client invocation of any
kind.
"""
import re
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

import organizational_memory as om
import tenancy


_MIGRATION_016 = (Path(__file__).resolve().parents[1] / "migrations"
                  / "016_organizational_memory.sql").read_text(encoding="utf-8")


ORG_A = "11111111-1111-1111-1111-111111111111"
ORG_B = "22222222-2222-2222-2222-222222222222"


def _source_item(item_id="s1", organization_id=ORG_A, content="We delivered leadership coaching to 40 federal executives across three departments.", **kw):
    kw.setdefault("provenance", om.SourceProvenance(file_id="file-1", content_hash="a" * 64, filename="case_study.pdf"))
    return om.OrganizationalMemoryItem(
        id=item_id, organization_id=organization_id,
        memory_class=om.MemoryClass.SOURCE_MEMORY,
        title="Federal executive coaching case study", content=content,
        **kw,
    )


def _approved_item(item_id="k1", organization_id=ORG_A, content="Our firm holds ICF ACTP accreditation renewed annually since 2015.", **kw):
    kw.setdefault("provenance", om.SourceProvenance(file_id="file-2", content_hash="b" * 64))
    kw.setdefault("derived_from_item_id", "s1")
    return om.OrganizationalMemoryItem(
        id=item_id, organization_id=organization_id,
        memory_class=om.MemoryClass.APPROVED_FIRM_KNOWLEDGE,
        title="ICF ACTP accreditation", content=content,
        approved_by="user-1", approved_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        **kw,
    )


def _proposal_item(item_id="p1", organization_id=ORG_A, content="Our team of 10 certified coaches will deliver the engagement within 12 weeks.", **kw):
    kw.setdefault("provenance", om.SourceProvenance(file_id="file-3", content_hash="c" * 64, source_bid_id=42))
    return om.OrganizationalMemoryItem(
        id=item_id, organization_id=organization_id,
        memory_class=om.MemoryClass.PROPOSAL_MEMORY,
        title="Staffing commitment language", content=content,
        **kw,
    )


# ── Memory class structural distinctness ────────────────────────────────

class TestMemoryClassStructuralDistinctness:

    def test_three_classes_are_recognized(self):
        assert om.MemoryClass.SOURCE_MEMORY.value == "SOURCE_MEMORY"
        assert om.MemoryClass.APPROVED_FIRM_KNOWLEDGE.value == "APPROVED_FIRM_KNOWLEDGE"
        assert om.MemoryClass.PROPOSAL_MEMORY.value == "PROPOSAL_MEMORY"

    def test_source_memory_is_not_trusted_fact(self):
        item = _source_item()
        assert item.is_trusted_fact is False
        assert item.can_prove_facts is False

    def test_approved_firm_knowledge_is_trusted_fact(self):
        item = _approved_item()
        assert item.is_trusted_fact is True
        assert item.can_prove_facts is True

    def test_proposal_memory_is_never_trusted_fact(self):
        item = _proposal_item()
        assert item.is_trusted_fact is False
        assert item.can_prove_facts is False


# ── Approval / trust semantics ───────────────────────────────────────────

class TestApprovalSemantics:

    def test_approved_firm_knowledge_requires_approved_by_and_at(self):
        with pytest.raises(om.OrganizationalMemoryError):
            om.OrganizationalMemoryItem(
                id="bad1", organization_id=ORG_A,
                memory_class=om.MemoryClass.APPROVED_FIRM_KNOWLEDGE,
                title="t", content="c",
                provenance=om.SourceProvenance(file_id="f"),
                # no approved_by / approved_at
            )

    def test_approved_firm_knowledge_rejects_partial_approval(self):
        with pytest.raises(om.OrganizationalMemoryError):
            om.OrganizationalMemoryItem(
                id="bad2", organization_id=ORG_A,
                memory_class=om.MemoryClass.APPROVED_FIRM_KNOWLEDGE,
                title="t", content="c",
                provenance=om.SourceProvenance(file_id="f"),
                approved_by="user-1",   # approved_at missing
            )

    def test_source_memory_cannot_carry_approval_fields(self):
        """Nothing gets APPROVED_FIRM_KNOWLEDGE status by default or
        automatically -- a SOURCE_MEMORY item that tries to smuggle in
        approval fields is rejected outright, never silently promoted."""
        with pytest.raises(om.OrganizationalMemoryError):
            om.OrganizationalMemoryItem(
                id="bad3", organization_id=ORG_A,
                memory_class=om.MemoryClass.SOURCE_MEMORY,
                title="t", content="c",
                provenance=om.SourceProvenance(file_id="f", content_hash="a" * 64),
                approved_by="user-1", approved_at=datetime.now(timezone.utc),
            )

    def test_proposal_memory_cannot_carry_approval_fields(self):
        with pytest.raises(om.OrganizationalMemoryError):
            om.OrganizationalMemoryItem(
                id="bad4", organization_id=ORG_A,
                memory_class=om.MemoryClass.PROPOSAL_MEMORY,
                title="t", content="c",
                provenance=om.SourceProvenance(file_id="f", content_hash="a" * 64),
                approved_by="user-1", approved_at=datetime.now(timezone.utc),
            )

    def test_valid_approved_item_constructs_cleanly(self):
        item = _approved_item()
        assert item.approved_by == "user-1"
        assert item.approved_at is not None

    def test_approved_firm_knowledge_requires_derived_from_item_id(self):
        """Mirrors migration 016's organizational_memory_items_approved_
        requires_lineage CHECK constraint at the Python layer -- it must be
        impossible to even CONSTRUCT an in-memory APPROVED_FIRM_KNOWLEDGE
        item with no identified SOURCE_MEMORY lineage."""
        with pytest.raises(om.OrganizationalMemoryError):
            om.OrganizationalMemoryItem(
                id="bad6", organization_id=ORG_A,
                memory_class=om.MemoryClass.APPROVED_FIRM_KNOWLEDGE,
                title="t", content="c",
                provenance=om.SourceProvenance(file_id="f"),
                approved_by="user-1", approved_at=datetime.now(timezone.utc),
                # no derived_from_item_id
            )

    def test_approved_firm_knowledge_with_derived_from_item_id_constructs_cleanly(self):
        item = _approved_item(derived_from_item_id="s1")
        assert item.derived_from_item_id == "s1"


# ── Exact source linkage (never fabricated/vague provenance) ────────────

class TestExactSourceLinkage:

    def test_source_memory_requires_exact_identity(self):
        with pytest.raises(om.OrganizationalMemoryError):
            om.OrganizationalMemoryItem(
                id="bad5", organization_id=ORG_A,
                memory_class=om.MemoryClass.SOURCE_MEMORY,
                title="t", content="c",
                provenance=om.SourceProvenance(),   # no file_id, no content_hash
            )

    def test_proposal_memory_requires_exact_identity(self):
        with pytest.raises(om.OrganizationalMemoryError):
            om.OrganizationalMemoryItem(
                id="bad6", organization_id=ORG_A,
                memory_class=om.MemoryClass.PROPOSAL_MEMORY,
                title="t", content="c",
                provenance=om.SourceProvenance(),
            )

    def test_content_hash_only_is_sufficient_identity(self):
        item = om.OrganizationalMemoryItem(
            id="ok1", organization_id=ORG_A,
            memory_class=om.MemoryClass.SOURCE_MEMORY,
            title="t", content="c",
            provenance=om.SourceProvenance(content_hash="d" * 64),
        )
        assert item.provenance.has_exact_identity()

    def test_content_hash_function_is_deterministic_and_exact(self):
        assert om.content_hash("hello world") == om.content_hash("hello world")
        assert om.content_hash("hello world") != om.content_hash("hello world!")

    def test_content_hash_normalizes_line_endings_not_meaning(self):
        assert om.content_hash("a\r\nb") == om.content_hash("a\nb")


# ── Immutability of write path (content_hash never trusted from caller) ──

class TestImmutableProvenanceWritePath:

    def test_create_forces_organization_id_and_recomputes_content_hash(self):
        captured = {}

        def fake_create(payload):
            captured.update(payload)
            return {"id": 1, **payload}

        with patch.object(tenancy.db, "create_organizational_memory_item", side_effect=fake_create):
            tenancy.create_organizational_memory_item_for_organization(
                ORG_A,
                {
                    "organization_id": "someone-elses-org",   # attempted spoof
                    "memory_class": "SOURCE_MEMORY",
                    "title": "t", "content": "authentic content",
                    "content_hash": "ffff",   # attempted spoofed hash
                    "source_file_id": "file-9",
                },
                created_by_user_id="user-1",
            )

        assert captured["organization_id"] == ORG_A
        assert captured["content_hash"] == om.content_hash("authentic content")
        assert captured["content_hash"] != "ffff"

    def test_create_requires_organization_id(self):
        with pytest.raises(ValueError):
            tenancy.create_organizational_memory_item_for_organization(
                "", {"memory_class": "SOURCE_MEMORY", "content": "x"})


# ── Organization isolation (direct data access) ──────────────────────────

class TestOrganizationIsolation:

    def test_list_never_crosses_organizations(self):
        rows_a = [{"id": 1, "organization_id": ORG_A, "memory_class": "SOURCE_MEMORY",
                   "title": "a", "content": "a-content"}]

        def fake_list(organization_id, memory_class=None):
            assert organization_id == ORG_A   # tenancy must have passed exactly what was asked
            return rows_a

        with patch.object(tenancy.db, "list_organizational_memory_items", side_effect=fake_list):
            result = tenancy.list_organizational_memory_for_organization(ORG_A)
        assert len(result) == 1
        assert result[0]["organization_id"] == ORG_A

    def test_list_requires_organization_id(self):
        with pytest.raises(ValueError):
            tenancy.list_organizational_memory_for_organization("")


# ── Retrieval contract: filtering / ranking / no cross-org leakage ──────

class TestRetrievalContract:

    def test_deterministic_given_same_inputs(self):
        items = [_source_item(), _approved_item(), _proposal_item()]
        r1 = om.retrieve(organization_id=ORG_A, query="coaching accreditation", items=items)
        r2 = om.retrieve(organization_id=ORG_A, query="coaching accreditation", items=items)
        assert [r.item_id for r in r1] == [r.item_id for r in r2]
        assert [r.relevance_score for r in r1] == [r.relevance_score for r in r2]

    def test_no_cross_organization_retrieval(self):
        """Same isolation guarantee as direct data access, but exercised
        through the retrieval contract's own query path."""
        items = [_source_item(item_id="a-item", organization_id=ORG_A),
                 _source_item(item_id="b-item", organization_id=ORG_B)]
        results = om.retrieve(organization_id=ORG_A, query="coaching", items=items)
        assert all(r.item_id == "a-item" for r in results)
        assert not any(r.item_id == "b-item" for r in results)

    def test_filters_by_memory_class(self):
        items = [_source_item(), _approved_item(), _proposal_item()]
        results = om.retrieve(
            organization_id=ORG_A, query="coaching accreditation staffing", items=items,
            memory_classes=[om.MemoryClass.APPROVED_FIRM_KNOWLEDGE])
        assert all(r.memory_class is om.MemoryClass.APPROVED_FIRM_KNOWLEDGE for r in results)
        assert len(results) == 1

    def test_trusted_only_restricts_to_approved_firm_knowledge(self):
        items = [_source_item(), _approved_item(), _proposal_item()]
        results = om.retrieve(organization_id=ORG_A, query="anything", items=items, trusted_only=True)
        assert all(r.is_trusted_fact for r in results)
        assert all(r.memory_class is om.MemoryClass.APPROVED_FIRM_KNOWLEDGE for r in results)

    def test_top_k_bounds_results_never_dumps_everything(self):
        items = [_source_item(item_id=f"s{i}", content=f"coaching engagement number {i} details") for i in range(50)]
        results = om.retrieve(organization_id=ORG_A, query="coaching engagement", items=items, top_k=5)
        assert len(results) <= 5

    def test_every_result_exposes_class_trust_provenance_and_score(self):
        items = [_approved_item()]
        results = om.retrieve(organization_id=ORG_A, query="ICF accreditation", items=items)
        assert results, "expected at least one keyword-matched result"
        r = results[0]
        d = r.to_dict()
        assert set(["memory_class", "is_trusted_fact", "approved_by", "approved_at",
                    "provenance", "relevance_score", "relevance_signal"]).issubset(d.keys())

    def test_requires_organization_id(self):
        with pytest.raises(om.OrganizationalMemoryError):
            om.retrieve(organization_id="", query="x", items=[])

    def test_empty_items_returns_empty(self):
        assert om.retrieve(organization_id=ORG_A, query="x", items=[]) == []

    def test_min_score_filters_low_relevance_results(self):
        items = [_source_item(content="completely unrelated municipal snow removal contract text")]
        results = om.retrieve(organization_id=ORG_A, query="executive coaching leadership",
                              items=items, min_score=0.5)
        assert results == []


# ── Previous-proposal-not-truth behavior ─────────────────────────────────

class TestProposalMemoryNeverTruth:

    def test_proposal_memory_result_never_marked_trusted(self):
        items = [_proposal_item()]
        results = om.retrieve(organization_id=ORG_A, query="staffing commitment", items=items)
        assert results
        assert all(not r.is_trusted_fact for r in results)

    def test_no_code_path_promotes_proposal_memory_to_approved(self):
        """There is no function anywhere in organizational_memory.py that
        changes an item's memory_class -- the only way PROPOSAL_MEMORY
        content becomes APPROVED_FIRM_KNOWLEDGE is a brand-new item built
        by an explicit human action, never a mutation of the existing row."""
        assert not hasattr(om, "promote")
        assert not hasattr(om, "promote_to_approved")
        assert not hasattr(om, "auto_approve")


# ── Graceful embedding-unavailable fallback ──────────────────────────────

class TestEmbeddingFallback:

    def test_no_embed_fn_uses_keyword_fallback(self):
        items = [_source_item()]
        results = om.retrieve(organization_id=ORG_A, query="federal executive coaching", items=items)
        assert results
        assert results[0].relevance_signal == "KEYWORD"

    def test_embed_fn_raising_degrades_to_keyword_fallback(self):
        def broken_embed(_query):
            raise RuntimeError("simulated Voyage outage")

        items = [_source_item()]
        results = om.retrieve(organization_id=ORG_A, query="federal executive coaching",
                              items=items, embed_fn=broken_embed)
        assert results
        assert results[0].relevance_signal == "KEYWORD"

    def test_embed_fn_returning_none_degrades_to_keyword_fallback(self):
        items = [_source_item()]
        results = om.retrieve(organization_id=ORG_A, query="federal executive coaching",
                              items=items, embed_fn=lambda q: None)
        assert results
        assert results[0].relevance_signal == "KEYWORD"

    def test_usable_mocked_embedding_uses_semantic_signal(self):
        item = _source_item()
        item_with_vec = om.OrganizationalMemoryItem(
            id=item.id, organization_id=item.organization_id, memory_class=item.memory_class,
            title=item.title, content=item.content, provenance=item.provenance,
            embedding=[1.0, 0.0, 0.0],
        )
        results = om.retrieve(
            organization_id=ORG_A, query="anything", items=[item_with_vec],
            embed_fn=lambda q: [1.0, 0.0, 0.0])
        assert results
        assert results[0].relevance_signal == "SEMANTIC"
        assert results[0].relevance_score == pytest.approx(1.0)

    def test_no_items_have_embeddings_degrades_even_with_working_embed_fn(self):
        items = [_source_item()]   # no embedding set
        results = om.retrieve(
            organization_id=ORG_A, query="federal executive coaching", items=items,
            embed_fn=lambda q: [1.0, 0.0, 0.0])
        assert results
        assert results[0].relevance_signal == "KEYWORD"


# ── tenancy.py retrieval wiring ───────────────────────────────────────────

class TestTenancyRetrievalWiring:

    def test_retrieve_for_organization_only_sees_own_rows(self):
        rows = [
            {"id": 1, "organization_id": ORG_A, "memory_class": "APPROVED_FIRM_KNOWLEDGE",
             "title": "ICF accreditation", "content": "Our firm holds ICF ACTP accreditation.",
             "approved_by_user_id": "user-1", "approved_at": "2026-01-01T00:00:00+00:00",
             "source_file_id": "file-2", "derived_from_item_id": 99},
        ]

        def fake_list(organization_id, memory_class=None):
            assert organization_id == ORG_A
            return rows

        with patch.object(tenancy.db, "list_organizational_memory_items", side_effect=fake_list):
            results = tenancy.retrieve_organizational_memory_for_organization(
                ORG_A, "ICF accreditation")
        assert len(results) == 1
        assert results[0]["memory_class"] == "APPROVED_FIRM_KNOWLEDGE"
        assert results[0]["is_trusted_fact"] is True
        assert results[0]["provenance"]["file_id"] == "file-2"

    def test_retrieve_requires_organization_id(self):
        with pytest.raises(ValueError):
            tenancy.retrieve_organizational_memory_for_organization("", "query")


# ── Compatibility with existing evidence/provenance discipline ──────────

class TestEvidenceArchitectureCompatibility:

    def test_provenance_shape_mirrors_proposal_source_ref_fields(self):
        """analyst._build_proposal_source_ref emits file_id/content_hash/
        filename/package_path (see analyst.py around _build_proposal_
        source_ref) -- SourceProvenance carries the same field names for
        the same physical-identity concepts, so a caller migrating
        provenance data between the two systems needs no field remapping."""
        provenance = om.SourceProvenance(
            file_id="file-1", content_hash="a" * 64, filename="doc.pdf",
            package_path="folder/doc.pdf", locator="page:3")
        d = provenance.to_dict()
        for key in ("file_id", "content_hash", "filename", "package_path", "locator"):
            assert key in d

    def test_content_hash_uses_sha256_like_evidence_py(self):
        import hashlib
        expected = hashlib.sha256("sample text".encode("utf-8")).hexdigest()
        assert om.content_hash("sample text") == expected


# ── Commissioning-review hardening: SQL-level write-boundary invariants ──
#
# Migration 016 is NOT applied to any live database in this test
# environment (see docs/current/SYSTEM_STATE.md / CLAUDE.md) -- these
# tests cannot issue real DDL/DML. They instead follow the same two-layer
# pattern tests/test_proposal_intelligence_database.py established for
# migration 015: (a) assert the migration FILE's own text expresses the
# intended CHECK/trigger/FK shape (a "migration DDL-intent" test -- proves
# the SQL text says what it must, not that Postgres has executed it), and
# (b) exercise the Python-layer entry point (tenancy.py's generic create
# function) directly -- including calls that do NOT go through
# OrganizationalMemoryItem's own __post_init__ at all -- to prove the
# application layer independently refuses the same disallowed cases as a
# defense-in-depth measure, not merely because the dataclass happens to.

class TestMigrationDDLIntent:
    """Migration 016 DDL-intent assertions -- mirrors
    TestMigrationDDLIntent in tests/test_proposal_intelligence_database.py."""

    def test_exact_source_identity_check_constraint_present(self):
        assert "organizational_memory_items_exact_source_identity" in _MIGRATION_016
        assert re.search(
            r"memory_class not in \('SOURCE_MEMORY', 'PROPOSAL_MEMORY'\)\s*"
            r"or source_file_id is not null\s*"
            r"or source_content_hash is not null",
            _MIGRATION_016)

    def test_approved_firm_knowledge_requires_lineage_check_constraint_present(self):
        assert "organizational_memory_items_approved_requires_lineage" in _MIGRATION_016
        assert re.search(
            r"memory_class <> 'APPROVED_FIRM_KNOWLEDGE' or derived_from_item_id is not null",
            _MIGRATION_016)

    def test_derived_from_item_id_has_composite_same_organization_fk(self):
        assert re.search(
            r"foreign key\s*\(derived_from_item_id,\s*organization_id\)\s*"
            r"references organizational_memory_items\s*\(id,\s*organization_id\)",
            _MIGRATION_016, re.IGNORECASE)

    def test_table_has_composite_unique_id_organization_id(self):
        assert "unique (id, organization_id)" in _MIGRATION_016

    def test_derived_lineage_class_guard_trigger_present(self):
        assert "organizational_memory_items_guard_derived_lineage" in _MIGRATION_016
        assert "trg_organizational_memory_items_guard_derived_lineage" in _MIGRATION_016
        # The trigger body must actually check the referenced row's
        # memory_class, not just its existence.
        assert re.search(
            r"select memory_class into v_source_class\s*"
            r"from public\.organizational_memory_items\s*"
            r"where id = new\.derived_from_item_id",
            _MIGRATION_016)
        assert "v_source_class <> 'SOURCE_MEMORY'" in _MIGRATION_016

    def test_source_bid_id_cross_tenant_guard_trigger_present(self):
        assert "organizational_memory_items_guard_source_bid_org" in _MIGRATION_016
        assert "trg_organizational_memory_items_guard_source_bid_org" in _MIGRATION_016
        assert re.search(
            r"select organization_id into v_bid_org\s*from public\.bids\s*"
            r"where id = new\.source_bid_id",
            _MIGRATION_016)
        assert "v_bid_org <> new.organization_id" in _MIGRATION_016

    def test_generic_rpc_rejects_approved_firm_knowledge(self):
        assert re.search(
            r"if p_item->>'memory_class' = 'APPROVED_FIRM_KNOWLEDGE' then\s*"
            r"raise exception",
            _MIGRATION_016)

    def test_both_new_guard_triggers_fire_before_insert_or_update(self):
        assert re.search(
            r"before insert or update on public\.organizational_memory_items\s*"
            r"for each row execute function public\.organizational_memory_items_guard_derived_lineage",
            _MIGRATION_016)
        assert re.search(
            r"before insert or update on public\.organizational_memory_items\s*"
            r"for each row execute function public\.organizational_memory_items_guard_source_bid_org",
            _MIGRATION_016)

    # ── Second commissioning-review pass: immutability + FK deletion ────

    def test_immutability_trigger_covers_approval_and_lineage_columns(self):
        """The immutable-provenance trigger must now ALSO block post-
        creation mutation of approved_by_user_id, approved_at, and
        derived_from_item_id -- trust-history fields, immutable exactly
        like source identity."""
        assert "organizational_memory_items_guard_immutable_provenance" in _MIGRATION_016
        assert re.search(
            r"new\.approved_by_user_id is distinct from old\.approved_by_user_id",
            _MIGRATION_016)
        assert re.search(
            r"new\.approved_at\s*is distinct from old\.approved_at",
            _MIGRATION_016)
        assert re.search(
            r"new\.derived_from_item_id is distinct from old\.derived_from_item_id",
            _MIGRATION_016)

    def test_source_bid_id_fk_uses_restrict_not_set_null(self):
        assert re.search(
            r"source_bid_id\s+bigint references public\.bids\(id\) on delete restrict",
            _MIGRATION_016, re.IGNORECASE)
        assert not re.search(
            r"source_bid_id\s+bigint references public\.bids\(id\) on delete set null",
            _MIGRATION_016, re.IGNORECASE)

    def test_derived_from_item_id_fk_uses_restrict_not_set_null(self):
        assert re.search(
            r"foreign key\s*\(derived_from_item_id,\s*organization_id\)\s*"
            r"references organizational_memory_items\s*\(id,\s*organization_id\)\s*on delete restrict",
            _MIGRATION_016, re.IGNORECASE)
        assert not re.search(
            r"foreign key\s*\(derived_from_item_id,\s*organization_id\)\s*"
            r"references organizational_memory_items\s*\(id,\s*organization_id\)\s*on delete set null",
            _MIGRATION_016, re.IGNORECASE)


class TestGenericCreatePathRejectsApprovedFirmKnowledge:
    """tenancy.create_organizational_memory_item_for_organization() is the
    generic write path. It must reject memory_class =
    'APPROVED_FIRM_KNOWLEDGE' at the APPLICATION layer -- called directly,
    bypassing OrganizationalMemoryItem's own __post_init__ entirely (no
    dataclass is constructed here), to prove this is genuine defense-in-
    depth and not just a restatement of the dataclass's own validation."""

    def test_rejects_approved_firm_knowledge_via_generic_path(self):
        with patch.object(tenancy.db, "create_organizational_memory_item") as fake_create:
            with pytest.raises(ValueError):
                tenancy.create_organizational_memory_item_for_organization(
                    ORG_A,
                    {
                        "memory_class": "APPROVED_FIRM_KNOWLEDGE",
                        "title": "t", "content": "manufactured trusted fact",
                        "approved_by_user_id": "user-1",
                        "approved_at": "2026-01-01T00:00:00+00:00",
                        "derived_from_item_id": 1,
                    },
                    created_by_user_id="user-1",
                )
            # The DB layer must never even be reached -- rejection happens
            # before any write is attempted.
            fake_create.assert_not_called()

    def test_source_memory_still_creatable_via_generic_path(self):
        """The restriction must be scoped to APPROVED_FIRM_KNOWLEDGE only
        -- SOURCE_MEMORY remains creatable through the same generic path,
        unaffected."""
        with patch.object(tenancy.db, "create_organizational_memory_item",
                          side_effect=lambda payload: {"id": 1, **payload}) as fake_create:
            result = tenancy.create_organizational_memory_item_for_organization(
                ORG_A,
                {
                    "memory_class": "SOURCE_MEMORY",
                    "title": "t", "content": "authentic source content",
                    "source_file_id": "file-9",
                },
                created_by_user_id="user-1",
            )
        fake_create.assert_called_once()
        assert result["memory_class"] == "SOURCE_MEMORY"

    def test_proposal_memory_still_creatable_via_generic_path(self):
        with patch.object(tenancy.db, "create_organizational_memory_item",
                          side_effect=lambda payload: {"id": 2, **payload}) as fake_create:
            result = tenancy.create_organizational_memory_item_for_organization(
                ORG_A,
                {
                    "memory_class": "PROPOSAL_MEMORY",
                    "title": "t", "content": "reusable proposal language",
                    "source_file_id": "file-10",
                },
                created_by_user_id="user-1",
            )
        fake_create.assert_called_once()
        assert result["memory_class"] == "PROPOSAL_MEMORY"
