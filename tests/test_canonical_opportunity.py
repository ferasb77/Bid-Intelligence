import copy
import itertools

from canonical_opportunity import (
    SCHEMA_VERSION, apply_authoritative_values, apply_legacy_conflict_fallback, build_canonical_opportunity,
    compact_stage_d_summary, remove_authoritative_values_for_validation,
    resolve_canonical_opportunity,
)


def metadata(*names):
    texts = {}
    for name in names:
        texts[name] = f"[[SOURCE: {name} | PAGE: 1]]\nTender Alpha Buyer Corp SOL-7 2030-01-02 2030-01-01 CAD 1000"
    return {"files": list(names), "doc_metadata": {n: {"page_count": 1} for n in names}, "doc_texts": texts}


def obs(kind, value, doc="a.pdf", family="IDENTITY", **extra):
    return {"family": family, "semantic_kind": kind, "original_value": value, "source_doc": doc,
            "source_refs": [{"source_doc": doc, "page": 1, "excerpt": str(value)}], **extra}


def resolved(facts, meta=None):
    meta = meta or metadata("a.pdf")
    return resolve_canonical_opportunity(build_canonical_opportunity(facts, meta))


def test_schema_and_repeated_agreement_preserve_both_sources():
    facts = [{"typed_observations": [obs("OPPORTUNITY_TITLE", "Tender Alpha", "a.pdf")]},
             {"typed_observations": [obs("OPPORTUNITY_TITLE", "Tender Alpha", "b.pdf")]}]
    c = resolved(facts, metadata("a.pdf", "b.pdf"))
    assert c["schema_version"] == SCHEMA_VERSION
    assert len(c["observations"]) == 2
    assert c["resolved"]["title"]["status"] == "RESOLVED"
    assert len(c["resolved"]["title"]["observation_ids"]) == 2


def test_document_title_and_reference_number_are_excluded():
    c = resolved([{"typed_observations": [obs("DOCUMENT_TITLE", "Tender Alpha"), obs("DOCUMENT_REFERENCE_NUMBER", "SOL-7")]}])
    assert c["resolved"]["title"]["status"] == "MISSING"
    assert c["resolved"]["file_number"]["status"] == "MISSING"


def test_conflicting_title_is_field_linked():
    c = resolved([{"typed_observations": [obs("OPPORTUNITY_TITLE", "Tender Alpha"), obs("OPPORTUNITY_TITLE", "Buyer Corp")]}])
    assert c["resolved"]["title"]["status"] == "CONFLICTED"
    assert c["conflicts"][0]["affected_fields"] == ["/resolved/title"]


def test_order_permutations_are_canonical():
    groups = [
        {"typed_observations": [obs("OPPORTUNITY_TITLE", "Tender Alpha", "a.pdf")]},
        {"typed_observations": [obs("BUYER_NAME", "Buyer Corp", "b.pdf")]},
        {"typed_observations": [obs("SOLICITATION_NUMBER", "SOL-7", "c.pdf")]},
    ]
    outputs = []
    for permutation in itertools.permutations(groups):
        outputs.append(resolved(list(permutation), metadata("a.pdf", "b.pdf", "c.pdf")))
    assert all(item == outputs[0] for item in outputs)


def test_same_deadline_agrees_and_distinct_deadlines_are_independent():
    facts = [{"typed_observations": [
        obs("SUBMISSION_DEADLINE", "2030-01-02", family="MILESTONE", date="2030-01-02"),
        obs("CLARIFICATION_DEADLINE", "2030-01-01", family="MILESTONE", date="2030-01-01"),
    ]}]
    c = resolved(facts)
    assert c["resolved"]["submission_deadline"]["value"]["date"] == "2030-01-02"
    assert c["resolved"]["clarification_deadline"]["value"]["date"] == "2030-01-01"


def test_submission_conflict_does_not_suppress_clarification():
    facts = [{"typed_observations": [
        obs("SUBMISSION_DEADLINE", "2030-01-02", family="MILESTONE", date="2030-01-02"),
        obs("SUBMISSION_DEADLINE", "2030-01-01", family="MILESTONE", date="2030-01-01"),
        obs("CLARIFICATION_DEADLINE", "2030-01-01", family="MILESTONE", date="2030-01-01"),
    ]}]
    c = resolved(facts)
    assert c["resolved"]["submission_deadline"]["status"] == "CONFLICTED"
    assert c["resolved"]["clarification_deadline"]["status"] == "RESOLVED"


