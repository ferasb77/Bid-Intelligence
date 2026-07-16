"""
Phase 3 pages — all new features.
Imported and called from app.py.
"""
import streamlit as st
from database import (
    get_bid, get_requirements, get_documents, get_outline,
    get_library_items, upsert_library_item, delete_library_item,
    get_coaches, upsert_coach, get_clarifications, upsert_clarification, delete_clarification,
    upsert_debrief, get_debriefs, save_upload,
)
from pdf_styles import generate_clarifications_pdf
from components.ui import (days_until,
                            days_label, PRIORITY_COLOURS)
from config import api_key_configured

LIB_CATEGORIES = [
    "Coaching Philosophy", "Methodology", "Case Study",
    "Team Qualification", "IDEA Statement", "ESG Statement",
    "Reconciliation Statement", "Executive Summary",
    "Sector Experience", "Reference", "CV Summary",
    "Pricing Structure", "Other",
]
CLAR_STATUSES   = ["Draft", "Submitted", "Answered", "Changes Required", "Closed"]
CLAR_PRIORITIES = ["Critical", "High", "Medium", "Low"]
ICF_LEVELS      = ["MCC", "PCC", "ACC", "EMCC Senior Practitioner",
                   "EMCC Practitioner", "Other", "None listed"]
COACH_AVAIL     = ["Available", "Partially Available", "Unavailable"]
DEBRIEF_OUTCOMES= ["Won", "Lost", "No Bid", "Withdrawn", "Pending", "Cancelled"]

# ═══════════════════════════════════════════════════════════════════════════════
# CONTENT LIBRARY
# ═══════════════════════════════════════════════════════════════════════════════
def page_content_library(bid_id=None):
    st.markdown("# Content Library")
    st.markdown('<div class="gold-rule"></div>', unsafe_allow_html=True)

    items = get_library_items(bid_id)

    # ── Edit panel — rendered FIRST so it stays visible after rerun ───────────
    eid = st.session_state.get("editing_lib")
    if eid:
        item = next((i for i in items if i["id"]==eid), None)
        if item:
            st.markdown(f"### ✏️ Editing — {item['title']}")
            with st.form("edit_lib_form"):
                title   = st.text_input("Title", value=item["title"])
                cat     = st.selectbox("Category", LIB_CATEGORIES,
                                       index=LIB_CATEGORIES.index(item["category"])
                                       if item["category"] in LIB_CATEGORIES else 0)
                content = st.text_area("Content", value=item.get("content",""), height=200)
                c1,c2   = st.columns(2)
                tags    = c1.text_input("Tags", value=item.get("tags",""))
                src     = c2.text_input("Source", value=item.get("source",""))
                appr    = st.checkbox("Approved for reuse", value=bool(item.get("approved")))
                notes   = st.text_area("Notes", value=item.get("notes",""), height=60)
                c1,c2,c3 = st.columns([2,1,1])
                sv = c1.form_submit_button("Save", use_container_width=True)
                dl = c2.form_submit_button("Delete", use_container_width=True)
                cx = c3.form_submit_button("Cancel", use_container_width=True)
            if sv:
                upsert_library_item({"id":eid,"title":title,"category":cat,
                    "content":content,"source":src,"bid_id":item.get("bid_id"),
                    "tags":tags,"approved":1 if appr else 0,"notes":notes})
                del st.session_state["editing_lib"]
                st.rerun()
            if dl:
                delete_library_item(eid)
                del st.session_state["editing_lib"]
                st.rerun()
            if cx:
                del st.session_state["editing_lib"]
                st.rerun()
            st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
            return   # Don't render the list while editing

    st.markdown('<div class="info-box">Reusable content blocks extracted from past proposals — '
                'coaching philosophies, methodologies, case studies, CVs, policy statements. '
                'Each item can be pulled into the Section Drafter when writing this bid.</div>',
                unsafe_allow_html=True)

    # ── Summary metrics ───────────────────────────────────────────────────────
    if items:
        approved = sum(1 for i in items if i.get("approved"))
        cats = list(set(i["category"] for i in items))
        c1,c2,c3 = st.columns(3)
        c1.metric("Total Items", len(items))
        c2.metric("Approved for Reuse", approved)
        c3.metric("Categories", len(cats))
        st.markdown("")

    # ── Filter bar ────────────────────────────────────────────────────────────
    c1,c2,c3 = st.columns([2,2,1])
    cat_filter  = c1.selectbox("Category", ["All"] + LIB_CATEGORIES, key="lib_cat")
    search      = c2.text_input("Search", placeholder="keyword…", key="lib_search")
    appr_filter = c3.checkbox("Approved only", key="lib_appr")

    filtered = items
    if cat_filter != "All":
        filtered = [i for i in filtered if i["category"]==cat_filter]
    if search:
        filtered = [i for i in filtered if search.lower() in
                                           (i.get("content","") + i.get("title","")).lower()]
    if appr_filter:
        filtered = [i for i in filtered if i.get("approved")]

    st.markdown(f'<span style="font-size:.78rem;color:#A9A69D">{len(filtered)} items</span>',
                unsafe_allow_html=True)
    st.markdown("")

    if not filtered:
        st.markdown('<div class="empty-state">No content yet. Upload past proposals using the '
                    '<strong>Proposal Analyzer</strong> to auto-populate the library.</div>',
                    unsafe_allow_html=True)
    else:
        for item in filtered:
            appr_icon = "✅" if item.get("approved") else "⬜"
            with st.expander(f"{appr_icon}  [{item['category']}]  {item['title']}"):
                st.markdown(f'<div style="font-size:.82rem;color:#EDEAE2;white-space:pre-wrap;'
                            f'background:#131316;border:1px solid #2A2A2E;border-radius:4px;'
                            f'padding:.8rem 1rem;max-height:200px;overflow-y:auto">'
                            f'{item["content"]}</div>', unsafe_allow_html=True)
                if item.get("tags"):
                    st.markdown(f'<span style="font-size:.72rem;color:#C6A15B">Tags: {item["tags"]}</span>',
                                unsafe_allow_html=True)
                if item.get("source"):
                    st.markdown(f'<span style="font-size:.72rem;color:#6E6C66">Source: {item["source"]}</span>',
                                unsafe_allow_html=True)
                c1,c2,c3,c4 = st.columns(4)
                if c1.button("✏ Edit", key=f"elib_{item['id']}"):
                    st.session_state["editing_lib"] = item["id"]
                    st.rerun()
                appr_label = "✅ Approved" if item.get("approved") else "☐ Mark Approved"
                if c2.button(appr_label, key=f"alib_{item['id']}"):
                    upsert_library_item({**item, "approved": 0 if item.get("approved") else 1})
                    st.rerun()
                if c3.button("🗑 Delete", key=f"dlib_{item['id']}"):
                    delete_library_item(item["id"])
                    st.rerun()

    # Edit panel now rendered at top of function

    # ── Add manually ──────────────────────────────────────────────────────────
    st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
    with st.expander("➕ Add Content Item Manually"):
        with st.form("add_lib", clear_on_submit=True):
            title   = st.text_input("Title *")
            cat     = st.selectbox("Category", LIB_CATEGORIES)
            content = st.text_area("Content *", height=150)
            c1,c2   = st.columns(2)
            tags    = c1.text_input("Tags", placeholder="coaching,executive,NFP")
            src     = c2.text_input("Source", placeholder="Proposal name / date")
            appr    = st.checkbox("Approved for reuse")
            if st.form_submit_button("Add Item", use_container_width=True):
                if title and content:
                    upsert_library_item({"title":title,"category":cat,"content":content,
                        "source":src,"bid_id":bid_id,"tags":tags,
                        "approved":1 if appr else 0,"notes":""})
                    st.rerun()
                else:
                    st.error("Title and Content required.")


# ═══════════════════════════════════════════════════════════════════════════════
# PAST PROPOSAL ANALYZER
# ═══════════════════════════════════════════════════════════════════════════════
def page_proposal_analyzer(bid_id):
    from analyst import analyze_past_proposal
    import fitz

    bid = get_bid(bid_id)
    st.markdown("# Past Proposal Analyzer")
    st.markdown('<div class="gold-rule"></div>', unsafe_allow_html=True)
    st.markdown('<div class="info-box">Upload a past Phoenix proposal (PDF). Claude reads the '
                'document and extracts reusable content blocks — methodology, case studies, '
                'team qualifications, policy statements — and maps them to the current bid. '
                'Everything goes straight into the Content Library.</div>',
                unsafe_allow_html=True)

    if not api_key_configured() and not st.session_state.get("anthropic_api_key"):
        st.markdown('<div class="warn-box">No API key configured.</div>', unsafe_allow_html=True)
        st.stop()

    uploaded = st.file_uploader("Upload past proposal (PDF)", type=["pdf","docx","txt"],
                                 key="pa_upload")
    if uploaded:
        fb = uploaded.read()
        st.markdown(f'<div class="info-box">📄 <strong>{uploaded.name}</strong> — '
                    f'{len(fb)//1024} KB ready to analyze.</div>', unsafe_allow_html=True)
        # Store file in session so button click doesn't re-trigger upload loop
        st.session_state["pa_pending_file"] = {"bytes": fb, "name": uploaded.name}

        if st.button("🔍 Analyze with Claude AI", use_container_width=True, type="primary"):
            with st.spinner("Reading past proposal and extracting reusable content… 20–40 seconds"):
                try:
                    # Extract text
                    if uploaded.name.lower().endswith(".pdf"):
                        doc  = fitz.open(stream=fb, filetype="pdf")
                        text = "\n".join(page.get_text() for page in doc)
                    else:
                        text = fb.decode("utf-8", errors="ignore")

                    result = analyze_past_proposal(text, bid)
                    pf = st.session_state.get("pa_pending_file", {})
                    st.session_state["pa_result"] = result
                    st.session_state["pa_filename"] = pf.get("name", "")
                    _up_key = f"uploaded_{bid_id}_{pf.get('name','')}_{len(pf.get('bytes',b''))}"
                    if not st.session_state.get(_up_key):
                        save_upload(bid_id, pf.get("name",""), pf.get("bytes", b""))
                        st.session_state[_up_key] = True
                    st.rerun()
                except Exception as e:
                    st.error(f"Analysis failed: {e}")

    # ── Results ───────────────────────────────────────────────────────────────
    if "pa_result" in st.session_state:
        r = st.session_state["pa_result"]

        # Guard: if AI returned a list or non-dict, wrap it
        if isinstance(r, list):
            r = {"library_items": r, "proposal_summary": {}, "coaches_found": [], "gaps": []}
        elif not isinstance(r, dict):
            st.error("Analysis returned an unexpected format. Please try again.")
            del st.session_state["pa_result"]
            st.rerun()

        fname   = st.session_state.get("pa_filename","")
        summary = r.get("proposal_summary",{}) if isinstance(r.get("proposal_summary"), dict) else {}
        items   = r.get("library_items",[]) if isinstance(r.get("library_items"), list) else []
        coaches = r.get("coaches_found",[]) if isinstance(r.get("coaches_found"), list) else []
        gaps    = r.get("gaps",[]) if isinstance(r.get("gaps"), list) else []

        st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
        c1,c2,c3,c4 = st.columns(4)
        c1.metric("Content Blocks Found", len(items))
        c2.metric("Coaches Identified",   len(coaches))
        c3.markdown(f'<div style="font-size:.82rem;color:#A9A69D">Proposal client</div>'
                    f'<div style="font-size:.95rem;font-weight:600">{summary.get("client","Unknown")}</div>',
                    unsafe_allow_html=True)
        c4.markdown(f'<div style="font-size:.82rem;color:#A9A69D">Outcome</div>'
                    f'<div style="font-size:.95rem;font-weight:600">{summary.get("outcome","Unknown")}</div>',
                    unsafe_allow_html=True)

        if gaps:
            st.markdown("**Gaps for current bid:**")
            for g in gaps:
                st.markdown(f'<span style="color:#E67E22;font-size:.82rem">⚠ {g}</span>',
                            unsafe_allow_html=True)

        # Preview extracted items
        st.markdown(f"### {len(items)} Content Blocks Extracted")
        for i, item in enumerate(items):
            with st.expander(f"[{item.get('category','')}]  {item.get('title','')}"):
                st.markdown(f'<div style="font-size:.82rem;color:#EDEAE2;white-space:pre-wrap;'
                            f'background:#131316;border:1px solid #2A2A2E;border-radius:4px;'
                            f'padding:.8rem;max-height:160px;overflow-y:auto">'
                            f'{item.get("content","")}</div>', unsafe_allow_html=True)
                if item.get("relevance_to_current"):
                    st.markdown(f'<span style="font-size:.75rem;color:#C6A15B">'
                                f'→ {item["relevance_to_current"]}</span>',
                                unsafe_allow_html=True)

        if coaches:
            st.markdown(f"### {len(coaches)} Coaches Found")
            for coach in coaches:
                st.markdown(f'**{coach.get("name","")}** — {coach.get("credentials","")} '
                            f'{coach.get("icf_level","")}', unsafe_allow_html=True)

        st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
        c1,c2 = st.columns([2,1])
        if c1.button("💾 Save All to Content Library", use_container_width=True, type="primary"):
            saved = 0
            for item in items:
                upsert_library_item({"title":item.get("title","Untitled"),
                    "category":item.get("category","Other"),
                    "content":item.get("content",""),
                    "source":fname,
                    "bid_id":bid_id,
                    "tags":item.get("tags",""),
                    "approved":0,
                    "notes":item.get("relevance_to_current","")})
                saved += 1
            for coach in coaches:
                existing = [c for c in get_coaches() if c["name"]==coach.get("name","")]
                if not existing:
                    upsert_coach({"name":coach.get("name",""),
                        "credentials":coach.get("credentials",""),
                        "icf_level":coach.get("icf_level",""),
                        "sectors":coach.get("sectors",""),
                        "languages":coach.get("languages",""),
                        "location":"","availability":"Available",
                        "email":"","phone":"",
                        "cv_summary":coach.get("cv_summary",""),
                        "reference_contact":"","notes":f"Found in: {fname}"})
            del st.session_state["pa_result"]
            del st.session_state["pa_filename"]
            st.success(f"Saved {saved} content blocks + {len(coaches)} coaches to library.")
            st.rerun()
        if c2.button("✕ Discard", use_container_width=True):
            del st.session_state["pa_result"]
            del st.session_state["pa_filename"]
            st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# COACH ROSTER
