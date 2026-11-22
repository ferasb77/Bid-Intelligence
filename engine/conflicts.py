"""Contradictions, clarifications and amendments as first-class register data.

Candidate relationships come from both analysts' package reviews, from
adjudication (superseded candidates) and from a deterministic scan (the same
kind of provision stated with different values). One bounded adjudication pass
classifies them. Precedence is accepted only with a verified express amendment
or order-of-precedence quote; recency alone never establishes it."""
from __future__ import annotations

import re

from engine import schema
from engine.package import SourcePackage
from engine.providers import Analyst, ProviderError, UsageLedger
from engine.register import _vals
from engine.verify import locate_quote, tokens

_SCANNED = {"DEADLINE", "SUBMISSION_METHOD", "GUARANTEE", "FINANCIAL_THRESHOLD", "DURATION", "PRICING",
            "PAYMENT", "EVALUATION"}
_STOP = {"the", "a", "an", "of", "to", "and", "or", "in", "on", "for", "by", "be", "is", "are", "with", "as",
         "at", "shall", "must", "will", "may", "should", "not", "no", "than", "later", "before", "after"}

CONFLICT_OUTPUT = schema._obj({"relationships": {"type": "array", "items": schema._obj({
    "candidate_id": schema._str(),
    "type": {"type": "string", "enum": ["CONSISTENT", "RESTATEMENT", "CLARIFICATION", "CONDITIONAL_EXCEPTION",
                                        "EXPRESS_AMENDMENT", "SUPERSEDED", "UNRESOLVED_CONTRADICTION",
                                        "NOT_RELATED"]},
    "prevailing_entry": schema._str("entry id that applies, only for EXPRESS_AMENDMENT/SUPERSEDED, else ''"),
    "superseded_entries": schema._strs("entry ids no longer applicable (EXPRESS_AMENDMENT/SUPERSEDED only)"),
    "authority_quote": schema._str("verbatim text establishing precedence (amendment wording or precedence "
                                   "rule), required for EXPRESS_AMENDMENT/SUPERSEDED"),
    "authority_document": schema._str(),
    "issue": schema._str("what differs, in one sentence"),
    "clarification_question": schema._str("neutral question for the buyer if unresolved, else ''"),
    "implication": schema._str("what it means for a bidder while unresolved, else ''")})}})

SYSTEM = """You classify relationships between provisions of one procurement package. For each candidate \
you receive the provisions (entry id, document, page, statement, verbatim quote), the package's \
order-of-precedence and amendment provisions, and the document list. Classify:
CONSISTENT / RESTATEMENT (same content), CLARIFICATION (explains without changing), CONDITIONAL_EXCEPTION \
(both apply under different conditions), EXPRESS_AMENDMENT (a provision expressly changes another), \
SUPERSEDED (expressly replaced), UNRESOLVED_CONTRADICTION (they cannot both apply and nothing in the package \
says which prevails), NOT_RELATED.
Rules: a later document or date does NOT by itself prevail -- only express amendment wording or a stated \
order-of-precedence rule does, and you must quote it verbatim in authority_quote. If you cannot quote such \
text, the relationship is UNRESOLVED_CONTRADICTION. For an unresolved contradiction, write a neutral \
clarification question and the implication for a bidder. Do not recommend which to follow."""


def _content_key(e: dict) -> set[str]:
    vals = {t for v in e.get("values") or [] for t in tokens(v.get("text") or "")}
    return {t for t in tokens(f"{e.get('party')} {e.get('action')}") if t not in _STOP and t not in vals
            and not t.isdigit()}


def scan_candidates(entries: list[dict]) -> list[list[str]]:
    live = [e for e in entries if e.get("category") in _SCANNED and e.get("applicability") in
            ("CURRENT", "AMBIGUOUS", "DISPUTED", "SUPERSEDED_CANDIDATE") and _vals(e)]
    out = []
    for i, a in enumerate(live):
        ka = _content_key(a)
        for b in live[i + 1:]:
            if a.get("category") != b.get("category") or not ka:
                continue
            kb = _content_key(b)
            if not kb or len(ka & kb) / len(ka | kb) < 0.5:
                continue
            if _vals(a) != _vals(b) and not (_vals(a) <= _vals(b) or _vals(b) <= _vals(a)):
                out.append([a["entry_id"], b["entry_id"]])
    return out


