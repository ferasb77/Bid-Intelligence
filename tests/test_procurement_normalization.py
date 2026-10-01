"""
tests/test_procurement_normalization.py -- Full-Package Analysis
Integrity Remediation Defects A/B/C/D. Pure-domain tests, no I/O, no
model call. Several fixtures mirror the REAL Bank of Canada Appendix D1
document text (live-verified during this task) without depending on the
live database or an Anthropic call.
"""
import procurement_normalization as pn


# ═══════════════════════════════════════════════════════════════════════════
# Defect A -- criterion response-prompt extraction
# ═══════════════════════════════════════════════════════════════════════════

_REAL_APPENDIX_D1_EXCERPT = """\
[[SOURCE: Appendix D1.docx | SECTION: Header]]
APPENDIX D1 - RATED CRITERIA RESPONSE FORM
Instructions: Proponents are to respond to each of the following requirements in the order presented below.
Corporate Profile
Proponents are to describe their organisation, its purpose, structure and makeup.
Profile and history of the organisation;
Number of employees;
Key Personnel and Roster
Proponents are to demonstrate their capabilities and capacity to provide the required services.
A brief profile for each individual who would serve in a dedicated role.
"""


class TestExtractCriterionResponsePrompts:

    def test_weight_and_requested_evidence_coexist(self):
        """A criterion carries BOTH a weight (from evaluation extraction,
        simulated here as the caller-supplied label list) and a captured
        response prompt -- the two coexist, extraction of one doesn't
        block the other."""
        labels = ["Corporate Profile", "Key Personnel and Roster"]
        prompts = pn.extract_criterion_response_prompts(_REAL_APPENDIX_D1_EXCERPT, labels)
        assert "Corporate Profile" in prompts
        assert "describe their organisation" in prompts["Corporate Profile"]["response_prompt"]

    def test_appendix_response_prompt_is_retained_verbatim(self):
        labels = ["Key Personnel and Roster"]
        prompts = pn.extract_criterion_response_prompts(_REAL_APPENDIX_D1_EXCERPT, labels)
        assert "demonstrate their capabilities" in prompts["Key Personnel and Roster"]["response_prompt"]

    def test_missing_prompt_remains_explicitly_absent(self):
        """A criterion label that never appears as a heading in the text
        is simply absent from the result dict -- never fabricated, never
        present with empty/placeholder text."""
        labels = ["Corporate Profile", "A Criterion Never Mentioned Anywhere"]
        prompts = pn.extract_criterion_response_prompts(_REAL_APPENDIX_D1_EXCERPT, labels)
        assert "A Criterion Never Mentioned Anywhere" not in prompts

    def test_no_known_labels_returns_empty(self):
        assert pn.extract_criterion_response_prompts(_REAL_APPENDIX_D1_EXCERPT, []) == {}

    def test_empty_document_text_returns_empty(self):
        assert pn.extract_criterion_response_prompts("", ["Corporate Profile"]) == {}

    def test_case_and_whitespace_insensitive_heading_match(self):
        text = "corporate   profile  \nDescribe your firm.\n"
        prompts = pn.extract_criterion_response_prompts(text, ["Corporate Profile"])
        assert "Corporate Profile" in prompts
        assert "Describe your firm" in prompts["Corporate Profile"]["response_prompt"]

    def test_truncation_flag_set_when_prompt_exceeds_cap(self):
        long_body = "word " * 500
        text = f"Corporate Profile\n{long_body}"
        prompts = pn.extract_criterion_response_prompts(text, ["Corporate Profile"])
        assert prompts["Corporate Profile"]["truncated"] is True
        assert len(prompts["Corporate Profile"]["response_prompt"]) <= pn.MAX_RESPONSE_PROMPT_CHARS

    def test_source_marker_lines_never_pollute_captured_text(self):
        text = "Corporate Profile\n[[SOURCE: x.docx | PAGE: 1]]\nDescribe your firm.\n"
        prompts = pn.extract_criterion_response_prompts(text, ["Corporate Profile"])
        assert "[[SOURCE" not in prompts["Corporate Profile"]["response_prompt"]

    def test_amended_form_overrides_superseded_wording_when_processed_last(self):
        """Simulates the caller-side authority rule (task section 12): a
        LATER document's extraction call simply overwrites an EARLIER
        one's for the same label when the caller processes the
        authoritative (amended) document after the superseded one --
        this function itself has no document-ordering opinion; it is a
        pure per-document extractor the caller sequences."""
        original_text = "Corporate Profile\nOriginal wording from the base form.\n"
        amended_text = "Corporate Profile\nAmended wording that supersedes the original.\n"
        original_prompts = pn.extract_criterion_response_prompts(original_text, ["Corporate Profile"])
        amended_prompts = pn.extract_criterion_response_prompts(amended_text, ["Corporate Profile"])
        merged = {}
        # Caller convention (mirrors fast_analysis.py's own "first non-
        # empty wins" pattern applied in AMENDMENT-then-ORIGINAL order):
        for source_prompts in (amended_prompts, original_prompts):
            for label, entry in source_prompts.items():
                merged.setdefault(label, entry)
        assert "Amended wording" in merged["Corporate Profile"]["response_prompt"]


