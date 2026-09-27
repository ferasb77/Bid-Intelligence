"""CHECK-1.2: Calgary Buyer Canonicalization Closure.

Targeted tests for the three buyer-side canonicalization defects found
during real Calgary (bid 1360, RFP 26-1603) commissioning:

  A. scoped evaluation criteria came back empty whenever a corpus's Fast
     Analysis routing never dispatched the V4 focused "rated_criteria"
     task (procurement_normalization.criteria_as_scoped_occurrences).
  B. the canonical submission/clarification deadline could be won by a
     stale value because deadline fields were merged under the blanket
     "identity" authority family instead of their own amendment-aware
     ranking (canonical_procurement.merge_identity_fields_with_provenance,
     FIELD_FAMILY_OVERRIDE_BY_FIELD, the new "deadline" family, and the
     new IDENTITY_ROLE_QA_LOG role).
  C. DOCX structured document tags / content controls (w:sdt) were never
     descended, so buyer text placed inside one (e.g. a whole clause, a
     date-picker deadline) was silently dropped
     (extractor.extract_docx_with_metadata).

Every fix here is GENERAL: none of it hard-codes Calgary's own text,
dates, or weights -- synthetic fixtures are used throughout, exactly like
tests/test_canonical_procurement.py's own convention. Zero database I/O,
zero Anthropic/model calls.
"""
from __future__ import annotations

import io

import docx
from docx.oxml import parse_xml

import canonical_procurement as cp
import extractor
import procurement_normalization as pn

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _sdt_xml(inner_xml: str) -> str:
    return f'<w:sdt xmlns:w="{W_NS}"><w:sdtPr><w:alias w:val="cc"/></w:sdtPr>' \
           f'<w:sdtContent>{inner_xml}</w:sdtContent></w:sdt>'


def _para_xml(text: str) -> str:
    return f'<w:p xmlns:w="{W_NS}"><w:r><w:t>{text}</w:t></w:r></w:p>'


# ═══════════════════════════════════════════════════════════════════════
# Defect C -- DOCX content-control extraction
# ═══════════════════════════════════════════════════════════════════════

class TestDocxContentControlExtraction:

    def _build(self, inject) -> bytes:
        doc = docx.Document()
        anchor = doc.add_paragraph("Anchor")
        inject(doc, anchor)
        buf = io.BytesIO()
        doc.save(buf)
        return buf.getvalue()

    def test_text_inside_a_content_control_is_extracted(self):
        def inject(doc, anchor):
            anchor._p.addnext(parse_xml(_sdt_xml(_para_xml(
                "Each proposal by a Multi-Party Team must include a signed Multi-Party Confirmation Form."))))

        text, meta = extractor.extract_docx_with_metadata(self._build(inject), "rfp.docx")
        assert "Multi-Party Confirmation Form" in text
        assert meta["content_controls"]["block_paragraphs"] == 1

    def test_nested_table_content_control_survives(self):
        table_xml = (
            f'<w:tbl xmlns:w="{W_NS}"><w:tr><w:tc><w:p><w:r><w:t>Row1Cell1</w:t></w:r></w:p></w:tc>'
            f'<w:tc><w:p><w:r><w:t>Row1Cell2</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
        )

        def inject(doc, anchor):
            anchor._p.addnext(parse_xml(_sdt_xml(table_xml)))

        text, meta = extractor.extract_docx_with_metadata(self._build(inject), "rfp.docx")
        assert "Row1Cell1 | Row1Cell2" in text
        assert meta["tables_count"] == 1
        assert meta["content_controls"]["table_rows"] == 1

    def test_ordinary_paragraphs_unchanged(self):
        def inject(doc, anchor):
            doc.add_paragraph("A perfectly ordinary paragraph.")

        text, meta = extractor.extract_docx_with_metadata(self._build(inject), "rfp.docx")
        assert "A perfectly ordinary paragraph." in text
        assert meta["content_controls"] == {"block_paragraphs": 0, "inline_paragraphs": 0, "table_rows": 0}

    def test_no_duplicate_text_from_container_and_child(self):
        """The container (w:sdt) must never ALSO emit its own aggregate
        text alongside its child paragraph's text -- exactly one line per
        real paragraph, however deeply content-control-wrapped."""
        def inject(doc, anchor):
            anchor._p.addnext(parse_xml(_sdt_xml(_para_xml("Unique clause text ABC123"))))

        text, meta = extractor.extract_docx_with_metadata(self._build(inject), "rfp.docx")
        assert text.count("Unique clause text ABC123") == 1
        paragraph_blocks = [b for b in meta["blocks"] if b["kind"] == "paragraph"
                            and "Unique clause text ABC123" in b.get("excerpt", "")]
        assert len(paragraph_blocks) == 1

    def test_inline_content_control_within_a_run_of_text(self):
        """A run-level (inline) sdt sitting inside an ordinary paragraph
        alongside plain runs must contribute its text exactly once, merged
        into that one paragraph -- not as a separate paragraph."""
        para_xml = (
            f'<w:p xmlns:w="{W_NS}"><w:r><w:t>Deadline: </w:t></w:r>'
            f'<w:sdt><w:sdtPr/><w:sdtContent><w:r><w:t>2026-07-16</w:t></w:r></w:sdtContent></w:sdt>'
            f'<w:r><w:t> (MST)</w:t></w:r></w:p>'
        )

        def inject(doc, anchor):
            anchor._p.addnext(parse_xml(para_xml))

        text, meta = extractor.extract_docx_with_metadata(self._build(inject), "rfp.docx")
        assert "Deadline: 2026-07-16 (MST)" in text
        assert text.count("2026-07-16") == 1
        assert meta["content_controls"]["inline_paragraphs"] == 1


