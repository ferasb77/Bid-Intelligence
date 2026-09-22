"""
Regression coverage for the Dashboard bid-listing completeness bug.

Root cause: `page_dashboard()` (app.py) and the "Edit Bid Details" stage
selectbox (also app.py) both index into `components.ui.STAGES` -- a
hardcoded stage vocabulary that had drifted out of sync with the actual
`bids.stage` values the app itself assigns (`app.py` creates every new bid
with `stage="Understand"`, part of the UNDERSTAND->DECIDE->BUILD->CHECK->
SUBMIT lifecycle). `STAGES` never included "Understand", so:

  - page_dashboard()'s "### Pipeline" section (`for stage in STAGES: sb =
    [b for b in bids if b["stage"] == stage]`) silently dropped every bid
    whose stage was "Understand" -- it never appeared under any stage
    header, even though it was counted in the top "X total" metric.
  - The "Edit Bid Details" stage selectbox (`STAGES.index(bid["stage"])`)
    would raise ValueError outright for such a bid.

Executive View (`pages_extra.page_exec_dashboard`) and Bids Directory
(`app.page_all_bids`) never filtered through `STAGES` at all -- they
either use an explicit small CLOSED-stage set or no stage filter -- so
they always showed every bid, which is why the bug was visible there
first. `tenancy.list_bids_authenticated()` (the shared, canonical,
already-consolidated retrieval path both pages call) was never the
problem: no pagination, no `.limit()`, no client-side slicing.

The fix adds "Understand" to `STAGES`/`STAGE_COLOURS` in
`components/ui.py` -- the smallest change that restores completeness
without touching the canonical retrieval path or redesigning the UI.
"""
import unittest

from components.ui import STAGES, STAGE_COLOURS


# The complete set of stage values the live application code actually
# assigns to bids.stage, gathered from every write site:
#   app.py:444            -- new bid ingestion default ("Understand")
#   pages/stage_decide.py -- DECIDE-stage No Bid / In Progress transition
#   pages/stage_submit.py -- SUBMIT-stage completion ("Submitted")
#   pages/stage_debrief.py -- Won/Lost outcome write-back
# plus the pre-existing manual-entry values a user can pick from the
# STAGES dropdown itself (Identified, Qualifying, Review, Withdrawn,
# No Bid) that predate the 5-stage lifecycle.
APPLICATION_ASSIGNED_STAGE_VALUES = {
    "Understand",   # app.py new-bid-ingestion default
    "In Progress",  # stage_decide.py (pursue)
    "No Bid",       # stage_decide.py (decline) / manual
    "Submitted",    # stage_submit.py
    "Won",          # stage_debrief.py
    "Lost",         # stage_debrief.py
    "Identified",   # manual / legacy default
    "Qualifying",   # manual
    "Review",       # manual
    "Withdrawn",    # manual
}


def _simulate_pipeline_grouping(bids, stages=STAGES):
    """Reproduces page_dashboard()'s exact "### Pipeline" grouping logic
    (app.py's `for stage in STAGES: sb = [b for b in bids if b["stage"]
    == stage]`) without needing to import/render the full Streamlit page."""
    shown = []
    for stage in stages:
        shown.extend(b for b in bids if b["stage"] == stage)
    return shown


def _simulate_edit_stage_dropdown_index(bid, stages=STAGES):
    """Reproduces app.py's `STAGES.index(bid["stage"])` used to seed the
    Edit Bid Details stage selectbox's default index."""
    return stages.index(bid["stage"])


class TestStageVocabularyCompleteness(unittest.TestCase):
    """STAGES/STAGE_COLOURS must be a superset of every stage value the
    application itself ever assigns -- this is the actual contract that
    was broken."""

    def test_stages_includes_every_application_assigned_value(self):
        missing = APPLICATION_ASSIGNED_STAGE_VALUES - set(STAGES)
        self.assertEqual(
            missing, set(),
            f"components.ui.STAGES is missing stage value(s) the app itself "
            f"assigns to bids.stage: {missing}. A bid with one of these "
            f"stages will be silently dropped from page_dashboard()'s "
            f"Pipeline section.",
        )

    def test_stage_colours_includes_every_application_assigned_value(self):
        missing = APPLICATION_ASSIGNED_STAGE_VALUES - set(STAGE_COLOURS)
        self.assertEqual(missing, set())

    def test_understand_specifically_present(self):
        # The exact value confirmed live on bid_id 1061/1062/1083/1211/
        # 1212/1217/1286/1295 (8 of 11 real bids in the live database at
        # the time this bug was found) -- named explicitly so a future
        # revert of just this one entry still fails loudly.
        self.assertIn("Understand", STAGES)
        self.assertIn("Understand", STAGE_COLOURS)


