"""End-to-end orchestration of one analysis of one package.

The run record states exactly which models and configurations ran, what
failed and what the verification status is. A report is labelled
INDEPENDENTLY_VERIFIED only when two real (non-synthetic) analysts from
different providers both completed, adjudication and review ran, the ledger
is complete and every page was readable. Anything less is labelled as what it
is; a failed independent pass can never yield a "verified" report.

Two modes (engine.budget): FAST, the Opportunity Snapshot (one extraction,
deterministic checks, one writing pass), and FULL, the Bid Opportunity
Assessment (adds package review, adjudication, conflict classification, final
review and optional buyer research). Each has its own hard cost cap and
per-stage allotments, and every model answer is checkpointed so a stopped run
resumes and FULL reuses FAST's extraction."""
from __future__ import annotations

import concurrent.futures
import copy
import os
import time
from dataclasses import dataclass, field

from engine import ENGINE_VERSION, adjudicate as adj, budget, conflicts as cf, extraction, register as rg, reports, review
from engine.checkpoints import CheckpointStore, with_checkpoints
from engine.package import SourcePackage
from engine.providers import (Analyst, CostLimitExceeded, ProviderError, ProviderNotAuthorized, ProviderNotConfigured,
                              ProviderUnavailable, UsageLedger)
from engine.verify import verify_finding

STATUS_TEXT = {
    "INDEPENDENTLY_VERIFIED": "Independently verified: two analysts from different providers read the complete "
                              "package; findings were reconciled, adjudicated against the source and reviewed.",
    "VERIFIED_WITH_LIMITATIONS": "Dual-analyst analysis with limitations listed in the Management Decision "
                                 "Reference.",
    "SINGLE_ANALYST": "Single-analyst analysis: the independent second analysis did not run, so findings are "
                      "source-verified but not independently confirmed.",
    "SYNTHETIC": "Development run with synthetic model responses -- not intelligence.",
    "FAILED": "The analysis failed and no report was produced.",
}


@dataclass
class EngineRoles:
    primary: Analyst                       # first independent analyst
    independent: Analyst | None            # second independent analyst (may be None / unauthorized)
    adjudicator: Analyst                   # adjudication, conflicts, analysis writing, final review
    reviewer: Analyst | None = None        # defaults to the adjudicator
    writer: Analyst | None = None          # FAST analysis writing; FULL uses the adjudicator


def _budget_refused(text) -> bool:
    return "refused before sending" in str(text or "")


def _checkpointed(roles: EngineRoles, store: CheckpointStore | None) -> EngineRoles:
    if store is None:
        return roles
    return EngineRoles(primary=with_checkpoints(roles.primary, store),
                       independent=with_checkpoints(roles.independent, store),
                       adjudicator=with_checkpoints(roles.adjudicator, store),
                       reviewer=with_checkpoints(roles.reviewer, store),
                       writer=with_checkpoints(roles.writer, store))


def new_ledger(mode: str, label: str = "", path: str | None = None) -> UsageLedger:
    """The ledger of one run of `mode`: its cap and its per-stage allotments."""
    return UsageLedger(label, path=path, max_cost_usd=budget.cap(mode), stage_budgets=budget.stage_budgets(mode))


@dataclass
class EngineRun:
    package: SourcePackage
    record: dict = field(default_factory=dict)
    inventories: dict = field(default_factory=dict)
    register: dict = field(default_factory=dict)
    conflicts: dict = field(default_factory=dict)
    analysis: dict = field(default_factory=dict)
    composed: dict = field(default_factory=dict)
    review: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"record": self.record, "inventories": self.inventories, "register": self.register,
                "conflicts": self.conflicts, "analysis": self.analysis, "composed": self.composed,
                "review": self.review, "package": {"hash": self.package.package_hash,
                                                   "data_class": self.package.data_class,
                                                   "documents": self.package.manifest(),
                                                   "readability": self.package.readability()}}


