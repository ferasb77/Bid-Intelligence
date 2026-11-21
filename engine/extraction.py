"""Independent, source-oriented extraction by one analyst.

The package is read in units of consecutive pages/sections. Each unit's
answer must account for every location it was given (findings, or an
explicit "no material provisions" / "unreadable"), so silent coverage loss is
detected. An analyst never sees the other analyst's output.

The prompts are general-purpose procurement instructions. They contain no
example from any evaluation document, buyer or RFP."""
from __future__ import annotations

import concurrent.futures
import os

from engine import schema
from engine.package import SourcePackage, Unit, units
from engine.providers import (Analyst, ProviderError, ProviderNotAuthorized, ProviderNotConfigured,
                              ProviderUnavailable, UsageLedger)

SYSTEM = """You are a senior procurement analyst. You read procurement documents (RFPs, ITBs, terms of reference, \
specifications, annexes, forms, price schedules, clarifications, addenda) and record every provision a bidder \
needs, exactly as the documents state it. Your record is checked word-for-word against the source, and \
anything you miss may cause a bidder to be excluded, so be complete and literal.

Rules:
1. Record a finding for every material provision: each eligibility condition, qualification, required document \
or form, submission instruction, deadline or date, submission method and address, guarantee or security, \
financial threshold, disqualification or rejection ground, evaluation criterion and weight, pricing and payment \
term, contractual obligation or restriction, duration, deliverable, scope element, risk or dependency, \
cross-reference, order-of-precedence rule, and every amendment or clarification. One finding per provision: \
if a sentence or list states several requirements, record each separately. Never merge two requirements \
because their wording is similar.
2. The quote must be copied verbatim from the page (same words, same order). Do not correct, translate or \
abbreviate it. Use " ... " only to join non-adjacent parts of the same page. Give the document name exactly as \
in the SOURCE marker and the page/sheet from the section marker that contains the quote.
3. The statement restates the quote faithfully: keep who is bound, the exact modal force (must / must not / \
should / may / will / is), every condition, exception, alternative, number, date, amount, unit, currency and \
qualifier ("only", "at least", "not later than", "either ... or", "unless"). "Will" is not "must"; "may" is not \
"must"; "should" is not "must". Add nothing the text does not say: no consequence, weight, date or obligation \
that is not stated.
4. Values: list each date, time, amount, percentage, duration, quantity, e-mail address, URL and reference \
number exactly as written in the quote.
5. Interpret defined terms as the package defines them. Record cross-references ("as specified in Annex B") as \
relations and keep the reference in the statement; do not invent the referenced content.
6. Geography of an organisation or programme is not the place of delivery unless the text says the work is \
delivered there.
7. Ignore tables of contents, running headers/footers and blank template fields -- but a requirement to submit \
a form IS a finding.
8. Uncertainty: if a provision is ambiguous, contradictory or partly illegible, say so in `uncertainty` instead \
of resolving it.
9. Account for every SECTION_ID you are given: HAS_FINDINGS, NO_MATERIAL_PROVISIONS (say briefly what it \
contains) or UNREADABLE (the text is garbled, missing or not interpretable).
10. Category = what the provision governs for the bidder. The period for which a bid must remain valid is a SUBMISSION_REQUIREMENT (DURATION is the contract or delivery period). A clarification or amendment that changes a provision takes the category of the provision it changes; use AMENDMENT only for changes without a single affected provision.
11. Do not evaluate, recommend or speculate. Record only what these documents say."""

UNIT_TEMPLATE = """PACKAGE DOCUMENTS:
{documents}

DEFINED TERMS IN THIS PACKAGE (for interpretation only; record a definition as a finding only where it is \
material):
{definitions}

DOCUMENT OUTLINE (for resolving cross-references):
{outline}

Extract every material provision from the following part of "{doc}". Account for each SECTION_ID: {ids}

{text}"""