def test_component_and_lot_deadlines_do_not_compete_for_headline():
    facts = [{"typed_observations": [
        obs("SUBMISSION_DEADLINE", "2030-01-02", family="MILESTONE", date="2030-01-02"),
        obs("SUBMISSION_DEADLINE", "2030-01-03", family="MILESTONE", date="2030-01-03", component="Pricing"),
        obs("SUBMISSION_DEADLINE", "2030-01-04", family="MILESTONE", date="2030-01-04", lot="Lot 2"),
    ]}]
    c = resolved(facts)
    assert c["resolved"]["submission_deadline"]["status"] == "RESOLVED"
    assert c["resolved"]["submission_deadline"]["value"]["date"] == "2030-01-02"
    assert len(c["observations"]) == 3


def test_fabricated_excerpt_is_retained_but_not_promoted():
    bad = obs("OPPORTUNITY_TITLE", "Fabricated words")
    c = resolved([{"typed_observations": [bad]}])
    assert len(c["observations"]) == 1
    assert c["observations"][0]["provenance_status"] == "PARTIAL"
    assert c["resolved"]["title"]["status"] == "UNVERIFIED"


def test_fabricated_locator_is_not_verified():
    bad = obs("OPPORTUNITY_TITLE", "Tender Alpha")
    bad["source_refs"][0]["page"] = 9
    c = resolved([{"typed_observations": [bad]}])
    assert c["observations"][0]["provenance_status"] != "VERIFIED"


def test_money_keeps_ceiling_separate_and_currency_neutral():
    facts = [{"typed_observations": [
        obs("ESTIMATED_CONTRACT_VALUE", "1000", family="MONETARY", amount="1000", currency="CAD", tax_basis="EXCLUSIVE"),
        obs("FRAMEWORK_CEILING", "1000", family="MONETARY", amount="1000", currency="USD"),
        obs("EVALUATION_SCENARIO_VALUE", "1000", family="MONETARY", amount="1000", currency="CAD"),
    ]}]
    c = resolved(facts)
    assert c["resolved"]["headline_value"]["value"]["currency"] == "CAD"
    out = apply_authoritative_values({"bid": {"value_cad": 7}, "brief": {}}, c)
    assert out["bid"]["value_cad"] is None
    assert len([o for o in c["observations"] if o["family"] == "MONETARY"]) == 3


def test_mechanics_are_atomic_and_tier_one_conservative():
    facts = [{"typed_observations": [
        obs("FRAMEWORK", "Framework", family="PROCUREMENT_MECHANIC"),
        obs("MULTIPLE_SUPPLIER_AWARD", "multiple", family="PROCUREMENT_MECHANIC"),
        obs("CALL_OFF", "call off", family="PROCUREMENT_MECHANIC"),
        obs("NO_GUARANTEED_VOLUME", "no guaranteed volume", family="PROCUREMENT_MECHANIC"),
    ]}]
    meta = metadata("a.pdf")
    meta["doc_texts"]["a.pdf"] += " Framework multiple call off no guaranteed volume"
    c = resolved(facts, meta)
    assert c["resolved"]["opportunity_type"]["status"] == "NOT_CLASSIFIED"
    assert c["resolved"]["procurement_model"]["value"] == "Multi-vendor Call-off"
    assert len(compact_stage_d_summary(c)["verified_mechanics"]) == 4


def test_duplicate_physical_occurrence_collapses_with_occurrences():
    item = obs("OPPORTUNITY_TITLE", "Tender Alpha")
    c = resolved([{"typed_observations": [copy.deepcopy(item), copy.deepcopy(item)]}])
    assert len(c["observations"]) == 1
    assert c["observations"][0]["extraction_occurrences"][0]["count"] == 2


def test_model_copies_of_authoritative_values_are_removed_before_validation():
    c = resolved([{"typed_observations": [obs("OPPORTUNITY_TITLE", "Tender Alpha")]}])
    response = {"synthesis": {"bid": {"title": "Tender Alpha"}, "brief": {}}, "citations": []}
    cleaned = remove_authoritative_values_for_validation(response, c)
    assert cleaned["synthesis"]["bid"]["title"] is None
    assert response["synthesis"]["bid"]["title"] == "Tender Alpha"


def test_exact_marker_locator_matching_adversarial_cases():
    text = "[[SOURCE: a.pdf | PAGE: 10]]\nwrong Tender Alpha\n[[SOURCE: a.pdf | PAGE: 1]]\nright Buyer Corp"
    meta = {"files": ["a.pdf"], "doc_metadata": {"a.pdf": {"page_count": 10}}, "doc_texts": {"a.pdf": text}}
    c = resolved([{"typed_observations": [obs("OPPORTUNITY_TITLE", "Tender Alpha")]}], meta)
    assert c["observations"][0]["provenance_status"] != "VERIFIED"
    assert resolved([{"typed_observations": [obs("BUYER_NAME", "Buyer Corp")]}], meta)["resolved"]["client"]["status"] == "RESOLVED"


