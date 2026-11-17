"""Arabic / bilingual text handling for procurement documents.

Pure, deterministic, no I/O and no model call. Used by:

* extractor.py      -- repairing what PDF text extraction returns for Arabic
                       (presentation-form glyphs, visual-order lines);
* procurement_digest.fold / change_tracking -- Arabic-aware matching, so an
                       Arabic excerpt can be verified against Arabic source
                       text (the previous ASCII-only fold reduced Arabic to
                       an empty string, which can never verify anything);
* source_translation.py -- language detection and the numeral/date
                       consistency check between an Arabic original and its
                       English rendering.

Two different normalizations exist on purpose:

``repair_extracted_text``  changes how extracted text is *encoded* (Unicode
    presentation forms -> base letters, visual -> logical order). It never
    changes wording; it makes the extracted text equal to what the document
    says. The original file bytes are stored unchanged.
``match_key``  is a *matching-only* form (diacritics, tatweel, alef/yaa/taa
    marbuta variants and Arabic-Indic digits folded). It is never displayed
    and never stored as evidence.
"""
from __future__ import annotations

import re
import unicodedata

# ── character classes ────────────────────────────────────────────────────────

_ARABIC_LETTER = re.compile(r"[ء-يٱ-ۓۺ-ۿﭐ-﷿ﹰ-﻿]")
_LATIN_LETTER = re.compile(r"[A-Za-z]")
_PRESENTATION_FORMS = re.compile(r"[ﭐ-﷿ﹰ-﻿]+")
_DIACRITICS = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭ]")
_TATWEEL = "ـ"
_BIDI_CONTROLS = re.compile(r"[‎‏‪-‮⁦-⁩؜]")

ARABIC_INDIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_ARABIC_PUNCT = str.maketrans({"،": ",", "؛": ";", "؟": "?", "٪": "%", "٫": ".", "٬": ","})
_LETTER_VARIANTS = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ة": "ه",
                                  "ؤ": "و", "ئ": "ي", "ک": "ك", "ی": "ي"})


def has_arabic(text: str) -> bool:
    return bool(_ARABIC_LETTER.search(text or ""))


def arabic_ratio(text: str) -> float:
    """Share of letters that are Arabic (0..1); 0 when there are no letters."""
    ar = len(_ARABIC_LETTER.findall(text or ""))
    la = len(_LATIN_LETTER.findall(text or ""))
    return ar / (ar + la) if (ar + la) else 0.0


#: Language labels (also persisted in FAST snapshots -- do not rename).
LANG_EN, LANG_AR, LANG_MIXED, LANG_UNKNOWN = "en", "ar", "mixed", "unknown"


def detect_language(text: str) -> str:
    """'ar' / 'en' / 'mixed' for a document's extracted text (markers ignored).
    Mixed = both scripts carry real content (each >= 15% of letters)."""
    body = re.sub(r"\[\[[^\]]*\]\]", " ", text or "")
    ar = len(_ARABIC_LETTER.findall(body))
    la = len(_LATIN_LETTER.findall(body))
    if ar + la < 20:
        return LANG_UNKNOWN if ar + la == 0 else (LANG_AR if ar > la else LANG_EN)
    r = ar / (ar + la)
    if r >= 0.85:
        return LANG_AR
    if r <= 0.15:
        return LANG_EN
    return LANG_MIXED


_ARABIC_NUMERIC_SIGNS = str.maketrans({"٪": "%", "٫": ".", "٬": ","})


def to_western_digits(text: str) -> str:
    """Arabic-Indic digits and the Arabic percent / decimal / thousands signs
    as their Western equivalents (display only; evidence keeps the original)."""
    return (text or "").translate(ARABIC_INDIC_DIGITS).translate(_ARABIC_NUMERIC_SIGNS)


# ── extraction repair (encoding only, never wording) ─────────────────────────

def _nfkc_presentation_forms(text: str) -> str:
    """Arabic presentation-form glyphs (U+FB50-FDFF, U+FE70-FEFF), which many
    PDF producers emit, become the base letters they display. Only those code
    points are touched -- every other character is left exactly as extracted."""
    return _PRESENTATION_FORMS.sub(lambda m: unicodedata.normalize("NFKC", m.group(0)), text)


_TOKEN = re.compile(r"[ء-ي]{3,}")
_MIRROR = str.maketrans("()[]{}<>«»", ")(][}{><»«")
# A left-to-right run inside a right-to-left line: Latin words, numbers
# (Western or Arabic-Indic) with their separators, e-mail addresses, URLs.
_LTR_RUN = re.compile(r"[A-Za-z0-9٠-٩۰-۹@][A-Za-z0-9٠-٩۰-۹@._:/%+\-,' ]*"
                      r"[A-Za-z0-9٠-٩۰-۹%]|[A-Za-z0-9٠-٩۰-۹]")


