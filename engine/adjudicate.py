"""Bounded, evidence-based adjudication of disputed, single-analyst and
unverified register entries: one pass, the cited source pages in front of the
adjudicator, both interpretations shown anonymously (neither is authoritative).

Safeguards applied in code, not trusted to the model:
* a corrected statement is accepted only if its quote verifies against the
  package and its figures come from that quote;
* a verified provision is never erased -- an interpretation judged
  unsupported keeps the provision in the register, excluded from the reports
  with its reason, and listed for traceability;
* "superseded" is only a candidate here; conflicts.py accepts it only with a
  verified express amendment or precedence rule."""
from __future__ import annotations

import concurrent.futures
import os

from engine import schema
from engine.package import SourcePackage
from engine.budget import max_tokens as _max_tokens
from engine.providers import Analyst, ProviderError, StageBudgetExceeded, UsageLedger
from engine.verify import locate_quote, value_issues

SYSTEM = """You are the adjudicator for a procurement evidence register. For each entry you receive one or two \
interpretations (labelled A and B; neither is authoritative and either may be wrong) of a provision, and the \
source page(s). Decide strictly from the source text:
- CONFIRMED: an interpretation is faithful (preferred = A, B or BOTH). If neither is perfectly faithful, use \
CORRECTED.
- CORRECTED: give the faithful statement, with the exact modal force (must/must not/should/may/will/is), every \
condition, exception, alternative, number and date, and a verbatim supporting quote. When the provision \
contains an enumerated list or a grouped and/or exclusion (for example several eligibility disqualifiers, \
required proposal sections, or conditions), the corrected statement must preserve EVERY listed item: keep the \
complete list intact; never drop, summarise or truncate items, and never replace them with "etc." or "such as".
- BOTH_VALID_DIFFERENT_CONDITIONS: both are correct under different stated conditions; give one statement that \
states both with their conditions.
- SUPERSEDED: the excerpt itself shows this provision was expressly replaced or amended (quote the replacing \
text). A later date alone is not enough.
- AMBIGUOUS_SOURCE: the source itself is ambiguous or contradictory; state the provision neutrally and say \
what is unclear in `reason`.
- UNSUPPORTED: the interpretation is not supported by the source (state why). If the quoted text exists but \
was misread, use CORRECTED instead.
- DUPLICATE: the entry states exactly the same requirement as another listed entry (give duplicate_of). Two \
requirements with similar wording but different parties, items, conditions or values are NOT duplicates.
Never add obligations, consequences, weights, figures or dates the source does not state. Quotes must be \
copied verbatim from the excerpt."""


def _excerpt(package: SourcePackage, loc_ids: list[str], limit: int = 24000) -> str:
    out, seen = [], set()
    for lid in loc_ids:
        loc = package.location(lid) if lid else None
        if not loc or lid in seen:
            continue
        seen.add(lid)
        d = package.document(loc.doc)
        idx = d.locations.index(loc) if d and loc in d.locations else -1
        nxt = d.locations[idx + 1] if d and 0 <= idx < len(d.locations) - 1 else None
        out.append(f"=== {loc.ref()} ===\n{loc.text}")
        if nxt is not None and nxt.loc_id not in seen:
            out.append(f"=== {nxt.ref()} (following page) ===\n{nxt.text[:4000]}")
    text = "\n\n".join(out)
    return text[:limit]


def _entry_block(e: dict, labels: dict[str, str]) -> str:
    lines = [f"ENTRY {e['entry_id']} | cited: {e.get('document')} {e.get('page')} | status: {e['status']}"]
    if e.get("differences"):
        lines.append("  differences: " + "; ".join(e["differences"]))
    vi = (e.get("verification") or {}).get("issues")
    if vi:
        lines.append("  verification issues: " + "; ".join(vi))
    if (e.get("verification") or {}).get("quote_status") in ("NOT_FOUND", "EMPTY"):
        lines.append("  verification issue: the quoted text was not found in the package")
    for sid, it in e["interpretations"].items():
        lines.append(f"  {labels.get(sid, '?')}: [{it.get('category')}, {it.get('modality')}] {it.get('statement')}"
                     f" | conditions: {it.get('conditions') or []} | exceptions: {it.get('exceptions') or []}"
                     f" | values: {[v.get('text') for v in it.get('values') or []]}"
                     f" | consequence: {it.get('consequence') or '-'} | quote: \"{it.get('quote')}\"")
    return "\n".join(lines)


