"""Procurement facts for the Phoenix reports: what each passage of the
package MEANS, classified by a model and checked against the source.

Why this exists. The Opportunity Snapshot and the Bid Opportunity Assessment
used to decide the meaning of source text with keyword rules (a sentence with
"delivered" became the delivery location, any e-mail near "submission" became
the submission method, a heading containing "Pricing" made everything under it
pricing ...). Keyword rules cannot tell a contact address from a submission
destination, a methodology sentence from a place of performance, or a bank
guarantee from a professional qualification -- and nothing checked that the
evidence supported the meaning, only that the words existed.

This module asks the model -- once per package, alongside FAST -- for typed
facts, each with a verbatim quote and its page, and then verifies every fact
deterministically:

1. the quote must be found in the documents (it is re-located to the page
   where it actually occurs);
2. every number, date, amount, percentage, e-mail address and URL in the
   statement must appear in the quote -- otherwise the statement is replaced
   by the quote itself (nothing the source does not say can be printed);
3. category evidence gates: a submission method must name a channel, a budget
   must carry an amount, a guarantee must name a guarantee/bond/security/
   insurance, a weight must be printed in its quote (rule 2).

Facts that fail (1) are discarded and counted. Passages the model could not
finish (output limit, unreadable response, failed call) are returned as
coverage gaps with their pages, so the reports can disclose them.

Nothing here knows any buyer, document, title or reference. The model is the
one FAST already uses; the verification is pure and re-run at report time.
"""
from __future__ import annotations

import concurrent.futures
import json
import re
import time

import procurement_digest as pdg

SCHEMA = "report-facts/1"
FACTS_MODEL = "claude-haiku-4-5-20251001"  # the model FAST uses; unchanged
MAX_OUTPUT_TOKENS = 16000
CHUNK_CHARS = 40000
CONCURRENCY = 3
MAX_QUOTE_CHARS = 600

CATEGORIES = {
    "SCOPE": "Work or services the contractor will perform.",
    "DELIVERABLE": "An output the contractor must hand over during the contract (report, plan, training "
                   "delivered, system, portfolio ...). NOT a document to include in the proposal.",
    "DELIVERY_LOCATION": "Where the services are performed or delivered, only when the document states it. "
                         "NOT the buyer's address, NOT the bid submission address, NOT a description of how "
                         "or in what style the work is done, NOT programme geography unless the work happens there.",
    "SCHEDULE": "Contract duration, start/end dates, phases and their timing, delivery milestones. NOT the bid "
                "submission deadline and NOT the bid validity period.",
    "SUBMISSION_DEADLINE": "The date and time by which bids must be received, and how receipt time is determined.",
    "ELIGIBILITY": "Who may bid and pass/fail conditions for a BID to be considered (legal status, registration, "
                   "exclusion, conflict of interest, joint ventures, minimum thresholds stated as pass/fail). "
                   "NOT the contractor's obligations or defaults under the contract.",
    "QUALIFICATION": "Experience, expertise, certifications or key staff required of the bidder.",
    "PROPOSAL_CONTENT": "A document or item of information the bid must contain (technical or financial "
                        "proposal contents, forms to submit, certificates, references).",
    "SUBMISSION_METHOD": "One permitted way of submitting the bid together with its destination (e-mail "
                         "address, portal, physical delivery by hand/courier/post to an address). One fact per "
                         "permitted method; if the bidder may choose between methods, say so. NOT an address "
                         "for questions or a general contact.",
    "SUBMISSION_RULE": "How the bid must be prepared or submitted: format, packaging, sealing, marking, "
                       "file naming, passwords, language, number of copies, bid validity, late-submission rule.",
    "CLARIFICATION": "How, where and until when questions may be asked; contact details for enquiries.",
    "EVALUATION": "How BIDS are evaluated and compared: method, stages, criteria, weights, scores or thresholds "
                  "exactly as published. If no weight is published, do not state one. NOT dispute resolution or "
                  "performance assessment under the contract.",
    "AWARD": "Award basis and conditions, the buyer's rights to accept, reject, split or negotiate, "
             "conditions for contract signature.",
    "PRICING": "How prices must be quoted: currency, price basis, what prices include, taxes, price forms.",
    "BUDGET": "A stated budget, ceiling or estimated contract value, with its amount.",
    "PAYMENT": "Payment terms: schedule, milestones, invoicing, timing, retention.",
    "GUARANTEE": "Bid bond / bid security, performance guarantee, advance-payment guarantee, required "
                 "insurance -- with the amount or percentage where stated. NOT a professional qualification.",
    "CONTRACT_TERM": "A material contractual obligation: liability, penalties or liquidated damages, "
                     "intellectual property, confidentiality, termination, default, dispute resolution, governing "
                     "law, subcontracting, acceptance and warranty of the work.",
    "BUYER_CONTEXT": "Facts about the issuing organisation or the programme the procurement serves "
                     "(mission, background, funder, beneficiaries).",
    "OTHER": "Any other fact a bidder must know that fits no category above (costs borne by the bidder, "
             "site visit, pre-bid meeting, mandatory registration on a system ...).",
}

