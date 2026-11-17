"""Controlled English rendering of Arabic / bilingual procurement documents,
linked line-by-line to the original Arabic evidence.

Why this exists
---------------
The Phoenix reports (phoenix_reports.py) print only statements verified
against the documents' own text. An English statement can never match Arabic
characters, so Arabic packages produced near-empty reports. Translating the
whole package into a free-standing English text would break the evidence
chain. This module keeps the chain intact:

    original Arabic line (exactly as extracted, with document/page/sheet)
      -> English rendering of that line (machine translation, made once per
         FAST run and persisted in the FAST snapshot)
      -> deterministic consistency check (arabic_text.check_translation:
         every number, percentage, date/month, e-mail address and URL must
         agree between the two)
      -> only CHECKED lines are ever used in an English report.

A line whose rendering fails the check is WITHHELD: nothing from it reaches
the English reports, so an unsupported translation is never presented as a
verified fact. The original Arabic stays available as evidence in the app.

Pure functions except ``translate_documents`` (model calls). The reports
consume only the persisted payload -- they remain zero-model.

Persisted payload (FastAnalysisResult.source_translations)::

    {"schema": "source-translations/1", "status": "COMPLETE|PARTIAL|FAILED|NOT_NEEDED",
     "model": str, "created_at": iso,
     "documents": {name: {"language": "ar|mixed", "segments": [
         {"line": int, "page": int|None, "sheet": str|None, "original": str,
          "english": str|None, "status": "CHECKED|WITHHELD|NOT_TRANSLATED", "issues": [str]}]}},
     "summary": {"segments", "checked", "withheld", "not_translated"}}
"""
from __future__ import annotations

import copy
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import arabic_text as at

SCHEMA = "source-translations/1"
CHECKED, WITHHELD, NOT_TRANSLATED = "CHECKED", "WITHHELD", "NOT_TRANSLATED"
TRANSLATION_MODEL = os.getenv("SOURCE_TRANSLATION_MODEL") or "claude-haiku-4-5-20251001"
_BATCH_CHARS = 4500
_BATCH_LINES = 90
_MAX_OUTPUT_TOKENS = 8000
_CONCURRENCY = 3

_MARKER = re.compile(r"^\[\[SOURCE:\s*(?P<doc>[^|\]]+?)\s*(?:\|\s*(?P<rest>[^\]]*))?\]\]\s*$")


# ═══════════════════════════════════════════════════════════════════════
# Language detection and segmentation
# ═══════════════════════════════════════════════════════════════════════

def document_languages(documents: list[tuple[str, str]]) -> dict[str, str]:
    """{document name: 'en' | 'ar' | 'mixed' | 'unknown'} -- automatic; the
    user never selects a language."""
    return {name: at.detect_language(text) for name, text in documents or []}


def needs_translation(documents: list[tuple[str, str]]) -> bool:
    return any(lang in (at.LANG_AR, at.LANG_MIXED) for lang in document_languages(documents).values())


def _located(text: str):
    """(line_index, page, sheet, stripped_line, is_marker) for every line."""
    page = sheet = None
    for idx, raw in enumerate((text or "").splitlines()):
        line = raw.strip()
        m = _MARKER.match(line)
        if m:
            page = sheet = None
            for part in (m.group("rest") or "").split("|"):
                k, _, v = part.partition(":")
                k, v = k.strip().upper(), v.strip()
                if k == "PAGE" and v.isdigit():
                    page = int(v)
                elif k == "SHEET":
                    sheet = v
            yield idx, page, sheet, line, True
            continue
        yield idx, page, sheet, line, False


def segment_documents(documents: list[tuple[str, str]]) -> dict[str, dict]:
    """Lines needing an English rendering: every non-marker line of an
    Arabic or mixed document that contains Arabic letters."""
    out: dict[str, dict] = {}
    for name, text in documents or []:
        lang = at.detect_language(text)
        if lang not in (at.LANG_AR, at.LANG_MIXED):
            continue
        segs = [{"line": idx, "page": page, "sheet": sheet, "original": line,
                 "english": None, "status": NOT_TRANSLATED, "issues": []}
                for idx, page, sheet, line, is_marker in _located(text)
                if not is_marker and line and at.has_arabic(line)]
        out[name] = {"language": lang, "segments": segs}
    return out