def visual_order_score(text: str) -> tuple[int, int]:
    """(logical, visual) evidence counts. Arabic words very frequently start
    with the article 'ال'; text extracted in visual (reversed) order shows the
    same words ending in 'لا' instead."""
    toks = _TOKEN.findall(text or "")
    logical = sum(1 for t in toks if t.startswith("ال"))
    visual = sum(1 for t in toks if t.endswith("لا") and not t.startswith("ال"))
    return logical, visual


def is_visual_order(text: str) -> bool:
    logical, visual = visual_order_score(text)
    return visual >= 3 and visual > 2 * logical


def to_logical_order(line: str) -> str:
    """Reverse a visual-order RTL line into logical order, keeping embedded
    left-to-right runs (numbers, Latin words, e-mail addresses) readable."""
    if not has_arabic(line):
        return line
    return logical_from_visual(list(line))


def _bidi_class(cluster: str) -> str:
    c = next((ch for ch in cluster if not unicodedata.combining(ch)), cluster[:1])
    if not c:
        return "ON"
    if _ARABIC_LETTER.match(c):
        return "R"
    if "٠" <= c <= "٩" or c in "٫٬":
        return "AN"
    if c.isdigit():
        return "EN"  # Western and Extended Arabic-Indic (U+06F0..) digits
    if c.isalpha():
        return "L"
    if c.isspace():
        return "WS"
    if c in ",./: ":
        return "CS"
    if c in "+-":
        return "ES"
    if c in "%٪#$°£€":
        return "ET"
    return "ON"


def logical_from_visual(clusters: list[str]) -> str:
    """Logical order of one right-to-left line given its glyph clusters in
    visual (left-to-right) order.

    The line is reversed, then the runs the Unicode Bidirectional Algorithm
    would display left-to-right are reversed back -- Latin words, numbers
    (W2/W4/W5/W7: Western digits after Arabic letters behave as Arabic
    numbers; one separator between digits joins them: 12:00, 30/11/2026,
    2.5) and neutrals between two left-to-right items of the same kind
    (N1). Space-separated numbers stay separate runs, as they are displayed.
    Bracket glyphs in right-to-left context are mirrored back. Simplified
    (single paragraph, no explicit embeddings), which covers procurement
    text lines."""
    seq = list(reversed([c for c in clusters if c]))
    n = len(seq)
    if not n:
        return ""
    cls = [_bidi_class(c) for c in seq]
    # W2: EN preceded by an Arabic letter (searching back) -> AN; W7: by L -> L.
    last_strong = "R"
    for i, t in enumerate(cls):
        if t in ("R", "L"):
            last_strong = t
        elif t == "EN":
            cls[i] = "AN" if last_strong == "R" else "L" if last_strong == "L" else "EN"
    # W4: a single separator between two numbers of the same type joins them.
    for i in range(1, n - 1):
        if cls[i] in ("CS", "ES") and cls[i - 1] == cls[i + 1] and cls[i - 1] in ("AN", "EN", "L"):
            if cls[i - 1] != "L" or (seq[i - 1].isdigit() and seq[i + 1].isdigit()):
                cls[i] = cls[i - 1]
    # W5: terminators (%, currency) adjacent to a European number belong to
    # it (not to an Arabic number: "٣٠٪" keeps the sign on its logical side).
    for i, t in enumerate(cls):
        if t == "ET":
            j = i
            while j < n and cls[j] == "ET":
                j += 1
            near = [k for k in (i - 1, j) if 0 <= k < n]
            num = next((cls[k] for k in near if cls[k] == "EN" or
                        (cls[k] == "L" and seq[k].isdigit())), None)
            if num:
                for k in range(i, j):
                    cls[k] = num
    # Strong direction of each position for neutral resolution (N1/N2):
    # numbers count as R; Latin (incl. W7 numbers) as L.
    def strong(t: str) -> str | None:
        return "L" if t == "L" else "R" if t in ("R", "AN", "EN") else None
    level = [0] * n
    i = 0
    while i < n:
        s = strong(cls[i])
        if s is not None:
            level[i] = 2 if cls[i] in ("L", "AN", "EN") else 1
            i += 1
            continue
        j = i
        while j < n and strong(cls[j]) is None:
            j += 1
        before = strong(cls[i - 1]) if i > 0 else "R"
        after = strong(cls[j]) if j < n else "R"
        lv = 2 if before == after == "L" else 1
        for k in range(i, j):
            level[k] = lv
        i = j
    # Re-reverse every left-to-right run (level 2); numbers separated by a
    # right-to-left neutral (e.g. "9 / 11 / 2026") are separate runs.
    out: list[str] = []
    i = 0
    while i < n:
        if level[i] == 2:
            j = i
            while j < n and level[j] == 2:
                j += 1
            out.extend(reversed(seq[i:j]))
            i = j
        else:
            out.append(seq[i].translate(_MIRROR) if cls[i] == "ON" else seq[i])
            i += 1
    return "".join(out)


