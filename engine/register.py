"""The unified evidence register: the union of both analysts' findings,
reconciled by the source text they rest on -- never by similar wording.

Two findings are compared only when their verified quotes overlap on the same
page. Agreement requires the same modal force, the same values and the same
conditions/exceptions; anything else is a dispute for adjudication. A finding
only one analyst made is kept (SINGLE_*) and adjudicated, never dropped."""
from __future__ import annotations

import re

from engine.schema import FAST_MANDATORY
from engine.verify import normalize, tokens

_RANK = {"CRITICAL": 3, "MATERIAL": 2, "INFORMATIONAL": 1}
_STOP = {"the", "a", "an", "of", "to", "and", "or", "in", "on", "for", "by", "be", "is", "are", "with", "as",
         "at", "any", "all", "its", "their", "this", "that", "which", "shall", "must", "will", "may", "should"}


def _span(f: dict):
    v = f.get("verification") or {}
    if v.get("quote_status") not in ("VERIFIED", "RELOCATED") or not v.get("span"):
        return None
    return v["loc_id"], v["span"][0], v["span"][1]


def overlap(a: dict, b: dict) -> float:
    sa, sb = _span(a), _span(b)
    if not sa or not sb or sa[0] != sb[0]:
        return 0.0
    inter = min(sa[2], sb[2]) - max(sa[1], sb[1])
    if inter <= 0:
        return 0.0
    return inter / max(1, min(sa[2] - sa[1], sb[2] - sb[1]))


def _vals(f: dict) -> set[str]:
    out = set()
    for v in f.get("values") or []:
        key = (v.get("normalized") or "").strip().lower() or " ".join(tokens(v.get("text") or ""))
        if key:
            out.add(re.sub(r"\s+", " ", key))
    return out


def _qual_key(items) -> set[str]:
    return {" ".join(t for t in tokens(x) if t not in _STOP) for x in items or [] if x and x.strip()}


def differences(a: dict, b: dict, *, a_finer: bool = False) -> list[str]:
    """Material interpretation differences between two findings of the same text.
    With a_finer, `a` states one part of what `b` states (values may be a subset)."""
    out = []
    if a.get("modality") != b.get("modality"):
        out.append(f"modal force: {a.get('modality')} vs {b.get('modality')}")
    va, vb = _vals(a), _vals(b)
    if (a_finer and not va <= vb) or (not a_finer and va != vb):
        out.append(f"values: {sorted(va)} vs {sorted(vb)}")
    for k in ("conditions", "exceptions"):
        ka, kb = _qual_key(a.get(k)), _qual_key(b.get(k))
        if bool(ka) != bool(kb) or (not a_finer and len(ka) != len(kb)):
            out.append(f"{k}: {a.get(k) or []} vs {b.get(k) or []}")
    ca, cb = a.get("category"), b.get("category")
    if ca != cb and ((ca in FAST_MANDATORY) != (cb in FAST_MANDATORY)):
        out.append(f"classification: {ca} vs {cb}")
    if bool((a.get("consequence") or "").strip()) != bool((b.get("consequence") or "").strip()):
        out.append(f"stated consequence: {a.get('consequence') or '-'} vs {b.get('consequence') or '-'}")
    return out


def _content(quote: str) -> set[str]:
    return {t for t in tokens(quote) if t not in _STOP}


def _dedupe(findings: list[dict]) -> tuple[list[dict], list[dict]]:
    """Folds a finding into an earlier one only when both rest on (nearly) the same
    span with the same content words: a quote that adds a word the other lacks
    (a list item under its heading) states a distinct requirement."""
    kept, dups = [], []
    for f in findings:
        twin = next((k for k in kept if overlap(f, k) >= 0.9 and _span(f) and _span(k)
                     and abs((_span(f)[2] - _span(f)[1]) - (_span(k)[2] - _span(k)[1])) <= 2
                     and _content(f.get("quote") or "") == _content(k.get("quote") or "")
                     and not differences(f, k)), None)
        (dups if twin else kept).append(dict(f, duplicate_of=twin["id"]) if twin else f)
    return kept, dups


_FIELDS = ("category", "statement", "quote", "document", "page", "section", "party", "action", "modality",
           "conditions", "exceptions", "values", "consequence", "relations", "uncertainty")


