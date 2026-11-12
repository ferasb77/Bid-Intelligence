"""Buyer Intelligence for the FULL Bid Opportunity Assessment.

One bounded, time-limited Claude call with the server-side web search tool.
Results are kept strictly separate from the RFP requirements and are only
kept when their URL is one the search actually returned (no invented
sources). The call never blocks the FULL analysis: it runs in a background
thread started alongside a FULL run and the report renders with whatever is
available ("not available" when research is still running or failed).

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
STALE_AFTER_SECONDS = 600
TOPICS = {"profile": "Organisation profile", "programme": "Related programmes",
          "partners": "Partners & funders", "news": "Recent news"}

SYSTEM = (
    "You compile public, verifiable background facts about a buyer organisation for a bid team. "
    "Report only facts explicitly stated in sources returned by your web searches. Never infer or "
    "speculate about the buyer's preferences, intentions, budget, evaluation behaviour or likely "
    "decision. Never give advice, recommendations or opinions. Prefer official and credible sources "
    "(the organisation's own website, funders, government or registry pages, reputable news) and "
    "recent material.")


def _path(bid_id: int, run_id: int) -> str:
    return f"{int(bid_id)}/buyer_research/{int(run_id)}.json"


def _prompt(client: str, title: str, reference: str | None, today: str) -> str:
    ref = f" (reference {reference})" if reference else ""
    return (
        f"Today is {today}. Buyer organisation: {client}. Opportunity: {title}{ref}.\n"
        "Search the web and find up to 6 factual items about this buyer covering: "
        "(profile) its mandate and profile; (programme) recent programmes or projects related to the "
        "opportunity's subject; (partners) partners or funders publicly linked to that work; "
        "(news) news from the last 24 months.\n"
        "If you cannot confirm that a source is about this specific organisation, leave it out.\n"
        "Finish with ONLY a JSON array inside <items></items>, each element: "
        '{"topic": "profile|programme|partners|news", "statement": "one factual sentence", '
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
        items.append({
            "topic": it.get("topic") if it.get("topic") in TOPICS else "profile",
            "statement": stmt,
            "url": url,
            "source_title": (meta or {}).get("title"),
            "published": _date(it.get("published"), (meta or {}).get("page_age")),
        })
    return items[:6]


def run_research(client_name: str, title: str, reference: str | None, api_key: str | None,
                 *, anthropic_client=None) -> dict:
    """One bounded research call. Returns the persisted payload shape."""
    import config
    today = datetime.now(timezone.utc).date().isoformat()
    started = time.monotonic()
    client = anthropic_client or config.get_anthropic_client(api_key)
    messages = [{"role": "user", "content": _prompt(client_name, title, reference, today)}]
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
    items = parse_items(text, urls)
    usage = {}
    try:
        u = resp.usage.model_dump() if resp is not None else {}
        usage = {k: u.get(k) for k in ("input_tokens", "output_tokens")}
        usage["web_search_requests"] = ((u.get("server_tool_use") or {}).get("web_search_requests"))
    except Exception:
        pass
    return {"status": "COMPLETE", "items": items, "searched_urls": len(urls), "model": MODEL,
            "researched_at": datetime.now(timezone.utc).isoformat(), "usage": usage,
            "query": {"client": client_name, "title": title, "reference": reference}}


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
            out = run_research(subj["client"], subj["title"] or subj["client"], subj["reference"], api_key)
        except Exception as exc:
            out = {"status": "FAILED", "error": type(exc).__name__, "items": []}
        out["started_at"] = started_at
        try:
            _save(bid_id, run_id, out)
        except Exception:
            pass

    threading.Thread(target=_work, name=f"buyer-research-{bid_id}-{run_id}", daemon=True).start()
    return True