def repair_extracted_text(text: str, *, fix_visual_order: bool | None = None) -> tuple[str, dict]:
    """Repair one block (e.g. a PDF page) of extracted text. Returns
    (text, info) where info records what was changed, for metadata."""
    info = {"presentation_forms": False, "visual_order_fixed": False}
    if not has_arabic(text):
        return text, info
    out = text
    if _PRESENTATION_FORMS.search(out):
        out = _nfkc_presentation_forms(out)
        info["presentation_forms"] = True
    out = _BIDI_CONTROLS.sub("", out)
    if fix_visual_order is None:
        fix_visual_order = is_visual_order(out)
    if fix_visual_order:
        out = "\n".join(to_logical_order(ln) for ln in out.split("\n"))
        info["visual_order_fixed"] = True
    return out, info


# ── matching form (never displayed, never stored as evidence) ────────────────

def match_key(text: str) -> str:
    """Arabic-aware comparison form: presentation forms, diacritics, tatweel and
    letter variants folded; Arabic-Indic digits and punctuation mapped to
    their Western equivalents. Latin text is only lower-cased."""
    s = _nfkc_presentation_forms(text or "")
    s = _BIDI_CONTROLS.sub("", s)
    s = _DIACRITICS.sub("", s).replace(_TATWEEL, "")
    s = s.translate(_LETTER_VARIANTS).translate(ARABIC_INDIC_DIGITS).translate(_ARABIC_PUNCT)
    return s.lower()


# ── numerals and dates (translation consistency) ─────────────────────────────

GREGORIAN_MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august",
                    "september", "october", "november", "december"]

#: Arabic names for Gregorian months: Egyptian/Gulf transliterations and the
#: Levantine/Iraqi (Syriac) names, in match_key form.
_AR_MONTHS = {
    1: ["يناير", "كانون الثاني"], 2: ["فبراير", "شباط"], 3: ["مارس", "اذار"], 4: ["ابريل", "نيسان"],
    5: ["مايو", "ايار"], 6: ["يونيو", "يونيه", "حزيران"], 7: ["يوليو", "يوليه", "تموز"],
    8: ["اغسطس", "اب"], 9: ["سبتمبر", "ايلول"], 10: ["اكتوبر", "تشرين الاول"],
    11: ["نوفمبر", "تشرين الثاني"], 12: ["ديسمبر", "كانون الاول"],
}
#: Hijri month names (match_key form). Their English renderings are
#: transliterations, so a Hijri date must never be turned into a Gregorian one.
HIJRI_MONTHS = ["محرم", "صفر", "ربيع الاول", "ربيع الثاني", "ربيع الاخر", "جمادي الاولي", "جمادي الاخره",
                "جمادي الثانيه", "رجب", "شعبان", "رمضان", "شوال", "ذو القعده", "ذو الحجه"]

_NUM_WORDS = {
    "واحد": 1, "واحده": 1, "اثنان": 2, "اثنين": 2, "اثنتان": 2, "ثلاث": 3, "ثلاثه": 3, "اربع": 4, "اربعه": 4,
    "خمس": 5, "خمسه": 5, "ست": 6, "سته": 6, "سبع": 7, "سبعه": 7, "ثمان": 8, "ثماني": 8, "ثمانيه": 8,
    "تسع": 9, "تسعه": 9, "عشر": 10, "عشره": 10, "عشرون": 20, "عشرين": 20, "ثلاثون": 30, "ثلاثين": 30,
    "اربعون": 40, "اربعين": 40, "خمسون": 50, "خمسين": 50, "ستون": 60, "ستين": 60, "سبعون": 70, "سبعين": 70,
    "ثمانون": 80, "ثمانين": 80, "تسعون": 90, "تسعين": 90, "مائه": 100, "مئه": 100, "الف": 1000,
    "يومين": 2, "شهرين": 2, "سنتين": 2, "عامين": 2, "اسبوعين": 2,
}
_EN_NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
                 "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30,
                 "forty": 40, "fifty": 50, "sixty": 60, "ninety": 90, "hundred": 100, "thousand": 1000}

_NUM = re.compile(r"\d+(?:[.,]\d+)*")