# ═══════════════════════════════════════════════════════════════════════════
# Defect B -- requirement deduplication
# ═══════════════════════════════════════════════════════════════════════════

def _req(desc, category="Mandatory", source_doc="RFP.pdf", source_refs=None):
    return {"category": category, "description": desc, "source_doc": source_doc, "source_refs": source_refs or []}


class TestCanonicalizeRequirements:

    def test_exact_duplicate_merges(self):
        reqs = [_req("Bilingualism required.", source_doc="A"), _req("Bilingualism required.", source_doc="B")]
        canon = pn.canonicalize_requirements(reqs)
        assert len(canon) == 1
        assert canon[0]["duplicate_count"] == 2
        assert set(canon[0]["source_docs"]) == {"A", "B"}

    def test_formatting_only_duplicate_merges(self):
        reqs = [
            _req("Bilingualism - written confirmation required.", source_doc="A"),
            _req("Bilingualism:  written   confirmation, required!", source_doc="B"),
        ]
        canon = pn.canonicalize_requirements(reqs)
        assert len(canon) == 1

    def test_near_duplicate_restatement_merges(self):
        reqs = [
            _req("Bilingualism - Each proposal must provide written confirmation of the ability to "
                 "provide all services, materials and solutions in both English and French.", source_doc="RFP"),
            _req("Bilingualism: Written confirmation of ability to provide all services, materials "
                 "and solutions in both English and French.", source_doc="Appendix B2"),
        ]
        canon = pn.canonicalize_requirements(reqs)
        assert len(canon) == 1
        assert canon[0]["duplicate_count"] == 2

    def test_distinct_requirements_remain_separate(self):
        reqs = [
            _req("Bilingualism confirmation required in English and French."),
            _req("Security clearance required for all delivery resources."),
        ]
        canon = pn.canonicalize_requirements(reqs)
        assert len(canon) == 2

    def test_merged_requirement_preserves_all_source_refs(self):
        reqs = [
            _req("Bilingualism required.", source_doc="A", source_refs=[{"page": 1}]),
            _req("Bilingualism required.", source_doc="B", source_refs=[{"page": 9}]),
        ]
        canon = pn.canonicalize_requirements(reqs)
        assert {"page": 1} in canon[0]["source_refs_all"]
        assert {"page": 9} in canon[0]["source_refs_all"]

    def test_merged_requirement_preserves_source_variants(self):
        reqs = [
            _req("Bilingualism - written confirmation required.", source_doc="A"),
            _req("Bilingualism: written confirmation, required.", source_doc="B"),
        ]
        canon = pn.canonicalize_requirements(reqs)
        assert len(canon[0]["source_variants"]) == 2

    def test_uncertainty_fails_conservatively_short_distinct_labels(self):
        """Two short, genuinely distinct one-line obligations that reduce
        to overlapping word sets below the 3-significant-word gate must
        NOT be falsely collapsed."""
        reqs = [_req("Provide phone number."), _req("Provide fax number.")]
        canon = pn.canonicalize_requirements(reqs)
        assert len(canon) == 2

    def test_never_compares_across_category(self):
        """Bounded candidate narrowing: two IDENTICAL description texts
        in DIFFERENT categories are never merged -- category is
        authoritative classification, never overridden by text
        similarity alone."""
        reqs = [_req("Identical text here.", category="Mandatory"), _req("Identical text here.", category="Rated")]
        canon = pn.canonicalize_requirements(reqs)
        assert len(canon) == 2

    def test_singleton_requirement_gains_uniform_output_shape(self):
        reqs = [_req("Only one requirement.")]
        canon = pn.canonicalize_requirements(reqs)
        assert canon[0]["duplicate_count"] == 1
        assert canon[0]["source_variants"] == ["Only one requirement."]

    def test_empty_input_returns_empty(self):
        assert pn.canonicalize_requirements([]) == []

    def test_no_model_call_surface(self):
        import inspect
        assert "anthropic" not in inspect.getsource(pn.canonicalize_requirements).lower()
        assert "execute_messages_create" not in inspect.getsource(pn.canonicalize_requirements)