def _verify_inventory(package: SourcePackage, inv: dict) -> dict:
    inv = dict(inv)
    inv["findings"] = [verify_finding(package, f) for f in inv["findings"]]
    counts: dict[str, int] = {}
    for f in inv["findings"]:
        s = f["verification"]["status"]
        counts[s] = counts.get(s, 0) + 1
    inv["verification_counts"] = counts
    return inv


def _mark_updates(entries: list[dict], previous_entries: list[dict] | None, new_docs: list[str]) -> list[str]:
    """New information is what a document added since the previous analysis
    states. Earlier entries on the same topics are listed for re-examination."""
    if previous_entries is None:
        return []
    new = set(new_docs)
    for e in entries:
        if e.get("document") in new and not e.get("previous"):
            e["new_in_update"] = True
    return cf.affected_by_new_documents(entries, new_docs)


def run(package: SourcePackage, roles: EngineRoles, *, mode: str = "FULL", ledger: UsageLedger | None = None,
        progress=None, research: dict | None = None, research_fn=None, previous: dict | None = None,
        store: CheckpointStore | None = None, preflight: dict | None = None) -> EngineRun:
    """One run of `mode` ("FAST" or "FULL").

    previous: an earlier run of the SAME bid ({"register": ..., "documents": [...]}) for update labelling.
    store: checkpoints of this bid (engine.checkpoints); every successful model
    answer is kept there and an identical request is answered from it at $0,
    so a failed or budget-stopped run resumes instead of paying twice, and FULL
    reuses the extraction of a FAST run of the same package.

    Every model call reserves its worst-case cost against the run cap and its
    stage's allotment before it is sent (UsageLedger). When the run cap is
    reached no further call is made and the run ends FAILED with error kind
    COST_LIMIT_EXCEEDED -- never COMPLETE."""
    if mode not in budget.MODES:
        raise ValueError(f"unknown engine mode {mode!r}")
    ledger = ledger or new_ledger(mode, package.package_hash[:12])
    roles = _checkpointed(roles, store)
    try:
        if mode == "FAST":
            out = _run_fast(package, roles, ledger=ledger, progress=progress)
        else:
            out = _run(package, roles, ledger=ledger, progress=progress, research=research,
                       research_fn=research_fn, previous=previous)
    except CostLimitExceeded:
        out = EngineRun(package)
    if ledger.cost_limit_hit:
        out.record.update(status="FAILED", verification="FAILED",
                          error={"kind": "COST_LIMIT_EXCEEDED", "message": ledger.cost_limit_hit},
                          usage=ledger.summary())
    out.record["mode"] = mode
    if preflight is not None:
        out.record["preflight"] = preflight
    if getattr(store, "reused_from", None):
        out.record["checkpoints_reused_from_runs"] = sorted(store.reused_from)
    return out


def _start_record(out: EngineRun, package: SourcePackage, roles: EngineRoles, models: dict) -> dict:
    rec = out.record
    rec.update(engine_version=ENGINE_VERSION, started_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
               package_hash=package.package_hash, data_class=package.data_class,
               documents=package.manifest(), readability=package.readability(), models=models,
               stages={}, limitations=[])
    return rec


def _blocking_extraction(package: SourcePackage, invs: tuple) -> list[str]:
    blocking = []
    for tag, inv in invs:
        failed_locs = [g for g in (inv or {}).get("gaps") or []
                       if str(g.get("reason", "")).startswith("extraction failed")]
        if failed_locs:
            blocking.append(f"{tag} extraction failed for {len(failed_locs)} of {len(package.locations)} "
                            f"page(s)/section(s): {failed_locs[0]['reason'][:200]}")
    return blocking


