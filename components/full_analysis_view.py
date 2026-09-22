"""
components/full_analysis_view.py -- MA-2B presentation adapter for Full
Bid Intelligence (the animated multi-agent experience).

PURE: no Streamlit, no database, no model/provider access, no imports of
full_analysis.py. It turns what full_analysis_service already persisted
(status dict from get_full_analysis_status, result dict from
get_full_analysis_result) into:

  * a truthful view model (bot states, reconciliation state, overall
    stage, honest "N of 6" progress text -- never a percentage);
  * the HTML/CSS/SVG constellation (six specialist bots around the shared
    canonical truth hub, reconciliation beneath it);
  * a decision-oriented grouping of the persisted FullAnalysisResult.

Truthfulness rules (MA-2A.2 / MA-2B):
  * A specialist's state comes from the durable event log (which already
    carries PARTIAL for a truncated result) and, whenever a persisted
    specialist row exists, from that row's `effective_status` -- NEVER
    from the raw migration-020 `status` column, which reads COMPLETE for a
    truncated result.
  * Nothing here ever invents a state: a specialist with no event yet is
    WAITING, not RUNNING; reconciliation is RUNNING only after
    RECONCILIATION_STARTED was recorded.
  * Animation is decoration of state: RUNNING bots pulse, a data packet is
    drawn ONLY for a specialist that transitioned into COMPLETE/PARTIAL
    since the previous poll of this browser session (a reconnect draws
    none), and a stuck run renders with every animation stopped.
"""
from __future__ import annotations

import html

# ─── closed vocabularies (mirrors full_analysis_service; duplicated as
#     plain strings so this module never imports the execution layer) ───
QUEUED, RUNNING, COMPLETE, PARTIAL, FAILED, SKIPPED = (
    "QUEUED", "RUNNING", "COMPLETE", "PARTIAL", "FAILED", "SKIPPED")
WAITING = "WAITING"  # no event yet for this specialist (not fabricated as QUEUED)
FINISHED = (COMPLETE, PARTIAL, FAILED)
USABLE = (COMPLETE, PARTIAL)
TERMINAL_RUN = (COMPLETE, PARTIAL, FAILED)

SPECIALISTS = (
    ("PROCUREMENT_STRUCTURE", "Procurement Structure", "PS"),
    ("REQUIREMENTS_COMPLIANCE", "Requirements & Compliance", "RC"),
    ("EVALUATION_INTELLIGENCE", "Evaluation Intelligence", "EV"),
    ("SCOPE_DELIVERABLES", "Scope & Deliverables", "SD"),
    ("COMMERCIAL_CONTRACTUAL", "Commercial & Contractual", "CC"),
    ("SCHEDULE_SUBMISSION", "Schedule & Submission", "SS"),
)
SPECIALIST_IDS = tuple(s[0] for s in SPECIALISTS)
SPECIALIST_NAME = {s[0]: s[1] for s in SPECIALISTS}

STATE_LABEL = {
    WAITING: "Waiting",
    QUEUED: "Queued",
    RUNNING: "Analyzing",
    COMPLETE: "Complete",
    PARTIAL: "Partial output",
    FAILED: "Failed",
    SKIPPED: "Not run",
}
# Text/icon mark per state so status never depends on colour or motion.
STATE_MARK = {
    WAITING: "○", QUEUED: "○", RUNNING: "◐", COMPLETE: "✓",
    PARTIAL: "!", FAILED: "✕", SKIPPED: "–",
}

#: Poll interval for a non-terminal run (seconds). A run is ~90s; 3s gives
#: ~30 light reads per viewer per run and keeps transitions legible.
POLL_INTERVAL_SECONDS = 3

# Hub counts: read from the CANONICAL_PACKAGE_READY event's own persisted
# object_counts -- no extra retrieval.
HUB_COUNT_LABELS = (
    ("CANONICAL_REQUIREMENT", "requirements"),
    ("SCOPED_EVALUATION_CRITERION", "evaluation criteria"),
    ("CATEGORY_SCOPE_ITEM", "scope items"),
    ("SCOPED_MILESTONE", "milestones"),
    ("COMMERCIAL_OBLIGATION", "commercial obligations"),
)