# ═══════════════════════════════════════════════════════════════════════════════
def page_coach_roster():
    coaches = get_coaches()
    st.markdown("# Coach Roster")
    st.markdown('<div class="gold-rule"></div>', unsafe_allow_html=True)

    if coaches:
        avail = sum(1 for c in coaches if c.get("availability")=="Available")
        langs = set()
        for c in coaches:
            if c.get("languages"):
                langs.update(lang.strip() for lang in c["languages"].split(","))
        c1,c2,c3 = st.columns(3)
        c1.metric("Total Coaches", len(coaches))
        c2.metric("Available", avail)
        c3.metric("Languages Covered", len(langs))
        st.markdown("")

        for coach in coaches:
            avail_col = {"Available":"#27AE60","Partially Available":"#E67E22",
                         "Unavailable":"#C0392B"}.get(coach.get("availability",""),"#6E6C66")
            with st.expander(f"**{coach['name']}**  ·  {coach.get('credentials','') or ''}  ·  "
                             f"{coach.get('icf_level','') or ''}"):
                c1,c2,c3 = st.columns(3)
                c1.markdown(f"**Sectors:** {coach.get('sectors') or '—'}")
                c1.markdown(f"**Languages:** {coach.get('languages') or '—'}")
                c2.markdown(f"**Location:** {coach.get('location') or '—'}")
                c2.markdown(f'**Availability:** <span style="color:{avail_col}">'
                            f'{coach.get("availability","—")}</span>',
                            unsafe_allow_html=True)
                c3.markdown(f"**Email:** {coach.get('email') or '—'}")
                c3.markdown(f"**Phone:** {coach.get('phone') or '—'}")
                if coach.get("cv_summary"):
                    st.markdown(f'<div style="font-size:.82rem;color:#A9A69D;'
                                f'background:#131316;border:1px solid #2A2A2E;'
                                f'border-radius:4px;padding:.6rem .8rem;margin:.4rem 0">'
                                f'{coach["cv_summary"]}</div>', unsafe_allow_html=True)
                if coach.get("reference_contact"):
                    st.markdown(f'<span style="font-size:.75rem;color:#C6A15B">'
                                f'Reference: {coach["reference_contact"]}</span>',
                                unsafe_allow_html=True)
                if st.button("✏ Edit", key=f"ec_{coach['id']}"):
                    st.session_state["editing_coach"] = coach["id"]
                    st.rerun()
    else:
        st.markdown('<div class="empty-state">No coaches yet. Run the Proposal Analyzer on past '
                    'proposals to auto-populate, or add manually below.</div>',
                    unsafe_allow_html=True)

    eid = st.session_state.get("editing_coach")
    if eid:
        coach = next((c for c in coaches if c["id"]==eid), None)
        if coach:
            st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
            st.markdown(f"### Edit — {coach['name']}")
            with st.form("edit_coach"):
                c1,c2 = st.columns(2)
                name  = c1.text_input("Full Name", value=coach["name"])
                creds = c2.text_input("Credentials", value=coach.get("credentials",""))
                c1,c2,c3 = st.columns(3)
                icf   = c1.selectbox("ICF/EMCC Level", ["—"]+ICF_LEVELS,
                                     index=ICF_LEVELS.index(coach.get("icf_level",""))+1
                                     if coach.get("icf_level") in ICF_LEVELS else 0)
                avail = c2.selectbox("Availability", COACH_AVAIL,
                                     index=COACH_AVAIL.index(coach.get("availability","Available"))
                                     if coach.get("availability") in COACH_AVAIL else 0)
                loc   = c3.text_input("Location", value=coach.get("location",""))
                c1,c2 = st.columns(2)
                sectors = c1.text_input("Sectors", value=coach.get("sectors",""))
                langs   = c2.text_input("Languages", value=coach.get("languages",""))
                c1,c2 = st.columns(2)
                email = c1.text_input("Email", value=coach.get("email",""))
                phone = c2.text_input("Phone", value=coach.get("phone",""))
                cv_sum  = st.text_area("CV Summary", value=coach.get("cv_summary",""), height=100)
                ref_con = st.text_input("Reference Contact", value=coach.get("reference_contact",""))
                notes   = st.text_area("Notes", value=coach.get("notes",""), height=60)
                c1,c2,c3 = st.columns([2,1,1])
                sv = c1.form_submit_button("Save", use_container_width=True)
                dl = c2.form_submit_button("Delete", use_container_width=True)
                cx = c3.form_submit_button("Cancel", use_container_width=True)
            if sv:
                upsert_coach({"id":eid,"name":name,"credentials":creds,
                    "icf_level":icf if icf!="—" else None,"sectors":sectors,
                    "languages":langs,"location":loc,"availability":avail,
                    "email":email,"phone":phone,"cv_summary":cv_sum,
                    "reference_contact":ref_con,"notes":notes})
                del st.session_state["editing_coach"]
                st.rerun()
            if dl:
                from database import delete_coach
                delete_coach(eid)
                del st.session_state["editing_coach"]
                st.rerun()
            if cx:
                del st.session_state["editing_coach"]
                st.rerun()

    st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
    with st.expander("➕ Add Coach"):
        with st.form("add_coach", clear_on_submit=True):
            c1,c2 = st.columns(2)
            name  = c1.text_input("Full Name *")
            creds = c2.text_input("Credentials", placeholder="ICF PCC, MBA…")
            c1,c2,c3 = st.columns(3)
            icf   = c1.selectbox("ICF/EMCC Level", ["—"]+ICF_LEVELS)
            avail = c2.selectbox("Availability", COACH_AVAIL)
            loc   = c3.text_input("Location")
            c1,c2 = st.columns(2)
            sectors = c1.text_input("Sectors", placeholder="Healthcare, Banking, Energy")
            langs   = c2.text_input("Languages", placeholder="English, Arabic, French")
            c1,c2 = st.columns(2)
            email = c1.text_input("Email")
            phone = c2.text_input("Phone")
            cv_sum  = st.text_area("CV Summary", height=100)
            ref_con = st.text_input("Reference Contact")
            if st.form_submit_button("Add Coach", use_container_width=True):
                if name:
                    upsert_coach({"name":name,"credentials":creds,
                        "icf_level":icf if icf!="—" else None,
                        "sectors":sectors,"languages":langs,"location":loc,
                        "availability":avail,"email":email,"phone":phone,
                        "cv_summary":cv_sum,"reference_contact":ref_con,"notes":""})
                    st.rerun()
                else:
                    st.error("Name required.")


