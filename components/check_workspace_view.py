"""
components/check_workspace_view.py -- CHECK-2C presentation adapter for the
client-facing Proposal Assurance workspace.

PURE: no Streamlit, no database, no model/provider access, and no import of
check_coverage.py / check_run_service.py (the status vocabulary below is
duplicated as plain strings, exactly like components/full_analysis_view.py
does for MA-2A, and a test pins it to check_coverage's constants). It turns
what the durable CHECK service already persisted into:

  * a factual overview (status counts -- never a score, a percentage, a
    readiness figure or a predicted evaluator mark);
  * a deterministic attention ordering built only from buyer metadata and
    the persisted CHECK status (see ATTENTION_ORDERING);
  * evaluation-criterion cards, requirement rows and a side-by-side
    "what the buyer asked for / what the bidder submitted" detail view;
  * bounded evidence rendering from the bid's own persisted CHECK-1
    evidence registry (filename, role, page/section/sheet/cell/row/field
    locator, a clipped excerpt) -- never a whole document, never a
    fabricated snippet: an evidence id that does not resolve inside THIS
    bid's registry is shown as unresolved, never invented.

Every string that reaches HTML goes through esc().
"""
from __future__ import annotations

import html
import re
from datetime import datetime, timezone

# ─── closed vocabularies (mirror check_coverage / check_run_service) ───
ADDRESSED = "ADDRESSED"
PARTIAL = "PARTIALLY_ADDRESSED"
NOT_ADDRESSED = "NOT_ADDRESSED"
NOT_APPLICABLE = "NOT_APPLICABLE"
NOT_VERIFIABLE = "NOT_VERIFIABLE_FROM_FILES"
HUMAN_REVIEW = "HUMAN_REVIEW_REQUIRED"
STATUSES = (ADDRESSED, PARTIAL, NOT_ADDRESSED, NOT_APPLICABLE, NOT_VERIFIABLE, HUMAN_REVIEW)
#: The five assurance outcomes shown as counts (NOT_APPLICABLE is shown
#: separately and subtly: it is never a proposal deficiency).
PRIMARY_STATUSES = (ADDRESSED, PARTIAL, NOT_ADDRESSED, NOT_VERIFIABLE, HUMAN_REVIEW)
ATTENTION_STATUSES = (NOT_ADDRESSED, PARTIAL, HUMAN_REVIEW, NOT_VERIFIABLE)

OBJECT_REQUIREMENT = "CANONICAL_REQUIREMENT"
OBJECT_CRITERION = "SCOPED_EVALUATION_CRITERION"

RUN_COMPLETE, RUN_PARTIAL, RUN_FAILED, RUN_RUNNING, RUN_QUEUED = (
    "COMPLETE", "PARTIAL", "FAILED", "RUNNING", "QUEUED")
TERMINAL_RUN = (RUN_COMPLETE, RUN_PARTIAL, RUN_FAILED)

#: Status presentation. Every state carries a text label AND a mark, so
#: nothing depends on colour alone.
STATUS_META = {
    ADDRESSED: {"label": "Addressed", "mark": "✓", "tone": "ok"},
    PARTIAL: {"label": "Partially addressed", "mark": "◐", "tone": "partial"},
    NOT_ADDRESSED: {"label": "Not addressed", "mark": "✕", "tone": "gap"},
    NOT_VERIFIABLE: {"label": "Not verifiable from files", "mark": "?", "tone": "unverifiable"},
    HUMAN_REVIEW: {"label": "Human review required", "mark": "◆", "tone": "review"},
    NOT_APPLICABLE: {"label": "Non-submission / informational", "mark": "–", "tone": "na"},
}
#: One-line meaning of each status, in the customer's language.
STATUS_MEANING = {
    ADDRESSED: "The submitted files demonstrate what the buyer asked for.",
    PARTIAL: "Some of what the buyer asked for is demonstrated; some is not.",
    NOT_ADDRESSED: "The whole package was searched and no response was found.",
    NOT_VERIFIABLE: "Cannot be verified from the submitted files. This is an assurance limit, not a gap.",
    HUMAN_REVIEW: "CHECK cannot safely determine coverage. A person should confirm it.",
    NOT_APPLICABLE: "Not a proposal obligation (buyer process, post-award, informational or deemed by submission).",
}
#: Status priority used for attention ordering and the criteria list.
STATUS_PRIORITY = {NOT_ADDRESSED: 0, PARTIAL: 1, HUMAN_REVIEW: 2, NOT_VERIFIABLE: 3, ADDRESSED: 4, NOT_APPLICABLE: 5}

SCOPE_LABEL = {
    "SUBMISSION_RESPONSE_REQUIRED": "Response required in the submission",
    "SUBMISSION_EVIDENCE_REQUIRED": "Evidence required in the submission",
    "EVALUATION_RESPONSE": "Evaluated response",
    "PORTAL_NATIVE": "Answered in the buyer's portal",
    "POST_AWARD_OBLIGATION": "Post-award obligation",
    "BUYER_PROCESS": "Buyer process",
    "INFORMATIONAL": "Informational",
    "DEEMED_BY_SUBMISSION": "Deemed by the act of submitting",
    "NOT_APPLICABLE": "Not applicable",
    "HUMAN_REVIEW_REQUIRED": "Scope needs human review",
}
ROLE_LABEL = {
    "TECHNICAL_PROPOSAL": "Technical proposal", "PRICING_FORM": "Pricing form",
    "SUBMISSION_FORM": "Submission form", "MULTI_PARTY_FORM": "Multi-party form",
    "SOCIAL_PROCUREMENT_RESPONSE": "Social procurement response", "CERTIFICATE": "Certificate",
    "EVIDENCE_ATTACHMENT": "Evidence attachment", "RESUME": "Résumé",
    "ORGANIZATION_CHART": "Organization chart", "SUPPORTING_DOCUMENT": "Supporting document",
    "UNKNOWN": "Unclassified",
}
METHOD_LABEL = {
    "SCOPE_GATE": "Scope rule (no adjudication needed)",
    "DETERMINISTIC": "Deterministic check of the submitted files",
    "MODEL": "Bounded model adjudication, evidence-validated",
    "DERIVED_FROM_LINKED_REQUIREMENTS": "Derived from the linked requirements",
}
KIND_LABEL = {
    "SECTION_TEXT": "Text", "TABLE_ROW": "Table row", "FORM_FIELD": "Form field", "CHECKBOX": "Checkbox",
    "SHEET_ROW": "Worksheet row", "SHEET_CELL": "Worksheet cell",
}
ELEMENT_COVERAGE_LABEL = {
    "ADDRESSED": "Demonstrated", "PARTIAL": "Only partly demonstrated", "ABSENT": "Not found in the submitted files",
    "NOT_VERIFIABLE": "Cannot be verified from files", "HUMAN_REVIEW": "Needs human review",
    "NON_OBLIGATION": "Not an obligation",
}

