import streamlit as st
import base64, json, re
from datetime import date, datetime
from database import (init_db, get_all_bids, get_bid, create_bid, update_bid, delete_bid,
                      get_deliverables, upsert_deliverable, delete_deliverable,
                      get_requirements, upsert_requirement, delete_requirement,
                      get_tasks, upsert_task, delete_task,
                      get_documents, upsert_document, delete_document, save_upload,
                      get_document_versions, create_expected_document,
                      get_outline, upsert_section, delete_section,
                      get_readiness)
from config import get_api_key, api_key_configured
from pages_extra import (page_content_library, page_proposal_analyzer,
    page_coach_roster, page_clarifications, page_section_drafter,
    page_submission_assembler, page_debrief, page_exec_dashboard)
from pdf_export import generate_compliance_pdf
from components.ui import (inject_css, stage_badge, status_badge, priority_badge,
                            readiness_bar, days_until, days_label, metric_card,
                            STAGES, STATUSES, PRIORITIES, CATEGORIES, SENSITIVITY,
                            DOC_TYPES, STAGE_COLOURS, PRIORITY_COLOURS)

st.set_page_config(page_title="Bid Intelligence Platform", page_icon="⚡",
                   layout="wide", initial_sidebar_state="expanded")
init_db()
inject_css()

# ── session defaults ──────────────────────────────────────────────────────────
if "page" not in st.session_state:
    st.session_state.page = "dashboard"
if "active_bid" not in st.session_state:
    st.session_state.active_bid = None

def go(page, bid_id=None):
    st.session_state.page = page
    if bid_id is not None:
        st.session_state.active_bid = bid_id
    st.rerun()