# ═══════════════════════════════════════════════════════════════════════════════
# CLARIFICATION TRACKER
# ═══════════════════════════════════════════════════════════════════════════════
def page_clarifications(bid_id):
    from analyst import generate_clarification_questions
    bid   = get_bid(bid_id)
    reqs  = get_requirements(bid_id)
    clars = get_clarifications(bid_id)

    st.markdown("# Clarification Questions")
    st.markdown('<div class="gold-rule"></div>', unsafe_allow_html=True)

    # ── Deadline banner ───────────────────────────────────────────────────────
    clar_dl = days_until(bid.get("clarification_deadline"))
    if clar_dl is not None:
        col = "#C0392B" if clar_dl <= 3 else "#E67E22" if clar_dl <= 7 else "#2471A3"
        st.markdown(
            f'<div style="background:{col}22;border:1px solid {col}55;border-radius:6px;'
            f'padding:.8rem 1.2rem;margin-bottom:1rem;display:flex;justify-content:space-between;'
            f'align-items:center">'
            f'<div>'
            f'<span style="color:{col};font-weight:700;font-size:.95rem">'
            f'Enquiry deadline: {bid.get("clarification_deadline","")} — 14:00 Ottawa (21:00 Beirut)</span>'
            f'<br><span style="color:#A9A69D;font-size:.78rem">'
            f'All questions and answers are shared with ALL bidders. Phrase accordingly.</span>'
            f'</div>'
            f'<span style="color:{col};font-size:1.2rem;font-weight:700">'
            f'{days_label(clar_dl)}</span></div>',
            unsafe_allow_html=True)

    # ── Metrics ───────────────────────────────────────────────────────────────
    if clars:
        c1,c2,c3,c4,c5 = st.columns(5)
        c1.metric("Total", len(clars))
        c2.metric("Critical", sum(1 for q in clars if q.get("priority")=="Critical"))
        c3.metric("Submitted", sum(1 for q in clars if q.get("status") in ("Submitted","Answered")))
        c4.metric("Answered", sum(1 for q in clars if q.get("status")=="Answered"))
        c5.metric("Matrix Changes", sum(1 for q in clars if q.get("changes_matrix")))
        st.markdown("")

    # ═══════════════════════════════════════════════════════════════════════════
    # AI GENERATOR — main feature
    # ═══════════════════════════════════════════════════════════════════════════
    st.markdown("### 🤖 AI Question Generator")
    st.markdown(
        '<div class="info-box">Claude reads the full compliance matrix and RFP context, ' 
        'identifies every genuine ambiguity that could affect eligibility, scope, or pricing, ' 
        'and writes submission-ready questions ranked by strategic importance. ' 
        'Each question includes a private rationale for internal use.</div>',
        unsafe_allow_html=True)

    with st.expander("⚙ Generation options", expanded=not clars):
        rfp_context = st.text_area(
            "Paste additional RFP text or your specific concerns",
            height=120,
            placeholder=(
                "Paste key sections from the RFP that have ambiguities, or describe specific "
                "concerns:\n\n- Phoenix coaches are based outside Canada\n"
                "- We want to propose Hogan assessments as optional services\n"
                "- Unsure whether $2M insurance must be in place at submission or award"
            ),
            key="cq_rfp_ctx")

        firm_concerns = st.text_area(
            "Phoenix-specific concerns (internal context — not sent to client)",
            height=80,
            placeholder=(
                "e.g. Our coaches are based in Beirut and Dubai. "
                "We want to propose Hogan as an optional service. "
                "We are considering a Canadian subcontractor arrangement."
            ),
            key="cq_firm_ctx")

        col1, col2 = st.columns([2,1])
        col2.checkbox("Replace existing questions", value=not bool(clars))

        if col1.button("🔍 Generate Clarification Questions with Claude",
                       use_container_width=True, type="primary"):
            if not (api_key_configured() or st.session_state.get("anthropic_api_key")):
                st.error("No API key configured.")
            elif not reqs:
                st.error("No requirements extracted yet — upload the RFP first.")
            else:
                combined_context = rfp_context
                if firm_concerns:
                    combined_context += f"\n\nBIDDER CONTEXT (internal — shape questions but do not reveal):\n{firm_concerns}"

                with st.spinner("Reading RFP requirements and generating strategic questions… 20–30 seconds"):
                    try:
                        result = generate_clarification_questions(bid, reqs, combined_context)
                        st.session_state["cq_generated"] = result
                        st.rerun()
                    except Exception as e:
                        st.error(f"Generation failed: {e}")

    # ── Generated questions preview ───────────────────────────────────────────
    if "cq_generated" in st.session_state:
        result  = st.session_state["cq_generated"]
        qs      = result.get("questions", [])
        critical= [q for q in qs if q.get("priority")=="Critical"]
        high    = [q for q in qs if q.get("priority")=="High"]
        medium  = [q for q in qs if q.get("priority")=="Medium"]

        st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
        st.markdown(f"#### {len(qs)} Questions Generated")

        c1,c2,c3 = st.columns(3)
        c1.markdown(f'<div style="text-align:center;background:#1A0000;border:1px solid #C0392B;'
                    f'border-radius:6px;padding:.6rem"><div style="font-size:1.3rem;font-weight:700;'
                    f'color:#C0392B">{len(critical)}</div><div style="font-size:.72rem;'
                    f'color:#A9A69D;text-transform:uppercase">Critical</div></div>',
                    unsafe_allow_html=True)
        c2.markdown(f'<div style="text-align:center;background:#1A0F00;border:1px solid #E67E22;'
                    f'border-radius:6px;padding:.6rem"><div style="font-size:1.3rem;font-weight:700;'
                    f'color:#E67E22">{len(high)}</div><div style="font-size:.72rem;'
                    f'color:#A9A69D;text-transform:uppercase">High</div></div>',
                    unsafe_allow_html=True)
        c3.markdown(f'<div style="text-align:center;background:#131316;border:1px solid #2A2A2E;'
                    f'border-radius:6px;padding:.6rem"><div style="font-size:1.3rem;font-weight:700;'
                    f'color:#A9A69D">{len(medium)}</div><div style="font-size:.72rem;'
                    f'color:#A9A69D;text-transform:uppercase">Medium</div></div>',
                    unsafe_allow_html=True)

        if result.get("submission_notes"):
            st.markdown(f'<div class="info-box" style="margin-top:.8rem">'
                        f'<strong>Submission advice:</strong> {result["submission_notes"]}</div>',
                        unsafe_allow_html=True)

        st.markdown("")

        for q in qs:
            pri = q.get("priority","Medium")
            pri_col = {"Critical":"#C0392B","High":"#E67E22","Medium":"#C6A15B"}.get(pri,"#6E6C66")
            cat = q.get("category","")
            relates = ", ".join(q.get("relates_to",[]))

            st.markdown(
                f'<div style="background:#131316;border:1px solid #2A2A2E;'
                f'border-left:4px solid {pri_col};border-radius:0 6px 6px 0;'
                f'padding:.8rem 1rem;margin:.4rem 0">'
                f'<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:.5rem">'
                f'<span style="font-weight:700;color:#EDEAE2;font-size:.92rem;flex:1;margin-right:1rem">'
                f'{q.get("id","")}. {q.get("question","")}</span>'
                f'<div style="text-align:right;white-space:nowrap">'
                f'<span style="background:{pri_col}22;color:{pri_col};padding:.15rem .5rem;'
                f'border-radius:3px;font-size:.7rem;font-weight:700">{pri.upper()}</span>'
                f'{"<br><span style=font-size:.68rem;color:#6E6C66;margin-top:.2rem;display:block>" + cat + "</span>" if cat else ""}'
                f'</div></div>'
                f'<div style="font-size:.76rem;color:#6E6C66;font-style:italic;margin-bottom:.3rem">'
                f'<strong style="color:#A9A69D">Why this matters (internal):</strong> {q.get("rationale","")}</div>'
                f'{"<div style=font-size:.72rem;color:#C0392B;margin-top:.2rem>Risk if unanswered: " + q.get("risk_if_unanswered","") + "</div>" if q.get("risk_if_unanswered") else ""}'
                f'{"<div style=font-size:.7rem;color:#A9A69D;margin-top:.3rem>Linked: " + relates + "</div>" if relates else ""}'
                f'</div>',
                unsafe_allow_html=True)

        st.markdown("")
        c1,c2,c3 = st.columns(3)

        if c1.button("💾 Save All to Tracker", use_container_width=True, type="primary"):
            saved = 0
            for q in qs:
                upsert_clarification({
                    "bid_id": bid_id,
                    "question_id": q.get("id",""),
                    "question": q.get("question",""),
                    "rationale": (f"{q.get('rationale','')} | "
                                  f"Risk: {q.get('risk_if_unanswered','')} | "
                                  f"Category: {q.get('category','')}"),
                    "priority": q.get("priority","Medium"),
                    "linked_req_ids": ", ".join(q.get("relates_to",[])),
                    "submitted_date": None, "answer": None, "answer_date": None,
                    "changes_matrix": 0, "status": "Draft", "notes": ""
                })
                saved += 1
            del st.session_state["cq_generated"]
            st.success(f"Saved {saved} questions to tracker.")
            st.rerun()

        # Export for submission — questions only, no internal rationale
        plain = f"Clarification Questions\n{bid.get('client','')} — {bid.get('title','')}\nFile: {bid.get('file_number','')}\nEnquiry deadline: {bid.get('clarification_deadline','')}\n\n"
        plain += "\n\n".join(
            f"{q.get('id','')}. {q.get('question','')}"
            for q in qs
        )
        # PDF exports
        try:
            pdf_sub = generate_clarifications_pdf(bid, qs, include_rationale=False)
            c2.download_button(
                "⬇ PDF — Submission copy",
                data=pdf_sub,
                file_name=f"clarification_questions_{bid.get('file_number','bid')}_SUBMISSION.pdf",
                mime="application/pdf",
                use_container_width=True)
        except Exception as e:
            c2.error(f"PDF error: {e}")

        try:
            pdf_int = generate_clarifications_pdf(bid, qs, include_rationale=True)
            c3.download_button(
                "⬇ PDF — Internal copy",
                data=pdf_int,
                file_name=f"clarification_questions_{bid.get('file_number','bid')}_INTERNAL.pdf",
                mime="application/pdf",
                use_container_width=True)
        except Exception as e:
            c3.error(f"PDF error: {e}")

        c1_2, c2_2 = st.columns([3,1])
        c1_2.download_button("⬇ TXT — Submission copy (plain text)", data=plain,
            file_name=f"clarification_questions_{bid.get('file_number','bid')}.txt",
            mime="text/plain", use_container_width=True)
        if c2_2.button("✕ Discard", use_container_width=True):
            del st.session_state["cq_generated"]
            st.rerun()

    # ── Saved questions tracker ───────────────────────────────────────────────
    if clars:
        st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
        st.markdown("### Saved Questions")

        for grp_status, grp_label, grp_col in [
            ("Draft",    "DRAFT",     "#C6A15B"),
            ("Submitted","SUBMITTED", "#2471A3"),
            ("Answered", "ANSWERED",  "#27AE60"),
            ("Changes Required", "CHANGES REQUIRED", "#C0392B"),
            ("Closed",   "CLOSED",    "#6E6C66"),
        ]:
            grp = [q for q in clars if q.get("status")==grp_status]
            if not grp:
                continue
            st.markdown(f'<span style="font-size:.78rem;color:{grp_col};font-weight:700;'
                        f'letter-spacing:.05em">{grp_label} ({len(grp)})</span>',
                        unsafe_allow_html=True)

            for q in grp:
                with st.expander(
                    f"{q.get('question_id','')}. {q.get('question','')[:90]}"
                    f"{'…' if len(q.get('question',''))>90 else ''}",
                    expanded=bool(q.get("changes_matrix") and grp_status=="Answered")
                ):
                    st.markdown(f'**Full question:** {q.get("question","")}')
                    if q.get("rationale"):
                        st.markdown(
                            f'<div style="background:#0A0A12;border-left:2px solid #6E6C66;'
                            f'padding:.4rem .8rem;font-size:.78rem;color:#A9A69D;font-style:italic;'
                            f'margin:.4rem 0">Internal rationale: {q["rationale"]}</div>',
                            unsafe_allow_html=True)
                    if q.get("answer"):
                        st.markdown(f'**Answer ({q.get("answer_date","")}):**')
                        st.markdown(
                            f'<div style="background:#0A1A0A;border-left:3px solid #27AE60;'
                            f'padding:.6rem 1rem;font-size:.85rem;border-radius:0 4px 4px 0">'
                            f'{q["answer"]}</div>', unsafe_allow_html=True)
                        if q.get("changes_matrix"):
                            st.markdown('<div class="warn-box" style="margin-top:.4rem">'
                                        '⚠ This answer requires compliance matrix updates — '
                                        'review and update before submission.</div>',
                                        unsafe_allow_html=True)
                    if st.button("✏ Edit / Record Answer", key=f"eq_{q['id']}"):
                        st.session_state["editing_clar"] = q["id"]
                        st.rerun()
            st.markdown("")

    # ── Edit panel ────────────────────────────────────────────────────────────
    eid = st.session_state.get("editing_clar")
    if eid:
        q = next((x for x in clars if x["id"]==eid), None)
        if q:
            st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
            st.markdown(f"### Edit — {q.get('question_id','')}.")
            with st.form("edit_clar"):
                qid   = st.text_input("Question ID", value=q.get("question_id",""))
                quest = st.text_area("Question text", value=q.get("question",""), height=100)
                rat   = st.text_area("Internal rationale", value=q.get("rationale",""), height=70)
                c1,c2,c3 = st.columns(3)
                pri  = c1.selectbox("Priority", CLAR_PRIORITIES,
                                    index=CLAR_PRIORITIES.index(q.get("priority","Medium"))
                                    if q.get("priority") in CLAR_PRIORITIES else 1)
                stat = c2.selectbox("Status", CLAR_STATUSES,
                                    index=CLAR_STATUSES.index(q.get("status","Draft"))
                                    if q.get("status") in CLAR_STATUSES else 0)
                linked = c3.text_input("Linked Req IDs", value=q.get("linked_req_ids",""))
                c1,c2 = st.columns(2)
                sub_d = c1.text_input("Submitted Date", value=q.get("submitted_date",""),
                                      placeholder="2026-07-22")
                ans_d = c2.text_input("Answer Date",    value=q.get("answer_date",""))
                answer  = st.text_area("Answer (record when received from CDA-AMC)",
                                       value=q.get("answer",""), height=120)
                changes = st.checkbox("⚠ This answer requires compliance matrix updates",
                                      value=bool(q.get("changes_matrix")))
                notes   = st.text_area("Notes", value=q.get("notes",""), height=50)
                c1,c2,c3 = st.columns([2,1,1])
                sv = c1.form_submit_button("Save", use_container_width=True)
                dl = c2.form_submit_button("Delete", use_container_width=True)
                cx = c3.form_submit_button("Cancel", use_container_width=True)
            if sv:
                upsert_clarification({"id":eid,"bid_id":bid_id,"question_id":qid,
                    "question":quest,"rationale":rat,"priority":pri,
                    "linked_req_ids":linked,"submitted_date":sub_d,
                    "answer":answer,"answer_date":ans_d,
                    "changes_matrix":1 if changes else 0,"status":stat,"notes":notes})
                del st.session_state["editing_clar"]
                st.rerun()
            if dl:
                delete_clarification(eid)
                del st.session_state["editing_clar"]
                st.rerun()
            if cx:
                del st.session_state["editing_clar"]
                st.rerun()

    # ── Export saved questions ────────────────────────────────────────────────
    if clars:
        st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
        st.markdown("### 📥 Export Questions")

        # Normalise saved questions to the format generate_clarifications_pdf expects
        export_qs = []
        for q in sorted(clars,
                key=lambda x: {"Critical":0,"High":1,"Medium":2,"Low":3}.get(
                    x.get("priority","Medium"), 2)):
            export_qs.append({
                "id":                  q.get("question_id") or str(clars.index(q)+1),
                "question":            q.get("question",""),
                "rationale":           q.get("rationale",""),
                "priority":            q.get("priority","Medium"),
                "risk_if_unanswered":  "",
                "relates_to":          [r.strip() for r in
                                        (q.get("linked_req_ids","") or "").split(",")
                                        if r.strip()],
                "category":            "",
            })

        c1, c2, c3 = st.columns(3)
        try:
            pdf_sub = generate_clarifications_pdf(bid, export_qs, include_rationale=False)
            c1.download_button(
                "⬇ PDF — Submission copy",
                data=pdf_sub,
                file_name=f"clarification_questions_{bid.get('file_number','bid')}_SUBMISSION.pdf",
                mime="application/pdf",
                use_container_width=True)
        except Exception as e:
            c1.error(f"PDF error: {e}")

        try:
            pdf_int = generate_clarifications_pdf(bid, export_qs, include_rationale=True)
            c2.download_button(
                "⬇ PDF — Internal copy",
                data=pdf_int,
                file_name=f"clarification_questions_{bid.get('file_number','bid')}_INTERNAL.pdf",
                mime="application/pdf",
                use_container_width=True)
        except Exception as e:
            c2.error(f"PDF error: {e}")

        plain = "\n\n".join(
            f"{q['id']}. {q['question']}" for q in export_qs)
        c3.download_button(
            "⬇ TXT — Plain text",
            data=plain,
            file_name=f"clarification_questions_{bid.get('file_number','bid')}.txt",
            mime="text/plain",
            use_container_width=True)

        st.markdown(
            '<div class="info-box" style="margin-top:.5rem">'
            '<strong>Submission copy</strong> — questions only, no internal rationale. '
            'Send this to contracts@cda-amc.ca.<br>'
            '<strong>Internal copy</strong> — includes private rationale and risk assessment. '
            'For Phoenix internal use only.</div>',
            unsafe_allow_html=True)

    # ── Add manually ──────────────────────────────────────────────────────────
    st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
    with st.expander("➕ Add Question Manually"):
        with st.form("add_clar", clear_on_submit=True):
            c1,c2 = st.columns([3,1])
            qid   = c2.text_input("ID", placeholder="Q1…")
            quest = st.text_area("Question *", height=100)
            rat   = st.text_area("Internal rationale", height=60)
            c1,c2 = st.columns(2)
            pri    = c1.selectbox("Priority", CLAR_PRIORITIES, index=1)
            linked = c2.text_input("Linked Req IDs", placeholder="M1, R4…")
            if st.form_submit_button("Add Question", use_container_width=True):
                if quest:
                    upsert_clarification({"bid_id":bid_id,"question_id":qid,
                        "question":quest,"rationale":rat,"priority":pri,
                        "linked_req_ids":linked,"submitted_date":None,
                        "answer":None,"answer_date":None,
                        "changes_matrix":0,"status":"Draft","notes":""})
                    st.rerun()
                else:
                    st.error("Question required.")