#: Documented, deterministic attention ordering (section 6). No hidden risk
#: score, no model severity: items in ATTENTION_STATUSES sorted by
#:   1. evaluation criteria before ordinary requirements
#:   2. highest buyer-stated weight (largest of the stated weight variants)
#:   3. a stated minimum threshold before none
#:   4. mandatory / submission-wide before other requirements
#:   5. status: NOT_ADDRESSED, PARTIALLY_ADDRESSED, HUMAN_REVIEW_REQUIRED,
#:      NOT_VERIFIABLE_FROM_FILES
#:   6. the persisted adjudication order (stable tie-break)
ATTENTION_ORDERING = (
    "evaluation criteria before requirements",
    "higher buyer-stated weight first",
    "stated minimum threshold first",
    "mandatory / submission-wide first",
    "status: not addressed, partially addressed, human review, not verifiable",
    "persisted order",
)

EXCERPT_CHARS = 420
EXPECTATION_CHARS = 320
MAX_EVIDENCE_SHOWN = 6

START_OUTCOME_NOTES = {
    "CREATED": ("info", "CHECK started for the current buyer package and submission. The result appears here when it finishes."),
    "ACTIVE_RUN_EXISTS": ("info", "A CHECK run is already in progress for this bid. Showing its progress."),
    "REUSED_COMPLETE": ("ok", "Nothing has changed since the last complete CHECK. The existing result is shown; no new analysis was run."),
    "EXISTING_FAILED": ("warn", "The last CHECK for these exact inputs failed. It was not re-run automatically."),
    "EXISTING_PARTIAL": ("caution", "The last CHECK for these exact inputs is partial. It is shown below and was not re-run automatically."),
}


def esc(value) -> str:
    """HTML-escape. Newlines become character references (a literal blank
    line would end Streamlit's markdown HTML block) and '$' is escaped so
    prices never trigger Streamlit's math rendering."""
    out = html.escape(str(value if value is not None else ""), quote=True)
    return out.replace("\r", "").replace("\n", "&#10;").replace("$", "&#36;")


def clip(text, n: int) -> str:
    body = re.sub(r"\s+", " ", str(text or "")).strip()
    return body if len(body) <= n else body[:n].rstrip() + "…"


def adj_dict(a) -> dict:
    """A CheckAdjudication (or an already-dict adjudication) as a dict."""
    return a.to_dict() if hasattr(a, "to_dict") else dict(a)


def adjudications(result) -> list:
    """Persisted order, as dicts, each tagged with its 0-based ordinal."""
    items = getattr(result, "adjudications", None)
    if items is None and isinstance(result, dict):
        items = result.get("adjudications")
    out = []
    for i, a in enumerate(items or []):
        d = adj_dict(a)
        d["_ordinal"] = i
        out.append(d)
    return out


# ═══════════════════════════════════════════════════════════════════════
# Facts about one buyer object
# ═══════════════════════════════════════════════════════════════════════

def is_criterion(a: dict) -> bool:
    return a.get("buyer_object_type") == OBJECT_CRITERION


def is_mandatory(a: dict) -> bool:
    return (str(a.get("buyer_category") or "").lower() == "mandatory"
            or a.get("applicability") == "SUBMISSION_WIDE")


def parse_percent(value):
    """'30%' -> 30.0. Used ONLY to order by a buyer-stated weight; the
    stated text itself is what is displayed."""
    m = re.search(r"(\d+(?:\.\d+)?)", str(value or ""))
    return float(m.group(1)) if m else None


def stated_weights(a: dict) -> list:
    out = []
    for w in [a.get("buyer_weight")] + list(a.get("buyer_weight_variants") or []):
        if w and w not in out:
            out.append(str(w))
    return out


def max_weight(a: dict):
    vals = [v for v in (parse_percent(w) for w in stated_weights(a)) if v is not None]
    return max(vals) if vals else None


def display_name(a: dict) -> str:
    if is_criterion(a) and a.get("buyer_label"):
        return str(a["buyer_label"])
    return f'{a.get("buyer_object_id")}: {clip(a.get("buyer_expectation"), 110) or "(no buyer wording)"}'


def concise_expectation(a: dict, n: int = EXPECTATION_CHARS) -> str:
    """What the buyer asked for, clipped. A derived criterion's persisted
    expectation is 'label\\n[REQ-x] wording ...': the label line is dropped
    (it is already the card title), the linked wording is kept verbatim."""
    text = str(a.get("buyer_expectation") or "")
    label = str(a.get("buyer_label") or "")
    lines = text.split("\n")
    if is_criterion(a) and len(lines) > 1 and lines[0].strip() == label.strip():
        text = " ".join(lines[1:])
    return clip(text, n)


def review_notes(a: dict) -> list:
    """The persisted ambiguity / review reason, split into its recorded
    segments (verbatim, nothing dropped or rephrased)."""
    reason = a.get("ambiguity_or_review_reason") or ""
    return [s.strip() for s in str(reason).split(" | ") if s.strip()]


def element_groups(a: dict) -> dict:
    """{'demonstrated': [...], 'not_demonstrated': [...], 'unverifiable': [...]}
    straight from the persisted element lists."""
    return {"demonstrated": list(a.get("addressed_elements") or []),
            "not_demonstrated": list(a.get("missing_elements") or []),
            "unverifiable": list(a.get("unverifiable_elements") or [])}


def fact_chips(a: dict) -> list:
    """Factual buyer metadata worth surfacing next to a finding."""
    chips = []
    if is_criterion(a):
        chips.append("Evaluation criterion")
    weights = stated_weights(a)
    if weights:
        chips.append("Buyer weight " + " / ".join(weights))
    if a.get("buyer_threshold"):
        chips.append(f"Minimum threshold {a['buyer_threshold']}")
    if is_mandatory(a):
        chips.append("Submission-wide" if a.get("applicability") == "SUBMISSION_WIDE" else "Mandatory")
    return chips


