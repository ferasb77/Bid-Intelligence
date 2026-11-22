"""Independent, source-oriented extraction by one analyst.

The package is read in units of consecutive pages/sections. Each unit's
answer must account for every location it was given (findings, or an
explicit "no material provisions" / "unreadable"), so silent coverage loss is
detected. An analyst never sees the other analyst's output.

The prompts are general-purpose procurement instructions. They contain no
example from any evaluation document, buyer or RFP."""
from __future__ import annotations

import concurrent.futures
import dataclasses
import os

from engine import schema
from engine.package import Location, SourcePackage, Unit, units
from engine.providers import (Analyst, ProviderError, ProviderNotAuthorized, ProviderNotConfigured,
                              ProviderOutputLimit, ProviderUnavailable, UsageLedger)

#: How many times one location's text may be halved after its answer hit the
#: output-token limit (2 = at most four parts, seven calls for that location).
MAX_TEXT_SPLITS = 2
_SEPARATORS = ("\n\n", "\n", ". ", "; ", " ")

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
because their wording is similar. Enumerated lists and grouped exclusions: when a clause enumerates items or \
groups several exclusions or conditions with "and"/"or" (for example several eligibility disqualifiers, required \
proposal sections, or conditions), preserve EVERY listed item -- either keep the complete enumerated list intact \
in one statement, or record a separate finding for every single item. Zero omissions: never summarise a list, \
keep only its first items, or replace items with "etc." or "such as".
2. The quote must be copied verbatim from the page (same words, same order). Do not correct, translate or \
abbreviate it. Use " ... " only to join non-adjacent parts of the same page. Give the document name exactly as \
in the SOURCE marker and the page/sheet from the section marker that contains the quote.
3. The statement restates the quote faithfully: keep who is bound, the exact modal force (must / must not / \
should / may / will / is), every condition, exception, alternative, number, date, amount, unit, currency and \
qualifier ("only", "at least", "not later than", "either ... or", "unless"). "Will" is not "must"; "may" is not \
"must"; "should" is not "must". Add nothing the text does not say: no consequence, weight, date or obligation \
that is not stated. A statement covering an enumerated list or a grouped and/or exclusion names every listed \
item.
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


def split_text(text: str) -> tuple[str, str] | None:
    """Two verbatim halves of `text`, cut at the clean boundary nearest the
    middle: a blank line, else a line break, else a sentence or clause end,
    else a space -- never inside a word, and never so far from the middle that
    one half keeps most of the text. None when the text cannot be split."""
    n = len(text)
    lo, hi, mid = n // 4, n - n // 4, n // 2
    for sep in _SEPARATORS:
        best = None
        for i in (text.rfind(sep, 0, mid + len(sep)), text.find(sep, mid)):
            if i < 0:
                continue
            cut = i + len(sep)
            if lo <= cut <= hi and text[:cut].strip() and text[cut:].strip() and (
                    best is None or abs(cut - mid) < abs(best - mid)):
                best = cut
        if best is not None:
            return text[:best].rstrip(), text[best:].lstrip()
    return None


def _text_parts(text: str, max_chars: int, limit: int = 64) -> list[str]:
    """`text` in clean-boundary parts of at most ~max_chars (pre-emptive
    sizing of one oversized page/section; bounded to `limit` parts)."""
    parts, todo = [], [text]
    while todo:
        t = todo.pop(0)
        halves = split_text(t) if len(t) > max_chars and len(parts) + len(todo) < limit - 1 else None
        if halves:
            todo[:0] = list(halves)
        else:
            parts.append(t)
    return parts


def _part(loc: Location, text: str) -> Location:
    """A slice of one location: same id, document and page/section label, so
    accounting and quote verification still refer to the whole location."""
    return dataclasses.replace(loc, text=text)


