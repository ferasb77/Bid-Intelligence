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
    # the deliverables themselves -- not a procedure about them ("Deliverable
    # Submission, Review and Approval") or a table column ("Deliverable title")
    ("deliverables", r"^((expected |key |required )?(deliverables?|outputs?)( list| schedule)?|phase \w{1,3} deliverables)$"),
    ("timeline", r"^(.*\b(workflow|timeline|time ?frame|schedule|work ?plan|implementation plan|duration|period of performance)\b.*)$"),
    ("qualifications", r"^((required |minimum )?(qualifications?|eligibility( criteria)?|experience( and qualifications)?|competencies|requirements for (bidders|applicants|consultants)|profile)|bidder requirements)\b"),
    ("general", r"^((general|other|special) (requirements|conditions|obligations))\b"),
    # whole heading: "Submission milestone" / "Submission date" are table columns, not the instructions
    ("submission", r"^(submission( requirements| instructions| procedures?| method| of (the )?(bids?|proposals?|tenders?|offers?|applications?|quotations?|bid proposals?)( in [a-z ]+)?)?|((bid|tender) )?proposal (content|requirements|format|submission)|required documents|documents (to be submitted|required)|how to apply|to apply|application (process|procedure|requirements)|instructions to (bidders|tenderers|applicants|offerors))$"),
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
_ITEM_START = re.compile(r"^(?:[-•●▪–*]\s+|\(?\d{1,2}[.)]\s+|\(?[a-zA-Z][.)]\s+|[ivx]{1,4}[.)]\s+|"
                         r"\d{1,2}(?:\.\d{1,2})+\.?\s+(?=[A-Z0-9(“\"'])|\d{1,2}[A-Z]\.\s+(?=[A-Z]))")
# A short phase/stage label on its own line ("Phase 2") is a sub-heading, never
# the tail of the previous item.
_STANDALONE_LABEL = re.compile(r"^(?:phase|stage|part|lot|step)\s+[0-9IVX]{1,3}[A-Z]?\s*[:.–-]?$", re.I)
_BULLET_ONLY = re.compile(r"^[-•●▪–*o]$")
_NUMBERING = re.compile(r"^(?:section\s+)?(?:\d{1,2}(?:\.\d{1,2})*[.)]?|[A-Z][.)]|[IVX]{1,4}[.)])\s+", re.I)
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


_ARABIC_CHAR = re.compile(r"[؀-ۿﭐ-﷿ﹰ-﻿]")


def fold(s: str) -> str:
    """Case/space/punctuation-insensitive form used to verify text against documents.

    Arabic letters are kept (in arabic_text.match_key form: diacritics,
    tatweel and letter variants folded, Arabic-Indic digits -> 0-9), so an
    Arabic excerpt verifies against Arabic source text. Before this, every
    Arabic letter folded away: an Arabic excerpt reduced to nothing (never
    verifiable) or to its bare digits (matchable anywhere). Text without
    Arabic characters folds exactly as before."""
    s = s or ""
    if _ARABIC_CHAR.search(s):
        import arabic_text
        s = arabic_text.match_key(s)
        s = s.replace("–", "-").replace("—", "-").replace("’", "'")
        return re.sub(r"[^a-z0-9%@.ء-ي]+", " ", s).strip()
    s = s.lower().replace("–", "-").replace("—", "-").replace("’", "'")
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


# ── Page furniture: running headers/footers and contents pages ──────────────
# Long tender packages repeat a header block on every page ("Tender No.: X
# Page 8 of 12 / <title> / Form (A)") and open each part with an index. Read
# as body text, a header line became a section heading on every page (e.g.
# "Exhibit II – Schedule of Compensation" -> a timeline section) and an index
# entry became the opportunity synopsis. Both are layout, not statements.

_TOC_HEAD = re.compile(r"^(?:index|contents|table of contents)$", re.I)
_CLAUSE_NO = re.compile(r"^(?:\d{1,3}(?:\.\d{1,2})*\.?|\(\d{1,2}\)|\d{1,2}[A-Z]\.?|\(?[a-z]\)|\([ivx]{1,4}\)|[ivx]{1,4}[.)])$")
_PLACEHOLDER = re.compile(r"_{4,}|\.{6,}|…{2,}|\bX{4,}\b|\(name of [^)]{0,40}\)", re.I)
_FURNITURE_ZONE_TOP, _FURNITURE_ZONE_BOTTOM, _FURNITURE_MIN_PAGES = 6, 3, 3


def _furniture_key(text: str) -> str:
    if _CLAUSE_NO.match(text.strip()):
        return ""  # a clause number at the top of a page ("2.0") is content, however often the shape repeats
    return re.sub(r"\d+", "#", fold(text))


