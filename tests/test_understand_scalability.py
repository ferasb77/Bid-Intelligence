"""tests/test_understand_scalability.py -- Tests for large-package scalability remediation."""
import json
import pytest
import understand_scalability as us


def test_exact_duplicate_document_suppression():
    doc1 = ("RFP_Main.pdf", "This is the complete text of the Request for Proposals.")
    doc2 = ("Copy_of_RFP_Main.pdf", "This is the complete text of the Request for Proposals.")
    doc3 = ("Addendum_1.pdf", "This is the complete text of the Request for Proposals.")  # Addendum keyword
    doc4 = ("Schedule_A.pdf", "Distinct text for schedule A.")

    docs = [doc1, doc2, doc3, doc4]
    retained, alias_map = us.detect_duplicate_documents(docs)

    retained_names = [name for name, _ in retained]
    assert "RFP_Main.pdf" in retained_names
    assert "Copy_of_RFP_Main.pdf" not in retained_names
    assert alias_map["Copy_of_RFP_Main.pdf"] == "RFP_Main.pdf"
    # Legal distinction preserved for Addendum even if boilerplate text matches
    assert "Addendum_1.pdf" in retained_names
    assert "Schedule_A.pdf" in retained_names


def test_near_duplicate_clustering_collapses_redundant_requirements():
    reqs = [
        {"req_id": "REQ-1", "category": "Mandatory", "description": "The contractor must submit proof of valid WCB insurance coverage.", "source_refs": [{"source_doc": "RFP.pdf", "page": 10}]},
        {"req_id": "REQ-2", "category": "Mandatory", "description": "The contractor must submit proof of valid WCB insurance coverage.", "source_refs": [{"source_doc": "Tender.pdf", "page": 12}]},
        {"req_id": "REQ-3", "category": "Mandatory", "description": "The contractor must submit proof of current WCB insurance coverage.", "source_refs": [{"source_doc": "Annex.pdf", "page": 3}]},
        {"req_id": "REQ-4", "category": "Rated", "description": "Describe your firm's quality management system.", "source_refs": []},
    ]
    clustered = us.cluster_near_duplicate_requirements(reqs)
    # The 3 WCB mandatory items cluster into 1 representative
    assert len(clustered) == 2
    wcb_cluster = next(r for r in clustered if "WCB" in r["description"])
    assert wcb_cluster["cluster_count"] == 3
    assert len(wcb_cluster["source_refs"]) == 3
    assert set(wcb_cluster["cluster_member_ids"]) == {"REQ-1", "REQ-2", "REQ-3"}


def test_material_variations_are_never_clustered():
    # 1. Deadline variation
    req1 = {"req_id": "D1", "category": "Mandatory", "description": "Submit proposal before 2026-10-19."}
    req2 = {"req_id": "D2", "category": "Mandatory", "description": "Submit proposal before 2026-10-22."}
    assert len(us.cluster_near_duplicate_requirements([req1, req2])) == 2

    # 2. Threshold variation
    req3 = {"req_id": "T1", "category": "Rated", "description": "Must achieve a minimum score of 70%."}
    req4 = {"req_id": "T2", "category": "Rated", "description": "Must achieve a minimum score of 80%."}
    assert len(us.cluster_near_duplicate_requirements([req3, req4])) == 2

    # 3. Quantity variation
    req5 = {"req_id": "Q1", "category": "Mandatory", "description": "Provide 3 comparable project references."}
    req6 = {"req_id": "Q2", "category": "Mandatory", "description": "Provide 5 comparable project references."}
    assert len(us.cluster_near_duplicate_requirements([req5, req6])) == 2

    # 4. Mandatory qualifier variation (must vs should)
    req7 = {"req_id": "M1", "category": "Technical", "description": "The proponent must provide an executive summary."}
    req8 = {"req_id": "M2", "category": "Technical", "description": "The proponent should provide an executive summary."}
    assert len(us.cluster_near_duplicate_requirements([req7, req8])) == 2

    # 5. Price variation
    req9 = {"req_id": "P1", "category": "Financial", "description": "Provide fixed fee under $150,000."}
    req10 = {"req_id": "P2", "category": "Financial", "description": "Provide fixed fee under $200,000."}
    assert len(us.cluster_near_duplicate_requirements([req9, req10])) == 2

    # 6. Exception clause variation
    req11 = {"req_id": "E1", "category": "Commercial", "description": "All work must be performed on site."}
    req12 = {"req_id": "E2", "category": "Commercial", "description": "All work must be performed on site, except for planning sessions."}
    assert len(us.cluster_near_duplicate_requirements([req11, req12])) == 2