START_OUTCOME_NOTES = {
    "CREATED": ("info", "Full Analysis started. Six specialists are working from the shared canonical truth."),
    "ACTIVE_RUN_EXISTS": ("info", "A Full Analysis is already running for this bid. Reconnected to it."),
    "REUSED_COMPLETE": ("success", "Using current Full Analysis. Nothing has changed since it ran, so no new analysis was needed."),
    "EXISTING_FAILED": ("warn", "The last Full Analysis for these exact inputs failed. It was not re-run automatically."),
    "EXISTING_PARTIAL": ("warn", "The last Full Analysis for these exact inputs is partial. It was not re-run automatically."),
}


def esc(value) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


# ═══════════════════════════════════════════════════════════════════════
# View model
# ═══════════════════════════════════════════════════════════════════════

def bot_state(specialist_id: str, status: dict | None, rows_by_id: dict | None = None) -> str:
    """Authoritative UI state for one specialist.

    Precedence: a persisted specialist row's `effective_status` (MA-2A.2)
    > the event-derived state from get_full_analysis_status > WAITING.
    The raw row `status` column is deliberately never read."""
    row = (rows_by_id or {}).get(specialist_id)
    if row is not None:
        eff = row.get("effective_status")
        if eff in (COMPLETE, PARTIAL, FAILED, SKIPPED):
            return eff
    derived = (((status or {}).get("specialists") or {}).get(specialist_id) or {}).get("status")
    if derived in (QUEUED, RUNNING, COMPLETE, PARTIAL, FAILED, SKIPPED):
        return derived
    if (status or {}).get("status") in TERMINAL_RUN:
        return SKIPPED
    return WAITING


def rows_by_specialist(rows) -> dict:
    return {r.get("specialist_id"): r for r in (rows or []) if isinstance(r, dict)}


def reconciliation_state(status: dict | None) -> str:
    st = ((status or {}).get("reconciliation") or {}).get("status")
    if st in (RUNNING, COMPLETE, PARTIAL, FAILED, SKIPPED):
        return st
    return WAITING


def hub_counts(status: dict | None) -> list:
    """[(count, label)] from the persisted CANONICAL_PACKAGE_READY event,
    or [] when that event is not (yet) in the log."""
    for ev in (status or {}).get("events") or []:
        if ev.get("event_type") == "CANONICAL_PACKAGE_READY":
            counts = (ev.get("detail") or {}).get("object_counts") or {}
            return [(int(counts[k]), label) for k, label in HUB_COUNT_LABELS
                    if isinstance(counts.get(k), (int, float))]
    return []


def is_stuck(status: dict | None) -> bool:
    return bool(((status or {}).get("stuck") or {}).get("stuck"))


def should_poll(status: dict | None) -> bool:
    """Poll only a genuinely live run: non-terminal and not stuck."""
    if not status:
        return False
    if status.get("is_terminal") or status.get("status") in TERMINAL_RUN:
        return False
    return not is_stuck(status)


def overall_stage(status: dict | None, bots: dict, recon: str) -> str:
    if not status:
        return "Not started"
    run_status = status.get("status")
    if run_status == COMPLETE:
        return "Complete"
    if run_status == PARTIAL:
        return "Partial"
    if run_status == FAILED:
        return "Failed"
    if is_stuck(status):
        return "Interrupted"
    if recon == RUNNING:
        return "Reconciling"
    if any(s in (RUNNING,) + FINISHED for s in bots.values()):
        return "Analyzing"
    return "Preparing"


def progress_text(bots: dict, recon: str) -> str:
    """Counts of real states only -- never a percentage."""
    done = [s for s in bots.values() if s in FINISHED]
    parts = [f"{len(done)} of {len(bots)} specialists finished"]
    running = sum(1 for s in bots.values() if s == RUNNING)
    if running and len(done) < len(bots):
        parts.append(f"{running} working now")
    partial = sum(1 for s in bots.values() if s == PARTIAL)
    failed = sum(1 for s in bots.values() if s == FAILED)
    if partial:
        parts.append(f"{partial} partial")
    if failed:
        parts.append(f"{failed} failed")
    parts.append({
        WAITING: "Reconciliation pending",
        RUNNING: "Reconciliation running",
        COMPLETE: "Reconciliation complete",
        PARTIAL: "Reconciliation partial",
        FAILED: "Reconciliation failed",
        SKIPPED: "Reconciliation not run",
    }.get(recon, "Reconciliation pending"))
    return " · ".join(parts)