# ═══════════════════════════════════════════════════════════════════════
# Overview / attention / criteria / requirements
# ═══════════════════════════════════════════════════════════════════════

def status_counts(adjs: list) -> dict:
    counts = {s: 0 for s in STATUSES}
    for a in adjs:
        if a.get("status") in counts:
            counts[a["status"]] += 1
    return counts


def overview(adjs: list) -> dict:
    counts = status_counts(adjs)
    return {"counts": [(s, counts[s]) for s in PRIMARY_STATUSES],
            "excluded": counts[NOT_APPLICABLE], "total": len(adjs),
            "criteria": sum(1 for a in adjs if is_criterion(a)),
            "requirements": sum(1 for a in adjs if not is_criterion(a))}


def attention_key(a: dict) -> tuple:
    w = max_weight(a)
    return (0 if is_criterion(a) else 1,
            -(w if w is not None else -1.0),
            0 if a.get("buyer_threshold") else 1,
            0 if is_mandatory(a) else 1,
            STATUS_PRIORITY.get(a.get("status"), 9),
            a.get("_ordinal", 0))


def attention_items(adjs: list, limit: int | None = None) -> list:
    items = sorted((a for a in adjs if a.get("status") in ATTENTION_STATUSES), key=attention_key)
    return items[:limit] if limit else items


def criteria(adjs: list) -> list:
    """Every scoped evaluation criterion, attention-first: status priority,
    then buyer-stated weight, then persisted order."""
    crits = [a for a in adjs if is_criterion(a)]
    return sorted(crits, key=lambda a: (STATUS_PRIORITY.get(a.get("status"), 9),
                                        -(max_weight(a) if max_weight(a) is not None else -1.0),
                                        a.get("_ordinal", 0)))


def submission_requirements(adjs: list) -> list:
    return [a for a in adjs if not is_criterion(a) and a.get("status") != NOT_APPLICABLE]


def non_submission(adjs: list) -> list:
    return [a for a in adjs if a.get("status") == NOT_APPLICABLE]


def filter_options(adjs: list) -> dict:
    roles = sorted({r for a in adjs for r in (a.get("expected_evidence_roles") or [])})
    return {"statuses": [s for s in STATUSES if any(a.get("status") == s for a in adjs)],
            "scopes": sorted({a.get("assurance_scope") for a in adjs if a.get("assurance_scope")}),
            "roles": roles}


def filter_findings(adjs: list, *, statuses=None, object_types=None, scopes=None, roles=None,
                    mandatory_only: bool = False) -> list:
    """Pure filter; an empty/None selector means 'no restriction'."""
    out = []
    for a in adjs:
        if statuses and a.get("status") not in statuses:
            continue
        if object_types and a.get("buyer_object_type") not in object_types:
            continue
        if scopes and a.get("assurance_scope") not in scopes:
            continue
        if roles and not (set(roles) & set(a.get("expected_evidence_roles") or [])):
            continue
        if mandatory_only and not is_mandatory(a):
            continue
        out.append(a)
    return sorted(out, key=lambda a: (STATUS_PRIORITY.get(a.get("status"), 9), a.get("_ordinal", 0)))


# ═══════════════════════════════════════════════════════════════════════
# Evidence (bidder side) -- resolved only inside THIS bid's registry
# ═══════════════════════════════════════════════════════════════════════

def cited_evidence_ids(a: dict) -> list:
    """Verdict-level ids first, then element-level ids, de-duplicated."""
    out = []
    for eid in a.get("evidence_ids") or []:
        if eid not in out:
            out.append(eid)
    for group in ("addressed_elements", "missing_elements", "unverifiable_elements"):
        for el in a.get(group) or []:
            for eid in (el or {}).get("evidence_ids") or []:
                if eid not in out:
                    out.append(eid)
    return out


def _location_parts(loc: dict, kind: str | None, sv: dict | None) -> list:
    loc = loc or {}
    parts = []
    if loc.get("page") is not None:
        parts.append(f"Page {loc['page']}")
    if loc.get("section_title"):
        num, title = loc.get("section_number"), loc["section_title"]
        parts.append(f"Section {num} {title}" if num and num not in title else f"Section {title}")
    if loc.get("sheet"):
        parts.append(f"Sheet {loc['sheet']}")
    if loc.get("cell"):
        parts.append(f"Cell {loc['cell']}")
    elif loc.get("row") is not None:
        parts.append(f"Row {loc['row']}")
    if loc.get("table_index") is not None:
        parts.append(f"Table {int(loc['table_index']) + 1}, row {loc.get('row_index')}")
    if kind in ("FORM_FIELD", "CHECKBOX", "SHEET_CELL") and (sv or {}).get("label"):
        parts.append(f"Field “{clip(sv['label'], 70)}”")
    return parts


def evidence_view(item, filename: str | None, logical_artifact_id: str | None = None) -> dict:
    """Bounded display record for one registry item (duck-typed EvidenceItem)."""
    sv = item.structured_value if isinstance(item.structured_value, dict) else None
    value = None
    if sv and sv.get("value") not in (None, ""):
        value = clip(sv.get("value"), EXCERPT_CHARS)
    return {"evidence_id": item.evidence_id, "bid_id": item.bid_id,
            "filename": filename or (item.provenance or {}).get("filename") or "(unnamed file)",
            "logical_artifact_id": logical_artifact_id or (item.provenance or {}).get("logical_artifact_id"),
            "document_role": item.document_role, "role_label": ROLE_LABEL.get(item.document_role, item.document_role),
            "kind": item.kind, "kind_label": KIND_LABEL.get(item.kind, item.kind),
            "location": _location_parts(item.location, item.kind, sv),
            "field_label": clip(sv.get("label"), 140) if sv and sv.get("label") else None,
            "value": value, "excerpt": clip(item.content, EXCERPT_CHARS)}


def build_evidence_index(package, bid_id: int, evidence_ids) -> dict:
    """{evidence_id: evidence_view} for the requested ids that resolve in the
    package's registry FOR THIS BID. A foreign-bid package, or an id the
    registry does not hold, is simply absent -- never fabricated."""
    if package is None or int(getattr(package, "bid_id", -1)) != int(bid_id):
        return {}
    docs = {}
    for d in getattr(package, "documents", ()) or ():
        docs[d.submission_document_id] = d
    out = {}
    for eid in evidence_ids:
        if eid in out:
            continue
        try:
            item = package.registry.get(eid, bid_id=int(bid_id))
        except Exception:
            continue
        if int(item.bid_id) != int(bid_id):
            continue
        doc = docs.get(item.submission_document_id)
        out[eid] = evidence_view(item, getattr(doc, "filename", None),
                                 getattr(doc, "logical_artifact_id", None) if doc else None)
    return out