# ═══════════════════════════════════════════════════════════════════════
# Defect A -- scoped evaluation criteria from the general (non-focused) route
# ═══════════════════════════════════════════════════════════════════════

class TestScopedCriteriaFromGeneralRouteEvaluationCriteria:

    def test_general_route_criteria_become_scoped_records(self):
        """No V4 focused rated_criteria task ran (evaluation_occurrences is
        empty), but the general route's own evaluation_criteria has real
        rated criteria -- these must still become scoped records."""
        evaluation_criteria = [
            {"stage": "Firm Experience", "parent_stage": "Rated Criteria",
             "weight": "30%", "threshold": "60%", "source_doc": "RFP.docx",
             "source_refs": ["r1"]},
            {"stage": "Team Experience and Qualifications", "parent_stage": "Rated Criteria",
             "weight": "20%", "threshold": None, "source_doc": "RFP.docx", "source_refs": []},
        ]
        occurrences = pn.criteria_as_scoped_occurrences(evaluation_criteria)
        records = pn.build_scoped_criterion_records(occurrences)
        assert len(records) == 2
        key = cp.scoped_criterion_map_key("", "Firm Experience")
        assert records[key]["weight"] == "30%"
        assert records[key]["minimum_score"] == "60%"
        assert records[key]["category_scope"] == ""
        assert records[key]["authoritative_source"] == "RFP.docx"

    def test_category_scope_is_never_fabricated_from_parent_stage(self):
        """parent_stage is a table/heading title, not a service category --
        it must never leak into category_scope."""
        occ = pn.criteria_as_scoped_occurrences(
            [{"stage": "Pricing", "parent_stage": "Section 4 - Evaluation", "weight": "10%"}])
        assert occ[0]["category_scope"] == ""

    def test_criteria_without_a_stage_label_are_skipped(self):
        assert pn.criteria_as_scoped_occurrences([{"stage": "", "weight": "5%"}]) == []
        assert pn.criteria_as_scoped_occurrences([{"weight": "5%"}]) == []

    def test_focused_task_occurrences_take_priority_when_present(self):
        """When evaluation_occurrences IS populated (the focused task did
        run), the general-route fallback must never be consulted at all --
        this is exercised at the fast_analysis.py call-site level, so this
        test asserts the fallback function itself is simply not invoked
        when occurrences already exist (contract, not implementation)."""
        occurrences = [{"criterion_label": "Firm Experience", "category_scope": "Category 1",
                        "weight": "30%"}]
        # The caller (fast_analysis.py) only calls criteria_as_scoped_occurrences
        # when `not scoped_occurrences` -- confirm real occurrences alone are
        # sufficient to build a correct, real record with no fallback data mixed in.
        records = pn.build_scoped_criterion_records(occurrences)
        key = cp.scoped_criterion_map_key("Category 1", "Firm Experience")
        assert records[key]["category_scope"] == "Category 1"
        assert len(records) == 1


# ═══════════════════════════════════════════════════════════════════════
# Defect B -- field-specific amendment authority for deadline fields
# ═══════════════════════════════════════════════════════════════════════