def build_view(status: dict | None, rows=None) -> dict:
    rows_map = rows_by_specialist(rows)
    bots = {sid: bot_state(sid, status, rows_map) for sid in SPECIALIST_IDS}
    recon = reconciliation_state(status)
    stuck = is_stuck(status) and not (status or {}).get("is_terminal")
    return {
        "run_id": (status or {}).get("run_id"),
        "run_status": (status or {}).get("status"),
        "bots": bots,
        "reconciliation": recon,
        "stage": overall_stage(status, bots, recon),
        "progress": progress_text(bots, recon),
        "hub_counts": hub_counts(status),
        "stuck": stuck,
        "live": should_poll(status),
        "failure_reason": (status or {}).get("failure_reason"),
    }


def packet_transitions(previous: dict | None, bots: dict) -> list:
    """Specialists that moved INTO a usable finished state since the last
    poll in this browser session. `previous is None` (first render, page
    refresh, reconnect) yields nothing: history is reconstructed, never
    replayed as animation."""
    if previous is None:
        return []
    return [sid for sid in SPECIALIST_IDS
            if bots.get(sid) in USABLE and previous.get(sid) not in USABLE]


def specialist_preview(row: dict | None, limit: int = 2) -> list:
    """Up to `limit` persisted finding titles for a finished specialist
    (highest severity first). Only real persisted findings."""
    result = (row or {}).get("result") or {}
    findings = [f for f in (result.get("findings") or []) if isinstance(f, dict)]
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    findings.sort(key=lambda f: order.get(f.get("severity"), 3))
    return [f.get("title") or f.get("detail") for f in findings[:limit] if (f.get("title") or f.get("detail"))]


# ═══════════════════════════════════════════════════════════════════════
# Constellation HTML
# ═══════════════════════════════════════════════════════════════════════