def test_rows_are_structural_ranges_not_digit_substrings():
    text = "[[SOURCE: a.pdf | SHEET: Data | ROWS: 10-20]]\nTender Alpha"
    meta = {"files": ["a.pdf"], "doc_metadata": {"a.pdf": {"sheets": ["Data"]}}, "doc_texts": {"a.pdf": text}}
    item = obs("OPPORTUNITY_TITLE", "Tender Alpha"); item["source_refs"][0].update(sheet="Data", row=1); item["source_refs"][0].pop("page")
    assert resolved([{"typed_observations": [item]}], meta)["observations"][0]["provenance_status"] != "VERIFIED"
    item["source_refs"][0]["row"] = 10
    assert resolved([{"typed_observations": [item]}], meta)["observations"][0]["provenance_status"] == "VERIFIED"


def test_stage_a_shaped_source_supersession_resolves_after_ids_exist():
    old = obs("SUBMISSION_DEADLINE", "2030-01-01", doc="old.pdf", family="MILESTONE", date="2030-01-01")
    new = obs("SUBMISSION_DEADLINE", "2030-01-02", doc="new.pdf", family="MILESTONE", date="2030-01-02")
    new["supersession"] = {"basis": "EXPLICIT_EXTENSION", "target_family": "MILESTONE",
        "target_semantic_kind": "SUBMISSION_DEADLINE", "old_value": "2030-01-01", "new_value": "2030-01-02", "scope": {},
        "source_refs": [{"source_doc": "new.pdf", "page": 1, "excerpt": "2030-01-01 2030-01-02"}]}
    meta = metadata("old.pdf", "new.pdf"); meta["doc_texts"]["new.pdf"] += " 2030-01-01 2030-01-02"
    c = resolved([{"typed_observations": [old]}, {"typed_observations": [new]}], meta)
    assert {o["original_value"]: o["supersession_state"] for o in c["observations"]} == {"2030-01-01": "SUPERSEDED", "2030-01-02": "ACTIVE"}
    assert c["resolved"]["submission_deadline"]["value"]["date"] == "2030-01-02"


def test_different_later_date_without_supersession_conflicts():
    c = resolved([{"typed_observations": [obs("SUBMISSION_DEADLINE", "2030-01-01", family="MILESTONE", date="2030-01-01"),
                                          obs("SUBMISSION_DEADLINE", "2030-01-02", family="MILESTONE", date="2030-01-02")]}])
    assert c["resolved"]["submission_deadline"]["status"] == "CONFLICTED"


def test_partial_coverage_uses_only_field_specific_legacy_fallback():
    c = resolved([{"typed_observations": [obs("CLARIFICATION_DEADLINE", "2030-01-01", family="MILESTONE", date="2030-01-01")]}])
    c = apply_legacy_conflict_fallback(c, [{"conflict_id": "legacy", "conflict_type": "DATE_CONFLICT", "topic": "Submission deadline"},
                                            {"conflict_id": "env", "conflict_type": "ENVELOPE_CONFLICT", "topic": "Envelope"}])
    assert c["resolved"]["submission_deadline"]["status"] == "CONFLICTED"
    assert c["resolved"]["clarification_deadline"]["status"] == "RESOLVED"


def test_single_typed_submission_value_cannot_override_legacy_disagreement():
    c = resolved([{"typed_observations": [obs("SUBMISSION_DEADLINE", "2030-10-01", family="MILESTONE", date="2030-10-01")]}],
                 {**metadata("a.pdf"), "doc_texts": {"a.pdf": "[[SOURCE: a.pdf | PAGE: 1]]\n2030-10-01"}})
    c = apply_legacy_conflict_fallback(c, [{"conflict_id": "legacy-submit", "conflict_type": "DATE_CONFLICT",
        "topic": "Submission deadline", "source_a": {"text": "2030-10-01"}, "source_b": {"text": "2030-10-03"}}])
    assert c["resolved"]["submission_deadline"]["status"] == "CONFLICTED"
    assert c["resolved"]["submission_deadline"]["value"] is None