def _batches(entries: list[dict], size: int = 12) -> list[list[dict]]:
    by_loc: dict[str, list[dict]] = {}
    for e in entries:
        by_loc.setdefault(str((e.get("verification") or {}).get("loc_id") or e.get("document")), []).append(e)
    out, cur = [], []
    for group in by_loc.values():
        for e in group:
            cur.append(e)
            if len(cur) >= size:
                out.append(cur)
                cur = []
        if len(cur) >= size // 2:
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def _apply(package: SourcePackage, e: dict, d: dict, by_id: dict) -> None:
    decision = d.get("decision")
    rec = {"decision": decision, "preferred": d.get("preferred"), "reason": d.get("reason"), "accepted": True}
    e["adjudication"] = rec
    quote_ok = (e.get("verification") or {}).get("quote_status") in ("VERIFIED", "RELOCATED")

    def take_statement(statement: str, quote: str, modality: str | None) -> bool:
        loc = locate_quote(package, quote, e.get("document") or "", e.get("page") or "")
        if loc["status"] not in ("VERIFIED", "RELOCATED"):
            rec.update(accepted=False, rejected_because="the adjudicator's quote was not found in the package")
            return False
        probe = {"statement": statement, "quote": quote, "values": [], "conditions": [], "exceptions": []}
        issues = value_issues(probe)
        if issues:
            rec.update(accepted=False, rejected_because="; ".join(issues))
            return False
        l2 = package.location(loc["loc_id"])
        e.update(statement=statement, quote=quote, document=l2.doc, page=l2.label)
        if modality:
            e["modality"] = modality
        e["verification"] = dict(e.get("verification") or {}, status="VERIFIED", quote_status=loc["status"],
                                 loc_id=loc["loc_id"], span=list(loc["span"]), issues=[])
        return True

    interp = e["interpretations"]
    ids = list(interp)
    if decision == "CONFIRMED":
        pref = d.get("preferred")
        pick = ids[0] if pref in ("A", "BOTH") or len(ids) == 1 else ids[1] if pref == "B" else None
        if pick and pick != e["sources"][0]:
            it = interp[pick]
            if not take_statement(it.get("statement") or "", it.get("quote") or "", it.get("modality")):
                e["status"] = "DISPUTED"
                return
            e.update(conditions=it.get("conditions"), exceptions=it.get("exceptions"), values=it.get("values"),
                     category=it.get("category") or e.get("category"), consequence=it.get("consequence"))
        if e["status"] == "UNVERIFIED" or (e.get("verification") or {}).get("status") == "VALUE_MISMATCH":
            rec.update(accepted=False, rejected_because="confirmed text still fails source verification")
            e["applicability"] = "EXCLUDED_UNVERIFIED"
            return
        e["status"] = "ADJUDICATED"
    elif decision in ("CORRECTED", "BOTH_VALID_DIFFERENT_CONDITIONS", "AMBIGUOUS_SOURCE"):
        if take_statement(d.get("statement") or "", d.get("quote") or "", d.get("modality")):
            e["status"] = "ADJUDICATED"
            e["conditions"], e["exceptions"] = [], []   # restated in the corrected statement itself
            e["values"] = [v for v in e.get("values") or [] if v.get("text") and v["text"] in (d.get("quote") or "")]
            if decision == "AMBIGUOUS_SOURCE":
                e["applicability"] = "AMBIGUOUS"
                e["uncertainty"] = d.get("reason") or e.get("uncertainty")
        else:
            e["applicability"] = "EXCLUDED_UNVERIFIED" if not quote_ok else "DISPUTED"
    elif decision == "SUPERSEDED":
        e["applicability"] = "SUPERSEDED_CANDIDATE"
        e["supersession_claim"] = {"quote": d.get("quote"), "reason": d.get("reason")}
        e["status"] = "ADJUDICATED"
    elif decision == "UNSUPPORTED":
        e["applicability"] = "EXCLUDED_UNSUPPORTED" if quote_ok else "EXCLUDED_UNVERIFIED"
    elif decision == "DUPLICATE":
        twin = by_id.get(d.get("duplicate_of") or "")
        same_page = twin and (twin.get("verification") or {}).get("loc_id") == (e.get("verification") or {}).get("loc_id")
        if twin and twin is not e and (same_page or twin.get("modality") == e.get("modality")):
            e["applicability"] = "DUPLICATE"
            e["duplicate_of"] = twin["entry_id"]
        else:
            rec.update(accepted=False, rejected_because="duplicate target missing or not the same provision")
    else:
        rec.update(accepted=False, rejected_because=f"unknown decision {decision!r}")


