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


def max_cost_usd() -> float:
    """Hard per-run spend cap in USD (ENGINE_MAX_COST_USD, default 2.00)."""
    try:
        cap = float(os.getenv("ENGINE_MAX_COST_USD", DEFAULT_MAX_COST_USD))
    except ValueError:
        cap = DEFAULT_MAX_COST_USD
    return cap if cap > 0 else DEFAULT_MAX_COST_USD


@dataclass
class Usage:
    provider: str
    model: str
    purpose: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    seconds: float = 0.0
    cost_usd: float | None = None
    request_id: str | None = None
    status: str = "OK"
    error: str | None = None

    def to_dict(self) -> dict:
        return dict(self.__dict__)


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
                  + u.cache_write_tokens * p["cache_write"]) / 1e6, 6)


class UsageLedger:
    """Thread-safe usage collector for one engine run; optionally appends each
    call to a local JSONL cost ledger (ENGINE_COST_LEDGER), kept separate from
    the application's own telemetry so rebuild costs are reported on their own."""

    def __init__(self, run_label: str = "", path: str | None = None, *, max_cost_usd: float | None = None):
        self.run_label = run_label
        self.path = path if path is not None else os.getenv("ENGINE_COST_LEDGER")
        self.calls: list[Usage] = []
        self._lock = threading.Lock()
        self.max_cost_usd = max_cost_usd if max_cost_usd is not None else globals()["max_cost_usd"]()
        self.cost_limit_hit: str | None = None   # why the breaker tripped, once it has

    def spent_usd(self) -> float:
        with self._lock:
            return round(sum(u.cost_usd or 0.0 for u in self.calls), 6)

    def before_call(self, provider: str, model: str, purpose: str, input_chars: int) -> None:
        """Circuit breaker, checked before every real provider request
        (including retries). Refuses the call -- raising CostLimitExceeded,
        nothing sent -- when the cap is already reached, when what is spent
        plus this request's estimated input cost would reach it, or when the
        model has no price so the cap cannot be enforced. Output cost is only
        known afterwards, so the run can end above the cap by at most the
        output of the requests already in flight; no request starts after."""
        p = _prices(provider, model)
        if p is None:
            reason = f"no price is configured for {provider}:{model}, so the run cost cap cannot be enforced"
        else:
            spent = self.spent_usd()
            est = input_chars / 4 * p["in"] / 1e6
            reason = None
            if self.cost_limit_hit or spent + est >= self.max_cost_usd:
                reason = (f"run cost cap reached: ${spent:.4f} spent of ${self.max_cost_usd:.2f} "
                          f"(ENGINE_MAX_COST_USD); refused {purpose}")
        if reason:
            with self._lock:
                self.cost_limit_hit = self.cost_limit_hit or reason
            raise CostLimitExceeded(reason)

    def add(self, u: Usage) -> None:
        u.cost_usd = cost_of(u)
        with self._lock:
            self.calls.append(u)
            spent = sum(c.cost_usd or 0.0 for c in self.calls)
            if spent > self.max_cost_usd and not self.cost_limit_hit:
                self.cost_limit_hit = (f"run cost cap exceeded: ${spent:.4f} spent of ${self.max_cost_usd:.2f} "
                                       f"(ENGINE_MAX_COST_USD) after {u.purpose}")
            if self.path:
                os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
                with open(self.path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(dict(u.to_dict(), run=self.run_label, at=time.strftime("%Y-%m-%dT%H:%M:%S")))
                             + "\n")

    def summary(self) -> dict:
        with self._lock:
            calls = list(self.calls)
        by: dict[str, dict] = {}
        for u in calls:
            k = f"{u.provider}:{u.model}"
            b = by.setdefault(k, {"calls": 0, "failed": 0, "input_tokens": 0, "output_tokens": 0,
                                  "cache_read_tokens": 0, "seconds": 0.0, "cost_usd": 0.0, "cost_complete": True})
            b["calls"] += 1
            b["failed"] += u.status != "OK"
            b["input_tokens"] += u.input_tokens
            b["output_tokens"] += u.output_tokens
            b["cache_read_tokens"] += u.cache_read_tokens
            b["seconds"] = round(b["seconds"] + u.seconds, 1)
            if u.cost_usd is None:
                b["cost_complete"] = False
            else:
                b["cost_usd"] = round(b["cost_usd"] + u.cost_usd, 4)
        total = round(sum(b["cost_usd"] for b in by.values()), 4)
        return {"by_model": by, "total_cost_usd": total,
                "cost_complete": all(b["cost_complete"] for b in by.values()), "calls": len(calls),
                "max_cost_usd": self.max_cost_usd, "cost_limit_hit": self.cost_limit_hit}


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
            ledger.before_call("anthropic", self.model, purpose, len(system) + len(_flat(user)))
            u = Usage("anthropic", self.model, purpose)
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
            except (anthropic.RateLimitError, anthropic.APIConnectionError, anthropic.InternalServerError) as exc:
                last = exc
                retry = True
            except anthropic.APIStatusError as exc:
                last = exc
                retry = exc.status_code >= 500 or exc.status_code == 529
                if _account_problem(exc):
                    u.status, u.error = "FAILED", f"{type(exc).__name__}: {str(exc)[:200]}"
                    ledger.add(u)
                    raise ProviderUnavailable(f"{self.name} ({self.model}): provider account problem: "
                                              f"{str(exc)[:300]}") from exc
            except ProviderError as exc:
                last = exc
                retry = "unparseable" in str(exc)
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
            ledger.before_call("openai", self.model, purpose, len(system) + len(_flat(user)))
            u = Usage("openai", self.model, purpose)
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
