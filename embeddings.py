"""
Semantic embedding and retrieval for the Content Library.

Uses the Voyage AI API (voyage-3-lite) via the voyageai package.
The VOYAGE_API_KEY must be set in Streamlit secrets or .env.

All operations degrade gracefully — if no key or voyageai is unavailable,
functions return None / fallback results so the rest of the platform is
unaffected.

Supabase schema requirement:
    ALTER TABLE content_library ADD COLUMN IF NOT EXISTS
        embedding TEXT;   -- stored as JSON array string

We store embeddings as a JSON string rather than a native vector column
to avoid requiring pgvector on Supabase. Similarity is computed in Python.
"""

import json
import math
import os
from typing import Optional


# ── Embedding model ───────────────────────────────────────────────────────────
EMBEDDING_MODEL = "voyage-3-lite"   # 512 dims, fast, cheap
EMBEDDING_DIMS  = 512


def _get_voyage_key() -> Optional[str]:
    """Resolve Voyage AI API key from secrets / env / session state."""
    try:
        import streamlit as st
        key = st.secrets.get("VOYAGE_API_KEY")
        if key:
            return key
    except Exception:
        pass
    return os.getenv("VOYAGE_API_KEY")


def _get_voyage_client():
    """Return a voyageai.Client or None if unavailable."""
    key = _get_voyage_key()
    if not key:
        return None
    try:
        import voyageai
        return voyageai.Client(api_key=key)
    except ImportError:
        return None


# ── Generate one embedding ────────────────────────────────────────────────────
def _record_embed_usage(operation: str, status: str, item_count: int, input_chars: int,
                        latency_ms: int, result=None, error_category: str | None = None) -> None:
    """Phase 4 (BI Context & Token Optimization Program). Never raises --
    a telemetry failure must never affect embed_text/embed_query's existing
    degrade-gracefully-to-None contract. `total_tokens` is passed through
    ONLY when the installed voyageai SDK's response object actually
    exposed it on this call; never estimated from input_chars (instruction
    10)."""
    try:
        import model_telemetry
        total_tokens = getattr(result, "total_tokens", None) if result is not None else None
        model_telemetry.record_voyage_usage(
            workflow="content_library", operation=operation, status=status,
            item_count=item_count, input_chars=input_chars, latency_ms=latency_ms,
            total_tokens=total_tokens, error_category=error_category,
        )
    except Exception:
        pass


def embed_text(text: str) -> Optional[list[float]]:
    """
    Return an embedding vector for the given text.
    Returns None on any failure so callers can degrade gracefully.
    """
    if not text or not text.strip():
        return None
    client = _get_voyage_client()
    if not client:
        return None
    import time
    truncated = text[:4000]
    t0 = time.monotonic()
    try:
        result = client.embed(
            [truncated],
            model=EMBEDDING_MODEL,
            input_type="document",
        )
        latency_ms = round((time.monotonic() - t0) * 1000)
        _record_embed_usage("embed_document", "SUCCESS", 1, len(truncated), latency_ms, result=result)
        return result.embeddings[0]
    except Exception:
        latency_ms = round((time.monotonic() - t0) * 1000)
        _record_embed_usage("embed_document", "FAILURE", 1, len(truncated), latency_ms,
                            error_category="PROCESSING_ERROR")
        return None


def embed_query(text: str) -> Optional[list[float]]:
    """Embed a search query (uses query input_type for better retrieval)."""
    if not text or not text.strip():
        return None
    client = _get_voyage_client()
    if not client:
        return None
    import time
    truncated = text[:2000]
    t0 = time.monotonic()
    try:
        result = client.embed(
            [truncated],
            model=EMBEDDING_MODEL,
            input_type="query",
        )
        latency_ms = round((time.monotonic() - t0) * 1000)
        _record_embed_usage("embed_query", "SUCCESS", 1, len(truncated), latency_ms, result=result)
        return result.embeddings[0]
    except Exception:
        latency_ms = round((time.monotonic() - t0) * 1000)
        _record_embed_usage("embed_query", "FAILURE", 1, len(truncated), latency_ms,
                            error_category="PROCESSING_ERROR")
        return None


# ── Cosine similarity ─────────────────────────────────────────────────────────
def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot   = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


# ── Build query from section drafter inputs ───────────────────────────────────
def build_section_query(section_title: str, requirements: list[dict],
                        bid_context: dict) -> str:
    """
    Compose a rich query string from section title + requirements so the
    embedding captures the semantic intent of what needs to be drafted.
    """
    parts = [section_title]
    if bid_context.get("client"):
        parts.append(f"Client: {bid_context['client']}")
    for r in requirements[:5]:
        desc = (r.get("description") or "")[:120]
        if desc:
            parts.append(desc)
    return " | ".join(parts)


# ── Text to embed for a library item ─────────────────────────────────────────
def library_item_text(item: dict) -> str:
    """
    Compose the text to embed for a library item.
    Combines title, category, tags, and content for a rich representation.
    """
    parts = []
    if item.get("title"):
        parts.append(item["title"])
    if item.get("category"):
        parts.append(f"Category: {item['category']}")
    if item.get("tags"):
        parts.append(f"Tags: {item['tags']}")
    if item.get("content"):
        parts.append(item["content"][:2000])
    return " | ".join(parts)


# ── Semantic retrieval ────────────────────────────────────────────────────────
def semantic_search(
    query: str,
    library_items: list[dict],
    top_k: int = 5,
    min_score: float = 0.30,
) -> tuple[list[dict], bool]:
    """
    Return (results, used_semantic) where results are the top_k most
    relevant library items and used_semantic indicates whether embedding
    similarity was used (True) or keyword fallback (False).

    Graceful fallback: if no embeddings exist or Voyage key is missing,
    returns the first top_k items with used_semantic=False.
    """
    if not library_items:
        return [], False

    # Filter to items that have stored embeddings
    items_with_embeddings = [
        item for item in library_items
        if item.get("embedding")
    ]

    if not items_with_embeddings:
        return library_items[:top_k], False

    # Embed the query
    query_vec = embed_query(query)
    if not query_vec:
        return library_items[:top_k], False

    # Score all items with embeddings
    scored = []
    for item in items_with_embeddings:
        raw = item.get("embedding")
        if isinstance(raw, str):
            try:
                vec = json.loads(raw)
            except Exception:
                continue
        elif isinstance(raw, list):
            vec = raw
        else:
            continue

        score = cosine_similarity(query_vec, vec)
        scored.append({**item, "similarity_score": round(score, 3)})

    scored.sort(key=lambda x: x["similarity_score"], reverse=True)

    # Apply min_score filter but fall back if nothing passes
    filtered = [s for s in scored if s["similarity_score"] >= min_score]
    results = (filtered or scored)[:top_k]

    return results, True


# ── Embed and update a library item in the database ──────────────────────────
def embed_library_item(item: dict) -> Optional[str]:
    """
    Generate an embedding for a library item and return it as a JSON string
    suitable for storing in the database embedding column.
    Returns None if embedding fails.
    """
    text = library_item_text(item)
    vec  = embed_text(text)
    if vec is None:
        return None
    return json.dumps(vec)


# ── Check if Voyage key is configured ────────────────────────────────────────
def voyage_configured() -> bool:
    return _get_voyage_key() is not None