# ═══════════════════════════════════════════════════════════════════════════════
# PROPOSAL SECTION DRAFTER
# ═══════════════════════════════════════════════════════════════════════════════
def page_section_drafter(bid_id):
    from analyst import draft_proposal_section
    bid     = get_bid(bid_id)
    reqs    = get_requirements(bid_id)
    sections= get_outline(bid_id)
    coaches = get_coaches()

    st.markdown("# Proposal Section Drafter")
    st.markdown('<div class="gold-rule"></div>', unsafe_allow_html=True)
    st.markdown('<div class="info-box">Select a proposal section, choose which requirements '
                'it must address, pick relevant library content, and Claude drafts a first-pass '
                'section using Phoenix\'s actual past proposal language.</div>',
                unsafe_allow_html=True)

    if not api_key_configured() and not st.session_state.get("anthropic_api_key"):
        st.markdown('<div class="warn-box">No API key configured.</div>', unsafe_allow_html=True)
        st.stop()

    lib_items = get_library_items(bid_id)
    if not lib_items:
        st.markdown('<div class="warn-box">No library content yet. Run the Proposal Analyzer '
                    'on past proposals first to build reusable content.</div>',
                    unsafe_allow_html=True)

    c1,c2 = st.columns(2)

    # Section selector
    if sections:
        sec_opts = {f"[{s.get('section_num','')}] {s['title']}": s for s in sections}
        sel_sec  = c1.selectbox("Select proposal section", list(sec_opts.keys()), key="dr_sec")
        chosen_sec = sec_opts[sel_sec]
        word_limit = chosen_sec.get("word_limit") or 500
    else:
        custom_title = c1.text_input("Section title", placeholder="e.g. Coaching Methodology")
        chosen_sec   = {"title": custom_title, "word_limit": 500}
        word_limit   = 500

    word_limit = c2.number_input("Target word count", value=int(word_limit), step=50, min_value=100)

    # Requirements filter
    st.markdown("**Requirements this section addresses:**")
    req_opts = {f"[{r['req_id']}] {r['description'][:70]}": r for r in reqs}
    sel_reqs = st.multiselect("Select requirements", list(req_opts.keys()), key="dr_reqs")
    chosen_reqs = [req_opts[k] for k in sel_reqs]

    # Library content picker
    st.markdown("**Relevant library content to draw from:**")
    if lib_items:
        lib_opts = {f"[{i['category']}] {i['title']}": i for i in lib_items}
        sel_lib  = st.multiselect("Select content blocks",
                                   list(lib_opts.keys()),
                                   default=[k for k in list(lib_opts.keys())[:3]],
                                   key="dr_lib")
        chosen_lib = [lib_opts[k] for k in sel_lib]
    else:
        chosen_lib = []
        st.markdown('<span style="font-size:.8rem;color:#6E6C66">No library items yet.</span>',
                    unsafe_allow_html=True)

    # Firm context
    coach_names = ", ".join(c["name"] for c in coaches) if coaches else ""
    firm_ctx = st.text_area("Additional firm context",
        value=f"Phoenix Consulting International, authorised Hogan distributor for the GCC. "
              f"{'Proposed coaches: ' + coach_names + '.' if coach_names else ''}",
        height=70, key="dr_ctx")

    if st.button("✍ Draft this section with Claude", use_container_width=True, type="primary"):
        if not chosen_reqs and not chosen_sec.get("title"):
            st.error("Select at least one requirement or enter a section title.")
        else:
            with st.spinner("Drafting section… 15–25 seconds"):
                try:
                    result = draft_proposal_section(
                        section_title=chosen_sec.get("title",""),
                        requirements=chosen_reqs,
                        library_items=chosen_lib,
                        bid_context=bid,
                        firm_context=firm_ctx,
                        word_limit=word_limit,
                    )
                    st.session_state["dr_result"] = result
                    st.rerun()
                except Exception as e:
                    st.error(f"Draft failed: {e}")

    if "dr_result" in st.session_state:
        r = st.session_state["dr_result"]
        st.markdown('<hr class="section-divider">', unsafe_allow_html=True)

        score = r.get("strength_rating",0)
        score_col = "#27AE60" if score>=4 else "#E67E22" if score>=3 else "#C0392B"
        c1,c2,c3 = st.columns(3)
        c1.markdown(f'<div style="text-align:center;background:#131316;border:1px solid #2A2A2E;'
                    f'border-radius:6px;padding:.8rem">'
                    f'<div style="font-size:1.6rem;font-weight:700;color:{score_col}">{score}/5</div>'
                    f'<div style="font-size:.72rem;color:#A9A69D;text-transform:uppercase">Draft Strength</div>'
                    f'</div>', unsafe_allow_html=True)
        c2.markdown(f'<div style="font-size:.8rem;color:#A9A69D;padding:.4rem 0">'
                    f'<strong>Addressed:</strong> {", ".join(r.get("requirements_addressed",[]) or ["—"])}</div>'
                    f'<div style="font-size:.8rem;color:#C0392B;padding:.2rem 0">'
                    f'<strong>Missing:</strong> {", ".join(r.get("requirements_missing",[]) or ["—"])}</div>',
                    unsafe_allow_html=True)
        c3.markdown(f'<div style="font-size:.78rem;color:#A9A69D">'
                    f'~{r.get("word_count",0)} words</div>', unsafe_allow_html=True)

        if r.get("improvement_notes"):
            st.markdown(f'<div class="info-box"><strong>To strengthen:</strong> '
                        f'{r["improvement_notes"]}</div>', unsafe_allow_html=True)

        st.markdown("### Draft")
        draft_text = r.get("draft","")
        edited = st.text_area("Edit draft here", value=draft_text, height=350, key="dr_edit")

        c1,c2 = st.columns(2)
        if c1.download_button("⬇ Download as text", data=edited,
                file_name=f"draft_{chosen_sec.get('title','section').replace(' ','_')}.txt",
                mime="text/plain", use_container_width=True):
            pass
        if c2.button("🔄 Redraft (discard edits)", use_container_width=True):
            del st.session_state["dr_result"]
            st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# SUBMISSION ASSEMBLER
