import streamlit as st

STAGES     = ["Identified", "Qualifying", "In Progress", "Review", "Submitted", "Won", "Lost", "No Bid"]
STATUSES   = ["Not Started", "In Progress", "Draft", "In Review", "Complete", "Blocked", "N/A"]
PRIORITIES = ["Critical", "High", "Medium", "Low"]
CATEGORIES = ["Mandatory", "Rated", "Financial", "Supporting"]
SENSITIVITY= ["Standard", "Sensitive"]
DOC_TYPES  = ["RFP / Source", "Submission", "Supporting", "Reference", "Internal"]

STAGE_COLOURS = {
    "Identified":  "#6E6C66",
    "Qualifying":  "#C6A15B",
    "In Progress": "#2980B9",
    "Review":      "#8E44AD",
    "Submitted":   "#27AE60",
    "Won":         "#1E8449",
    "Lost":        "#C0392B",
    "No Bid":      "#555555",
}
STATUS_COLOURS = {
    "Not Started": "#6E6C66",
    "In Progress": "#2980B9",
    "Draft":       "#C6A15B",
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

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=EB+Garamond:ital,wght@0,400;0,600;1,400&display=swap');

html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

.stApp { background-color: #0C0C0E; color: #EDEAE2; }

section[data-testid="stSidebar"] {
    background-color: #131316 !important;
    border-right: 1px solid #2A2A2E;
}
section[data-testid="stSidebar"] * { color: #EDEAE2 !important; }

h1,h2,h3 { font-family: 'EB Garamond', serif !important; color: #EDEAE2; }
h1 { font-size: 2rem !important; }
h2 { font-size: 1.4rem !important; }
h3 { font-size: 1.15rem !important; color: #C6A15B !important; }

.stButton>button {
    background: #1B2A41; color: #EDEAE2; border: 1px solid #2A3A55;
    border-radius: 4px; font-size: 0.82rem; padding: 0.3rem 0.8rem;
    transition: all .15s;
}
.stButton>button:hover { background: #C6A15B; color: #0C0C0E; border-color: #C6A15B; }

.stTextInput>div>div>input,
.stTextArea>div>div>textarea,
.stSelectbox>div>div>div,
.stDateInput>div>div>input,
.stNumberInput>div>div>input {
    background: #1A1A1E !important; color: #EDEAE2 !important;
    border: 1px solid #2A2A2E !important; border-radius: 4px !important;
}
div[data-testid="stForm"] { background: #131316; border: 1px solid #2A2A2E; border-radius: 6px; padding: 1rem; }

.metric-card {
    background: #131316; border: 1px solid #2A2A2E; border-radius: 6px;
    padding: 1rem 1.2rem; margin-bottom: .5rem;
}
.metric-card .label { font-size: .72rem; color: #A9A69D; letter-spacing: .06em; text-transform: uppercase; }
.metric-card .value { font-size: 1.6rem; font-weight: 700; color: #EDEAE2; margin: .15rem 0; }
.metric-card .sub   { font-size: .78rem; color: #C6A15B; }

.bid-card {
    background: #131316; border: 1px solid #2A2A2E; border-radius: 6px;
    padding: 1rem 1.2rem; margin-bottom: .75rem; cursor: pointer;
    transition: border-color .15s;
}
.bid-card:hover { border-color: #C6A15B; }
.bid-card .bid-title { font-family: 'EB Garamond', serif; font-size: 1.1rem; color: #EDEAE2; }
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

.section-divider {
    border: none; border-top: 1px solid #2A2A2E; margin: 1.2rem 0;
}
.gold-rule { border-top: 2px solid #C6A15B; margin: .5rem 0 1.2rem 0; }

.readiness-bar-bg {
    background: #1A1A1E; border-radius: 4px; height: 8px; margin: .3rem 0;
}
.readiness-bar-fill {
    height: 8px; border-radius: 4px; transition: width .3s;
}

.info-box {
    background: #131316; border-left: 3px solid #C6A15B;
    padding: .6rem 1rem; margin: .5rem 0; border-radius: 0 4px 4px 0;
    font-size: .85rem; color: #A9A69D;
}
.warn-box {
    background: #1A0A0A; border-left: 3px solid #C0392B;
    padding: .6rem 1rem; margin: .5rem 0; border-radius: 0 4px 4px 0;
    font-size: .85rem; color: #E57373;
}

.row-table { width:100%; border-collapse:collapse; font-size:.82rem; }
.row-table th {
    background:#1B2A41; color:#EDEAE2; padding:.45rem .7rem;
    text-align:left; font-weight:600; font-size:.72rem;
    letter-spacing:.05em; text-transform:uppercase;
}
.row-table td { padding:.4rem .7rem; border-bottom:1px solid #1E1E22; color:#EDEAE2; vertical-align:top; }
.row-table tr:hover td { background:#16161A; }

.empty-state { text-align:center; color:#6E6C66; padding:2.5rem 1rem; font-size:.9rem; }
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

def readiness_bar(pct, colour="#C6A15B"):
    w = min(int(pct), 100)
    col = "#27AE60" if pct >= 80 else ("#E67E22" if pct >= 50 else "#C0392B")
    return f"""
    <div class="readiness-bar-bg">
      <div class="readiness-bar-fill" style="width:{w}%;background:{col}"></div>
    </div>
    <span style="font-size:.75rem;color:{col}">{pct:.0f}% ready</span>
    """

def metric_card(label, value, sub=""):
    return f"""
    <div class="metric-card">
      <div class="label">{label}</div>
      <div class="value">{value}</div>
      {"<div class='sub'>"+sub+"</div>" if sub else ""}
    </div>"""

def days_until(deadline_str):
    if not deadline_str:
        return None
    from datetime import date
    try:
        d = date.fromisoformat(deadline_str)
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
        return f"<span style='color:#C6A15B'>{n}d left</span>"
    return f"<span style='color:#A9A69D'>{n}d left</span>"