def _numbers(text: str) -> list[str]:
    """Numbers as canonical strings ('1,500' -> '1500', '07' -> '7', '2.5' kept)."""
    out = []
    for m in _NUM.finditer(to_western_digits(text or "")):
        tok = m.group(0)
        if re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d+)?", tok):
            tok = tok.replace(",", "")
        for part in ([tok] if re.fullmatch(r"\d+(\.\d+)?", tok) else re.split(r"[.,]", tok)):
            if part:
                out.append(part.lstrip("0") or "0" if "." not in part else part)
    return out


def _arabic_word_numbers(key: str) -> set[str]:
    words = re.findall(r"[ء-ي]+", key)
    out = set()
    for w in words:
        w2 = w[1:] if w.startswith(("و", "ب", "ل")) and w[1:] in _NUM_WORDS else w
        w2 = w2[2:] if w2.startswith("ال") and w2[2:] in _NUM_WORDS else w2
        if w2 in _NUM_WORDS:
            out.add(str(_NUM_WORDS[w2]))
    return out


def gregorian_months_in_arabic(text: str) -> set[int]:
    key = match_key(text)
    found = set()
    for m, names in _AR_MONTHS.items():
        for n in names:
            if re.search(rf"(?<![ء-ي]){re.escape(n)}(?![ء-ي])", key):
                found.add(m)
    for d in re.finditer(r"\b(\d{1,4})\s*[/.\-]\s*(\d{1,2})\s*[/.\-]\s*(\d{1,4})\b", key):
        a, b, c = d.groups()
        if len(c) == 4 and 1 <= int(b) <= 12:   # d/m/yyyy
            found.add(int(b))
        if len(a) == 4 and 1 <= int(b) <= 12:   # yyyy-mm-dd
            found.add(int(b))
    return found


def check_translation(original: str, english: str) -> list[str]:
    """Deterministic consistency check of an English rendering against its
    original. Returns a list of issues (empty = consistent). It cannot prove a
    translation is right; it catches the failures that matter most for
    procurement facts: a number, percentage, date, month, e-mail address or
    URL that the rendering adds, drops or changes."""
    issues: list[str] = []
    if not (english or "").strip():
        return ["empty translation"]
    okey = match_key(original)
    o_nums = _numbers(okey)
    e_nums = _numbers(english)
    o_set = set(o_nums) | _arabic_word_numbers(okey)
    e_low = english.lower()
    e_words = {str(v) for k, v in _EN_NUM_WORDS.items() if re.search(rf"\b{k}\b", e_low)}
    months_o = gregorian_months_in_arabic(original) | {
        i + 1 for i, mname in enumerate(GREGORIAN_MONTHS) if re.search(rf"\b{mname}\b", okey)}
    months_e = {i + 1 for i, mname in enumerate(GREGORIAN_MONTHS) if re.search(rf"\b{mname}\b", e_low)}

    added = [n for n in e_nums if n not in o_set and not (n.isdigit() and int(n) in months_o)]
    # Number words in the rendering ("six sessions") must be stated in the
    # original too (as a word or digits). "one" is excluded: it is also a pronoun.
    added += [n for n in e_words if n != "1" and n not in o_set]
    if added:
        issues.append("number not in original: " + ", ".join(sorted(set(added))))
    month_nums = {str(m) for m in months_e}
    dropped = [n for n in o_nums if n not in e_nums and n not in e_words and n not in month_nums]
    if dropped:
        issues.append("number missing from translation: " + ", ".join(sorted(set(dropped))))
    if months_e - months_o:
        if any(h in okey for h in HIJRI_MONTHS):
            issues.append("Gregorian month given for a Hijri date")
        else:
            issues.append("month not in original: " + ", ".join(GREGORIAN_MONTHS[m - 1] for m in sorted(months_e - months_o)))
    if "%" in okey and "%" not in english and "percent" not in e_low:
        issues.append("percentage sign missing")
    for token in re.findall(r"[\w.+-]+@[\w-]+\.[\w.-]+|https?://\S+|www\.\S+", original or ""):
        if token.rstrip(".,;") not in english:
            issues.append(f"address not preserved: {token.rstrip('.,;')}")
    return issues


# ── display ──────────────────────────────────────────────────────────────────

def rtl_html(text: str, *, escape=None, style: str = "") -> str:
    """Arabic (or mixed) evidence as a right-to-left HTML block; isolates the
    excerpt so surrounding English layout is unaffected."""
    import html as _html
    esc = escape or _html.escape
    direction = "rtl" if arabic_ratio(text) >= 0.5 else "auto"
    return (f'<div dir="{direction}" lang="ar" style="unicode-bidi:isolate;text-align:start;'
            f'font-family:\'Noto Naskh Arabic\',\'Segoe UI\',Tahoma,\'Arial\',sans-serif;{style}">{esc(text)}</div>')