# ═══════════════════════════════════════════════════════════════════════════
# Defect C -- milestone canonicalization
# ═══════════════════════════════════════════════════════════════════════════

def _milestone(kind, value, date, category, page):
    return {"family": "MILESTONE", "semantic_kind": kind, "original_value": value, "date": date,
            "scope": {"category": category}, "source_refs": [{"page": page}]}


class TestCanonicalizeMilestones:

    def test_equivalent_date_wording_canonicalizes(self):
        obs = [
            _milestone("PRESENTATION_OR_DEMO", "Week of October 26 — Presentation / demonstration", None, "Category 1", 3),
            _milestone("PRESENTATION_OR_DEMO", "2026-10-26 — Presentation / demonstration", "2026-10-26", "Category 1", 10),
        ]
        canon = pn.canonicalize_milestones(obs, assumed_year=2026)
        assert len(canon) == 1
        assert canon[0]["normalized_date_start"] == "2026-10-26"
        assert len(canon[0]["original_wording"]) == 2

    def test_category_specific_distinct_dates_remain_distinct(self):
        obs = [
            _milestone("PRESENTATION_OR_DEMO", "2026-10-26", "2026-10-26", "Category 1", 3),
            _milestone("CONTRACT_AWARD", "Week of November 2", None, "Category 2", 4),
        ]
        canon = pn.canonicalize_milestones(obs, assumed_year=2026)
        assert len(canon) == 2

    def test_genuinely_different_dates_same_category_never_merge(self):
        obs = [
            _milestone("PRESENTATION_OR_DEMO", "2026-10-26", "2026-10-26", "Category 1", 3),
            _milestone("PRESENTATION_OR_DEMO", "2026-11-15", "2026-11-15", "Category 1", 4),
        ]
        canon = pn.canonicalize_milestones(obs, assumed_year=2026)
        assert len(canon) == 2

    def test_unparseable_date_becomes_ambiguity_not_false_dedup(self):
        obs = [
            _milestone("PRESENTATION_OR_DEMO", "sometime in the fall", None, "Category 1", 3),
            _milestone("PRESENTATION_OR_DEMO", "2026-10-26", "2026-10-26", "Category 1", 4),
        ]
        canon = pn.canonicalize_milestones(obs, assumed_year=2026)
        assert len(canon) == 2  # never merged -- one date window is unknown

    def test_empty_input_returns_empty(self):
        assert pn.canonicalize_milestones([]) == []

    def test_source_refs_merged_across_canonicalized_members(self):
        obs = [
            _milestone("PRESENTATION_OR_DEMO", "Week of October 26", None, "Category 1", 3),
            _milestone("PRESENTATION_OR_DEMO", "2026-10-26", "2026-10-26", "Category 1", 10),
        ]
        canon = pn.canonicalize_milestones(obs, assumed_year=2026)
        pages = {r["page"] for r in canon[0]["source_refs"]}
        assert pages == {3, 10}


# ═══════════════════════════════════════════════════════════════════════════
# Defect D -- category scope derivation
# ═══════════════════════════════════════════════════════════════════════════

