"""Deterministic source checks. A quote is verified when its words occur, in
order, on the cited page (or, relocated, elsewhere in the package); every
value and every number, e-mail address and URL in the statement must come
from the quote. Verification proves the text exists -- not that an
interpretation is right (that is adjudication's job)."""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

from engine.package import Location, SourcePackage

_TOKEN = re.compile(r"[a-zÀ-ɏ؀-ۿ]+|\d+")
_ELLIPSIS = re.compile(r"\s*(?:\.\.\.|…|\[\.\.\.\])\s*")
_DIGITS = re.compile(r"\d+(?:[.,]\d+)*")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_URL = re.compile(r"(?:https?://|www\.)[^\s)>\]]+", re.I)
_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
# function words that carry no requirement content on their own
STOPWORDS = frozenset({"the", "a", "an", "of", "to", "and", "or", "in", "on", "for", "by", "be", "is", "are", "with",
                       "as", "at", "any", "all", "its", "their", "this", "that", "which", "shall", "must", "will",
                       "may", "should", "not", "no", "per", "from", "into", "than", "above", "below"})
_SHORT = 3   # quotes with fewer tokens are only checked against their cited location


def normalize(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "").translate(_ARABIC_DIGITS)
    t = t.replace("­", "")
    t = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", t)      # hyphenated line breaks
    return t.lower()


def tokens(text: str) -> list[str]:
    return _TOKEN.findall(normalize(text))


@lru_cache(maxsize=4096)
def _loc_tokens(text: str) -> tuple[str, ...]:
    return tuple(tokens(text))


def _find(hay: tuple[str, ...], needle: list[str], start: int = 0) -> int:
    if not needle:
        return -1
    n, first = len(needle), needle[0]
    i = start
    while True:
        try:
            i = hay.index(first, i)
        except ValueError:
            return -1
        if list(hay[i:i + n]) == needle:
            return i
        i += 1


def _match_parts(hay: tuple[str, ...], parts: list[list[str]]) -> tuple[int, int] | None:
    pos, first = 0, None
    for p in parts:
        i = _find(hay, p, pos)
        if i < 0:
            return None
        first = i if first is None else first
        pos = i + len(p)
    return (first, pos) if first is not None else None


def quote_parts(quote: str) -> list[list[str]]:
    return [t for t in (tokens(p) for p in _ELLIPSIS.split(quote or "")) if t]


def locate_quote(package: SourcePackage, quote: str, doc: str = "", label: str = "") -> dict:
    """{"status": VERIFIED|RELOCATED|NOT_FOUND|EMPTY, "loc_id", "span": (start, end) token span,
    "spans_next": bool}. A quote may continue onto the next page of the same document."""
    parts = quote_parts(quote)
    n_tok = sum(len(p) for p in parts)
    cited = package.find_location(doc, label) if doc else None
    if not parts:
        return {"status": "EMPTY", "loc_id": None, "span": None}
    if n_tok < _SHORT:
        # a 1-2 word quote (a heading, a list item) is too short to relocate safely: it is checked
        # only against its cited location, and only when it carries a content word
        if cited is None or not any(len(t) > 1 and t not in STOPWORDS for p in parts for t in p):
            return {"status": "EMPTY", "loc_id": None, "span": None}

    def try_loc(loc: Location) -> dict | None:
        hay = _loc_tokens(loc.text)
        m = _match_parts(hay, parts)
        if m:
            return {"loc_id": loc.loc_id, "span": m, "spans_next": False}
        d = package.document(loc.doc)
        if d:
            idx = d.locations.index(loc) if loc in d.locations else -1
            if 0 <= idx < len(d.locations) - 1:
                both = hay + _loc_tokens(d.locations[idx + 1].text)
                m = _match_parts(both, parts)
                if m and m[0] < len(hay):
                    return {"loc_id": loc.loc_id, "span": (m[0], min(m[1], len(hay))), "spans_next": True}
        return None

    if cited:
        hit = try_loc(cited)
        if hit:
            return dict(hit, status="VERIFIED")
    if n_tok < _SHORT:
        return {"status": "NOT_FOUND", "loc_id": cited.loc_id, "span": None}
    order = []
    d = package.document(doc) if doc else None
    if d:
        order += d.locations
    order += [loc for loc in package.locations if loc not in order]
    hits = []
    for loc in order:
        if cited is not None and loc.loc_id == cited.loc_id:
            continue
        hit = try_loc(loc)
        if hit:
            hits.append(hit)
            if len(hits) > 1:
                break
    if hits:
        return dict(hits[0], status="RELOCATED", ambiguous=len(hits) > 1)
    return {"status": "NOT_FOUND", "loc_id": cited.loc_id if cited else None, "span": None}


def _numbers(text: str) -> set[str]:
    out = set()
    for m in _DIGITS.findall(normalize(text)):
        v = m.replace(",", "")
        v = v.rstrip("0").rstrip(".") if "." in v else v
        out.add(v.lstrip("0") or "0")
    return out


def value_issues(finding: dict) -> list[str]:
    """Values and literal figures that the quote does not contain."""
    quote = finding.get("quote") or ""
    qtok = tokens(quote)
    qnums = _numbers(quote)
    issues = []
    for v in finding.get("values") or []:
        vt = tokens(v.get("text") or "")
        if vt and _find(tuple(qtok), vt) < 0 and not (_numbers(v.get("text") or "") and
                                                      _numbers(v.get("text") or "") <= qnums):
            issues.append(f"value '{v.get('text')}' is not in the quote")
    stmt = " ".join([finding.get("statement") or ""] + list(finding.get("conditions") or [])
                    + list(finding.get("exceptions") or []))
    extra = _numbers(stmt) - qnums
    if extra:
        issues.append("figures not in the quote: " + ", ".join(sorted(extra)))
    qnorm = normalize(quote)
    for e in _EMAIL.findall(stmt):
        if e.lower() not in qnorm:
            issues.append(f"e-mail address '{e}' is not in the quote")
    for u in _URL.findall(stmt):
        if u.lower().rstrip(".,;") not in qnorm:
            issues.append(f"URL '{u}' is not in the quote")
    return issues


def verify_finding(package: SourcePackage, finding: dict) -> dict:
    """Adds a `verification` block to (a copy of) the finding."""
    loc = locate_quote(package, finding.get("quote") or "", finding.get("document") or "", finding.get("page") or "")
    out = dict(finding)
    issues = value_issues(finding) if loc["status"] in ("VERIFIED", "RELOCATED") else []
    status = loc["status"]
    if status in ("VERIFIED", "RELOCATED") and issues:
        status = "VALUE_MISMATCH"
    l2 = package.location(loc["loc_id"]) if loc.get("loc_id") else None
    if l2 is not None and loc["status"] == "RELOCATED":
        out["document"], out["page"] = l2.doc, l2.label
    out["verification"] = {"status": status, "quote_status": loc["status"], "loc_id": loc.get("loc_id"),
                           "span": list(loc["span"]) if loc.get("span") else None,
                           "issues": issues, "ocr_source": bool(l2 and l2.status == "OCR"),
                           "ambiguous_location": bool(loc.get("ambiguous"))}
    return out


def quote_supported(package: SourcePackage, quote: str, doc: str = "", label: str = "") -> bool:
    return locate_quote(package, quote, doc, label)["status"] in ("VERIFIED", "RELOCATED")