def adjudicate(adjudicator: Analyst, package: SourcePackage, entries: list[dict], targets: list[dict],
               ledger: UsageLedger, *, concurrency: int | None = None) -> dict:
    """Adjudicates `targets` (a subset of `entries`) in place. Returns stats."""
    by_id = {e["entry_id"]: e for e in entries}
    stats = {"adjudicated": 0, "failed_batches": 0, "decisions": {}}
    batches = _batches(targets)

    def run(batch):
        labels = {}
        for e in batch:
            for n, sid in enumerate(e["interpretations"]):
                labels[sid] = "AB"[n] if n < 2 else f"C{n}"
        locs = [(e.get("verification") or {}).get("loc_id") or
                (package.find_location(e.get("document") or "", e.get("page") or "") or
                 type("x", (), {"loc_id": None})).loc_id for e in batch]
        neighbours = [x["entry_id"] + ": " + (x.get("statement") or "")[:200] for x in entries
                      if (x.get("verification") or {}).get("loc_id") in set(locs) and x not in batch][:40]
        user = ("SOURCE EXCERPT:\n" + _excerpt(package, locs) + "\n\nOTHER ENTRIES ON THESE PAGES (for DUPLICATE "
                "decisions only):\n" + ("\n".join(neighbours) or "(none)") + "\n\nENTRIES TO ADJUDICATE:\n" +
                "\n\n".join(_entry_block(e, labels) for e in batch))
        return adjudicator.call_json(SYSTEM, user, schema.ADJUDICATION_OUTPUT, purpose="adjudicate",
                                     ledger=ledger, data_class=package.data_class,
                                     max_tokens=_max_tokens("adjudicate"))

    # at most two batches in flight, so the stage's worst-case reservations do not
    # crowd each other out of its allotment while answers are still coming in
    workers = concurrency or int(os.getenv("ENGINE_ADJUDICATE_CONCURRENCY", "2"))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futs = {pool.submit(run, b): b for b in batches}
        for fut in concurrent.futures.as_completed(futs):
            batch = futs[fut]
            try:
                decisions = {d.get("entry_id"): d for d in (fut.result().get("decisions") or [])}
            except StageBudgetExceeded as exc:
                # not run: the stage's budget could not cover the batch. Its entries stay
                # disputed / excluded (below) and the run discloses how many were deferred.
                stats["deferred_batches"] = stats.get("deferred_batches", 0) + 1
                stats["deferred_entries"] = stats.get("deferred_entries", 0) + len(batch)
                for e in batch:
                    e["adjudication"] = {"decision": None, "accepted": False, "deferred": True,
                                         "error": str(exc)[:200]}
                continue
            except ProviderError as exc:
                stats["failed_batches"] += 1
                for e in batch:
                    e["adjudication"] = {"decision": None, "accepted": False, "error": str(exc)[:200]}
                continue
            for e in batch:
                d = decisions.get(e["entry_id"])
                if not d:
                    e["adjudication"] = {"decision": None, "accepted": False, "error": "no decision returned"}
                    continue
                _apply(package, e, d, by_id)
                stats["adjudicated"] += 1
                stats["decisions"][d.get("decision")] = stats["decisions"].get(d.get("decision"), 0) + 1
    for e in targets:   # anything left without an accepted decision stays visibly open
        if not (e.get("adjudication") or {}).get("accepted") and e.get("applicability") == "CURRENT":
            if e["status"] == "UNVERIFIED":
                e["applicability"] = "EXCLUDED_UNVERIFIED"
            elif e["status"] == "DISPUTED":
                e["applicability"] = "DISPUTED"
    return stats