def test_envelope_and_bilingual_conflicts_suppress_no_dates_or_term():
    items = [obs("SUBMISSION_DEADLINE", "2030-10-01", family="MILESTONE", date="2030-10-01"),
             obs("CLARIFICATION_DEADLINE", "2030-09-20", family="MILESTONE", date="2030-09-20"),
             obs("INITIAL_DURATION", "24 months", family="CONTRACT_TERM", duration=24, unit="months")]
    meta = metadata("a.pdf"); meta["doc_texts"]["a.pdf"] += " 2030-10-01 2030-09-20 24 months"
    c = resolved([{"typed_observations": items}], meta)
    c = apply_legacy_conflict_fallback(c, [{"conflict_id": "env", "conflict_type": "ENVELOPE_CONFLICT", "topic": "Envelope"},
                                            {"conflict_id": "lang", "conflict_type": "BILINGUAL_SCOPE_CONFLICT", "topic": "Bilingual scope"}])
    assert c["resolved"]["submission_deadline"]["status"] == "RESOLVED"
    assert c["resolved"]["clarification_deadline"]["status"] == "RESOLVED"
    assert c["resolved"]["contract_term"]["status"] == "RESOLVED"


def test_verified_supersession_accounts_for_corresponding_legacy_disagreement():
    old = obs("SUBMISSION_DEADLINE", "2030-10-01", doc="old.pdf", family="MILESTONE", date="2030-10-01")
    new = obs("SUBMISSION_DEADLINE", "2030-10-03", doc="new.pdf", family="MILESTONE", date="2030-10-03")
    new["supersession"] = {"basis": "EXPLICIT_EXTENSION", "target_family": "MILESTONE",
        "target_semantic_kind": "SUBMISSION_DEADLINE", "old_value": "2030-10-01", "new_value": "2030-10-03", "scope": {},
        "source_refs": [{"source_doc": "new.pdf", "page": 1, "excerpt": "2030-10-01 to 2030-10-03"}]}
    meta = metadata("old.pdf", "new.pdf"); meta["doc_texts"]["new.pdf"] += " 2030-10-01 to 2030-10-03"
    c = resolved([{"typed_observations": [old]}, {"typed_observations": [new]}], meta)
    c = apply_legacy_conflict_fallback(c, [{"conflict_id": "legacy-submit", "conflict_type": "DATE_CONFLICT",
        "topic": "Submission deadline", "source_a": {"text": "2030-10-01"}, "source_b": {"text": "2030-10-03"}}])
    assert c["resolved"]["submission_deadline"]["status"] == "RESOLVED"
    assert c["resolved"]["submission_deadline"]["value"]["date"] == "2030-10-03"
    assert c["coverage"]["submission_deadline"]["legacy_conflict_accounted_by_supersession"] is True


def test_repeatable_extensions_and_human_display():
    items = [obs("INITIAL_DURATION", "24 months", family="CONTRACT_TERM", duration=24, unit="months"),
             obs("EXTENSION_OPTION", "12 months", family="CONTRACT_TERM", duration=12, unit="months", optional=True),
             obs("EXTENSION_OPTION", "6 months", family="CONTRACT_TERM", duration=6, unit="months", optional=True, conditions="approval")]
    meta = metadata("a.pdf"); meta["doc_texts"]["a.pdf"] += " 24 months 12 months 6 months approval"
    c = resolved([{"typed_observations": items}], meta)
    assert c["resolved"]["contract_term"]["status"] == "RESOLVED"
    display = apply_authoritative_values({"bid": {}, "brief": {}}, c)["brief"]["contract_term"]
    assert "Optional extension: 12 months" in display and "Optional extension: 6 months subject to approval" in display
    assert "{" not in display


def test_scoped_term_display_retains_scope_qualifier():
    """A term observation scoped to one lot/component is not an
    opportunity-wide fact. The formatted display must say so, or a reader
    (including Stage D's authoritative brief.contract_term) would take a
    single-category value as if it applied to the whole opportunity."""
    items = [obs("INITIAL_DURATION", "12 weeks", family="CONTRACT_TERM", duration=12, unit="weeks",
                 component="HR Advisory")]
    meta = metadata("a.pdf"); meta["doc_texts"]["a.pdf"] += " 12 weeks HR Advisory"
    c = resolved([{"typed_observations": items}], meta)
    assert c["resolved"]["contract_term"]["status"] == "RESOLVED"
    assert c["resolved"]["contract_term"]["value"][0]["scope"] == {"component": "HR Advisory"}
    display = apply_authoritative_values({"bid": {}, "brief": {}}, c)["brief"]["contract_term"]
    assert display == "Initial term: 12 weeks (component: HR Advisory)"