def submitted_files(package) -> list:
    """Authoritative submitted artifacts (one per logical artifact)."""
    if package is None:
        return []
    return [{"filename": d.filename, "role": d.document_role,
             "role_label": ROLE_LABEL.get(d.document_role, d.document_role),
             "file_type": d.file_type, "page_count": d.page_count, "sheets": list(d.sheets or ()),
             "evidence_count": d.evidence_count}
            for d in package.member_documents()]


def strongest_evidence(a: dict, index: dict):
    for eid in a.get("evidence_ids") or []:
        if eid in index:
            return index[eid]
    return None


# ═══════════════════════════════════════════════════════════════════════
# Run header
# ═══════════════════════════════════════════════════════════════════════

def format_ts(value) -> str:
    if not value:
        return "—"
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if ts.tzinfo is not None:
            ts = ts.astimezone(timezone.utc)
        return ts.strftime("%d %b %Y, %H:%M UTC")
    except Exception:
        return str(value)


def run_view(status: dict | None) -> dict:
    """Truthful run header from the DURABLE run status (never inferred from
    the presence of result rows)."""
    s = status or {}
    run_status = s.get("status")
    tone = {RUN_COMPLETE: "ok", RUN_PARTIAL: "caution", RUN_FAILED: "gap"}.get(run_status, "info")
    label = {RUN_COMPLETE: "Complete", RUN_PARTIAL: "Partial", RUN_FAILED: "Failed",
             RUN_RUNNING: "Running", RUN_QUEUED: "Queued"}.get(run_status, str(run_status or "Unknown"))
    when = s.get("completed_at") or s.get("failed_at") or s.get("started_at") or s.get("created_at")
    return {"run_id": s.get("run_id"), "status": run_status, "label": label, "tone": tone,
            "when": format_ts(when), "is_terminal": run_status in TERMINAL_RUN,
            "source_analysis_run_id": s.get("source_analysis_run_id"),
            "package_snapshot_id": s.get("source_package_snapshot_id"),
            "failure_reason": s.get("failure_reason"),
            "stuck": bool(((s.get("stuck") or {}).get("stuck")))}


def partial_disclosure(status: dict | None, result_payload: dict | None) -> list:
    """For a PARTIAL run: which semantic stages did not complete (persisted)."""
    lines = []
    batches = (result_payload or {}).get("semantic_batches") or []
    for b in batches:
        if b.get("effective_status") != "COMPLETE":
            lines.append(f"Semantic batch {b.get('batch_id')} is {b.get('effective_status')}"
                         + (f": {b.get('failure_reason')}" if b.get("failure_reason") else ""))
    if not lines and (status or {}).get("failure_reason"):
        lines.append(str(status["failure_reason"]))
    return lines


def progress_text(status: dict | None) -> str:
    p = (status or {}).get("progress") or {}
    total, done = p.get("semantic_batches_total"), p.get("semantic_batches_complete") or 0
    if total:
        return f"{done} of {total} semantic batches complete"
    return "Preparing buyer objects and submission evidence"


def rerun_cta(run_status: str | None) -> dict:
    """Explicit CHECK execution only. COMPLETE reuses the durable result when
    nothing changed (REUSED_COMPLETE, zero model calls); PARTIAL / FAILED
    need an explicit, labelled retry that states its cost."""
    if run_status == RUN_COMPLETE:
        return {"label": "Run CHECK again", "retry": False,
                "caption": ("Re-checks the current buyer package and submission. If nothing has changed, this "
                            "result is reused and no new analysis runs. If inputs changed, a new CHECK run starts "
                            "(at most 12 bounded model calls).")}
    return {"label": "Run CHECK again for these inputs", "retry": True,
            "caption": ("Starts a fresh CHECK run for the current inputs (at most 12 bounded model calls). "
                        "Nothing runs unless you click.")}


# ═══════════════════════════════════════════════════════════════════════
# HTML
# ═══════════════════════════════════════════════════════════════════════

