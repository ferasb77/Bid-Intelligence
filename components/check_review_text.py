"""
components/check_review_text.py -- CHECK-2D.1: the ONE client-safe projection
of a persisted CHECK review / ambiguity reason.

PURE: only `re`. No Streamlit, no database, no PDF library, no provider, no
import of check_coverage.py / check_run_service.py.

    persisted adjudication.ambiguity_or_review_reason   (RAW DURABLE VALUE)
            |
    client_safe_review_notes()   <- this module (presentation only)
            |
    CHECK-2C workspace (components/check_workspace_view.review_notes)
    CHECK-2D report    (components/check_report_model, via the same call)

The persisted value is never modified: every function here takes a value and
returns a new list. `raw_review_notes()` keeps the verbatim segments for
audit / debug.

Two kinds of internal CHECK metadata are normalized, nothing else:

1. The CHECK-2B.1 replay-commissioning placeholder
   ("recorded live adjudication (reason text omitted from content-free
   fixture)"). It records how a run was commissioned, not why a finding has
   its status, so it is dropped. It is never replaced with invented
   narrative: if a HUMAN_REVIEW_REQUIRED finding is left with no reason at
   all, a fixed neutral sentence (NEUTRAL_REVIEW_REASON) says exactly that.

2. Internal status-routing notation (e.g. "... -> HUMAN_REVIEW_REQUIRED")
   written by check_coverage's fail-closed validation. Only an arrow followed
   by a KNOWN CHECK status token (ROUTING_TOKENS) is routing notation; any
   other arrow is left untouched. The known validation templates are restated
   in plain language that says only what the rule itself says; any other
   routed segment keeps its substantive text with the status tokens spelled
   out in words.

Everything else -- buyer wording ("element needs review: <buyer text>"),
scope bases, weight notes, "[REQ-x]" linkage prefixes -- passes through
verbatim.
"""
from __future__ import annotations

import re

HUMAN_REVIEW = "HUMAN_REVIEW_REQUIRED"

#: The exact commissioning placeholder the CHECK-2A replay adjudicator
#: (scripts/commission_check2a_calgary.py replay_adjudicator) wrote as the
#: model "reason" of every replayed object.
COMMISSIONING_PLACEHOLDER = "recorded live adjudication (reason text omitted from content-free fixture)"
#: Distinctive marker, used as a belt-and-braces guard.
COMMISSIONING_PLACEHOLDER_MARKER = "reason text omitted from content-free fixture"

#: Shown only when a HUMAN_REVIEW_REQUIRED finding has no reason left after
#: the placeholder is removed. Says what is true; implies no deficiency.
NEUTRAL_REVIEW_REASON = ("Human review is required for this item; no additional narrative reason was "
                         "preserved in the source adjudication.")

#: Internal CHECK status / routing tokens -> plain language (longest first so
#: HUMAN_REVIEW_REQUIRED is matched before HUMAN_REVIEW).
ROUTING_TOKENS = {
    "HUMAN_REVIEW_REQUIRED": "human review required",
    "NOT_VERIFIABLE_FROM_FILES": "not verifiable from the submitted files",
    "PARTIALLY_ADDRESSED": "partially addressed",
    "NOT_ADDRESSED": "not addressed",
    "NOT_APPLICABLE": "not applicable",
    "HUMAN_REVIEW": "human review required",
    "ADDRESSED": "addressed",
}
#: Status / element-coverage tokens spelled out when they remain inside the
#: substantive text of a ROUTED segment (never applied to any other segment).
INLINE_TOKENS = dict(ROUTING_TOKENS, NOT_VERIFIABLE="not verifiable")
_TOKEN_ALT = "|".join(sorted(ROUTING_TOKENS, key=len, reverse=True))
_INLINE_ALT = "|".join(sorted(INLINE_TOKENS, key=len, reverse=True))
_TOKEN_RE = re.compile(rf"(?<![A-Za-z0-9_])({_INLINE_ALT})(?![A-Za-z0-9_])")
#: An arrow is routing notation ONLY when a known status token follows it.
_ROUTE_RE = re.compile(rf"\s*->\s*({_TOKEN_ALT})(?![A-Za-z0-9_])")
_PREFIX_RE = re.compile(r"^(\[[A-Za-z0-9._:-]+\])\s*")

_CONFIRM = "a person should confirm it"
#: A segment carrying verbatim buyer wording (check_coverage's
#: "element needs review: <buyer element>") -- passed through untouched.
BUYER_ELEMENT_PREFIX = "element needs review:"

