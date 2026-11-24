"""Model providers behind one interface: `call_json(system, user, schema)`.

* AnthropicAnalyst -- Claude (primary analyst, adjudicator, reviewer).
* OpenAIAnalyst    -- the independent analyst. Refuses client documents unless
  the owner's separate authorization is configured (constraint C3).
* ScriptedAnalyst  -- deterministic stand-in for tests. Its output is always
  labelled SYNTHETIC and can never make a report "independently verified".

No provider substitutes another model: an unavailable model is a recorded
failure, not a silent fallback.
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

#: USD per million tokens. A model missing here is costed as unknown, never 0.
PRICES = {
    "claude-opus-5-5": {"in": 4.00, "out": 20.00, "cache_read": 0.20, "cache_write": 5.00},
    "claude-sonnet-5-5": {"in": 2.00, "out": 10.00, "cache_read": 0.10, "cache_write": 2.50},
    # Haiku 5.5 rate for prompts up to 100K tokens (above: $0.50 / $2.50). Extraction
    # units are ~10,000 characters, far below that threshold.
    "claude-haiku-5-5": {"in": 0.10, "out": 0.50, "cache_read": 0.01, "cache_write": 0.125},
}


class ProviderError(RuntimeError):
    """A model call that did not produce a usable answer."""


class ProviderOutputLimit(ProviderError):
    """The answer hit the output-token limit before it was complete. Not
    retried as-is (the same request would truncate again); callers may split
    the input and ask again."""


def _final_error(name: str, model: str, purpose: str, last: Exception | None) -> ProviderError:
    cls = ProviderOutputLimit if isinstance(last, ProviderOutputLimit) else ProviderError
    return cls(f"{name} ({model}) failed for {purpose}: {last}")


class ProviderNotAuthorized(ProviderError):
    """Sending this package to this provider is not authorized."""


class ProviderNotConfigured(ProviderError):
    """The provider is deliberately not set up (no key/model/package): the
    role is absent, not failed."""


class ProviderUnavailable(ProviderError):
    """Credentials, SDK or model access missing."""


class CostLimitExceeded(ProviderUnavailable):
    """The run's cost cap (ENGINE_MAX_COST_USD) is reached or cannot be
    enforced. Raised BEFORE the provider call, so nothing more is spent; like
    any ProviderUnavailable it stops the run instead of recording page gaps."""


DEFAULT_MAX_COST_USD = 2.00


#: The project's hard per-run ceiling (CONSTRAINTS.md section 2). Settings can
#: lower a run cap, never raise it above this.
HARD_CEILING_USD = 2.00


def max_cost_usd() -> float:
    """Per-run spend cap in USD: ENGINE_MAX_COST_USD (default 2.00), never above HARD_CEILING_USD."""
    try:
        cap = float(os.getenv("ENGINE_MAX_COST_USD", DEFAULT_MAX_COST_USD))
    except ValueError:
        cap = DEFAULT_MAX_COST_USD
    cap = cap if cap > 0 else DEFAULT_MAX_COST_USD
    return min(cap, HARD_CEILING_USD)


class StageBudgetExceeded(ProviderError):
    """One stage's allotment cannot cover this request's worst-case cost.
    Raised BEFORE the provider call. Unlike CostLimitExceeded it does not stop
    the run: the stage records what it could not do (disclosed as a
    limitation, never silently dropped)."""


#: USD per web search request (server-side web search tool).
WEB_SEARCH_USD = 0.01
#: Characters per token assumed when estimating a request's input before it is
#: sent (English text is ~4; 3.5 leaves headroom).
CHARS_PER_TOKEN = 3.5


@dataclass
class Usage:
    provider: str
    model: str
    purpose: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    web_search_requests: int = 0
    seconds: float = 0.0
    cost_usd: float | None = None
    request_id: str | None = None
    status: str = "OK"
    error: str | None = None
    reservation: int | None = None
    #: the request may have been billed but no usage came back (a dropped
    #: stream, a server error): the ledger charges its reserved worst case
    charge_reserved: bool = False
    cost_estimated: bool = False

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if k not in ("reservation", "charge_reserved")}


def _openai_prices() -> dict | None:
    try:
        return {"in": float(os.environ["ENGINE_OPENAI_PRICE_IN"]), "out": float(os.environ["ENGINE_OPENAI_PRICE_OUT"]),
                "cache_read": float(os.getenv("ENGINE_OPENAI_PRICE_CACHED", os.environ["ENGINE_OPENAI_PRICE_IN"])),
                "cache_write": 0.0}
    except (KeyError, ValueError):
        return None


def _prices(provider: str, model: str) -> dict | None:
    return PRICES.get(model) if provider == "anthropic" else _openai_prices() if provider == "openai" else None


def cost_of(u: Usage) -> float | None:
    p = _prices(u.provider, u.model)
    if not p:
        return None
    return round((u.input_tokens * p["in"] + u.output_tokens * p["out"] + u.cache_read_tokens * p["cache_read"]
                  + u.cache_write_tokens * p["cache_write"]) / 1e6 + u.web_search_requests * WEB_SEARCH_USD, 6)


def worst_case_usd(provider: str, model: str, input_chars: int, max_tokens: int, *,
                   extra_input_tokens: int = 0, web_searches: int = 0) -> float | None:
    """Upper bound of one request's cost: every input token at the dearer of
    the input and cache-write price, and the full max_tokens of output
    (thinking counts inside max_tokens). None for an unpriced model."""
    p = _prices(provider, model)
    if p is None:
        return None
    tokens_in = input_chars / CHARS_PER_TOKEN + extra_input_tokens
    return round((tokens_in * max(p["in"], p["cache_write"]) + max_tokens * p["out"]) / 1e6
                 + web_searches * WEB_SEARCH_USD, 6)


def stage_of(purpose: str) -> str:
    """The budget stage a call belongs to: "extract:U3s1" -> "extract"."""
    return purpose.split(":", 1)[0]


def _new_bucket() -> dict:
    return {"calls": 0, "failed": 0, "input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0,
            "cache_write_tokens": 0, "seconds": 0.0, "cost_usd": 0.0, "cost_complete": True}


class UsageLedger:
    """Thread-safe usage collector and budget enforcer for one engine run.

    Before every real provider request the request's WORST-CASE cost (input
    estimate + its full max_tokens of output) is reserved; when the call ends
    the reservation is replaced by the actual cost. A request is refused --
    nothing sent -- when spent + reserved + its worst case would exceed the
    run cap or its stage's allotment. A run therefore never ends above its cap.

    * CostLimitExceeded (the run stops): the model is unpriced, the cap was
      already hit, or nothing is left of the run cap.
    * StageBudgetExceeded (the stage records what it could not do): the
      request does not fit what is left of its stage (plus the shared
      "reserve") or of the run.

    stage_budgets: {"extract": 0.20, ..., "reserve": 0.10}; None = only the
    run cap. Optionally appends each call to a local JSONL cost ledger
    (ENGINE_COST_LEDGER), kept separate from the application's telemetry."""

    def __init__(self, run_label: str = "", path: str | None = None, *, max_cost_usd: float | None = None,
                 stage_budgets: dict | None = None):
        self.run_label = run_label
        self.path = path if path is not None else os.getenv("ENGINE_COST_LEDGER")
        self.calls: list[Usage] = []
        self._lock = threading.Lock()
        self.max_cost_usd = max_cost_usd if max_cost_usd is not None else globals()["max_cost_usd"]()
        self.stage_budgets = dict(stage_budgets) if stage_budgets else None
        self.cost_limit_hit: str | None = None   # why the run breaker tripped, once it has
        self.refusals: list[dict] = []           # every refused request, with its stage and reason
        self.cached: dict[str, int] = {}         # stage -> answers served from checkpoints ($0)
        self._reserved: dict[int, tuple[str, float]] = {}
        self._next = 0

    # -- accounting helpers (call with the lock held) --
    def _committed(self) -> float:
        return sum(u.cost_usd or 0.0 for u in self.calls) + sum(v for _, v in self._reserved.values())

    def _stage_spent(self, stage: str) -> float:
        return sum(u.cost_usd or 0.0 for u in self.calls if stage_of(u.purpose) == stage) + \
            sum(v for s, v in self._reserved.values() if s == stage)

    def _reserve_used(self) -> float:
        """What stages have drawn beyond their own allotment (counted against "reserve")."""
        if not self.stage_budgets:
            return 0.0
        stages = {stage_of(u.purpose) for u in self.calls} | {s for s, _ in self._reserved.values()}
        return sum(max(0.0, self._stage_spent(s) - self.stage_budgets.get(s, 0.0)) for s in stages)

    def _stage_left(self, stage: str) -> float:
        run_left = self.max_cost_usd - self._committed()
        if not self.stage_budgets:
            return max(0.0, run_left)
        own = self.stage_budgets.get(stage, 0.0) - self._stage_spent(stage)
        reserve = self.stage_budgets.get("reserve", 0.0) - self._reserve_used()
        return max(0.0, min(run_left, max(own, 0.0) + max(reserve, 0.0)))

    # -- public --
    def spent_usd(self) -> float:
        with self._lock:
            return round(sum(u.cost_usd or 0.0 for u in self.calls), 6)

    def committed_usd(self) -> float:
        """Spent plus what in-flight requests have reserved."""
        with self._lock:
            return round(self._committed(), 6)

    def remaining_usd(self, stage: str | None = None) -> float:
        """What the run (or one stage, with the shared reserve) can still commit."""
        with self._lock:
            if stage is None:
                return max(0.0, self.max_cost_usd - self._committed())
            return self._stage_left(stage)

    def before_call(self, provider: str, model: str, purpose: str, input_chars: int, max_tokens: int = 32000, *,
                    extra_input_tokens: int = 0, web_searches: int = 0) -> int:
        """Reserves the request's worst-case cost or refuses it (see the class
        docstring). Returns the reservation id to put on the call's Usage."""
        stage = stage_of(purpose)
        worst = worst_case_usd(provider, model, input_chars, max_tokens, extra_input_tokens=extra_input_tokens,
                               web_searches=web_searches)
        with self._lock:
            if worst is None:
                reason = f"no price is configured for {provider}:{model}, so the run cost cap cannot be enforced"
                self.cost_limit_hit = self.cost_limit_hit or reason
                self.refusals.append({"purpose": purpose, "stage": stage, "kind": "COST_LIMIT", "reason": reason})
                raise CostLimitExceeded(reason)
            committed = self._committed()
            if self.cost_limit_hit or committed >= self.max_cost_usd - 1e-9:
                reason = self.cost_limit_hit or (f"run cost cap reached: ${committed:.4f} committed of "
                                                 f"${self.max_cost_usd:.2f}; refused {purpose}")
                self.cost_limit_hit = reason
                self.refusals.append({"purpose": purpose, "stage": stage, "kind": "COST_LIMIT", "reason": reason})
                raise CostLimitExceeded(reason)
            left = self._stage_left(stage)
            if worst > left + 1e-9:
                if self.stage_budgets is None:
                    reason = (f"run cost cap: ${committed:.4f} spent or reserved of ${self.max_cost_usd:.2f}; "
                              f"{purpose} could cost up to ${worst:.4f}; refused before sending")
                    self.cost_limit_hit = reason
                    self.refusals.append({"purpose": purpose, "stage": stage, "kind": "COST_LIMIT",
                                          "reason": reason})
                    raise CostLimitExceeded(reason)
                reason = (f"budget: {stage} can still commit ${left:.4f} (stage allotment "
                          f"${self.stage_budgets.get(stage, 0.0):.2f} + reserve, within the ${self.max_cost_usd:.2f} "
                          f"run cap); {purpose} could cost up to ${worst:.4f}; refused before sending")
                self.refusals.append({"purpose": purpose, "stage": stage, "kind": "STAGE_BUDGET", "reason": reason})
                raise StageBudgetExceeded(reason)
            self._next += 1
            self._reserved[self._next] = (stage, worst)
            return self._next

    def release(self, reservation: int | None) -> None:
        with self._lock:
            self._reserved.pop(reservation, None)

    def add_cached(self, purpose: str) -> None:
        with self._lock:
            st = stage_of(purpose)
            self.cached[st] = self.cached.get(st, 0) + 1

    def add(self, u: Usage) -> None:
        u.cost_usd = cost_of(u)
        with self._lock:
            held = self._reserved.pop(u.reservation, None)
            if u.charge_reserved and held is not None and not (u.input_tokens or u.output_tokens):
                u.cost_usd = round(held[1], 6)     # unknown usage: assume the worst case was billed
                u.cost_estimated = True
            self.calls.append(u)
            spent = sum(c.cost_usd or 0.0 for c in self.calls)
            if spent > self.max_cost_usd + 1e-9 and not self.cost_limit_hit:
                self.cost_limit_hit = (f"run cost cap exceeded: ${spent:.4f} spent of ${self.max_cost_usd:.2f} "
                                       f"after {u.purpose}")
            if self.path:
                os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
                with open(self.path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(dict(u.to_dict(), run=self.run_label, at=time.strftime("%Y-%m-%dT%H:%M:%S")))
                             + "\n")

    def summary(self) -> dict:
        with self._lock:
            calls = list(self.calls)
            refusals = list(self.refusals)
            cached = dict(self.cached)
        by: dict[str, dict] = {}
        by_stage: dict[str, dict] = {}
        for u in calls:
            for table, k in ((by, f"{u.provider}:{u.model}"), (by_stage, stage_of(u.purpose))):
                b = table.setdefault(k, _new_bucket())
                b["calls"] += 1
                b["failed"] += u.status != "OK"
                b["input_tokens"] += u.input_tokens
                b["output_tokens"] += u.output_tokens
                b["cache_read_tokens"] += u.cache_read_tokens
                b["cache_write_tokens"] += u.cache_write_tokens
                b["seconds"] = round(b["seconds"] + u.seconds, 1)
                if u.cost_estimated:
                    b["estimated_calls"] = b.get("estimated_calls", 0) + 1
                if u.web_search_requests:
                    b["web_search_requests"] = b.get("web_search_requests", 0) + u.web_search_requests
                if u.cost_usd is None:
                    b["cost_complete"] = False
                else:
                    b["cost_usd"] = round(b["cost_usd"] + u.cost_usd, 4)
        for st, n in cached.items():
            by_stage.setdefault(st, _new_bucket())["from_checkpoint"] = n
        if self.stage_budgets is not None:
            for st, b in by_stage.items():
                b["budget_usd"] = self.stage_budgets.get(st, 0.0)
        total = round(sum(b["cost_usd"] for b in by.values()), 4)
        return {"by_model": by, "by_stage": by_stage, "total_cost_usd": total,
                "cost_complete": all(b["cost_complete"] for b in by.values()), "calls": len(calls),
                "max_cost_usd": self.max_cost_usd, "stage_budgets": self.stage_budgets,
                "cost_limit_hit": self.cost_limit_hit, "refusals": refusals}


