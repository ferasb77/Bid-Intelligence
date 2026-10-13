import streamlit as st

STAGES     = ["Identified", "Understand", "Qualifying", "In Progress", "Review", "Submitted", "Won", "Lost", "Withdrawn", "No Bid"]
STATUSES   = ["Not Started", "In Progress", "Draft", "In Review", "Complete", "Blocked", "N/A"]
PRIORITIES = ["Critical", "High", "Medium", "Low"]
CATEGORIES = ["Mandatory", "Rated", "Financial", "Supporting"]
SENSITIVITY= ["Standard", "Sensitive"]
DOC_TYPES  = ["RFP / Source", "Submission", "Supporting", "Reference",
              "Past Proposal", "Financial", "Internal"]
QUAL_STATUSES = ["PASS", "CONCERN", "FAIL", "UNKNOWN"]
EVIDENCE_STATUSES = ["READY", "PARTIAL", "MISSING", "NOT REQUIRED"]

STAGE_COLOURS = {
    "Identified":  "#6E6C66",
    "Understand":  "#8E7CC3",
    "Qualifying":  "#C9A96E",
    "In Progress": "#2980B9",
    "Review":      "#8E44AD",
    "Submitted":   "#27AE60",
    "Won":         "#1E8449",
    "Lost":        "#C0392B",
    "Withdrawn":   "#7F8C8D",
    "No Bid":      "#555555",
}
STATUS_COLOURS = {
    "Not Started": "#6E6C66",
    "In Progress": "#2980B9",
    "Draft":       "#C9A96E",
    "In Review":   "#8E44AD",
    "Complete":    "#27AE60",
    "Blocked":     "#C0392B",
    "N/A":         "#555555",
}
PRIORITY_COLOURS = {
    "Critical": "#C0392B",
    "High":     "#E67E22",
    "Medium":   "#2980B9",
    "Low":      "#6E6C66",
}
QUAL_COLOURS = {
    "PASS":    "#27AE60",
    "CONCERN": "#E67E22",
    "FAIL":    "#C0392B",
    "UNKNOWN": "#6E6C66",
}
EVIDENCE_COLOURS = {
    "READY":        "#27AE60",
    "PARTIAL":      "#E67E22",
    "MISSING":      "#C0392B",
    "NOT REQUIRED": "#6E6C66",
    "UNASSESSED":   "#6E6C66",
    "NOT ASSESSED": "#6E6C66",
}
EPISTEMIC_COLOURS = {
    "RFP FACT":                            "#C9A96E",
    "EXTERNAL BUYER FACT":                 "#2980B9",
    "BID INTELLIGENCE INTERPRETATION":     "#8E44AD",
    "BID STRATEGY / PROOF RECOMMENDATION": "#27AE60",
    "UNKNOWN":                             "#6E6C66",
}

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,300;0,400;0,600;1,300;1,400&family=Inter:wght@300;400;500;600;700&display=swap');

html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