PACKAGE_REVIEW_SYSTEM = """You are a senior procurement analyst reviewing your own extraction of a procurement \
package as a whole. You receive the package's document list and your findings (id, location, category, \
statement). Tasks:
1. Identify each document's role and the version/issue it states for itself.
2. Identify relationships between findings that matter to a bidder: restatements, clarifications, conditional \
exceptions, express amendments, superseded provisions, and unresolved contradictions (for example two \
different deadlines, amounts, methods or conditions for the same thing). A later date of issue does NOT by \
itself make a provision prevail: only an express amendment or a stated order-of-precedence rule does. When \
claiming that one provision prevails, give the verbatim authority_quote that establishes it (from the \
findings' quotes or the package text you were given); otherwise classify it as UNRESOLVED_CONTRADICTION and \
propose a neutral clarification question.
3. List material provisions you can see are missing from your findings, only if you are certain they are in \
the documents (with verbatim quote and location).
Do not evaluate or recommend."""


def _doc_list(package: SourcePackage) -> str:
    return "\n".join(f"- {d.name} ({len(d.locations)} sections/pages)" for d in package.documents)


def _call_unit(analyst: Analyst, package: SourcePackage, unit: Unit, ctx: dict, ledger: UsageLedger) -> dict:
    ids = ", ".join(loc.loc_id for loc in unit.locations)
    full = UNIT_TEMPLATE.format(documents=ctx["documents"], definitions=ctx["definitions"] or "(none found)",
                                outline=ctx["outline"] or "(none found)", doc=unit.doc, ids=ids, text=unit.text())
    cut = full.index("Extract every material provision")
    user = (full[:cut].rstrip(), full[cut:])     # package context is shared by every unit: cached
    return analyst.call_json(SYSTEM, user, schema.EXTRACTION_OUTPUT, purpose=f"extract:{unit.unit_id}",
                             ledger=ledger, data_class=package.data_class)


def _extract_unit(analyst, package, unit, ctx, ledger, depth=0) -> dict:
    """Returns {"findings", "accounts", "gaps"}; halves a unit whose answer
    did not fit, and re-asks once for locations the answer did not account for."""
    try:
        data = _call_unit(analyst, package, unit, ctx, ledger)
    except (ProviderNotAuthorized, ProviderNotConfigured, ProviderUnavailable):
        raise
    except ProviderError as exc:
        if len(unit.locations) > 1 and depth < 4:
            mid = len(unit.locations) // 2
            a = _extract_unit(analyst, package, Unit(unit.unit_id + "a", unit.doc, unit.locations[:mid]), ctx,
                              ledger, depth + 1)
            b = _extract_unit(analyst, package, Unit(unit.unit_id + "b", unit.doc, unit.locations[mid:]), ctx,
                              ledger, depth + 1)
            return {"findings": a["findings"] + b["findings"], "accounts": a["accounts"] + b["accounts"],
                    "gaps": a["gaps"] + b["gaps"]}
        return {"findings": [], "accounts": [],
                "gaps": [{"loc_id": loc.loc_id, "ref": loc.ref(), "reason": f"extraction failed: {exc}"[:300]}
                         for loc in unit.locations]}
    findings = [f for f in data.get("findings") or [] if isinstance(f, dict)]
    accounts = [a for a in data.get("sections") or [] if isinstance(a, dict)]
    ids = {loc.loc_id for loc in unit.locations}
    seen = {a.get("section_id") for a in accounts} | {
        loc.loc_id for f in findings for loc in unit.locations
        if (f.get("page") or "").strip() == loc.label and f.get("document") == loc.doc}
    missing = [loc for loc in unit.locations if loc.loc_id not in seen]
    accounts = [a for a in accounts if a.get("section_id") in ids]
    gaps = []
    if missing and depth == 0:
        retry = _extract_unit(analyst, package, Unit(unit.unit_id + "r", unit.doc, missing), ctx, ledger, depth + 5)
        findings += retry["findings"]
        accounts += retry["accounts"]
        gaps += retry["gaps"]
        still = {loc.loc_id for loc in missing} - {a.get("section_id") for a in retry["accounts"]}
        gaps += [{"loc_id": loc.loc_id, "ref": loc.ref(), "reason": "not accounted for by the analyst"}
                 for loc in missing if loc.loc_id in still and not any(g["loc_id"] == loc.loc_id for g in gaps)]
    elif missing:
        gaps += [{"loc_id": loc.loc_id, "ref": loc.ref(), "reason": "not accounted for by the analyst"}
                 for loc in missing]
    return {"findings": findings, "accounts": accounts, "gaps": gaps}


