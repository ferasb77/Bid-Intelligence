"""Per-mode, per-stage cost budgets and the pre-flight check.

Two modes, each with a hard run cap:

* FAST -- Opportunity Snapshot. Haiku extraction of the whole package, one
  Sonnet writing pass, deterministic verification, conflict scan and checks.
  No Opus, no adjudication, no model review, no buyer research.
* FULL -- Bid Opportunity Assessment. The same extraction (reused from a FAST
  run's checkpoints when the package is unchanged), then Opus package review,
  adjudication, conflicts, analysis and final review, then buyer research if
  the budget still allows it.

Each stage has an allotment (USD) and a fixed output limit per call, so the
worst case of every call is known before it is sent (see UsageLedger). The
pre-flight sums the worst case of the planned calls and refuses to start a run
that could exceed its cap. Caps can be lowered (never raised past the
application's ENGINE_MAX_COST_USD) with ENGINE_FAST_MAX_COST_USD /
ENGINE_FULL_MAX_COST_USD."""
from __future__ import annotations

import os

from engine.package import SourcePackage, units
from engine.providers import max_cost_usd, worst_case_usd

MODES = ("FAST", "FULL")

DEFAULT_CAPS = {"FAST": 0.50, "FULL": 2.00}

#: USD allotment per stage. "reserve" is shared: a stage that needs more than
#: its own allotment (output-limit splits, a parse retry) may draw on it.
STAGE_BUDGETS = {
    "FAST": {"extract": 0.20, "analysis": 0.15, "reserve": 0.15},
    "FULL": {"extract": 0.20, "package_review": 0.30, "adjudicate": 0.40, "conflicts": 0.20, "analysis": 0.25,
             "final_review": 0.30, "buyer_research": 0.25, "reserve": 0.10},
}

#: Output limit (max_tokens, thinking included) of one call of each stage. The
#: worst case of a call is this many output tokens at the model's output price.
MAX_TOKENS = {"extract": 16000, "package_review": 10000, "adjudicate": 6000, "conflicts": 6000,
              "analysis": 8000, "final_review": 8000, "buyer_research": 3000}

#: Characters of prompt text the stages add around their data (system prompts,
#: instructions, schemas), used by the pre-flight input estimates.
PROMPT_OVERHEAD_CHARS = 8000

#: Stages whose worst case the pre-flight must cover before a run may start
#: (buyer research is optional: it runs only if the budget still allows).
REQUIRED_STAGES = {"FAST": ("extract", "analysis"),
                   "FULL": ("extract", "package_review", "adjudicate", "conflicts", "analysis", "final_review")}


def cap(mode: str) -> float:
    if mode not in MODES:
        raise ValueError(f"unknown engine mode {mode!r}")
    try:
        c = float(os.getenv(f"ENGINE_{mode}_MAX_COST_USD", DEFAULT_CAPS[mode]))
    except ValueError:
        c = DEFAULT_CAPS[mode]
    c = c if c > 0 else DEFAULT_CAPS[mode]
    return round(min(c, max_cost_usd()), 4)


def stage_budgets(mode: str) -> dict:
    """The mode's allotments, scaled down proportionally if its cap was lowered."""
    b = dict(STAGE_BUDGETS[mode])
    total = sum(b.values())
    c = cap(mode)
    if total > c:
        b = {k: round(v * c / total, 4) for k, v in b.items()}
    return b


def max_tokens(stage: str) -> int:
    return MAX_TOKENS[stage]


def _extraction_worst(package: SourcePackage, model: str, unit_chars: int,
                      provider: str = "anthropic") -> tuple[float | None, int]:
    """Worst case of reading the whole package once: one call per unit (and per
    pre-split part of an oversized page), full output limit each."""
    from engine import extraction
    total, calls = 0.0, 0
    ctx_chars = len(extraction.SYSTEM) + len(package.definitions() or "") + len(package.outline() or "") + 2000
    for u in units(package, max_chars=unit_chars):
        parts = ([p for p in extraction._text_parts(u.locations[0].text, unit_chars)]
                 if len(u.locations) == 1 and len(u.locations[0].text) > unit_chars else [u.text()])
        for text in parts:
            w = worst_case_usd(provider, model, ctx_chars + len(text), MAX_TOKENS["extract"])
            if w is None:
                return None, 0
            total += w
            calls += 1
    return round(total, 4), calls