#: check_coverage's validation-downgrade templates, restated. Each rewrite
#: says only what the deterministic rule says (no new facts); captured
#: groups carry the persisted substantive text through unchanged.
_TEMPLATES = (
    (re.compile(r"^NOT_ADDRESSED -> HUMAN_REVIEW_REQUIRED:\s*(.+)$", re.S),
     lambda m: _sentence(m.group(1))),
    (re.compile(r"^element (?:ADDRESSED|PARTIAL) without valid evidence -> HUMAN_REVIEW(?:_REQUIRED)?\b.*$", re.S),
     lambda m: "The evidence cited for an element could not be validated, so that element needs human review."),
    (re.compile(r"^ADDRESSED without valid bidder evidence -> HUMAN_REVIEW_REQUIRED$"),
     lambda m: f"No valid bidder evidence could be confirmed for this item, so {_CONFIRM}."),
    (re.compile(r"^ADDRESSED but an element is absent/partial -> PARTIALLY_ADDRESSED$"),
     lambda m: "At least one requested element is absent or only partly demonstrated."),
    (re.compile(r"^ADDRESSED but an element lost its evidence -> HUMAN_REVIEW_REQUIRED$"),
     lambda m: f"The evidence cited for an element could not be validated, so {_CONFIRM}."),
    (re.compile(r"^PARTIALLY_ADDRESSED -> ADDRESSED:\s*(.+)$", re.S),
     lambda m: "Treated as addressed: " + m.group(1).strip()),
    (re.compile(r"^PARTIALLY_ADDRESSED without valid bidder evidence -> HUMAN_REVIEW_REQUIRED$"),
     lambda m: f"No valid bidder evidence could be confirmed for this item, so {_CONFIRM}."),
    (re.compile(r"^PARTIALLY_ADDRESSED without an identified absent/partial buyer element -> HUMAN_REVIEW_REQUIRED$"),
     lambda m: f"No specific absent or partly demonstrated buyer element was identified, so {_CONFIRM}."),
    (re.compile(r"^NOT_ADDRESSED on a non-response scope -> NOT_VERIFIABLE_FROM_FILES$"),
     lambda m: "This is not a response item, so it cannot be verified from the submitted files."),
    (re.compile(r"^NOT_ADDRESSED where CHECK-1 artifact status is \S+ -> NOT_VERIFIABLE_FROM_FILES$"),
     lambda m: "The expected document cannot be confirmed from the uploaded files, so this cannot be verified "
               "from them."),
    (re.compile(r"^NOT_ADDRESSED while citing supporting evidence -> HUMAN_REVIEW_REQUIRED$"),
     lambda m: f"A not-addressed conclusion conflicted with cited supporting evidence, so {_CONFIRM}."),
    (re.compile(r"^NOT_ADDRESSED contradicted by package artifacts \((.*)\) -> HUMAN_REVIEW_REQUIRED$", re.S),
     lambda m: f"A not-addressed conclusion is contradicted by documents in the package ({m.group(1)}), "
               f"so {_CONFIRM}."),
    (re.compile(r"^unknown status .* -> HUMAN_REVIEW_REQUIRED$", re.S),
     lambda m: f"The adjudication result could not be interpreted, so {_CONFIRM}."),
)


def _sentence(text: str) -> str:
    body = str(text or "").strip()
    return body[:1].upper() + body[1:] if body else body


def raw_review_notes(reason) -> list:
    """The persisted reason split into its recorded segments, VERBATIM (audit
    / debug view -- nothing dropped or rephrased)."""
    return [s.strip() for s in str(reason or "").split(" | ") if s.strip()]


def is_commissioning_placeholder(segment) -> bool:
    body = _PREFIX_RE.sub("", str(segment or "").strip())
    return COMMISSIONING_PLACEHOLDER_MARKER in body


def has_routing_notation(text) -> bool:
    return bool(_ROUTE_RE.search(str(text or "")))


def _strip_placeholder(body: str) -> str:
    out = body.replace(COMMISSIONING_PLACEHOLDER, "")
    if COMMISSIONING_PLACEHOLDER_MARKER in out:          # any other wrapping of the marker
        out = re.sub(r"[^|]*" + re.escape(COMMISSIONING_PLACEHOLDER_MARKER) + r"[^|]*", "", out)
    return out.strip(" ;,.-")


def normalize_routing(body: str) -> str:
    """One segment's internal routing notation -> plain language. Text with no
    arrow-plus-known-status-token is returned unchanged."""
    if not has_routing_notation(body):
        return body
    for rx, rewrite in _TEMPLATES:
        m = rx.match(body)
        if m:
            return _spell_tokens(rewrite(m))
    # Generic: keep the substantive text; spell out the status tokens.
    m = _ROUTE_RE.search(body)
    before, target, after = body[:m.start()], m.group(1), body[m.end():]
    label = ROUTING_TOKENS[target]
    after = after.lstrip(" :").strip()
    after = normalize_routing(after) if after else after
    before = _sentence(_spell_tokens(before).strip())
    head = f"{before} ({label})" if before else _sentence(label)
    return f"{head}: {_spell_tokens(after)}" if after else head


def _spell_tokens(text: str) -> str:
    return _TOKEN_RE.sub(lambda t: INLINE_TOKENS[t.group(1)], text)


def client_safe_segment(segment) -> str | None:
    """One recorded segment -> its client-safe form, or None when nothing
    client-meaningful remains. A '[REQ-x]' linkage prefix is preserved."""
    seg = str(segment or "").strip()
    m = _PREFIX_RE.match(seg)
    prefix, body = (m.group(1), seg[m.end():]) if m else ("", seg)
    if COMMISSIONING_PLACEHOLDER_MARKER in body:
        body = _strip_placeholder(body)
    if not body:
        return None
    if body.lower().startswith(BUYER_ELEMENT_PREFIX):
        return f"{prefix} {body}" if prefix else body   # verbatim buyer wording: never normalized
    body = normalize_routing(body)
    if not body:
        return None
    return f"{prefix} {body}" if prefix else body


def client_safe_review_notes(reason, status: str | None = None) -> list:
    """The customer-facing projection of a persisted review reason: the
    recorded segments, with the commissioning placeholder removed and internal
    routing notation normalized; de-duplicated, order preserved. A
    HUMAN_REVIEW_REQUIRED finding left with no reason gets NEUTRAL_REVIEW_REASON
    (never an invented deficiency). The input is never modified."""
    out: list = []
    for seg in raw_review_notes(reason):
        safe = client_safe_segment(seg)
        if safe and safe not in out:
            out.append(safe)
    if not out and status == HUMAN_REVIEW:
        out = [NEUTRAL_REVIEW_REASON]
    return out


def client_safe_reason(reason, status: str | None = None) -> str | None:
    """client_safe_review_notes joined back with the persisted separator."""
    notes = client_safe_review_notes(reason, status)
    return " | ".join(notes) if notes else None