class TestPipelineGroupingCompleteness(unittest.TestCase):
    """Regression fixture reproducing the exact defect: a Dashboard bid
    list containing bids across every stage the app assigns. Against the
    pre-fix STAGES (without "Understand") this fails -- the two
    "Understand"-stage bids never appear in `shown`. Against the fix it
    passes."""

    def _fixture_bids(self):
        return [
            {"id": 1, "client": "The City of Calgary", "stage": "Submitted"},
            {"id": 3, "client": "CDA-AMC", "stage": "Qualifying"},
            {"id": 8, "client": "Bank of Canada", "stage": "Identified"},
            {"id": 81, "client": "The British Council", "stage": "Qualifying"},
            {"id": 1061, "client": "Phoenix Client", "stage": "Understand"},
            {"id": 1062, "client": "Liquor Distribution Branch", "stage": "Understand"},
            {"id": 1211, "client": "HRPA", "stage": "Understand"},
        ]

    def test_every_bid_appears_in_the_pipeline_grouping(self):
        bids = self._fixture_bids()
        shown = _simulate_pipeline_grouping(bids)
        shown_ids = {b["id"] for b in shown}
        all_ids = {b["id"] for b in bids}
        self.assertEqual(
            shown_ids, all_ids,
            f"Bid(s) silently dropped from Dashboard Pipeline grouping: "
            f"{all_ids - shown_ids}",
        )

    def test_reproduces_the_bug_against_the_stale_stage_list(self):
        """Proves this fixture is a genuine reproduction: replaying it
        against the pre-fix STAGES (STAGES with "Understand" removed)
        demonstrably drops bids -- the fixture is not vacuously true."""
        stale_stages = [s for s in STAGES if s != "Understand"]
        bids = self._fixture_bids()
        shown = _simulate_pipeline_grouping(bids, stages=stale_stages)
        shown_ids = {b["id"] for b in shown}
        all_ids = {b["id"] for b in bids}
        dropped = all_ids - shown_ids
        self.assertEqual(
            dropped, {1061, 1062, 1211},
            "Expected the stale (pre-fix) stage list to drop exactly the "
            "three 'Understand'-stage bids, reproducing the live defect.",
        )

    def test_no_arbitrary_row_limit_in_grouping(self):
        # 250 bids, evenly spread across every application-assigned
        # stage -- none should be truncated by any hard-coded maximum.
        stages = sorted(APPLICATION_ASSIGNED_STAGE_VALUES)
        bids = [
            {"id": i, "stage": stages[i % len(stages)]}
            for i in range(250)
        ]
        shown = _simulate_pipeline_grouping(bids)
        self.assertEqual(len(shown), 250)

    def test_bids_in_every_workflow_stage_remain_visible(self):
        bids = [{"id": i, "stage": s}
                for i, s in enumerate(sorted(APPLICATION_ASSIGNED_STAGE_VALUES))]
        shown_ids = {b["id"] for b in _simulate_pipeline_grouping(bids)}
        self.assertEqual(shown_ids, {b["id"] for b in bids})


class TestEditStageDropdownNeverRaises(unittest.TestCase):
    """The second, independent symptom of the same root cause: app.py's
    `STAGES.index(bid["stage"])` used to seed the Edit Bid Details
    selectbox. Pre-fix, this raised ValueError for any "Understand"-stage
    bid (i.e. most live bids) the instant a user opened that expander."""

    def test_index_lookup_succeeds_for_every_application_assigned_stage(self):
        for stage in sorted(APPLICATION_ASSIGNED_STAGE_VALUES):
            with self.subTest(stage=stage):
                idx = _simulate_edit_stage_dropdown_index({"stage": stage})
                self.assertGreaterEqual(idx, 0)

    def test_understand_specifically_does_not_raise(self):
        try:
            _simulate_edit_stage_dropdown_index({"stage": "Understand"})
        except ValueError:
            self.fail(
                "STAGES.index('Understand') raised ValueError -- the "
                "Edit Bid Details form would crash for any bid still in "
                "the Understand stage."
            )


if __name__ == "__main__":
    unittest.main()