def _entry(base: dict, status: str, sources: list[dict], partners: list[dict], diffs: list[str]) -> dict:
    e = {k: base.get(k) for k in _FIELDS}
    e.update(status=status, materiality=max((s.get("materiality") or "INFORMATIONAL" for s in sources + partners),
                                            key=lambda m: _RANK.get(m, 0)),
             sources=[s["id"] for s in sources], partners=[p["id"] for p in partners],
             analysts=sorted({s.get("analyst") for s in sources + partners}),
             verification=base.get("verification"), differences=diffs,
             interpretations={s["id"]: {k: s.get(k) for k in ("statement", "modality", "conditions", "exceptions",
                                                              "values", "category", "consequence", "quote")}
                              for s in sources + partners},
             adjudication=None, applicability="CURRENT", relationships=[])
    return e


def reconcile(inv_a: dict, inv_b: dict | None) -> dict:
    """inv_*: verified inventories {"tag", "findings"}. Returns {"entries", "duplicates", "stats"}."""
    a_all = inv_a["findings"]
    b_all = inv_b["findings"] if inv_b else []
    a_ok, a_dup = _dedupe([f for f in a_all if _span(f)])
    b_ok, b_dup = _dedupe([f for f in b_all if _span(f)])
    a_bad = [f for f in a_all if not _span(f)]
    b_bad = [f for f in b_all if not _span(f)]

    # overlap graph -> connected groups across analysts
    by_loc: dict[str, list[dict]] = {}
    for f in a_ok + b_ok:
        by_loc.setdefault(_span(f)[0], []).append(f)
    parent: dict[str, str] = {f["id"]: f["id"] for f in a_ok + b_ok}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for fs in by_loc.values():
        for i, x in enumerate(fs):
            for y in fs[i + 1:]:
                if x.get("analyst") != y.get("analyst") and overlap(x, y) >= 0.5:
                    parent[find(x["id"])] = find(y["id"])
    groups: dict[str, list[dict]] = {}
    for f in a_ok + b_ok:
        groups.setdefault(find(f["id"]), []).append(f)

    ta, tb = inv_a["tag"], (inv_b or {}).get("tag")
    entries: list[dict] = []
    for g in groups.values():
        ga = [f for f in g if f.get("analyst") == ta]
        gb = [f for f in g if f.get("analyst") == tb]
        if not gb or not ga:
            for f in ga or gb:
                entries.append(_entry(f, f"SINGLE_{f.get('analyst')}", [f], [], []))
            continue
        finer, coarser = (ga, gb) if len(ga) >= len(gb) else (gb, ga)
        for f in finer:
            partners = [p for p in coarser if overlap(f, p) >= 0.5]
            if not partners:
                entries.append(_entry(f, f"SINGLE_{f.get('analyst')}", [f], [], []))
                continue
            diffs_by = [(p, differences(f, p, a_finer=len(finer) > len(coarser))) for p in partners]
            best = min(diffs_by, key=lambda t: len(t[1]))
            status = "AGREED" if not best[1] else "DISPUTED"
            entries.append(_entry(f, status, [f], [best[0]], best[1]))
        for p in coarser:   # a coarser finding none of the finer ones matched keeps its own entry
            if not any(p["id"] in e["partners"] for e in entries):
                entries.append(_entry(p, f"SINGLE_{p.get('analyst')}", [p], [], []))
    for f in a_bad + b_bad:
        entries.append(_entry(f, "UNVERIFIED", [f], [], []))

    def order(e):
        v = e.get("verification") or {}
        return (str(e.get("document")), str(v.get("loc_id") or ""), (v.get("span") or [10 ** 9])[0])
    entries.sort(key=order)
    for i, e in enumerate(entries, 1):
        e["entry_id"] = f"E{i:03d}"
    stats = {"entries": len(entries)}
    for e in entries:
        stats[e["status"]] = stats.get(e["status"], 0) + 1
    return {"entries": entries, "duplicates": a_dup + b_dup, "stats": stats}


def needs_adjudication(e: dict, *, dual: bool) -> bool:
    v = (e.get("verification") or {}).get("status")
    if e["status"] in ("DISPUTED", "UNVERIFIED") or v == "VALUE_MISMATCH":
        return True
    if dual and e["status"].startswith("SINGLE_") and e.get("materiality") in ("CRITICAL", "MATERIAL"):
        return True
    return bool((e.get("verification") or {}).get("ocr_source")) and e.get("materiality") == "CRITICAL"


def statement_key(e: dict) -> str:
    return normalize(e.get("statement") or "")
