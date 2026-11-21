"""Release-blocking constraints C1/C2 (docs/current/ENGINE_REBUILD_CONSTRAINTS.md):
no buyer-/document-specific behaviour, no evaluation material reachable from
production, no cross-tenant or memory reads."""
from __future__ import annotations

import ast
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE = os.path.join(ROOT, "engine")
PROD = [os.path.join(ENGINE, f) for f in os.listdir(ENGINE) if f.endswith(".py")] + \
       [os.path.join(ROOT, "pages", "stage_engine.py")]

#: names of real buyers, clients and evaluation packages that must never appear
#: in production engine code or prompts
FORBIDDEN = re.compile(r"\b(?:LAU|Lebanese American|OPCO|2B ?OPCO|INJAZ|Phoenix|Bank of Canada|Calgar\w*|"
                       r"Northwind|NRA-SYN|Meridian Coastal|MCWA|GovTech|Ngultrum|CSCS|ICFR|Energy Secure|DEOS|"
                       r"Tomorrow.s Leaders|Adaptive Leadership|Heifetz|Vacancy\.proc|sokhen)\b", re.I)


def _src(p):
    with open(p, encoding="utf-8") as fh:
        return fh.read()


def test_no_buyer_or_document_specific_text_in_engine_code_or_prompts():
    hits = [(os.path.basename(p), m.group(0)) for p in PROD for m in FORBIDDEN.finditer(_src(p))]
    assert hits == []


def _imports(p):
    tree = ast.parse(_src(p))
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module:
            out.add(n.module)
    return out


def test_production_never_imports_test_material_memory_or_content_library():
    banned = {"engine_synthetic", "tests", "organizational_memory", "content_library", "embeddings",
              "section_drafting", "evidence_strengthening"}
    for p in PROD:
        bad = {m for m in _imports(p) if m.split(".")[0] in banned}
        assert not bad, (p, bad)


def test_engine_reads_documents_only_of_the_requested_bid(monkeypatch):
    import database as db
    from engine import service
    seen = []
    monkeypatch.setattr(db, "get_documents", lambda bid_id: seen.append(bid_id) or [
        {"id": 1, "name": "x.txt", "doc_type": "RFP / Source", "storage_path": f"{bid_id}/x.txt", "created_at": "1"},
        {"id": 2, "name": "proposal.txt", "doc_type": "Proposal Draft", "storage_path": f"{bid_id}/p.txt"}])
    monkeypatch.setattr(db, "download_file", lambda path: (seen.append(path) or b"Bidders must register."))
    p = service.load_bid_package(41)
    assert seen == [41, "41/x.txt"] and [d.name for d in p.documents] == ["x.txt"]
    assert p.data_class == "CLIENT"


def test_tenancy_wrappers_check_access_first(monkeypatch):
    import tenancy
    calls = []
    monkeypatch.setattr(tenancy, "require_bid_access", lambda b, o: calls.append((b, o)) or
                        (_ for _ in ()).throw(tenancy.AccessDeniedError("no")))
    for fn in (lambda: tenancy.start_engine_analysis_for_organization(5, "org"),
               lambda: tenancy.get_engine_status_for_organization(5, "org"),
               lambda: tenancy.get_engine_result_for_organization(5, "org", 1),
               lambda: tenancy.export_engine_pdf_for_organization(5, "org", 1, "FAST")):
        try:
            fn()
        except tenancy.AccessDeniedError:
            pass
        else:
            raise AssertionError("access was not checked")
    assert calls == [(5, "org")] * 4


def test_migration_scopes_runs_to_the_bid_owner():
    sql = _src(os.path.join(ROOT, "migrations", "027_engine_runs.sql"))
    assert "organization_id" in sql and "can_access_bid(bid_id)" in sql
    assert "does not own bid" in sql and "enable row level security" in sql
    assert not re.search(r"create policy[^;]*for (insert|update|delete)", sql, re.I)
