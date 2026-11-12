"""Deterministic, zero-model digest of procurement document text.

Reads the text produced by extractor.extract_document_with_metadata (with its
``[[SOURCE: name | PAGE: n]]`` / ``[[SOURCE: name | SHEET: s | ROWS: a-b]]``
markers) and recovers the document's own sections -- overview, scope,
deliverables, timeline, qualifications, submission, evaluation, payment ... --
as verbatim items with document/page references.

Used by the Phoenix reports (phoenix_reports.py) so that what the buyer
actually wrote is reported from the documents themselves, never from an empty
AI field. Nothing here invents, paraphrases or repairs a procurement fact: an
item is a span of the source text, and a section that cannot be located is
simply absent (absence of a heading is NOT treated as absence of information).
"""
from __future__ import annotations

import re

_MARKER = re.compile(r"^\[\[SOURCE:\s*(?P<doc>[^|\]]+?)\s*(?:\|\s*(?P<rest>[^\]]*))?\]\]\s*$")

# (section key, heading regex applied to a cleaned candidate heading line)
SECTION_PATTERNS: list[tuple[str, re.Pattern]] = [(k, re.compile(p, re.I)) for k, p in [
    ("about", r"^about\b"),
    ("overview", r"^(overview|background|introduction|purpose|objectives?|context|project (overview|description|background|summary)|summary|general information)\b"),
    ("scope", r"^((detailed )?scope( of (the )?(work|services|assignment))?|statement of work|services required|description of (the )?services|tasks?( and responsibilities)?|responsibilities)\b"),
    ("deliverables", r"^((expected |key )?(deliverables?|outputs?))\b"),
    ("timeline", r"^(.*\b(workflow|timeline|time ?frame|schedule|work ?plan|implementation plan|duration|period of performance)\b.*)$"),
    ("qualifications", r"^((required |minimum )?(qualifications?|eligibility( criteria)?|experience( and qualifications)?|competencies|requirements for (bidders|applicants|consultants)|profile)|bidder requirements)\b"),
    ("general", r"^((general|other|special) (requirements|conditions|obligations))\b"),
    ("submission", r"^(submission( requirements| instructions| of proposals| procedure)?|proposal (content|requirements|format|submission)|required documents|documents (to be submitted|required)|how to apply|to apply|application (process|procedure|requirements)|instructions to (bidders|tenderers|applicants|offerors))\b"),
    ("evaluation", r"^((proposal |bid |tender )?evaluation( criteria| methodology| process| and selection)?|award criteria|selection (criteria|process|method)|scoring( methodology)?)\b"),
    ("pricing", r"^(financial (proposal|offer)|price (proposal|schedule|offer)|pricing( instructions| schedule)?|budget|cost proposal|commercial (proposal|offer)|fees?)\b"),
    ("payment", r"^((terms of |schedule of )?payments?( terms| schedule| conditions)?|invoicing)\b"),
    ("contract", r"^(contract(ual)? (terms|conditions)|terms and conditions|general terms|conditions of contract|special terms)\b"),
]]

SECTION_TITLES = {
    "about": "About", "overview": "Overview", "scope": "Scope of work", "deliverables": "Deliverables",
    "timeline": "Workflow & timeline", "qualifications": "Qualifications & eligibility",
    "general": "General requirements", "submission": "Submission", "evaluation": "Evaluation",
    "pricing": "Pricing", "payment": "Payment terms", "contract": "Contract terms",
}

_LABEL_START = re.compile(r"^[A-Z][A-Za-z0-9 &/()'-]{2,45}:\s+\S")
_COURTESY = re.compile(r"^(thank you|thanks|best regards|regards|sincerely)\W*$", re.I)
_ITEM_START = re.compile(r"^(?:[-•●▪–*]\s+|\(?\d{1,2}[.)]\s+|\(?[a-zA-Z][.)]\s+|[ivx]{1,4}[.)]\s+)")
_BULLET_ONLY = re.compile(r"^[-•●▪–*o]$")
_NUMBERING = re.compile(r"^(?:section\s+)?(?:\d{1,2}(?:\.\d{1,2})*[.)]?|[A-Z][.)]|[IVX]{1,4}[.)])\s+", re.I)
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def fold(s: str) -> str:
    """Case/space/punctuation-insensitive form used to verify text against documents."""
    s = (s or "").lower().replace("–", "-").replace("—", "-").replace("’", "'")
    return re.sub(r"[^a-z0-9%@.]+", " ", s).strip()