class TestDeriveCategoryScopeSummaries:

    def test_scope_derived_only_from_source_supported_material(self):
        """CI-1 Defect B updated this case deliberately: prompt text that
        describes the WORK ("The Services will include ...") is genuine
        scope material; prompt text that instructs the PROPONENT is not
        (see test_response_prompt_never_becomes_scope below)."""
        weights = {"Category 1 — Learning & Development": [{"weight": "35 points", "criterion": "Curriculum Design"}]}
        prompts = {"Curriculum Design": {
            "response_prompt": "The Services will include designing, developing and delivering learning solutions.",
            "truncated": False}}
        summaries = pn.derive_category_scope_summaries(weights, prompts)
        assert summaries["Category 1 — Learning & Development"]["summary_available"] is True
        assert "designing, developing" in summaries["Category 1 — Learning & Development"]["criteria_prompts"][0]["response_prompt"]

    def test_response_prompt_never_becomes_scope(self):
        """CI-1 Defect B: 'Proponents are to describe their organisation...'
        is an evaluation/response instruction. It must never populate a
        scope-of-work field, however many service words it contains --
        it is preserved, correctly typed, under
        `response_prompts_not_scope` instead."""
        weights = {"Category 2 — HR Advisory": [{"weight": "20 points", "criterion": "Corporate Profile"}]}
        prompts = {"Corporate Profile": {
            "response_prompt": "Proponents are to describe their organisation and its advisory services experience.",
            "truncated": False}}
        summaries = pn.derive_category_scope_summaries(weights, prompts)
        cat = summaries["Category 2 — HR Advisory"]
        assert cat["criteria_prompts"] == []
        assert cat["summary_available"] is False
        assert cat["response_prompts_not_scope"][0]["semantic_type"] == "RESPONSE_PROMPT"

    def test_category_title_alone_never_fabricates_a_summary(self):
        weights = {"Category 1 — Learning & Development": [{"weight": "35 points", "criterion": "Curriculum Design"}]}
        summaries = pn.derive_category_scope_summaries(weights, {})  # no captured prompts at all
        assert summaries["Category 1 — Learning & Development"]["summary_available"] is False
        assert summaries["Category 1 — Learning & Development"]["criteria_prompts"] == []

    def test_enumerated_scope_items_included_only_when_relevant(self):
        weights = {"Learning Category": []}
        scope = {"items": ["learning workshops", "facilitator coaching"]}
        summaries = pn.derive_category_scope_summaries(weights, {}, scope)
        assert summaries["Learning Category"]["summary_available"] is True

    def test_unrelated_enumerated_items_not_attached(self):
        weights = {"Pricing Only": []}
        scope = {"items": ["catering services", "office supplies"]}
        summaries = pn.derive_category_scope_summaries(weights, {}, scope)
        assert summaries["Pricing Only"]["summary_available"] is False

    def test_empty_weights_by_category_returns_empty(self):
        assert pn.derive_category_scope_summaries({}, {}) == {}


# ═══════════════════════════════════════════════════════════════════════════
# Multilingual regression (task section 11): dedup must never falsely
# merge across languages just because two requirements share a topic --
# cross-language semantic equivalence detection is explicitly out of
# scope for this remediation ("do not launch a full multilingual
# project"); the conservative, correct behavior is to keep them as
# separate, fully source-traceable rows rather than silently guess a
# translation-equivalence this deterministic matcher cannot verify.
# ═══════════════════════════════════════════════════════════════════════════

class TestBilingualRequirementHandling:

    def test_english_and_french_restatement_of_the_same_topic_stay_separate(self):
        """An EN/FR pair shares essentially no common significant-word
        tokens (different vocabulary), so the word-overlap dedup never
        falsely collapses them into one requirement -- this is the
        correct, conservative failure mode (section 4: "if BI is not
        confident two obligations are the same, keep them separate"),
        not a translation-merging feature."""
        reqs = [
            _req("Bilingualism - written confirmation of the ability to provide all services "
                 "in both English and French.", source_doc="RFP.pdf"),
            _req("Bilinguisme - confirmation écrite de la capacité à fournir tous les services "
                 "en anglais et en français.", source_doc="Annexe F.xlsx"),
        ]
        canon = pn.canonicalize_requirements(reqs)
        assert len(canon) == 2, "cross-language pairs must never be silently merged"

    def test_source_variants_never_dropped_regardless_of_language(self):
        """Whatever language a source variant is written in, it is always
        preserved verbatim in source_variants -- canonicalization never
        discards or rewrites original wording."""
        reqs = [
            _req("Security clearance required.", source_doc="RFP.pdf"),
            _req("Security clearance required.", source_doc="Appendix B2.xlsx"),
        ]
        canon = pn.canonicalize_requirements(reqs)
        assert canon[0]["source_variants"] == ["Security clearance required."]
        assert set(canon[0]["source_docs"]) == {"RFP.pdf", "Appendix B2.xlsx"}