CSS = """
<style>
.fa-wrap{--fa-ink:#EDEAE3;--fa-mute:#8C8A83;--fa-dim:#4A4955;--fa-line:#23232E;
 --fa-panel:#101019;--fa-brass:#C9A96E;--fa-signal:#6CC4D8;--fa-ok:#7FBF94;
 --fa-warn:#E0A84A;--fa-bad:#D46A5E;
 background:radial-gradient(ellipse at 50% 42%,#15152A 0%,#0C0C14 58%,#0A0A0F 100%);
 border:1px solid var(--fa-line);border-radius:10px;padding:22px 18px 18px;margin:.4rem 0 1rem;
 font-family:'Inter',sans-serif;color:var(--fa-ink);container-type:inline-size}
.fa-head{display:flex;justify-content:space-between;align-items:baseline;gap:12px;flex-wrap:wrap;margin-bottom:14px}
.fa-stage{font-family:'Cormorant Garamond',serif;font-size:1.35rem;color:var(--fa-ink)}
.fa-progress{font-size:.8rem;color:var(--fa-mute)}
.fa-grid{display:grid;grid-template-columns:minmax(150px,1fr) 64px minmax(190px,1.15fr) 64px minmax(150px,1fr);
 grid-template-rows:repeat(3,auto);align-items:center;row-gap:14px}
.fa-bot{display:flex;align-items:center;gap:10px;background:var(--fa-panel);border:1px solid var(--fa-line);
 border-radius:8px;padding:9px 11px;min-height:64px;transition:border-color .4s,opacity .4s}
.fa-col-r .fa-bot{flex-direction:row-reverse;text-align:right}
.fa-bot svg{flex:0 0 38px}
.fa-name{font-size:.8rem;font-weight:600;line-height:1.2}
.fa-st{font-size:.72rem;margin-top:3px;color:var(--fa-mute)}
.fa-st b{display:inline-block;min-width:1em;font-weight:700}
.fa-wire{position:relative;height:2px;background:var(--fa-line);overflow:visible}
.fa-packet{position:absolute;top:-3px;width:8px;height:8px;border-radius:50%;opacity:0}
.fa-l .fa-packet{left:0;animation:fa-flow-r 1.4s ease-in 1 forwards}
.fa-r .fa-packet{right:0;animation:fa-flow-l 1.4s ease-in 1 forwards}
.fa-hub{grid-column:3;grid-row:1/4;align-self:stretch;display:flex;flex-direction:column;justify-content:center;
 align-items:center;text-align:center;border:1px solid #3A3322;border-radius:50%/42%;padding:26px 14px;
 background:radial-gradient(circle at 50% 40%,#1C1A14 0%,#12110E 70%);box-shadow:0 0 34px #C9A96E14 inset}
.fa-hub-t{font-family:'Cormorant Garamond',serif;font-size:1.3rem;color:var(--fa-brass);letter-spacing:.02em}
.fa-hub-s{font-size:.7rem;color:var(--fa-mute);margin:2px 0 10px}
.fa-hub-c{font-size:.72rem;color:var(--fa-ink);line-height:1.55}
.fa-hub-c span{color:var(--fa-brass);font-weight:600}
.fa-recon-row{display:flex;flex-direction:column;align-items:center;margin-top:6px}
.fa-stem{width:2px;height:22px;background:var(--fa-line)}
.fa-recon{display:flex;align-items:center;gap:10px;background:var(--fa-panel);border:1px solid var(--fa-line);
 border-radius:8px;padding:9px 14px;min-width:260px;justify-content:center}
/* state treatments */
.s-WAITING,.s-QUEUED{opacity:.55}
.s-RUNNING{border-color:#2E5963}
.s-RUNNING .fa-st{color:var(--fa-signal)}
.s-COMPLETE{border-color:#2F4A37}.s-COMPLETE .fa-st{color:var(--fa-ok)}
.s-PARTIAL{border-color:#5A4522;border-style:dashed}.s-PARTIAL .fa-st{color:var(--fa-warn)}
.s-FAILED{border-color:#5A2A25}.s-FAILED .fa-st{color:var(--fa-bad)}
.s-SKIPPED{opacity:.45;border-style:dotted}
.w-RUNNING{background:linear-gradient(90deg,transparent,#6CC4D8 50%,transparent);background-size:200% 100%;
 animation:fa-wire 1.8s linear infinite}
.w-COMPLETE{background:#3E6B4B}.w-PARTIAL{background:repeating-linear-gradient(90deg,#8A6A30 0 6px,transparent 6px 10px)}
.w-FAILED{background:#3A1E1B}
.s-RUNNING .fa-eye{animation:fa-scan 2.2s ease-in-out infinite}
.s-RUNNING .fa-ant{animation:fa-blink 1.6s ease-in-out infinite}
.fa-stuck .fa-bot,.fa-stuck .fa-wire,.fa-stuck .fa-eye,.fa-stuck .fa-ant{animation:none!important}
.fa-stuck .w-RUNNING{background:var(--fa-line)}
@keyframes fa-wire{from{background-position:100% 0}to{background-position:-100% 0}}
@keyframes fa-scan{0%,100%{transform:translateX(-1.5px)}50%{transform:translateX(1.5px)}}
@keyframes fa-blink{0%,100%{opacity:.35}50%{opacity:1}}
@keyframes fa-flow-r{0%{left:0;opacity:0}15%{opacity:1}100%{left:calc(100% - 8px);opacity:0}}
@keyframes fa-flow-l{0%{right:0;opacity:0}15%{opacity:1}100%{right:calc(100% - 8px);opacity:0}}
@media (prefers-reduced-motion:reduce){.fa-wrap *{animation:none!important;transition:none!important}
 .fa-packet{display:none}}
/* narrow widths: drop the radial composition, stack cleanly */
@media (max-width:860px){.fa-grid{grid-template-columns:1fr;row-gap:8px}
 .fa-grid>*{grid-column:1!important;grid-row:auto!important}
 .fa-wire{display:none}.fa-hubcell{order:-1}.fa-hub{border-radius:10px;padding:14px}
 .fa-col-r .fa-bot{flex-direction:row;text-align:left}.fa-recon{min-width:0;width:100%}}
@container (max-width:720px){.fa-grid{grid-template-columns:1fr;row-gap:8px}
 .fa-grid>*{grid-column:1!important;grid-row:auto!important}
 .fa-wire{display:none}.fa-hubcell{order:-1}.fa-hub{border-radius:10px;padding:14px}
 .fa-col-r .fa-bot{flex-direction:row;text-align:left}.fa-recon{min-width:0;width:100%}}
.fa-strip{display:flex;flex-wrap:wrap;gap:6px;margin:.3rem 0 .8rem}
.fa-chip{display:inline-flex;align-items:center;gap:6px;font-size:.72rem;padding:4px 9px;border-radius:14px;
 border:1px solid var(--fa-line,#23232E);background:#101019;color:#EDEAE3}
.fa-chip.s-COMPLETE{border-color:#2F4A37}.fa-chip.s-PARTIAL{border-color:#5A4522;border-style:dashed}
.fa-chip.s-FAILED{border-color:#5A2A25}.fa-chip.s-SKIPPED{opacity:.6;border-style:dotted}
.fa-chip b{font-weight:700}
.fa-chip.s-COMPLETE b{color:#7FBF94}.fa-chip.s-PARTIAL b{color:#E0A84A}.fa-chip.s-FAILED b{color:#D46A5E}
.fa-find{border-left:2px solid #2A2A36;padding:.35rem .8rem;margin:.35rem 0}
.fa-find.sev-HIGH{border-left-color:#C9A96E}
.fa-find-t{font-size:.86rem;color:#EDEAE3;font-weight:600}
.fa-find-d{font-size:.8rem;color:#A9A69D;margin-top:2px;line-height:1.5}
.fa-find-m{font-size:.7rem;color:#6E6C66;margin-top:3px}
.fa-tag{display:inline-block;font-size:.66rem;padding:0 6px;border-radius:3px;margin-right:4px;border:1px solid #33323C;color:#A9A69D}
.fa-tag.interp{border-color:#3C3552;color:#A99BD6}.fa-tag.canon{border-color:#3A3322;color:#C9A96E}
.fa-tag.confirm{border-color:#5A4522;color:#E0A84A}
</style>
"""