PROMPT = """You are reading part of a procurement package (RFP, ITB, RFQ, tender, call for proposals, addendum). \
Extract the facts a consulting firm needs to understand the opportunity, and classify each one by what it MEANS \
in its context -- not by the words it happens to contain.

Write one JSON object per line (JSON Lines). No prose, no markdown, no array.

First line, only if this part states what is being procured:
{"category": "ASSIGNMENT", "statement": "<1-2 plain sentences: who is procuring what, for whom or for what \
purpose, and the main parameters stated (duration, quantity, place)>", "quotes": [{"quote": "<passage>", \
"page": <n>}, ...], "delivery": {"statement": "<where the work is performed>", "quote": "<passage>", "page": <n>} or null}
"quotes" holds the one to three verbatim passages that together support every element of the statement.
"delivery" is the passage stating where the services are performed or delivered (DELIVERY_LOCATION meaning), or null if this part does not state it.

Then one line per fact:
{"category": "<CATEGORY>", "priority": <1|2|3>, "statement": "<one concise sentence stating the fact>", \
"quote": "<verbatim source passage>", "page": <n>}

priority: 1 = essential to understand what is procured and what a bid must meet (the actual services and \
deliverables of this assignment, decisive requirements, the submission method, amounts); 2 = important; \
3 = detail or standard contract boilerplate.

Categories:
{categories}

Rules:
- quote: copy ONE contiguous passage exactly as printed (same words, spelling and numbers), normally one or two \
sentences, at most 400 characters. Never join text from different places, never add "...", never paraphrase.
- statement: plain English, only what the quote says. Copy every number, date, amount, percentage, e-mail \
address and URL exactly as in the quote. Keep conditions, exceptions, options and alternatives ("either ... \
or", "unless", "only if", "may"). Never add a weight, amount, date, place or obligation the quote does not \
state. Do not evaluate or recommend.
- Places: an organisation's address, its offices, or the geography of a programme or project is not where \
this assignment is delivered unless the text says the work is done there; never present it as the delivery \
place, in any statement including ASSIGNMENT.
- page: the number in the nearest [[PAGE n]] marker before the quote.
- Ignore: tables of contents, running headers and footers, definitions, blank forms and templates the bidder \
fills in (but a requirement to SUBMIT a form is PROPOSAL_CONTENT), sample or example entries, and boilerplate \
with no consequence for this bid.
- A list of items (deliverables, documents, criteria) gives one line per item; keep the buyer's wording.
- Whenever this part states them, always include: where the work is delivered, every permitted submission method, the submission deadline, the contract duration, any budget, guarantee amounts and evaluation weights.
- If nothing in this part is relevant, output nothing.
- At most 80 lines. Most important facts first if you must choose."""

_PAGE_LINE = re.compile(r"^\[\[PAGE (\S+)\]\]$")
_NUM = re.compile(r"\d+(?:[.,:/]\d+)*")
_URLISH = re.compile(r"(?:https?://|www\.)\S+", re.I)
_CHANNEL = re.compile(r"e-?mail|@|portal|online|upload|electronic|platform|system|website|hand|courier|post|"
                      r"mail|deliver|address|envelope|hard ?cop|physical|office|box|submit", re.I)
_GUARANTEE = re.compile(r"guarant|bond|security|securities|insur|retention|surety", re.I)


def _segments(documents: list[tuple[str, str]]) -> list[dict]:
    """Page-sized segments of furniture-free content (running headers/footers
    and contents pages removed): [{"doc", "page", "sheet", "label", "text"}]."""
    segs: list[dict] = []
    for ln in pdg.content_lines(documents):
        label = ln.get("sheet") or ln.get("page")
        if not segs or (segs[-1]["doc"], segs[-1]["label"]) != (ln["doc"], label):
            segs.append({"doc": ln["doc"], "page": ln.get("page"), "sheet": ln.get("sheet"),
                         "label": label, "lines": []})
        segs[-1]["lines"].append(ln["text"])
    for s in segs:
        s["text"] = "\n".join(s["lines"])
    return segs


def chunks(documents: list[tuple[str, str]], max_chars: int = CHUNK_CHARS) -> list[dict]:
    """Model inputs: consecutive page segments of ONE document up to max_chars
    (a single oversized page is cut into parts)."""
    out: list[dict] = []
    for s in _segments(documents):
        body = f"[[PAGE {s['label'] if s['label'] is not None else '?'}]]\n{s['text']}\n"
        pieces = [body[i:i + max_chars] for i in range(0, len(body), max_chars)] or [body]
        for piece in pieces:
            if out and out[-1]["doc"] == s["doc"] and len(out[-1]["text"]) + len(piece) <= max_chars:
                out[-1]["text"] += piece
                out[-1]["labels"].append(s["label"])
            else:
                out.append({"doc": s["doc"], "text": piece, "labels": [s["label"]]})
    for c in out:
        labels = [str(x) for x in c["labels"] if x is not None]
        c["pages"] = (labels[0] if len(set(labels)) == 1 else f"{labels[0]}-{labels[-1]}") if labels else None
    return out


