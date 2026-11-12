"""Buyer Intelligence for the FULL Bid Opportunity Assessment.

One bounded, time-limited Claude call with the server-side web search tool.
Results are kept strictly separate from the RFP requirements and are only
kept when their URL is one the search actually returned (no invented
sources). The call never blocks the FULL analysis: it runs in a background
thread -- started alongside a new FULL run, or when a FULL result without
research is opened (`ensure`) -- and the report states the actual research
state: not yet run, in progress, completed with / without findings, failed,
or skipped. Completed research for the same buyer and opportunity is reused
across FULL runs of the same bid instead of paying for a new search.

Persisted as JSON in Storage at {bid_id}/buyer_research/{full_run_id}.json --
no schema change.
"""
from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime, timezone

MODEL = "claude-opus-5-5"
MAX_SEARCHES = 5
TIMEOUT_SECONDS = 150
STALE_AFTER_SECONDS = 200  # > TIMEOUT_SECONDS: a RUNNING marker older than this was orphaned (e.g. restart)
TOPICS = {"programme": "Current programmes", "initiative": "Initiative named in the procurement",
          "subject": "Work in the opportunity's subject", "partners": "Partnerships & funding",
          "procurement": "Comparable projects or procurements", "profile": "Organisation profile",
          "news": "Recent news"}

SYSTEM = (
    "You compile public, verifiable background facts about a buyer organisation for a bid team. "
    "Report only facts explicitly stated in sources returned by your web searches. Never infer or "
    "speculate about the buyer's preferences, intentions, budget, evaluation behaviour or likely "
    "decision. Never give advice, recommendations or opinions. Prefer official and credible sources "
    "(the organisation's own website, funders, government or registry pages, reputable news) and "
    "recent material.")


def _path(bid_id: int, run_id: int) -> str:
    return f"{int(bid_id)}/buyer_research/{int(run_id)}.json"


def _prompt(client: str, title: str, reference: str | None, today: str, context: str = "") -> str:
    ref = f" (reference {reference})" if reference else ""
    ctx = f"Procurement context, quoted from the documents: \"{context}\"\n" if context else ""
    return (
        f"Today is {today}. Buyer organisation: {client}. Opportunity: {title}{ref}.\n{ctx}"
        "Search the web and find up to 6 verifiable facts about this buyer, in this priority: "
        "(initiative) the programme or initiative named in the procurement context, if any; "
        "(programme) the buyer's current programmes; (subject) its work in the opportunity's subject area; "
        "(partners) documented partnerships and funding for that work; (procurement) comparable projects "
        "or procurements it has run; (profile) its mandate, only if little else is found.\n"
        "If you cannot confirm that a source is about this specific organisation, leave it out.\n"
        "Do not restate what the procurement context already says. Each fact must be distinct.\n"
        "For every fact copy one sentence VERBATIM from the source page that supports it (\"evidence\"); facts "
        "without such a sentence must be left out. If a fact concerns a past period (for example a programme "
        "launched, or funding granted, in an earlier year), say so with its year and give that period in "
        "\"as_of\"; never present an older funding or partnership arrangement as applying to a current "
        "programme or to this opportunity. Never infer preferences, intentions, budgets or likely decisions.\n"
        "Finish with ONLY a JSON array inside <items></items>, each element: "
        '{"topic": "initiative|programme|subject|partners|procurement|profile", '
        '"statement": "one factual sentence", "evidence": "verbatim sentence from the source", '
        '"as_of": "the year or period the fact refers to, or null", '
        '"url": "the exact source URL", "published": "YYYY-MM-DD, YYYY-MM, YYYY or null"}.')