@dataclass
class Analyst:
    """Base class. `role` names the provider family for independence checks."""
    name: str
    provider: str
    model: str
    synthetic: bool = False
    config: dict = field(default_factory=dict)

    def describe(self) -> dict:
        return {"name": self.name, "provider": self.provider, "model": self.model, "synthetic": self.synthetic,
                "config": self.config}

    def check_allowed(self, data_class: str) -> None:  # pragma: no cover - overridden
        return None

    def call_json(self, system: str, user: str, schema: dict, *, purpose: str, ledger: UsageLedger,
                  data_class: str, max_tokens: int = 32000) -> dict:
        raise NotImplementedError


def _flat(user) -> str:
    """`user` is a string, or (shared_prefix, rest): the prefix is the part
    repeated across calls of one run (package context), cached where supported."""
    return user if isinstance(user, str) else "\n\n".join(user)


_ACCOUNT_MARKERS = ("credit balance", "insufficient_quota", "billing", "quota exceeded", "account is not active",
                    "permission", "api key", "authentication")


def _account_problem(exc) -> bool:
    """Errors no retry or smaller request can fix (credit, quota, key,
    permission): the whole run must stop instead of recording page gaps."""
    code = getattr(exc, "status_code", None)
    if code in (401, 402, 403):
        return True
    return code in (400, 429) and any(m in str(exc).lower() for m in _ACCOUNT_MARKERS[:5])


