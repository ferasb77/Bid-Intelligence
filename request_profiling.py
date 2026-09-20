"""
request_profiling.py -- deterministic, zero-generation request-size profiler
(BI Token Optimization Program, Phase 5A: Offline Request Profiling &
Token Budgeting).

Measures the STRUCTURE of an Anthropic request (named-component character
and byte counts) before it is ever sent, using only Python's own str/bytes
measurement -- never a live model call. Every number in a `RequestProfile`
is one of:
  * an exact, deterministic character/byte count of text this process
    already holds in memory, or
  * `provider_counted_input_tokens`, populated ONLY from a real
    `client.messages.count_tokens(...)` response (never derived from
    chars/bytes -- see `try_count_tokens()`), or
  * `estimated_input_tokens`, a rough chars/4 heuristic that callers must
    always label ESTIMATE and never present as an exact token count (see
    `estimate_tokens_from_chars`).

No prompt/response/document TEXT is ever stored on a `RequestProfile` or
returned by any function here -- only sizes and, for duplicate-context
detection, one-way sha256 hashes of component text (see `hash_component`).
This module performs no I/O and makes no network calls of its own;
`try_count_tokens` is the only function that can reach the network, and
only when a caller explicitly passes it a real client.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from hashlib import sha256

# Claude Haiku 4.5's documented minimum cacheable prompt-prefix length, in
# provider tokens (Phase 5A instruction 12). Not derived from this app's
# own measurements -- a fixed constant from Anthropic's own documentation.
MIN_CACHEABLE_PREFIX_TOKENS = 4096

# A rough, explicitly-labeled heuristic ONLY -- never treated as an exact
# token count anywhere in this module or its callers (instruction 4).
CHARS_PER_TOKEN_ESTIMATE = 4

_COMPONENT_NAMES = (
    "system", "schema", "source_document", "procurement_context",
    "buyer_intelligence", "proposal_content", "organizational_context",
    "other_context",
)


def _measure(text: str | None) -> tuple[int, int]:
    """(chars, utf8_bytes) for one piece of text. None/"" -> (0, 0) --
    instruction 2: nullable/zero values, never force a workflow to carry
    a component it does not have."""
    if not text:
        return 0, 0
    return len(text), len(text.encode("utf-8"))


def hash_component(text: str | None) -> str | None:
    """One-way sha256 hex digest of a component's text, for duplicate-
    context detection (instruction 11). The text itself is never returned
    or retained by this function or any caller in this module."""
    if not text:
        return None
    return sha256(text.encode("utf-8")).hexdigest()


def estimate_tokens_from_chars(chars: int) -> int:
    """A rough ESTIMATE only (instruction 4/12). Callers MUST label any
    value derived from this 'ESTIMATE' wherever it is displayed or
    reported -- it is never a substitute for a provider-reported count."""
    return chars // CHARS_PER_TOKEN_ESTIMATE


@dataclass
class RequestProfile:
    """One offline, zero-generation measurement of a would-be Anthropic
    request's component sizes. Never carries prompt/response text."""
    workflow: str
    operation: str
    model: str | None = None

    system_chars: int = 0
    system_bytes: int = 0
    schema_chars: int = 0
    schema_bytes: int = 0
    source_document_chars: int = 0
    source_document_bytes: int = 0
    procurement_context_chars: int = 0
    procurement_context_bytes: int = 0
    buyer_intelligence_chars: int = 0
    buyer_intelligence_bytes: int = 0
    proposal_content_chars: int = 0
    proposal_content_bytes: int = 0
    organizational_context_chars: int = 0
    organizational_context_bytes: int = 0
    other_context_chars: int = 0
    other_context_bytes: int = 0

    messages_total_chars: int = 0
    request_total_bytes: int = 0
    tool_schema_bytes: int = 0
    max_tokens: int | None = None

    provider_counted_input_tokens: int | None = None  # ONLY from count_tokens
    estimated_input_tokens: int | None = None  # always an ESTIMATE, see above

    component_hashes: dict = field(default_factory=dict)  # name -> sha256 hex only
    notes: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def build_profile(*, workflow: str, operation: str, model: str | None = None,
                  system: str | None = None, schema: str | None = None,
                  source_document: str | None = None,
                  procurement_context: str | None = None,
                  buyer_intelligence: str | None = None,
                  proposal_content: str | None = None,
                  organizational_context: str | None = None,
                  other_context: str | None = None,
                  tool_schema_bytes: int = 0,
                  max_tokens: int | None = None,
                  provider_counted_input_tokens: int | None = None,
                  hash_components: bool = True,
                  notes: str = "") -> RequestProfile:
    """Builds one RequestProfile from named components. Every text
    parameter is optional (instruction 2) -- an absent component
    contributes 0/0 and gets no hash entry; do not force every workflow
    to supply every component. `system` is excluded from
    `messages_total_chars` because in every workflow in this codebase it
    is its own separate request field, never part of `messages`."""
    texts = {
        "system": system, "schema": schema, "source_document": source_document,
        "procurement_context": procurement_context, "buyer_intelligence": buyer_intelligence,
        "proposal_content": proposal_content, "organizational_context": organizational_context,
        "other_context": other_context,
    }
    sizes = {name: _measure(text) for name, text in texts.items()}
    messages_total_chars = sum(chars for name, (chars, _) in sizes.items() if name != "system")
    request_total_bytes = sum(b for _, b in sizes.values()) + tool_schema_bytes

    profile = RequestProfile(
        workflow=workflow, operation=operation, model=model,
        system_chars=sizes["system"][0], system_bytes=sizes["system"][1],
        schema_chars=sizes["schema"][0], schema_bytes=sizes["schema"][1],
        source_document_chars=sizes["source_document"][0],
        source_document_bytes=sizes["source_document"][1],
        procurement_context_chars=sizes["procurement_context"][0],
        procurement_context_bytes=sizes["procurement_context"][1],
        buyer_intelligence_chars=sizes["buyer_intelligence"][0],
        buyer_intelligence_bytes=sizes["buyer_intelligence"][1],
        proposal_content_chars=sizes["proposal_content"][0],
        proposal_content_bytes=sizes["proposal_content"][1],
        organizational_context_chars=sizes["organizational_context"][0],
        organizational_context_bytes=sizes["organizational_context"][1],
        other_context_chars=sizes["other_context"][0],
        other_context_bytes=sizes["other_context"][1],
        messages_total_chars=messages_total_chars,
        request_total_bytes=request_total_bytes,
        tool_schema_bytes=tool_schema_bytes,
        max_tokens=max_tokens,
        provider_counted_input_tokens=provider_counted_input_tokens,
        estimated_input_tokens=estimate_tokens_from_chars(request_total_bytes),
        notes=notes,
    )
    if hash_components:
        profile.component_hashes = {
            name: hash_component(text) for name, text in texts.items() if text
        }
    return profile