def _parse(text: str) -> list[dict]:
    rows = []
    for line in (text or "").splitlines():
        line = line.strip().rstrip(",")
        if not line.startswith("{"):
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue  # an unfinished last line after an output limit
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _call(client, chunk: dict, telemetry_context: dict | None) -> dict:
    from config import execute_messages_create
    prompt = PROMPT.replace("{categories}", "\n".join(f"- {k}: {v}" for k, v in CATEGORIES.items()))
    kwargs = {}
    if telemetry_context:
        kwargs["telemetry_context"] = dict(telemetry_context, operation="report_facts")
    t0 = time.monotonic()
    row = {"doc": chunk["doc"], "pages": chunk["pages"], "chars": len(chunk["text"])}
    try:
        resp = execute_messages_create(
            client, model=FACTS_MODEL, max_tokens=MAX_OUTPUT_TOKENS,
            messages=[{"role": "user", "content": [{"type": "text", "text":
                       f"{prompt}\n\nDOCUMENT: {chunk['doc']}\n\n{chunk['text']}"}]}], **kwargs)
        text = resp.content[0].text if resp.content else ""
        usage = getattr(resp, "usage", None)
        row.update(stop_reason=getattr(resp, "stop_reason", None),
                   input_tokens=getattr(usage, "input_tokens", None),
                   output_tokens=getattr(usage, "output_tokens", None))
        rows = _parse(text)
        row["rows"] = len(rows)
        if not rows and text.strip():
            row["error"] = "UNREADABLE_RESPONSE"
        return {"telemetry": dict(row, seconds=round(time.monotonic() - t0, 2)), "rows": rows}
    except Exception as exc:
        row["error"] = f"CALL_FAILED: {type(exc).__name__}: {exc}"[:300]
        return {"telemetry": dict(row, seconds=round(time.monotonic() - t0, 2)), "rows": []}


# ── deterministic verification (also re-run at report time) ────────────────

_TOKEN = re.compile(r"[a-zء-ي]+|\d+")
_QUOTE_PART = re.compile(r"(?<=[.;:!?])\s+|\s+(?=[-•▪]\s)")


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(pdg.fold(text))


def _skippable(tok: str) -> bool:
    """Source tokens a faithful quote may leave out: list numbering ("1-",
    "A-", "(b)") and page numbers."""
    return tok.isdigit() or len(tok) == 1


class _Index:
    """One token stream per document (words and numbers, furniture removed),
    each token mapped to its page/sheet segment."""

    def __init__(self, documents):
        self.segs = _segments(documents)
        self.docs: dict[str, dict] = {}
        for s in self.segs:
            d = self.docs.setdefault(s["doc"], {"toks": [], "seg": [], "at": {}})
            for t in _tokens(" ".join(s["lines"])):
                d["at"].setdefault(t, []).append(len(d["toks"]))
                d["toks"].append(t)
                d["seg"].append(s)

    def _match(self, d: dict, q: list[str], start: int) -> bool:
        toks, i, j = d["toks"], 0, start
        while i < len(q):
            if j >= len(toks):
                return False
            if toks[j] == q[i] or (i == len(q) - 1 and len(q[i]) >= 2 and toks[j].startswith(q[i])):
                i, j = i + 1, j + 1  # (a quote cut off mid-word at its end still matches)
            elif _skippable(toks[j]) and j > start:
                j += 1
            else:
                return False
        return True

    def _find(self, docs: list[dict], q: list[str], page) -> dict | None:
        hits = []
        for d in docs:
            for start in d["at"].get(q[0], []):
                if self._match(d, q, start):
                    hits.append(d["seg"][start])
        if not hits:
            return None
        return next((s for s in hits if str(s["label"]) == str(page)), hits[0])

    def locate(self, doc: str | None, page, quote: str) -> dict | None:
        """The page/sheet segment where the quote occurs, or None. Every word
        and number of the quote must occur in the source in the same order;
        only list numbering and page numbers may be skipped (so a changed
        number never matches). A quote joining sentences that the source
        separates by a heading or list item is accepted when each sentence
        occurs in the document; its page is that of the first sentence."""
        pieces = re.split(r"\.\.\.|…", quote or "")  # passages joined with an ellipsis
        quote = " ".join(pieces)
        q = _tokens(quote)
        if len(q) < 3:
            return None
        docs = [self.docs[doc]] if doc in self.docs else list(self.docs.values())
        found = self._find(docs, q, page)
        if found is not None:
            return found
        parts = [_tokens(p) for piece in pieces for p in _QUOTE_PART.split(piece)]
        parts = [p for p in parts if len(p) >= 3]
        if len(parts) < 2:
            return None
        hits = [self._find(docs, p, page) for p in parts]
        return None if any(h is None for h in hits) else hits[0]