def test_unscoped_term_display_has_no_scope_suffix():
    """An opportunity-wide term (no scope) must not gain a spurious suffix --
    the fix is additive only when a real scope dict is present."""
    items = [obs("INITIAL_DURATION", "3 years", family="CONTRACT_TERM", duration=3, unit="years")]
    meta = metadata("a.pdf"); meta["doc_texts"]["a.pdf"] += " 3 years"
    c = resolved([{"typed_observations": items}], meta)
    display = apply_authoritative_values({"bid": {}, "brief": {}}, c)["brief"]["contract_term"]
    assert display == "Initial term: 3 years"
    assert "(" not in display


def test_same_identified_option_disagreement_conflicts():
    items = [obs("EXTENSION_OPTION", "12 months", family="CONTRACT_TERM", duration=12, unit="months", option_sequence="1"),
             obs("EXTENSION_OPTION", "6 months", family="CONTRACT_TERM", duration=6, unit="months", option_sequence="1")]
    meta = metadata("a.pdf"); meta["doc_texts"]["a.pdf"] += " 12 months 6 months"
    assert resolved([{"typed_observations": items}], meta)["resolved"]["contract_term"]["status"] == "CONFLICTED"


def test_invalid_family_kind_and_dates_are_retained_as_diagnostics_or_unparsed():
    malformed = obs("NOT_A_REAL_KIND", "x")
    invalid_date = obs("SUBMISSION_DEADLINE", "2030-02-29", family="MILESTONE", date="2030-02-29")
    c = resolved([{"typed_observations": [malformed, invalid_date]}])
    assert c["integrity_diagnostics"]["invalid_observations"][0]["validation_state"] == "INVALID_FAMILY_KIND"
    assert c["observations"][0]["normalization_state"] == "UNPARSED"
    assert c["resolved"]["submission_deadline"]["status"] == "UNVERIFIED"


def test_valid_leap_date_time_and_no_timezone_inference():
    item = obs("SUBMISSION_DEADLINE", "2032-02-29", family="MILESTONE", date="2032-02-29", time="23:59")
    meta = metadata("a.pdf"); meta["doc_texts"]["a.pdf"] += " 2032-02-29"
    c = resolved([{"typed_observations": [item]}], meta)
    assert c["resolved"]["submission_deadline"]["value"]["timezone"] is None
    item["time"] = "25:00"
    assert resolved([{"typed_observations": [item]}], meta)["observations"][0]["normalization_state"] == "UNPARSED"


def test_headline_deadline_precision_requires_day_level_validity():
    cases = [
        ("DATE", "2032-02-29", None, "RESOLVED"),
        ("DATETIME", "2032-02-29", "09:30", "RESOLVED"),
        ("DATETIME", "2032-02-30", "09:30", "UNVERIFIED"),
        ("DATETIME", "2032-02-29", "29:30", "UNVERIFIED"),
        ("MONTH", "2032-02", None, "UNVERIFIED"),
        ("YEAR", "2032", None, "UNVERIFIED"),
        ("UNKNOWN", "early 2032", None, "UNVERIFIED"),
    ]
    for precision, value, time, status in cases:
        item = obs("SUBMISSION_DEADLINE", value, family="MILESTONE", date=value, precision=precision)
        if time is not None: item["time"] = time
        meta = metadata("a.pdf"); meta["doc_texts"]["a.pdf"] += " " + value
        c = resolved([{"typed_observations": [item]}], meta)
        assert c["resolved"]["submission_deadline"]["status"] == status
        assert len(c["observations"]) == 1


def test_datetime_requires_explicit_valid_time():
    item = obs("CLARIFICATION_DEADLINE", "2032-02-29", family="MILESTONE", date="2032-02-29", precision="DATETIME")
    meta = metadata("a.pdf"); meta["doc_texts"]["a.pdf"] += " 2032-02-29"
    c = resolved([{"typed_observations": [item]}], meta)
    assert c["observations"][0]["normalization_state"] == "UNPARSED"
    assert c["resolved"]["clarification_deadline"]["status"] == "UNVERIFIED"


def test_observation_order_does_not_change_authoritative_object_or_digest():
    items = [obs("OPPORTUNITY_TITLE", "Tender Alpha"), obs("BUYER_NAME", "Buyer Corp"), obs("SOLICITATION_NUMBER", "SOL-7")]
    outputs = [resolved([{"typed_observations": list(p)}]) for p in itertools.permutations(items)]
    assert all(x == outputs[0] for x in outputs)


def test_buyer_precedes_distinct_issuing_authority_and_issuer_is_fallback():
    buyer = obs("BUYER_NAME", "Buyer Corp")
    issuer = obs("ISSUING_AUTHORITY", "Tender Alpha")
    c = resolved([{"typed_observations": [buyer, issuer]}])
    assert c["resolved"]["client"]["value"] == "Buyer Corp"
    fallback = resolved([{"typed_observations": [issuer]}])
    assert fallback["resolved"]["client"]["resolution_basis"] == "ISSUING_AUTHORITY_FALLBACK"