# ═══════════════════════════════════════════════════════════════════════════════
def page_submission_assembler(bid_id):
    from analyst import submission_readiness_check, analyze_proposal_alignment
    import fitz

    bid     = get_bid(bid_id)
    reqs    = get_requirements(bid_id)
    docs    = get_documents(bid_id)
    outline = get_outline(bid_id)
    clars   = get_clarifications(bid_id)

    st.markdown("# Submission Assembler")
    st.markdown('<div class="gold-rule"></div>', unsafe_allow_html=True)

    sub_d = days_until(bid.get("submission_deadline"))
    if sub_d is not None:
        col = "#C0392B" if sub_d<=3 else "#E67E22" if sub_d<=7 else "#27AE60"
        st.markdown(f'<div style="background:{col}22;border:1px solid {col}44;'
                    f'border-radius:6px;padding:1rem 1.2rem;margin-bottom:1rem">'
                    f'<span style="font-size:1.1rem;font-weight:700;color:{col}">'
                    f'{days_label(sub_d).replace("<span","<span")}</span> '
                    f'<span style="color:#A9A69D;font-size:.85rem">until submission — '
                    f'{bid.get("submission_deadline","")} 14:00 Ottawa (21:00 Beirut)</span></div>',
                    unsafe_allow_html=True)

    tab1, tab2 = st.tabs(["📋 Readiness & Checklist", "🔍 Proposal Review"])

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 1 — existing readiness check + manual checklist
    # ══════════════════════════════════════════════════════════════════════════
    with tab1:
        # ── AI Readiness Check ────────────────────────────────────────────────
        if api_key_configured() or st.session_state.get("anthropic_api_key"):
            if st.button("🎯 Run AI Readiness Check", use_container_width=True, type="primary"):
                with st.spinner("Checking submission readiness…"):
                    try:
                        result = submission_readiness_check(bid, reqs, docs, outline)
                        st.session_state["sub_check"] = result
                        st.rerun()
                    except Exception as e:
                        st.error(f"Check failed: {e}")

        if "sub_check" in st.session_state:
            r = st.session_state["sub_check"]
            gng = r.get("go_no_go","?")
            gng_col = {"GO":"#27AE60","NO GO":"#C0392B","CONDITIONAL GO":"#E67E22"}.get(gng,"#6E6C66")
            score = r.get("readiness_score",0)

            st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
            c1,c2 = st.columns([1,4])
            c1.markdown(f'<div style="text-align:center;background:#131316;border:2px solid {gng_col};'
                        f'border-radius:6px;padding:1rem">'
                        f'<div style="font-size:1.2rem;font-weight:700;color:{gng_col}">{gng}</div>'
                        f'<div style="font-size:1.8rem;font-weight:700;color:#EDEAE2">{score}</div>'
                        f'<div style="font-size:.7rem;color:#A9A69D">Readiness Score</div>'
                        f'</div>', unsafe_allow_html=True)
            c2.markdown(f'<div class="info-box">{r.get("summary","")}</div>',
                        unsafe_allow_html=True)
            if r.get("recommended_submission_time"):
                c2.markdown(f'<div style="background:#1B2A41;border-left:3px solid #C6A15B;'
                            f'padding:.6rem 1rem;border-radius:0 4px 4px 0;font-size:.85rem;margin-top:.5rem">'
                            f'<strong>Recommended submission time:</strong> '
                            f'{r["recommended_submission_time"]}</div>', unsafe_allow_html=True)

            if r.get("blockers"):
                st.markdown("#### Blockers")
                for b in r["blockers"]:
                    sev_col = {"Critical":"#C0392B","High":"#E67E22","Medium":"#C6A15B"}.get(b.get("severity",""),"#6E6C66")
                    st.markdown(f'<div style="background:#1A0000;border:1px solid #3A0000;'
                                f'border-left:3px solid {sev_col};border-radius:0 4px 4px 0;'
                                f'padding:.6rem .8rem;margin:.3rem 0">'
                                f'<span style="color:{sev_col};font-weight:700">{b.get("severity","")}</span> — '
                                f'{b.get("item","")}'
                                f'<br><span style="color:#E57373;font-size:.8rem">Action: {b.get("action","")}</span>'
                                f'{"<br><span style=color:#A9A69D;font-size:.75rem>By: "+b.get("by_when","")+"</span>" if b.get("by_when") else ""}'
                                f'</div>', unsafe_allow_html=True)

            if r.get("warnings"):
                st.markdown("#### Warnings")
                for w in r["warnings"]:
                    st.markdown(f'<span style="color:#E67E22;font-size:.82rem">⚠ {w}</span>',
                                unsafe_allow_html=True)

            st.markdown("")

        st.markdown('<hr class="section-divider">', unsafe_allow_html=True)

        # ── Manual checklist ──────────────────────────────────────────────────
        st.markdown("### Submission Package Checklist")
        CHECKLIST = [
            ("Technical Proposal", "Separate searchable PDF", "technical"),
            ("Financial Proposal", "Separate searchable PDF (Appendix B both options)", "financial"),
            ("Supplement A", "Submission Form — signed by authorized signatory", "form"),
            ("Schedule A — AI Disclosure", "Completed and signed; aligned with methodology and pricing", "form"),
            ("Insurance confirmations", "Liability $2M + E&O $2M", "form"),
            ("Three references", "Contact details; max 1 CDA-AMC internal (pre-approved)", "supporting"),
            ("Coach CVs", "All proposed coaches with credentials", "supporting"),
            ("Case study / testimonial", "With measurable behaviour change outcomes", "supporting"),
            ("AI/Non-AI pricing alignment", "Technical methodology ↔ Financial pricing ↔ AI Disclosure all consistent", "qa"),
            ("File size check", "Total email ≤ 20 MB including all attachments", "qa"),
            ("Submission email", "To contracts@cda-amc.ca or MERX upload — before 14:00 Ottawa", "qa"),
        ]
        sub_docs = {d["name"]: d["status"] for d in docs if d.get("doc_type")=="Submission"}

        for item, detail, _ in CHECKLIST:
            matched_status = next((v for k,v in sub_docs.items()
                                   if item.lower()[:12] in k.lower()), None)
            icon = "✅" if matched_status=="Complete" else "⬜"
            col  = "#27AE60" if matched_status=="Complete" else "#EDEAE2"
            st.markdown(f'<div style="padding:.3rem 0;border-bottom:1px solid #1E1E22">'
                        f'<span style="color:{col}">{icon} <strong>{item}</strong></span> '
                        f'<span style="font-size:.78rem;color:#A9A69D">— {detail}</span></div>',
                        unsafe_allow_html=True)

        # Clarification answers check
        st.markdown("")
        unanswered = [c for c in clars if c.get("status")=="Submitted"]
        if unanswered:
            st.markdown(f'<div class="warn-box">⚠ {len(unanswered)} clarification question(s) '
                        f'submitted but not yet answered — check for CDA-AMC bulletins by July 28.</div>',
                        unsafe_allow_html=True)
        needs_matrix = [c for c in clars if c.get("changes_matrix") and c.get("status")=="Answered"]
        if needs_matrix:
            st.markdown(f'<div class="warn-box">⚠ {len(needs_matrix)} answered question(s) '
                        f'require compliance matrix updates — review before finalizing.</div>',
                        unsafe_allow_html=True)

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 2 — Proposal Review: upload final PDF → AI alignment analysis
    # ══════════════════════════════════════════════════════════════════════════
    with tab2:
        st.markdown("### Proposal Review — RFP Alignment Analysis")
        st.markdown('<div class="info-box">Upload your final proposal PDF. Claude reads it against '
                    'all RFP documents in the system and the compliance matrix, then produces a '
                    'scored alignment report with prioritised recommendations.</div>',
                    unsafe_allow_html=True)

        if not (api_key_configured() or st.session_state.get("anthropic_api_key")):
            st.markdown('<div class="warn-box">No API key configured.</div>',
                        unsafe_allow_html=True)
            st.stop()

        # ── Pull RFP text from uploaded documents ─────────────────────────────
        rfp_docs = [d for d in docs if d.get("doc_type") in
                    ("RFP", "RFSO", "Addendum", "RFP Document", "Supporting")]
        rfp_text_combined = ""
        if rfp_docs:
            from database import download_file as _dl
            for rd in rfp_docs[:3]:   # cap at 3 RFP docs to stay within context
                sp = rd.get("storage_path")
                if not sp:
                    continue
                try:
                    fb = _dl(sp)
                    if rd.get("name","").lower().endswith(".pdf"):
                        pdoc = fitz.open(stream=fb, filetype="pdf")
                        rfp_text_combined += "\n".join(pg.get_text() for pg in pdoc)[:4000]
                    else:
                        rfp_text_combined += fb.decode("utf-8", errors="ignore")[:4000]
                except Exception:
                    pass

        if rfp_docs:
            st.markdown(f'<span style="font-size:.78rem;color:#A9A69D">ℹ RFP context pulled from '
                        f'{len(rfp_docs)} document(s) in registry: '
                        f'{", ".join(d["name"] for d in rfp_docs[:3])}</span>',
                        unsafe_allow_html=True)
        else:
            st.markdown('<div class="warn-box">No RFP documents found in the Document Registry. '
                        'Upload the RFSO/RFP first for a more accurate analysis.</div>',
                        unsafe_allow_html=True)

        # ── Upload proposal ───────────────────────────────────────────────────
        uploaded = st.file_uploader(
            "Upload final proposal PDF",
            type=["pdf", "docx", "txt"],
            key=f"pr_upload_{bid_id}"
        )

        if uploaded:
            fb = uploaded.read()
            size_kb = len(fb) // 1024
            st.markdown(f'<div class="info-box">📄 <strong>{uploaded.name}</strong> — '
                        f'{size_kb} KB ready for analysis.</div>', unsafe_allow_html=True)
            st.session_state[f"pr_pending_{bid_id}"] = {"bytes": fb, "name": uploaded.name}

        pending = st.session_state.get(f"pr_pending_{bid_id}")

        if pending:
            col1, col2 = st.columns([3, 1])
            if col1.button("🔍 Analyze Proposal with Claude",
                           use_container_width=True, type="primary",
                           key=f"pr_run_{bid_id}"):
                with st.spinner("Reading proposal and running alignment analysis… 30–60 seconds"):
                    try:
                        fb = pending["bytes"]
                        name = pending["name"]
                        # Extract text
                        if name.lower().endswith(".pdf"):
                            pdoc = fitz.open(stream=fb, filetype="pdf")
                            proposal_text = "\n".join(pg.get_text() for pg in pdoc)
                        else:
                            proposal_text = fb.decode("utf-8", errors="ignore")

                        result = analyze_proposal_alignment(
                            proposal_text  = proposal_text,
                            requirements   = reqs,
                            rfp_text       = rfp_text_combined,
                            bid_info       = bid,
                        )
                        st.session_state[f"pr_result_{bid_id}"] = result
                        st.session_state[f"pr_filename_{bid_id}"] = name
                        st.rerun()
                    except Exception as e:
                        st.error(f"Analysis failed: {e}")

            if col2.button("✕ Clear", use_container_width=True, key=f"pr_clear_{bid_id}"):
                st.session_state.pop(f"pr_pending_{bid_id}", None)
                st.session_state.pop(f"pr_result_{bid_id}", None)
                st.rerun()

        # ── Results ───────────────────────────────────────────────────────────
        result = st.session_state.get(f"pr_result_{bid_id}")
        if not result:
            if not pending:
                st.markdown('<div style="text-align:center;padding:3rem 0;color:#6E6C66;'
                            'font-size:.9rem">Upload your proposal PDF above to run the analysis.'
                            '</div>', unsafe_allow_html=True)
        else:
            fname = st.session_state.get(f"pr_filename_{bid_id}", "proposal")
            st.markdown('<hr class="section-divider">', unsafe_allow_html=True)

            if result.get("_truncated"):
                st.markdown('<div class="warn-box">⚠ The model response was truncated — '
                            'coverage table or next steps may be incomplete. '
                            'Results shown are partial but findings and score are intact. '
                            'Re-run if needed.</div>', unsafe_allow_html=True)

            # ── Score header ──────────────────────────────────────────────────────
            score     = result.get("overall_score", 0)
            rec       = result.get("recommendation", "")
            rec_col   = {
                "SUBMIT AS-IS":             "#27AE60",
                "REVISE BEFORE SUBMITTING": "#E67E22",
                "MAJOR REVISION NEEDED":    "#C0392B",
            }.get(rec, "#6E6C66")

            def _score_ring(s):
                s_col = "#27AE60" if s >= 75 else "#E67E22" if s >= 55 else "#C0392B"
                return (f'<div style="text-align:center;background:#131316;border:2px solid {s_col};'
                        f'border-radius:8px;padding:1.2rem .8rem">'
                        f'<div style="font-size:2.4rem;font-weight:800;color:{s_col}">{s}</div>'
                        f'<div style="font-size:.7rem;color:#A9A69D;text-transform:uppercase;'
                        f'letter-spacing:.06em">Alignment Score</div></div>')

            c1, c2 = st.columns([1, 4])
            c1.markdown(_score_ring(score), unsafe_allow_html=True)
            with c2:
                st.markdown(f'<div style="background:{rec_col}22;border:1px solid {rec_col}55;'
                            f'border-radius:6px;padding:.6rem 1rem;margin-bottom:.5rem">'
                            f'<span style="font-weight:700;color:{rec_col}">{rec}</span></div>',
                            unsafe_allow_html=True)
                st.markdown(f'<div class="info-box">{result.get("executive_summary","")}</div>',
                            unsafe_allow_html=True)
                st.markdown(f'<span style="font-size:.74rem;color:#6E6C66">Analyzed: '
                            f'<em>{fname}</em> · {len(reqs)} requirements in matrix</span>',
                            unsafe_allow_html=True)

            st.markdown("")

            # ── PDF export button ─────────────────────────────────────────────────
            try:
                from pdf_styles import generate_proposal_review_pdf
                pdf_bytes = generate_proposal_review_pdf(bid, result, fname)
                safe_name = (bid.get("client") or "proposal").replace(" ", "_")
                st.download_button(
                    label="📄 Export Report as PDF",
                    data=pdf_bytes,
                    file_name=f"{safe_name}_proposal_review.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                    key=f"pr_pdf_{bid_id}",
                )
            except Exception as pdf_err:
                st.warning(f"PDF export unavailable: {pdf_err}")

            st.markdown("")

            # ── Strengths ─────────────────────────────────────────────────────────
            strengths = result.get("strengths", [])
            if strengths:
                with st.expander("✅ Strengths", expanded=False):
                    for s in strengths:
                        st.markdown(f'<span style="color:#27AE60;font-size:.85rem">✓ {s}</span>',
                                    unsafe_allow_html=True)

            # ── Findings by severity ──────────────────────────────────────────────
            findings = result.get("findings", [])
            SEV_ORDER  = ["Critical", "High", "Medium", "Low"]
            SEV_COLOUR = {
                "Critical": "#C0392B",
                "High":     "#E67E22",
                "Medium":   "#C6A15B",
                "Low":      "#6E6C66",
            }
            SEV_BG = {
                "Critical": "#1A0000",
                "High":     "#1A0A00",
                "Medium":   "#1A1500",
                "Low":      "#131316",
            }
            EFFORT_COL = {
                "Minor edit":      "#27AE60",
                "Moderate rewrite":"#E67E22",
                "Major addition":  "#C0392B",
            }

            if findings:
                st.markdown("### Findings")

                # Summary strip
                for sev in SEV_ORDER:
                    count = sum(1 for f in findings if f.get("severity") == sev)
                    if count:
                        sc = SEV_COLOUR[sev]
                        st.markdown(
                            f'<span style="background:{sc}22;border:1px solid {sc}44;'
                            f'border-radius:4px;padding:.15rem .5rem;margin-right:.4rem;'
                            f'font-size:.78rem;color:{sc};font-weight:600">'
                            f'{sev}: {count}</span>',
                            unsafe_allow_html=True
                        )
                st.markdown("")

                # Stage colour legend
                STAGE_COL = {
                    "Proposal Submission":       "#C0392B",
                    "Negotiation / Shortlist":   "#E67E22",
                    "Contract Execution":        "#2471A3",
                    "Contractual Obligation":    "#6E6C66",
                }
                for stage_label, sc2 in STAGE_COL.items():
                    stage_count = sum(1 for f in findings if f.get("stage") == stage_label)
                    if stage_count:
                        st.markdown(
                            f'<span style="background:{sc2}22;border:1px solid {sc2}55;'
                            f'border-radius:4px;padding:.15rem .55rem;margin-right:.4rem;'
                            f'font-size:.75rem;color:{sc2}">'
                            f'{stage_label}: {stage_count}</span>',
                            unsafe_allow_html=True
                        )
                st.markdown("")

                for sev in SEV_ORDER:
                    sev_findings = [f for f in findings if f.get("severity") == sev]
                    if not sev_findings:
                        continue
                    sc = SEV_COLOUR[sev]
                    bg = SEV_BG[sev]
                    st.markdown(
                        f'<div style="margin:.8rem 0 .3rem 0;font-size:.78rem;'
                        f'color:{sc};font-weight:700;letter-spacing:.06em;'
                        f'text-transform:uppercase">{sev} ({len(sev_findings)})</div>',
                        unsafe_allow_html=True
                    )
                    for idx, finding in enumerate(sev_findings):
                        title    = finding.get("title", "Finding")
                        issue    = finding.get("issue", "")
                        rec_text = finding.get("recommendation", "")
                        location = finding.get("proposal_location", "")
                        effort   = finding.get("effort", "")
                        req_id   = finding.get("req_id", "")
                        cat      = finding.get("category", "")
                        stage    = finding.get("stage", "")
                        stage_c  = STAGE_COL.get(stage, "#6E6C66")
                        ec       = EFFORT_COL.get(effort, "#6E6C66")

                        label = f"{sev[0]}{idx+1}  {title}"
                        if req_id:
                            label += f"  [{req_id}]"

                        with st.expander(label, expanded=(sev == "Critical")):
                            st.markdown(
                                f'<div style="background:{bg};border:1px solid {sc}33;'
                                f'border-left:3px solid {sc};border-radius:0 6px 6px 0;'
                                f'padding:.8rem 1rem">'
                                f'<div style="font-size:.78rem;color:#A9A69D;margin-bottom:.5rem">'
                                f'<span style="color:{sc};font-weight:600">{sev}</span>'
                                f'{" · "+cat if cat else ""}'
                                f'{" · Req "+req_id if req_id else ""}'
                                f'{" · "+location if location and location != "N/A" else ""}'
                                f'</div>'
                                f'{"<div style=background:"+stage_c+"22;border:1px solid "+stage_c+"44;border-radius:4px;padding:.2rem .6rem;display:inline-block;font-size:.72rem;color:"+stage_c+";font-weight:600;margin-bottom:.5rem>⏱ "+stage+"</div>" if stage else ""}'
                                f'<div style="font-size:.88rem;color:#EDEAE2;margin-bottom:.6rem">'
                                f'<strong>Issue:</strong> {issue}</div>'
                                f'<div style="font-size:.85rem;color:#C6A15B;margin-bottom:.4rem">'
                                f'<strong>Recommendation:</strong> {rec_text}</div>'
                                f'<div style="font-size:.75rem;color:{ec}">'
                                f'Effort: {effort}</div>'
                                f'</div>',
                                unsafe_allow_html=True
                            )
            else:
                st.markdown('<div class="info-box">No findings returned — analysis may have '
                            'encountered a parsing issue. Try re-running.</div>',
                            unsafe_allow_html=True)

            # ── Requirement coverage table ────────────────────────────────────────
            coverage = result.get("requirement_coverage", [])
            if coverage:
                st.markdown("### Requirement Coverage")

                COV_COL = {
                    "Fully Addressed":     "#27AE60",
                    "Partially Addressed": "#E67E22",
                    "Not Addressed":       "#C0392B",
                    "Cannot Assess":       "#6E6C66",
                }

                # Summary counts
                for status in ["Fully Addressed","Partially Addressed","Not Addressed","Cannot Assess"]:
                    count = sum(1 for c in coverage if c.get("coverage") == status)
                    if count:
                        sc = COV_COL[status]
                        st.markdown(
                            f'<span style="background:{sc}22;border:1px solid {sc}44;'
                            f'border-radius:4px;padding:.15rem .5rem;margin-right:.4rem;'
                            f'font-size:.78rem;color:{sc}">{status}: {count}</span>',
                            unsafe_allow_html=True
                        )
                st.markdown("")

                # Coverage rows
                hdr = st.columns([1, 1.5, 3, 2.5, 1.5])
                for col_w, label in zip(hdr, ["Req ID","Category","Description","Coverage","Confidence"]):
                    col_w.markdown(f'<span style="font-size:.72rem;color:#6E6C66;'
                                   f'text-transform:uppercase;font-weight:600">{label}</span>',
                                   unsafe_allow_html=True)
                st.markdown('<hr class="section-divider" style="margin:.2rem 0">', unsafe_allow_html=True)

                for cov in coverage:
                    cov_status = cov.get("coverage","")
                    cc = COV_COL.get(cov_status,"#6E6C66")
                    conf = cov.get("confidence","")
                    notes = cov.get("notes","")
                    row = st.columns([1, 1.5, 3, 2.5, 1.5])
                    row[0].markdown(f'<span style="font-size:.8rem;color:#C6A15B">'
                                    f'{cov.get("req_id","")}</span>', unsafe_allow_html=True)
                    row[1].markdown(f'<span style="font-size:.78rem;color:#A9A69D">'
                                    f'{cov.get("category","")}</span>', unsafe_allow_html=True)
                    row[2].markdown(f'<span style="font-size:.8rem">{cov.get("description","")}'
                                    f'{"<br><span style=font-size:.72rem;color:#6E6C66>"+notes+"</span>" if notes else ""}'
                                    f'</span>', unsafe_allow_html=True)
                    row[3].markdown(f'<span style="color:{cc};font-size:.8rem">{cov_status}</span>',
                                    unsafe_allow_html=True)
                    row[4].markdown(f'<span style="font-size:.78rem;color:#A9A69D">{conf}</span>',
                                    unsafe_allow_html=True)
                    st.markdown('<hr class="section-divider" style="margin:.15rem 0">',
                                unsafe_allow_html=True)

            # ── Next steps ────────────────────────────────────────────────────────
            next_steps = result.get("next_steps", [])
            if next_steps:
                st.markdown("### Recommended Next Steps")
                WHEN_COL = {
                    "Before submission":        "#C0392B",
                    "If shortlisted":           "#E67E22",
                    "Before contract execution":"#2471A3",
                }
                for step in sorted(next_steps, key=lambda x: x.get("priority", 99)):
                    pri  = step.get("priority", "")
                    when = step.get("when", "")
                    wc   = WHEN_COL.get(when, "#6E6C66")
                    when_badge = (
                        f'<span style="background:{wc}22;border:1px solid {wc}44;'
                        f'border-radius:3px;padding:.1rem .4rem;font-size:.7rem;'
                        f'color:{wc};font-weight:600;margin-left:.5rem">{when}</span>'
                        if when else ""
                    )
                    st.markdown(
                        f'<div style="background:#131316;border:1px solid #2A2A2E;'
                        f'border-left:3px solid #C6A15B;border-radius:0 4px 4px 0;'
                        f'padding:.6rem 1rem;margin:.3rem 0">'
                        f'<span style="color:#C6A15B;font-weight:700;font-size:.8rem">#{pri}</span> '
                        f'<span style="font-size:.88rem;color:#EDEAE2">{step.get("action","")}</span>'
                        f'{when_badge}'
                        f'<br><span style="font-size:.78rem;color:#A9A69D">{step.get("rationale","")}</span>'
                        f'</div>',
                        unsafe_allow_html=True
                    )

            # ── Re-run / clear ────────────────────────────────────────────────────
            st.markdown("")
            c1, c2 = st.columns(2)
            if c1.button("🔄 Re-run analysis", use_container_width=True, key=f"pr_rerun_{bid_id}"):
                st.session_state.pop(f"pr_result_{bid_id}", None)
                st.rerun()
            if c2.button("🗑 Clear results", use_container_width=True, key=f"pr_del_{bid_id}"):
                st.session_state.pop(f"pr_result_{bid_id}", None)
                st.session_state.pop(f"pr_pending_{bid_id}", None)
                st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# WIN/LOSS DEBRIEF
