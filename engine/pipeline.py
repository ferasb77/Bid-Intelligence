"""End-to-end orchestration of one analysis of one package.

The run record states exactly which models and configurations ran, what
failed and what the verification status is. A report is labelled
INDEPENDENTLY_VERIFIED only when two real (non-synthetic) analysts from
different providers both completed, adjudication and review ran, the ledger
is complete and every page was readable. Anything less is labelled as what it
is; a failed independent pass can never yield a "verified" report."""
from __future__ import annotations

import concurrent.futures
import copy
import time
from dataclasses import dataclass, field

from engine import ENGINE_VERSION, adjudicate as adj, conflicts as cf, extraction, register as rg, reports, review
from engine.package import SourcePackage
from engine.providers import (Analyst, ProviderError, ProviderNotAuthorized, ProviderNotConfigured,
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


def run(package: SourcePackage, roles: EngineRoles, *, ledger: UsageLedger | None = None, progress=None,
        research: dict | None = None, research_fn=None, previous: dict | None = None) -> EngineRun:
    """previous: an earlier run of the SAME bid ({"register": ..., "documents": [...]}) for update labelling."""
    t0 = time.monotonic()
    ledger = ledger or UsageLedger(package.package_hash[:12])
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
        stage(f"extract_{tag}", "OK" if tag in results else "FAILED", error=errors.get(tag),
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
    stage("adjudicate", "OK" if not adj_stats["failed_batches"] else "PARTIAL", targets=len(targets), **adj_stats)

    # 4. conflicts, clarifications, amendments
    reviews = [inv.get("review") or {} for inv in (inv_a, inv_b) if inv]
    out.conflicts = cf.resolve(roles.adjudicator, package, entries, reviews, ledger)
    stage("conflicts", "OK" if not out.conflicts["errors"] else "PARTIAL",
          conflicts=len(out.conflicts["conflicts"]), amendments=len(out.conflicts["amendments"]))
    prev_entries = (previous or {}).get("register", {}).get("entries") if previous else None
    new_docs = [d.name for d in package.documents if previous and d.name not in set(previous.get("documents") or [])]
    rec["update"] = {"previous_run": (previous or {}).get("run_id"), "new_documents": new_docs,
                     "re_examined_entries": _mark_updates(entries, prev_entries, new_docs)} if previous else None

    # 5. analysis writing + composition
    out.analysis = reports.analysis(roles.adjudicator, entries, ledger, package.data_class,
                                    run_date=str(rec.get("started_at") or "")[:10])
    stage("analysis", "OK" if not out.analysis.get("error") else "FAILED", rejected=len(out.analysis["rejected"]))
    if research is None and research_fn is not None:   # external buyer research, kept apart from document facts
        try:
            research = research_fn(out.analysis)
        except Exception as exc:
            research = {"status": "FAILED", "error": str(exc)[:200]}
        stage("buyer_research", (research or {}).get("status") or "NONE")
    rec["buyer_research_status"] = (research or {}).get("status")

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
    stage("review", "OK" if not mr.get("error") else "FAILED", applied=len(corr["applied"]),
          unresolved=len(corr["unresolved"]), added=len(corr["added"]), deterministic=len(det_after))

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
    blocking = []
    for tag, inv in (("primary", inv_a), ("independent", inv_b)):
        failed_locs = [g for g in (inv or {}).get("gaps") or []
                       if str(g.get("reason", "")).startswith("extraction failed")]
        if failed_locs:
            blocking.append(f"{tag} extraction failed for {len(failed_locs)} of {len(package.locations)} "
                            f"page(s)/section(s): {failed_locs[0]['reason'][:200]}")
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


def default_roles(*, anthropic_key: str | None = None, independent: str | None = "openai") -> EngineRoles:
    """Opus 5.5 primary/adjudicator; OpenAI independent analyst (refuses client
    data until authorized -- the run then records SINGLE_ANALYST)."""
    from engine.providers import AnthropicAnalyst, OpenAIAnalyst
    primary = AnthropicAnalyst("claude-opus-5-5", effort="high", api_key=anthropic_key, name="claude-primary")
    adjudicator = AnthropicAnalyst("claude-opus-5-5", effort="high", api_key=anthropic_key, name="claude-adjudicator")
    ind = OpenAIAnalyst(name="openai-independent") if independent == "openai" else None
    return EngineRoles(primary=primary, independent=ind, adjudicator=adjudicator)


def snapshot(run_: EngineRun) -> dict:
    return copy.deepcopy(run_.to_dict())