def test_excel_multi_letter_cell_ranges_use_numeric_column_order():
    def provenance(marker_range, requested):
        text = f"[[SOURCE: a.xlsx | SHEET: Data | CELLS: {marker_range}]]\nTender Alpha"
        meta = {"files": ["a.xlsx"], "doc_metadata": {"a.xlsx": {"sheets": ["Data"]}}, "doc_texts": {"a.xlsx": text}}
        item = obs("OPPORTUNITY_TITLE", "Tender Alpha", doc="a.xlsx")
        item["source_refs"][0] = {"source_doc": "a.xlsx", "sheet": "Data", "cell": requested, "excerpt": "Tender Alpha"}
        return resolved([{"typed_observations": [item]}], meta)["observations"][0]["provenance_status"]
    assert provenance("A1:Z10", "AA5") != "VERIFIED"
    assert provenance("A1:AA10", "Z5") == "VERIFIED"
    assert provenance("Z1:AB10", "AA5") == "VERIFIED"
    assert provenance("AA1:AB10", "Z5") != "VERIFIED"


def test_term_dates_exclude_unparsed_and_display_valid_values():
    valid = [obs("COMMENCEMENT_DATE", "2030-01-01", family="CONTRACT_TERM", date="2030-01-01", precision="DATE"),
             obs("END_DATE", "2030-12-31", family="CONTRACT_TERM", date="2030-12-31", precision="DATE")]
    meta = metadata("a.pdf"); meta["doc_texts"]["a.pdf"] += " 2030-01-01 2030-12-31"
    c = resolved([{"typed_observations": valid}], meta)
    display = apply_authoritative_values({"bid": {}, "brief": {}}, c)["brief"]["contract_term"]
    assert "Commencement date: 2030-01-01" in display and "End date: 2030-12-31" in display
    assert "{" not in display
    for kind, bad in (("COMMENCEMENT_DATE", "2030-02-30"), ("END_DATE", "not-a-date")):
        item = obs(kind, bad, family="CONTRACT_TERM", date=bad, precision="DATE")
        bad_meta = metadata("a.pdf"); bad_meta["doc_texts"]["a.pdf"] += " " + bad
        invalid = resolved([{"typed_observations": [item]}], bad_meta)
        assert invalid["observations"][0]["normalization_state"] == "UNPARSED"
        assert invalid["resolved"]["contract_term"]["status"] == "UNVERIFIED"


def test_partial_precision_term_dates_remain_human_readable():
    items = [obs("COMMENCEMENT_DATE", "2030-01", family="CONTRACT_TERM", date="2030-01", precision="MONTH"),
             obs("END_DATE", "2031", family="CONTRACT_TERM", date="2031", precision="YEAR")]
    meta = metadata("a.pdf"); meta["doc_texts"]["a.pdf"] += " 2030-01 2031"
    display = apply_authoritative_values({"bid": {}, "brief": {}}, resolved([{"typed_observations": items}], meta))["brief"]["contract_term"]
    assert "Commencement date: 2030-01" in display and "End date: 2031" in display and "{" not in display


def test_mechanic_classification_support_is_decisive_and_scope_aware():
    meta = metadata("a.pdf"); meta["doc_texts"]["a.pdf"] += " single multiple call off rate cap milestone payment"
    single = resolved([{"typed_observations": [obs("SINGLE_SUPPLIER_AWARD", "single", family="PROCUREMENT_MECHANIC"),
        obs("RATE_CAP", "rate cap", family="PROCUREMENT_MECHANIC"),
        obs("MILESTONE_PAYMENT", "milestone payment", family="MONETARY", amount="1", currency="CAD")]}], meta)
    model = single["resolved"]["procurement_model"]
    assert model["value"] == "Single Contract" and len(model["observation_ids"]) == 1
    decisive = next(o for o in single["observations"] if o["observation_id"] in model["observation_ids"])
    assert decisive["family"] == "PROCUREMENT_MECHANIC" and decisive["semantic_kind"] == "SINGLE_SUPPLIER_AWARD"

    multi = resolved([{"typed_observations": [obs("MULTIPLE_SUPPLIER_AWARD", "multiple", family="PROCUREMENT_MECHANIC"),
        obs("CALL_OFF", "call off", family="PROCUREMENT_MECHANIC"), obs("RATE_CAP", "rate cap", family="PROCUREMENT_MECHANIC")]}], meta)
    assert multi["resolved"]["procurement_model"]["value"] == "Multi-vendor Call-off"
    support_kinds = {o["semantic_kind"] for o in multi["observations"] if o["observation_id"] in multi["resolved"]["procurement_model"]["observation_ids"]}
    assert support_kinds == {"MULTIPLE_SUPPLIER_AWARD", "CALL_OFF"}

    scoped_items = [obs("SINGLE_SUPPLIER_AWARD", "single", family="PROCUREMENT_MECHANIC", lot="1"),
                    obs("MULTIPLE_SUPPLIER_AWARD", "multiple", family="PROCUREMENT_MECHANIC", lot="2")]
    scoped = resolved([{"typed_observations": scoped_items}], meta)
    assert scoped["resolved"]["procurement_model"]["status"] == "NOT_CLASSIFIED"