CSS = """
<style>
.ck{--ink:#EDEAE3;--mute:#9C998F;--dim:#6E6C66;--line:#262631;--panel:#111118;--panel2:#0E0E15;
 --buyer:#C9A96E;--bidder:#8FB3D1;--ok:#7FBF94;--partial:#E0A84A;--gap:#D46A5E;--unv:#8C9BB5;--review:#B39DDB;
 font-family:'Inter',sans-serif;color:var(--ink)}
.ck *{box-sizing:border-box}
.ck-kicker{font-size:.74rem;color:var(--buyer);letter-spacing:.04em;font-weight:600;margin-bottom:.25rem}
.ck-title{font-family:'Cormorant Garamond',serif;font-size:2.1rem;line-height:1.08;margin:0}
.ck-sub{font-size:.95rem;color:var(--mute);margin:.35rem 0 .9rem;max-width:72ch;line-height:1.45}
.ck-meta{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:0;border:1px solid var(--line);
 border-radius:6px;background:var(--panel);margin:.2rem 0 1rem}
.ck-meta div{padding:.55rem .85rem;border-right:1px solid var(--line)}
.ck-meta div:last-child{border-right:none}
.ck-meta dt{font-size:.68rem;color:var(--dim);margin:0}
.ck-meta dd{font-size:.86rem;margin:.1rem 0 0;color:var(--ink)}
.ck-banner{border-left:3px solid var(--unv);background:var(--panel);padding:.6rem .95rem;border-radius:0 5px 5px 0;
 font-size:.85rem;line-height:1.5;margin:.5rem 0 1rem;color:var(--ink)}
.ck-banner b.m{margin-right:.45rem}
.ck-banner.t-ok{border-color:var(--ok)}.ck-banner.t-caution{border-color:var(--partial)}
.ck-banner.t-gap{border-color:var(--gap)}.ck-banner.t-warn{border-color:var(--gap)}
.ck-counts{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));border:1px solid var(--line);border-radius:6px;
 overflow:hidden;background:var(--panel)}
.ck-count{padding:.8rem .9rem;border-right:1px solid var(--line);position:relative}
.ck-count:last-child{border-right:none}
.ck-count::before{content:"";position:absolute;left:0;top:0;right:0;height:3px;background:var(--c)}
.ck-count .n{font-family:'Inter',sans-serif;font-weight:300;font-size:1.9rem;line-height:1;color:var(--ink);
 font-variant-numeric:lining-nums tabular-nums}
.ck-count .l{font-size:.78rem;color:var(--mute);margin-top:.3rem;display:flex;gap:.35rem;align-items:baseline}
.ck-count .l b{color:var(--c);font-weight:700}
.ck-count.zero .n{color:var(--dim)}
.ck-excluded{font-size:.8rem;color:var(--dim);margin:.55rem 0 1.4rem}
.ck-h{font-family:'Cormorant Garamond',serif;font-size:1.45rem;margin:1.2rem 0 .15rem;color:var(--ink)}
.ck-hn{font-size:.82rem;color:var(--mute);margin:0 0 .7rem;max-width:80ch;line-height:1.5}
.ck-pill{display:inline-flex;gap:.35rem;align-items:center;font-size:.74rem;font-weight:600;padding:.12rem .5rem;
 border-radius:3px;border:1px solid var(--c);color:var(--c);white-space:nowrap}
.ck-chip{display:inline-block;font-size:.72rem;color:var(--buyer);border:1px solid #3A3322;border-radius:3px;
 padding:.08rem .45rem;margin:.15rem .3rem 0 0;white-space:nowrap}
.ck-att{border:1px solid var(--line);border-radius:6px;background:var(--panel);margin-bottom:.4rem}
.ck-att-row{display:grid;grid-template-columns:2.2rem minmax(0,1fr);gap:.6rem;padding:.6rem .9rem;border-bottom:1px solid var(--line)}
.ck-att-row:last-child{border-bottom:none}
.ck-att-m{font-size:1.05rem;color:var(--c);text-align:center;padding-top:.05rem}
.ck-att-t{font-size:.9rem;font-weight:600;line-height:1.35}
.ck-att-d{font-size:.8rem;color:var(--mute);margin-top:.2rem;line-height:1.45}
.ck-card{border:1px solid var(--line);border-left:3px solid var(--c);border-radius:0 6px 6px 0;background:var(--panel);
 padding:.85rem 1rem .9rem;margin:.75rem 0 .2rem}
.ck-card.t-ok{padding:.55rem 1rem}
.ck-card-h{display:flex;justify-content:space-between;gap:.8rem;align-items:flex-start;flex-wrap:wrap}
.ck-card-t{font-family:'Cormorant Garamond',serif;font-size:1.22rem;line-height:1.2;max-width:70ch}
.ck-card.t-ok .ck-card-t{font-size:1.08rem}
.ck-ask{font-size:.84rem;color:var(--ink);opacity:.86;line-height:1.55;margin:.45rem 0 0;max-width:95ch}
.ck-ask::before{content:"Buyer asked: ";color:var(--buyer);font-weight:600}
.ck-split{display:grid;grid-template-columns:1fr 1fr;gap:.8rem;margin-top:.7rem}
.ck-col h5{font-size:.76rem;font-weight:600;margin:0 0 .3rem;color:var(--c)}
.ck-col ul{margin:0;padding-left:1.05rem}
.ck-col li{font-size:.82rem;line-height:1.45;margin:.18rem 0;color:var(--ink)}
.ck-col li small{color:var(--mute)}
.ck-note{font-size:.8rem;color:var(--mute);margin-top:.55rem;line-height:1.5}
.ck-note b{color:var(--ink);font-weight:600}
.ck-ev1{font-size:.78rem;color:var(--mute);margin-top:.3rem}
.ck-ev1 span{color:var(--bidder)}
/* detail: buyer vs bidder */
.ck-detail{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:0;border:1px solid var(--line);border-radius:6px;overflow:hidden}
.ck-side{padding:.9rem 1rem}
.ck-side.buyer{background:#14120D;border-right:1px solid var(--line)}
.ck-side.bidder{background:#0D1218}
.ck-side-h{font-family:'Cormorant Garamond',serif;font-size:1.12rem;margin:0 0 .55rem}
.ck-side.buyer .ck-side-h{color:var(--buyer)}.ck-side.bidder .ck-side-h{color:var(--bidder)}
.ck-quote{font-family:'Cormorant Garamond',serif;font-size:1.02rem;line-height:1.55;border-left:2px solid var(--buyer);
 padding:.1rem 0 .1rem .75rem;margin:0 0 .7rem;max-height:16rem;overflow:auto;white-space:pre-line}
.ck-dl{display:grid;grid-template-columns:8.5rem minmax(0,1fr);gap:.2rem .6rem;font-size:.78rem;margin:0}
.ck-dl dt{color:var(--dim)}.ck-dl dd{margin:0;color:var(--ink);overflow-wrap:anywhere}
.ck-src{font-size:.76rem;color:var(--mute);border-top:1px dashed var(--line);margin-top:.55rem;padding-top:.45rem;line-height:1.45}
.ck-src q{color:var(--ink)}
.ck-ev{border:1px solid #1F2A35;border-radius:5px;padding:.55rem .7rem;margin:0 0 .55rem;background:#0A0F14}
.ck-ev-f{font-size:.8rem;font-weight:600;color:var(--bidder);overflow-wrap:anywhere}
.ck-ev-l{font-size:.74rem;color:var(--mute);margin:.15rem 0 .35rem}
.ck-ev-x{font-size:.8rem;line-height:1.5;color:var(--ink);max-height:9rem;overflow:auto;white-space:pre-line}
.ck-ev-x .fv{color:var(--mute)}
.ck-none{font-size:.82rem;color:var(--mute);font-style:italic}
.ck-concl{border:1px solid var(--line);border-top:none;border-radius:0 0 6px 6px;padding:.75rem 1rem;background:var(--panel2)}
.ck-concl-h{display:flex;gap:.6rem;align-items:center;flex-wrap:wrap;margin-bottom:.35rem}
.ck-concl-h span.what{font-size:.8rem;color:var(--mute)}
.ck-files{width:100%;border-collapse:collapse;font-size:.82rem}
.ck-files th{text-align:left;font-weight:600;color:var(--mute);font-size:.74rem;padding:.4rem .6rem;border-bottom:1px solid var(--line)}
.ck-files td{padding:.45rem .6rem;border-bottom:1px solid #1B1B23;vertical-align:top;overflow-wrap:anywhere}
.ck-legend{display:flex;flex-wrap:wrap;gap:.4rem .9rem;font-size:.76rem;color:var(--mute);margin:.2rem 0 .9rem}
.ck-legend span b{color:var(--c)}
@media (max-width:900px){.ck-counts{grid-template-columns:repeat(2,minmax(0,1fr))}
 .ck-count{border-bottom:1px solid var(--line)}
 .ck-detail,.ck-split{grid-template-columns:1fr}
 .ck-side.buyer{border-right:none;border-bottom:1px solid var(--line)}
 .ck-dl{grid-template-columns:1fr}}
</style>
"""

