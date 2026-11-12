"""New / Updated / Conflict labelling for procurement packages that grow over
time (addenda, clarifications, corrected annexes).

Deterministic and zero-model. Works from the FAST result (per-document
identity metadata, evaluation criteria, requirements, commercial clauses)
plus the extracted document text:

* NEW      -- a requirement/condition introduced by an amending document (or a
              document added since the previous analysis) with no earlier
              counterpart.
* UPDATED  -- a value that an amending document changes: shows the current
              value, the previous value, the document that introduced the
              change and the earlier statement it supersedes.
* CONFLICT -- two base documents state different values and no amending
              document resolves it. Shown factually; never silently repaired.

Ordinary restatements (same value, or near-identical wording) are not labelled.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

import procurement_digest as pdg

_AMEND_NAME = re.compile(r"(addend|amend|corrigend|errat|clarif|bulletin|revision|revised|q\s*&\s*a|questions)", re.I)
_AMEND_TEXT = re.compile(r"\b(addendum|amendment|corrigendum|clarification(s)? (no|notice|#)|bid bulletin|erratum)\b", re.I)
_OBLIGATION = re.compile(r"\b(must|shall|required|requirement|mandatory|is extended|has been (extended|changed|amended|revised)|replaced?|supersede[sd]?|now)\b", re.I)


def is_amending_document(name: str, text: str = "") -> bool:
    base = re.sub(r"[_\-.]+", " ", (name or "").rsplit("/", 1)[-1])
    if _AMEND_NAME.search(base):
        return True
    head = re.sub(r"\[\[[^\]]*\]\]", " ", text or "")[:600]
    return bool(_AMEND_TEXT.search(head))


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, pdg.fold(a), pdg.fold(b)).ratio()


def _first_ref(refs: list | None) -> dict:
    r = (refs or [{}])[0] or {}
    return {"doc": r.get("source_doc"), "page": r.get("page"), "sheet": r.get("sheet"),
            "excerpt": pdg.norm(r.get("excerpt") or "")[:220]}


def _deadline_sentence(documents, doc_name, value) -> dict:
    sents = [s for s in pdg.located_sentences([(n, t) for n, t in documents if n == doc_name])]
    pref = [s for s in sents if re.search(r"deadline|no later than|closing|submi", s["text"], re.I)]
    for s in pref + sents:
        if _date_in(s["text"], value):
            return {"doc": s["doc"], "page": s.get("page"), "sheet": s.get("sheet"), "excerpt": s["text"][:220]}
    return {"doc": doc_name, "page": None, "sheet": None, "excerpt": ""}


_MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august",
           "september", "october", "november", "december"]


def _date_in(text: str, iso: str) -> bool:
    if not iso or not re.match(r"^\d{4}-\d{2}-\d{2}", str(iso)):
        return False
    y, m, d = str(iso)[:10].split("-")
    low = text.lower()
    month = _MONTHS[int(m) - 1]
    day = str(int(d))
    return (str(iso)[:10] in text or (month in low and y in low and re.search(rf"\b0?{day}\b", low) is not None)
            or re.search(rf"\b0?{day}[/.-]0?{int(m)}[/.-]{y}\b", text) is not None)


def parse_date(text: str) -> str | None:
    """First full calendar date in `text` as ISO (ISO, 'November 20, 2026'
    or '20 November 2026'); None when no unambiguous full date is present."""
    t = text or ""
    m = re.search(r"\b(20\d{2})-(\d{2})-(\d{2})\b", t)
    if m:
        return m.group(0)
    months = "|".join(_MONTHS)
    m = re.search(rf"\b({months})\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(20\d{{2}})\b", t, re.I)
    if m:
        return f"{m.group(3)}-{_MONTHS.index(m.group(1).lower()) + 1:02d}-{int(m.group(2)):02d}"
    m = re.search(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({months}),?\s+(20\d{{2}})\b", t, re.I)
    if m:
        return f"{m.group(3)}-{_MONTHS.index(m.group(2).lower()) + 1:02d}-{int(m.group(1)):02d}"
    return None


def effective_deadline(result: dict, documents: list[tuple[str, str]]) -> dict:
    """The extracted submission deadline with its authority:
    {"value", "doc", "ref", "amended_from": {...} | None, "conflict": [...]}.
    An amending document's deadline governs (latest amending document by
    package order); otherwise the base documents' agreed value."""
    meta = (result or {}).get("doc_metadata_by_doc") or {}
    texts = dict(documents or [])
    base, amend = [], []
    for name, m in meta.items():
        v = (m or {}).get("submission_deadline")
        if not v:
            continue
        (amend if is_amending_document(name, texts.get(name, "")) else base).append((name, str(v)))
    base_vals = sorted({v for _, v in base})
    out = {"value": None, "doc": None, "ref": None, "amended_from": None, "conflict": []}
    if base:
        name, v = base[0]
        out.update(value=v, doc=name, ref=_deadline_sentence(documents, name, v))
        if len(base_vals) > 1:
            out["conflict"] = [{"value": v2, "doc": n2, "ref": _deadline_sentence(documents, n2, v2)} for n2, v2 in base]
    if not amend:
        # FAST may not extract identity metadata from a short addendum: read
        # the amending documents' own deadline statements (verbatim, dated).
        for name, text in documents or []:
            if name in meta and (meta.get(name) or {}).get("submission_deadline"):
                continue
            if not is_amending_document(name, text):
                continue
            for s in pdg.located_sentences([(name, text)]):
                if re.search(r"deadline|closing date|no later than|extended", s["text"], re.I):
                    iso = parse_date(s["text"])
                    if iso:
                        amend.append((name, iso))
                        break
    if amend:
        name, v = amend[-1]
        previous = {k: out[k] for k in ("value", "doc", "ref")} if out["value"] and out["value"] != v else None
        out.update(value=v, doc=name, ref=_deadline_sentence(documents, name, v), amended_from=previous, conflict=[])
    if not out["value"]:
        for m in (result or {}).get("canonical_milestones") or []:
            if (m.get("label") or "").upper() == "SUBMISSION_DEADLINE" and m.get("normalized_date_start"):
                ref = _first_ref(m.get("source_refs"))
                out.update(value=m["normalized_date_start"], doc=ref.get("doc"), ref=ref)
                break
    return out