def test_unscoped_single_and_multiple_awards_conflict_without_tier2_escape():
    meta = metadata("a.pdf"); meta["doc_texts"]["a.pdf"] += " single multiple"
    c = resolved([{"typed_observations": [obs("SINGLE_SUPPLIER_AWARD", "single", family="PROCUREMENT_MECHANIC"),
        obs("MULTIPLE_SUPPLIER_AWARD", "multiple", family="PROCUREMENT_MECHANIC")]}], meta)
    result = c["resolved"]["procurement_model"]
    assert result["status"] == "CONFLICTED" and result["value"] is None
    assert result["stage_d_tier2_permitted"] is False
    assert any(x["affected_fields"] == ["/resolved/procurement_model"] for x in c["conflicts"])


# ── Contract-term candidacy and scope audit regression tests ────────────────
#
# A real-corpus finding: a source marker that only publishes page granularity
# (true for every PDF in the Bank of Canada corpus around these pages) cannot
# corroborate a ref's more precise `section` citation, and _locator_matches()
# used to treat that as an outright mismatch -- rejecting genuinely valid,
# page-locatable evidence for citing MORE precision than the marker system
# happens to publish. Separately, _validate_ref()'s excerpt-grounding check
# used plain _norm() (collapse whitespace to one space), which does not
# tolerate two extremely common PDF-extraction artifacts: a hyphenated
# line-wrap ("one-\nyear" -> "one- year") and a missing space after label
# punctuation ("Duration:3 years"). Both defects independently caused a
# genuinely well-evidenced, page/section-cited, real-text excerpt to be
# downgraded from VERIFIED to PARTIAL, excluding it from every resolver's
# VERIFIED-only candidacy gate (contract_term, procurement_model, ...).

def test_section_citation_against_a_page_only_marker_still_verifies():
    """Citing extra precision (a section number) must never be worse than
    omitting it. A page-only marker cannot corroborate or refute section, so
    it must not block verification of an otherwise well-grounded excerpt."""
    meta = metadata("a.pdf")
    meta["doc_texts"]["a.pdf"] += " The term of each agreement will be three years."
    items = [obs("INITIAL_DURATION", "three years", family="CONTRACT_TERM", duration=3, unit="years",
                 source_refs=[{"source_doc": "a.pdf", "page": 1, "section": "4.2",
                              "excerpt": "The term of each agreement will be three years."}])]
    c = resolved([{"typed_observations": items}], meta)
    o = next(x for x in c["observations"] if x["family"] == "CONTRACT_TERM")
    assert o["provenance_status"] == "VERIFIED"


def test_section_mismatch_against_a_real_section_marker_still_rejected():
    """The relaxation is narrow: when the marker DOES publish a section and
    it genuinely disagrees with the ref, that is a real mismatch and must
    still fail to ground -- this is not a blanket bypass of section checks."""
    meta = metadata("a.pdf")
    meta["doc_texts"]["a.pdf"] = ("[[SOURCE: a.pdf | PAGE: 1 | SECTION: 3.1]]\n"
                                  "The term of each agreement will be three years.")
    items = [obs("INITIAL_DURATION", "three years", family="CONTRACT_TERM", duration=3, unit="years",
                 source_refs=[{"source_doc": "a.pdf", "page": 1, "section": "4.2",
                              "excerpt": "The term of each agreement will be three years."}])]
    c = resolved([{"typed_observations": items}], meta)
    o = next(x for x in c["observations"] if x["family"] == "CONTRACT_TERM")
    assert o["provenance_status"] == "PARTIAL"