def _numbers(text: str) -> set[str]:
    return {re.sub(r"[,]", "", n).rstrip(".:/") for n in _NUM.findall(text or "")}


def supported(statement: str, quote: str, *, summary: bool = False) -> bool:
    """Every number, e-mail address and URL in the statement occurs in the
    quote, its wording is supported by the quote, and it keeps the quote's
    negations, conditions, alternatives and modality (see _qualifiers_kept)."""
    qf = pdg.fold(quote)
    qnums = _numbers(quote) | {n for n in _numbers(qf)}
    if not _numbers(statement) <= qnums:
        return False
    for e in pdg.EMAIL.findall(statement or ""):
        if e.lower().rstrip(".") not in (quote or "").lower():
            return False
    for u in _URLISH.findall(statement or ""):
        if pdg.fold(u.rstrip(".,)")) not in qf:
            return False
    return _word_support(statement, quote) >= MIN_WORD_SUPPORT and _qualifiers_kept(statement, quote,
                                                                                    summary=summary)


# Words that change what a sentence commits to. A statement may rephrase its
# quote, but it may not drop or add a negation, a condition or exception, an
# alternative, or turn a permission into an obligation (or back): if it does,
# the quote itself is printed instead. Deliberately strict -- a false alarm
# only means the verbatim quote is shown.
_NEGATION = re.compile(r"\b(?:not|no|never|none|nor|neither|cannot|without|non)\b|n't\b", re.I)
_CONDITION = re.compile(r"\b(?:if|unless|only|provided|subject to|except|excepting|excluding|conditional\w*|"
                        r"in (?:the )?case|where applicable|as applicable|if applicable)\b", re.I)
# (a bare "or" is usually a list -- "inquiries or regrets" -- so only explicit
# choice markers count as an alternative)
_ALTERNATIVE = re.compile(r"\b(?:either|alternatively|alternative|optional\w*|option|and/or)\b", re.I)
_PERMISSION = re.compile(r"\b(?:may|can|could|optional\w*|option|permitted|allowed|either|alternatively|"
                         r"discretion|reserves?)\b", re.I)
_OBLIGATION = re.compile(r"\b(?:must|shall|required|requires?|mandatory|obligat\w*|need to|has to|have to|"
                         r"will be|is to|are to)\b", re.I)


def _qualifiers_kept(statement: str, quote: str, *, summary: bool = False) -> bool:
    """`summary`: the statement condenses several passages (the assignment),
    so it may leave qualifiers out, but it still may not add a negation or
    an option the passages do not state."""
    s, whole = statement or "", quote or ""
    if _PERMISSION.search(s) and not (_PERMISSION.search(whole) or _ALTERNATIVE.search(whole)
                                      or re.search(r"\bor\b", whole, re.I)):
        return False  # an obligation or plain statement presented as optional
    if _NEGATION.search(s) and not _NEGATION.search(whole):
        return False  # a negation the source does not state
    if summary:
        return True
    # What the statement may not DROP is judged on the quote sentences it
    # actually restates (most of whose words it carries): a quote often
    # holds a neighbouring sentence that is a separate fact.
    sentences = [x for x in re.split(r"(?<=[.;:!?])\s+", whole) if x.strip()]
    q = " ".join(x for x in sentences if _word_support(x, s) >= 0.5) or whole
    if _NEGATION.search(q) and not _NEGATION.search(s):
        return False  # a negation dropped
    if _CONDITION.search(q) and not _CONDITION.search(s):
        return False  # a condition or exception dropped
    if _ALTERNATIVE.search(q) and not (_ALTERNATIVE.search(s) or _PERMISSION.search(s)):
        return False  # alternatives presented as the only way
    if _PERMISSION.search(q) and not _PERMISSION.search(s) and _OBLIGATION.search(s):
        return False  # a permission presented as an obligation
    return True


# A statement may rephrase, but its substance must come from the quote: at
# least this share of its content words (stem-compared) must occur there. It
# stops a statement from carrying in a place, an option or an obligation
# from elsewhere ("... with the option to shift online").
MIN_WORD_SUPPORT = 0.75
_STOP = set("""a an the and or nor of to in on at by for from with without within into onto over under as is are
was were be been being will shall must may can could should would this that these those it its their there
which who whom whose any all each every such than then also only not no per via upon about between before after
during including include includes included other others same both either neither if when where while has have had
do does did bidder bidders""".split())


def _stems(text: str) -> list[str]:
    return [t[:5] for t in _TOKEN.findall(pdg.fold(text)) if not t.isdigit() and len(t) > 2 and t not in _STOP]