_EYE = {WAITING: "#4A4955", QUEUED: "#5B5A66", RUNNING: "#6CC4D8", COMPLETE: "#7FBF94",
        PARTIAL: "#E0A84A", FAILED: "#D46A5E", SKIPPED: "#3A3944"}


def bot_svg(state: str, glyph: str) -> str:
    """A small robot: head, two eyes (state colour), antenna light, and a
    two-letter domain mark on the chest plate. Inline SVG, no assets."""
    eye = _EYE.get(state, "#4A4955")
    frame = "#3A3944" if state in (WAITING, QUEUED, SKIPPED) else "#5E5C6A"
    eyes = ('<g class="fa-eye">'
            f'<circle cx="14" cy="15" r="2.4" fill="{eye}"/><circle cx="24" cy="15" r="2.4" fill="{eye}"/></g>')
    if state == FAILED:
        eyes = (f'<g stroke="{eye}" stroke-width="1.6" stroke-linecap="round">'
                '<path d="M12 13l4 4M16 13l-4 4M22 13l4 4M26 13l-4 4"/></g>')
    return (
        '<svg width="38" height="40" viewBox="0 0 38 40" aria-hidden="true">'
        f'<line x1="19" y1="2" x2="19" y2="7" stroke="{frame}" stroke-width="1.4"/>'
        f'<circle class="fa-ant" cx="19" cy="2.5" r="2" fill="{eye}"/>'
        f'<rect x="6" y="7" width="26" height="17" rx="5" fill="#16161F" stroke="{frame}" stroke-width="1.4"/>'
        f'{eyes}'
        f'<rect x="9" y="26" width="20" height="12" rx="3" fill="#16161F" stroke="{frame}" stroke-width="1.2"/>'
        f'<text x="19" y="35" text-anchor="middle" font-size="7" font-family="Inter,sans-serif" '
        f'font-weight="700" fill="{eye}">{esc(glyph)}</text></svg>')


def _bot_html(sid: str, state: str, glyph: str) -> str:
    label = STATE_LABEL.get(state, state)
    return (f'<div class="fa-bot s-{state}" role="group" aria-label="{esc(SPECIALIST_NAME[sid])}: {esc(label)}" '
            f'data-specialist="{sid}" data-state="{state}">{bot_svg(state, glyph)}'
            f'<div><div class="fa-name">{esc(SPECIALIST_NAME[sid])}</div>'
            f'<div class="fa-st"><b>{STATE_MARK.get(state, "")}</b> {esc(label)}</div></div></div>')


def _wire_html(side: str, state: str, packet: bool) -> str:
    colour = "#E0A84A" if state == PARTIAL else "#7FBF94"
    pk = (f'<div class="fa-packet" data-packet="1" style="background:{colour};'
          f'box-shadow:0 0 8px {colour}"></div>') if packet else ""
    return f'<div class="fa-wire fa-{side} w-{state}">{pk}</div>'