def extract(analyst: Analyst, package: SourcePackage, ledger: UsageLedger, *, tag: str,
            concurrency: int | None = None, progress=None) -> dict:
    """One analyst's complete, independent inventory of the package."""
    analyst.check_allowed(package.data_class)
    us = units(package, max_chars=int(os.getenv("ENGINE_UNIT_CHARS", "10000")))   # smaller units run in parallel
    ctx = {"documents": _doc_list(package), "definitions": package.definitions(), "outline": package.outline()}
    workers = concurrency or int(os.getenv("ENGINE_CONCURRENCY", "4"))
    results: dict[str, dict] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futs = {pool.submit(_extract_unit, analyst, package, u, ctx, ledger): u for u in us}
        for n, fut in enumerate(concurrent.futures.as_completed(futs), 1):
            u = futs[fut]
            try:
                results[u.unit_id] = fut.result()
            except (ProviderNotAuthorized, ProviderNotConfigured, ProviderUnavailable):
                for f in futs:
                    f.cancel()
                raise
            except Exception as exc:  # never lose the rest of the package to one unit
                results[u.unit_id] = {"findings": [], "accounts": [], "gaps": [
                    {"loc_id": loc.loc_id, "ref": loc.ref(), "reason": f"extraction failed: {exc}"[:300]}
                    for loc in u.locations]}
            if progress:
                progress(tag, n, len(us))
    findings, accounts, gaps = [], [], []
    for u in us:
        r = results.get(u.unit_id) or {}
        for i, f in enumerate(r.get("findings") or [], 1):
            findings.append(dict(f, id=f"{tag}-{u.unit_id}-{i:02d}", analyst=tag))
        accounts += r.get("accounts") or []
        gaps += r.get("gaps") or []
    return {"analyst": analyst.describe(), "tag": tag, "units": len(us), "findings": findings,
            "accounts": accounts, "gaps": gaps}


def package_review(analyst: Analyst, package: SourcePackage, inventory: dict, ledger: UsageLedger) -> dict:
    """The analyst's own package-level pass over its own findings."""
    lines = [f"{f['id']} | {f.get('document')} p.{f.get('page')} | {f.get('category')} | {f.get('modality')} | "
             f"{f.get('statement')} || quote: {(f.get('quote') or '')[:300]}" for f in inventory["findings"]]
    user = (f"PACKAGE DOCUMENTS:\n{_doc_list(package)}\n\nFIRST PAGE OF EACH DOCUMENT:\n" +
            "\n\n".join(f"--- {d.name} ---\n{(d.locations[0].text if d.locations else '')[:2500]}"
                        for d in package.documents) +
            "\n\nYOUR FINDINGS:\n" + "\n".join(lines))
    try:
        return analyst.call_json(PACKAGE_REVIEW_SYSTEM, user, schema.PACKAGE_REVIEW_OUTPUT,
                                 purpose="package_review", ledger=ledger, data_class=package.data_class)
    except (ProviderNotAuthorized, ProviderNotConfigured, ProviderUnavailable):
        raise
    except ProviderError as exc:
        return {"documents": [], "relationships": [], "missed": [], "error": str(exc)[:300]}
