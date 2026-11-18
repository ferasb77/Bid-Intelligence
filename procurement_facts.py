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


def supported(statement: str, quote: str) -> bool:
    """Every number, e-mail address and URL in the statement occurs in the quote."""
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
    return _word_support(statement, quote) >= MIN_WORD_SUPPORT


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
    """A quote printed in place of an unsupported statement: its first passage
    (quotes joined with an ellipsis are shown one passage at a time), with a
    capital first letter."""
    first = pdg.norm(re.split(r"\.\.\.|…", quote)[0]).rstrip(" ,;") or quote
    return first[:1].upper() + first[1:]


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
    exact = bool(stmt) and supported(stmt, joined + " " + evidence)
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