def _is_tocish(text: str) -> bool:
    t = text.strip()
    return bool(_CLAUSE_NO.match(t)) or (len(t) <= 80 and not t.endswith((".", ";", ":", ",")))


def content_lines(documents: list[tuple[str, str]]) -> list[dict]:
    """located_lines() without page furniture: lines repeated in the top/
    bottom band of at least three pages of the same document (running
    headers/footers, page numbers folded), and contents/index pages (from an
    INDEX / CONTENTS heading to the end of its page, continuing onto
    following pages that are still only short entries). Workbook sheets are
    never filtered."""
    lines = located_lines(documents)
    pages: dict[tuple, list[int]] = {}
    for i, ln in enumerate(lines):
        if ln.get("page") is not None and not ln.get("sheet"):
            pages.setdefault((ln["doc"], ln["page"]), []).append(i)
    seen: dict[tuple, set] = {}
    for (doc, page), idx in pages.items():
        zone = idx[:_FURNITURE_ZONE_TOP] + idx[-_FURNITURE_ZONE_BOTTOM:]
        for i in zone:
            seen.setdefault((doc, _furniture_key(lines[i]["text"])), set()).add(page)
    drop: set[int] = set()
    for (doc, page), idx in pages.items():
        zone = set(idx[:_FURNITURE_ZONE_TOP] + idx[-_FURNITURE_ZONE_BOTTOM:])
        for i in zone:
            k = _furniture_key(lines[i]["text"])
            if k and len(seen.get((doc, k), ())) >= _FURNITURE_MIN_PAGES:
                drop.add(i)
    toc_open = None  # doc whose previous page ended inside a contents list
    for (doc, page), idx in sorted(pages.items(), key=lambda kv: kv[1][0]):
        body = [i for i in idx if i not in drop]
        # the INDEX line itself may repeat on several pages (and so count as
        # furniture) -- look for it among all of the page's lines
        start = next((n for n, i in enumerate(idx)
                      if _TOC_HEAD.match(_NUMBERING.sub("", lines[i]["text"]).strip().rstrip(":"))), None)
        if start is not None:
            drop.update(idx[start:])
        elif toc_open == doc and len(body) >= 6 and \
                sum(_is_tocish(lines[i]["text"]) for i in body) >= 0.8 * len(body):
            drop.update(body)
        else:
            toc_open = None
            continue
        toc_open = doc
    return [ln for i, ln in enumerate(lines) if i not in drop]


def _template_pages(lines: list[dict]) -> set[tuple]:
    """Pages of a fill-in form (resume format, guarantee template ...): two or
    more blank placeholders. Their headings are the form's fields, not the
    buyer's sections."""
    counts: dict[tuple, int] = {}
    for ln in lines:
        if ln.get("page") is not None:
            n = len(_PLACEHOLDER.findall(ln["text"]))
            if n:
                counts[(ln["doc"], ln["page"])] = counts.get((ln["doc"], ln["page"]), 0) + n
    return {k for k, n in counts.items() if n >= 2}


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
    pending_number = None  # a clause number on its own line ("3.2.", "5A", "(c)") opens the next item
    lines = content_lines(documents)
    templates = _template_pages(lines)
    in_list = False  # after a lead-in ("... covering at least the following areas:") until a sentence ends
    for ln in lines:
        text = ln["text"]
        after_lead_in = in_list
        if text.rstrip().endswith(":") and len(text.split()) >= 4:
            in_list = True
        elif text.rstrip().endswith("."):
            in_list = False
        if cur is not None and cur["doc"] != ln["doc"]:
            cur = None  # a section never runs on into the next document
        if _BULLET_ONLY.match(text):
            pending_bullet = True
            continue
        if not pending_bullet and _CLAUSE_NO.match(text):
            pending_number = text
            continue
        # after a bullet or a list reference ("1A", "(c)") comes a list entry, never a heading;
        # after a clause number ("15.0") a heading may follow
        listing = pending_bullet or bool(pending_number and not re.match(r"^\d{1,3}(?:\.\d{1,2})*\.?$", pending_number))
        # an un-numbered title-like line inside a lead-in list ("Background", "Timeline") is
        # an entry of that list, not a section heading
        listing = listing or (after_lead_in and pending_number is None and not _NUMBERING.match(text))
        key = None if listing else _heading_key(text)
        on_template = (ln["doc"], ln.get("page")) in templates
        if key:
            # a fill-in form's field labels ("EXPERIENCE:") are not the buyer's sections
            cur = None if on_template else {"key": key, "heading": norm(_NUMBERING.sub("", text).rstrip(":")),
                                            **_ref(ln), "items": []}
            if cur is not None:
                out.append(cur)
            pending_bullet, pending_number = False, None
            continue
        if cur is not None and not pending_bullet and _is_other_heading(text, number=pending_number):
            cur = None  # a numbered heading of another topic ends the section
        if cur is None:
            pending_bullet, pending_number = False, None
            continue
        if _COURTESY.match(text):
            continue
        starts = (pending_bullet or pending_number is not None or bool(_ITEM_START.match(text))
                  or bool(_LABEL_START.match(text)) or bool(_STANDALONE_LABEL.match(text)))
        body = _ITEM_START.sub("", text).strip() if not pending_bullet else text
        items = cur["items"]
        prev = items[-1] if items else None
        same_place = prev is not None and prev["doc"] == ln["doc"]
        if (not starts and prev is not None and same_place
                and (not prev["text"].rstrip().endswith((".", ":", "!", "?")) or body[:1].islower())):
            prev["text"] = norm(prev["text"] + " " + body)
        else:
            items.append({"text": norm(body), "doc": ln["doc"], "page": ln.get("page"), "sheet": ln.get("sheet"),
                          "numbered": bool(re.match(r"^\(?\d{1,2}[.)]\s", text)
                                           or (pending_number and re.match(r"^\(?\d{1,2}[.)]$", pending_number))),
                          # opened by a bullet / item number / reference code ("1A"): a list entry,
                          # however short -- never a sub-heading
                          "listed": bool(pending_bullet or pending_number or _ITEM_START.match(text))})
        pending_bullet, pending_number = False, None
    for s in out:
        # fill-in template text ("we (Name of Banker) ... ……") is never a statement of the buyer
        s["items"] = [i for i in s["items"] if len(i["text"]) > 1 and not _PLACEHOLDER.search(i["text"])]
    return out