def _parse_json(text: str) -> dict:
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):]
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ProviderError(f"unparseable JSON output: {exc}") from exc
    if not isinstance(data, dict):
        raise ProviderError("JSON output is not an object")
    return data


class AnthropicAnalyst(Analyst):
    def __init__(self, model: str = "claude-opus-5-5", *, effort: str = "high", api_key: str | None = None,
                 name: str = "claude", client=None, max_attempts: int = 3):
        super().__init__(name=name, provider="anthropic", model=model,
                         config={"effort": effort, "thinking": "adaptive", "structured_output": True})
        self.effort = effort
        self._api_key = api_key
        self._client = client
        self.max_attempts = max_attempts

    def client(self):
        if self._client is None:
            import config as app_config
            if not (self._api_key or app_config.get_api_key()):
                raise ProviderUnavailable("no Anthropic API key configured")
            self._client = app_config.get_anthropic_client(self._api_key)
        return self._client

    def call_json(self, system, user, schema, *, purpose, ledger, data_class, max_tokens=32000):
        import anthropic
        last: Exception | None = None
        for attempt in range(self.max_attempts):
            rid = ledger.before_call("anthropic", self.model, purpose, len(system) + len(_flat(user)), max_tokens)
            u = Usage("anthropic", self.model, purpose, reservation=rid)
            t0 = time.monotonic()
            try:
                with self.client().messages.stream(
                        model=self.model, max_tokens=max_tokens, thinking={"type": "adaptive"},
                        output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": schema}},
                        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                        messages=[{"role": "user", "content": user if isinstance(user, str) else [
                            {"type": "text", "text": user[0], "cache_control": {"type": "ephemeral"}},
                            {"type": "text", "text": user[1]}]}]) as stream:
                    msg = stream.get_final_message()
                u.seconds = round(time.monotonic() - t0, 2)
                us = msg.usage
                u.input_tokens = us.input_tokens or 0
                u.output_tokens = us.output_tokens or 0
                u.cache_read_tokens = getattr(us, "cache_read_input_tokens", 0) or 0
                u.cache_write_tokens = getattr(us, "cache_creation_input_tokens", 0) or 0
                u.request_id = getattr(msg, "_request_id", None)
                if msg.stop_reason == "refusal":
                    raise ProviderError("model declined the request (refusal)")
                if msg.stop_reason == "max_tokens":
                    raise ProviderOutputLimit("output limit reached before the answer was complete")
                text = "".join(b.text for b in msg.content if b.type == "text")
                data = _parse_json(text)
                ledger.add(u)
                return data
            except anthropic.RateLimitError as exc:       # refused before any work: not billed
                last = exc
                retry = True
            except (anthropic.APIConnectionError, anthropic.InternalServerError) as exc:
                last = exc
                retry = True
                u.charge_reserved = True    # the stream may have been billed before it dropped
            except anthropic.APIStatusError as exc:
                last = exc
                retry = exc.status_code >= 500 or exc.status_code == 529
                u.charge_reserved = exc.status_code >= 500
                if _account_problem(exc):
                    u.status, u.error = "FAILED", f"{type(exc).__name__}: {str(exc)[:200]}"
                    ledger.add(u)
                    raise ProviderUnavailable(f"{self.name} ({self.model}): provider account problem: "
                                              f"{str(exc)[:300]}") from exc
            except ProviderError as exc:
                last = exc
                retry = "unparseable" in str(exc)
            except BaseException:
                ledger.release(rid)          # an unexpected error never leaves a reservation behind
                raise
            u.seconds = round(time.monotonic() - t0, 2)
            u.status, u.error = "FAILED", f"{type(last).__name__}: {str(last)[:200]}"
            ledger.add(u)
            if not retry or attempt == self.max_attempts - 1:
                break
            time.sleep(min(60, 4 * 2 ** attempt))
        raise _final_error(self.name, self.model, purpose, last)