# ═══════════════════════════════════════════════════════════════════════
# Translation (model calls; run once per FAST run)
# ═══════════════════════════════════════════════════════════════════════

TRANSLATION_PROMPT = """You translate lines of an Arabic (or mixed Arabic/English) public-procurement \
document into English for a procurement analyst. Each input line is "<id>\\t<text>". Lines are in \
document order; a line may be a heading, a table row (cells separated by " | "), a list item, or a \
fragment of a sentence that continues on the next line.

Rules -- accuracy outranks fluency:
1. Translate each line separately and completely. Never merge, split, summarise, reorder or skip \
lines, and never add information that is not in the line (no explanations, no inferred dates, no \
notes). A fragment stays a fragment.
2. Numbers: keep every number exactly, written with Western digits (٣٠ -> 30, ١٥٠٠٠ -> 15000, \
٢٫٥ -> 2.5). Keep percentages as N%. Do not convert currencies or units.
3. Dates: keep the calendar. Gregorian month names, including Levantine/Iraqi names, become English \
month names (كانون الثاني -> January, شباط -> February, آذار -> March, نيسان -> April, أيار -> May, \
حزيران -> June, تموز -> July, آب -> August, أيلول -> September, تشرين الأول -> October, \
تشرين الثاني -> November, كانون الأول -> December). Hijri dates stay Hijri, transliterated, with "AH" \
(e.g. "15 Jumada al-Awwal 1448 AH"); never convert a Hijri date to Gregorian. Write a full date as \
"30 November 2026". Keep numeric dates as numbers in their original order (٣٠/١١/٢٠٢٦ -> 30/11/2026).
4. Copy e-mail addresses, URLs, reference/tender numbers and English words exactly as written.
5. Headings: render as a short English heading in Title Case; render leading heading/list numbering \
as "3." (e.g. "٣- نطاق العمل" -> "3. Scope of Work").
6. Use the procurement meaning in context, not a word-for-word gloss. Usual meanings include: \
كراسة الشروط والمواصفات = Terms and Specifications Booklet (tender document); المنافسة / المناقصة = \
tender; طلب عروض = request for proposals; الجهة الحكومية / الجهة المتعاقدة / صاحب العمل = contracting \
entity; المتنافس / مقدم العرض / المورد = bidder; العرض الفني = technical proposal; العرض المالي = \
financial proposal; جدول الكميات = bill of quantities; الضمان الابتدائي = bid bond (bid security); \
الضمان النهائي = performance bond; آخر موعد لتقديم العروض = deadline for submission of proposals; \
فتح المظاريف = opening of envelopes; معايير التقييم = evaluation criteria; الوزن النسبي = weight; \
الحد الأدنى = minimum; نطاق العمل = scope of work; المخرجات / التسليمات = deliverables; شروط الأهلية \
= eligibility requirements; السجل التجاري = commercial registration; شهادة الزكاة = Zakat certificate; \
غرامات التأخير = delay penalties; الدفعة المقدمة = advance payment; مستخلص = progress invoice; \
ملحق = addendum when it amends the tender, otherwise annex/appendix (decide from the line itself); \
تمديد = extension; يلغى ويستبدل = is cancelled and replaced. Modal force must be kept: يجب / يلتزم = \
must/shall; يجوز = may; لا يجوز = must not.
7. Keep proper names of organisations and places as their established English name when the line \
itself makes it certain; otherwise transliterate.

Return ONLY JSON: {"lines": {"<id>": "<English>", ...}} with exactly one entry per input id."""


def _batches(segs: list[dict]) -> list[list[int]]:
    out, cur, size = [], [], 0
    for i, s in enumerate(segs):
        n = len(s["original"])
        if cur and (size + n > _BATCH_CHARS or len(cur) >= _BATCH_LINES):
            out.append(cur)
            cur, size = [], 0
        cur.append(i)
        size += n
    if cur:
        out.append(cur)
    return out