def collect_candidates(entries: list[dict], reviews: list[dict]) -> list[dict]:
    src_to_entry = {}
    for e in entries:
        for s in e["sources"] + e["partners"]:
            src_to_entry.setdefault(s, e["entry_id"])
    seen, cands = set(), []

    def add(ids, origin, note=""):
        ids = sorted({i for i in ids if i})
        key = tuple(ids)
        if len(ids) < 2 and origin != "adjudication" or key in seen:
            return
        seen.add(key)
        new = {"candidate_id": "", "entry_ids": ids, "origin": origin, "note": note}
        if origin != "adjudication":
            # one provision clash is adjudicated once: a set already covered by an
            # existing candidate is not added, and a superset replaces its subsets
            s = set(ids)
            peers = [c for c in cands if c["origin"] != "adjudication"]
            if any(s <= set(c["entry_ids"]) for c in peers):
                return
            subs = [c for c in peers if set(c["entry_ids"]) < s]
            if subs:
                cands[cands.index(subs[0])] = new
                for c in subs[1:]:
                    cands.remove(c)
                return
        cands.append(new)

    for rv in reviews:
        for r in rv.get("relationships") or []:
            if r.get("type") in ("CONSISTENT", "RESTATEMENT"):
                continue
            add([src_to_entry.get(f) for f in r.get("finding_ids") or []], "analyst_review", r.get("explanation", ""))
    for pair in scan_candidates(entries):
        add(pair, "value_scan", "the same kind of provision is stated with different values")
    for e in entries:
        if e.get("applicability") == "SUPERSEDED_CANDIDATE":
            amend = [x["entry_id"] for x in entries if x.get("category") in ("AMENDMENT", "DOCUMENT_AUTHORITY")
                     and x is not e][:6]
            add([e["entry_id"]] + amend, "adjudication", (e.get("supersession_claim") or {}).get("reason", ""))
    for n, c in enumerate(cands, 1):
        c["candidate_id"] = f"C{n:02d}"
    return cands