def _collect(blocks: list[dict]) -> tuple[dict[str, dict], str]:
    """Search-result URLs actually returned (url -> {title, page_age}) and the text."""
    urls, text = {}, []
    for b in blocks or []:
        t = b.get("type")
        if t == "web_search_tool_result" and isinstance(b.get("content"), list):
            for r in b["content"]:
                if isinstance(r, dict) and r.get("url"):
                    urls[r["url"]] = {"title": r.get("title"), "page_age": r.get("page_age")}
        elif t == "text":
            text.append(b.get("text") or "")
            for c in b.get("citations") or []:
                if isinstance(c, dict) and c.get("url"):
                    urls.setdefault(c["url"], {"title": c.get("title"), "page_age": None})
    return urls, "\n".join(text)


def _norm_url(u: str) -> str:
    return (u or "").strip().rstrip("/").split("#")[0].lower()


def _date(published, page_age) -> str | None:
    for v in (published, page_age):
        if isinstance(v, str):
            m = re.search(r"([A-Z][a-z]+ \d{1,2}, (19|20)\d{2})", v)
            if m:
                try:
                    return datetime.strptime(m.group(1), "%B %d, %Y").date().isoformat()
                except ValueError:
                    pass
            m = re.search(r"\b(19|20)\d{2}(-\d{2}(-\d{2})?)?\b", v)
            if m:
                return m.group(0)
    return None


def parse_items(text: str, urls: dict[str, dict]) -> list[dict]:
    """Keep only well-formed items whose URL was really returned by the search."""
    m = re.search(r"<items>(.*?)</items>", text or "", re.S)
    if not m:
        return []
    try:
        raw = json.loads(m.group(1).strip())
    except Exception:
        return []
    known = {_norm_url(u): (u, meta) for u, meta in urls.items()}
    items = []
    for it in raw if isinstance(raw, list) else []:
        if not isinstance(it, dict):
            continue
        hit = known.get(_norm_url(it.get("url") or ""))
        stmt = re.sub(r"\s+", " ", str(it.get("statement") or "")).strip()
        if not hit or not stmt or len(stmt) > 400:
            continue
        url, meta = hit
        ev = re.sub(r"\s+", " ", str(it.get("evidence") or "")).strip()
        as_of = re.sub(r"\s+", " ", str(it.get("as_of") or "")).strip()
        items.append({
            "topic": it.get("topic") if it.get("topic") in TOPICS else "profile",
            "statement": stmt,
            "evidence": ev[:600] or None,
            "as_of": as_of[:40] if as_of and as_of.lower() not in ("null", "none", "n/a") else None,
            "url": url,
            "source_title": (meta or {}).get("title"),
            "published": _date(it.get("published"), (meta or {}).get("page_age")),
        })
    return items[:6]


_FETCH_BYTES = 3_000_000


def page_text(url: str, timeout: float = 12.0) -> str | None:
    """Readable text of a public web page (for evidence verification), or
    None. Only http(s) to public addresses; never raises."""
    import html as _html
    import ipaddress
    import socket
    import urllib.request
    from urllib.parse import urlparse
    try:
        u = urlparse(url)
        if u.scheme not in ("http", "https") or not u.hostname:
            return None
        for info in socket.getaddrinfo(u.hostname, None):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                return None
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; BidIntelligence-research-check)"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read(_FETCH_BYTES)
            charset = r.headers.get_content_charset() or "utf-8"
        text = raw.decode(charset, errors="replace")
        text = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", text)
        text = re.sub(r"(?s)<[^>]+>", " ", text)
        return _html.unescape(text)
    except Exception:
        return None