def _is_other_heading(text: str, *, number: str | None) -> bool:
    """An all-capitals heading line of a topic outside SECTION_PATTERNS that
    carries a top-level clause number ("16.0 / JOINT BID PROPOSAL") -- the end of
    the current section, not more of its content. A sub-clause heading
    ("14.2.1 / TECHNICAL BID PROPOSAL PACKAGE") stays inside its section."""
    t = text.strip()
    top = r"\d{1,2}(?:\.0)?\.?"
    has_number = bool(number and re.fullmatch(top, number)) or bool(re.match(top + r"\s+\S", t))
    t = _NUMBERING.sub("", t).strip()
    letters = re.sub(r"[^A-Za-z]", "", t)
    return (has_number and len(letters) >= 4 and t.isupper() and len(t) <= 70 and len(t.split()) <= 8
            and not t.endswith((".", ",", ";")))


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
    for ln in content_lines(documents):
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
    # sentence ends, and inline bullets ("... following: • A. • B.") -- each bullet is its own statement
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9(\"'])|\s+[•●▪]\s+", norm(buf))
    return [{"text": p.strip(), **ref} for p in parts
            if len(p.strip()) > 3 and not _CLAUSE_NO.match(p.strip()) and not _PLACEHOLDER.search(p)]


# Any inflection of the submit/send/deliver verbs ("are to be sent by email",
# "shall be emailed to", "deliver to"), or "<offer> ... must/shall/are to be".
_SUBMIT_HINT = re.compile(
    r"\b(submit\w*|submission|send|sent|e-?mailed|deliver\w*|lodg\w*|apply|"
    r"(proposals?|bids?|offers?|tenders?|quotations?|applications?|responses?)\s+"
    r"(must|shall|should|will|are\s+to|is\s+to)\s+be)\b", re.I)
_OFFER = re.compile(r"\b(proposals?|bids?|offers?|tenders?|quotations?|applications?|responses?|submissions?)\b", re.I)
# Questions/clarification contacts are not the submission channel unless the
# sentence also says the proposal itself goes there.
_ENQUIRY = re.compile(r"\b(questions?|enquir\w*|inquir\w*|clarifications?|queries|query)\b", re.I)
_CHANNEL = re.compile(r"(e-?mail|@|portal|online|upload|e-?tender|platform|hand[- ]deliver|deliver(ed)? to|sealed envelope|courier|address)", re.I)
_DEADLINE = re.compile(r"\b(no later than|not later than|deadline|closing (date|time)|due (date|by)|before\s+\d{1,2}[:.]\d{2})\b", re.I)
_LATE = re.compile(r"\b(late|after the (\w+ ){0,2}(deadline|closing))\b.*\b(not be (considered|accepted|evaluated)|rejected|disqualif)", re.I)
_SUBJECT = re.compile(r"\bsubject (line|of the e-?mail)\b", re.I)


def _is_method_sentence(text: str) -> bool:
    """A sentence saying how/where the proposal is submitted."""
    if not (_SUBMIT_HINT.search(text) and _CHANNEL.search(text)):
        return False
    if _ENQUIRY.search(text) and not re.search(r"\bsubmi\w*", text, re.I):
        # "Questions must be sent to x@y" -- an enquiry contact, unless the
        # same sentence also says proposals/bids go there.
        stripped = _ENQUIRY.sub(" ", text)
        return bool(_OFFER.search(stripped)) and not re.search(
            r"\b(about|regarding|concerning|on)\s+the\s+(proposals?|bids?|offers?|tenders?|rfp|solicitation)\b",
            text, re.I)
    return True