def _word_support(statement: str, quote: str) -> float:
    words = _stems(statement)
    if not words:
        return 1.0
    have = set(_stems(quote))
    return sum(w in have for w in words) / len(words)


_WEIGHT_LABEL_CATEGORIES = {"PROPOSAL_CONTENT", "DELIVERABLE", "SCOPE", "QUALIFICATION", "ELIGIBILITY"}


def _gate(category: str, statement: str, quote: str) -> bool:
    """Evidence the category's meaning requires of its quote."""
    words = [t for t in _tokens(quote) if not t.isdigit()]
    if category in ("OTHER", "BUYER_CONTEXT") and len(words) < 5:
        return False  # a bare label ("Request for Proposals No.") states no fact
    if category in _WEIGHT_LABEL_CATEGORIES and len(words) <= 4 and "%" in quote:
        return False  # "Financial Proposal 30%" is a published weight, not a content requirement
    if category == "SUBMISSION_METHOD":
        return bool(_CHANNEL.search(quote))
    if category == "BUDGET":
        return bool(re.search(r"\d", quote))
    if category == "GUARANTEE":
        return bool(_GUARANTEE.search(quote))
    return True


def verify(payload: dict | None, documents: list[tuple[str, str]], *, context: list[str] | None = None) -> dict:
    """The payload's facts checked against `documents` (pure, no model call):
    located quotes only, page corrected to where the quote is, statement
    replaced by the quote when it states anything the quote does not.
    `context`: the opportunity's verified identity (title, buyer, reference),
    which the assignment summary may name."""
    payload = payload or {}
    idx = _Index(documents)
    out, dropped, seen = [], 0, set()
    raw_assignments = []
    facts = list(payload.get("facts") or [])
    for f in list(facts):
        d = f.get("delivery") if str(f.get("category") or "").upper() == "ASSIGNMENT" else None
        if isinstance(d, dict) and d.get("quote"):
            facts.append({"category": "DELIVERY_LOCATION", "priority": 1, "doc": f.get("doc"), **d})
    for f in facts:
        if str(f.get("category") or "").upper() == "ASSIGNMENT":
            raw_assignments.append(f)
            continue
        cat = str(f.get("category") or "").upper()
        quote = pdg.norm(str(f.get("quote") or ""))
        stmt = pdg.norm(str(f.get("statement") or ""))
        if cat not in CATEGORIES:
            dropped += 1
            continue
        seg = idx.locate(f.get("doc"), f.get("page"), quote)
        if seg is None or not _gate(cat, stmt, quote):
            dropped += 1
            continue
        exact = bool(stmt) and supported(stmt, quote)
        try:
            priority = min(3, max(1, int(f.get("priority") or 2)))
        except (TypeError, ValueError):
            priority = 2
        item = {"category": cat, "text": stmt if exact else _shown_quote(quote), "quote": quote, "doc": seg["doc"],
                "page": seg["page"], "sheet": seg["sheet"], "verbatim": not exact, "fact": True,
                "priority": priority}
        key = (cat, pdg.fold(item["text"])[:160])
        if key in seen or _repeats(item, out):
            continue  # long packages restate the same fact in several places
        seen.add(key)
        out.append(item)
    # The assignment summary draws the package together, so its evidence is
    # its own quotes plus every verified fact's quote and the identity; each
    # number in it must still occur in its own quotes or a verified fact.
    evidence = " ".join([it["quote"] for it in out] + [c for c in context or [] if c])
    assignments = [a for a in (_assignment(idx, f, evidence) for f in raw_assignments) if a]
    # the fullest supported description of the assignment (long packages
    # restate the title many times; the scope section describes the work)
    best = max([a for a in assignments if not a["verbatim"]] or assignments,
               key=lambda a: min(len(a["text"]), 450), default=None)
    return {"assignment": best, "facts": out, "dropped": dropped,
            "coverage_gaps": list(payload.get("coverage_gaps") or [])}


def _shown_quote(quote: str) -> str:
    """A quote printed in place of an unsupported statement: every passage
    (passages the model joined with an ellipsis are separated by " … "), with
    a capital first letter -- nothing the quote states is dropped."""
    parts = [pdg.norm(p).strip(" ,;") for p in re.split(r"\.\.\.|…", quote)]
    text = " … ".join(p for p in parts if p) or quote
    return text[:1].upper() + text[1:]


def _repeats(item: dict, kept: list[dict]) -> bool:
    from difflib import SequenceMatcher
    a = pdg.fold(item["text"])
    for k in kept:
        if k["category"] == item["category"]:
            b = pdg.fold(k["text"])
            m = SequenceMatcher(None, a, b, autojunk=False)
            if m.real_quick_ratio() > 0.85 and m.quick_ratio() > 0.85 and m.ratio() > 0.85:
                return True
    return False