# ═════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ═════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("""
    <div style="padding:.5rem 0 1rem 0">
      <div style="font-family:'EB Garamond',serif;font-size:1.25rem;color:#EDEAE2">Bid Intelligence</div>
      <div style="font-size:.7rem;color:#C6A15B;letter-spacing:.1em;text-transform:uppercase">Platform · MVP</div>
    </div>""", unsafe_allow_html=True)

    if api_key_configured():
        st.markdown('<span style="font-size:.7rem;color:#27AE60">● API key configured</span>', unsafe_allow_html=True)
    else:
        st.markdown('<span style="font-size:.7rem;color:#E67E22">● No API key — add to .env</span>', unsafe_allow_html=True)

    st.markdown('<hr class="section-divider">', unsafe_allow_html=True)

    for label, key in {"🏠  Dashboard": "dashboard", "📋  All Bids": "all_bids",
                   "➕  New Bid": "new_bid", "📚  Content Library": "content_library",
                   "🏋  Coach Roster": "coach_roster",
                   "📊  Executive View": "exec_dashboard"}.items():
        if st.button(label, key=f"nav_{key}", use_container_width=True):
            go(key)

    if st.session_state.active_bid:
        bid = get_bid(st.session_state.active_bid)
        if bid:
            st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
            st.markdown(f'<div style="font-size:.75rem;color:#C6A15B;text-transform:uppercase;margin-bottom:.3rem">Active Bid</div>'
                        f'<div style="font-size:.85rem;font-weight:600;color:#EDEAE2;line-height:1.3">{bid["client"]}<br>'
                        f'<span style="font-weight:400;color:#A9A69D">{bid["title"][:38]}{"…" if len(bid["title"])>38 else ""}</span></div>',
                        unsafe_allow_html=True)
            st.markdown("")
            for label, key in {
                "📊  Overview":          "bid_overview",
                "✅  Compliance Matrix": "compliance",
                "📁  Documents":         "documents",
                "☑️  Tasks":             "tasks",
                "📦  Deliverables":      "deliverables",
                "📝  Proposal Outline":  "outline",
                "🤖  AI Analyst":        "ai_analyst",
                "❓  Clarifications":    "clarifications",
                "✍  Section Drafter":   "section_drafter",
                "🔬  Proposal Analyzer": "proposal_analyzer",
                "📤  Submission":        "submission_assembler",
                "🏆  Debrief":           "debrief",
            }.items():
                if st.button(label, key=f"nav_{key}", use_container_width=True):
                    go(key)
            st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
            if st.button("← All Bids", use_container_width=True):
                st.session_state.active_bid = None
                go("all_bids")

# ═════════════════════════════════════════════════════════════════════════════
# PAGE: DASHBOARD
# ═════════════════════════════════════════════════════════════════════════════
def page_dashboard():
    st.markdown("# Bid Intelligence Platform")
    st.markdown('<div class="gold-rule"></div>', unsafe_allow_html=True)
    bids = get_all_bids()
    active    = [b for b in bids if b["stage"] in ("Qualifying","In Progress","Review")]
    submitted = [b for b in bids if b["stage"] == "Submitted"]
    won       = [b for b in bids if b["stage"] == "Won"]
    lost      = [b for b in bids if b["stage"] == "Lost"]
    urgent    = [b for b in active if (days_until(b.get("submission_deadline")) or 999) <= 14]

    c1,c2,c3,c4 = st.columns(4)
    c1.markdown(metric_card("Active Bids", len(active), f"{len(bids)} total"), unsafe_allow_html=True)
    c2.markdown(metric_card("Submitted", len(submitted), "awaiting outcome"), unsafe_allow_html=True)
    wr = f"{round(len(won)/(len(won)+len(lost))*100)}%" if (won or lost) else "—"
    c3.markdown(metric_card("Win Rate", wr, f"{len(won)}W / {len(lost)}L"), unsafe_allow_html=True)
    c4.markdown(metric_card("Deadlines ≤14d", len(urgent), "need attention"), unsafe_allow_html=True)
    st.markdown("")

    if not bids:
        st.markdown('<div class="info-box">No bids yet — use <strong>New Bid</strong> to create your first opportunity.</div>', unsafe_allow_html=True)
        return

    if urgent:
        st.markdown("### ⚠️ Urgent — submission within 14 days")
        for b in sorted(urgent, key=lambda x: x.get("submission_deadline") or ""):
            pct = (b["req_done"]/b["req_count"]*100) if b["req_count"] else 0
            c1,c2,c3,c4 = st.columns([3,1.5,2,1])
            c1.markdown(f"**{b['client']}** — {b['title']}")
            c2.markdown(days_label(days_until(b.get("submission_deadline"))), unsafe_allow_html=True)
            c3.markdown(readiness_bar(pct), unsafe_allow_html=True)
            if c4.button("Open", key=f"urg_{b['id']}"):
                go("bid_overview", b["id"])
        st.markdown('<hr class="section-divider">', unsafe_allow_html=True)

    st.markdown("### Pipeline")
    for stage in STAGES:
        sb = [b for b in bids if b["stage"] == stage]
        if not sb:
            continue
        col = STAGE_COLOURS.get(stage, "#6E6C66")
        st.markdown(f'<span style="color:{col};font-weight:600;font-size:.85rem">{stage.upper()} ({len(sb)})</span>', unsafe_allow_html=True)
        for b in sb:
            pct = (b["req_done"]/b["req_count"]*100) if b["req_count"] else 0
            c1,c2,c3,c4,c5 = st.columns([3,2,1.5,2,1])
            c1.markdown(f"**{b['client']}** · {b['title'][:45]}")
            c2.markdown(f'<span style="color:#A9A69D;font-size:.8rem">{b.get("owner") or "—"}</span>', unsafe_allow_html=True)
            c3.markdown(days_label(days_until(b.get("submission_deadline"))), unsafe_allow_html=True)
            c4.markdown(readiness_bar(pct) if b["req_count"] else '<span style="color:#6E6C66;font-size:.75rem">No requirements</span>', unsafe_allow_html=True)
            if c5.button("Open", key=f"dash_{b['id']}"):
                go("bid_overview", b["id"])
        st.markdown("")

# ═════════════════════════════════════════════════════════════════════════════
# PAGE: ALL BIDS
# ═════════════════════════════════════════════════════════════════════════════
def page_all_bids():
    st.markdown("# All Bids")
    st.markdown('<div class="gold-rule"></div>', unsafe_allow_html=True)
    bids = get_all_bids()
    if not bids:
        st.markdown('<div class="empty-state">No bids yet.</div>', unsafe_allow_html=True)
        return
    for b in bids:
        pct = (b["req_done"]/b["req_count"]*100) if b["req_count"] else 0
        c1,c2,c3,c4,c5 = st.columns([3.5,1.5,1.5,2,1])
        c1.markdown(f"**{b['client']}**")
        c1.markdown(f'<span style="color:#A9A69D;font-size:.8rem">{b["title"]}</span>', unsafe_allow_html=True)
        c2.markdown(stage_badge(b["stage"]), unsafe_allow_html=True)
        c3.markdown(days_label(days_until(b.get("submission_deadline"))), unsafe_allow_html=True)
        c3.markdown(f'<span style="color:#6E6C66;font-size:.72rem">{b.get("submission_deadline") or "—"}</span>', unsafe_allow_html=True)
        c4.markdown(readiness_bar(pct) if b["req_count"] else '<span style="color:#6E6C66;font-size:.75rem">No requirements</span>', unsafe_allow_html=True)
        if c5.button("Open →", key=f"all_{b['id']}"):
            go("bid_overview", b["id"])
        st.markdown('<hr class="section-divider">', unsafe_allow_html=True)

# ═════════════════════════════════════════════════════════════════════════════
# PAGE: NEW BID
# ═════════════════════════════════════════════════════════════════════════════
def page_new_bid():
    from extractor import extract_rfp
    st.markdown("# New Bid")
    st.markdown('<div class="gold-rule"></div>', unsafe_allow_html=True)

    # API key
    from config import get_api_key as _gak, api_key_configured as _akc
    if _akc() and not st.session_state.get("anthropic_api_key"):
        st.session_state["anthropic_api_key"] = _gak()

    if not st.session_state.get("anthropic_api_key"):
        st.markdown("### Anthropic API Key")
        st.markdown('<div class="info-box">Get your key at <strong>console.anthropic.com</strong> → API Keys. Stored in session only, or add to <code>.env</code> for persistence.</div>', unsafe_allow_html=True)
        key = st.text_input("Paste Anthropic API key", type="password", placeholder="sk-ant-…")
        if st.button("Save key →") and key:
            st.session_state["anthropic_api_key"] = key
            st.rerun()
        st.markdown('<hr class="section-divider">', unsafe_allow_html=True)

    # If extraction done — show review
    if st.session_state.get("extraction"):
        _render_extraction_review()
        return

    # Upload
    st.markdown("### Upload RFP")
    st.markdown('<div class="info-box">Upload the RFP or tender document. Claude will extract the bid details, deadlines, compliance matrix, and proposal outline automatically.</div>', unsafe_allow_html=True)
    uploaded = st.file_uploader("Drop RFP here (PDF, DOCX, TXT)", type=["pdf","docx","doc","txt"], label_visibility="collapsed")
    if uploaded:
        fb = uploaded.read()
        st.markdown(f'<div class="info-box">📄 <strong>{uploaded.name}</strong> — {len(fb)//1024} KB ready to extract.</div>', unsafe_allow_html=True)
        if st.button("🔍  Extract with Claude AI →", use_container_width=True, type="primary"):
            if not st.session_state.get("anthropic_api_key"):
                st.error("Add your Anthropic API key first.")
            else:
                with st.spinner("Reading RFP and extracting structure… 15–30 seconds"):
                    try:
                        result, model_used = extract_rfp(fb, uploaded.name, st.session_state["anthropic_api_key"])
                        st.session_state["extraction"] = result
                        st.session_state["extraction_file"] = {"bytes": fb, "name": uploaded.name}
                        st.session_state["model_used"] = model_used
                        st.rerun()
                    except Exception as e:
                        st.error(f"Extraction failed: {e}")
                        st.markdown('<div class="warn-box">Check that your Anthropic API key is valid (starts with sk-ant-).</div>', unsafe_allow_html=True)

    st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
    with st.expander("✏️ Create bid manually instead"):
        with st.form("manual_bid"):
            c1,c2 = st.columns(2)
            title  = c1.text_input("Title *")
            client = c2.text_input("Client *")
            c1,c2 = st.columns(2)
            file_no = c1.text_input("File Number")
            owner = c2.text_input("Proposal Lead")
            c1,c2,c3 = st.columns(3)
            stage = c1.selectbox("Stage", STAGES, index=1)
            sens  = c2.selectbox("Sensitivity", SENSITIVITY)
            val   = c3.number_input("Value (CAD)", min_value=0.0, step=1000.0)
            c1,c2 = st.columns(2)
            sub_dl  = c1.text_input("Submission Deadline", placeholder="2026-08-06")
            clar_dl = c2.text_input("Clarification Deadline", placeholder="2026-07-23")
            notes = st.text_area("Notes", height=70)
            if st.form_submit_button("Create →", use_container_width=True):
                if title and client:
                    bid_id = create_bid({"title":title,"client":client,"file_number":file_no,
                        "stage":stage,"sensitivity":sens,"owner":owner,"value_cad":val or None,
                        "submission_deadline":sub_dl or None,"clarification_deadline":clar_dl or None,"notes":notes})
                    go("bid_overview", bid_id)
                else:
                    st.error("Title and Client required.")

def _render_extraction_review():
    extracted = st.session_state["extraction"]
    fb        = st.session_state["extraction_file"]["bytes"]
    fname     = st.session_state["extraction_file"]["name"]
    model_used= st.session_state.get("model_used","claude-sonnet-4-6")
    bid   = extracted.get("bid",{})
    reqs  = extracted.get("requirements",[])
    docs  = extracted.get("documents",[])
    secs  = extracted.get("outline",[])

    st.markdown("## Review Extracted Information")
    st.markdown(f'<div class="info-box">Extracted using <strong>{model_used}</strong>. Review and edit, then click <strong>Create Bid</strong>.</div>', unsafe_allow_html=True)

    st.markdown("### Bid Details")
    c1,c2 = st.columns(2)
    title  = c1.text_input("Title",  value=bid.get("title") or "")
    client = c2.text_input("Client", value=bid.get("client") or "")
    c1,c2 = st.columns(2)
    file_no = c1.text_input("File Number", value=bid.get("file_number") or "")
    owner   = c2.text_input("Proposal Lead", value=bid.get("owner") or "")
    c1,c2,c3 = st.columns(3)
    stage = c1.selectbox("Stage", STAGES, index=1)
    sens  = c2.selectbox("Sensitivity", SENSITIVITY)
    val   = c3.number_input("Value (CAD)", min_value=0.0, step=1000.0, value=float(bid.get("value_cad") or 0))
    c1,c2 = st.columns(2)
    sub_dl  = c1.text_input("Submission Deadline",    value=bid.get("submission_deadline") or "")
    clar_dl = c2.text_input("Clarification Deadline", value=bid.get("clarification_deadline") or "")
    notes = st.text_area("Summary / Notes", value=bid.get("notes") or "", height=80)

    st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
    st.markdown(f"### Compliance Matrix — {len(reqs)} requirements extracted")
    for cat in ["Mandatory","Rated","Financial","Supporting"]:
        cr = [r for r in reqs if r.get("category")==cat]
        if not cr:
            continue
        st.markdown(f'<span style="font-size:.78rem;color:#C6A15B;font-weight:600">{cat.upper()} ({len(cr)})</span>', unsafe_allow_html=True)
        for r in cr:
            w = f" · {r['weight']*100:.0f}%" if r.get("weight") else ""
            st.markdown(f'<div style="background:#131316;border:1px solid #2A2A2E;border-radius:4px;padding:.4rem .7rem;margin:.2rem 0;font-size:.82rem">'
                        f'<span style="color:#C6A15B">{r.get("req_id","")}</span><span style="color:#6E6C66">{w}</span> {r.get("description","")}'
                        f'{"<br><span style=color:#6E6C66;font-size:.74rem>"+r.get("evidence","")+"</span>" if r.get("evidence") else ""}'
                        f'</div>', unsafe_allow_html=True)

    if docs:
        st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
        st.markdown(f"### Submission Checklist — {len(docs)} items")
        for d in docs:
            st.markdown(f'<div style="font-size:.82rem;padding:.2rem 0">☐ <strong>{d.get("name","")}</strong></div>', unsafe_allow_html=True)

    if secs:
        st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
        st.markdown(f"### Proposal Outline — {len(secs)} sections")
        for s in sorted(secs, key=lambda x: x.get("sort_order",0)):
            st.markdown(f'<div style="font-size:.82rem;padding:.15rem 0">'
                        f'<span style="color:#C6A15B;margin-right:.4rem">{s.get("section_num","")}</span>{s.get("title","")}</div>', unsafe_allow_html=True)

    st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
    c1,c2 = st.columns([2,1])
    if c1.button("✅  Create Bid with Extracted Data", use_container_width=True, type="primary"):
        if not title or not client:
            st.error("Title and Client are required.")
            return
        bid_id = create_bid({"title":title,"client":client,"file_number":file_no,
            "stage":stage,"sensitivity":sens,"owner":owner,"value_cad":val or None,
            "submission_deadline":sub_dl or None,"clarification_deadline":clar_dl or None,"notes":notes})
        save_upload(bid_id, fname, fb)
        for r in reqs:
            upsert_requirement({**r,"id":None,"bid_id":bid_id,"notes":r.get("notes") or ""})
        for d in docs:
            upsert_document({**d,"id":None,"bid_id":bid_id,"file_path":None})
        for s in secs:
            upsert_section({**s,"id":None,"bid_id":bid_id})
        st.session_state["extraction"] = None
        st.session_state["extraction_file"] = None
        go("bid_overview", bid_id)
    if c2.button("✕  Start Over", use_container_width=True):
        st.session_state["extraction"] = None
        st.session_state["extraction_file"] = None
        st.rerun()

# ═════════════════════════════════════════════════════════════════════════════
# PAGE: BID OVERVIEW
# ═════════════════════════════════════════════════════════════════════════════
def page_bid_overview(bid_id):
    bid = get_bid(bid_id)
    if not bid:
        st.error("Bid not found.")
        return
    c1,c2 = st.columns([4,1])
    c1.markdown(f"# {bid['client']}")
    c1.markdown(f'<span style="color:#A9A69D">{bid["title"]}</span>', unsafe_allow_html=True)
    if bid.get("file_number"):
        c1.markdown(f'<span style="font-size:.78rem;color:#6E6C66">File #{bid["file_number"]}</span>', unsafe_allow_html=True)
    c2.markdown(stage_badge(bid["stage"]), unsafe_allow_html=True)
    sc = "#C0392B" if bid["sensitivity"]=="Sensitive" else "#27AE60"
    c2.markdown(f'<span style="font-size:.75rem;color:{sc}">● {bid["sensitivity"]}</span>', unsafe_allow_html=True)
    st.markdown('<div class="gold-rule"></div>', unsafe_allow_html=True)

    r = get_readiness(bid_id)
    m_pct  = (r["m_done"]/r["m_total"]*100)  if r["m_total"]  else 0
    rt_pct = (r["r_done"]/r["r_total"]*100)  if r["r_total"]  else 0
    t_pct  = (r["t_done"]/r["t_total"]*100)  if r["t_total"]  else 0
    d_pct  = (r["d_done"]/r["d_total"]*100)  if r["d_total"]  else 0
    for col,(label,done,total,pct) in zip(st.columns(4),[
        ("Mandatory",r["m_done"],r["m_total"],m_pct),
        ("Rated/Other",r["r_done"],r["r_total"],rt_pct),
        ("Tasks",r["t_done"],r["t_total"],t_pct),
        ("Submission Docs",r["d_done"],r["d_total"],d_pct)]):
        col.markdown(metric_card(label,f"{done}/{total}",f"{pct:.0f}% complete"), unsafe_allow_html=True)
        col.markdown(readiness_bar(pct), unsafe_allow_html=True)

    st.markdown("")
    c1,c2,c3 = st.columns(3)
    sub_d  = days_until(bid.get("submission_deadline"))
    clar_d = days_until(bid.get("clarification_deadline"))
    c1.markdown(metric_card("Submission Deadline", bid.get("submission_deadline") or "—",
        days_label(sub_d) if sub_d is not None else ""), unsafe_allow_html=True)
    c2.markdown(metric_card("Clarification Deadline", bid.get("clarification_deadline") or "—",
        days_label(clar_d) if clar_d is not None else ""), unsafe_allow_html=True)
    val = f"CAD {bid['value_cad']:,.0f}" if bid.get("value_cad") else "—"
    c3.markdown(metric_card("Estimated Value", val, f"Lead: {bid.get('owner') or '—'}"), unsafe_allow_html=True)

    st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
    st.markdown("### 📎 RFP / Source Documents")
    rfp_docs = [d for d in get_documents(bid_id) if d["doc_type"]=="RFP / Source"]
    if rfp_docs:
        for d in rfp_docs:
            st.markdown(f'<span style="color:#27AE60">✓</span> <span style="font-size:.85rem">{d["name"]}</span>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="info-box">No RFP uploaded yet.</div>', unsafe_allow_html=True)
    up = st.file_uploader("Upload RFP", type=["pdf","docx","xlsx","doc"], key=f"up_{bid_id}", label_visibility="collapsed")
    if up:
        _upload_key = f"uploaded_{bid_id}_{up.name}_{up.size}"
        if not st.session_state.get(_upload_key):
            save_upload(bid_id, up.name, up.read())
            st.session_state[_upload_key] = True
            st.success(f"Uploaded: {up.name}")
            st.rerun()

    if bid.get("notes"):
        st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
        st.markdown("### Notes")
        st.markdown(f'<div class="info-box">{bid["notes"]}</div>', unsafe_allow_html=True)

    def _parse_date(s):
        try:
            return date.fromisoformat(s)
        except Exception:
            return None

    with st.expander("✏️ Edit Bid Details"):
        with st.form("edit_bid"):
            c1,c2 = st.columns(2)
            title  = c1.text_input("Title",  value=bid["title"])
            client = c2.text_input("Client", value=bid["client"])
            c1,c2 = st.columns(2)
            file_no = c1.text_input("File Number", value=bid.get("file_number") or "")
            owner   = c2.text_input("Proposal Lead", value=bid.get("owner") or "")
            c1,c2,c3 = st.columns(3)
            stage = c1.selectbox("Stage", STAGES, index=STAGES.index(bid["stage"]))
            sens  = c2.selectbox("Sensitivity", SENSITIVITY, index=SENSITIVITY.index(bid["sensitivity"]))
            val   = c3.number_input("Value (CAD)", value=float(bid.get("value_cad") or 0), step=1000.0)
            c1,c2 = st.columns(2)
            sub_dl  = c1.date_input("Submission Deadline",    value=_parse_date(bid.get("submission_deadline")))
            clar_dl = c2.date_input("Clarification Deadline", value=_parse_date(bid.get("clarification_deadline")))
            notes = st.text_area("Notes", value=bid.get("notes") or "", height=80)
            c1,c2 = st.columns([3,1])
            save = c1.form_submit_button("Save Changes", use_container_width=True)
            dell = c2.form_submit_button("🗑 Delete Bid", use_container_width=True)
        if save:
            update_bid(bid_id,{"title":title,"client":client,"file_number":file_no,"stage":stage,
                "sensitivity":sens,"owner":owner,"value_cad":val or None,
                "submission_deadline":str(sub_dl) if sub_dl else None,
                "clarification_deadline":str(clar_dl) if clar_dl else None,"notes":notes})
            st.success("Saved.")
            st.rerun()
        if dell:
            delete_bid(bid_id)
            st.session_state.active_bid = None
            go("all_bids")

# ═════════════════════════════════════════════════════════════════════════════
# PAGE: COMPLIANCE MATRIX
# ═════════════════════════════════════════════════════════════════════════════
def page_compliance(bid_id):
    reqs = get_requirements(bid_id)
    st.markdown("# Compliance Matrix")
    st.markdown('<div class="gold-rule"></div>', unsafe_allow_html=True)
    # ── Export button ─────────────────────────────────────────────────────────
    col_title, col_btn = st.columns([4, 1])
    with col_btn:
        if reqs:
            try:
                bid = get_bid(bid_id)
                pdf_bytes = generate_compliance_pdf(bid, reqs)
                client_slug = (bid.get("client") or "bid").replace(" ","_")[:30]
                st.download_button(
                    "⬇ Export PDF",
                    data=pdf_bytes,
                    file_name=f"compliance_matrix_{client_slug}.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                )
            except Exception as e:
                st.error(f"PDF error: {e}")

    if reqs:
        total=len(reqs)
        done=sum(1 for r in reqs if r["status"]=="Complete")
        blocked=sum(1 for r in reqs if r["status"]=="Blocked")
        mfail=sum(1 for r in reqs if r["category"]=="Mandatory" and r["status"] not in ("Complete","N/A"))
        c1,c2,c3,c4=st.columns(4)
        c1.metric("Total",total)
        c2.metric("Complete",done)
        c3.metric("Blocked",blocked)
        c4.metric("Mandatory Outstanding",mfail)
        if mfail:
            st.markdown('<div class="warn-box">⚠ Outstanding mandatory requirements — submission may be disqualified.</div>', unsafe_allow_html=True)
        st.markdown("")

    for cat in ["Mandatory","Rated","Financial","Supporting"]:
        cr = [r for r in reqs if r["category"]==cat]
        done_c = sum(1 for r in cr if r["status"]=="Complete")
        st.markdown(f'<span style="font-size:.8rem;color:#C6A15B;font-weight:600;letter-spacing:.06em">{cat.upper()} — {done_c}/{len(cr)} complete</span>', unsafe_allow_html=True)
        if not cr:
            st.markdown('<div class="empty-state" style="padding:.8rem">None yet.</div>', unsafe_allow_html=True)
        else:
            for h,w in zip(["ID","Ref","Requirement","Evidence","Owner","Deadline","Status",""],
                           [1,.8,4,2,2,1.5,1.8,1]):
                pass
            hcols = st.columns([1,.8,4,2,2,1.5,1.8,1])
            for h,col in zip(["ID","Ref","Requirement","Evidence","Owner","Deadline","Status",""],hcols):
                col.markdown(f'<span style="font-size:.7rem;color:#A9A69D;font-weight:600;text-transform:uppercase">{h}</span>', unsafe_allow_html=True)
            for req in cr:
                c1,c2,c3,c4,c5,c6,c7,c8=st.columns([1,.8,4,2,2,1.5,1.8,1])
                c1.markdown(f'<span style="font-size:.82rem;color:#A9A69D">{req["req_id"] or "—"}</span>', unsafe_allow_html=True)
                c2.markdown(f'<span style="font-size:.78rem;color:#6E6C66">{req["rfso_ref"] or "—"}</span>', unsafe_allow_html=True)
                c3.markdown(f'<span style="font-size:.82rem">{req["description"]}</span>', unsafe_allow_html=True)
                if req.get("weight"):
                    c3.markdown(f'<span style="font-size:.72rem;color:#C6A15B">{req["weight"]*100:.0f}% weight</span>', unsafe_allow_html=True)
                c4.markdown(f'<span style="font-size:.78rem;color:#A9A69D">{req["evidence"] or "—"}</span>', unsafe_allow_html=True)
                c5.markdown(f'<span style="font-size:.82rem">{req["owner"] or "—"}</span>', unsafe_allow_html=True)
                c6.markdown(f'<span style="font-size:.78rem;color:#A9A69D">{req["deadline"] or "—"}</span>', unsafe_allow_html=True)
                c7.markdown(status_badge(req["status"]), unsafe_allow_html=True)
                if c8.button("✏", key=f"er_{req['id']}"):
                    st.session_state["editing_req"]=req["id"]
                    st.rerun()
                st.markdown('<hr class="section-divider" style="margin:.3rem 0">', unsafe_allow_html=True)
        st.markdown("")

    eid = st.session_state.get("editing_req")
    if eid:
        req = next((r for r in reqs if r["id"]==eid), None)
        if req:
            st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
            st.markdown(f"### Edit — {req.get('req_id','') or req['description'][:40]}")
            with st.form("edit_req"):
                c1,c2,c3=st.columns(3)
                rid=c1.text_input("ID",value=req.get("req_id") or "")
                cat=c2.selectbox("Category",CATEGORIES,index=CATEGORIES.index(req["category"]) if req["category"] in CATEGORIES else 0)
                ref=c3.text_input("RFSO Ref",value=req.get("rfso_ref") or "")
                desc=st.text_area("Description",value=req["description"],height=80)
                c1,c2=st.columns(2)
                ev=c1.text_area("Evidence",value=req.get("evidence") or "",height=60)
                own=c2.text_input("Owner",value=req.get("owner") or "")
                c1,c2,c3=st.columns(3)
                dl=c1.text_input("Deadline",value=req.get("deadline") or "")
                wt=c2.number_input("Weight (%)",min_value=0.0,max_value=100.0,value=float((req.get("weight") or 0)*100),step=0.5)
                st_=c3.selectbox("Status",STATUSES,index=STATUSES.index(req["status"]) if req["status"] in STATUSES else 0)
                notes=st.text_area("Notes",value=req.get("notes") or "",height=50)
                c1,c2,c3=st.columns([2,1,1])
                sv=c1.form_submit_button("Save",use_container_width=True)
                dl_=c2.form_submit_button("Delete",use_container_width=True)
                cx=c3.form_submit_button("Cancel",use_container_width=True)
            if sv:
                upsert_requirement({"id":eid,"bid_id":bid_id,"req_id":rid,"category":cat,
                    "description":desc,"rfso_ref":ref,"weight":wt/100 if wt else None,
                    "evidence":ev,"owner":own,"deadline":dl,"status":st_,"notes":notes})
                del st.session_state["editing_req"]
                st.rerun()
            if dl_:
                delete_requirement(eid)
                del st.session_state["editing_req"]
                st.rerun()
            if cx:
                del st.session_state["editing_req"]
                st.rerun()

    st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
    with st.expander("➕ Add Requirement"):
        with st.form("add_req",clear_on_submit=True):
            c1,c2,c3=st.columns(3)
            rid=c1.text_input("ID",placeholder="M1, R3…")
            cat=c2.selectbox("Category",CATEGORIES)
            ref=c3.text_input("RFSO Ref")
            desc=st.text_area("Description *",height=70)
            c1,c2,c3=st.columns(3)
            ev=c1.text_input("Evidence")
            own=c2.text_input("Owner")
            dl=c3.text_input("Deadline")
            c1,c2=st.columns(2)
            wt=c1.number_input("Weight (%)",min_value=0.0,max_value=100.0,step=0.5)
            st_=c2.selectbox("Status",STATUSES)
            notes=st.text_area("Notes",height=50)
            if st.form_submit_button("Add",use_container_width=True):
                if desc:
                    upsert_requirement({"id":None,"bid_id":bid_id,"req_id":rid,"category":cat,
                        "description":desc,"rfso_ref":ref,"weight":wt/100 if wt else None,
                        "evidence":ev,"owner":own,"deadline":dl,"status":st_,"notes":notes})
                    st.rerun()

# ═════════════════════════════════════════════════════════════════════════════
# PAGE: TASKS
# ═════════════════════════════════════════════════════════════════════════════
def page_tasks(bid_id):
    tasks = get_tasks(bid_id)
    st.markdown("# Tasks")
    st.markdown('<div class="gold-rule"></div>', unsafe_allow_html=True)
    if tasks:
        total=len(tasks)
        done=sum(1 for t in tasks if t["status"]=="Complete")
        blocked=sum(1 for t in tasks if t["status"]=="Blocked")
        overdue=sum(1 for t in tasks if (days_until(t.get("due_date")) or 1)<0 and t["status"]!="Complete")
        c1,c2,c3,c4=st.columns(4)
        c1.metric("Total",total)
        c2.metric("Complete",done)
        c3.metric("Blocked",blocked)
        c4.metric("Overdue",overdue)
        st.markdown("")

    for pri in PRIORITIES:
        pt = [t for t in tasks if t["priority"]==pri and t["status"]!="Complete"]
        if not pt:
            continue
        col=PRIORITY_COLOURS.get(pri,"#6E6C66")
        st.markdown(f'<span style="font-size:.8rem;color:{col};font-weight:600">{pri.upper()} ({len(pt)})</span>', unsafe_allow_html=True)
        for t in pt:
            d=days_until(t.get("due_date"))
            c1,c2,c3,c4,c5=st.columns([3.5,1.5,1.5,1.8,1])
            c1.markdown(f"**{t['title']}**")
            if t.get("description"):
                c1.markdown(f'<span style="font-size:.78rem;color:#A9A69D">{t["description"]}</span>', unsafe_allow_html=True)
            c2.markdown(f'<span style="font-size:.82rem">{t.get("owner") or "—"}</span>', unsafe_allow_html=True)
            c3.markdown(days_label(d) if d is not None else '<span style="color:#6E6C66">—</span>', unsafe_allow_html=True)
            c4.markdown(status_badge(t["status"]), unsafe_allow_html=True)
            if c5.button("✏",key=f"et_{t['id']}"):
                st.session_state["editing_task"]=t["id"]
                st.rerun()
            st.markdown('<hr class="section-divider" style="margin:.25rem 0">', unsafe_allow_html=True)
        st.markdown("")

    done_t=[t for t in tasks if t["status"]=="Complete"]
    if done_t:
        with st.expander(f"✅ Completed ({len(done_t)})"):
            for t in done_t:
                c1,c2,c3=st.columns([4,2,1])
                c1.markdown(f'<span style="color:#6E6C66;text-decoration:line-through">{t["title"]}</span>', unsafe_allow_html=True)
                c2.markdown(f'<span style="font-size:.78rem;color:#6E6C66">{t.get("owner") or "—"}</span>', unsafe_allow_html=True)
                if c3.button("✏",key=f"edt_{t['id']}"):
                    st.session_state["editing_task"]=t["id"]
                    st.rerun()

    if not tasks:
        st.markdown('<div class="empty-state">No tasks yet.</div>', unsafe_allow_html=True)

    eid=st.session_state.get("editing_task")
    if eid:
        task=next((t for t in tasks if t["id"]==eid),None)
        if task:
            st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
            st.markdown(f"### Edit Task — {task['title']}")
            with st.form("edit_task"):
                title=st.text_input("Title",value=task["title"])
                desc=st.text_area("Description",value=task.get("description") or "",height=60)
                c1,c2,c3=st.columns(3)
                own=c1.text_input("Owner",value=task.get("owner") or "")
                dd=c2.text_input("Due Date",value=task.get("due_date") or "",placeholder="2026-07-25")
                pri=c3.selectbox("Priority",PRIORITIES,index=PRIORITIES.index(task["priority"]) if task["priority"] in PRIORITIES else 1)
                st_=st.selectbox("Status",STATUSES,index=STATUSES.index(task["status"]) if task["status"] in STATUSES else 0)
                c1,c2,c3=st.columns([2,1,1])
                sv=c1.form_submit_button("Save",use_container_width=True)
                dl=c2.form_submit_button("Delete",use_container_width=True)
                cx=c3.form_submit_button("Cancel",use_container_width=True)
            if sv:
                upsert_task({"id":eid,"bid_id":bid_id,"title":title,"description":desc,
                    "owner":own,"due_date":dd,"priority":pri,"status":st_})
                del st.session_state["editing_task"]
                st.rerun()
            if dl:
                delete_task(eid)
                del st.session_state["editing_task"]
                st.rerun()
            if cx:
                del st.session_state["editing_task"]
                st.rerun()

    st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
    with st.expander("➕ Add Task"):
        with st.form("add_task",clear_on_submit=True):
            title=st.text_input("Title *")
            desc=st.text_area("Description",height=60)
            c1,c2,c3=st.columns(3)
            own=c1.text_input("Owner")
            dd=c2.text_input("Due Date",placeholder="2026-07-25")
            pri=c3.selectbox("Priority",PRIORITIES,index=1)
            st_=st.selectbox("Status",STATUSES)
            if st.form_submit_button("Add Task",use_container_width=True):
                if title:
                    upsert_task({"id":None,"bid_id":bid_id,"title":title,"description":desc,
                        "owner":own,"due_date":dd,"priority":pri,"status":st_})
                    st.rerun()

# ═════════════════════════════════════════════════════════════════════════════
# PAGE: DOCUMENTS
# ═════════════════════════════════════════════════════════════════════════════
def page_documents(bid_id):
    from database import get_document_versions, create_expected_document
    bid  = get_bid(bid_id)
    docs = get_documents(bid_id)
    reqs = get_requirements(bid_id)

    st.markdown("# Document Registry")
    st.markdown('<div class="gold-rule"></div>', unsafe_allow_html=True)

    # ── Status summary ────────────────────────────────────────────────────────
    if docs:
        expected  = sum(1 for d in docs if d["status"]=="Expected"
                        and d.get("doc_type") != "Past Proposal")
        uploaded  = sum(1 for d in docs if d["status"] in ("Uploaded","In Review","Approved")
                        and d.get("doc_type") != "Past Proposal")
        submitted = sum(1 for d in docs if d["status"]=="Submitted")
        mandatory_missing = sum(1 for d in docs
                                if d.get("mandatory") and d["status"]=="Expected"
                                and d.get("doc_type") != "Past Proposal")

        c1,c2,c3,c4 = st.columns(4)
        c1.metric("Total Documents", len(docs))
        c2.metric("Expected / Missing", expected,
                  delta=f"⚠ {mandatory_missing} mandatory" if mandatory_missing else None,
                  delta_color="inverse")
        c3.metric("Uploaded / Ready", uploaded)
        c4.metric("Submitted", submitted)

        if mandatory_missing:
            st.markdown(
                f'<div class="warn-box">⚠ {mandatory_missing} mandatory document(s) '
                f'not yet uploaded. Note: some may be post-award obligations (insurance, '
                f'WCB, registration) rather than proposal submission requirements — '
                f'review the compliance matrix to confirm which are needed at submission.</div>',
                unsafe_allow_html=True)
        st.markdown("")

    # ── Auto-generate expected documents from matrix ───────────────────────────
    existing_names = {d["name"].lower() for d in docs}
    auto_candidates = [r for r in reqs
                       if r.get("evidence") and r.get("category") in ("Mandatory","Financial")]
    new_expected = [r for r in auto_candidates
                    if r.get("evidence","").lower() not in existing_names
                    and r.get("req_id","").lower() not in existing_names]

    if new_expected:
        st.markdown(
            f'<div class="info-box">📋 {len(new_expected)} expected document(s) identified '
            f'from the compliance matrix but not yet in the registry. '
            f'Click to add them as placeholders.</div>',
            unsafe_allow_html=True)
        if st.button(f"➕ Add {len(new_expected)} expected document(s) from matrix",
                     use_container_width=False):
            for r in new_expected:
                create_expected_document(
                    bid_id=bid_id,
                    name=r.get("evidence",""),
                    doc_type="Submission" if r["category"]=="Mandatory" else "Financial",
                    owner=r.get("owner"),
                    due_date=r.get("deadline"),
                    linked_req_ids=r.get("req_id",""),
                    mandatory=1 if r["category"]=="Mandatory" else 0,
                    notes=f"Required for {r.get('req_id','')} — {r.get('description','')[:80]}"
                )
            st.success(f"Added {len(new_expected)} expected documents.")
            st.rerun()
        st.markdown("")

    # ── Bulk reclassify panel ─────────────────────────────────────────────────
    # Allows quick correction of mis-typed documents (e.g. past proposals
    # that were saved as "RFP / Source") without editing one by one.
    with st.expander("🔀 Bulk Reclassify Documents", expanded=False):
        st.markdown('<span style="font-size:.82rem;color:#A9A69D">Select documents and '
                    'assign a new type. Use this to move past proposals, submissions, or '
                    'other mis-classified files to the correct category.</span>',
                    unsafe_allow_html=True)
        if docs:
            doc_options = {f"{d['name']} [{d.get('doc_type','')}]": d["id"] for d in docs}
            selected_labels = st.multiselect(
                "Select documents to reclassify",
                options=list(doc_options.keys()),
                key="bulk_reclassify_sel"
            )
            new_type = st.selectbox(
                "Reclassify to",
                DOC_TYPES,
                key="bulk_reclassify_type"
            )
            if st.button("✅ Apply Reclassification", key="bulk_reclassify_btn",
                         use_container_width=True):
                selected_ids = [doc_options[lbl] for lbl in selected_labels]
                for did in selected_ids:
                    doc = next((d for d in docs if d["id"] == did), None)
                    if doc:
                        upsert_document({
                            "id": did, "bid_id": bid_id,
                            "name": doc["name"],
                            "doc_type": new_type,
                            "owner": doc.get("owner"),
                            "due_date": doc.get("due_date"),
                            "status": doc.get("status", "Uploaded"),
                            "linked_req_ids": doc.get("linked_req_ids"),
                            "mandatory": doc.get("mandatory", 0),
                            "notes": doc.get("notes"),
                            "file_path": None, "file_size": None, "version": None,
                        })
                st.success(f"Reclassified {len(selected_ids)} document(s) → {new_type}")
                st.rerun()
        else:
            st.markdown("No documents to reclassify.")

    # ── Document type tabs ────────────────────────────────────────────────────
    TYPE_ORDER = [
        ("📄 RFP / Source",    "RFP / Source"),
        ("📋 Submission",      "Submission"),
        ("💰 Financial",       "Financial"),
        ("👤 Supporting",      "Supporting"),
        ("📚 Reference",       "Reference"),
        ("📁 Past Proposals",  "Past Proposal"),
        ("🗂 Internal",        "Internal"),
    ]

    STATUS_COL = {
        "Expected":  "#C0392B",
        "Uploaded":  "#2471A3",
        "In Review": "#E67E22",
        "Approved":  "#27AE60",
        "Submitted": "#1E8449",
        "Not Started":"#6E6C66",
        "Complete":  "#27AE60",
        "Blocked":   "#C0392B",
        "N/A":       "#6E6C66",
    }

    has_any = any(any(d["doc_type"]==dt for d in docs) for _,dt in TYPE_ORDER)

    if not docs and not has_any:
        st.markdown('<div class="empty-state">No documents yet. Upload below or '
                    'auto-generate expected documents from the compliance matrix.</div>',
                    unsafe_allow_html=True)

    for label, doc_type in TYPE_ORDER:
        type_docs = [d for d in docs if d["doc_type"]==doc_type]
        if not type_docs:
            continue

        done    = sum(1 for d in type_docs if d["status"] in ("Uploaded","Approved","Submitted","Complete"))
        missing = sum(1 for d in type_docs if d["status"]=="Expected")
        hdr_col = "#C0392B" if missing else "#C6A15B"

        st.markdown(
            f'<div style="background:#131316;border-left:3px solid {hdr_col};'
            f'padding:.4rem .8rem;margin:.5rem 0;border-radius:0 4px 4px 0">'
            f'<span style="color:{hdr_col};font-weight:700;font-size:.82rem">'
            f'{label}</span>'
            f'<span style="color:#6E6C66;font-size:.75rem;margin-left:.8rem">'
            f'{done}/{len(type_docs)} ready'
            f'{f"  ·  <span style=color:#C0392B>{missing} missing</span>" if missing else ""}'
            f'</span></div>',
            unsafe_allow_html=True)

        # Column headers — 7 columns, buttons always visible
        hcols = st.columns([3.5, 1.5, 0.7, 0.5, 0.5, 0.5, 0.5])
        for h, hc in zip(["Document / Owner","Status","Ver","⬆","🔍","✏",""], hcols):
            hc.markdown(
                f'<span style="font-size:.68rem;color:#6E6C66;font-weight:600;'
                f'text-transform:uppercase">{h}</span>',
                unsafe_allow_html=True)

        for d in type_docs:
            st_col  = STATUS_COL.get(d.get("status","Expected"), "#6E6C66")
            icon    = "⚠" if d["status"]=="Expected" else "📄" if d.get("file_path") or d.get("storage_path") else "☐"
            mand_tag= ' <span style="color:#C0392B;font-size:.68rem">★</span>' \
                      if d.get("mandatory") else ""
            has_file= bool(d.get("file_path") or d.get("storage_path"))

            c1,c2,c3,c4,c5,c6,c7 = st.columns([3.5,1.5,0.7,0.5,0.5,0.5,0.5])

            # Name + owner + linked reqs
            owner_str = f' <span style="color:#6E6C66;font-size:.75rem">· {d["owner"]}</span>' \
                        if d.get("owner") else ""
            c1.markdown(
                f'<span style="font-size:.85rem">{icon} <b>{d["name"]}</b></span>'
                f'{mand_tag}{owner_str}',
                unsafe_allow_html=True)
            if d.get("linked_req_ids"):
                c1.markdown(
                    f'<span style="font-size:.7rem;color:#C6A15B">'
                    f'Reqs: {d["linked_req_ids"]}</span>',
                    unsafe_allow_html=True)

            # Status badge
            c2.markdown(
                f'<span style="background:{st_col}22;color:{st_col};padding:.15rem .5rem;'
                f'border-radius:3px;font-size:.72rem;font-weight:600">'
                f'{d.get("status","Expected")}</span>',
                unsafe_allow_html=True)

            # Version
            c3.markdown(
                f'<span style="font-size:.75rem;color:#6E6C66">'
                f'v{d.get("version") or 1}</span>',
                unsafe_allow_html=True)

            # ⬆ Upload / new version
            if c4.button("⬆", key=f"upv_{d['id']}",
                         help="Upload / replace this document"):
                st.session_state["upload_for_doc"] = d["id"]
                st.rerun()

            # 🔍 Analyze — active only when file is uploaded
            if has_file:
                if c5.button("🔍", key=f"ana_{d['id']}",
                             help="Analyze with Claude — extract requirements & changes"):
                    st.session_state["analyze_doc_id"] = d["id"]
                    st.rerun()
            else:
                c5.markdown(
                    '<span style="color:#2A2A2E;font-size:.9rem" '
                    'title="Upload a file first">🔍</span>',
                    unsafe_allow_html=True)

            # ✏ Edit
            if c6.button("✏", key=f"edd_{d['id']}",
                         help="Edit document details"):
                st.session_state["editing_doc"] = d["id"]
                st.rerun()

            st.markdown(
                '<hr class="section-divider" style="margin:.2rem 0">',
                unsafe_allow_html=True)
        st.markdown("")

    # ── Upload against a specific document ────────────────────────────────────
    upload_doc_id = st.session_state.get("upload_for_doc")
    if upload_doc_id:
        target = next((d for d in docs if d["id"]==upload_doc_id), None)
        if target:
            st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
            st.markdown(f"### ⬆ Upload: {target['name']}")
            if target.get("version",1) > 1:
                st.markdown(
                    f'<div class="info-box">Current version: v{target["version"]}. '
                    f'Uploading will create v{target["version"]+1} and archive the previous version.</div>',
                    unsafe_allow_html=True)
            up = st.file_uploader(
                f"Select file for {target['name']}",
                type=["pdf","docx","xlsx","doc","pptx","txt","png","jpg"],
                key=f"upfile_{upload_doc_id}")
            uploader_name = st.text_input("Uploaded by", placeholder="Your name",
                                          key=f"upby_{upload_doc_id}")
            st.text_input("Version notes (optional)",
                          placeholder="e.g. Final version after legal review",
                          key=f"upnotes_{upload_doc_id}")

            c1,c2 = st.columns([2,1])
            if c1.button("✅ Confirm Upload", use_container_width=True, type="primary"):
                if up:
                    _key = f"uploaded_{bid_id}_{upload_doc_id}_{up.name}_{up.size}"
                    if not st.session_state.get(_key):
                        fb = up.read()
                        save_upload(bid_id, up.name, fb,
                                    doc_type=target["doc_type"],
                                    owner=uploader_name or target.get("owner"),
                                    doc_id=upload_doc_id)
                        st.session_state[_key] = True
                    del st.session_state["upload_for_doc"]
                    st.success(f"✅ Uploaded successfully.")
                    st.rerun()
                else:
                    st.error("Please select a file first.")
            if c2.button("Cancel", use_container_width=True):
                del st.session_state["upload_for_doc"]
                st.rerun()

    # ── Edit document details ──────────────────────────────────────────────────
    eid = st.session_state.get("editing_doc")
    if eid:
        doc = next((d for d in docs if d["id"]==eid), None)
        if doc:
            st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
            st.markdown(f"### ✏ Edit — {doc['name']}")

            # Show version history
            versions = get_document_versions(eid)
            if versions:
                with st.expander(f"📂 Version History ({len(versions)} previous versions)"):
                    for v in versions:
                        st.markdown(
                            f'v{v["version"]} — {v.get("created_at","")[:10]} — '
                            f'{v.get("uploaded_by") or "unknown"} — '
                            f'{v.get("file_path","").split("/")[-1] if v.get("file_path") else "—"}',
                            unsafe_allow_html=True)

            with st.form("edit_doc_form"):
                name = st.text_input("Document Name", value=doc["name"])
                c1,c2 = st.columns(2)
                dt   = c1.selectbox("Type", DOC_TYPES,
                                    index=DOC_TYPES.index(doc["doc_type"])
                                    if doc["doc_type"] in DOC_TYPES else 0)
                owner= c2.text_input("Owner", value=doc.get("owner") or "")
                c1,c2,c3 = st.columns(3)
                due  = c1.text_input("Due Date", value=doc.get("due_date") or "",
                                     placeholder="2026-08-03")
                st_  = c2.selectbox("Status",
                                    ["Expected","Uploaded","In Review","Approved",
                                     "Submitted","Blocked","N/A"],
                                    index=["Expected","Uploaded","In Review","Approved",
                                           "Submitted","Blocked","N/A"].index(
                                               doc.get("status","Expected"))
                                    if doc.get("status") in ["Expected","Uploaded",
                                                              "In Review","Approved",
                                                              "Submitted","Blocked","N/A"]
                                    else 0)
                linked = c3.text_input("Linked Req IDs",
                                       value=doc.get("linked_req_ids") or "",
                                       placeholder="M1, R3…")
                mand = st.checkbox("Mandatory submission item",
                                   value=bool(doc.get("mandatory")))
                notes = st.text_area("Notes", value=doc.get("notes") or "", height=60)
                c1,c2,c3 = st.columns([2,1,1])
                sv = c1.form_submit_button("Save", use_container_width=True)
                dl = c2.form_submit_button("Delete", use_container_width=True)
                cx = c3.form_submit_button("Cancel", use_container_width=True)
            if sv:
                upsert_document({"id":eid,"bid_id":bid_id,"name":name,"doc_type":dt,
                    "owner":owner,"due_date":due,"status":st_,
                    "linked_req_ids":linked,"mandatory":1 if mand else 0,
                    "notes":notes,"file_path":None,"file_size":None,"version":None})
                del st.session_state["editing_doc"]
                st.rerun()
            if dl:
                delete_document(eid)
                del st.session_state["editing_doc"]
                st.rerun()
            if cx:
                del st.session_state["editing_doc"]
                st.rerun()

    # ── Add new document / upload ──────────────────────────────────────────────
    st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
    st.markdown("### Add Document")
    tab1, tab2 = st.tabs(["⬆ Upload New File", "📋 Add Expected Document (no file yet)"])

    with tab1:
        c1,c2 = st.columns([2,1])
        up_type = c1.selectbox("Document Type", DOC_TYPES, key="new_up_type")
        up_owner= c2.text_input("Uploaded by", key="new_up_owner")
        up = st.file_uploader("Select file",
                              type=["pdf","docx","xlsx","doc","pptx","txt","png","jpg"],
                              key="new_up_file")
        linked_new = st.text_input("Linked requirement IDs (optional)",
                                   placeholder="M1, R3…", key="new_up_linked")
        mand_new = st.checkbox("Mandatory submission item", key="new_up_mand")
        if up and st.button("⬆ Upload", use_container_width=True, type="primary",
                            key="new_up_btn"):
            _key = f"uploaded_{bid_id}_{up.name}_{up.size}"
            if not st.session_state.get(_key):
                fb = up.read()
                save_upload(bid_id, up.name, fb, doc_type=up_type,
                            owner=up_owner or None)
                # Update linked/mandatory if set
                new_docs = get_documents(bid_id)
                latest = next((d for d in reversed(new_docs)
                               if d["name"]==up.name), None)
                if latest and (linked_new or mand_new):
                    upsert_document({**latest, "linked_req_ids":linked_new,
                                     "mandatory":1 if mand_new else 0})
                st.session_state[_key] = True
                st.success(f"Uploaded: {up.name}")
                st.rerun()

    with tab2:
        with st.form("add_expected", clear_on_submit=True):
            name_e = st.text_input("Document Name *",
                                   placeholder="e.g. Supplement A — Submission Form")
            c1,c2  = st.columns(2)
            dt_e   = c1.selectbox("Type", DOC_TYPES)
            own_e  = c2.text_input("Assigned To / Owner")
            c1,c2,c3 = st.columns(3)
            due_e   = c1.text_input("Due Date", placeholder="2026-08-03")
            linked_e= c2.text_input("Linked Req IDs", placeholder="M1, F1…")
            mand_e  = c3.checkbox("Mandatory")
            notes_e = st.text_area("Notes / Instructions", height=60)
            if st.form_submit_button("Add to Registry", use_container_width=True):
                if name_e:
                    create_expected_document(
                        bid_id=bid_id, name=name_e, doc_type=dt_e,
                        owner=own_e or None, due_date=due_e or None,
                        linked_req_ids=linked_e or None,
                        mandatory=1 if mand_e else 0, notes=notes_e)
                    st.rerun()
                else:
                    st.error("Document name required.")

    # ── Document analysis trigger ──────────────────────────────────────────────
    analyze_id = st.session_state.get("analyze_doc_id")
    if analyze_id:
        doc = next((d for d in docs if d["id"] == analyze_id), None)
        if doc:
            st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
            st.markdown(f"### 🔍 Analyze: {doc['name']}")
            st.markdown(
                '<div class="info-box">Claude will read this document and identify '
                'new requirements, deadline changes, modifications to existing requirements, '
                'and clarifications. You review the findings before anything is applied.</div>',
                unsafe_allow_html=True)

            c1, c2 = st.columns([3, 1])
            if c1.button("🔍 Run Analysis with Claude", use_container_width=True, type="primary",
                         key="run_analysis_btn"):
                from analyst import analyze_addendum
                from database import download_file
                import fitz, base64, anthropic as _ant

                with st.spinner(f"Analyzing {doc['name']}… 20–40 seconds"):
                    try:
                        sp   = doc.get("storage_path") or ""
                        fp   = doc.get("file_path") or ""
                        name_lower = doc["name"].lower()
                        file_bytes = None
                        text = ""

                        # 1. Try Supabase Storage first
                        if sp:
                            file_bytes = download_file(sp)

                        # 2. Fallback: local disk
                        if not file_bytes and fp and not fp.startswith("supabase://"):
                            import os as _os
                            if _os.path.exists(fp):
                                with open(fp, "rb") as f_:
                                    file_bytes = f_.read()

                        # 3. Extract text
                        if file_bytes:
                            if name_lower.endswith(".pdf"):
                                fitz_doc = fitz.open(stream=file_bytes, filetype="pdf")
                                text = "\n".join(p.get_text() for p in fitz_doc)
                            else:
                                text = file_bytes.decode("utf-8", errors="ignore")
                        else:
                            st.error("Could not retrieve file. Try re-uploading the document.")
                            st.stop()

                        if text.strip():
                            reqs   = get_requirements(bid_id)
                            result = analyze_addendum(text, reqs, bid)
                            st.session_state["addendum_result"] = result
                            st.session_state["addendum_source"] = doc["name"]
                            del st.session_state["analyze_doc_id"]
                            st.rerun()
                        else:
                            st.error("Could not extract text from this document.")
                    except Exception as e:
                        st.error(f"Analysis failed: {e}")

            if c2.button("Cancel", use_container_width=True, key="cancel_analysis_btn"):
                del st.session_state["analyze_doc_id"]
                st.rerun()

    # ── Addendum analysis result display ──────────────────────────────────────
    if st.session_state.get("addendum_result"):
        from database import update_bid
        r   = st.session_state["addendum_result"]
        src = st.session_state.get("addendum_source", "")

        st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
        st.markdown(f"### 📋 Analysis: {r.get('document_number','Document')} — {r.get('document_type','')}")
        st.markdown(f'<div class="info-box">{r.get("summary","")}</div>', unsafe_allow_html=True)

        # Deadline changes
        dl = r.get("deadline_changes", {}) or {}
        if dl.get("submission_deadline") or dl.get("clarification_deadline"):
            st.markdown("#### ⏰ Deadline Changes")
            if dl.get("submission_deadline"):
                st.markdown(f'<div class="warn-box">Submission deadline → <strong>{dl["submission_deadline"]}</strong></div>',
                            unsafe_allow_html=True)
            if dl.get("clarification_deadline"):
                st.markdown(f'<div class="warn-box">Clarification deadline → <strong>{dl["clarification_deadline"]}</strong></div>',
                            unsafe_allow_html=True)

        # Key changes
        if r.get("key_changes"):
            st.markdown("#### Key Changes")
            for ch in r["key_changes"]:
                st.markdown(f'<span style="color:#C6A15B;font-size:.85rem">· {ch}</span>',
                            unsafe_allow_html=True)

        # New requirements
        new_reqs = r.get("new_requirements", []) or []
        mod_reqs = r.get("modified_requirements", []) or []
        clars    = r.get("clarifications", []) or []

        if new_reqs:
            st.markdown(f"#### ➕ New Requirements ({len(new_reqs)})")
            for req in new_reqs:
                st.markdown(
                    f'<div style="background:#131316;border-left:3px solid #C6A15B;'
                    f'padding:.5rem .8rem;margin:.25rem 0;font-size:.82rem">'
                    f'<span style="color:#C6A15B;font-weight:700">{req.get("req_id","")}</span> '
                    f'({req.get("category","")}) {req.get("description","")}</div>',
                    unsafe_allow_html=True)

        if mod_reqs:
            st.markdown(f"#### ✏️ Modified Requirements ({len(mod_reqs)})")
            for mod in mod_reqs:
                st.markdown(
                    f'<div style="background:#1A0F00;border-left:3px solid #E67E22;'
                    f'padding:.5rem .8rem;margin:.25rem 0;font-size:.82rem">'
                    f'<span style="color:#E67E22;font-weight:700">{mod.get("req_id","")}</span> — '
                    f'{mod.get("change_description","")}</div>',
                    unsafe_allow_html=True)

        if clars:
            st.markdown(f"#### 💬 Clarifications ({len(clars)})")
            for cl in clars:
                st.markdown(
                    f'<div style="background:#0A1A0A;border-left:3px solid #27AE60;'
                    f'padding:.5rem .8rem;font-size:.82rem;margin:.25rem 0">'
                    f'<strong style="color:#27AE60">{cl.get("topic","")}</strong>: '
                    f'{cl.get("clarification","")}</div>',
                    unsafe_allow_html=True)

        st.markdown("")
        c1, c2 = st.columns([2, 1])

        if c1.button("✅ Apply all changes to bid", use_container_width=True,
                     type="primary", key="apply_changes_btn"):
            applied = 0
            for req in new_reqs:
                upsert_requirement({**req, "id": None, "bid_id": bid_id,
                                    "notes": (req.get("notes","") or "") + f" | Source: {src}"})
                applied += 1
            # Update deadlines if changed
            if dl.get("submission_deadline") or dl.get("clarification_deadline"):
                update_bid(bid_id, {
                    **bid,
                    "submission_deadline":    dl.get("submission_deadline") or bid.get("submission_deadline"),
                    "clarification_deadline": dl.get("clarification_deadline") or bid.get("clarification_deadline"),
                })
            # Log clarifications as notes on linked requirements
            all_reqs = get_requirements(bid_id)
            for cl in clars:
                for rid in (cl.get("affects_req_ids") or []):
                    match = next((r2 for r2 in all_reqs if r2.get("req_id")==rid), None)
                    if match:
                        upsert_requirement({**match,
                            "notes": (match.get("notes","") or "") +
                                     f" | Clarification ({src}): {cl.get('clarification','')[:120]}"})
            del st.session_state["addendum_result"]
            st.session_state.pop("addendum_source", None)
            st.success(f"Applied: {applied} new requirements added. Deadlines and clarifications updated.")
            st.rerun()

        if c2.button("✕ Discard", use_container_width=True, key="discard_changes_btn"):
            del st.session_state["addendum_result"]
            st.session_state.pop("addendum_source", None)
            st.rerun()


def page_outline(bid_id):
    sections=get_outline(bid_id)
    st.markdown("# Proposal Outline")
    st.markdown('<div class="gold-rule"></div>', unsafe_allow_html=True)
    if sections:
        total=len(sections)
        done=sum(1 for s in sections if s["status"]=="Complete")
        c1,c2,c3=st.columns(3)
        c1.metric("Sections",total)
        c2.metric("Complete",done)
        c3.metric("In Progress",sum(1 for s in sections if s["status"]=="In Progress"))
        st.markdown(readiness_bar(done/total*100 if total else 0), unsafe_allow_html=True)
        st.markdown("")
        hcols=st.columns([.7,.7,4,1.5,1.2,1.8,1])
        for h,col in zip(["#","Sec","Title","Owner","Words","Status",""],hcols):
            col.markdown(f'<span style="font-size:.7rem;color:#A9A69D;font-weight:600;text-transform:uppercase">{h}</span>', unsafe_allow_html=True)
        for i,sec in enumerate(sections,1):
            c1,c2,c3,c4,c5,c6,c7=st.columns([.7,.7,4,1.5,1.2,1.8,1])
            c1.markdown(f'<span style="font-size:.78rem;color:#6E6C66">{i}</span>', unsafe_allow_html=True)
            c2.markdown(f'<span style="font-size:.82rem;color:#C6A15B">{sec.get("section_num") or ""}</span>', unsafe_allow_html=True)
            c3.markdown(f'<span style="font-size:.85rem;font-weight:500">{sec["title"]}</span>', unsafe_allow_html=True)
            if sec.get("notes"):
                c3.markdown(f'<span style="font-size:.74rem;color:#6E6C66">{sec["notes"]}</span>', unsafe_allow_html=True)
            c4.markdown(f'<span style="font-size:.82rem">{sec.get("owner") or "—"}</span>', unsafe_allow_html=True)
            c5.markdown(f'<span style="font-size:.78rem;color:#A9A69D">{sec.get("word_limit") or "—"}</span>', unsafe_allow_html=True)
            c6.markdown(status_badge(sec["status"]), unsafe_allow_html=True)
            if c7.button("✏",key=f"es_{sec['id']}"):
                st.session_state["editing_sec"]=sec["id"]
                st.rerun()
            st.markdown('<hr class="section-divider" style="margin:.25rem 0">', unsafe_allow_html=True)
    else:
        st.markdown('<div class="empty-state">No sections yet.</div>', unsafe_allow_html=True)
        st.markdown("### Quick-start template")
        c1,c2=st.columns(2)
        if c1.button("📋 CDA-AMC Coaching RFSO Structure",use_container_width=True):
            for i,(n,t,o,w) in enumerate([
                ("1","Executive Summary","Proposal Lead",500),
                ("2","Understanding of CDA-AMC's Needs","Proposal Lead",400),
                ("3","Coaching Philosophy","Proposal Lead",500),
                ("4","Coaching Methodology","Proposal Lead",600),
                ("5","Approach to the Three Coaching Groups","Proposal Lead",700),
                ("6","Work Plan and Delivery Model","Proposal Lead",500),
                ("7","Coach Selection and Matching Process","Proposal Lead",400),
                ("8","Confidentiality and Ethics","Proposal Lead",300),
                ("9","Team Qualifications and CVs","HR Coordinator",600),
                ("10","Case Study / Testimonial","Business Development",400),
                ("11","Healthcare and NFP Sector Familiarity","Proposal Lead",400),
                ("12","Change Management Experience","Proposal Lead",300),
                ("13","IDEA, Reconciliation, and ESG","Executive Sponsor",400),
                ("14","AI / Non-AI Methodology and Safeguards","Proposal Lead",400),
                ("15","Responses to Five Coaching Questions","Proposal Lead",600),
                ("16","Optional Services","Proposal Lead",200)]):
                upsert_section({"id":None,"bid_id":bid_id,"sort_order":i,"section_num":n,
                    "title":t,"owner":o,"word_limit":w,"status":"Not Started","notes":""})
            st.rerun()
        if c2.button("📄 Generic Consulting Proposal",use_container_width=True):
            for i,(n,t,o,w) in enumerate([
                ("1","Executive Summary","Proposal Lead",400),
                ("2","Understanding of the Requirement","Proposal Lead",500),
                ("3","Proposed Methodology","Proposal Lead",700),
                ("4","Work Plan and Timeline","Proposal Lead",400),
                ("5","Team Qualifications","HR",500),
                ("6","Relevant Experience and Case Studies","Business Development",400),
                ("7","Quality Assurance","Proposal Lead",300),
                ("8","Pricing and Value","Finance",300)]):
                upsert_section({"id":None,"bid_id":bid_id,"sort_order":i,"section_num":n,
                    "title":t,"owner":o,"word_limit":w,"status":"Not Started","notes":""})
            st.rerun()

    eid=st.session_state.get("editing_sec")
    if eid:
        sec=next((s for s in sections if s["id"]==eid),None)
        if sec:
            st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
            st.markdown(f"### Edit — {sec['title']}")
            with st.form("edit_sec"):
                title=st.text_input("Title",value=sec["title"])
                c1,c2,c3,c4=st.columns(4)
                n=c1.text_input("Number",value=sec.get("section_num") or "")
                so=c2.number_input("Order",value=int(sec.get("sort_order") or 0),step=1)
                own=c3.text_input("Owner",value=sec.get("owner") or "")
                wl=c4.number_input("Word Limit",value=int(sec.get("word_limit") or 0),step=50)
                st_=st.selectbox("Status",STATUSES,index=STATUSES.index(sec["status"]) if sec["status"] in STATUSES else 0)
                notes=st.text_area("Notes",value=sec.get("notes") or "",height=60)
                c1,c2,c3=st.columns([2,1,1])
                sv=c1.form_submit_button("Save",use_container_width=True)
                dl=c2.form_submit_button("Delete",use_container_width=True)
                cx=c3.form_submit_button("Cancel",use_container_width=True)
            if sv:
                upsert_section({"id":eid,"bid_id":bid_id,"title":title,"section_num":n,
                    "sort_order":so,"owner":own,"word_limit":wl or None,"status":st_,"notes":notes})
                del st.session_state["editing_sec"]
                st.rerun()
            if dl:
                delete_section(eid)
                del st.session_state["editing_sec"]
                st.rerun()
            if cx:
                del st.session_state["editing_sec"]
                st.rerun()

    st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
    with st.expander("➕ Add Section"):
        with st.form("add_sec",clear_on_submit=True):
            title=st.text_input("Title *")
            c1,c2,c3,c4=st.columns(4)
            n=c1.text_input("Number")
            so=c2.number_input("Order",value=len(sections),step=1)
            own=c3.text_input("Owner")
            wl=c4.number_input("Word Limit",value=0,step=50)
            notes=st.text_area("Notes",height=50)
            if st.form_submit_button("Add",use_container_width=True):
                if title:
                    upsert_section({"id":None,"bid_id":bid_id,"title":title,"section_num":n,
                        "sort_order":so,"owner":own,"word_limit":wl or None,
                        "status":"Not Started","notes":notes})
                    st.rerun()

# ═════════════════════════════════════════════════════════════════════════════
# PAGE: AI ANALYST
# ═════════════════════════════════════════════════════════════════════════════
def _score_colour(score):
    if score>=75:
        return "#27AE60"
    if score>=50:
        return "#E67E22"
    return "#C0392B"

def _dim_bar(score):
    col=_score_colour(score*10)
    return (f'<div style="display:flex;align-items:center;gap:.6rem">'
            f'<div style="background:#1A1A1E;border-radius:3px;height:6px;width:80px">'
            f'<div style="background:{col};width:{score*10}%;height:6px;border-radius:3px"></div></div>'
            f'<span style="color:{col};font-weight:600;font-size:.85rem">{score}/10</span></div>')

def _rec_badge(rec):
    colours={"BID":"#27AE60","NO BID":"#C0392B","CONDITIONAL BID":"#E67E22"}
    col=colours.get(rec,"#6E6C66")
    return (f'<span style="background:{col};color:#fff;padding:.3rem 1rem;'
            f'border-radius:4px;font-weight:700;font-size:1rem">{rec}</span>')

def page_ai_analyst(bid_id):
    from analyst import (compliance_review, missing_evidence,
                         generate_clarification_questions, bid_no_bid_score)
    bid=get_bid(bid_id)
    reqs=get_requirements(bid_id)
    st.markdown("# AI Compliance Assistant")
    st.markdown('<div class="gold-rule"></div>', unsafe_allow_html=True)

    if not api_key_configured() and not st.session_state.get("anthropic_api_key"):
        st.markdown('<div class="warn-box">No Anthropic API key. Add <code>ANTHROPIC_API_KEY=sk-ant-…</code> to your <code>.env</code> file.</div>', unsafe_allow_html=True)
        key=st.text_input("Or paste key for this session",type="password",placeholder="sk-ant-…")
        if st.button("Save") and key:
            st.session_state["anthropic_api_key"]=key
            st.rerun()
        st.stop()

    if not reqs:
        st.markdown('<div class="info-box">No requirements yet — upload an RFP or add them manually in the Compliance Matrix.</div>', unsafe_allow_html=True)
        st.stop()

    tab1,tab2,tab3,tab4=st.tabs(["📋 Compliance Review","⚠️ Missing Evidence","❓ Clarification Questions","🎯 Bid / No-Bid"])

    with tab1:
        st.markdown("### Proposal Section Review")
        st.markdown('<div class="info-box">Paste a draft section. The AI checks it against every requirement and identifies what is addressed, weak, or missing.</div>', unsafe_allow_html=True)
        cats=["All"]+sorted(set(r["category"] for r in reqs))
        c1,c2=st.columns([2,3])
        cf=c1.selectbox("Filter by category",cats,key="cr_cat")
        filtered=reqs if cf=="All" else [r for r in reqs if r["category"]==cf]
        c2.markdown(f'<div style="padding-top:1.8rem;color:#A9A69D;font-size:.82rem">{len(filtered)} requirements selected</div>', unsafe_allow_html=True)
        draft=st.text_area("Paste draft text",height=200,placeholder="Paste any proposal section here…",key="cr_draft")
        if st.button("🔍 Review against requirements",key="cr_run",use_container_width=True,type="primary"):
            if not draft.strip():
                st.error("Paste some draft text first.")
            else:
                with st.spinner("Reviewing…"):
                    try:
                        st.session_state["cr_result"]=compliance_review(draft,filtered)
                    except Exception as e:
                        st.error(f"Review failed: {e}")
        if "cr_result" in st.session_state:
            r=st.session_state["cr_result"]
            st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
            score=r.get("overall_score",0)
            c1,c2=st.columns([1,3])
            c1.markdown(f'<div style="text-align:center;background:#131316;border:1px solid #2A2A2E;border-radius:6px;padding:1rem">'
                        f'<div style="font-size:2.5rem;font-weight:700;color:{_score_colour(score)}">{score}</div>'
                        f'<div style="font-size:.72rem;color:#A9A69D;text-transform:uppercase">Compliance Score</div></div>', unsafe_allow_html=True)
            c2.markdown(f'<div class="info-box">{r.get("summary","")}</div>', unsafe_allow_html=True)
            if r.get("critical_gaps"):
                for g in r["critical_gaps"]:
                    c2.markdown(f'<span style="color:#C0392B">⚠ {g}</span>', unsafe_allow_html=True)
            st.markdown("")
            c1,c2,c3=st.columns(3)
            with c1:
                st.markdown(f'<span style="color:#27AE60;font-weight:600">✓ Addressed ({len(r.get("addressed",[]))})</span>', unsafe_allow_html=True)
                for item in r.get("addressed",[]):
                    st.markdown(f'<div style="background:#0A1A0A;border:1px solid #1E3A1E;border-radius:4px;padding:.4rem .6rem;margin:.2rem 0;font-size:.8rem">'
                                f'<span style="color:#27AE60;font-weight:600">{item.get("req_id","")}</span> {item.get("finding","")}</div>', unsafe_allow_html=True)
            with c2:
                st.markdown(f'<span style="color:#E67E22;font-weight:600">~ Weak ({len(r.get("weak",[]))})</span>', unsafe_allow_html=True)
                for item in r.get("weak",[]):
                    st.markdown(f'<div style="background:#1A0F00;border:1px solid #3A2A00;border-radius:4px;padding:.4rem .6rem;margin:.2rem 0;font-size:.8rem">'
                                f'<span style="color:#E67E22;font-weight:600">{item.get("req_id","")}</span> {item.get("finding","")}'
                                f'<br><span style="color:#C6A15B;font-size:.75rem">→ {item.get("suggestion","")}</span></div>', unsafe_allow_html=True)
            with c3:
                st.markdown(f'<span style="color:#C0392B;font-weight:600">✗ Missing ({len(r.get("missing",[]))})</span>', unsafe_allow_html=True)
                for item in r.get("missing",[]):
                    st.markdown(f'<div style="background:#1A0000;border:1px solid #3A0000;border-radius:4px;padding:.4rem .6rem;margin:.2rem 0;font-size:.8rem">'
                                f'<span style="color:#C0392B;font-weight:600">{item.get("req_id","")}</span> {item.get("finding","")}'
                                f'<br><span style="color:#E57373;font-size:.75rem">→ {item.get("suggestion","")}</span></div>', unsafe_allow_html=True)

    with tab2:
        st.markdown("### At-Risk Requirements Scan")
        st.markdown('<div class="info-box">Scans the entire compliance matrix and surfaces unassigned owners, missing evidence, approaching deadlines, and blocked items.</div>', unsafe_allow_html=True)
        if st.button("⚠️ Scan for at-risk items",key="me_run",use_container_width=True,type="primary"):
            with st.spinner("Scanning…"):
                try:
                    st.session_state["me_result"]=missing_evidence(reqs,bid)
                except Exception as e:
                    st.error(f"Scan failed: {e}")
        if "me_result" in st.session_state:
            r=st.session_state["me_result"]
            st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
            risk=r.get("risk_level","Unknown")
            rc={"High":"#C0392B","Medium":"#E67E22","Low":"#27AE60"}.get(risk,"#6E6C66")
            c1,c2=st.columns([1,4])
            c1.markdown(f'<div style="text-align:center;background:#131316;border:2px solid {rc};border-radius:6px;padding:1rem">'
                        f'<div style="font-size:1.4rem;font-weight:700;color:{rc}">{risk}</div>'
                        f'<div style="font-size:.72rem;color:#A9A69D;text-transform:uppercase">Risk Level</div></div>', unsafe_allow_html=True)
            c2.markdown(f'<div class="warn-box">{r.get("summary","")}</div>', unsafe_allow_html=True)
            if r.get("recommendation"):
                c2.markdown(f'<div style="background:#1B2A41;border-left:3px solid #C6A15B;padding:.6rem 1rem;border-radius:0 4px 4px 0;font-size:.85rem;margin-top:.5rem">'
                            f'<strong>Do this today:</strong> {r["recommendation"]}</div>', unsafe_allow_html=True)
            st.markdown("")
            if r.get("critical"):
                st.markdown(f'<span style="color:#C0392B;font-weight:600">CRITICAL ({len(r["critical"])})</span>', unsafe_allow_html=True)
                for item in r["critical"]:
                    st.markdown(f'<div style="background:#1A0000;border:1px solid #3A0000;border-radius:4px;padding:.6rem .8rem;margin:.3rem 0">'
                                f'<span style="color:#C0392B;font-weight:700">{item.get("req_id","")}</span> — {item.get("reason","")}'
                                f'<br><span style="color:#E57373;font-size:.8rem">Action: {item.get("action","")}</span>'
                                f'{"<br><span style=color:#A9A69D;font-size:.75rem>By: "+item.get("by_when","")+"</span>" if item.get("by_when") else ""}</div>', unsafe_allow_html=True)
            if r.get("at_risk"):
                st.markdown(f'<span style="color:#E67E22;font-weight:600">AT RISK ({len(r["at_risk"])})</span>', unsafe_allow_html=True)
                for item in r["at_risk"]:
                    st.markdown(f'<div style="background:#1A0F00;border:1px solid #3A2A00;border-radius:4px;padding:.5rem .8rem;margin:.25rem 0;font-size:.82rem">'
                                f'<span style="color:#E67E22;font-weight:600">{item.get("req_id","")}</span> — {item.get("reason","")}'
                                f'<br><span style="color:#C6A15B">→ {item.get("action","")}</span></div>', unsafe_allow_html=True)
            if r.get("unassigned"):
                st.markdown(f'<div style="background:#131316;border:1px solid #2A2A2E;border-radius:4px;padding:.6rem .8rem;margin:.5rem 0;font-size:.82rem">'
                            f'<span style="color:#A9A69D;font-weight:600">Unassigned owners: </span>{", ".join(r["unassigned"])}</div>', unsafe_allow_html=True)

    with tab3:
        st.markdown("### Clarification Question Generator")
        st.markdown('<div class="info-box">Generates strategic questions ranked by importance, phrased to protect your competitive position.</div>', unsafe_allow_html=True)
        extra=st.text_area("Additional context (optional)",height=80,placeholder="Ambiguities, assumptions to confirm…",key="cq_extra")
        if st.button("❓ Generate clarification questions",key="cq_run",use_container_width=True,type="primary"):
            with st.spinner("Generating…"):
                try:
                    st.session_state["cq_result"]=generate_clarification_questions(bid,reqs,extra)
                except Exception as e:
                    st.error(f"Generation failed: {e}")
        if "cq_result" in st.session_state:
            r=st.session_state["cq_result"]
            st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
            if r.get("submission_advice"):
                st.markdown(f'<div class="info-box"><strong>Submission advice:</strong> {r["submission_advice"]}</div>', unsafe_allow_html=True)
            questions=sorted(r.get("questions",[]),key=lambda q:{"Critical":0,"High":1,"Medium":2}.get(q.get("priority","Medium"),2))
            for q in questions:
                pc=PRIORITY_COLOURS.get(q.get("priority","Medium"),"#6E6C66")
                relates=", ".join(q.get("relates_to",[]))
                st.markdown(f'<div style="background:#131316;border:1px solid #2A2A2E;border-left:3px solid {pc};border-radius:0 4px 4px 0;padding:.7rem 1rem;margin:.4rem 0">'
                            f'<div style="display:flex;justify-content:space-between;margin-bottom:.3rem">'
                            f'<span style="font-weight:600;color:#EDEAE2">{q.get("id","")}. {q.get("question","")}</span>'
                            f'<span style="font-size:.72rem;color:{pc};white-space:nowrap;margin-left:.5rem">{q.get("priority","")}</span></div>'
                            f'<div style="font-size:.76rem;color:#6E6C66;font-style:italic">Why this matters: {q.get("rationale","")}</div>'
                            f'{"<div style=font-size:.72rem;color:#A9A69D;margin-top:.2rem>Relates to: "+relates+"</div>" if relates else ""}'
                            f'</div>', unsafe_allow_html=True)
            if questions:
                plain="\n\n".join(f"{q.get('id','')}. {q.get('question','')}" for q in questions)
                st.download_button("⬇ Download questions (plain text)",data=plain,
                    file_name=f"clarification_questions_{bid.get('file_number','bid')}.txt",
                    mime="text/plain",use_container_width=True)

    with tab4:
        st.markdown("### Bid / No-Bid Assessment")
        st.markdown('<div class="info-box">Scores this opportunity across five strategic dimensions and produces a recommendation.</div>', unsafe_allow_html=True)
        fc=st.text_area("Your firm's relevant capabilities",height=120,
            placeholder="e.g. Phoenix Consulting International is the authorised Hogan distributor for the GCC…",key="bn_context")
        if st.button("🎯 Generate bid/no-bid assessment",key="bn_run",use_container_width=True,type="primary"):
            with st.spinner("Scoring opportunity…"):
                try:
                    st.session_state["bn_result"]=bid_no_bid_score(bid,reqs,fc)
                except Exception as e:
                    st.error(f"Assessment failed: {e}")
        if "bn_result" in st.session_state:
            r=st.session_state["bn_result"]
            st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
            c1,c2=st.columns([1,3])
            with c1:
                st.markdown(f'<div style="text-align:center;background:#131316;border:1px solid #2A2A2E;border-radius:6px;padding:1.2rem .8rem">'
                            f'{_rec_badge(r.get("recommendation","?"))}'
                            f'<div style="margin-top:.8rem"><div style="font-size:2rem;font-weight:700;color:{_score_colour(r.get("overall_score",0))}">{r.get("overall_score",0)}</div>'
                            f'<div style="font-size:.7rem;color:#A9A69D;text-transform:uppercase">Overall Score</div></div>'
                            f'<div style="margin-top:.5rem;font-size:.75rem;color:#6E6C66">Confidence: {r.get("confidence","?")}</div></div>', unsafe_allow_html=True)
            with c2:
                st.markdown(f'<div class="info-box">{r.get("summary","")}</div>', unsafe_allow_html=True)
                for cond in r.get("conditions",[]):
                    st.markdown(f'<span style="color:#E67E22;font-size:.82rem">⚡ {cond}</span>', unsafe_allow_html=True)
            st.markdown("#### Dimension Scores")
            dims=r.get("dimensions",{})
            for key,label in [("strategic_fit","Strategic Fit"),("capability_fit","Capability Fit"),
                               ("competitive_position","Competitive Position"),
                               ("resource_availability","Resource Availability"),("risk","Risk")]:
                d=dims.get(key,{})
                score=d.get("score",0)
                with st.expander(f"{label}  {_dim_bar(score)}",expanded=False):
                    st.markdown(f'**Rationale:** {d.get("rationale","")}')
                    if d.get("evidence"):
                        st.markdown(f'*{d.get("evidence","")}*')
            c1,c2=st.columns(2)
            with c1:
                if r.get("win_themes"):
                    st.markdown("#### Win Themes")
                    for t in r["win_themes"]:
                        st.markdown(f'<span style="color:#27AE60">✓ {t}</span>', unsafe_allow_html=True)
            with c2:
                if r.get("red_flags"):
                    st.markdown("#### Red Flags")
                    for f_ in r["red_flags"]:
                        st.markdown(f'<span style="color:#C0392B">⚠ {f_}</span>', unsafe_allow_html=True)



# ═════════════════════════════════════════════════════════════════════════════
# PAGE: DELIVERABLES (Services Register)
# ═════════════════════════════════════════════════════════════════════════════
DEL_CATEGORIES = ["Core Service", "Optional Service", "Call-up Mechanic", "Reporting"]

def page_deliverables(bid_id):
    bid  = get_bid(bid_id)
    dels = get_deliverables(bid_id)
    reqs = get_requirements(bid_id)

    st.markdown("# Services & Deliverables Register")
    st.markdown('<div class="gold-rule"></div>', unsafe_allow_html=True)
    st.markdown('<div class="info-box">This register captures the <strong>services being procured</strong> — '
                'what the client is buying, how it is structured, and how it will be priced. '
                'It is drawn from the Statement of Work, not the submission requirements.</div>',
                unsafe_allow_html=True)
    st.markdown("")

    # ── Action bar ────────────────────────────────────────────────────────────
    c1, c2, c3 = st.columns([3, 1, 1])
    with c2:
        if dels:
            try:
                pdf_bytes = _services_pdf(bid, dels)
                slug = (bid.get("client") or "bid").replace(" ", "_")[:30]
                st.download_button("⬇ Export PDF", data=pdf_bytes,
                    file_name=f"services_register_{slug}.pdf",
                    mime="application/pdf", use_container_width=True)
            except Exception as e:
                st.error(f"PDF error: {e}")
    with c3:
        if not dels:
            if st.button("⚡ Load from RFP", use_container_width=True, type="primary"):
                _auto_populate_services(bid_id, reqs, bid)
                st.rerun()

    # ── Summary ───────────────────────────────────────────────────────────────
    if dels:
        core     = [d for d in dels if not d.get("optional")]
        optional = [d for d in dels if d.get("optional")]
        priced_ai    = [d for d in dels if d.get("price_ai")]
        priced_nonai = [d for d in dels if d.get("price_non_ai")]

        c1,c2,c3,c4 = st.columns(4)
        c1.metric("Core Services",     len(core))
        c2.metric("Optional Services", len(optional))
        c3.metric("AI Priced",         len(priced_ai))
        c4.metric("Non-AI Priced",     len(priced_nonai))
        st.markdown("")

        # ── Pricing summary table ─────────────────────────────────────────────
        has_price = any(d.get("price_ai") or d.get("price_non_ai") for d in dels)
        if has_price:
            st.markdown("### Pricing Summary")
            total_ai    = sum(d.get("price_ai")     or 0 for d in dels if not d.get("optional"))
            total_nonai = sum(d.get("price_non_ai") or 0 for d in dels if not d.get("optional"))
            total_ai_all    = sum(d.get("price_ai")     or 0 for d in dels)
            total_nonai_all = sum(d.get("price_non_ai") or 0 for d in dels)

            c1,c2 = st.columns(2)
            if total_ai:
                c1.markdown(
                    f'<div style="background:#131316;border:1px solid #2A2A2E;border-left:3px solid #2471A3;'
                    f'border-radius:0 4px 4px 0;padding:.8rem 1rem">'
                    f'<div style="font-size:.72rem;color:#A9A69D;text-transform:uppercase;letter-spacing:.06em">Option 1 — AI-Assisted (Core)</div>'
                    f'<div style="font-size:1.6rem;font-weight:700;color:#EDEAE2">CAD {total_ai:,.2f}</div>'
                    f'{"<div style=font-size:.75rem;color:#6E6C66>+ CAD " + f"{total_ai_all - total_ai:,.2f}" + " optional services</div>" if total_ai_all > total_ai else ""}'
                    f'</div>', unsafe_allow_html=True)
            if total_nonai:
                c2.markdown(
                    f'<div style="background:#131316;border:1px solid #2A2A2E;border-left:3px solid #1E8449;'
                    f'border-radius:0 4px 4px 0;padding:.8rem 1rem">'
                    f'<div style="font-size:.72rem;color:#A9A69D;text-transform:uppercase;letter-spacing:.06em">Option 2 — Non-AI / Human-Only (Core)</div>'
                    f'<div style="font-size:1.6rem;font-weight:700;color:#EDEAE2">CAD {total_nonai:,.2f}</div>'
                    f'{"<div style=font-size:.75rem;color:#6E6C66>+ CAD " + f"{total_nonai_all - total_nonai:,.2f}" + " optional services</div>" if total_nonai_all > total_nonai else ""}'
                    f'</div>', unsafe_allow_html=True)
            st.markdown("")

        # ── Services grouped by category ──────────────────────────────────────
        CAT_COLORS = {
            "Core Service":       "#2471A3",
            "Optional Service":   "#7D3C98",
            "Call-up Mechanic":   "#C6A15B",
            "Reporting":          "#1E8449",
        }

        for cat in DEL_CATEGORIES:
            cat_dels = [d for d in dels if d.get("category") == cat]
            if not cat_dels:
                continue
            col = CAT_COLORS.get(cat, "#6E6C66")
            st.markdown(
                f'<div style="background:{col}22;border-left:3px solid {col};'
                f'padding:.5rem 1rem;border-radius:0 4px 4px 0;margin:.6rem 0 .3rem 0">'
                f'<span style="color:{col};font-weight:700;font-size:.82rem;letter-spacing:.06em">'
                f'{cat.upper()} ({len(cat_dels)})</span></div>',
                unsafe_allow_html=True)

            hcols = st.columns([.5, 2.2, 2.8, 1.2, 1.2, 1.6, 1.6, .5])
            for h, hcol in zip(["ID","Service","Description / Scope",
                                  "Duration","Volume / Unit",
                                  "Price (AI)","Price (Non-AI)",""], hcols):
                hcol.markdown(f'<span style="font-size:.7rem;color:#A9A69D;'
                              f'font-weight:600;text-transform:uppercase">{h}</span>',
                              unsafe_allow_html=True)

            for d in cat_dels:
                c1,c2,c3,c4,c5,c6,c7,c8 = st.columns([.5,2.2,2.8,1.2,1.2,1.6,1.6,.5])
                c1.markdown(f'<span style="font-size:.82rem;color:{col};font-weight:700">'
                            f'{d.get("service_id") or "—"}</span>', unsafe_allow_html=True)

                c2.markdown(f'<span style="font-size:.88rem;font-weight:600">{d["title"]}</span>',
                            unsafe_allow_html=True)
                if d.get("linked_req_ids"):
                    c2.markdown(f'<span style="font-size:.7rem;color:#6E6C66">'
                                f'Ref: {d["linked_req_ids"]}</span>', unsafe_allow_html=True)

                c3.markdown(f'<span style="font-size:.8rem;color:#A9A69D">'
                            f'{d.get("description") or "—"}</span>', unsafe_allow_html=True)

                c4.markdown(f'<span style="font-size:.8rem">{d.get("duration") or "—"}</span>',
                            unsafe_allow_html=True)

                vol  = d.get("volume") or "—"
                unit = d.get("unit") or ""
                c5.markdown(f'<span style="font-size:.8rem">{vol}</span><br>'
                            f'<span style="font-size:.72rem;color:#6E6C66">{unit}</span>',
                            unsafe_allow_html=True)

                ai_p = f'CAD {d["price_ai"]:,.2f}' if d.get("price_ai") else "—"
                c6.markdown(f'<span style="font-size:.85rem;color:#EDEAE2">{ai_p}</span>',
                            unsafe_allow_html=True)

                na_p = f'CAD {d["price_non_ai"]:,.2f}' if d.get("price_non_ai") else "—"
                c7.markdown(f'<span style="font-size:.85rem;color:#EDEAE2">{na_p}</span>',
                            unsafe_allow_html=True)

                if c8.button("✏", key=f"eds_{d['id']}"):
                    st.session_state["editing_svc"] = d["id"]
                    st.rerun()
                st.markdown('<hr class="section-divider" style="margin:.25rem 0">',
                            unsafe_allow_html=True)
            st.markdown("")

    else:
        st.markdown(
            '<div class="info-box">No services defined yet. Click <strong>Load from RFP</strong> '
            'to auto-populate from the extracted requirements, or add manually below.</div>',
            unsafe_allow_html=True)

    # ── Edit panel ────────────────────────────────────────────────────────────
    eid = st.session_state.get("editing_svc")
    if eid:
        svc = next((d for d in dels if d["id"] == eid), None)
        if svc:
            st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
            st.markdown(f"### Edit — {svc['title']}")
            with st.form("edit_svc"):
                c1,c2,c3 = st.columns(3)
                title = c1.text_input("Service Title", value=svc["title"])
                sid   = c2.text_input("ID", value=svc.get("service_id") or "")
                cat   = c3.selectbox("Category", DEL_CATEGORIES,
                                     index=DEL_CATEGORIES.index(svc.get("category","Core Service"))
                                     if svc.get("category") in DEL_CATEGORIES else 0)
                desc = st.text_area("Description / Scope", value=svc.get("description") or "", height=80)
                c1,c2,c3 = st.columns(3)
                dur  = c1.text_input("Duration", value=svc.get("duration") or "",
                                     placeholder="e.g. 12 months")
                vol  = c2.text_input("Volume", value=svc.get("volume") or "",
                                     placeholder="e.g. 24 hours")
                unit = c3.text_input("Unit", value=svc.get("unit") or "",
                                     placeholder="e.g. per engagement")
                c1,c2,c3,c4 = st.columns(4)
                pai  = c1.number_input("Price — AI Option (CAD)",
                                       value=float(svc.get("price_ai") or 0), step=100.0, min_value=0.0)
                pna  = c2.number_input("Price — Non-AI Option (CAD)",
                                       value=float(svc.get("price_non_ai") or 0), step=100.0, min_value=0.0)
                opt  = c3.checkbox("Optional service", value=bool(svc.get("optional")))
                so   = c4.number_input("Order", value=int(svc.get("sort_order") or 0), step=1)
                linked = st.text_input("Linked Req IDs", value=svc.get("linked_req_ids") or "",
                                       placeholder="§4.6, R3…")
                notes = st.text_area("Notes", value=svc.get("notes") or "", height=60)
                c1,c2,c3 = st.columns([2,1,1])
                sv = c1.form_submit_button("Save", use_container_width=True)
                dl = c2.form_submit_button("Delete", use_container_width=True)
                cx = c3.form_submit_button("Cancel", use_container_width=True)
            if sv:
                upsert_deliverable({"id":eid,"bid_id":bid_id,"title":title,
                    "service_id":sid,"category":cat,"description":desc,
                    "duration":dur,"volume":vol,"unit":unit,
                    "price_ai":pai or None,"price_non_ai":pna or None,
                    "optional":1 if opt else 0,"sort_order":so,
                    "linked_req_ids":linked,"notes":notes})
                del st.session_state["editing_svc"]
                st.rerun()
            if dl:
                delete_deliverable(eid)
                del st.session_state["editing_svc"]
                st.rerun()
            if cx:
                del st.session_state["editing_svc"]
                st.rerun()

    # ── Add service ───────────────────────────────────────────────────────────
    st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
    with st.expander("➕ Add Service"):
        with st.form("add_svc", clear_on_submit=True):
            c1,c2,c3 = st.columns(3)
            title = c1.text_input("Service Title *")
            sid   = c2.text_input("ID", placeholder="S1, OPT1…")
            cat   = c3.selectbox("Category", DEL_CATEGORIES)
            desc  = st.text_area("Description / Scope", height=70)
            c1,c2,c3 = st.columns(3)
            dur  = c1.text_input("Duration",  placeholder="e.g. 6 months")
            vol  = c2.text_input("Volume",    placeholder="e.g. 12 hours")
            unit = c3.text_input("Unit",      placeholder="e.g. per engagement")
            c1,c2,c3,c4 = st.columns(4)
            pai  = c1.number_input("Price — AI (CAD)",     min_value=0.0, step=100.0)
            pna  = c2.number_input("Price — Non-AI (CAD)", min_value=0.0, step=100.0)
            opt  = c3.checkbox("Optional service")
            linked = c4.text_input("Linked Refs", placeholder="§4.6, R3…")
            notes = st.text_area("Notes", height=50)
            if st.form_submit_button("Add Service", use_container_width=True):
                if title:
                    upsert_deliverable({"id":None,"bid_id":bid_id,
                        "sort_order":len(dels),"service_id":sid,
                        "title":title,"description":desc,"category":cat,
                        "duration":dur,"volume":vol,"unit":unit,
                        "price_ai":pai or None,"price_non_ai":pna or None,
                        "optional":1 if opt else 0,
                        "linked_req_ids":linked,"notes":notes})
                    st.rerun()
                else:
                    st.error("Title is required.")


def _auto_populate_services(bid_id, reqs, bid):
    """Pre-populate services from the Statement of Work based on extracted requirements."""
    # Standard coaching groups from CDA-AMC RFSO §4.6 — or generic if not recognized
    notes_lower = (bid.get("notes") or "").lower()
    is_coaching = any(w in notes_lower for w in ["coach","coaching","mentor"])

    if is_coaching:
        services = [
            {"service_id":"S1","title":"Group 1 — Executive Coaching",
             "description":"12-month coaching engagement for executive-level leaders. "
                           "24 coaching hours total. Includes chemistry meeting, triangulation "
                           "session with people-leader, and structured coaching cycle.",
             "category":"Core Service","duration":"12 months","volume":"24 hours",
             "unit":"per engagement","optional":0,
             "linked_req_ids":"§4.6 II(a), R3","notes":""},
            {"service_id":"S2","title":"Group 2 — Select Leader Coaching",
             "description":"6-month coaching engagement for select leaders seeking development. "
                           "12 coaching hours total. Covers high-potential and development-opportunity leaders.",
             "category":"Core Service","duration":"6 months","volume":"12 hours",
             "unit":"per engagement","optional":0,
             "linked_req_ids":"§4.6 II(b), R3","notes":"Groups 2 and 3 are majority of volume"},
            {"service_id":"S3","title":"Group 3 — New Leader Coaching",
             "description":"3-month coaching engagement for newly promoted or acquired leaders. "
                           "6 coaching hours total. Focused on role alignment and measurable results.",
             "category":"Core Service","duration":"3 months","volume":"6 hours",
             "unit":"per engagement","optional":0,
             "linked_req_ids":"§4.6 II(c), R3","notes":""},
            {"service_id":"S4","title":"Chemistry Meeting",
             "description":"Initial meeting between coach and employee to assess fit. "
                           "If not a fit, vendor has up to 5 business days to propose an alternative coach.",
             "category":"Call-up Mechanic","duration":"One session","volume":"1 hour",
             "unit":"per engagement","optional":0,
             "linked_req_ids":"§4.6 I(a)","notes":"If substitution fails, CDA-AMC may select alternate vendor"},
            {"service_id":"S5","title":"Triangulation Meeting",
             "description":"First formal coaching session including the employee's people-leader. "
                           "Sets development goals and defines observable outcomes and measurement approach.",
             "category":"Call-up Mechanic","duration":"First session","volume":"1 hour",
             "unit":"per engagement","optional":0,
             "linked_req_ids":"§4.6 I(c)","notes":"Included within total coaching hours"},
            {"service_id":"OPT1","title":"360-Degree Assessment",
             "description":"Multi-rater feedback assessment gathering input from manager, peers, "
                           "and direct reports. Must be requested early and priced separately.",
             "category":"Optional Service","duration":"As requested","volume":"Per participant",
             "unit":"per participant","optional":1,
             "linked_req_ids":"§4.6 V","notes":"Must be priced separately; declining does not diminish core coaching"},
            {"service_id":"OPT2","title":"Psychometric / Personality Assessment",
             "description":"Validated psychometric instrument (e.g. Hogan) providing leadership "
                           "potential, derailer, and values insight to inform coaching goals.",
             "category":"Optional Service","duration":"As requested","volume":"Per participant",
             "unit":"per participant","optional":1,
             "linked_req_ids":"§4.6 V","notes":"Propose Hogan suite as optional — confirm via clarification Q"},
            {"service_id":"OPT3","title":"Leadership Assessment Report",
             "description":"Written assessment report synthesising psychometric and coaching data "
                           "into a structured leadership profile and development recommendations.",
             "category":"Optional Service","duration":"As requested","volume":"Per participant",
             "unit":"per participant","optional":1,
             "linked_req_ids":"§4.6 V","notes":""},
            {"service_id":"SOA1","title":"Standing Offer Agreement (SOA) — Call-up Mechanic",
             "description":"No guaranteed volume. Each engagement triggered by a written Call-up "
                           "from a CDA-AMC representative. Services, deliverables, and fees stated per call-up. "
                           "CDA-AMC may award more than one SOA. Agreement valid Oct 1, 2026 – Sep 30, 2029.",
             "category":"Call-up Mechanic","duration":"Oct 2026 – Sep 2029","volume":"No guaranteed volume",
             "unit":"per call-up","optional":0,
             "linked_req_ids":"§4.7","notes":"PCHO clause: other pan-Canadian health orgs may access same services and pricing"},
            {"service_id":"REP1","title":"Post-Engagement Progress Update",
             "description":"Confidential summary of coaching progress and goal achievement shared "
                           "between coach, participant, and people-leader at end of engagement.",
             "category":"Reporting","duration":"End of engagement","volume":"Per engagement",
             "unit":"per engagement","optional":0,
             "linked_req_ids":"§4.6 I(c)","notes":"Confidential — no individual session content disclosed"},
        ]
    else:
        # Generic services template for non-coaching bids
        services = [
            {"service_id":"S1","title":"Core Service Delivery",
             "description":"Primary service as described in the Statement of Work.",
             "category":"Core Service","duration":"Per SOW","volume":"As specified",
             "unit":"per engagement","optional":0,"linked_req_ids":"§4.0","notes":""},
            {"service_id":"OPT1","title":"Optional Services",
             "description":"Additional services not included in the standard package.",
             "category":"Optional Service","duration":"As requested","volume":"Per request",
             "unit":"per item","optional":1,"linked_req_ids":"","notes":"Price separately"},
        ]

    for i, s in enumerate(services):
        upsert_deliverable({**s,"id":None,"bid_id":bid_id,"sort_order":i,
            "price_ai":None,"price_non_ai":None})


def _services_pdf(bid, dels):
    """McKinsey-style services register PDF."""
    import io
    from reportlab.lib.pagesizes import landscape, A4
    from reportlab.lib.units import mm
    from reportlab.lib.colors import HexColor
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                     Table, TableStyle, HRFlowable, KeepTogether)
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from pdf_styles import (
        pp, safe, fmt_cad, status_para, cover_header, make_footer,
        content_w, STYLES, CAT_ACCENT,
        C_NAVY, C_BLUE, C_BLUE_L, C_WHITE, C_BLACK,
        C_GREY_1, C_GREY_2, C_GREY_3, C_GREY_4,
        PW_L, ML, MR, MT, MB, _font,
    )

    CAT_ORDER = ["Core Service", "Call-up Mechanic", "Optional Service", "Reporting"]

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4),
        leftMargin=ML, rightMargin=MR,
        topMargin=MT, bottomMargin=MB+8*mm,
        title=f"Services Register — {bid.get('client','')}")

    footer = make_footer(
        f"{bid.get('client','')}  ·  {bid.get('title','')}  ·  Services & Deliverables Register",
        landscape_mode=True)

    CW = content_w(True)

    story = []
    cover_header(story, bid, "Services & Deliverables Register")

    # Pricing summary scorecard
    core_ai    = sum(d.get("price_ai")     or 0 for d in dels if not d.get("optional"))
    core_nonai = sum(d.get("price_non_ai") or 0 for d in dels if not d.get("optional"))
    opt_ai     = sum(d.get("price_ai")     or 0 for d in dels if d.get("optional"))
    opt_nonai  = sum(d.get("price_non_ai") or 0 for d in dels if d.get("optional"))

    if core_ai or core_nonai:
        sc_data = [
            [pp("OPTION 1 — AI-ASSISTED DELIVERY", "price_lbl"),
             pp("OPTION 2 — HUMAN-ONLY DELIVERY",  "price_lbl")],
            [pp(fmt_cad(core_ai) if core_ai else "To be priced", "price_lg"),
             pp(fmt_cad(core_nonai) if core_nonai else "To be priced", "price_lg")],
            [pp(f"Core services     +  {fmt_cad(opt_ai)} optional add-ons" if opt_ai else "Core services only", "price_sub"),
             pp(f"Core services     +  {fmt_cad(opt_nonai)} optional add-ons" if opt_nonai else "Core services only", "price_sub")],
        ]
        sc = Table(sc_data, colWidths=[CW/2]*2, rowHeights=[7*mm, 11*mm, 7*mm])
        sc.setStyle(TableStyle([
            ("BACKGROUND",  (0,0),(-1,-1), C_GREY_4),
            ("LINEAFTER",   (0,0),(0,2),   0.5,  C_GREY_3),
            ("BOX",         (0,0),(-1,-1), 0.5,  C_GREY_3),
            ("LINEABOVE",   (0,0),(0,0),   3,    C_BLUE),
            ("LINEABOVE",   (1,0),(1,0),   3,    HexColor("#375623")),
            ("TOPPADDING",  (0,0),(-1,-1), 2),
            ("BOTTOMPADDING",(0,0),(-1,-1),2),
        ]))
        story.append(sc)
        story.append(Spacer(1, 5*mm))

    # Service count summary line
    core_n = len([d for d in dels if not d.get("optional")])
    opt_n  = len([d for d in dels if d.get("optional")])
    story.append(pp(
        f"{core_n} core service{'s' if core_n!=1 else ''}     ·     "
        f"{opt_n} optional service{'s' if opt_n!=1 else ''}     ·     "
        f"SOA period: {bid.get('submission_deadline','TBC')} onward",
        "note"))
    story.append(Spacer(1, 5*mm))

    # Col widths: ID | Service | Description | Duration | Volume | AI Price | Non-AI
    raw = [10, 42, 72, 22, 28, 28, 28]
    scale = CW / sum(r*mm for r in raw)
    col_w = [r*mm*scale for r in raw]
    HDR = ["ID", "Service", "Scope / Description",
           "Duration", "Volume & Unit", "Price (AI)", "Price (Non-AI)"]

    for cat in CAT_ORDER:
        cat_dels = [d for d in dels if d.get("category") == cat]
        if not cat_dels:
            continue

        accent = CAT_ACCENT.get(cat, C_BLUE)

        hdr_bar = Table([[Paragraph(
            f'<font name="{_font("bold")}" color="#FFFFFF">{cat.upper()}</font>',
            ParagraphStyle("sh2", fontName=_font("bold"), fontSize=8.5,
                           leading=11, textColor=C_WHITE)
        )]], colWidths=[CW])
        hdr_bar.setStyle(TableStyle([
            ("BACKGROUND",    (0,0),(-1,-1), C_NAVY),
            ("TOPPADDING",    (0,0),(-1,-1), 3*mm),
            ("BOTTOMPADDING", (0,0),(-1,-1), 3*mm),
            ("LEFTPADDING",   (0,0),(-1,-1), 3*mm),
            ("LINEABOVE",     (0,0),(-1,0),  2.5, accent),
        ]))

        hdr_row = [Paragraph(h, STYLES["col_hdr"]) for h in HDR]
        tdata = [hdr_row]

        for d in cat_dels:
            vol_str = d.get("volume") or "—"
            if d.get("unit"):
                vol_str += f"\n{d['unit']}"
            opt_tag = ('  <font name="' + _font("regular") + '" size="6" color="#7030A0">optional</font>') if d.get("optional") else ""
            title_para = Paragraph(
                f'<font name="{_font("semibold")}">{safe(d["title"],70)}</font>{opt_tag}',
                ParagraphStyle("tp", fontName=_font("semibold"), fontSize=8,
                               leading=10, textColor=C_BLACK))
            ref_para = Paragraph(
                safe(d.get("linked_req_ids",""), 40),
                ParagraphStyle("rp", fontName=_font("regular"), fontSize=6.5,
                               leading=9, textColor=C_GREY_2)) if d.get("linked_req_ids") else Paragraph("", STYLES["cell"])

            from reportlab.platypus import KeepInFrame
            title_cell = [title_para, ref_para]

            tdata.append([
                pp(safe(d.get("service_id",""), 8), "cell_id"),
                title_cell,
                pp(safe(d.get("description",""), 260), "cell_sm"),
                pp(safe(d.get("duration",""), 30), "cell"),
                Paragraph(vol_str.replace("\n","<br/>"),
                          ParagraphStyle("vc", fontName=_font("regular"), fontSize=7,
                                         leading=9, textColor=C_GREY_1)),
                pp(fmt_cad(d.get("price_ai")), "cell_num"),
                pp(fmt_cad(d.get("price_non_ai")), "cell_num"),
            ])

        t = Table(tdata, colWidths=col_w, repeatRows=1)
        ts = TableStyle([
            ("BACKGROUND",    (0,0),(-1,0),  C_BLUE),
            ("TOPPADDING",    (0,0),(-1,0),  2.5*mm),
            ("BOTTOMPADDING", (0,0),(-1,0),  2.5*mm),
            ("LINEBELOW",     (0,0),(-1,0),  1.5, C_NAVY),
            ("VALIGN",        (0,0),(-1,-1), "TOP"),
            ("TOPPADDING",    (0,1),(-1,-1), 3),
            ("BOTTOMPADDING", (0,1),(-1,-1), 3),
            ("LEFTPADDING",   (0,0),(-1,-1), 3),
            ("RIGHTPADDING",  (0,0),(-1,-1), 3),
            ("LINEBELOW",     (0,1),(-1,-1), 0.4, C_GREY_3),
            ("BOX",           (0,0),(-1,-1), 0.5, C_GREY_3),
            ("LINEBEFORE",    (0,1),(0,-1),  2.5, accent),
        ])
        for i in range(1, len(tdata)):
            ts.add("BACKGROUND", (0,i),(-1,i), C_WHITE if i%2==1 else C_BLUE_L)
        t.setStyle(ts)

        story.append(KeepTogether([hdr_bar, t]))
        story.append(Spacer(1, 5*mm))

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()

# ═════════════════════════════════════════════════════════════════════════════
# ROUTER
# ═════════════════════════════════════════════════════════════════════════════
page  = st.session_state.page
bid_id = st.session_state.active_bid

if   page == "dashboard":
    page_dashboard()
elif page == "content_library":
    page_content_library()
elif page == "coach_roster":
    page_coach_roster()
elif page == "exec_dashboard":
    page_exec_dashboard()
elif page == "all_bids":
    page_all_bids()
elif page == "new_bid":
    page_new_bid()
elif bid_id is None:
    go("dashboard")
elif page == "bid_overview":
    page_bid_overview(bid_id)
elif page == "compliance":
    page_compliance(bid_id)
elif page == "tasks":
    page_tasks(bid_id)
elif page == "documents":
    page_documents(bid_id)
elif page == "outline":
    page_outline(bid_id)
elif page == "ai_analyst":
    page_ai_analyst(bid_id)
elif page == "deliverables":
    page_deliverables(bid_id)
elif page == "clarifications":
    page_clarifications(bid_id)
elif page == "section_drafter":
    page_section_drafter(bid_id)
elif page == "proposal_analyzer":
    page_proposal_analyzer(bid_id)
elif page == "submission_assembler":
    page_submission_assembler(bid_id)
elif page == "debrief":
    page_debrief(bid_id)
else:
    go("dashboard")