def _run_fast(package: SourcePackage, roles: EngineRoles, *, ledger: UsageLedger, progress=None) -> EngineRun:
    """FAST -- Opportunity Snapshot: one complete extraction of the package
    (every page/section accounted for), deterministic source verification,
    deterministic conflict scan (listed as open questions), one writing pass
    and deterministic report checks. No adjudication, conflict classification,
    model review or buyer research: those are FULL's. A FAST report is
    advisory triage and says so."""
    t0 = time.monotonic()
    out = EngineRun(package)
    writer = roles.writer or roles.adjudicator
    rec = _start_record(out, package, roles, {"primary": roles.primary.describe(), "independent": None,
                                              "writer": writer.describe()})

    def stage(name, status, **kw):
        rec["stages"][name] = dict(status=status, seconds=round(time.monotonic() - t0, 1), **kw)
        if progress:
            progress("stage", name, status)

    try:
        inv = extraction.extract(roles.primary, package, ledger, tag="A", progress=progress)
    except (ProviderNotAuthorized, ProviderNotConfigured, ProviderUnavailable) as exc:
        stage("extract_A", "FAILED", error={"kind": type(exc).__name__, "message": str(exc)}, findings=0, gaps=0)
        rec.update(status="FAILED", verification="FAILED", error={"kind": type(exc).__name__, "message": str(exc)},
                   usage=ledger.summary(), seconds=round(time.monotonic() - t0, 1))
        return out
    stage("extract_A", "OK", findings=len(inv["findings"]), gaps=len(inv["gaps"]))
    inv_a = _verify_inventory(package, inv)
    out.inventories = {"A": inv_a, "B": None, "errors": {}}

    reg = rg.reconcile(inv_a, None)
    entries = reg["entries"]
    stage("reconcile", "OK", stats=reg["stats"])
    # no adjudication in FAST: what FULL would adjudicate stays visibly open
    for e in entries:
        if rg.needs_adjudication(e, dual=False) and e.get("applicability") == "CURRENT":
            if e["status"] == "UNVERIFIED":
                e["applicability"] = "EXCLUDED_UNVERIFIED"
            elif e["status"] == "DISPUTED":
                e["applicability"] = "DISPUTED"

    out.conflicts = cf.unclassified(entries)
    stage("conflicts", "SCANNED", conflicts=len(out.conflicts["conflicts"]), classified=False)

    out.analysis = reports.analysis(writer, entries, ledger, package.data_class,
                                    run_date=str(rec.get("started_at") or "")[:10])
    an_err = out.analysis.get("error")
    stage("analysis", "OK" if not an_err else ("BUDGET_REFUSED" if _budget_refused(an_err) else "FAILED"),
          rejected=len(out.analysis["rejected"]))
    rec["buyer_research_status"] = None

    def compose():
        return reports.compose(entries, an=out.analysis, conflicts=out.conflicts, readability=package.readability(),
                               run_meta={"verification": rec.get("verification"),
                                         "run_date": str(rec.get("started_at") or "")[:10]}, research=None)

    composed = compose()
    det = review.deterministic_checks(composed, entries)
    out.review = {"deterministic_before": det, "deterministic_after": det, "model_issues": None,
                  "model_error": None, "applied": [], "unresolved": [], "added": []}
    stage("review", "DETERMINISTIC_ONLY", deterministic=len(det))

    synthetic = any(a.synthetic for a in (roles.primary, writer) if a)
    lim = rec["limitations"]
    lim.append("FAST triage: one analyst, no adjudication, no model review and no buyer research. Candidate "
               "conflicts are listed as open questions without classification. The Bid Opportunity Assessment "
               "(FULL) adds these checks.")
    if not package.readability()["complete"]:
        lim.append("Some pages could not be read; see coverage.")
    if inv_a.get("gaps"):
        lim.append(f"{len(inv_a['gaps'])} page(s)/section(s) were not fully accounted for by the analyst.")
    open_n = sum(1 for e in entries if e.get("applicability") in ("DISPUTED", "EXCLUDED_UNVERIFIED"))
    if open_n:
        lim.append(f"{open_n} register entr{'y' if open_n == 1 else 'ies'} could not be confirmed against the source "
                   f"without adjudication and are left out or marked disputed.")
    if an_err:
        lim.append("The summary/analysis writing pass failed; the report contains document facts only.")
    if det:
        lim.append(f"{len(det)} deterministic check(s) failing.")

    blocking = _blocking_extraction(package, (("primary", inv_a),))
    if any((e.get("verification") or {}).get("status") is None for e in entries):
        blocking.append("some register entries were never verified against the source")
    if not composed["ledger"]["complete"]:
        blocking.append("omission ledger violations: " + ", ".join(composed["ledger"]["violations"][:10]))
    if an_err:
        blocking.append(f"analysis writing failed: {an_err[:200]}")
    out.register = {"entries": entries, "duplicates": reg["duplicates"], "stats": _stats(entries)}
    if blocking:
        out.composed = composed
        rec.update(status="FAILED", verification="FAILED", limitations=lim,
                   error={"kind": "INCOMPLETE_ANALYSIS", "message": "; ".join(blocking)},
                   usage=ledger.summary(), seconds=round(time.monotonic() - t0, 1))
        return out
    status = "SYNTHETIC" if synthetic else "SINGLE_ANALYST"
    rec["verification"] = status
    rec["verification_text"] = STATUS_TEXT[status]
    composed = compose()
    composed["fast"]["verification"] = {"status": status, "text": STATUS_TEXT[status], "limitations": list(lim)}
    composed["full"] = None          # FAST produces the Opportunity Snapshot only
    out.composed = composed
    rec.update(status="COMPLETE", usage=ledger.summary(), seconds=round(time.monotonic() - t0, 1),
               finished_at=time.strftime("%Y-%m-%dT%H:%M:%S"), ledger_complete=composed["ledger"]["complete"])
    return out