# The offer itself goes by e-mail: "by/via e-mail", "e-mailed to", "to the
# following e-mail", "submit/send ... to x@y". An address merely printed in a
# contact block ("Email: x@y" under a postal address) is contact information.
_EMAIL_SUBMIT = re.compile(
    r"\b(?:by|via|through|per)\s+e-?mail\b|\be-?mail(?:ed)?\s+to\b|\be-?mailed\b|\bto\s+(?:the\s+)?(?:following\s+)?e-?mail\b|"
    r"\b(?:submit\w*|sen[dt]|deliver\w*|forward\w*|lodg\w*)\b[^.@]{0,80}?\b(?:to|at)\s*:?\s*[A-Za-z0-9._%+-]+@", re.I)
_EMAIL_LABEL = re.compile(r"\be-?mail\s*(?:address)?\s*:\s*$", re.I)
_PHYSICAL = re.compile(r"\bby hand\b|\bhand[- ]deliver\w*|\bcourier\b|\bsealed\b|\benvelopes?\b|"
                       r"\b(?:bound|hard) cop(?:y|ies)\b|\bdeliver\w*\b[^.]{0,40}\baddress\b|"
                       r"\bto the (?:following|below|above) address\b", re.I)
_ELECTRONIC = re.compile(r"portal|online|upload|e-?tender|platform", re.I)


def _submission_emails(text: str) -> tuple[list[str], list[str]]:
    """(submission addresses, contact-only addresses) stated in one sentence."""
    sub, contact = [], []
    about_offer = bool(_OFFER.search(text) or re.search(r"\bsubmi", text, re.I))
    if not about_offer:  # e.g. a contract's notices address -- neither the channel nor a bid contact
        return sub, contact
    for m in EMAIL.finditer(text):
        e = m.group(0).rstrip(".")
        labelled = _EMAIL_LABEL.search(text[max(0, m.start() - 20):m.start()])
        (contact if labelled or not _EMAIL_SUBMIT.search(text) else sub).append(e)
    return sub, contact


def submission_instructions(documents: list[tuple[str, str]]) -> dict:
    """Verbatim submission facts: method sentence(s), addresses, deadline
    sentence(s), subject-line and late-submission rules, each located.

    The channel is read from what the method sentences say is done with the
    offer: an e-mail address counts as the submission channel only when a
    sentence sends the offer to it. An address printed in a contact block
    (e.g. under the postal address for sealed, hand-delivered bids) is
    returned separately as a contact, never as the method."""
    sents = located_sentences(documents)
    method = [s for s in sents if _is_method_sentence(s["text"])]
    emails, contacts, seen = [], [], set()
    for s in method:
        sub, contact = _submission_emails(s["text"])
        for e, target in [(e, emails) for e in sub] + [(e, contacts) for e in contact]:
            if e.lower() not in seen:
                seen.add(e.lower())
                # The address is printed only as found in the document text,
                # with the sentence that states it as its reference.
                target.append({"email": e, "doc": s["doc"], "page": s.get("page"),
                               "sheet": s.get("sheet"), "sentence": s})
    # Only sentences about the offer itself decide the channel -- a contract's
    # notices clause ("notices ... delivered by hand ... or e-mail") does not.
    offer = [s for s in method if _OFFER.search(s["text"])]
    by_channel = {
        "Email": [s for s in method if any(e["sentence"] is s for e in emails)
                  or (s in offer and re.search(r"\be-?mail", s["text"], re.I) and _EMAIL_SUBMIT.search(s["text"]))],
        "Electronic submission": [s for s in offer if _ELECTRONIC.search(s["text"])],
        "Physical delivery": [s for s in offer if _PHYSICAL.search(s["text"])],
    }
    stated = [c for c in ("Email", "Electronic submission", "Physical delivery") if by_channel[c]]
    if not stated and contacts:
        # nothing else is said about how the offer travels: the address printed
        # with the submission instructions is the channel (as before)
        emails, contacts = contacts, []
        by_channel["Email"] = [e["sentence"] for e in emails]
        stated = ["Email"]
    channel = " / ".join(stated) if stated else None
    # the sentence that states the channel leads, so the report quotes the method itself
    ordered, ids = [], set()
    for s in [s for c in stated for s in by_channel[c]] + method:
        if id(s) not in ids:
            ids.add(id(s))
            ordered.append(s)
    method = ordered
    return {
        "channel": channel,
        "method_sentences": method[:3],
        "emails": emails,
        "contact_emails": contacts,
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