# ═══════════════════════════════════════════════════════════════════════════════
def page_debrief(bid_id):
    debriefs= get_debriefs(bid_id)

    st.markdown("# Win / Loss Debrief")
    st.markdown('<div class="gold-rule"></div>', unsafe_allow_html=True)
    st.markdown('<div class="info-box">Record the outcome and evaluation feedback for this bid. '
                'Over time, this builds Phoenix\'s institutional win-rate intelligence — '
                'which sectors they win, at what price points, and where scoring is weakest.</div>',
                unsafe_allow_html=True)

    if debriefs:
        d = debriefs[0]
        outcome_col = {"Won":"#27AE60","Lost":"#C0392B","Pending":"#C6A15B"}.get(
            d.get("outcome","Pending"),"#6E6C66")
        c1,c2,c3,c4 = st.columns(4)
        c1.markdown(f'<div class="metric-card"><div class="label">Outcome</div>'
                    f'<div class="value" style="color:{outcome_col};font-size:1.4rem">'
                    f'{d.get("outcome","Pending")}</div></div>', unsafe_allow_html=True)
        c2.markdown(f'<div class="metric-card"><div class="label">Technical Score</div>'
                    f'<div class="value">{d.get("score_technical") or "—"}</div></div>',
                    unsafe_allow_html=True)
        c3.markdown(f'<div class="metric-card"><div class="label">Financial Score</div>'
                    f'<div class="value">{d.get("score_financial") or "—"}</div></div>',
                    unsafe_allow_html=True)
        c4.markdown(f'<div class="metric-card"><div class="label">Total Score / Rank</div>'
                    f'<div class="value">{d.get("score_total") or "—"}'
                    f'{"  #"+str(d["rank"]) if d.get("rank") else ""}</div></div>',
                    unsafe_allow_html=True)

        if d.get("evaluator_feedback"):
            st.markdown("### Evaluator Feedback")
            st.markdown(f'<div class="info-box">{d["evaluator_feedback"]}</div>',
                        unsafe_allow_html=True)
        c1,c2 = st.columns(2)
        if d.get("win_factors"):
            c1.markdown("### What worked")
            for f in d["win_factors"].split("\n"):
                if f.strip():
                    c1.markdown(f'<span style="color:#27AE60;font-size:.85rem">✓ {f.strip()}</span>',
                                unsafe_allow_html=True)
        if d.get("loss_factors"):
            c2.markdown("### What didn't")
            for f in d["loss_factors"].split("\n"):
                if f.strip():
                    c2.markdown(f'<span style="color:#C0392B;font-size:.85rem">✗ {f.strip()}</span>',
                                unsafe_allow_html=True)
        if d.get("lessons"):
            st.markdown("### Lessons for next time")
            st.markdown(f'<div class="info-box">{d["lessons"]}</div>', unsafe_allow_html=True)
        if d.get("competitors"):
            st.markdown(f'<span style="font-size:.78rem;color:#6E6C66">Competitors identified: {d["competitors"]}</span>',
                        unsafe_allow_html=True)

        if st.button("✏ Edit Debrief", key="edit_deb"):
            st.session_state["editing_debrief"] = d["id"]

    else:
        st.markdown('<div class="empty-state">No debrief recorded yet. '
                    'Complete after outcome notification (expected September 24, 2026).</div>',
                    unsafe_allow_html=True)

    # ── Form (new or edit) ────────────────────────────────────────────────────
    show_form = not debriefs or st.session_state.get("editing_debrief")
    if show_form:
        d = debriefs[0] if (debriefs and st.session_state.get("editing_debrief")) else {}
        st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
        st.markdown("### Record / Update Debrief")
        with st.form("debrief_form"):
            c1,c2,c3,c4 = st.columns(4)
            outcome = c1.selectbox("Outcome", DEBRIEF_OUTCOMES,
                                   index=DEBRIEF_OUTCOMES.index(d.get("outcome","Pending"))
                                   if d.get("outcome") in DEBRIEF_OUTCOMES else 4)
            t_score = c2.number_input("Technical Score", value=float(d.get("score_technical") or 0),
                                      min_value=0.0, max_value=100.0, step=0.5)
            f_score = c3.number_input("Financial Score", value=float(d.get("score_financial") or 0),
                                      min_value=0.0, max_value=100.0, step=0.5)
            rank    = c4.number_input("Rank", value=int(d.get("rank") or 0), min_value=0, step=1)
            total   = st.number_input("Total Score", value=float(d.get("score_total") or 0),
                                      min_value=0.0, max_value=100.0, step=0.1)
            competitors = st.text_input("Competitors (if known)", value=d.get("competitors",""))
            feedback    = st.text_area("Evaluator Feedback", value=d.get("evaluator_feedback",""), height=100)
            c1,c2 = st.columns(2)
            wins  = c1.text_area("What worked (one per line)", value=d.get("win_factors",""), height=100)
            losses= c2.text_area("What didn't (one per line)", value=d.get("loss_factors",""), height=100)
            lessons= st.text_area("Lessons for next time", value=d.get("lessons",""), height=80)
            notes  = st.text_area("Notes", value=d.get("notes",""), height=60)
            if st.form_submit_button("Save Debrief", use_container_width=True):
                upsert_debrief({"id":d.get("id"),"bid_id":bid_id,"outcome":outcome,
                    "score_technical":t_score or None,"score_financial":f_score or None,
                    "score_total":total or None,"rank":rank or None,
                    "competitors":competitors,"evaluator_feedback":feedback,
                    "win_factors":wins,"loss_factors":losses,
                    "lessons":lessons,"notes":notes})
                if "editing_debrief" in st.session_state:
                    del st.session_state["editing_debrief"]
                st.success("Debrief saved.")
                st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# EXECUTIVE DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════════