def _assignment(idx: "_Index", f: dict, evidence: str = "") -> dict | None:
    quotes = f.get("quotes")
    if not isinstance(quotes, list):
        quotes = [{"quote": f.get("quote"), "page": f.get("page")}]
    located = []
    for q in quotes[:3]:
        q = q if isinstance(q, dict) else {"quote": q}
        text = pdg.norm(str(q.get("quote") or ""))
        seg = idx.locate(f.get("doc"), q.get("page"), text)
        if seg is not None:
            located.append((text, seg))
    if not located:
        return None
    stmt = pdg.norm(str(f.get("statement") or ""))
    joined = " ".join(t for t, _ in located)
    exact = bool(stmt) and supported(stmt, joined + " " + evidence, summary=True)
    seg = located[0][1]
    return {"category": "ASSIGNMENT", "text": stmt if exact else located[0][0], "quote": joined,
            "doc": seg["doc"], "page": seg["page"], "sheet": seg["sheet"], "verbatim": not exact, "fact": True}


def by_category(verified: dict) -> dict[str, list[dict]]:
    """Facts per category, most essential first (document order within a
    priority), so a capped list shows what matters rather than what comes first."""
    d: dict[str, list[dict]] = {}
    for f in verified.get("facts") or []:
        d.setdefault(f["category"], []).append(f)
    return {k: sorted(v, key=lambda f: f.get("priority") or 2) for k, v in d.items()}


# ── extraction ─────────────────────────────────────────────────────────────

def extract(documents: list[tuple[str, str]], api_key: str | None = None, *, client=None,
            telemetry_context: dict | None = None) -> dict:
    """One model pass over the package. Returns the raw payload (facts as the
    model gave them, with the chunk's document) plus coverage gaps and usage
    telemetry; verify() is applied by the caller / at report time."""
    if client is None:
        from config import get_anthropic_client
        client = get_anthropic_client(api_key=api_key)
    parts = chunks(documents)
    t0 = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        results = list(pool.map(lambda c: _call(client, c, telemetry_context), parts))
    facts, gaps, telemetry = [], [], []
    for c, res in zip(parts, results):
        tel = res["telemetry"]
        telemetry.append(tel)
        for row in res["rows"]:
            row.setdefault("doc", c["doc"])
            facts.append(row)
        if tel.get("error") or tel.get("stop_reason") == "max_tokens":
            gaps.append({"filename": c["doc"], "route": "REPORT_FACTS", "pages": c["pages"],
                         "reason": "OUTPUT_LIMIT" if tel.get("stop_reason") == "max_tokens"
                         else ("CALL_FAILED" if str(tel.get("error", "")).startswith("CALL_FAILED")
                               else "UNREADABLE_RESPONSE")})
    return {"schema": SCHEMA, "model": FACTS_MODEL, "facts": facts, "coverage_gaps": gaps,
            "chunks": len(parts), "seconds": round(time.monotonic() - t0, 2), "telemetry": telemetry}


# ── Full Analysis specialist findings checked against the verified facts ──

def fact_index(verified: dict | None) -> dict[str, dict]:
    """FACT-n -> verified fact, numbered exactly as the Full Analysis canonical
    package numbers them (the assignment first, then the facts in order)."""
    if not isinstance(verified, dict):
        return {}
    items = ([verified["assignment"]] if verified.get("assignment") else []) + list(verified.get("facts") or [])
    return {f"FACT-{i}": f for i, f in enumerate(items, 1) if isinstance(f, dict) and f.get("text")}


# A finding that says something is missing, unstated or undefined.
_ABSENCE = re.compile(
    r"\b(?:not|never|no)\b[^.;:]{0,50}?\b(?:stated|specified|defined|provided|given|identified|disclosed|included|"
    r"mentioned|addressed|set out|documented|indicated)\b|\b(?:undefined|unspecified|unstated|missing|absent|"
    r"lacks?|lacking|omit\w*|silent)\b", re.I)
# Words that describe the claim of absence, or the analysis's own data, rather than its topic.
_ABSENCE_WORDS = set("""not never no stated specified defined undefined unspecified unstated provided given
identified disclosed included mentioned addressed documented indicated missing absent lack lacks lacking omitted
silent referenced unclear exact explicit explicitly field fields canonical object objects value values null
document documents procurement rfp tender bidder bidders lau buyer""".split())
# Internal vocabulary: a finding about the analysis's own data, not about the procurement.
_INTERNAL = re.compile(r"\bcanonical\b|\b(?:object|field)s?\b|\bnull\b", re.I)
# Canonical-id citations inside specialist prose ("FACT-18", "REQ-2", "CRIT-best-value").
_CANONICAL_REF = re.compile(r"\s*\(?\b(?:FACT|REQ|CRIT|SCOPE|OBL|MS|DOC|CAT|REL)-[A-Za-z0-9-]+\)?"
                            r"|\b(?:IDENT|SUBMISSION|PKG)\b")