def verify_items(items: list[dict], fetch=page_text) -> list[dict]:
    """Mark each item evidence_verified only when its quoted source sentence
    is actually present on the cited page (a valid URL alone is not evidence)."""
    import procurement_digest as pdg
    pages: dict[str, str | None] = {}
    for it in items:
        ev = pdg.fold(it.get("evidence") or "")
        if len(ev) < 25:
            it["evidence_verified"] = False
            continue
        if it["url"] not in pages:
            pages[it["url"]] = fetch(it["url"])
        page = pdg.fold(pages[it["url"]] or "")
        probes = [ev[:100], ev[len(ev) // 2 - 50: len(ev) // 2 + 50] if len(ev) > 140 else ev[-100:]]
        it["evidence_verified"] = bool(page) and all(p.strip() in page for p in probes if p.strip())
    return items


def run_research(client_name: str, title: str, reference: str | None, api_key: str | None,
                 *, anthropic_client=None, context: str = "", fetch=page_text) -> dict:
    """One bounded research call. Returns the persisted payload shape."""
    import config
    today = datetime.now(timezone.utc).date().isoformat()
    started = time.monotonic()
    client = anthropic_client or config.get_anthropic_client(api_key)
    messages = [{"role": "user", "content": _prompt(client_name, title, reference, today, context)}]
    blocks: list[dict] = []
    resp = None
    for _ in range(3):  # resume a paused server-tool turn at most twice
        remaining = TIMEOUT_SECONDS - (time.monotonic() - started)
        if remaining <= 5:
            break
        resp = client.with_options(timeout=remaining, max_retries=1).beta.messages.create(
            model=MODEL, max_tokens=6000, system=SYSTEM, messages=messages,
            tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": MAX_SEARCHES}],
            output_config={"effort": "low"},
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        )
        data = resp.model_dump() if hasattr(resp, "model_dump") else dict(resp)
        blocks.extend(data.get("content") or [])
        if data.get("stop_reason") != "pause_turn":
            break
        messages = messages + [{"role": "assistant", "content": data.get("content") or []}]
    urls, text = _collect(blocks)
    items = verify_items(parse_items(text, urls), fetch)
    usage = {}
    try:
        u = resp.usage.model_dump() if resp is not None else {}
        usage = {k: u.get(k) for k in ("input_tokens", "output_tokens")}
        usage["web_search_requests"] = ((u.get("server_tool_use") or {}).get("web_search_requests"))
    except Exception:
        pass
    return {"status": "COMPLETE", "items": items, "searched_urls": len(urls), "model": MODEL,
            "evidence_checked": True,
            "verified_count": sum(1 for i in items if i.get("evidence_verified")),
            "researched_at": datetime.now(timezone.utc).isoformat(), "usage": usage,
            "query": {"client": client_name, "title": title, "reference": reference, "context": context}}


# ── persistence + background launch ────────────────────────────────────────

def load(bid_id: int, run_id: int) -> dict | None:
    import database as db
    try:
        raw = db.download_file(_path(bid_id, run_id))
        if not raw:
            return None
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        return None
    if data.get("status") == "COMPLETE" and not data.get("evidence_checked"):
        return None  # pre-verification format: superseded by a verified search
    if data.get("status") == "RUNNING":
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(data.get("started_at"))).total_seconds()
        except Exception:
            age = STALE_AFTER_SECONDS + 1
        if age > STALE_AFTER_SECONDS:
            data["status"] = "FAILED"
            data["error"] = "timed out"
    return data


def _save(bid_id: int, run_id: int, payload: dict) -> None:
    import database as db
    db.upload_json_object(_path(bid_id, run_id), payload)


def research_subject(bid_id: int) -> dict:
    """Buyer/title/reference for the research query: the bid record (which
    FAST identity fills or the user corrects)."""
    import bid_identity
    import database as db
    bid = db.get_bid(bid_id) or {}
    client = (bid.get("client") or "").strip()
    title = (bid.get("title") or "").strip()
    if client in ("", bid_identity.PLACEHOLDER_CLIENT):
        client = ""
    if title == bid_identity.PLACEHOLDER_TITLE:
        title = ""
    return {"client": client, "title": title, "reference": (bid.get("file_number") or "").strip() or None}


def procurement_context(bid_id: int, run_id: int) -> str:
    """Short verbatim context for the search (the documents' own 'about' and
    overview sentences), so research targets the programme named in the
    procurement. Empty when it cannot be read; never raises."""
    try:
        import full_analysis_service
        import phoenix_report_service as prs
        import phoenix_reports as pr
        source = (full_analysis_service.get_full_analysis_status(bid_id, run_id) or {}).get("source_analysis_run_id")
        if not source:
            return ""
        f = prs.build_facts_for_run(bid_id, int(source))
        parts = [(pr.sentences_of(it["text"]) or [""])[0] for it in f.get("about") or []]
        parts += [s["text"] for s in (f.get("synopsis") or [])[:1]]
        return pr.clip(" ".join(p for p in parts if p), 600)
    except Exception:
        return ""


def _same_subject(a: dict, subj: dict) -> bool:
    q = (a or {}).get("query") or {}
    return ((q.get("client") or "").casefold() == (subj.get("client") or "").casefold()
            and (q.get("title") or "").casefold() == ((subj.get("title") or subj.get("client")) or "").casefold())


def reusable(bid_id: int, run_id: int) -> dict | None:
    """COMPLETE research from another FULL run of the same bid, for the same
    buyer and opportunity title (newest first). Read-only."""
    import database as db
    try:
        subj = research_subject(bid_id)
        runs = [r for r in db.list_analysis_runs(bid_id)
                if r.get("analysis_mode") == "FULL" and int(r["id"]) != int(run_id)]
    except Exception:
        return None
    for r in sorted(runs, key=lambda r: (str(r.get("created_at")), r["id"]), reverse=True):
        other = load(bid_id, int(r["id"]))
        if other and other.get("status") == "COMPLETE" and _same_subject(other, subj):
            return dict(other, reused_from_run=other.get("reused_from_run") or int(r["id"]))
    return None


def for_report(bid_id: int, run_id: int) -> dict | None:
    """What the assessment shows: this run's research, else reusable research."""
    own = load(bid_id, run_id)
    if own and own.get("status") in ("COMPLETE", "RUNNING"):
        return own
    return reusable(bid_id, run_id) or own


def ensure(bid_id: int, run_id: int, api_key: str | None) -> dict | None:
    """Make research available for a FULL run without blocking: existing
    state is returned as is (a FAILED attempt is not retried automatically);
    otherwise completed research of an earlier run of the same bid is reused;
    otherwise -- with an API key -- one background search is started."""
    existing = load(bid_id, run_id)
    if existing:
        return existing
    reused = reusable(bid_id, run_id)
    if reused:
        try:
            _save(bid_id, run_id, reused)
        except Exception:
            pass
        return reused
    if api_key:
        start_background(bid_id, run_id, api_key)
    return load(bid_id, run_id)


def start_background(bid_id: int, run_id: int, api_key: str | None) -> bool:
    """Start research for a FULL run in a daemon thread unless it already
    exists or is running. Never raises."""
    try:
        existing = load(bid_id, run_id)
        if existing and existing.get("status") in ("RUNNING", "COMPLETE"):
            return False
        subj = research_subject(bid_id)
        if not subj["client"]:
            _save(bid_id, run_id, {"status": "SKIPPED", "error": "buyer organisation not identified",
                                   "started_at": datetime.now(timezone.utc).isoformat()})
            return False
        started_at = datetime.now(timezone.utc).isoformat()
        _save(bid_id, run_id, {"status": "RUNNING", "started_at": started_at})
    except Exception:
        return False

    def _work():
        try:
            out = run_research(subj["client"], subj["title"] or subj["client"], subj["reference"], api_key,
                               context=procurement_context(bid_id, run_id))
        except Exception as exc:
            out = {"status": "FAILED", "error": type(exc).__name__, "items": [],
                   "query": {"client": subj["client"], "title": subj["title"] or subj["client"]}}
        out["started_at"] = started_at
        try:
            _save(bid_id, run_id, out)
        except Exception:
            pass

    threading.Thread(target=_work, name=f"buyer-research-{bid_id}-{run_id}", daemon=True).start()
    return True