def page_exec_dashboard():
    from database import (get_all_bids, get_requirements, get_tasks,
                          get_clarifications, get_debriefs, get_coaches,
                          get_documents)
    from datetime import date

    st.markdown("# Executive Dashboard")
    st.markdown(
        f'<div style="font-size:.82rem;color:#A9A69D;margin-bottom:.5rem">'
        f'Phoenix Consulting International  ·  '
        f'Bid Intelligence Platform  ·  '
        f'{date.today().strftime("%B %d, %Y")}</div>',
        unsafe_allow_html=True)
    st.markdown('<div class="gold-rule"></div>', unsafe_allow_html=True)

    bids = get_all_bids()
    if not bids:
        st.markdown('<div class="empty-state">No bids in the pipeline yet.</div>',
                    unsafe_allow_html=True)
        return

    # ── Enrich each bid with full data ────────────────────────────────────────
    enriched = []
    for b in bids:
        reqs  = get_requirements(b["id"])
        tasks = get_tasks(b["id"])
        clars = get_clarifications(b["id"])
        debs  = get_debriefs(b["id"])

        m_total  = len([r for r in reqs if r["category"]=="Mandatory"])
        m_done   = len([r for r in reqs if r["category"]=="Mandatory" and r["status"]=="Complete"])
        r_total  = len([r for r in reqs if r["category"]=="Rated"])
        r_done   = len([r for r in reqs if r["category"]=="Rated" and r["status"]=="Complete"])
        t_total  = len(tasks)
        t_done   = len([t for t in tasks if t["status"]=="Complete"])
        t_blocked= len([t for t in tasks if t["status"]=="Blocked"])
        clar_unanswered = len([c for c in clars if c["status"]=="Submitted"])
        clar_changes    = len([c for c in clars if c.get("changes_matrix") and c["status"]=="Answered"])
        outcome = debs[0].get("outcome") if debs else None
        score   = debs[0].get("score_total") if debs else None

        d = days_until(b.get("submission_deadline"))

        # Overall readiness %
        total_items = (m_total + r_total + t_total)
        done_items  = (m_done  + r_done  + t_done)
        readiness   = round(done_items / total_items * 100) if total_items else 0

        # Risk level
        risk = "Low"
        if m_total > 0 and m_done < m_total:
            risk = "High" if (m_total - m_done) >= 3 else "Medium"
        if d is not None and d <= 7 and readiness < 60:
            risk = "High"
        if t_blocked > 0:
            risk = max(risk, "Medium",
                       key=lambda x: ["Low","Medium","High"].index(x))
        if clar_changes > 0:
            risk = "High"

        enriched.append({**b,
            "m_total":m_total,"m_done":m_done,
            "r_total":r_total,"r_done":r_done,
            "t_total":t_total,"t_done":t_done,"t_blocked":t_blocked,
            "clar_unanswered":clar_unanswered,"clar_changes":clar_changes,
            "outcome":outcome,"score":score,
            "days":d,"readiness":readiness,"risk":risk,
        })

    # ── KPI strip ─────────────────────────────────────────────────────────────
    active    = [b for b in enriched if b["stage"] in ("Qualifying","In Progress","Review")]
    won       = [b for b in enriched if b["stage"]=="Won"]
    lost      = [b for b in enriched if b["stage"]=="Lost"]
    at_risk   = [b for b in active    if b["risk"]=="High"]
    urgent    = [b for b in active    if (b["days"] or 999) <= 14]

    wr = f"{round(len(won)/(len(won)+len(lost))*100)}%" if (won or lost) else "—"
    pipeline_val = sum(b.get("value_cad") or 0 for b in active)
    won_val      = sum(b.get("value_cad") or 0 for b in won)

    c1,c2,c3,c4,c5,c6 = st.columns(6)
    def kpi(col, label, value, sub="", colour="#EDEAE2"):
        col.markdown(
            f'<div style="background:#131316;border:1px solid #2A2A2E;border-radius:6px;'
            f'padding:.8rem .6rem;text-align:center">'
            f'<div style="font-size:.68rem;color:#A9A69D;text-transform:uppercase;'
            f'letter-spacing:.06em;margin-bottom:.2rem">{label}</div>'
            f'<div style="font-size:1.5rem;font-weight:700;color:{colour}">{value}</div>'
            f'{"<div style=font-size:.72rem;color:#6E6C66;margin-top:.15rem>" + sub + "</div>" if sub else ""}'
            f'</div>', unsafe_allow_html=True)

    kpi(c1, "Active Bids",       len(active),    f"{len(bids)} total")
    kpi(c2, "Pipeline Value",
        f"${pipeline_val/1000:.0f}K" if pipeline_val else "—",
        "active opportunities")
    kpi(c3, "At Risk",           len(at_risk),   "need attention",
        "#C0392B" if at_risk else "#27AE60")
    kpi(c4, "Deadlines ≤14d",   len(urgent),    "immediate action",
        "#E67E22" if urgent else "#27AE60")
    kpi(c5, "Win Rate",          wr,             f"{len(won)}W / {len(lost)}L",
        "#27AE60" if won else "#EDEAE2")
    kpi(c6, "Won Value",
        f"${won_val/1000:.0f}K" if won_val else "—",
        "confirmed revenue")

    st.markdown("")

    # ── Alert bar ─────────────────────────────────────────────────────────────
    alerts = []
    for b in enriched:
        if b.get("clar_changes"):
            alerts.append(f"<strong>{b['client']}</strong> — {b['clar_changes']} clarification answer(s) require compliance matrix updates")
        if b.get("clar_unanswered") and (b["days"] or 999) <= 10:
            alerts.append(f"<strong>{b['client']}</strong> — {b['clar_unanswered']} question(s) submitted but unanswered; bulletin deadline approaching")
        if b["stage"] in ("In Progress","Review") and (b["days"] or 999) <= 5:
            alerts.append(f"<strong>{b['client']}</strong> — submission in {b['days']} day(s)")
        if b["m_total"] > 0 and b["m_done"] < b["m_total"] and (b["days"] or 999) <= 14:
            outstanding = b["m_total"] - b["m_done"]
            alerts.append(f"<strong>{b['client']}</strong> — {outstanding} mandatory requirement(s) incomplete with {b['days']} days to deadline")

    if alerts:
        st.markdown(
            f'<div style="background:#1A0505;border:1px solid #C0392B44;border-left:3px solid #C0392B;'
            f'border-radius:0 6px 6px 0;padding:.8rem 1.2rem;margin-bottom:1rem">'
            f'<div style="font-size:.75rem;color:#C0392B;font-weight:700;text-transform:uppercase;'
            f'letter-spacing:.06em;margin-bottom:.4rem">⚠  Alerts requiring attention</div>'
            f'{"".join(f"<div style=font-size:.82rem;color:#E57373;padding:.15rem 0>· {a}</div>" for a in alerts)}'
            f'</div>', unsafe_allow_html=True)

    # ── Active bids table ──────────────────────────────────────────────────────
    st.markdown("### Active Bids")

    # Column headers
    hcols = st.columns([2.5, 1.2, 1, 1.2, 1.5, 1, 1.2, 0.8])
    for h, col in zip(["Client / Opportunity","Stage","Deadline","Readiness",
                        "Mandatory","Tasks","Risk",""], hcols):
        col.markdown(
            f'<span style="font-size:.7rem;color:#A9A69D;font-weight:600;'
            f'text-transform:uppercase">{h}</span>',
            unsafe_allow_html=True)

    STAGE_COL = {
        "Identified":"#6E6C66","Qualifying":"#C6A15B",
        "In Progress":"#2980B9","Review":"#8E44AD",
        "Submitted":"#27AE60","Won":"#1E8449",
        "Lost":"#C0392B","No Bid":"#555555",
    }
    RISK_COL = {"High":"#C0392B","Medium":"#E67E22","Low":"#27AE60"}

    active_sorted = sorted(
        [b for b in enriched if b["stage"] not in ("Won","Lost","No Bid")],
        key=lambda x: (x["days"] or 999))

    for b in active_sorted:
        c1,c2,c3,c4,c5,c6,c7,c8 = st.columns([2.5,1.2,1,1.2,1.5,1,1.2,0.8])
        stage_col = STAGE_COL.get(b["stage"],"#6E6C66")
        risk_col  = RISK_COL.get(b["risk"],"#6E6C66")

        # Client + title
        c1.markdown(
            f'<span style="font-weight:600;font-size:.9rem">{b["client"]}</span><br>'
            f'<span style="font-size:.75rem;color:#A9A69D">'
            f'{b["title"][:45]}{"…" if len(b["title"])>45 else ""}</span>',
            unsafe_allow_html=True)

        # Stage badge
        c2.markdown(
            f'<span style="background:{stage_col}22;color:{stage_col};'
            f'padding:.15rem .5rem;border-radius:3px;font-size:.75rem;font-weight:600">'
            f'{b["stage"]}</span>',
            unsafe_allow_html=True)

        # Deadline
        d = b["days"]
        if d is None:
            c3.markdown('<span style="color:#6E6C66;font-size:.8rem">—</span>',
                        unsafe_allow_html=True)
        elif d < 0:
            c3.markdown('<span style="color:#C0392B;font-size:.8rem;font-weight:700">'
                        'OVERDUE</span>', unsafe_allow_html=True)
        elif d == 0:
            c3.markdown('<span style="color:#C0392B;font-size:.8rem;font-weight:700">'
                        'TODAY</span>', unsafe_allow_html=True)
        elif d <= 7:
            c3.markdown(f'<span style="color:#E67E22;font-size:.85rem;font-weight:700">'
                        f'{d}d</span>', unsafe_allow_html=True)
        else:
            c3.markdown(f'<span style="font-size:.85rem;color:#A9A69D">{d}d</span>',
                        unsafe_allow_html=True)

        # Readiness bar
        r = b["readiness"]
        bar_col = "#27AE60" if r>=80 else "#E67E22" if r>=50 else "#C0392B"
        c4.markdown(
            f'<div style="background:#1A1A1E;border-radius:3px;height:6px;margin-top:.5rem">'
            f'<div style="background:{bar_col};width:{r}%;height:6px;border-radius:3px"></div>'
            f'</div>'
            f'<span style="font-size:.72rem;color:{bar_col}">{r}%</span>',
            unsafe_allow_html=True)

        # Mandatory
        m_col = "#27AE60" if b["m_done"]==b["m_total"] and b["m_total"]>0 else \
                "#C0392B" if b["m_done"]<b["m_total"] else "#6E6C66"
        c5.markdown(
            f'<span style="font-size:.85rem;color:{m_col}">'
            f'{b["m_done"]}/{b["m_total"]} complete</span>',
            unsafe_allow_html=True)
        if b["clar_changes"]:
            c5.markdown(
                f'<span style="font-size:.7rem;color:#C0392B">'
                f'⚠ {b["clar_changes"]} matrix update(s)</span>',
                unsafe_allow_html=True)

        # Tasks
        t_col = "#C0392B" if b["t_blocked"] else \
                "#27AE60" if b["t_done"]==b["t_total"] and b["t_total"]>0 else "#A9A69D"
        c6.markdown(
            f'<span style="font-size:.85rem;color:{t_col}">'
            f'{b["t_done"]}/{b["t_total"]}</span>'
            f'{"<br><span style=font-size:.7rem;color:#C0392B>" + str(b["t_blocked"]) + " blocked</span>" if b["t_blocked"] else ""}',
            unsafe_allow_html=True)

        # Risk
        c7.markdown(
            f'<span style="background:{risk_col}22;color:{risk_col};'
            f'padding:.15rem .5rem;border-radius:3px;font-size:.75rem;font-weight:700">'
            f'{b["risk"]}</span>',
            unsafe_allow_html=True)

        # Open button
        if c8.button("→", key=f"ex_{b['id']}",
                     help=f"Open {b['client']}"):
            st.session_state.active_bid = b["id"]
            st.session_state.page = "bid_overview"
            st.rerun()

        st.markdown(
            '<hr class="section-divider" style="margin:.3rem 0">',
            unsafe_allow_html=True)

    # ── Upcoming deadlines timeline ────────────────────────────────────────────
    deadline_bids = [(b, b["days"]) for b in enriched
                     if b["days"] is not None and -5 <= b["days"] <= 60
                     and b["stage"] not in ("Won","Lost","No Bid")]
    if deadline_bids:
        st.markdown("")
        st.markdown("### Deadline Timeline")

        timeline_data = sorted(deadline_bids, key=lambda x: x[1])
        max_days = max(d for _,d in timeline_data) or 1

        for b, d in timeline_data:
            pct  = max(0, min(100, int(d / max(max_days, 1) * 100)))
            col  = "#C0392B" if d<=7 else "#E67E22" if d<=21 else "#2980B9"
            label= b.get("submission_deadline","")
            st.markdown(
                f'<div style="margin:.4rem 0">'
                f'<div style="display:flex;justify-content:space-between;'
                f'align-items:center;margin-bottom:.2rem">'
                f'<span style="font-size:.82rem;font-weight:600">{b["client"]}</span>'
                f'<span style="font-size:.78rem;color:{col};font-weight:700">'
                f'{"OVERDUE" if d<0 else f"{d} days — {label}"}</span></div>'
                f'<div style="background:#1A1A1E;border-radius:3px;height:5px">'
                f'<div style="background:{col};width:{pct}%;height:5px;'
                f'border-radius:3px;opacity:.7"></div></div></div>',
                unsafe_allow_html=True)

    # ── Won / Lost outcomes ───────────────────────────────────────────────────
    completed = [b for b in enriched if b["stage"] in ("Won","Lost")]
    if completed:
        st.markdown("")
        st.markdown("### Recent Outcomes")
        c1,c2 = st.columns(2)

        with c1:
            wins = [b for b in completed if b["stage"]=="Won"]
            st.markdown(f'<span style="color:#27AE60;font-weight:600">'
                        f'WON ({len(wins)})</span>', unsafe_allow_html=True)
            for b in wins:
                val = f"  ·  CAD {b['value_cad']:,.0f}" if b.get("value_cad") else ""
                score = f"  ·  Score: {b['score']}" if b.get("score") else ""
                st.markdown(
                    f'<div style="padding:.3rem 0;border-bottom:1px solid #1E1E22">'
                    f'<span style="color:#27AE60">✓</span> '
                    f'<strong>{b["client"]}</strong>{val}{score}</div>',
                    unsafe_allow_html=True)

        with c2:
            losses = [b for b in completed if b["stage"]=="Lost"]
            st.markdown(f'<span style="color:#C0392B;font-weight:600">'
                        f'LOST ({len(losses)})</span>', unsafe_allow_html=True)
            for b in losses:
                score = f"  ·  Score: {b['score']}" if b.get("score") else ""
                st.markdown(
                    f'<div style="padding:.3rem 0;border-bottom:1px solid #1E1E22">'
                    f'<span style="color:#C0392B">✗</span> '
                    f'<strong>{b["client"]}</strong>{score}</div>',
                    unsafe_allow_html=True)

    # ── Coach roster summary ──────────────────────────────────────────────────
    coaches = get_coaches()
    if coaches:
        st.markdown("")
        st.markdown("### Coach Roster")
        avail   = [c for c in coaches if c.get("availability")=="Available"]
        partial = [c for c in coaches if c.get("availability")=="Partially Available"]
        unavail = [c for c in coaches if c.get("availability")=="Unavailable"]

        c1,c2,c3,c4 = st.columns(4)
        c1.metric("Total Coaches", len(coaches))
        c2.metric("Available",     len(avail))
        c3.metric("Partial",       len(partial))
        c4.metric("Unavailable",   len(unavail))

        # Availability dots
        st.markdown(
            '<div style="display:flex;flex-wrap:wrap;gap:.4rem;margin-top:.5rem">',
            unsafe_allow_html=True)
        for coach in coaches:
            col = {"Available":"#27AE60","Partially Available":"#E67E22",
                   "Unavailable":"#C0392B"}.get(coach.get("availability",""),"#6E6C66")
            st.markdown(
                f'<span style="background:{col}22;border:1px solid {col}55;'
                f'color:{col};padding:.2rem .6rem;border-radius:12px;'
                f'font-size:.75rem">{coach["name"]}</span>',
                unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

    # ── PDF export ────────────────────────────────────────────────────────────
    st.markdown("")
    st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
    if st.button("⬇ Export Executive Report (PDF)", use_container_width=False):
        try:
            pdf = _exec_dashboard_pdf(enriched, coaches, alerts)
            st.download_button(
                "⬇ Download PDF",
                data=pdf,
                file_name=f"phoenix_bid_executive_report_{date.today().isoformat()}.pdf",
                mime="application/pdf")
        except Exception as e:
            st.error(f"PDF error: {e}")


def _exec_dashboard_pdf(bids, coaches, alerts):
    """McKinsey-style executive dashboard PDF — A4 portrait."""
    import io
    from datetime import date
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.colors import HexColor
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                     Table, TableStyle, HRFlowable)
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_LEFT, TA_CENTER
    from pdf_styles import (_font, C_NAVY, C_BLUE, C_BLUE_L, C_WHITE, C_BLACK,
                             C_GREY_1, C_GREY_2, C_GREY_3, C_GREY_4,
                             C_RED, C_GREEN)

    C_AMBER = HexColor("#E26B0A")

    fn_r  = _font("regular")
    fn_sb = _font("semibold")
    fn_b  = _font("bold")

    def sp(name, size=9, fn=None, color=None, align=TA_LEFT, leading=None):
        return ParagraphStyle(name, fontName=fn or fn_r, fontSize=size,
            leading=leading or size*1.4, textColor=color or C_BLACK,
            alignment=align, spaceAfter=0, spaceBefore=0)

    def pp(text, size=9, fn=None, color=None, align=TA_LEFT, leading=None):
        return Paragraph(str(text) if text else "—",
                         sp("x", size, fn, color, align, leading))

    buf = io.BytesIO()
    PW, PH = A4
    ML = MR = 20*mm
    CW = PW - ML - MR

    doc = SimpleDocTemplate(buf, pagesize=A4,
        leftMargin=ML, rightMargin=MR, topMargin=20*mm, bottomMargin=20*mm,
        title="Executive Bid Report — Phoenix Consulting International")

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(C_GREY_3)
        canvas.setLineWidth(0.5)
        canvas.line(ML, 14*mm, PW-MR, 14*mm)
        canvas.setFont(fn_r, 7)
        canvas.setFillColor(C_GREY_2)
        canvas.drawString(ML, 10*mm,
            "Phoenix Consulting International  ·  Bid Intelligence Platform  ·  Executive Report")
        canvas.drawRightString(PW-MR, 10*mm, f"Page {doc.page}")
        canvas.restoreState()

    story = []

    # Header
    story.append(pp("Enable My Growth  ·  Bid Intelligence Platform",
                    7.5, fn_sb, C_BLUE))
    story.append(Spacer(1, 1*mm))
    story.append(pp("Executive Bid Report", 8, fn_r, C_GREY_1))
    story.append(Spacer(1, 3*mm))
    story.append(HRFlowable(width="100%", thickness=3, color=C_NAVY, spaceAfter=3*mm))
    story.append(pp("Phoenix Consulting International", 20, fn_b, C_NAVY, leading=24))
    story.append(Spacer(1, 1*mm))
    story.append(pp("Bid Pipeline — Executive Summary", 10, fn_r, C_GREY_1))
    story.append(Spacer(1, 1*mm))
    story.append(pp(f"Generated  {date.today().strftime('%B %d, %Y')}", 8, fn_r, C_GREY_2))
    story.append(Spacer(1, 1.5*mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=C_GREY_3, spaceAfter=5*mm))

    # KPI scorecard
    active    = [b for b in bids if b["stage"] in ("Qualifying","In Progress","Review")]
    won       = [b for b in bids if b["stage"]=="Won"]
    lost      = [b for b in bids if b["stage"]=="Lost"]
    at_risk   = [b for b in active if b.get("risk")=="High"]
    pipeline_val = sum(b.get("value_cad") or 0 for b in active)
    wr = f"{round(len(won)/(len(won)+len(lost))*100)}%" if (won or lost) else "N/A"

    kpi_data = [
        [pp("ACTIVE BIDS",    7, fn_sb, C_GREY_2, TA_CENTER),
         pp("PIPELINE VALUE", 7, fn_sb, C_GREY_2, TA_CENTER),
         pp("AT RISK",        7, fn_sb, C_GREY_2, TA_CENTER),
         pp("WIN RATE",       7, fn_sb, C_GREY_2, TA_CENTER)],
        [pp(str(len(active)),  16, fn_b, C_NAVY,  TA_CENTER),
         pp(f"${pipeline_val/1000:.0f}K" if pipeline_val else "—",
            16, fn_b, C_NAVY, TA_CENTER),
         pp(str(len(at_risk)), 16, fn_b,
            C_RED if at_risk else C_GREEN, TA_CENTER),
         pp(wr, 16, fn_b, C_GREEN if won else C_GREY_1, TA_CENTER)],
        [pp(f"of {len(bids)} total", 7, fn_r, C_GREY_2, TA_CENTER),
         pp("active opportunities", 7, fn_r, C_GREY_2, TA_CENTER),
         pp("immediate attention",  7, fn_r, C_GREY_2, TA_CENTER),
         pp(f"{len(won)}W / {len(lost)}L", 7, fn_r, C_GREY_2, TA_CENTER)],
    ]
    kw = CW / 4
    sc = Table(kpi_data, colWidths=[kw]*4, rowHeights=[7*mm, 11*mm, 6*mm])
    sc.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), C_GREY_4),
        ("LINEAFTER",     (0,0),(2,2),   0.5, C_GREY_3),
        ("BOX",           (0,0),(-1,-1), 0.5, C_GREY_3),
        ("LINEABOVE",     (0,0),(0,0),   3,   C_NAVY),
        ("LINEABOVE",     (1,0),(1,0),   3,   C_BLUE),
        ("LINEABOVE",     (2,0),(2,0),   3,   C_RED if at_risk else C_GREEN),
        ("LINEABOVE",     (3,0),(3,0),   3,   C_GREEN if won else C_GREY_2),
        ("TOPPADDING",    (0,0),(-1,-1), 2),
        ("BOTTOMPADDING", (0,0),(-1,-1), 2),
    ]))
    story.append(sc)
    story.append(Spacer(1, 5*mm))

    # Alerts
    if alerts:
        alert_rows = [[pp(f"⚠  {a}", 8, fn_r, HexColor("#C00000"))] for a in alerts]
        alert_tbl  = Table(alert_rows, colWidths=[CW])
        alert_tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0,0),(-1,-1), HexColor("#FFF0F0")),
            ("LINEBEFORE",    (0,0),(-1,-1), 3, C_RED),
            ("BOX",           (0,0),(-1,-1), 0.5, HexColor("#F5CCCC")),
            ("TOPPADDING",    (0,0),(-1,-1), 2*mm),
            ("BOTTOMPADDING", (0,0),(-1,-1), 2*mm),
            ("LEFTPADDING",   (0,0),(-1,-1), 3*mm),
        ]))
        story.append(alert_tbl)
        story.append(Spacer(1, 4*mm))

    # Active bids table
    story.append(pp("Active Bid Pipeline", 11, fn_b, C_NAVY))
    story.append(Spacer(1, 2*mm))

    RISK_COL_PDF = {"High": C_RED, "Medium": C_AMBER, "Low": C_GREEN}

    col_w = [r*mm for r in [55, 22, 18, 18, 22, 20]]
    scale = CW / sum(col_w)
    col_w = [w*scale for w in col_w]
    hdr   = ["Client / Opportunity","Stage","Deadline","Readiness",
             "Mandatory","Risk"]
    hdr_row = [pp(h, 7.5, fn_sb, C_WHITE) for h in hdr]

    rows = [hdr_row]
    active_sorted = sorted(
        [b for b in bids if b["stage"] not in ("Won","Lost","No Bid")],
        key=lambda x: (x.get("days") or 999))

    for i, b in enumerate(active_sorted):
        d     = b.get("days")
        r     = b.get("readiness", 0)
        rc    = RISK_COL_PDF.get(b.get("risk","Low"), C_GREEN)
        stage_text = b["stage"]
        deadline_text = (f"{d}d" if d is not None and d >= 0 else
                         "OVERDUE" if d is not None else "—")

        rows.append([
            pp(f"{b['client']}\n{b['title'][:40]}", 8, fn_r, C_BLACK),
            pp(stage_text, 8, fn_r, C_GREY_1),
            pp(deadline_text, 8,
               fn_sb if (d is not None and d <= 7) else fn_r,
               C_RED if (d is not None and d <= 7) else C_GREY_1),
            pp(f"{r}%", 8,
               fn_sb,
               C_RED if r<50 else C_AMBER if r<80 else C_GREEN),
            pp(f"{b.get('m_done',0)}/{b.get('m_total',0)}", 8,
               fn_r,
               C_RED if b.get('m_done',0)<b.get('m_total',0) else C_GREEN),
            pp(b.get("risk","—"), 8, fn_sb, rc),
        ])

    bid_tbl = Table(rows, colWidths=col_w, repeatRows=1)
    ts = TableStyle([
        ("BACKGROUND",    (0,0),(-1,0),  C_NAVY),
        ("TOPPADDING",    (0,0),(-1,0),  2.5*mm),
        ("BOTTOMPADDING", (0,0),(-1,0),  2.5*mm),
        ("LINEBELOW",     (0,0),(-1,0),  1.5, C_BLUE),
        ("VALIGN",        (0,0),(-1,-1), "TOP"),
        ("TOPPADDING",    (0,1),(-1,-1), 3),
        ("BOTTOMPADDING", (0,1),(-1,-1), 3),
        ("LEFTPADDING",   (0,0),(-1,-1), 3),
        ("RIGHTPADDING",  (0,0),(-1,-1), 3),
        ("LINEBELOW",     (0,1),(-1,-1), 0.4, C_GREY_3),
        ("BOX",           (0,0),(-1,-1), 0.5, C_GREY_3),
    ])
    for i in range(1, len(rows)):
        ts.add("BACKGROUND", (0,i),(-1,i), C_WHITE if i%2==1 else C_BLUE_L)
    bid_tbl.setStyle(ts)
    story.append(bid_tbl)

    # Coach roster summary
    if coaches:
        story.append(Spacer(1, 6*mm))
        story.append(pp("Coach Roster", 11, fn_b, C_NAVY))
        story.append(Spacer(1, 2*mm))
        avail   = len([c for c in coaches if c.get("availability")=="Available"])
        partial = len([c for c in coaches if c.get("availability")=="Partially Available"])
        unavail = len([c for c in coaches if c.get("availability")=="Unavailable"])
        coach_summary = Table([[
            pp(f"Total: {len(coaches)}", 8, fn_sb, C_BLACK),
            pp(f"Available: {avail}", 8, fn_sb, C_GREEN),
            pp(f"Partial: {partial}", 8, fn_sb, C_AMBER),
            pp(f"Unavailable: {unavail}", 8, fn_sb, C_RED),
        ]], colWidths=[CW/4]*4)
        coach_summary.setStyle(TableStyle([
            ("BACKGROUND",  (0,0),(-1,-1), C_GREY_4),
            ("BOX",         (0,0),(-1,-1), 0.5, C_GREY_3),
            ("LINEAFTER",   (0,0),(2,0),   0.5, C_GREY_3),
            ("TOPPADDING",  (0,0),(-1,-1), 3*mm),
            ("BOTTOMPADDING",(0,0),(-1,-1),3*mm),
            ("LEFTPADDING", (0,0),(-1,-1), 3*mm),
        ]))
        story.append(coach_summary)

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