def _without_refs(text: str) -> str:
    text = _CANONICAL_REF.sub("", text or "")
    text = re.sub(r"\b(?:and|or)\s+(?=[,.;]|and\b|together\b|establish|require|state|indicate|include|list|"
                  r"permit|mandate)", "", text)
    text = re.sub(r"^\s*(?:and\s+)?together\s+", "", text)
    text = pdg.norm(re.sub(r"\s+([,.;])", r"\1", text)).lstrip(",.; ")
    return _sentences_capitalised(text)


def _sentences_capitalised(text: str) -> str:
    return re.sub(r"(^|[.!?]\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), text)


# Consequences a specialist may not add to what its cited facts state.
_CONSEQUENCE = re.compile(r"\b(?:disqualif\w*|reject\w*|exclu\w*|invalid\w*|terminat\w*|penalt\w*|forfeit\w*|"
                          r"dismiss\w*|ineligib\w*|void)\b", re.I)


# Words that make a claim absolute. A finding may use one only if its cited
# facts do ("unlimited", "automatic", "strictly", "alone" ...).
_ABSOLUTE = re.compile(r"\b(?:automatic\w*|unlimited|limitless|unconditional\w*|strict\w*|always|never|alone|"
                       r"solely|sole|exclusive\w*|absolute\w*|invariabl\w*|guaranteed|certain(?:ly)?|"
                       r"no exceptions?|without exception|in all cases|hard|only)\b", re.I)
# A requirement or precondition, and one the source only makes possible
# ("may require", "may be asked to").
_OBLIGATION = re.compile(r"\b(?:must|shall|mandatory|compulsory|required?|requires|obligat\w*|contingent|"
                         r"conditional|prerequisite\w*)\b", re.I)
_HEDGED_OBLIGATION = re.compile(r"\b(?:may|might|could|can)\s+(?:also\s+)?(?:be\s+)?"
                                r"(?:requir\w*|request\w*|ask\w*|demand\w*|call\w* for)\b", re.I)
_FIRM_OBLIGATION = re.compile(r"\b(?:must|shall|mandatory|compulsory|is required|are required|requires|"
                              r"contingent|conditional|subject to|only (?:if|upon|after|against))\b", re.I)
_HEDGE = re.compile(r"\b(?:may|might|could|can|possibl\w*|potential\w*|reserves?|discretion\w*|risk\w*|likely)\b",
                    re.I)
_APPROX = re.compile(r"\b(?:about|approximately|approx|around|roughly|some|nearly|almost|up to|no more than|"
                     r"at most|not exceeding|maximum of)\b", re.I)
_APPROX_NUMBER = re.compile(r"\b(?:about|approximately|approx\.?|around|roughly|some|nearly|almost|up to)\s+"
                            r"(\d+(?:[.,]\d+)?)", re.I)


def _sentences(text: str) -> list[str]:
    return [x for x in re.split(r"(?<=[.!?;])\s+", text or "") if x.strip()]


def overstates(claim: str, evidence: str) -> str | None:
    """Why `claim` (one sentence of a specialist finding, or its title) says
    more than its cited `evidence`, or None. It may not:
    - add a consequence (disqualification, rejection, penalty ...) the facts do not state;
    - state firmly a consequence the facts only make possible ("may result in");
    - drop the approximation from a figure ("about 20 minutes" -> "20 minutes");
    - state as a requirement or precondition what the facts only make possible ("may require");
    - add an absolute ("unlimited", "automatic", "strictly", "alone", "only") the facts do not use;
    - add a negation the facts do not contain."""
    ev = evidence or ""
    ev_sentences = _sentences(ev)
    for m in _CONSEQUENCE.finditer(claim):
        stem = m.group(0).lower()[:6]
        holding = [s for s in ev_sentences if any(x.group(0).lower()[:6] == stem for x in _CONSEQUENCE.finditer(s))]
        if not holding:
            return "a consequence the facts do not state"
        if all(_HEDGE.search(s) for s in holding) and not _HEDGE.search(claim):
            return "a possible consequence stated as certain"
    if (_OBLIGATION.search(claim) and not _HEDGE.search(claim) and _HEDGED_OBLIGATION.search(ev)
            and not _FIRM_OBLIGATION.search(_HEDGED_OBLIGATION.sub(" ", ev))):
        return "a possibility stated as a requirement"
    approx = {m.group(1) for m in _APPROX_NUMBER.finditer(ev)}
    if approx & _numbers(claim) and not _APPROX.search(claim):
        return "an approximate figure stated as exact"
    for m in _ABSOLUTE.finditer(claim):
        if not re.search(r"\b" + re.escape(m.group(0).lower()[:5]), ev, re.I):
            return "an absolute the facts do not state"
    if _NEGATION.search(claim) and not _NEGATION.search(ev):
        return "a negation the facts do not state"
    return None


#: A detail sentence is printed only if at least this share of its words
#: come from the cited facts: the explanation stays tied to the evidence, and
#: speculation or advice phrased as a requirement ("Bidders must ...") that
#: the facts do not state is left out (the title carries the point).
MIN_DETAIL_SUPPORT = 0.5


def _without_overstatements(detail: str, evidence: str) -> str:
    """The detail without any sentence that says more than the cited facts."""
    return " ".join(s for s in _sentences(detail)
                    if overstates(s, evidence) is None and _word_support(s, evidence) >= MIN_DETAIL_SUPPORT).strip()


_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_MONTHS = ("January February March April May June July August September October November December").split()


def _topic_stems(title: str) -> list[str]:
    out = []
    for t in _tokens(title):
        if t.isdigit() or len(t) <= 2 or t in _STOP or t in _ABSENCE_WORDS:
            continue
        s = t[:5]
        if s not in out:
            out.append(s)
    return out


def contradicted(finding: dict, index: dict[str, dict]) -> dict | None:
    """The verified fact that already states what `finding` says is missing,
    or None. Only claims of absence are tested: a verified fact covering at
    least two thirds (and at least two) of the claim's topic words states the
    matter, so the claim contradicts the documents."""
    title = str(finding.get("title") or "")
    if finding.get("finding_type") not in ("GAP", "AMBIGUITY") and not _ABSENCE.search(title):
        return None
    topic = _topic_stems(title)
    if len(topic) < 2:
        return None
    need = max(2, -(-2 * len(topic) // 3))
    for f in index.values():
        have = set(_stems(f"{f.get('text', '')} {str(f.get('category') or '').replace('_', ' ')}"))
        if sum(t in have for t in topic) >= need:
            return f
    return None


def _iso_to_text(text: str) -> str:
    return _ISO_DATE.sub(lambda m: f"{int(m.group(3))} {_MONTHS[int(m.group(2)) - 1]} {m.group(1)}"
                         if 1 <= int(m.group(2)) <= 12 else m.group(0), text or "")


SPECIALIST_SHOWN_TYPES = ("RISK", "AMBIGUITY", "INTERPRETATION", "ATTENTION_ITEM", "GAP")


def specialist_findings(findings: list[dict] | None, index: dict[str, dict]) -> dict:
    """The Full Analysis findings a report may print, each grounded in the
    verified facts it cites: {"shown": [...], "withheld": {reason: n}}.

    Kept: risks, ambiguities, interpretations, attention items and gaps that
    cite at least one verified fact (a gap needs none -- it states an
    absence), whose figures and dates all occur in the facts they cite, that
    do not merely restate one fact, and that no verified fact contradicts.
    Each shown finding carries "refs": the cited facts (for page references)."""
    shown, withheld = [], {}

    def drop(reason):
        withheld[reason] = withheld.get(reason, 0) + 1

    sev = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    for f in sorted((f for f in findings or [] if isinstance(f, dict)),
                    key=lambda f: sev.get(str(f.get("severity")), 1)):
        ftype = str(f.get("finding_type") or "").upper()
        title, detail = _without_refs(str(f.get("title") or "")), _without_refs(str(f.get("detail") or ""))
        if ftype not in SPECIALIST_SHOWN_TYPES or not title:
            continue
        if _INTERNAL.search(f"{title} {detail}"):
            drop("about the analysis data rather than the documents")
            continue
        refs = [index[i] for i in f.get("canonical_ids") or [] if i in index]
        if ftype != "GAP" and not refs:
            drop("not grounded in a verified fact")
            continue
        if contradicted(f, index) is not None:
            drop("contradicted by a verified fact")
            continue
        evidence = " ".join(r.get("text", "") + " " + r.get("quote", "") for r in refs)
        if refs:
            if overstates(title, evidence):
                drop("stating more than the cited facts")
                continue
            detail = _without_overstatements(detail, evidence)
        claim = _iso_to_text(f"{title} {detail}")
        if refs and not _numbers(claim) <= (_numbers(evidence) | _numbers(pdg.fold(evidence))):
            drop("with a figure or date not in the cited facts")
            continue
        if ftype == "ATTENTION_ITEM" and refs and _word_support(title, evidence) >= 0.8:
            drop("restating a verified fact")
            continue
        stems = set(_topic_stems(title))
        if any(len(stems & s["_stems"]) >= max(2, (min(len(stems), len(s["_stems"])) + 1) // 2) for s in shown):
            drop("repeating another finding")
            continue
        shown.append({"type": ftype, "severity": f.get("severity"), "title": title,
                      "detail": _iso_to_text(detail), "refs": refs, "_stems": stems,
                      "produced_by": list(f.get("produced_by") or [])})
    for s in shown:
        s.pop("_stems", None)
    return {"shown": shown, "withheld": withheld}