def resolve(adjudicator: Analyst, package: SourcePackage, entries: list[dict], reviews: list[dict],
            ledger: UsageLedger) -> dict:
    by_id = {e["entry_id"]: e for e in entries}
    cands = collect_candidates(entries, reviews)
    result = {"candidates": cands, "conflicts": [], "amendments": [], "clarifications": [], "errors": []}
    if not cands:
        _release_unconfirmed(entries)
        return result
    authority = [e for e in entries if e.get("category") in ("DOCUMENT_AUTHORITY", "AMENDMENT")]

    def line(e):
        return (f"{e['entry_id']} | {e.get('document')} p.{e.get('page')} | {e.get('category')} | "
                f"{e.get('statement')} || quote: \"{(e.get('quote') or '')[:500]}\"")
    user = ("DOCUMENTS (upload order, which does not imply precedence):\n" +
            "\n".join(f"- {d.name}" for d in package.documents) +
            "\n\nPRECEDENCE AND AMENDMENT PROVISIONS:\n" + ("\n".join(line(e) for e in authority) or "(none)") +
            "\n\nCANDIDATES:\n" + "\n\n".join(
                f"{c['candidate_id']} (noted: {c['note'][:200]})\n" + "\n".join(line(by_id[i]) for i in c["entry_ids"]
                                                                       if i in by_id) for c in cands))
    try:
        data = adjudicator.call_json(SYSTEM, user, CONFLICT_OUTPUT, purpose="conflicts", ledger=ledger,
                                     data_class=package.data_class, max_tokens=16000)
    except ProviderError as exc:
        result["errors"].append(str(exc)[:300])
        for c in cands:   # unclassified candidates stay visible as open items
            if c["origin"] != "adjudication":
                result["conflicts"].append({"entry_ids": c["entry_ids"], "type": "UNCLASSIFIED",
                                            "issue": c["note"], "clarification_question": "", "implication": ""})
        _release_unconfirmed(entries)
        return result
    cmap = {c["candidate_id"]: c for c in cands}
    for r in data.get("relationships") or []:
        c = cmap.get(r.get("candidate_id"))
        if not c:
            continue
        t = r.get("type")
        ids = [i for i in c["entry_ids"] if i in by_id]
        if t in ("EXPRESS_AMENDMENT", "SUPERSEDED"):
            loc = locate_quote(package, r.get("authority_quote") or "", r.get("authority_document") or "", "")
            old = [i for i in r.get("superseded_entries") or [] if i in ids and i != r.get("prevailing_entry")]
            new = r.get("prevailing_entry")
            if loc["status"] in ("VERIFIED", "RELOCATED") and old and new in ids:
                l2 = package.location(loc["loc_id"])
                for i in old:
                    by_id[i]["applicability"] = "SUPERSEDED"
                    by_id[i]["superseded_by"] = new
                    by_id[i]["relationships"].append({"type": "SUPERSEDED_BY", "entry_id": new})
                by_id[new]["relationships"].append({"type": "SUPERSEDES", "entry_ids": old})
                by_id[new]["previous"] = [{"entry_id": i, "statement": by_id[i].get("statement"),
                                           "document": by_id[i].get("document"), "page": by_id[i].get("page")}
                                          for i in old]
                result["amendments"].append({"prevailing": new, "superseded": old, "issue": r.get("issue"),
                                             "authority_quote": r.get("authority_quote"),
                                             "authority_ref": l2.ref() if l2 else ""})
                continue
            t = "UNRESOLVED_CONTRADICTION"       # precedence claimed without verifiable authority
            r = dict(r, issue=(r.get("issue") or "") + " (no verifiable amendment or precedence text)")
        if t == "UNRESOLVED_CONTRADICTION":
            for i in ids:
                if by_id[i].get("applicability") in ("CURRENT", "SUPERSEDED_CANDIDATE"):
                    by_id[i]["applicability"] = "CONFLICTED"
                by_id[i]["relationships"].append({"type": "CONFLICTS_WITH", "entry_ids": [x for x in ids if x != i]})
            result["conflicts"].append({"entry_ids": ids, "type": t, "issue": r.get("issue"),
                                        "clarification_question": r.get("clarification_question"),
                                        "implication": r.get("implication")})
            if r.get("clarification_question"):
                result["clarifications"].append({"entry_ids": ids, "question": r["clarification_question"]})
        elif t in ("CLARIFICATION", "CONDITIONAL_EXCEPTION"):
            for i in ids:
                by_id[i]["relationships"].append({"type": t, "entry_ids": [x for x in ids if x != i]})
    _release_unconfirmed(entries)
    return result


def _release_unconfirmed(entries: list[dict]) -> None:
    """A superseded candidate that was not confirmed with verified authority
    stays applicable (and visible), never silently dropped."""
    for e in entries:
        if e.get("applicability") == "SUPERSEDED_CANDIDATE":
            e["applicability"] = "CURRENT"
            e.setdefault("uncertainty", "")
            e["uncertainty"] = (e["uncertainty"] + " Possibly superseded, but no verifiable amendment text was "
                                "found.").strip()


def affected_by_new_documents(entries: list[dict], new_docs: list[str]) -> list[str]:
    """Entry ids whose topic a newly added document also addresses -- used on
    package updates so earlier conclusions are re-examined, not assumed valid."""
    new = {re.sub(r"\s+", " ", d.lower()) for d in new_docs}
    fresh = [e for e in entries if re.sub(r"\s+", " ", str(e.get("document")).lower()) in new]
    out = []
    for e in entries:
        if e in fresh:
            continue
        ke = _content_key(e)
        if any(f.get("category") == e.get("category") and ke and
               len(ke & _content_key(f)) / max(1, len(ke | _content_key(f))) >= 0.4 for f in fresh):
            out.append(e["entry_id"])
    return out