def _parse_lines(raw: str) -> dict[str, str]:
    t = (raw or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        data = json.loads(t)
    except Exception:
        m = re.search(r"\{.*\}", t, re.S)
        if not m:
            return {}
        try:
            data = json.loads(m.group(0))
        except Exception:
            return {}
    lines = data.get("lines") if isinstance(data, dict) else None
    return {str(k): v for k, v in (lines or {}).items() if isinstance(v, str)}


def _translate_batch(client, doc_name: str, segs: list[dict], idxs: list[int],
                     telemetry: list, telemetry_context: dict | None) -> None:
    from config import execute_messages_create
    body = "\n".join(f"{n}\t{segs[i]['original']}" for n, i in enumerate(idxs, 1))
    t0 = time.monotonic()
    kwargs = {}
    if telemetry_context:
        kwargs["telemetry_context"] = dict(telemetry_context, operation="source_translation")
    try:
        resp = execute_messages_create(
            client, model=TRANSLATION_MODEL, max_tokens=_MAX_OUTPUT_TOKENS,
            messages=[{"role": "user", "content": [
                {"type": "text", "text": TRANSLATION_PROMPT + f"\n\nDOCUMENT: {doc_name}\nLINES:\n{body}"}]}],
            **kwargs)
        lines = _parse_lines(resp.content[0].text)
        usage = getattr(resp, "usage", None)
        telemetry.append({"doc": doc_name, "lines": len(idxs), "seconds": round(time.monotonic() - t0, 3),
                          "input_tokens": getattr(usage, "input_tokens", None),
                          "output_tokens": getattr(usage, "output_tokens", None),
                          "stop_reason": getattr(resp, "stop_reason", None)})
    except Exception as exc:
        telemetry.append({"doc": doc_name, "lines": len(idxs), "error": f"{type(exc).__name__}: {exc}"[:300]})
        return
    for n, i in enumerate(idxs, 1):
        en = (lines.get(str(n)) or "").strip()
        apply_translation(segs[i], en)


def apply_translation(seg: dict, english: str) -> dict:
    """Record a rendering for one segment and run the consistency check."""
    english = at.to_western_digits(re.sub(r"\s+", " ", english or "")).strip()
    if not english:
        seg.update(english=None, status=NOT_TRANSLATED, issues=["no translation returned"])
        return seg
    issues = at.check_translation(seg["original"], english)
    seg.update(english=english, status=WITHHELD if issues else CHECKED, issues=issues)
    return seg


def summarize(payload: dict) -> dict:
    segs = [s for d in (payload.get("documents") or {}).values() for s in d.get("segments") or []]
    return {"segments": len(segs), "checked": sum(s["status"] == CHECKED for s in segs),
            "withheld": sum(s["status"] == WITHHELD for s in segs),
            "not_translated": sum(s["status"] == NOT_TRANSLATED for s in segs)}


def translate_documents(documents: list[tuple[str, str]], api_key: str | None = None, *, client=None,
                        telemetry_context: dict | None = None) -> dict:
    """Translate every Arabic line of the package, once. Never raises: a
    failure yields status FAILED/PARTIAL and untranslated lines are simply
    not used by the English reports."""
    docs = segment_documents(documents)
    payload = {"schema": SCHEMA, "model": TRANSLATION_MODEL,
               "created_at": datetime.now(timezone.utc).isoformat(),
               "languages": document_languages(documents), "documents": docs, "telemetry": []}
    if not docs:
        payload.update(status="NOT_NEEDED", summary=summarize(payload))
        return payload
    try:
        if client is None:
            from config import get_anthropic_client
            client = get_anthropic_client(api_key=api_key)
    except Exception as exc:
        payload.update(status="FAILED", error=f"{type(exc).__name__}: {exc}"[:300], summary=summarize(payload))
        return payload
    jobs = [(name, d["segments"], idxs) for name, d in docs.items() for idxs in _batches(d["segments"])]
    lock = threading.Lock()
    telemetry: list = []

    def run(job):
        local: list = []
        _translate_batch(client, job[0], job[1], job[2], local, telemetry_context)
        with lock:
            telemetry.extend(local)

    with ThreadPoolExecutor(max_workers=_CONCURRENCY) as pool:
        list(pool.map(run, jobs))
    payload["telemetry"] = telemetry
    payload["summary"] = summarize(payload)
    s = payload["summary"]
    payload["status"] = ("COMPLETE" if s["not_translated"] == 0 else
                         "FAILED" if s["checked"] + s["withheld"] == 0 else "PARTIAL")
    return payload


# ═══════════════════════════════════════════════════════════════════════
# English view of the package (for the deterministic report digest)
# ═══════════════════════════════════════════════════════════════════════

def _seg_map(translations: dict | None) -> dict[str, dict[int, dict]]:
    return {name: {s["line"]: s for s in d.get("segments") or []}
            for name, d in ((translations or {}).get("documents") or {}).items()}


def english_view(documents: list[tuple[str, str]], translations: dict | None) -> list[tuple[str, str]]:
    """The package with every Arabic line replaced by its CHECKED English
    rendering (same markers, same line positions, so document/page/sheet
    references are unchanged). WITHHELD or untranslated Arabic lines are
    left out -- nothing unsupported can be reported from them. Documents
    without Arabic are returned unchanged."""
    segmap = _seg_map(translations)
    out = []
    for name, text in documents or []:
        segs = segmap.get(name)
        if not segs and not at.has_arabic(text or ""):
            out.append((name, text))
            continue
        lines = []
        for idx, raw in enumerate((text or "").splitlines()):
            line = raw.strip()
            seg = (segs or {}).get(idx)
            if seg is not None and seg.get("original") == line:
                if seg.get("status") == CHECKED and seg.get("english"):
                    lines.append(seg["english"])
                continue
            if _MARKER.match(line):
                lines.append(raw)  # markers keep the (possibly Arabic) file name
                continue
            if at.has_arabic(line):
                continue  # Arabic with no checked rendering -- never reported
            lines.append(at.to_western_digits(raw))
        out.append((name, "\n".join(lines)))
    return out


# ═══════════════════════════════════════════════════════════════════════
# Evidence linking: original Arabic <-> English statement
# ═══════════════════════════════════════════════════════════════════════

def _fold(s: str) -> str:
    import procurement_digest as pdg
    return pdg.fold(s)


class EvidenceIndex:
    """Lookups between original lines, their renderings and locations."""

    def __init__(self, documents: list[tuple[str, str]], translations: dict | None):
        self.translations = translations or {}
        self.segmap = _seg_map(translations)
        self.lines: dict[str, list[tuple]] = {}
        self._hay: dict[tuple, tuple] = {}
        for name, text in documents or []:
            self.lines[name] = [(idx, page, sheet, line) for idx, page, sheet, line, mk in _located(text)
                                if not mk and line]
        self._en_folded = {name: [(idx, seg, _fold(seg["english"])) for idx, seg in sorted(segs.items())
                                  if seg.get("status") == CHECKED and seg.get("english")]
                           for name, segs in self.segmap.items()}

    def _haystack(self, name: str, page) -> tuple:
        key = (name, page)
        if key not in self._hay:
            rows = [r for r in self.lines[name] if page is None or r[1] == page]
            folded, spans, pos = [], [], 0
            for r in rows:
                f = _fold(r[3])
                spans.append((pos, pos + len(f), r))
                folded.append(f)
                pos += len(f) + 1
            self._hay[key] = (" ".join(folded), spans)
        return self._hay[key]

    @property
    def active(self) -> bool:
        return bool(self.segmap)

    def _rendering(self, doc: str, idx: int, line: str) -> str | None:
        seg = self.segmap.get(doc, {}).get(idx)
        if seg is not None and seg.get("original") == line:
            return seg["english"] if seg.get("status") == CHECKED and seg.get("english") else None
        return None if at.has_arabic(line) else at.to_western_digits(line)

    def locate_original(self, doc: str | None, text: str, page=None) -> list[tuple] | None:
        """Original lines (idx, page, sheet, line) covering `text` (an
        excerpt in the original language), searched on `page` first."""
        needle = _fold(text)[:90].strip()
        if len(needle) < 3:
            return None
        names = [doc] if doc in self.lines else list(self.lines)
        for pass_page in ((page, None) if page else (None,)):
            for name in names:
                hay, spans = self._haystack(name, pass_page)
                at_ = hay.find(needle)
                if at_ < 0:
                    continue
                end = at_ + len(needle)
                covered = [r for s, e, r in spans if s < end and e > at_]
                return [(name,) + r for r in covered]
        return None

    def english_for_original(self, doc: str | None, text: str, page=None) -> dict | None:
        """English rendering of the original lines that contain `text`, with
        the evidence record; None when any covering line lacks a CHECKED
        rendering (the statement is then not reportable in English)."""
        covered = self.locate_original(doc, text, page)
        if not covered:
            return None
        parts = []
        for name, idx, pg, sheet, line in covered:
            en = self._rendering(name, idx, line)
            if not en:
                return None
            parts.append(en)
        first = covered[0]
        return {"english": " ".join(parts), "doc": first[0], "page": first[2], "sheet": first[3],
                "original": " ".join(c[4] for c in covered), "lines": [c[1] for c in covered]}

    def original_for_english(self, doc: str | None, text: str, page=None, sheet=None) -> str | None:
        """The original Arabic behind an English statement taken from the
        English view (joined if it spans several translated lines)."""
        if not self.segmap or not text:
            return None
        target = _fold(text)
        if not target:
            return None
        names = [doc] if doc in self.segmap else list(self.segmap)
        hits = []
        for name in names:
            for idx, seg, f in self._en_folded.get(name, []):
                if page and seg.get("page") and seg["page"] != page:
                    continue
                if sheet and seg.get("sheet") and seg["sheet"] != sheet:
                    continue
                if f and ((len(f) >= 8 and f in target) or (len(target) >= 12 and target in f)):
                    hits.append(seg["original"])
            if hits:
                break
        return " ".join(dict.fromkeys(hits)) or None


def evidence_record(field: str, statement: str, located: dict, *, model: str | None = None) -> dict:
    """The controlled representation linking an English statement to its
    original evidence (requirement 4 of the Arabic support task)."""
    import procurement_digest as pdg
    return {
        "field": field,
        "statement_en": statement,
        "original_text": located["original"],
        "original_language": "ar" if at.arabic_ratio(located["original"]) >= 0.5 else "mixed",
        "doc": located["doc"], "page": located.get("page"), "sheet": located.get("sheet"),
        "match_key": pdg.fold(located["original"]),
        "translation": {"text": located["english"], "method": "machine translation", "model": model,
                        "check": "numbers, dates, percentages and addresses consistent"},
        "status": "VERIFIED_ORIGINAL_CHECKED_TRANSLATION",
    }


# ═══════════════════════════════════════════════════════════════════════
# FAST result localisation (for the English reports only)
# ═══════════════════════════════════════════════════════════════════════

_TEXT_KEYS = ("stage", "parent_stage", "weight", "threshold", "description", "topic", "source_fact",
              "label", "original_value", "title", "client", "criterion_label", "category_scope",
              "evaluation_stage", "parent_heading", "minimum_score", "raw_wording", "submission_time")


def localize_fast_result(result: dict, documents: list[tuple[str, str]], translations: dict | None) -> dict:
    """A copy of a serialized FAST result in which every Arabic excerpt is
    replaced by the CHECKED English rendering of the original lines that
    contain it (the Arabic is kept in ``excerpt_original`` and the link in
    ``evidence``). An excerpt whose original cannot be located, or whose
    lines lack a checked rendering, becomes empty -- the item then fails the
    reports' verification and is not published. Arabic values in text
    fields are rendered the same way; values that cannot be are left as
    they are and flagged ``_untranslated``. The persisted FAST snapshot
    itself is never modified."""
    if not result:
        return result
    idx = EvidenceIndex(documents, translations)
    if not idx.active and not any(at.has_arabic(t or "") for _, t in documents or []):
        return result
    out = copy.deepcopy(result)
    model = (translations or {}).get("model")

    def fix_ref(ref: dict, field: str) -> None:
        ex = ref.get("excerpt") or ""
        if not at.has_arabic(ex):
            if ex:
                ref["excerpt"] = at.to_western_digits(ex)
            return
        loc = idx.english_for_original(ref.get("source_doc"), ex, ref.get("page"))
        ref["excerpt_original"] = ex
        if not loc:
            ref["excerpt"] = ""
            ref["evidence_status"] = "UNSUPPORTED_TRANSLATION"
            return
        ref["excerpt"] = loc["english"]
        ref["page"] = ref.get("page") or loc.get("page")
        ref["evidence"] = evidence_record(field, loc["english"], loc, model=model)

    def walk(node, doc=None, field=""):
        if isinstance(node, list):
            for x in node:
                walk(x, doc, field)
            return
        if not isinstance(node, dict):
            return
        doc = node.get("source_doc") or doc
        refs = node.get("source_refs")
        if isinstance(refs, list):
            for r in refs:
                if isinstance(r, dict):
                    fix_ref(r, field)
            if refs and isinstance(refs[0], dict):
                doc = refs[0].get("source_doc") or doc
        for k in _TEXT_KEYS:
            v = node.get(k)
            if isinstance(v, str) and at.has_arabic(v):
                loc = idx.english_for_original(doc, v, None)
                node[k + "_original"] = v
                if loc:
                    node[k] = loc["english"] if len(loc["original"]) <= len(v) * 1.6 + 20 else v
                    if node[k] == v:
                        node[k + "_untranslated"] = True
                else:
                    node[k + "_untranslated"] = True
            elif isinstance(v, str) and k in ("weight", "threshold", "minimum_score"):
                node[k] = at.to_western_digits(v)
        for k, v in node.items():
            if k != "source_refs" and isinstance(v, (dict, list)):
                walk(v, doc, k)

    for name, meta in list((out.get("doc_metadata_by_doc") or {}).items()):
        walk(meta, name, "doc_metadata")
    for key, val in out.items():
        if key not in ("doc_metadata_by_doc", "source_translations"):
            walk(val, None, key)
    return out


def original_grounded(value: str | None, documents: list[tuple[str, str]]) -> bool:
    """True when an original-language value occurs in the original text."""
    import procurement_digest as pdg
    return bool(value) and at.has_arabic(value) and pdg.corpus_contains(documents, value)


def annotate_with_originals(obj, idx: EvidenceIndex, _depth: int = 0):
    """Attach ``original`` (the Arabic evidence) to every located item
    ({"text"|"excerpt", "doc", "page"/"sheet"}) of a report fact model built
    from the English view. In place; returns obj."""
    if _depth > 8 or not idx.active:
        return obj
    if isinstance(obj, list):
        for x in obj:
            annotate_with_originals(x, idx, _depth + 1)
    elif isinstance(obj, dict):
        text = obj.get("text") if isinstance(obj.get("text"), str) else obj.get("excerpt")
        if "original" not in obj and isinstance(obj.get("excerpt_original"), str):
            obj["original"] = obj["excerpt_original"]
        if isinstance(text, str) and "doc" in obj and "original" not in obj:
            orig = idx.original_for_english(obj.get("doc"), text, obj.get("page"), obj.get("sheet"))
            if orig:
                obj["original"] = orig
        for k, v in list(obj.items()):
            if k != "original" and isinstance(v, (dict, list)):
                annotate_with_originals(v, idx, _depth + 1)
    return obj


def rendering_for_excerpt(translations: dict | None, doc: str | None, excerpt: str) -> str | None:
    """English rendering of an Arabic excerpt for display next to it, from
    the persisted segments alone (no document re-read): the CHECKED
    renderings of the consecutive original lines the excerpt overlaps.
    None when any overlapped line has no checked rendering."""
    if not excerpt or not at.has_arabic(excerpt):
        return None
    target = _fold(excerpt)
    if len(target) < 3:
        return None
    docs = (translations or {}).get("documents") or {}
    for name in ([doc] if doc in docs else list(docs)):
        segs = docs[name].get("segments") or []
        hit = [i for i, s in enumerate(segs)
               if (fs := _fold(s["original"])) and (fs in target or (len(target) >= 6 and target in fs))]
        if not hit:
            continue
        run = segs[hit[0]:hit[-1] + 1] if hit[-1] - hit[0] < 8 else [segs[i] for i in hit]
        if any(s.get("status") != CHECKED or not s.get("english") for s in run):
            return None
        return " ".join(s["english"] for s in run)
    return None


def payload_summary_line(translations: dict | None) -> str | None:
    """One factual sentence for report notes; None when nothing was translated."""
    t = translations or {}
    docs = [n for n, d in (t.get("documents") or {}).items() if d.get("segments")]
    if not docs:
        return None
    s = t.get("summary") or summarize(t)
    held = s["withheld"] + s["not_translated"]
    return (f"{len(docs)} source document(s) are in Arabic or bilingual. Their statements appear here in "
            f"English renderings of the original lines, each checked for consistent numbers, dates and "
            f"addresses; the original Arabic text is shown as evidence in the app."
            + (f" {held} line(s) whose rendering could not be checked were not used." if held else ""))
