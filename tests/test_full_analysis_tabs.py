"""Full Bid Intelligence page: six tabs over the verified report facts, and
Detailed Findings limited to document-grounded specialist findings."""
from pages import stage_full_analysis as page


def test_six_tabs_in_order():
    assert page.RESULT_TABS == ("Overview", "Requirements", "Evaluation", "Commercial",
                                "Buyer Intelligence", "Detailed Findings")


def test_detailed_findings_show_only_grounded_facts():
    findings = [
        {"title": "Email submission to two addresses", "authority": "CANONICAL", "canonical_ids": ["SUB-1"]},
        {"title": "Buyer may favour local trainers", "authority": "SPECIALIST_INTERPRETATION",
         "canonical_ids": ["REQ-2"]},
        {"title": "Payment terms not specified", "authority": "CANONICAL", "canonical_ids": ["PAY-1"]},
        {"title": "Unreferenced fact", "authority": "CANONICAL"},
    ]
    assert [f["title"] for f in page._grounded(findings)] == ["Email submission to two addresses"]


def test_facts_cache_does_not_cache_errors(monkeypatch):
    calls = []

    def boom(*a):
        calls.append(a)
        raise RuntimeError("storage down")
    monkeypatch.setattr(page.tenancy, "get_full_analysis_facts_for_organization", boom)
    session = {}
    assert "error" in page.load_facts(1, "org", 2, session) and session == {}
    monkeypatch.setattr(page.tenancy, "get_full_analysis_facts_for_organization", lambda *a: {"ok": 1})
    assert page.load_facts(1, "org", 2, session) == {"facts": {"ok": 1}}
    assert page.load_facts(1, "org", 2, session) == {"facts": {"ok": 1}}