# ── Splitting extracted text into located lines ─────────────────────────────

def located_lines(documents: list[tuple[str, str]]) -> list[dict]:
    """[{"doc", "page", "sheet", "text"}] for every non-empty line, in order."""
    out = []
    for name, text in documents or []:
        doc, page, sheet = name, None, None
        for raw in (text or "").splitlines():
            m = _MARKER.match(raw.strip())
            if m:
                doc = m.group("doc").strip() or name
                page, sheet = None, None
                for part in (m.group("rest") or "").split("|"):
                    k, _, v = part.partition(":")
                    k, v = k.strip().upper(), v.strip()
                    if k == "PAGE" and v.isdigit():
                        page = int(v)
                    elif k == "SHEET":
                        sheet = v
                continue
            line = raw.strip()
            if line:
                out.append({"doc": doc, "page": page, "sheet": sheet, "text": line})
    return out


def _heading_key(line: str) -> str | None:
    """Section key when `line` looks like a section heading, else None."""
    t = line.strip()
    if len(t) > 70 or len(t) < 3 or t.endswith((".", ",", ";")):
        return None
    t = _NUMBERING.sub("", t).strip().rstrip(":").strip()
    if not t or len(t.split()) > 8 or ":" in t:
        return None
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z'&-]*", t) if len(w) > 3]
    if not t[0].isupper() or (words and not t.isupper()
                              and sum(w[0].isupper() for w in words) / len(words) < 0.5):
        return None
    for key, pat in SECTION_PATTERNS:
        if pat.match(t):
            return key
    return None


def _ref(ln: dict) -> dict:
    return {"doc": ln["doc"], "page": ln.get("page"), "sheet": ln.get("sheet")}


def sections(documents: list[tuple[str, str]]) -> list[dict]:
    """Ordered sections: {"key", "heading", "doc", "page", "items": [{"text", "doc", "page"}]}.
    Items are verbatim source spans (wrapped lines re-joined, bullets split)."""
    out: list[dict] = []
    cur = None
    pending_bullet = False
    for ln in located_lines(documents):
        text = ln["text"]
        if cur is not None and cur["doc"] != ln["doc"]:
            cur = None  # a section never runs on into the next document
        if _BULLET_ONLY.match(text):
            pending_bullet = True
            continue
        key = None if pending_bullet else _heading_key(text)
        if key:
            cur = {"key": key, "heading": norm(_NUMBERING.sub("", text).rstrip(":")), **_ref(ln), "items": []}
            out.append(cur)
            pending_bullet = False
            continue
        if cur is None:
            continue
        if _COURTESY.match(text):
            continue
        starts = pending_bullet or bool(_ITEM_START.match(text)) or bool(_LABEL_START.match(text))
        body = _ITEM_START.sub("", text).strip() if not pending_bullet else text
        items = cur["items"]
        prev = items[-1] if items else None
        same_place = prev is not None and prev["doc"] == ln["doc"]
        if (not starts and prev is not None and same_place
                and (not prev["text"].rstrip().endswith((".", ":", "!", "?")) or body[:1].islower())):
            prev["text"] = norm(prev["text"] + " " + body)
        else:
            items.append({"text": norm(body), "doc": ln["doc"], "page": ln.get("page"), "sheet": ln.get("sheet"),
                          "numbered": bool(re.match(r"^\(?\d{1,2}[.)]\s", text))})
        pending_bullet = False
    for s in out:
        s["items"] = [i for i in s["items"] if len(i["text"]) > 1]
    return out


def by_key(secs: list[dict]) -> dict[str, list[dict]]:
    d: dict[str, list[dict]] = {}
    for s in secs:
        d.setdefault(s["key"], []).append(s)
    return d


# ── Sentence-level finders (whole corpus) ────────────────────────────────────