def preflight(package: SourcePackage, mode: str, *, extract_model: str, synthesis_model: str,
              writer_model: str | None = None, independent: tuple[str, str] | None = None) -> dict:
    """Worst-case cost of the stages a run of this mode must complete, before
    any call. `ok` is False when that worst case exceeds the mode cap or a
    required stage's worst case exceeds its allotment plus the reserve -- the
    run must then not start.

    independent: (provider, model) of FULL's independent analyst, when one is
    configured: its complete extraction draws on the same "extract" allotment,
    so it is counted there (an unpriced one fails the pre-flight).

    The tail stages are estimated from the package size: their prompts carry
    the extracted findings, which are a fraction of the package text."""
    budgets = stage_budgets(mode)
    unit_chars = int(os.getenv("ENGINE_UNIT_CHARS", "10000"))
    pkg_chars = sum(len(loc.text) for loc in package.locations)
    ext, ext_calls = _extraction_worst(package, extract_model, unit_chars)
    stages = {"extract": {"worst_usd": ext, "calls": ext_calls, "model": extract_model}}
    problems = []
    if mode == "FULL" and independent:
        ind, ind_calls = _extraction_worst(package, independent[1], unit_chars, provider=independent[0])
        if ind is None:
            problems.append(f"no price is configured for the independent analyst {independent[0]}:{independent[1]}")
            ind = 0.0
        stages["extract"].update(worst_usd=round(ext + ind, 4), calls=ext_calls + ind_calls,
                                 independent={"model": independent[1], "worst_usd": ind})
    # the register (one line per finding) is at most about half the package text
    reg_chars = pkg_chars // 2 + PROMPT_OVERHEAD_CHARS
    if mode == "FAST":
        w = worst_case_usd("anthropic", writer_model or synthesis_model, reg_chars, MAX_TOKENS["analysis"]) or 0.0
        stages["analysis"] = {"worst_usd": round(w, 4), "calls": 1, "model": writer_model or synthesis_model}
    else:
        for st, chars, calls in (("package_review", reg_chars, 1),
                                 ("conflicts", min(reg_chars, 60000), 1),
                                 ("analysis", reg_chars, 1),
                                 ("final_review", 40000 + reg_chars, 1)):
            w = worst_case_usd("anthropic", synthesis_model, chars, MAX_TOKENS[st]) or 0.0
            stages[st] = {"worst_usd": round(w * calls, 4), "calls": calls, "model": synthesis_model}
        # adjudication is batched; it runs the batches its allotment covers and
        # discloses the rest, so its worst case is its allotment
        stages["adjudicate"] = {"worst_usd": budgets["adjudicate"], "calls": None, "model": synthesis_model,
                                "note": "batches beyond the allotment stay disputed and are disclosed"}
    required = REQUIRED_STAGES[mode]
    total = round(sum(stages[s]["worst_usd"] for s in required), 4)
    reserve = budgets.get("reserve", 0.0)
    for s in required:
        if stages[s]["worst_usd"] > budgets.get(s, 0.0) + reserve + 1e-9:
            problems.append(f"{s} worst case ${stages[s]['worst_usd']:.2f} exceeds its allotment "
                            f"${budgets.get(s, 0.0):.2f} + reserve ${reserve:.2f}")
    if total > cap(mode) + 1e-9:
        problems.append(f"worst case ${total:.2f} exceeds the {mode} cap ${cap(mode):.2f}")
    return {"mode": mode, "cap_usd": cap(mode), "stage_budgets": budgets, "stages": stages,
            "worst_case_required_usd": total, "ok": not problems, "problems": problems,
            "package_chars": pkg_chars, "locations": len(package.locations)}