class RoutedAnalyst(Analyst):
    """One analyst role served by two models: raw page extraction
    (purpose "extract:*") goes to `extractor`; everything else the role does
    (its package-level review) goes to `default`. Both must be the same
    provider, so the role's provider for independence checks is unchanged."""

    def __init__(self, extractor: Analyst, default: Analyst, *, name: str):
        if extractor.provider != default.provider:
            raise ValueError("a routed analyst's models must come from one provider")
        super().__init__(name=name, provider=default.provider, model=default.model,
                         synthetic=extractor.synthetic or default.synthetic,
                         config={"extract": extractor.describe(), "default": default.describe()})
        self.extractor, self.default = extractor, default

    def route(self, purpose: str) -> Analyst:
        return self.extractor if purpose.startswith("extract:") else self.default

    def check_allowed(self, data_class: str) -> None:
        self.extractor.check_allowed(data_class)
        self.default.check_allowed(data_class)

    def call_json(self, system, user, schema, *, purpose, ledger, data_class, max_tokens=32000):
        return self.route(purpose).call_json(system, user, schema, purpose=purpose, ledger=ledger,
                                             data_class=data_class, max_tokens=max_tokens)


def openai_client_data_authorized() -> bool:
    """The owner's separate authorization to send client documents to OpenAI
    (constraint C3). Off unless explicitly configured."""
    return os.getenv("ENGINE_OPENAI_CLIENT_DATA_AUTHORIZED", "").strip().lower() == "yes"