TONE_COLOR = {"ok": "var(--ok)", "partial": "var(--partial)", "gap": "var(--gap)", "unverifiable": "var(--unv)",
              "review": "var(--review)", "na": "var(--dim)", "caution": "var(--partial)", "info": "var(--unv)",
              "warn": "var(--gap)"}


def _c(status: str) -> str:
    return TONE_COLOR[STATUS_META.get(status, STATUS_META[NOT_APPLICABLE])["tone"]]


def status_pill(status: str) -> str:
    m = STATUS_META.get(status, {"label": status, "mark": "·", "tone": "na"})
    return (f'<span class="ck-pill" style="--c:{TONE_COLOR[m["tone"]]}" data-status="{esc(status)}">'
            f'<b aria-hidden="true">{esc(m["mark"])}</b>{esc(m["label"])}</span>')


def chips_html(a: dict) -> str:
    return "".join(f'<span class="ck-chip">{esc(c)}</span>' for c in fact_chips(a))


def wrap(inner: str) -> str:
    return f'{CSS}<div class="ck">{inner}</div>'


def render_banner(tone: str, title: str, lines=()) -> str:
    mark = {"ok": "✓", "caution": "◐", "gap": "✕", "warn": "!", "info": "i"}.get(tone, "i")
    body = "".join(f"<br>{esc(line)}" for line in lines or [])
    return (f'<div class="ck-banner t-{esc(tone)}" data-tone="{esc(tone)}"><b class="m">{esc(mark)}</b>'
            f'<strong>{esc(title)}</strong>{body}</div>')


def render_header(bid: dict | None, rv: dict, files: list) -> str:
    bid = bid or {}
    rfp = bid.get("file_number") or "—"
    snap = rv.get("package_snapshot_id")
    fileline = f"{len(files)} submitted file{'s' if len(files) != 1 else ''}" if files else "—"
    meta = [("CHECK run", f"Run {rv.get('run_id')}" if rv.get("run_id") is not None else "—"),
            ("Run status", rv.get("label")),
            ("Run finished" if rv.get("is_terminal") else "Last activity", rv.get("when")),
            ("RFP identifier", rfp),
            ("Submission assessed", fileline + (f" (package snapshot {snap})" if snap is not None else ""))]
    cells = "".join(f"<div><dt>{esc(k)}</dt><dd>{esc(v)}</dd></div>" for k, v in meta)
    return (f'<div class="ck-kicker">CHECK: proposal assurance</div>'
            f'<h1 class="ck-title">{esc(bid.get("client") or "Opportunity")}</h1>'
            f'<div class="ck-sub">{esc(bid.get("title") or "")}</div>'
            f'<dl class="ck-meta">{cells}</dl>')


def render_counts(ov: dict) -> str:
    cells = []
    for s, n in ov["counts"]:
        m = STATUS_META[s]
        cells.append(f'<div class="ck-count{" zero" if not n else ""}" style="--c:{TONE_COLOR[m["tone"]]}" '
                     f'data-status="{esc(s)}" title="{esc(STATUS_MEANING[s])}"><div class="n">{n}</div>'
                     f'<div class="l"><b aria-hidden="true">{esc(m["mark"])}</b>{esc(m["label"])}</div></div>')
    excluded = ov["excluded"]
    note = (f'<div class="ck-excluded">{excluded} buyer object{"s" if excluded != 1 else ""} classified as '
            f'non-submission / informational (buyer process, post-award, informational or deemed by '
            f'submission). These are not proposal gaps. {ov["total"]} buyer objects in total: '
            f'{ov["requirements"]} requirements and {ov["criteria"]} evaluation criteria.</div>')
    return f'<div class="ck-counts">{"".join(cells)}</div>{note}'


def render_legend() -> str:
    parts = []
    for s in PRIMARY_STATUSES:
        m = STATUS_META[s]
        parts.append(f'<span style="--c:{TONE_COLOR[m["tone"]]}"><b>{esc(m["mark"])}</b> '
                     f'{esc(m["label"])}: {esc(STATUS_MEANING[s])}</span>')
    return f'<div class="ck-legend">{"".join(parts)}</div>'


def _first_gap(a: dict) -> str:
    g = element_groups(a)
    if a.get("status") in (PARTIAL, NOT_ADDRESSED) and g["not_demonstrated"]:
        names = [clip(e.get("element"), 90) for e in g["not_demonstrated"][:3]]
        more = len(g["not_demonstrated"]) - len(names)
        return "Not (fully) demonstrated: " + "; ".join(names) + (f"; and {more} more" if more > 0 else "")
    notes = review_notes(a)
    if a.get("status") in (NOT_VERIFIABLE, HUMAN_REVIEW):
        fallback = notes[-1] if notes else STATUS_MEANING[a["status"]]
        if g["unverifiable"]:
            return clip(g["unverifiable"][0].get("note") or fallback, 220)
        return clip(fallback, 220)
    return ""


def render_attention(items: list) -> str:
    if not items:
        return '<div class="ck-none">Nothing needs attention: no partial, unverifiable or human-review findings.</div>'
    rows = []
    for a in items:
        m = STATUS_META.get(a.get("status"), STATUS_META[NOT_APPLICABLE])
        rows.append(f'<div class="ck-att-row" style="--c:{_c(a.get("status"))}" data-object="{esc(a.get("buyer_object_id"))}">'
                    f'<div class="ck-att-m" aria-hidden="true">{esc(m["mark"])}</div><div>'
                    f'<div class="ck-att-t">{esc(display_name(a))}</div>'
                    f'<div>{status_pill(a.get("status"))} {chips_html(a)}</div>'
                    f'<div class="ck-att-d">{esc(_first_gap(a))}</div></div></div>')
    return f'<div class="ck-att">{"".join(rows)}</div>'