def _merge(results: list[dict]) -> dict:
    """Combines the answers for parts of the same unit. A location counts as
    accounted for if any part accounted for it; extraction failures remain."""
    findings = [f for r in results for f in r["findings"]]
    accounts, by_id = [], {}
    for a in (a for r in results for a in r["accounts"]):
        sid = a.get("section_id")
        if sid not in by_id:
            by_id[sid] = len(accounts)
            accounts.append(a)
        elif a.get("status") == "HAS_FINDINGS":
            accounts[by_id[sid]] = a
    gaps, seen = [], set()
    for g in (g for r in results for g in r["gaps"]):
        if g["reason"] == "not accounted for by the analyst" and g["loc_id"] in by_id:
            continue
        # one failure per location, however many of its parts failed
        key = (g["loc_id"], "failed" if str(g["reason"]).startswith("extraction failed") else g["reason"])
        if key not in seen:
            seen.add(key)
            gaps.append(g)
    return {"findings": findings, "accounts": accounts, "gaps": gaps}


def _split_unit(analyst, package, unit, ctx, ledger, depth, split) -> dict | None:
    """Re-asks for a single-location unit whose answer hit the output limit,
    one half of its text at a time. None when it cannot be split further."""
    if len(unit.locations) != 1 or split >= MAX_TEXT_SPLITS:
        return None
    halves = split_text(unit.locations[0].text)
    if not halves:
        return None
    return _merge([_extract_unit(analyst, package, Unit(f"{unit.unit_id}s{k}", unit.doc,
                                                        [_part(unit.locations[0], half)]),
                                 ctx, ledger, depth, split + 1)
                   for k, half in enumerate(halves, 1)])


def _extract_unit(analyst, package, unit, ctx, ledger, depth=0, split=0) -> dict:
    """Returns {"findings", "accounts", "gaps"}. A unit whose answer did not
    fit is halved by location; a single location whose answer hit the output
    limit is halved by text on a paragraph/line boundary (at most
    MAX_TEXT_SPLITS times). Locations the answer did not account for are
    re-asked once."""
    try:
        data = _call_unit(analyst, package, unit, ctx, ledger)
    except (ProviderNotAuthorized, ProviderNotConfigured, ProviderUnavailable):
        raise
    except ProviderError as exc:
        if len(unit.locations) > 1 and depth < 4:
            mid = len(unit.locations) // 2
            return _merge([_extract_unit(analyst, package, Unit(unit.unit_id + sfx, unit.doc, locs), ctx, ledger,
                                         depth + 1, split)
                           for sfx, locs in (("a", unit.locations[:mid]), ("b", unit.locations[mid:]))])
        if isinstance(exc, ProviderOutputLimit):
            halved = _split_unit(analyst, package, unit, ctx, ledger, depth, split)
            if halved is not None:
                return halved
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
        retry = _extract_unit(analyst, package, Unit(unit.unit_id + "r", unit.doc, missing), ctx, ledger, depth + 5,
                              split)
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


def _extract_sized(analyst, package, unit, ctx, ledger) -> dict:
    """A single page/section longer than the unit size is read in
    clean-boundary parts up front, so one dense location does not routinely
    exhaust the output limit (units() never cuts a location itself)."""
    max_chars = ctx.get("max_chars") or 10 ** 9
    if len(unit.locations) == 1 and len(unit.locations[0].text) > max_chars:
        parts = _text_parts(unit.locations[0].text, max_chars)
        if len(parts) > 1:
            return _merge([_extract_unit(analyst, package, Unit(f"{unit.unit_id}p{k}", unit.doc,
                                                                [_part(unit.locations[0], t)]), ctx, ledger)
                           for k, t in enumerate(parts, 1)])
    return _extract_unit(analyst, package, unit, ctx, ledger)


def extract(analyst: Analyst, package: SourcePackage, ledger: UsageLedger, *, tag: str,
            concurrency: int | None = None, progress=None) -> dict:
    """One analyst's complete, independent inventory of the package."""
    analyst.check_allowed(package.data_class)
    max_chars = int(os.getenv("ENGINE_UNIT_CHARS", "10000"))
    us = units(package, max_chars=max_chars)   # smaller units run in parallel
    ctx = {"documents": _doc_list(package), "definitions": package.definitions(), "outline": package.outline(),
           "max_chars": max_chars}
    workers = concurrency or int(os.getenv("ENGINE_CONCURRENCY", "4"))
    results: dict[str, dict] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futs = {pool.submit(_extract_sized, analyst, package, u, ctx, ledger): u for u in us}
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