def render_constellation(view: dict, packets=()) -> str:
    """The live multi-agent view. Deterministic for a given (view,
    packets): identical input -> identical HTML, so an unchanged poll does
    not remount the DOM or restart animations."""
    packets = set(packets or ())
    bots = view["bots"]
    cells = []
    for i, (sid, _name, glyph) in enumerate(SPECIALISTS):
        left = i < 3
        row = (i % 3) + 1
        state = bots[sid]
        bot_col, wire_col = (1, 2) if left else (5, 4)
        cells.append(f'<div class="{"fa-col-l" if left else "fa-col-r"}" '
                     f'style="grid-column:{bot_col};grid-row:{row}">{_bot_html(sid, state, glyph)}</div>')
        cells.append(f'<div style="grid-column:{wire_col};grid-row:{row}">'
                     f'{_wire_html("l" if left else "r", state, sid in packets)}</div>')
    counts = "".join(f'<div><span>{n}</span> {esc(label)}</div>' for n, label in view.get("hub_counts") or [])
    hub = ('<div class="fa-hub"><div class="fa-hub-t">Shared Truth</div>'
           '<div class="fa-hub-s">Canonical bid intelligence every specialist reads from</div>'
           f'<div class="fa-hub-c">{counts or "Canonical package preparing"}</div></div>')
    recon = view["reconciliation"]
    recon_label = {WAITING: "Waiting for specialists", RUNNING: "Reconciling specialist outputs",
                   COMPLETE: "Complete", PARTIAL: "Partial output", FAILED: "Failed",
                   SKIPPED: "Not run"}.get(recon, recon)
    recon_html = ('<div class="fa-recon-row"><div class="fa-stem w-' + recon + '"></div>'
                  f'<div class="fa-recon s-{recon}" data-state="{recon}" role="group" '
                  f'aria-label="Reconciliation and Assurance: {esc(recon_label)}">'
                  f'{bot_svg(recon, "RA")}<div><div class="fa-name">Reconciliation &amp; Assurance</div>'
                  f'<div class="fa-st"><b>{STATE_MARK.get(recon, "")}</b> {esc(recon_label)}</div></div></div></div>')
    wrap_cls = "fa-wrap fa-stuck" if view.get("stuck") or not view.get("live") else "fa-wrap"
    stage = "Analysis interrupted" if view.get("stuck") else view["stage"]
    return (CSS + f'<div class="{wrap_cls}" data-stage="{esc(view["stage"])}">'
            f'<div class="fa-head"><div class="fa-stage">{esc(stage)}</div>'
            f'<div class="fa-progress" aria-live="polite">{esc(view["progress"])}</div></div>'
            f'<div class="fa-grid">{"".join(cells)}'
            f'<div class="fa-hubcell" style="grid-column:3;grid-row:1/4">{hub}</div></div>{recon_html}</div>')


def render_strip(bots: dict, recon: str) -> str:
    """Compact, static specialist status row for the completed view."""
    chips = [f'<span class="fa-chip s-{st}" title="{esc(STATE_LABEL.get(st, st))}">'
             f'<b>{STATE_MARK.get(st, "")}</b>{esc(SPECIALIST_NAME[sid])}</span>'
             for sid, st in bots.items()]
    chips.append(f'<span class="fa-chip s-{recon}"><b>{STATE_MARK.get(recon, "")}</b>Reconciliation</span>')
    return CSS + '<div class="fa-strip">' + "".join(chips) + "</div>"


# ═══════════════════════════════════════════════════════════════════════
# Completed result grouping (persisted FullAnalysisResult only)
# ═══════════════════════════════════════════════════════════════════════

RESULT_SECTIONS = (
    ("PROCUREMENT_STRUCTURE", "Executive Intelligence",
     "Opportunity structure and the decisions it implies."),
    ("REQUIREMENTS_COMPLIANCE", "Requirements & Compliance",
     "Gates, category qualifications and submission obligations."),
    ("EVALUATION_INTELLIGENCE", "Evaluation Intelligence",
     "Weighted criteria, evidence expectations and response priorities."),
    ("SCOPE_DELIVERABLES", "Scope & Delivery",
     "Workstreams, resourcing and delivery complexity."),
    ("COMMERCIAL_CONTRACTUAL", "Commercial & Contractual",
     "Material exposures, constraints and bidder decisions."),
    ("SCHEDULE_SUBMISSION", "Schedule & Submission",
     "Deadlines, category milestones and timing dependencies."),
)
_SEV = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}