def _element_li(el: dict, show_cov: bool) -> str:
    cov = el.get("coverage")
    extra = []
    if show_cov and cov:
        extra.append(ELEMENT_COVERAGE_LABEL.get(cov, cov))
    if el.get("source_object_id"):
        extra.append(f"from {el['source_object_id']}")
    if el.get("note"):
        extra.append(clip(el["note"], 200))
    tail = f' <small>({esc("; ".join(extra))})</small>' if extra else ""
    return f'<li>{esc(clip(el.get("element"), 260))}{tail}</li>'


def render_elements(a: dict) -> str:
    """Demonstrated vs Not demonstrated (the PARTIAL centrepiece)."""
    g = element_groups(a)
    if not (g["demonstrated"] or g["not_demonstrated"]):
        return ""
    dem = "".join(_element_li(e, False) for e in g["demonstrated"]) or '<li class="ck-none">None recorded</li>'
    miss = "".join(_element_li(e, True) for e in g["not_demonstrated"]) or '<li class="ck-none">None</li>'
    n_d, n_m = len(g["demonstrated"]), len(g["not_demonstrated"])
    who = "The evaluation criterion" if is_criterion(a) else "The buyer"
    summary = (f'<div class="ck-note">{who} asks for {n_d + n_m} recorded element{"s" if n_d + n_m != 1 else ""}. '
               f'The submission demonstrates {n_d}; {n_m} {"is" if n_m == 1 else "are"} not demonstrated or only '
               f'partly demonstrated.</div>') if n_m else ""
    return (f'{summary}<div class="ck-split">'
            f'<div class="ck-col" style="--c:var(--ok)"><h5>✓ Demonstrated ({len(g["demonstrated"])})</h5><ul>{dem}</ul></div>'
            f'<div class="ck-col" style="--c:var(--partial)"><h5>◐ Not demonstrated ({len(g["not_demonstrated"])})</h5>'
            f'<ul>{miss}</ul></div></div>')


def render_unverifiable(a: dict) -> str:
    g = element_groups(a)
    if not g["unverifiable"]:
        return ""
    items = "".join(_element_li(e, False) for e in g["unverifiable"])
    return (f'<div class="ck-split" style="grid-template-columns:1fr"><div class="ck-col" style="--c:var(--unv)">'
            f'<h5>? Cannot be verified from the submitted files ({len(g["unverifiable"])})</h5><ul>{items}</ul></div></div>')


def _reason_block(a: dict) -> str:
    st_ = a.get("status")
    notes = review_notes(a)
    if st_ == NOT_VERIFIABLE:
        head = "Why this cannot be verified from the submitted files"
    elif st_ == HUMAN_REVIEW:
        head = "Why CHECK cannot safely determine coverage"
    elif st_ == NOT_APPLICABLE:
        head = "Why this is not a proposal obligation"
    else:
        return ""
    body = "; ".join(notes) if notes else STATUS_MEANING.get(st_, "")
    todo = ""
    if st_ == HUMAN_REVIEW:
        todo = ("<br><b>What a person should verify:</b> read the buyer wording on the left against the cited "
                "submission evidence and confirm whether it is met.")
    elif st_ == NOT_VERIFIABLE:
        todo = "<br><b>What to confirm:</b> confirm it outside the uploaded files (for example in the buyer's portal)."
    return f'<div class="ck-note"><b>{esc(head)}:</b> {esc(clip(body, 900))}{todo}</div>'


def render_card(a: dict, index: dict) -> str:
    """Criterion / requirement summary card (no evidence dump)."""
    st_ = a.get("status")
    tone = STATUS_META.get(st_, STATUS_META[NOT_APPLICABLE])["tone"]
    head = (f'<div class="ck-card-h"><div class="ck-card-t">{esc(display_name(a))}</div>'
            f'<div>{status_pill(st_)}</div></div><div>{chips_html(a)}</div>')
    if st_ == ADDRESSED:
        ev = strongest_evidence(a, index)
        evline = (f'<div class="ck-ev1">Strongest evidence: <span>{esc(ev["filename"])}</span>'
                  f'{(", " + esc(", ".join(ev["location"]))) if ev["location"] else ""}</div>') if ev else ""
        return f'<div class="ck-card t-ok" style="--c:{_c(st_)}" data-object="{esc(a.get("buyer_object_id"))}">{head}{evline}</div>'
    body = f'<div class="ck-ask">{esc(concise_expectation(a))}</div>'
    if a.get("evidence_summary"):
        body += f'<div class="ck-note"><b>Evidence summary:</b> {esc(clip(a["evidence_summary"], 400))}</div>'
    body += render_elements(a) + render_unverifiable(a) + _reason_block(a)
    return (f'<div class="ck-card t-{esc(tone)}" style="--c:{_c(st_)}" data-object="{esc(a.get("buyer_object_id"))}">'
            f'{head}{body}</div>')


def _buyer_source_html(a: dict) -> str:
    prov = a.get("source_provenance") or {}
    refs = prov.get("source_refs") or []
    out = []
    for r in refs[:4]:
        where = [x for x in (r.get("source_doc"), f"section {r['section']}" if r.get("section") else None,
                             f"page {r['page']}" if r.get("page") is not None else None,
                             f"sheet {r['sheet']}" if r.get("sheet") else None) if x]
        ex = f' <q>{esc(clip(r.get("excerpt"), 260))}</q>' if r.get("excerpt") else ""
        out.append(f'<div>{esc(", ".join(where) or "Buyer source")}{ex}</div>')
    if not out and prov.get("source_docs"):
        out = [f'<div>{esc(d)}</div>' for d in prov["source_docs"][:4]]
    return "".join(out) or '<div class="ck-none">No buyer source reference was persisted.</div>'


def render_evidence_item(ev: dict, used_for: list | None = None) -> str:
    loc = ", ".join(ev["location"]) or "Location not recorded"
    if ev.get("value") is not None and ev.get("field_label"):
        x = f'<span class="fv">{esc(ev["field_label"])}:</span> {esc(ev["value"])}'
    else:
        x = esc(ev["excerpt"]) or '<span class="ck-none">(empty)</span>'
    used = f'<div class="ck-ev-l">Supports: {esc("; ".join(used_for))}</div>' if used_for else ""
    return (f'<div class="ck-ev" data-evidence="{esc(ev["evidence_id"])}"><div class="ck-ev-f">{esc(ev["filename"])}</div>'
            f'<div class="ck-ev-l">{esc(ev["role_label"])}, {esc(ev["kind_label"])}. {esc(loc)}</div>'
            f'<div class="ck-ev-x">{x}</div>{used}</div>')


