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
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

import organizational_memory as om
import tenancy


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
             "source_file_id": "file-2"},
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
