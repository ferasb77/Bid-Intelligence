"""A procurement package as a set of related documents, split into locatable
units (PDF pages, workbook sheet ranges, DOCX sections) with a readability
assessment for each, so no analysis can claim coverage of text it never had.

Input is the application's existing extraction output: text with
[[SOURCE: <doc> | PAGE: n]] / SHEET / SECTION markers (extractor.py)."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

_MARKER = re.compile(r"\[\[SOURCE:\s*(?P<doc>[^|\]]+?)\s*(?:\|\s*(?P<rest>[^\]]*))?\]\]")
_FAILURE = re.compile(r"^\[(?:Scanned PDF|Unsupported file format|DOCX parsing failed|XLSX parsing failed|"
                      r"XLS parsing failed|CSV parsing failed)[^\]]*\]$", re.I | re.M)
_HEADING = re.compile(r"^(?:(?:\d+(?:\.\d+){0,3}\.?|[IVXLC]+\.|[A-Z]\.|(?:ARTICLE|SECTION|PART|ANNEX|APPENDIX|"
                      r"SCHEDULE|EXHIBIT|CHAPTER)\b[^\n]{0,12})\s+\S[^\n]{2,90}|[A-Z][A-Z0-9 ,&/()\-]{4,80})$")
_DEFINITION = re.compile(r"^[\"“']?[A-Z][\w /&()\-]{1,60}[\"”']?\s*(?:means|shall mean|refers to|is defined as|:)\s+\S",
                         re.M)
MIN_CHARS = 40          # fewer non-space characters than this on a page = near-empty
UNIT_CHARS = 30000      # characters of source text per extraction unit


@dataclass
class Location:
    loc_id: str
    doc: str
    label: str            # "12" (page), "Prices rows 1-40" (sheet), heading (DOCX section)
    kind: str             # PAGE | SHEET | SECTION | TEXT
    text: str
    ocr: bool = False
    status: str = "READ"  # READ | NEAR_EMPTY | OCR | UNREADABLE | MISSING
    note: str = ""

    @property
    def chars(self) -> int:
        return len(re.sub(r"\s+", "", self.text))

    def ref(self) -> str:
        return f"{self.doc}, {'p. ' if self.kind == 'PAGE' else ''}{self.label}"


@dataclass
class Document:
    doc_id: str
    name: str
    text: str
    meta: dict = field(default_factory=dict)
    uploaded_at: str | None = None
    sha256: str = ""
    locations: list[Location] = field(default_factory=list)


@dataclass
class SourcePackage:
    documents: list[Document]
    data_class: str = "CLIENT"     # CLIENT | SYNTHETIC -- governs provider authorization
    package_hash: str = ""

    @property
    def locations(self) -> list[Location]:
        return [loc for d in self.documents for loc in d.locations]

    def location(self, loc_id: str) -> Location | None:
        return next((loc for loc in self.locations if loc.loc_id == loc_id), None)

    def find_location(self, doc: str, label: str) -> Location | None:
        doc_n, label_n = _norm_name(doc), _norm_label(label)
        cands = [loc for loc in self.locations if _norm_name(loc.doc) == doc_n] or \
                [loc for loc in self.locations if doc_n and doc_n in _norm_name(loc.doc)]
        return next((loc for loc in cands if _norm_label(loc.label) == label_n), None) or \
            next((loc for loc in cands if label_n and _norm_label(loc.label).startswith(label_n)), None)

    def document(self, name: str) -> Document | None:
        n = _norm_name(name)
        return next((d for d in self.documents if _norm_name(d.name) == n), None) or \
            next((d for d in self.documents if n and n in _norm_name(d.name)), None)

    def readability(self) -> dict:
        counts: dict[str, int] = {}
        for loc in self.locations:
            counts[loc.status] = counts.get(loc.status, 0) + 1
        problems = [{"loc_id": loc.loc_id, "ref": loc.ref(), "status": loc.status, "note": loc.note}
                    for loc in self.locations if loc.status in ("UNREADABLE", "MISSING", "OCR", "NEAR_EMPTY")]
        return {"locations": len(self.locations), "by_status": counts, "problems": problems,
                "complete": not any(p["status"] in ("UNREADABLE", "MISSING") for p in problems)}

    def manifest(self) -> list[dict]:
        return [{"doc_id": d.doc_id, "name": d.name, "sha256": d.sha256, "uploaded_at": d.uploaded_at,
                 "locations": len(d.locations), "page_count": d.meta.get("page_count")} for d in self.documents]

    def definitions(self, limit: int = 6000) -> str:
        """Defined terms stated anywhere in the package (general glossary
        convention), so each extraction unit reads terms as the package defines them."""
        out, total = [], 0
        for loc in self.locations:
            for m in _DEFINITION.finditer(loc.text):
                line = loc.text[m.start():loc.text.find("\n", m.start()) if "\n" in loc.text[m.start():] else None]
                line = line.strip()[:300]
                if total + len(line) > limit:
                    return "\n".join(out)
                out.append(f"[{loc.ref()}] {line}")
                total += len(line)
        return "\n".join(out)

    def outline(self, limit: int = 8000) -> str:
        """Heading lines of every document, for resolving cross-references."""
        out, total = [], 0
        for d in self.documents:
            for loc in d.locations:
                for line in loc.text.splitlines():
                    s = line.strip()
                    if 4 <= len(s) <= 100 and _HEADING.match(s):
                        item = f"{d.name} [{loc.label}]: {s}"
                        total += len(item)
                        if total > limit:
                            return "\n".join(out)
                        out.append(item)
        return "\n".join(out)


def _norm_name(s: str) -> str:
    return re.sub(r"[^a-z0-9؀-ۿ]+", "", (s or "").lower())


def _norm_label(s) -> str:
    s = str(s or "").strip().lower()
    s = re.sub(r"^(?:p(?:age)?\.?\s*|sheet\s*)", "", s)
    return re.sub(r"\s+", " ", s)


def _split(doc_id: str, name: str, text: str, meta: dict) -> list[Location]:
    locs: list[Location] = []
    cur = {"label": "1", "kind": "TEXT", "ocr": False, "lines": []}

    def flush():
        body = "\n".join(cur["lines"]).strip()
        if body or cur["kind"] == "PAGE":
            if locs and locs[-1].label == cur["label"] and locs[-1].kind == cur["kind"]:
                locs[-1].text += "\n" + body
            else:
                locs.append(Location(f"{doc_id}-L{len(locs) + 1}", name, cur["label"], cur["kind"], body,
                                     ocr=cur["ocr"]))
        cur["lines"] = []

    for raw in (text or "").splitlines():
        m = _MARKER.search(raw)
        if m and m.group("rest") and m.group("rest").strip().upper() == "TABLE":
            cur["lines"].append(raw[m.end():].strip())       # inline DOCX table-row marker
            continue
        if m and raw.strip().startswith("[[SOURCE"):
            rest = m.group("rest") or ""
            parts = {k.strip().upper(): v.strip() for k, _, v in (p.partition(":") for p in rest.split("|"))}
            if "PAGE" in parts:
                label, kind = parts["PAGE"], "PAGE"
            elif "SHEET" in parts:
                label = parts["SHEET"] + (f" rows {parts['ROWS']}" if parts.get("ROWS") else "")
                kind = "SHEET"
            elif "SECTION" in parts:
                label, kind = parts["SECTION"][:80] or "Section", "SECTION"
            elif "ROWS" in parts:
                label, kind = f"rows {parts['ROWS']}", "SHEET"
            else:
                label, kind = cur["label"], cur["kind"]
            if (label, kind) != (cur["label"], cur["kind"]) or cur["lines"]:
                flush()
            cur.update(label=label, kind=kind, ocr="OCR" in parts)
            trailing = raw[m.end():].strip()
            if trailing:
                cur["lines"].append(trailing)
            continue
        cur["lines"].append(raw)
    flush()

    # a very long non-page location (a DOCX body, a large sheet) is divided at
    # line boundaries so every part fits one extraction unit
    split: list[Location] = []
    for loc in locs:
        if loc.kind == "PAGE" or len(loc.text) <= UNIT_CHARS:
            split.append(loc)
            continue
        lines, buf, n = loc.text.splitlines(), [], 0
        parts: list[str] = []
        for line in lines:
            if buf and n + len(line) > UNIT_CHARS * 0.8:
                parts.append("\n".join(buf))
                buf, n = [], 0
            buf.append(line)
            n += len(line) + 1
        if buf:
            parts.append("\n".join(buf))
        for k, body in enumerate(parts, 1):
            split.append(Location("", name, f"{loc.label} (part {k})", loc.kind, body, ocr=loc.ocr))
    locs = split
    for i, loc in enumerate(locs, 1):
        loc.loc_id = f"{doc_id}-L{i}"

    for loc in locs:
        if _FAILURE.search(loc.text):
            loc.status, loc.note = "UNREADABLE", _FAILURE.search(loc.text).group(0).strip("[]")
        elif loc.ocr:
            loc.status, loc.note = "OCR", "text recognised by OCR; wording may contain recognition errors"
        elif loc.chars < MIN_CHARS:
            loc.status, loc.note = "NEAR_EMPTY", "almost no text on this page"
    pc = meta.get("page_count")
    if isinstance(pc, int) and pc > 0 and any(loc.kind == "PAGE" for loc in locs):
        have = {loc.label for loc in locs if loc.kind == "PAGE"}
        ocr = meta.get("ocr") or {}
        for i in range(1, pc + 1):
            if str(i) not in have:
                scanned = i in (ocr.get("pages") or []) or ocr.get("status") == "UNAVAILABLE"
                locs.append(Location(f"{doc_id}-L{len(locs) + 1}", name, str(i), "PAGE", "",
                                     status="UNREADABLE" if scanned else "MISSING",
                                     note="scanned page without usable text" if scanned
                                     else "no text was extracted from this page"))
        locs.sort(key=lambda loc: int(loc.label) if loc.kind == "PAGE" and loc.label.isdigit() else 10 ** 6)
    return locs


def build_package(documents: list[dict], *, data_class: str = "CLIENT") -> SourcePackage:
    """documents: [{"name", "text", "meta"?, "uploaded_at"?, "sha256"?}] in upload order."""
    if data_class not in ("CLIENT", "SYNTHETIC"):
        raise ValueError("data_class must be CLIENT or SYNTHETIC")
    docs = []
    for i, d in enumerate(documents, 1):
        doc_id = f"D{i}"
        text = d.get("text") or ""
        sha = d.get("sha256") or hashlib.sha256(text.encode("utf-8")).hexdigest()
        doc = Document(doc_id, d["name"], text, d.get("meta") or {}, d.get("uploaded_at"), sha)
        doc.locations = _split(doc_id, d["name"], text, doc.meta)
        docs.append(doc)
    h = hashlib.sha256()
    for d in docs:
        h.update(d.name.encode("utf-8") + b"\0" + d.sha256.encode() + b"\0")
    return SourcePackage(docs, data_class, h.hexdigest())


@dataclass
class Unit:
    unit_id: str
    doc: str
    locations: list[Location]

    def text(self) -> str:
        parts = []
        for loc in self.locations:
            head = {"PAGE": f"PAGE {loc.label}", "SHEET": f"SHEET {loc.label}",
                    "SECTION": f"SECTION HEADING {loc.label}"}.get(loc.kind, "TEXT")
            flag = f" | NOTE: {loc.note}" if loc.status in ("OCR", "UNREADABLE", "MISSING", "NEAR_EMPTY") else ""
            parts.append(f"[[SECTION_ID: {loc.loc_id} | SOURCE: {loc.doc} | {head}{flag}]]\n{loc.text}")
        return "\n\n".join(parts)


def units(package: SourcePackage, max_chars: int = UNIT_CHARS) -> list[Unit]:
    """Consecutive locations of one document, up to max_chars each. A single
    oversized location becomes its own unit (never cut: quotes must stay whole)."""
    out: list[Unit] = []
    for d in package.documents:
        cur: list[Location] = []
        size = 0
        for loc in d.locations:
            n = len(loc.text)
            if cur and size + n > max_chars:
                out.append(Unit(f"U{len(out) + 1}", d.name, cur))
                cur, size = [], 0
            cur.append(loc)
            size += n
        if cur:
            out.append(Unit(f"U{len(out) + 1}", d.name, cur))
    return out