def test_hyphenated_line_wrap_excerpt_still_grounds():
    """A word hyphenated across a PDF line wrap ('one-\\nyear') must ground
    against a clean excerpt ('one-year') -- the words are identical, only
    incidental reflow whitespace differs."""
    meta = metadata("a.pdf")
    meta["doc_texts"]["a.pdf"] += " with the option to extend for up to two additional one-\nyear terms."
    items = [obs("EXTENSION_OPTION", "one year", family="CONTRACT_TERM", duration=1, unit="years", optional=True,
                 source_refs=[{"source_doc": "a.pdf", "page": 1,
                              "excerpt": "with the option to extend for up to two additional one-year terms."}])]
    c = resolved([{"typed_observations": items}], meta)
    o = next(x for x in c["observations"] if x["family"] == "CONTRACT_TERM")
    assert o["provenance_status"] == "VERIFIED"


def test_missing_space_after_punctuation_still_grounds():
    """A label/value pair extracted from a PDF with no space after the colon
    ('Duration:3 years') must ground against a naturally-spaced excerpt
    ('Duration: 3 years') -- same words, incidental layout whitespace only."""
    meta = metadata("a.pdf")
    meta["doc_texts"]["a.pdf"] += " Purchase Type\nDuration:3 years\nOption: 2 years"
    items = [obs("INITIAL_DURATION", "3 years", family="CONTRACT_TERM", duration=3, unit="years",
                 source_refs=[{"source_doc": "a.pdf", "page": 1, "excerpt": "Duration: 3 years"}])]
    c = resolved([{"typed_observations": items}], meta)
    o = next(x for x in c["observations"] if x["family"] == "CONTRACT_TERM")
    assert o["provenance_status"] == "VERIFIED"


def test_genuinely_absent_excerpt_still_fails_to_ground():
    """The whitespace tolerance must not become a license to fabricate --
    an excerpt whose actual words are not present anywhere in the source
    must remain unverified, not just cosmetically different."""
    meta = metadata("a.pdf")
    meta["doc_texts"]["a.pdf"] += " The engagement covers unrelated deliverables only."
    items = [obs("INITIAL_DURATION", "three years", family="CONTRACT_TERM", duration=3, unit="years",
                 source_refs=[{"source_doc": "a.pdf", "page": 1,
                              "excerpt": "The term of each agreement will be three years."}])]
    c = resolved([{"typed_observations": items}], meta)
    o = next(x for x in c["observations"] if x["family"] == "CONTRACT_TERM")
    assert o["provenance_status"] == "PARTIAL"


def test_scoped_and_unscoped_contract_terms_coexist_without_conflict():
    """An opportunity-wide term and a differently-scoped service-level
    duration are not the same canonical fact and must not compete for the
    same slot -- both should resolve, side by side, distinctly scoped."""
    meta = metadata("a.pdf")
    meta["doc_texts"]["a.pdf"] += " Overall term three years. HR Advisory engagement twelve weeks."
    items = [
        obs("INITIAL_DURATION", "three years", family="CONTRACT_TERM", duration=3, unit="years",
           source_refs=[{"source_doc": "a.pdf", "page": 1, "excerpt": "Overall term three years."}]),
        obs("INITIAL_DURATION", "twelve weeks", family="CONTRACT_TERM", duration=12, unit="weeks",
           component="HR Advisory",
           source_refs=[{"source_doc": "a.pdf", "page": 1, "excerpt": "HR Advisory engagement twelve weeks."}]),
    ]
    c = resolved([{"typed_observations": items}], meta)
    result = c["resolved"]["contract_term"]
    assert result["status"] == "RESOLVED"
    scopes = [item["scope"] for item in result["value"]]
    assert {} in scopes and {"component": "HR Advisory"} in scopes and len(scopes) == 2
    assert not c["conflicts"]


def test_same_scope_contract_term_shape_mismatch_conflicts():
    """Two verified, same-scope INITIAL_DURATION observations whose
    normalized_value shapes genuinely differ (one carries structured
    duration/unit, the other only a bare string) must not be silently
    assumed equivalent -- that would be inferring semantic identity beyond
    what the structured facts state. This must conflict, not corroborate."""
    meta = metadata("a.pdf")
    meta["doc_texts"]["a.pdf"] += " Duration: 3 years. Term of three years stated separately."
    items = [
        obs("INITIAL_DURATION", "3 years", family="CONTRACT_TERM",
           source_refs=[{"source_doc": "a.pdf", "page": 1, "excerpt": "Duration: 3 years."}]),
        obs("INITIAL_DURATION", "three years", family="CONTRACT_TERM", duration=3, unit="years",
           source_refs=[{"source_doc": "a.pdf", "page": 1, "excerpt": "Term of three years stated separately."}]),
    ]
    c = resolved([{"typed_observations": items}], meta)
    result = c["resolved"]["contract_term"]
    assert result["status"] == "CONFLICTED" and result["value"] is None