def try_count_tokens(client, *, model: str, system: str | None = None,
                     messages: list[dict] | None = None) -> tuple[int | None, str | None]:
    """Attempts EXACTLY ONE `client.messages.count_tokens(...)` call --
    never `messages.create`, never retried by this function. Returns
    `(input_tokens, None)` on success or `(None, error_type_name)` on
    failure. Callers must not loop/retry around this; call it once and
    branch on the result (instruction 4)."""
    kwargs = {"model": model, "messages": messages or [{"role": "user", "content": "x"}]}
    if system:
        kwargs["system"] = system
    try:
        response = client.messages.count_tokens(**kwargs)
        return getattr(response, "input_tokens", None), None
    except Exception as exc:
        return None, type(exc).__name__


def duplicate_context_map(profiles: list[RequestProfile]) -> dict:
    """Groups profiles by component hash to show which named components
    repeat byte-identically across calls (instruction 11) -- e.g. the
    same system prompt reused on every chunk of a document. Returns
    `{component_name: {sha256_hex: [ "workflow/operation", ... ]}}`,
    restricted to hashes shared by 2+ profiles. Never returns text."""
    by_component: dict[str, dict[str, list[str]]] = {}
    for profile in profiles:
        label = f"{profile.workflow}/{profile.operation}"
        for name, digest in profile.component_hashes.items():
            by_component.setdefault(name, {}).setdefault(digest, []).append(label)
    return {
        name: {digest: labels for digest, labels in hashes.items() if len(labels) > 1}
        for name, hashes in by_component.items()
        if any(len(labels) > 1 for labels in hashes.values())
    }


def cache_candidacy(*, prefix_chars: int, counted_tokens: int | None = None,
                    min_cacheable_tokens: int = MIN_CACHEABLE_PREFIX_TOKENS) -> str:
    """CACHE_CANDIDATE / NOT_CANDIDATE / UNKNOWN for one stable prefix,
    against the documented minimum cacheable-prefix token floor
    (instruction 12). Uses a real provider count when given. Without one,
    this only ever rules OUT candidacy (when even a generous chars/4
    estimate is well under the floor) -- it never rules candidacy IN from
    an estimate, since that would silently convert an ESTIMATE into an
    implied token count."""
    if counted_tokens is not None:
        return "CACHE_CANDIDATE" if counted_tokens >= min_cacheable_tokens else "NOT_CANDIDATE"
    estimate = estimate_tokens_from_chars(prefix_chars)
    if estimate < min_cacheable_tokens * 0.5:
        return "NOT_CANDIDATE"
    return "UNKNOWN"