class OpenAIAnalyst(Analyst):
    def __init__(self, model: str | None = None, *, api_key: str | None = None, name: str = "openai",
                 reasoning_effort: str = "high", client=None, max_attempts: int = 3):
        model = model or os.getenv("ENGINE_OPENAI_MODEL", "")
        super().__init__(name=name, provider="openai", model=model,
                         config={"reasoning_effort": reasoning_effort, "structured_output": True})
        self._api_key = api_key or os.getenv("OPENAI_API_KEY")
        self._client = client
        self.reasoning_effort = reasoning_effort
        self.max_attempts = max_attempts

    def check_allowed(self, data_class: str) -> None:
        if data_class != "SYNTHETIC" and not openai_client_data_authorized():
            raise ProviderNotAuthorized("client documents may not be sent to OpenAI: the owner's authorization "
                                        "(ENGINE_OPENAI_CLIENT_DATA_AUTHORIZED) is not configured")
        if not self.model:
            raise ProviderNotConfigured("no OpenAI model configured (ENGINE_OPENAI_MODEL)")
        if self._client is None and not self._api_key:
            raise ProviderNotConfigured("no OpenAI API key configured (OPENAI_API_KEY)")

    def client(self):
        if self._client is None:
            try:
                import openai
            except ImportError as exc:
                raise ProviderNotConfigured("the openai package is not installed") from exc
            self._client = openai.OpenAI(api_key=self._api_key)
        return self._client

    def call_json(self, system, user, schema, *, purpose, ledger, data_class, max_tokens=32000):
        self.check_allowed(data_class)
        self.client()                      # a missing SDK is "not configured", never a per-page failure
        last: Exception | None = None
        for attempt in range(self.max_attempts):
            rid = ledger.before_call("openai", self.model, purpose, len(system) + len(_flat(user)), max_tokens)
            u = Usage("openai", self.model, purpose, reservation=rid)
            t0 = time.monotonic()
            retry = False
            try:
                resp = self.client().responses.create(
                    model=self.model, instructions=system, input=_flat(user), max_output_tokens=max_tokens,
                    reasoning={"effort": self.reasoning_effort}, store=False,
                    text={"format": {"type": "json_schema", "name": "result", "schema": schema, "strict": True}})
                u.seconds = round(time.monotonic() - t0, 2)
                us = getattr(resp, "usage", None)
                if us is not None:
                    u.input_tokens = getattr(us, "input_tokens", 0) or 0
                    u.output_tokens = getattr(us, "output_tokens", 0) or 0
                    det = getattr(us, "input_tokens_details", None)
                    u.cache_read_tokens = getattr(det, "cached_tokens", 0) or 0 if det else 0
                    u.input_tokens -= u.cache_read_tokens
                u.request_id = getattr(resp, "id", None)
                if getattr(resp, "status", "completed") != "completed":
                    reason = getattr(getattr(resp, "incomplete_details", None), "reason", None)
                    if reason == "max_output_tokens":
                        raise ProviderOutputLimit("output limit reached before the answer was complete")
                    raise ProviderError(f"response status {resp.status}")
                data = _parse_json(resp.output_text)
                ledger.add(u)
                return data
            except ProviderError as exc:
                last, retry = exc, "unparseable" in str(exc)
            except Exception as exc:  # SDK error classes vary by version
                last = exc
                code = getattr(exc, "status_code", None)
                retry = code is None or code == 429 or code >= 500
                if _account_problem(exc):
                    u.status, u.error = "FAILED", f"{type(exc).__name__}: {str(exc)[:200]}"
                    ledger.add(u)
                    raise ProviderUnavailable(f"{self.name} ({self.model}): provider account problem: "
                                              f"{str(exc)[:300]}") from exc
            u.seconds = round(time.monotonic() - t0, 2)
            u.status, u.error = "FAILED", f"{type(last).__name__}: {str(last)[:200]}"
            ledger.add(u)
            if not retry or attempt == self.max_attempts - 1:
                break
            time.sleep(min(60, 4 * 2 ** attempt))
        raise _final_error(self.name, self.model, purpose, last)


class ScriptedAnalyst(Analyst):
    """Test double: `responder(purpose, system, user, schema) -> dict`. Always
    synthetic; the pipeline never labels its output as model intelligence."""

    def __init__(self, responder: Callable[[str, str, str, dict], dict], *, name: str = "scripted",
                 provider: str = "scripted", model: str = "scripted"):
        super().__init__(name=name, provider=provider, model=model, synthetic=True)
        self.responder = responder

    def call_json(self, system, user, schema, *, purpose, ledger, data_class, max_tokens=32000):
        u = Usage(self.provider, self.model, purpose)
        try:
            data = self.responder(purpose, system, _flat(user), schema)
        except Exception as exc:
            u.status, u.error = "FAILED", str(exc)[:200]
            ledger.add(u)
            if isinstance(exc, ProviderOutputLimit):
                raise
            raise ProviderError(str(exc)) from exc
        ledger.add(u)
        return data