def _element_use(a: dict) -> dict:
    use: dict = {}
    for group in ("addressed_elements", "missing_elements", "unverifiable_elements"):
        for el in a.get(group) or []:
            for eid in (el or {}).get("evidence_ids") or []:
                use.setdefault(eid, [])
                name = clip(el.get("element"), 70)
                if name not in use[eid]:
                    use[eid].append(name)
    return use


def evidence_items_for(a: dict, index: dict) -> tuple:
    """(resolved evidence views in citation order, unresolved ids)."""
    ids = cited_evidence_ids(a)
    return [index[e] for e in ids if e in index], [e for e in ids if e not in index]


def render_detail(a: dict, index: dict, *, max_evidence: int = MAX_EVIDENCE_SHOWN,
                  include_elements: bool = True) -> tuple:
    """(detail_html, overflow_html). LEFT: what the buyer asked for; RIGHT:
    what the bidder submitted; the CHECK conclusion beneath both. The
    overflow holds evidence beyond `max_evidence` (rendered in a separate,
    collapsed area by the page)."""
    prov = a.get("source_provenance") or {}
    rows = [("Buyer object", a.get("buyer_object_id")),
            ("Type", "Evaluation criterion" if is_criterion(a) else "Requirement"),
            ("Scope", SCOPE_LABEL.get(a.get("assurance_scope"), a.get("assurance_scope"))),
            ("Scope basis", a.get("scope_basis"))]
    if a.get("buyer_category"):
        rows.append(("Buyer category", a["buyer_category"]))
    if a.get("applicability") and a["applicability"] != "UNKNOWN":
        rows.append(("Applicability", a["applicability"].replace("_", " ").lower()
                     + (f" ({clip(a['applicability_condition'], 160)})" if a.get("applicability_condition") else "")))
    weights = stated_weights(a)
    if weights:
        rows.append(("Buyer weight", " / ".join(weights)
                     + (" (buyer sources state differing weights)" if len(weights) > 1 else "")))
    if a.get("buyer_threshold"):
        rows.append(("Minimum threshold", a["buyer_threshold"]))
    if prov.get("required_form"):
        rows.append(("Required form", prov["required_form"]))
    if a.get("linked_requirement_ids"):
        rows.append(("Linked requirements", ", ".join(a["linked_requirement_ids"])))
    if a.get("expected_evidence_roles"):
        rows.append(("Expected evidence in", ", ".join(ROLE_LABEL.get(r, r) for r in a["expected_evidence_roles"])))
    dl = "".join(f"<dt>{esc(k)}</dt><dd>{esc(v)}</dd>" for k, v in rows if v)
    wording = str(a.get("buyer_expectation") or "").strip() or "(the canonical buyer object carries no wording)"
    buyer = (f'<div class="ck-side buyer"><div class="ck-side-h">What the buyer asked for</div>'
             f'<div class="ck-quote">{esc(clip(wording, 2400) if len(wording) > 2400 else wording)}</div>'
             f'<dl class="ck-dl">{dl}</dl><div class="ck-src"><b>Buyer source</b>{_buyer_source_html(a)}</div></div>')

    resolved, unresolved = evidence_items_for(a, index)
    use = _element_use(a)
    shown, rest = resolved[:max_evidence], resolved[max_evidence:]
    if shown:
        ev_html = "".join(render_evidence_item(ev, use.get(ev["evidence_id"])) for ev in shown)
        if rest:
            ev_html += f'<div class="ck-note">{len(rest)} more cited evidence item(s) below.</div>'
    elif a.get("status") == NOT_APPLICABLE:
        ev_html = '<div class="ck-none">No bidder evidence is expected: this is not a proposal obligation.</div>'
    elif a.get("assurance_scope") == "PORTAL_NATIVE":
        ev_html = ('<div class="ck-none">No uploaded file can show this: the buyer collects it in its '
                   'e-procurement portal.</div>')
    else:
        ev_html = '<div class="ck-none">No bidder evidence was cited for this finding.</div>'
    if unresolved:
        ev_html += (f'<div class="ck-note">{len(unresolved)} cited evidence reference(s) could not be resolved in '
                    f'this bid\'s submission registry and are not shown.</div>')
    bidder = f'<div class="ck-side bidder"><div class="ck-side-h">What the bidder submitted</div>{ev_html}</div>'

    method = METHOD_LABEL.get(a.get("deterministic_or_model"), a.get("deterministic_or_model"))
    concl = (f'<div class="ck-concl"><div class="ck-concl-h">{status_pill(a.get("status"))}'
             f'<span class="what">CHECK conclusion. {esc(method)}.</span></div>'
             + (f'{render_elements(a)}{render_unverifiable(a)}{_reason_block(a)}' if include_elements
                else '<div class="ck-note">The elements and reasons behind this conclusion are shown on the card above.</div>'))
    if a.get("status") not in (NOT_VERIFIABLE, HUMAN_REVIEW, NOT_APPLICABLE) and review_notes(a):
        concl += f'<div class="ck-note"><b>Adjudication notes:</b> {esc(clip("; ".join(review_notes(a)), 700))}</div>'
    concl += "</div>"
    overflow = "".join(render_evidence_item(ev, use.get(ev["evidence_id"])) for ev in rest)
    return f'<div class="ck-detail">{buyer}{bidder}</div>{concl}', overflow


def render_files(files: list) -> str:
    if not files:
        return '<div class="ck-none">No submitted files were loaded for this run.</div>'
    rows = "".join(
        f'<tr><td>{esc(f["filename"])}</td><td>{esc(f["role_label"])}</td><td>{esc((f["file_type"] or "").upper())}</td>'
        f'<td>{esc(f["page_count"] if f["page_count"] else (", ".join(f["sheets"]) or "—"))}</td>'
        f'<td>{esc(f["evidence_count"])}</td></tr>' for f in files)
    return (f'<table class="ck-files"><thead><tr><th>File</th><th>Role</th><th>Type</th><th>Pages / sheets</th>'
            f'<th>Evidence items</th></tr></thead><tbody>{rows}</tbody></table>')


def select_label(a: dict) -> str:
    """Plain-text label for a finding (selectors / expanders)."""
    m = STATUS_META.get(a.get("status"), STATUS_META[NOT_APPLICABLE])
    w = stated_weights(a)
    return f'{m["mark"]} {display_name(a)[:120]}' + (f"  [{' / '.join(w)}]" if w else "")