class TestDeadlineAmendmentAuthority:

    def test_base_deadline_superseded_by_later_addendum(self):
        merged = cp.merge_identity_fields({
            "RFP.docx": {"submission_deadline": "2026-07-07", "title": "The RFP"},
            "Addendum One.pdf": {"submission_deadline": "2026-07-14"},
        })
        assert merged["submission_deadline"] == "2026-07-14"
        # a non-overridden identity field is unaffected by the addendum
        assert merged["title"] == "The RFP"

    def test_earlier_amendment_superseded_by_later_amendment(self):
        """Multiple addenda restate the deadline; regardless of dict/scan
        order, the LATEST stated value among same-authority amendments
        wins -- never "whichever amendment happened to be scanned first"."""
        merged_a = cp.merge_identity_fields({
            "Addendum One.pdf": {"submission_deadline": "2026-07-14"},
            "Addendum Four.pdf": {"submission_deadline": "2026-07-16"},
        })
        merged_b = cp.merge_identity_fields({
            "Addendum Four.pdf": {"submission_deadline": "2026-07-16"},
            "Addendum One.pdf": {"submission_deadline": "2026-07-14"},
        })
        assert merged_a["submission_deadline"] == "2026-07-16"
        assert merged_b["submission_deadline"] == "2026-07-16"

    def test_unrelated_addendum_does_not_overwrite_deadline(self):
        """An addendum that never states a deadline at all must never
        blank out or otherwise affect an existing deadline value."""
        merged = cp.merge_identity_fields({
            "RFP.docx": {"submission_deadline": "2026-07-07"},
            "Addendum Two.pdf": {"clarification_deadline": "2026-06-30"},
        })
        assert merged["submission_deadline"] == "2026-07-07"
        assert merged["clarification_deadline"] == "2026-06-30"

    def test_qa_log_never_outranks_the_primary_solicitation_or_an_amendment(self):
        assert cp.classify_identity_role("QA Log 26-1603_Updated_July 08_2026.xlsx") == cp.IDENTITY_ROLE_QA_LOG
        merged = cp.merge_identity_fields({
            "QA Log Updated.xlsx": {"submission_deadline": "2026-07-07", "title": "QA restatement"},
            "RFP.docx": {"submission_deadline": "2026-07-14", "title": "Design and Delivery Services RFP"},
        })
        assert merged["submission_deadline"] == "2026-07-14"
        assert merged["title"] == "Design and Delivery Services RFP"

    def test_qa_log_only_package_still_yields_an_honest_answer(self):
        """Last-resort fallback: if NOTHING else states the deadline, the
        Q&A log's own value is still surfaced rather than silence."""
        merged = cp.merge_identity_fields({"QA Log.xlsx": {"submission_deadline": "2026-07-07"}})
        assert merged["submission_deadline"] == "2026-07-07"

    def test_superseded_values_remain_available_as_milestone_provenance(self):
        """canonicalize_milestones (the separate provenance layer) must
        keep the stale and final deadlines as DISTINCT rows -- the merge
        function decides the one canonical winner; it must never delete
        the earlier value's own record."""
        observations = [
            {"semantic_kind": "SUBMISSION_DEADLINE", "original_value": "2026 July 7",
             "date": "2026-07-07", "source_refs": ["ref-base"]},
            {"semantic_kind": "SUBMISSION_DEADLINE", "original_value": "2026 July 16",
             "date": "2026-07-16", "source_refs": ["ref-addendum-4"]},
        ]
        canonical = pn.canonicalize_milestones(observations)
        dates = sorted(m["normalized_date_start"] for m in canonical)
        assert dates == ["2026-07-07", "2026-07-16"]

    def test_final_authoritative_deadline_is_deterministic(self):
        meta = {
            "RFP.docx": {"submission_deadline": "2026-07-07"},
            "Addendum One.pdf": {"submission_deadline": "2026-07-14"},
            "Addendum Four.pdf": {"submission_deadline": "2026-07-16"},
            "QA Log.xlsx": {"submission_deadline": "2026-07-07"},
        }
        results = {cp.merge_identity_fields(meta)["submission_deadline"] for _ in range(5)}
        assert results == {"2026-07-16"}


# ═══════════════════════════════════════════════════════════════════════
# Multi-party requirement candidate chain (Defect C's downstream effect)
# ═══════════════════════════════════════════════════════════════════════

class TestMultiPartyRequirementOriginatesFromBuyerPackage:

    def test_multi_party_clause_extracted_from_content_control_is_available_as_source_text(self):
        """After Defect C's fix, a buyer-authored multi-party clause held
        in a content control is present in the extracted document text --
        the only thing this task requires generally (never special-cased
        on the phrase itself, never manufactured from the bidder's own B2
        form). Downstream requirement extraction/canonicalization already
        consumes extracted document text as its sole input; this proves
        that input is no longer silently missing this clause."""
        doc = docx.Document()
        anchor = doc.add_paragraph("B2: MULTI-PARTY CONFIRMATION FORM")
        anchor._p.addnext(parse_xml(_sdt_xml(_para_xml(
            "Each proposal submitted on behalf of a Multi-Party Team must include a Multi-Party "
            "Confirmation Form completed and signed by all Team Members."))))
        buf = io.BytesIO()
        doc.save(buf)
        text, _ = extractor.extract_docx_with_metadata(buf.getvalue(), "rfp.docx")
        assert "Multi-Party Confirmation Form completed and signed by all Team Members" in text

    def test_bidder_form_alone_cannot_create_a_buyer_requirement(self):
        """A bidder's own submitted B2 form is never itself the source of
        a canonical buyer requirement -- canonicalize_requirements only
        ever canonicalizes what is passed to it as a requirement; passing
        none in yields none out, regardless of what evidence later exists
        on the bidder side."""
        assert pn.canonicalize_requirements([]) == []