def _run(package: SourcePackage, roles: EngineRoles, *, ledger: UsageLedger, progress=None,
         research: dict | None = None, research_fn=None, previous: dict | None = None) -> EngineRun:
    t0 = time.monotonic()
    out = EngineRun(package)
    rec = out.record
    rec.update(engine_version=ENGINE_VERSION, started_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
               package_hash=package.package_hash, data_class=package.data_class,
               documents=package.manifest(), readability=package.readability(),
               models={"primary": roles.primary.describe(),
                       "independent": roles.independent.describe() if roles.independent else None,
                       "adjudicator": roles.adjudicator.describe(),
                       "reviewer": (roles.reviewer or roles.adjudicator).describe()},
               stages={}, limitations=[])

    def stage(name, status, **kw):
        rec["stages"][name] = dict(status=status, seconds=round(time.monotonic() - t0, 1), **kw)
        if progress:
            progress("stage", name, status)

    # 1. independent extraction (in parallel; neither sees the other)
    def do_extract(analyst, tag):
        inv = extraction.extract(analyst, package, ledger, tag=tag, progress=progress)
        inv["review"] = extraction.package_review(analyst, package, inv, ledger)
        for i, f in enumerate(inv["review"].get("missed") or [], 1):
            inv["findings"].append(dict(f, id=f"{tag}-M{i:02d}", analyst=tag, from_package_review=True))
        return inv

    jobs = {"A": roles.primary}
    if roles.independent is not None:
        jobs["B"] = roles.independent
    results, errors = {}, {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futs = {pool.submit(do_extract, a, tag): tag for tag, a in jobs.items()}
        for fut in concurrent.futures.as_completed(futs):
            tag = futs[fut]
            try:
                results[tag] = fut.result()
            except (ProviderNotAuthorized, ProviderNotConfigured, ProviderUnavailable) as exc:
                errors[tag] = {"kind": type(exc).__name__, "message": str(exc)}
            except Exception as exc:
                errors[tag] = {"kind": "FAILED", "message": f"{type(exc).__name__}: {exc}"[:400]}
    for tag in jobs:
        kind = (errors.get(tag) or {}).get("kind")
        st = "OK" if tag in results else (
            "NOT_CONFIGURED" if tag == "B" and kind in ("ProviderNotAuthorized", "ProviderNotConfigured") else "FAILED")
        stage(f"extract_{tag}", st, error=errors.get(tag),
              findings=len(results.get(tag, {}).get("findings", [])), gaps=len(results.get(tag, {}).get("gaps", [])))
    if "A" not in results:
        rec.update(status="FAILED", verification="FAILED", error=errors.get("A"), usage=ledger.summary(),
                   seconds=round(time.monotonic() - t0, 1))
        return out
    inv_a = _verify_inventory(package, results["A"])
    inv_b = _verify_inventory(package, results["B"]) if "B" in results else None
    out.inventories = {"A": inv_a, "B": inv_b, "errors": errors}
    dual = inv_b is not None

    # 2. register and reconciliation
    reg = rg.reconcile(inv_a, inv_b)
    entries = reg["entries"]
    stage("reconcile", "OK", stats=reg["stats"])

    # 3. adjudication (bounded, one pass)
    targets = [e for e in entries if rg.needs_adjudication(e, dual=dual)]
    adj_stats = adj.adjudicate(roles.adjudicator, package, entries, targets, ledger) if targets else \
        {"adjudicated": 0, "failed_batches": 0, "decisions": {}}
    stage("adjudicate", "OK" if not (adj_stats["failed_batches"] or adj_stats.get("deferred_batches")) else "PARTIAL",
          targets=len(targets), **adj_stats)

    # 4. conflicts, clarifications, amendments
    reviews = [inv.get("review") or {} for inv in (inv_a, inv_b) if inv]
    out.conflicts = cf.resolve(roles.adjudicator, package, entries, reviews, ledger)
    stage("conflicts", "OK" if not out.conflicts["errors"] else (
        "BUDGET_REFUSED" if _budget_refused(out.conflicts["errors"][0]) else "PARTIAL"),
          conflicts=len(out.conflicts["conflicts"]), amendments=len(out.conflicts["amendments"]))
    prev_entries = (previous or {}).get("register", {}).get("entries") if previous else None
    new_docs = [d.name for d in package.documents if previous and d.name not in set(previous.get("documents") or [])]
    rec["update"] = {"previous_run": (previous or {}).get("run_id"), "new_documents": new_docs,
                     "re_examined_entries": _mark_updates(entries, prev_entries, new_docs)} if previous else None

    # 5. analysis writing + composition
    out.analysis = reports.analysis(roles.adjudicator, entries, ledger, package.data_class,
                                    run_date=str(rec.get("started_at") or "")[:10])
    an_err = out.analysis.get("error")
    stage("analysis", "OK" if not an_err else ("BUDGET_REFUSED" if _budget_refused(an_err) else "FAILED"),
          rejected=len(out.analysis["rejected"]))

    def compose():
        return reports.compose(entries, an=out.analysis, conflicts=out.conflicts, readability=package.readability(),
                               run_meta={"verification": rec.get("verification"),
                                         "run_date": str(rec.get("started_at") or "")[:10]},
                               research=research)

    composed = compose()

    # 6. final review, evidence-backed corrections, recomposition
    reviewer = roles.reviewer or roles.adjudicator
    det = review.deterministic_checks(composed, entries)
    mr = review.model_review(reviewer, package, composed, entries, ledger)
    corr = review.apply_corrections(package, entries, [i for i in mr.get("issues") or []], out.analysis)
    composed = compose()
    det_after = review.deterministic_checks(composed, entries)
    out.review = {"deterministic_before": det, "deterministic_after": det_after, "model_issues": mr.get("issues"),
                  "model_error": mr.get("error"), **corr}
    stage("review", "OK" if not mr.get("error") else ("BUDGET_REFUSED" if _budget_refused(mr["error"]) else "FAILED"),
          applied=len(corr["applied"]), unresolved=len(corr["unresolved"]), added=len(corr["added"]),
          deterministic=len(det_after))

    # 6b. external buyer research -- optional, last, and only within what the budget still allows;
    # kept apart from document facts
    if research is None and research_fn is not None:
        if ledger.cost_limit_hit:
            research = {"status": "SKIPPED", "error": "run cost cap reached"}
        else:
            try:
                research = research_fn(out.analysis, ledger)
            except Exception as exc:
                research = {"status": "FAILED", "error": str(exc)[:200]}
        stage("buyer_research", (research or {}).get("status") or "NONE")
    rec["buyer_research_status"] = (research or {}).get("status")
    if research is not None:
        composed = compose()

    # 7. verification status (computed, never asserted)
    synthetic = any(a.synthetic for a in [roles.primary, roles.independent, roles.adjudicator, reviewer] if a)
    gaps = (inv_a.get("gaps") or []) + ((inv_b or {}).get("gaps") or [])
    lim = rec["limitations"]
    if not package.readability()["complete"]:
        lim.append("Some pages could not be read; see coverage.")
    if gaps:
        lim.append(f"{len(gaps)} page(s)/section(s) were not fully accounted for by an analyst.")
    if adj_stats["failed_batches"]:
        lim.append("Some adjudication batches failed; affected entries remain marked as disputed.")
    if adj_stats.get("deferred_batches"):
        lim.append(f"{adj_stats.get('deferred_entries', 0)} entr{'y was' if adj_stats.get('deferred_entries') == 1 else 'ies were'} "
                   f"not adjudicated because the adjudication budget was used up "
                   f"({adj_stats['deferred_batches']} batch(es)); they remain marked as disputed or unconfirmed.")
    if out.conflicts["errors"]:
        lim.append("Conflict classification failed; candidate conflicts are listed unclassified.")
    if mr.get("error"):
        lim.append("The final review pass failed.")
    if out.analysis.get("error"):
        lim.append("The summary/analysis writing pass failed; reports contain document facts only.")
    if det_after:
        lim.append(f"{len(det_after)} deterministic check(s) still failing after review.")
    if corr["unresolved"]:
        lim.append(f"{len(corr['unresolved'])} review issue(s) could not be resolved with verifiable evidence.")
    # a run that could not read part of the package with its primary analyst,
    # or could not write or review its reports, is not a completed analysis
    blocking = _blocking_extraction(package, (("primary", inv_a), ("independent", inv_b)))
    b_err = errors.get("B") or {}
    if b_err and b_err.get("kind") not in ("ProviderNotAuthorized", "ProviderNotConfigured"):
        # an independent analyst that was configured and authorized but failed is a failed run,
        # not a quietly downgraded single-analyst one
        blocking.append(f"independent analysis failed: {b_err.get('message', '')[:200]}")
    if adj_stats["failed_batches"]:
        blocking.append(f"adjudication failed for {adj_stats['failed_batches']} batch(es)")
    if out.conflicts["errors"]:
        blocking.append(f"conflict classification failed: {out.conflicts['errors'][0][:200]}")
    if any((e.get("verification") or {}).get("status") is None for e in entries if e.get("status") != "REVIEW_ADDED"):
        blocking.append("some register entries were never verified against the source")
    if not composed["ledger"]["complete"]:
        blocking.append("omission ledger violations: " + ", ".join(composed["ledger"]["violations"][:10]))
    if out.analysis.get("error"):
        blocking.append(f"analysis writing failed: {out.analysis['error'][:200]}")
    if mr.get("error"):
        blocking.append(f"final review failed: {str(mr['error'])[:200]}")
    if blocking:
        out.register = {"entries": entries, "duplicates": reg["duplicates"], "stats": _stats(entries)}
        out.composed = composed
        rec.update(status="FAILED", verification="FAILED", limitations=lim,
                   error={"kind": "INCOMPLETE_ANALYSIS", "message": "; ".join(blocking)},
                   usage=ledger.summary(), seconds=round(time.monotonic() - t0, 1))
        return out
    if synthetic:
        status = "SYNTHETIC"
    elif not dual:
        status = "SINGLE_ANALYST"
        lim.insert(0, "Independent second analysis did not run: " +
                   (errors.get("B", {}).get("message") or "not configured"))
    elif roles.independent.provider == roles.primary.provider:
        status = "VERIFIED_WITH_LIMITATIONS"
        lim.insert(0, "Both analysts are from the same provider.")
    else:
        status = "VERIFIED_WITH_LIMITATIONS" if lim else "INDEPENDENTLY_VERIFIED"
    rec["verification"] = status
    rec["verification_text"] = STATUS_TEXT[status]
    composed = compose()
    for rep in (composed["fast"], composed["full"]):
        rep["verification"] = {"status": status, "text": STATUS_TEXT[status], "limitations": list(lim)}
    out.composed = composed
    out.register = {"entries": entries, "duplicates": reg["duplicates"], "stats": _stats(entries)}
    rec.update(status="COMPLETE", usage=ledger.summary(), seconds=round(time.monotonic() - t0, 1),
               finished_at=time.strftime("%Y-%m-%dT%H:%M:%S"), ledger_complete=composed["ledger"]["complete"])
    return out


def _stats(entries: list[dict]) -> dict:
    s: dict = {"entries": len(entries), "status": {}, "applicability": {}, "materiality": {}}
    for e in entries:
        for k, key in (("status", "status"), ("applicability", "applicability"), ("materiality", "materiality")):
            s[k][e.get(key)] = s[k].get(e.get(key), 0) + 1
    return s


DEFAULT_EXTRACT_MODEL = "claude-haiku-5-5"
DEFAULT_EXTRACT_EFFORT = "low"
SYNTHESIS_MODEL = "claude-opus-5-5"
DEFAULT_SYNTHESIS_EFFORT = "medium"
DEFAULT_WRITER_MODEL = "claude-sonnet-5-5"      # FAST writing pass
DEFAULT_WRITER_EFFORT = "medium"


def _env(name: str, default: str) -> str:
    return os.getenv(name, "").strip() or default


def default_roles(*, anthropic_key: str | None = None, independent: str | None = "openai",
                  mode: str = "FULL") -> EngineRoles:
    """Raw page extraction ("extract:*") on ENGINE_EXTRACT_MODEL (default
    Haiku 5.5) at ENGINE_EXTRACT_EFFORT (default "low") -- the same model and
    prompts in both modes, so a FULL run reuses a FAST run's extraction.

    FAST: that extractor alone, and one writing pass on ENGINE_WRITER_MODEL
    (default Sonnet 5.5, effort ENGINE_WRITER_EFFORT, default "medium"). No
    Opus, no independent analyst.

    FULL: package review, adjudication, conflicts, analysis writing and final
    review on Opus 5.5 at ENGINE_SYNTHESIS_EFFORT (default "medium"); OpenAI
    independent analyst (refuses client data until authorized -- the run then
    records SINGLE_ANALYST)."""
    from engine.providers import AnthropicAnalyst, OpenAIAnalyst, RoutedAnalyst
    if mode not in budget.MODES:
        raise ValueError(f"unknown engine mode {mode!r}")
    extractor = AnthropicAnalyst(_env("ENGINE_EXTRACT_MODEL", DEFAULT_EXTRACT_MODEL),
                                 effort=_env("ENGINE_EXTRACT_EFFORT", DEFAULT_EXTRACT_EFFORT),
                                 api_key=anthropic_key, name="claude-extractor")
    if mode == "FAST":
        writer = AnthropicAnalyst(_env("ENGINE_WRITER_MODEL", DEFAULT_WRITER_MODEL),
                                  effort=_env("ENGINE_WRITER_EFFORT", DEFAULT_WRITER_EFFORT),
                                  api_key=anthropic_key, name="claude-writer")
        return EngineRoles(primary=extractor, independent=None, adjudicator=writer, writer=writer)
    effort = _env("ENGINE_SYNTHESIS_EFFORT", DEFAULT_SYNTHESIS_EFFORT)
    primary = RoutedAnalyst(extractor, AnthropicAnalyst(SYNTHESIS_MODEL, effort=effort, api_key=anthropic_key,
                                                        name="claude-primary-review"), name="claude-primary")
    adjudicator = AnthropicAnalyst(SYNTHESIS_MODEL, effort=effort, api_key=anthropic_key, name="claude-adjudicator")
    ind = OpenAIAnalyst(name="openai-independent") if independent == "openai" else None
    return EngineRoles(primary=primary, independent=ind, adjudicator=adjudicator)


def snapshot(run_: EngineRun) -> dict:
    return copy.deepcopy(run_.to_dict())