def located_sentences(documents: list[tuple[str, str]]) -> list[dict]:
    """Sentences re-joined across wrapped lines, each with doc/page."""
    out = []
    buf, ref = "", None
    for ln in located_lines(documents):
        if ref is not None and (ln["doc"], ln.get("page"), ln.get("sheet")) != (ref["doc"], ref.get("page"), ref.get("sheet")):
            if buf.strip():
                out.extend(_split(buf, ref))
            buf = ""
        ref = _ref(ln)
        if _heading_key(ln["text"]) or _BULLET_ONLY.match(ln["text"]):
            if buf.strip():
                out.extend(_split(buf, ref))
            buf = ""
            continue
        buf += " " + ln["text"]
    if ref and buf.strip():
        out.extend(_split(buf, ref))
    return out


def _split(buf: str, ref: dict) -> list[dict]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9(\"'])", norm(buf))
    return [{"text": p.strip(), **ref} for p in parts if len(p.strip()) > 3]


_SUBMIT_HINT = re.compile(r"\b(submit|submitted|submission|send|apply|proposals?\s+(must|shall|should)\s+be)\b", re.I)
_CHANNEL = re.compile(r"(e-?mail|@|portal|online|upload|e-?tender|platform|hand[- ]deliver|deliver(ed)? to|sealed envelope|courier|address)", re.I)
_DEADLINE = re.compile(r"\b(no later than|not later than|deadline|closing (date|time)|due (date|by)|before\s+\d{1,2}[:.]\d{2})\b", re.I)
_LATE = re.compile(r"\b(late|after the (deadline|closing))\b.*\b(not be (considered|accepted|evaluated)|rejected|disqualif)", re.I)
_SUBJECT = re.compile(r"\bsubject (line|of the e-?mail)\b", re.I)


def submission_instructions(documents: list[tuple[str, str]]) -> dict:
    """Verbatim submission facts: method sentence(s), addresses, deadline
    sentence(s), subject-line and late-submission rules, each located."""
    sents = located_sentences(documents)
    method = [s for s in sents if _SUBMIT_HINT.search(s["text"]) and _CHANNEL.search(s["text"])]
    emails, seen = [], set()
    for s in method:
        for e in EMAIL.findall(s["text"]):
            e = e.rstrip(".")
            if e.lower() not in seen:
                seen.add(e.lower())
                emails.append({"email": e, "doc": s["doc"], "page": s.get("page")})
    channel = None
    blob = " ".join(s["text"] for s in method).lower()
    if emails or re.search(r"\be-?mail\b", blob):
        channel = "Email"
    elif re.search(r"portal|online|upload|e-?tender|platform", blob):
        channel = "Electronic submission"
    elif re.search(r"hand|sealed envelope|courier|deliver", blob):
        channel = "Physical delivery"
    return {
        "channel": channel,
        "method_sentences": method[:3],
        "emails": emails,
        "deadline_sentences": [s for s in sents if _DEADLINE.search(s["text"])][:3],
        "subject_rule": next((s for s in sents if _SUBJECT.search(s["text"])), None),
        "late_rule": next((s for s in sents if _LATE.search(s["text"])), None),
    }


def find_sentences(documents: list[tuple[str, str]], pattern: str, limit: int = 3) -> list[dict]:
    rx = re.compile(pattern, re.I)
    return [s for s in located_sentences(documents) if rx.search(s["text"])][:limit]


def corpus_contains(documents: list[tuple[str, str]], text: str) -> bool:
    """True when `text` (folded) occurs in the folded corpus -- used to verify
    any statement before it is published."""
    needle = fold(text)
    if not needle:
        return False
    return needle in fold(" ".join(t for _, t in documents or []))


def ref_label(doc: str | None, page=None, sheet=None, short: bool = True) -> str:
    """Compact source reference: 'ToR p.3' / 'Pricing.xlsx · Sheet "Rates"'."""
    name = doc or ""
    if short and len(name) > 34:
        stem, dot, ext = name.rpartition(".")
        name = (stem[:28] + "…" + dot + ext) if dot else name[:32] + "…"
    parts = [name] if name else []
    if page:
        parts.append(f"p.{page}")
    if sheet:
        parts.append(f'sheet "{sheet}"')
    return " · ".join(parts)