.stApp { background-color: #0A0A0F; color: #EDEAE3; }

section[data-testid="stSidebar"] {
    background-color: #111118 !important;
    border-right: 1px solid #292832;
}
section[data-testid="stSidebar"] * { color: #EDEAE3 !important; }

h1,h2,h3 { font-family: 'Cormorant Garamond', serif !important; color: #EDEAE3; }
h1 { font-size: 2rem !important; }
h2 { font-size: 1.4rem !important; }
h3 { font-size: 1.15rem !important; color: #C9A96E !important; }

.stButton>button {
    background: #18181F; color: #EDEAE3; border: 1px solid #353129;
    border-radius: 4px; font-size: 0.82rem; padding: 0.3rem 0.8rem;
    transition: all .15s;
}
.stButton>button:hover { background: #C9A96E; color: #0A0A0F; border-color: #C9A96E; }

.stTextInput>div>div>input,
.stTextArea>div>div>textarea,
.stSelectbox>div>div>div,
.stDateInput>div>div>input,
.stNumberInput>div>div>input {
    background: #1A1A1E !important; color: #EDEAE3 !important;
    border: 1px solid #292832 !important; border-radius: 4px !important;
}
div[data-testid="stForm"] { background: #111118; border: 1px solid #292832; border-radius: 6px; padding: 1rem; }

.metric-card {
    background: #111118; border: 1px solid #292832; border-radius: 6px;
    padding: 1rem 1.2rem; margin-bottom: .5rem;
}
.metric-card .label { font-size: .72rem; color: #A9A69D; letter-spacing: .06em; text-transform: uppercase; }
.metric-card .value { font-size: 1.6rem; font-weight: 700; color: #EDEAE3; margin: .15rem 0; }
.metric-card .sub   { font-size: .78rem; color: #C9A96E; }

.bid-card {
    background: #111118; border: 1px solid #292832; border-radius: 6px;
    padding: 1rem 1.2rem; margin-bottom: .75rem; cursor: pointer;
    transition: border-color .15s;
}
.bid-card:hover { border-color: #C9A96E; }
.bid-card .bid-title { font-family: 'Cormorant Garamond', serif; font-size: 1.1rem; color: #EDEAE3; }
.bid-card .bid-meta  { font-size: .78rem; color: #A9A69D; margin-top: .2rem; }

.stage-badge {
    display:inline-block; padding:.15rem .55rem; border-radius:3px;
    font-size:.7rem; font-weight:600; letter-spacing:.05em;
}
.status-badge {
    display:inline-block; padding:.1rem .45rem; border-radius:3px;
    font-size:.68rem; font-weight:600;
}
.priority-badge {
    display:inline-block; padding:.1rem .45rem; border-radius:3px;
    font-size:.68rem; font-weight:600;
}
.qual-badge {
    display:inline-block; padding:.15rem .6rem; border-radius:3px;
    font-size:.72rem; font-weight:700; letter-spacing:.06em;
}

.section-divider {
    border: none; border-top: 1px solid #292832; margin: 1.2rem 0;
}
.gold-rule { border-top: 2px solid #C9A96E; margin: .5rem 0 1.2rem 0; }

.readiness-bar-bg {
    background: #1A1A1E; border-radius: 4px; height: 8px; margin: .3rem 0;
}
.readiness-bar-fill {
    height: 8px; border-radius: 4px; transition: width .3s;
}

.info-box {
    background: #111118; border-left: 3px solid #C9A96E;
    padding: .6rem 1rem; margin: .5rem 0; border-radius: 0 4px 4px 0;
    font-size: .85rem; color: #A9A69D;
}
.warn-box {
    background: #1A0A0A; border-left: 3px solid #C0392B;
    padding: .6rem 1rem; margin: .5rem 0; border-radius: 0 4px 4px 0;
    font-size: .85rem; color: #E57373;
}
.success-box {
    background: #0A1A0A; border-left: 3px solid #27AE60;
    padding: .6rem 1rem; margin: .5rem 0; border-radius: 0 4px 4px 0;
    font-size: .85rem; color: #81C784;
}

.row-table { width:100%; border-collapse:collapse; font-size:.82rem; }
.row-table th {
    background:#18181F; color:#EDEAE3; padding:.45rem .7rem;
    text-align:left; font-weight:600; font-size:.72rem;
    letter-spacing:.05em; text-transform:uppercase;
}
.row-table td { padding:.4rem .7rem; border-bottom:1px solid #1E1E22; color:#EDEAE3; vertical-align:top; }
.row-table tr:hover td { background:#16161A; }

.empty-state { text-align:center; color:#6E6C66; padding:2.5rem 1rem; font-size:.9rem; }

/* Stepper Bar */
.stage-stepper {
    display: flex; gap: 8px; margin-bottom: 1.2rem; flex-wrap: wrap;
}
.step-pill {
    padding: .4rem .8rem; border-radius: 4px; font-size: .78rem; font-weight: 600;
    text-decoration: none; border: 1px solid #292832; background: #111118; color: #A9A69D;
}
.step-pill.active {
    background: #C9A96E; color: #0A0A0F; border-color: #C9A96E; font-weight: 700;
}
.step-pill.completed {
    border-color: #27AE60; color: #27AE60;
}

/* Enable My Growth endorsed-product identity */
.emg-sidebar-brand { display:flex; align-items:center; gap:10px; padding:12px 8px 6px; }
.emg-sidebar-brand img { width:54px; height:54px; object-fit:contain; }
.emg-product-name { font-family:'Cormorant Garamond',serif; font-size:1.2rem; color:#EDEAE3; line-height:1.05; }
.emg-edition,.emg-endorsement { color:#C9A96E; font-size:.61rem; letter-spacing:.12em; text-transform:uppercase; }
.emg-endorsement { padding:0 10px 6px; color:#918E86; }
.emg-dashboard-brand { border-left:1px solid #C9A96E; padding:1.1rem 1.5rem 1.2rem; margin:0 0 1.8rem; background:linear-gradient(105deg,#111118 0%,#0A0A0F 75%); }
.emg-dashboard-kicker { color:#C9A96E; font-size:.65rem; font-weight:500; letter-spacing:.18em; }
.emg-dashboard-name { margin-top:.45rem; color:#EDEAE3; font-family:'Cormorant Garamond',serif; font-size:2.55rem; line-height:1; }
.emg-dashboard-name span { color:#C9A96E; }
.emg-dashboard-descriptor { max-width:760px; margin-top:.75rem; color:#918E86; font-size:.87rem; line-height:1.6; }
.emg-dashboard-line { margin-top:.65rem; color:#C9A96E; font-family:'Cormorant Garamond',serif; font-size:1.05rem; }
@media (max-width:700px) { .emg-dashboard-name { font-size:2.1rem; } .emg-dashboard-brand { padding:1rem; } }

/* Bid Intelligence Dedicated Enterprise Sign-in Experience */
.bi-login-brand {
    text-align: center;
    margin: 1.5rem auto 1.5rem auto;
}
.bi-login-mark {
    width: 62px;
    height: 62px;
    object-fit: contain;
    margin: 0 auto 0.85rem auto;
    display: block;
}
.bi-login-title {
    font-family: 'Cormorant Garamond', serif !important;
    font-size: 2.15rem !important;
    font-weight: 600 !important;
    letter-spacing: 0.07em !important;
    color: #EDEAE3 !important;
    line-height: 1.1 !important;
    margin-bottom: 0.25rem !important;
}
.bi-login-subtitle {
    font-size: 0.74rem !important;
    letter-spacing: 0.16em !important;
    text-transform: uppercase !important;
    color: #C9A96E !important;
    font-weight: 500 !important;
    margin-bottom: 0.85rem !important;
}
.bi-login-tagline {
    font-family: 'Inter', sans-serif !important;
    font-size: 0.90rem !important;
    color: #A9A69D !important;
    line-height: 1.4 !important;
}
.bi-login-card-header {
    font-size: 0.98rem;
    font-weight: 600;
    color: #EDEAE3;
    margin-bottom: 0.75rem;
    letter-spacing: -0.01em;
}
.bi-login-footer {
    text-align: center;
    font-size: 0.76rem;
    color: #918E86;
    line-height: 1.6;
    margin-top: 1.75rem;
    letter-spacing: 0.02em;
}
.bi-login-subfooter {
    color: #6E6C66;
    font-size: 0.70rem;
    letter-spacing: 0.04em;
    margin-top: 0.2rem;
}
</style>
"""

def inject_css():
    st.markdown(CSS, unsafe_allow_html=True)

def stage_badge(stage):
    c = STAGE_COLOURS.get(stage, "#6E6C66")
    return f'<span class="stage-badge" style="background:{c}22;color:{c};border:1px solid {c}44">{stage}</span>'

def status_badge(status):
    c = STATUS_COLOURS.get(status, "#6E6C66")
    return f'<span class="status-badge" style="background:{c}22;color:{c}">{status}</span>'

def priority_badge(priority):
    c = PRIORITY_COLOURS.get(priority, "#6E6C66")
    return f'<span class="priority-badge" style="background:{c}22;color:{c}">{priority}</span>'

def qual_badge(status):
    c = QUAL_COLOURS.get(status, "#6E6C66")
    return f'<span class="qual-badge" style="background:{c}22;color:{c};border:1px solid {c}55">{status}</span>'

def evidence_badge(status):
    c = EVIDENCE_COLOURS.get(status, "#6E6C66")
    return f'<span class="qual-badge" style="background:{c}22;color:{c};border:1px solid {c}55">Evidence: {status}</span>'

def resolve_evidence_display_status(req: dict | None) -> str:
    """Resolve presentation-layer evidence readiness status.

    Distinguishes unassessed evidence from confirmed MISSING evidence without
    modifying database schemas, constraints, or enum values.

    Rules:
    - If req is None or empty: returns 'UNASSESSED'.
    - If requirement has an explicit non-missing status ('READY', 'PARTIAL', 'NOT REQUIRED'):
      respects that status.
    - If requirement has raw status 'MISSING' or empty/None:
      checks whether a user has actually evaluated the requirement (i.e. qual_status is set
      to an evaluated value other than 'UNKNOWN', or evidence text, gap action, owner,
      or notes have been entered). If not evaluated, returns 'UNASSESSED'.
      If evaluated, returns 'MISSING'.
    """
    if not req:
        return "UNASSESSED"
    raw = req.get("evidence_status")
    if raw in ("READY", "PARTIAL", "NOT REQUIRED"):
        return raw
    has_been_assessed = (
        req.get("qual_status") not in (None, "", "UNKNOWN")
        or bool(req.get("evidence"))
        or bool(req.get("qual_notes"))
        or bool(req.get("notes"))
        or bool(req.get("gap_action"))
        or bool(req.get("owner"))
    )
    if has_been_assessed and raw == "MISSING":
        return "MISSING"
    if not has_been_assessed:
        return "UNASSESSED"
    return raw or "UNASSESSED"

def epistemic_badge(epistemic_class):
    c = EPISTEMIC_COLOURS.get(epistemic_class, "#6E6C66")
    return f'<span style="display:inline-block;background:{c}22;color:{c};border:1px solid {c}55;padding:.12rem .45rem;border-radius:3px;font-size:.68rem;font-weight:700;letter-spacing:.04em">{epistemic_class}</span>'

def decision_badge(decision):
    colours = {
        "GO": "#27AE60",
        "GO WITH CONDITIONS": "#E67E22",
        "NO-GO": "#C0392B",
        "NO GO": "#C0392B",
        "NEEDS MORE INFORMATION": "#2980B9",
        "NEEDS MORE INFO": "#2980B9",
    }
    col = colours.get(decision.upper(), "#6E6C66")
    return f'<span style="background:{col};color:#fff;padding:.3rem .9rem;border-radius:4px;font-weight:700;font-size:.9rem">{decision}</span>'

def readiness_bar(pct, colour="#C9A96E"):
    w = min(int(pct), 100)
    col = "#27AE60" if pct >= 80 else ("#E67E22" if pct >= 50 else "#C0392B")
    return f"""
    <div class="readiness-bar-bg">
      <div class="readiness-bar-fill" style="width:{w}%;background:{col}"></div>
    </div>
    <span style="font-size:.75rem;color:{col}">{pct:.0f}% ready</span>
    """

def metric_card(label, value, sub="", color=None):
    style = f" style='color:{color}'" if color else ""
    return f"""
    <div class="metric-card">
      <div class="label">{label}</div>
      <div class="value"{style}>{value}</div>
      {"<div class='sub'>"+sub+"</div>" if sub else ""}
    </div>"""

# Sentinel default for `based_on_revision`: distinguishes "this artifact
# has no stored revision-basis concept at all" (the default -- e.g. CHECK's
# live-read compliance matrix, which is always current by construction, so
# there is nothing to compare) from an explicit `None`, which means "this
# artifact DOES have a based_on_procurement_revision column, and its
# stored value is NULL" -- a historical row that predates procurement-
# revision tracking, never treated as current just because None == None
# would otherwise short-circuit the comparison.
_NO_REVISION_BASIS_TRACKED = object()


def procurement_staleness_banner(procurement_state: dict, based_on_revision=_NO_REVISION_BASIS_TRACKED,
                                  context_label: str = "This page") -> str:
    """Shared governance/staleness banner for DECIDE and CHECK (migration
    010). `procurement_state` is {'procurement_revision', 'procurement_truth_status'}
    from tenancy.get_procurement_state_for_organization() -- an 'ungoverned'
    bid must never visually imply its (unverified) revision 1 is verified
    truth; that stronger message always takes precedence over an ordinary
    stale-revision comparison below.

    `based_on_revision`:
      - omitted (default): this artifact has no stored revision-basis
        concept (nothing to compare) -- only the ungoverned check applies.
      - explicit None: the artifact DOES track a basis, and its stored
        value is NULL (predates tracking / never recorded) -- rendered as
        "basis unknown", never treated as current.
      - an int: compared against the CURRENT revision to detect drift
        caused by a buyer update or conflict resolution applied since.

    Returns "" when nothing is stale."""
    current_revision = procurement_state.get("procurement_revision", 1)
    truth_status = procurement_state.get("procurement_truth_status", "ungoverned")
    if truth_status != "governed":
        return (
            '<div class="warn-box">'
            '⚠️ <strong>PROCUREMENT TRUTH NOT YET GOVERNED:</strong> No baseline procurement review has been '
            f'completed for this opportunity. {context_label} may reflect an unverified initial extraction, '
            'not a human-reviewed procurement baseline. Establish a baseline review before relying on it.'
            '</div>'
        )
    if based_on_revision is _NO_REVISION_BASIS_TRACKED:
        return ""
    if based_on_revision is None:
        return (
            '<div class="warn-box">'
            f'⚠️ <strong>PROCUREMENT REVISION BASIS UNKNOWN:</strong> {context_label} predates procurement-'
            'revision tracking, or its basis was never recorded. Re-analysis is required before treating it '
            'as current.'
            '</div>'
        )
    if based_on_revision != current_revision:
        return (
            '<div class="warn-box">'
            f'⚠️ <strong>STALE — PROCUREMENT TRUTH HAS CHANGED:</strong> {context_label} is based on procurement '
            f'revision {based_on_revision}. The current procurement revision is {current_revision} '
            '(a buyer update or conflict resolution was applied since). Re-analysis is required.'
            '</div>'
        )
    return ""


def days_until(deadline_str):
    if not deadline_str:
        return None
    from datetime import date
    try:
        d = date.fromisoformat(deadline_str[:10])
        return (d - date.today()).days
    except Exception:
        return None

def days_label(n):
    if n is None:
        return "—"
    if n < 0:
        return f"<span style='color:#C0392B'>OVERDUE {abs(n)}d</span>"
    if n == 0:
        return "<span style='color:#C0392B'>DUE TODAY</span>"
    if n <= 3:
        return f"<span style='color:#E67E22'>{n}d left</span>"
    if n <= 7:
        return f"<span style='color:#C9A96E'>{n}d left</span>"
    return f"<span style='color:#A9A69D'>{n}d left</span>"