def _weight_key(stage: str) -> str:
    return pdg.fold(re.sub(r"\(.*?\)|\d+\s*%", "", stage or ""))[:60]


def detect_changes(result: dict, documents: list[tuple[str, str]],
                   previous_result: dict | None = None,
                   previous_doc_names: list[str] | None = None) -> list[dict]:
    """Change records: {"kind", "topic", "current", "previous", "source", "supersedes"}.
    `source`/`supersedes` are {"doc","page","sheet","excerpt"}."""
    result = result or {}
    texts = dict(documents or [])
    names = list(texts) or list((result.get("doc_metadata_by_doc") or {}).keys())
    prev_names = set(previous_doc_names or [])
    amending = {n for n in names if is_amending_document(n, texts.get(n, ""))}
    added = {n for n in names if prev_names and n not in prev_names}
    changers = amending | added
    changes: list[dict] = []

    # 1. Submission deadline
    dl = effective_deadline(result, documents)
    if dl["amended_from"]:
        changes.append({"kind": "UPDATED", "topic": "Submission deadline", "current": dl["value"],
                        "previous": dl["amended_from"]["value"], "source": dl["ref"],
                        "supersedes": dl["amended_from"]["ref"]})
    elif dl["conflict"]:
        a, b = dl["conflict"][0], dl["conflict"][1]
        changes.append({"kind": "CONFLICT", "topic": "Submission deadline", "current": a["value"],
                        "previous": b["value"], "source": a["ref"], "supersedes": b["ref"]})
    elif previous_result:
        prev = effective_deadline(previous_result, documents)
        if prev["value"] and dl["value"] and prev["value"] != dl["value"]:
            changes.append({"kind": "UPDATED", "topic": "Submission deadline", "current": dl["value"],
                            "previous": prev["value"], "source": dl["ref"], "supersedes": prev["ref"]})

    # 2. Evaluation weights
    base_w: dict[str, dict] = {}
    for ec in result.get("evaluation_criteria") or []:
        ref = _first_ref(ec.get("source_refs"))
        doc = ref.get("doc") or ec.get("source_doc")
        key = _weight_key(ec.get("stage"))
        if not key:
            continue
        rec = {"stage": ec.get("stage"), "weight": ec.get("weight"), "ref": ref, "doc": doc}
        if doc in changers:
            old = base_w.get(key)
            if old is None:
                cands = [v for v in base_w.values() if _similar(v["stage"], ec.get("stage") or "") > 0.8]
                old = cands[0] if cands else None
            if old and str(old["weight"]) != str(ec.get("weight")):
                changes.append({"kind": "UPDATED", "topic": f"Evaluation weight – {pdg.norm(ec.get('stage'))[:70]}",
                                "current": ec.get("weight"), "previous": old["weight"], "source": ref,
                                "supersedes": old["ref"]})
            elif not old:
                changes.append({"kind": "NEW", "topic": "Evaluation criterion",
                                "current": f"{pdg.norm(ec.get('stage'))} ({ec.get('weight') or 'weight not stated'})",
                                "previous": None, "source": ref, "supersedes": None})
        else:
            old = base_w.get(key)
            if old and old["doc"] != doc and str(old["weight"]) != str(ec.get("weight")):
                changes.append({"kind": "CONFLICT", "topic": f"Evaluation weight – {pdg.norm(ec.get('stage'))[:70]}",
                                "current": ec.get("weight"), "previous": old["weight"], "source": ref,
                                "supersedes": old["ref"]})
            base_w.setdefault(key, rec)

    # 3. Requirements / commercial conditions introduced by amending documents
    base_items, new_items = [], []
    corpus = pdg.fold(" ".join(texts.values()))

    def _verbatim(ref: dict) -> str | None:
        """The document's own words for an extracted item -- the AI's
        paraphrase is never published as a requirement change."""
        ex = pdg.norm(ref.get("excerpt") or "")
        if len(ex) < 20 or not corpus or pdg.fold(ex[:90]) not in corpus:
            return None
        return ex

    for item in (result.get("requirements") or []) + (result.get("commercial_clauses") or []):
        ref = _first_ref(item.get("source_refs"))
        doc = ref.get("doc") or item.get("source_doc")
        text = _verbatim(ref) if texts else pdg.norm(item.get("description") or item.get("source_fact"))
        if not text:
            continue
        if doc in changers and ref.get("sheet"):
            continue  # workbook contents are reported by workbook intelligence, not as conditions
        (new_items if doc in changers else base_items).append((text, ref))
    # The amending documents' own obligation sentences (FAST may not have
    # extracted them as requirements) -- verbatim, located.
    covered = [t for t, _ in new_items]
    for s in pdg.located_sentences([(n, texts[n]) for n in names if n in changers and n in texts]):
        t = s["text"]
        if len(t) < 25 or not _OBLIGATION.search(t) or any(_similar(t, c) > 0.6 for c in covered):
            continue
        if dl["amended_from"] and _date_in(t, dl["value"]):
            continue  # the deadline change is already reported as UPDATED
        new_items.append((t, {"doc": s["doc"], "page": s.get("page"), "sheet": s.get("sheet"), "excerpt": t[:220]}))
        covered.append(t)
    reported: list[str] = []
    for text, ref in new_items:
        if not text or any(_similar(text, r) > 0.6 or pdg.fold(r) in pdg.fold(text) or pdg.fold(text) in pdg.fold(r)
                           for r in reported):
            continue  # same statement found twice (FAST item + sentence scan)
        reported.append(text)
        best, best_ref = 0.0, None
        for bt, bref in base_items:
            sim = _similar(text, bt)
            if sim > best:
                best, best_ref = sim, bref
        if best >= 0.85:
            continue  # restatement -- not labelled
        if best >= 0.5 and best_ref:
            changes.append({"kind": "UPDATED", "topic": "Requirement", "current": text,
                            "previous": best_ref.get("excerpt") or None, "source": ref, "supersedes": best_ref})
        else:
            changes.append({"kind": "NEW", "topic": "Requirement / condition", "current": text,
                            "previous": None, "source": ref, "supersedes": None})
    return changes[:20]