def _findings_from_rows(rows) -> list:
    out = []
    for row in rows or []:
        for f in ((row.get("result") or {}).get("findings") or []):
            if isinstance(f, dict):
                out.append(f)
    return out


def group_result(result: dict | None, rows=None) -> dict:
    """Group reconciled findings by their FIRST producing specialist (a
    merged finding is shown once, with its other producers noted).
    Falls back to the persisted specialist rows' own findings when the run
    has no reconciled output (e.g. FAILED reconciliation / FAILED run)."""
    result = result or {}
    findings = [f for f in (result.get("reconciled_findings") or []) if isinstance(f, dict)]
    if not findings:
        findings = _findings_from_rows(rows)
    by_domain = {sid: [] for sid in SPECIALIST_IDS}
    for f in findings:
        producers = [p for p in (f.get("produced_by") or []) if p in by_domain]
        if producers:
            by_domain[producers[0]].append(f)
    for sid in by_domain:
        by_domain[sid].sort(key=lambda f: (_SEV.get(f.get("severity"), 3), str(f.get("title"))))
    return {
        "domains": by_domain,
        "cross_domain_risks": list(result.get("cross_domain_risks") or []),
        "gaps": list(result.get("unresolved_gaps") or []),
        "ambiguities": list(result.get("ambiguities") or []),
        "human_confirmation": list(result.get("human_confirmation_required") or []),
        "completeness": result.get("completeness_status"),
        "completeness_note": (result.get("reconciliation") or {}).get("completeness_note") or "",
    }


def incomplete_domain_messages(bots: dict, recon: str) -> list:
    msgs = []
    for sid, st in bots.items():
        name = SPECIALIST_NAME[sid]
        if st == PARTIAL:
            msgs.append(f"{name} returned partial output. Its preserved findings are shown, but this domain is incomplete.")
        elif st == FAILED:
            msgs.append(f"{name} failed. This domain was not analyzed.")
        elif st == SKIPPED:
            msgs.append(f"{name} did not run. This domain was not analyzed.")
    if recon == PARTIAL:
        msgs.append("Reconciliation & Assurance returned partial output. Cross-domain checks may be incomplete.")
    elif recon == FAILED:
        msgs.append("Reconciliation & Assurance failed. Specialist findings are preserved, but cross-domain reconciliation is missing.")
    elif recon == SKIPPED:
        msgs.append("Reconciliation & Assurance did not run.")
    return msgs


def finding_html(f: dict, *, primary: str | None = None) -> str:
    sev = f.get("severity") or "MEDIUM"
    tags = []
    auth = f.get("authority")
    if auth == "CANONICAL":
        tags.append('<span class="fa-tag canon">Canonical fact</span>')
    elif auth:
        tags.append('<span class="fa-tag interp">Specialist interpretation</span>')
    if f.get("human_confirmation_required"):
        tags.append('<span class="fa-tag confirm">Needs confirmation</span>')
    if f.get("category_scope"):
        tags.append(f'<span class="fa-tag">{esc(f["category_scope"])}</span>')
    others = [SPECIALIST_NAME.get(p, p) for p in (f.get("produced_by") or f.get("domains") or [])
              if p != primary and p in SPECIALIST_NAME]
    also = f' Also raised by {esc(", ".join(others))}.' if others else ""
    return (f'<div class="fa-find sev-{esc(sev)}"><div class="fa-find-t">{esc(f.get("title") or "Untitled finding")}</div>'
            f'<div class="fa-find-d">{esc(f.get("detail") or "")}</div>'
            f'<div class="fa-find-m"><span class="fa-tag">{esc(sev.title())}</span>{"".join(tags)}{also}</div></div>')


def trace_rows(findings: list) -> list:
    """[(title, [canonical ids], [finding ids])] for the traceability
    expander -- only items that actually carry references."""
    out = []
    for f in findings:
        cids = [str(c) for c in (f.get("canonical_ids") or [])]
        fids = [str(c) for c in (f.get("finding_ids") or [])]
        if cids or fids:
            out.append((f.get("title") or "Untitled", cids, fids))
    return out