def test_consistent_excerpt_bounding_across_all_sections():
    huge_text = "Verbatim contract text from the buyer. " * 50  # ~2000 chars
    normalized_facts = {
        "requirements": [
            {"req_id": f"R-{i}", "category": "Mandatory", "description": f"Requirement {i}: {huge_text}",
             "source_refs": [{"source_doc": "RFP.pdf", "excerpt": huge_text}]}
            for i in range(10)
        ],
        "deliverables": [
            {"deliv_id": "DEL-1", "description": huge_text, "source_refs": [{"excerpt": huge_text}]}
        ],
        "commercial_clauses": [
            {"clause_id": "COM-1", "source_fact": huge_text, "source_refs": [{"excerpt": huge_text}]}
        ],
        "contract_risks": [
            {"risk_id": "RSK-1", "description": huge_text, "mitigation": huge_text}
        ],
        "evaluation_criteria": [
            {"criterion": "Technical", "description": huge_text}
        ],
        "submission_rules": [
            {"rule_id": "SUB-1", "description": huge_text}
        ],
        "dates": [
            {"milestone": "Closing", "source_text": huge_text}
        ],
    }

    context = us.build_scalable_stage_d_context(normalized_facts, [], excerpt_cap=200)

    # Check that excerpt bounds are applied across ALL sections
    assert len(context["requirements"]["mandatory"][0]["description"]) <= 210
    assert len(context["requirements"]["mandatory"][0]["source_refs"][0]["excerpt"]) <= 210
    assert len(context["deliverables"][0]["description"]) <= 210
    assert len(context["commercial_clauses"][0]["source_fact"]) <= 210
    assert len(context["contract_risks"][0]["description"]) <= 210
    assert len(context["evaluation_criteria"][0]["description"]) <= 210
    assert len(context["submission_rules"][0]["description"]) <= 210
    assert len(context["dates"][0]["source_text"]) <= 210


def test_british_council_scale_fixture_remains_analyzable():
    """Simulate British Council scale (559 requirements, 8 documents) without context explosion."""
    # Build 559 requirements with repetitive boilerplate patterns typical of the 8-document corpus
    raw_reqs = []
    for i in range(559):
        # 10 recurring boilerplate clauses repeated across multiple documents
        boilerplate_group = i % 10
        raw_reqs.append({
            "req_id": f"BC-REQ-{i}",
            "category": "Mandatory" if i % 2 == 0 else "Rated",
            "description": f"Standard clause {boilerplate_group}: The provider must adhere to British Council standard operating procedures and security guidelines.",
            "source_refs": [{"source_doc": f"Doc_{(i % 8) + 1}.pdf", "page": (i % 20) + 1, "excerpt": "Long excerpt repetition " * 20}],
        })

    normalized_facts = {
        "requirements": raw_reqs,
        "evaluation_criteria": [{"criterion": f"Criterion {i}", "description": "Evaluation text"} for i in range(20)],
        "deliverables": [{"deliv_id": f"DEL-{i}", "description": "Deliverable text"} for i in range(30)],
        "commercial_clauses": [{"clause_id": f"COM-{i}", "source_fact": "Commercial term"} for i in range(40)],
        "submission_rules": [{"rule_id": f"SUB-{i}", "description": "Submission rule"} for i in range(25)],
    }

    context = us.build_scalable_stage_d_context(normalized_facts, [], excerpt_cap=300, apply_clustering=True)
    serialized = json.dumps(context)

    # In the live failure report, the serialized context size was 1,045,967 characters (exceeding 580,000 limit)
    # With clustering and consistent bounding, size is reduced by > 80% while retaining 100% of requirement integrity
    assert len(serialized) < 250_000, f"Serialized context size was {len(serialized)}, expected < 250,000"
    assert context["context_integrity"]["source_requirement_count"] == 559
    assert context["context_integrity"]["omitted_requirement_count"] == 0
