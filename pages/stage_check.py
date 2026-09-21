"""
Stage 4: CHECK — Bid Review & Compliance Audit
Consolidated quality gate answering:
1. Are we compliant?
2. Are we competitive?
3. Are we complete?
4. What could cause disqualification?
5. What is still weak or missing?
"""
import io
import json
from datetime import date
import streamlit as st
import auth_session
import tenancy
import proposal_intelligence
from analyst import missing_evidence, compliance_review
from extractor import build_alignment_submission_package, summarize_submission_package, build_report_manifest
from config import api_key_configured
from components.ui import (qual_badge, evidence_badge, status_badge, readiness_bar,
                           metric_card, procurement_staleness_banner, QUAL_STATUSES)
from requirement_semantics import select_qualification_requirements
from pdf_alignment import generate_alignment_audit_pdf


def _current_access_token_and_org():
    session = auth_session.current_session()
    ctx = auth_session.current_auth_context()
    return session["access_token"], ctx.organization_id


def _sanitize_filename_component(text: str) -> str:
    text = (text or "bid").strip()
    cleaned = "".join(c if c.isalnum() or c in "-._" else "_" for c in text)
    return cleaned.strip("_") or "bid"


# ── ALIGNMENT SESSION-STATE KEYS (bid-scoped) ───────────────────────────────
# Every Alignment Analyzer key below is namespaced by bid_id -- a
# Submission Package, its manifest, primary-file selection, audit
# result, and report metadata for Bid A must never leak into Bid B's
# CHECK page. The full set of prefixes here is also what app.py's
# logout handler clears (see _clear_all_user_scoped_state()).
_ALIGN_STATE_PREFIXES = ("align_package_", "align_result_", "align_pi_run_")


def _align_package_key(bid_id) -> str:
    return f"align_package_{bid_id}"


def _align_result_key(bid_id) -> str:
    return f"align_result_{bid_id}"


def _align_result_snapshot_key(bid_id) -> str:
    return f"align_result_package_snapshot_{bid_id}"


def _align_pi_run_key(bid_id) -> str:
    """Holds the PERSISTED Proposal Intelligence run dict (migrations/
    015_proposal_intelligence.sql) once one has been created or
    discovered on reload -- distinct from _align_result_key's legacy-
    shaped rendering dict, so the staleness indicator always has the
    real run row (procurement_revision/package_snapshot_id/
    analysis_version) to compare against, not just its reconstruction."""
    return f"align_pi_run_{bid_id}"


_MANIFEST_STATUS_LABEL = {
    "extracted": ("Included" , "#27AE60"),
    "failed": ("Failed", "#C0392B"),
    "unsupported": ("Unsupported", "#E67E22"),
    "duplicate": ("Duplicate", "#6E6C66"),
    "rejected": ("Rejected", "#C0392B"),
}


def _render_submission_package_manifest(package: dict, bid_id, editable: bool) -> None:
    """Renders the Submission Package Manifest (instruction 9): summary
    metrics plus a per-file row with type, primary indicator, include/
    exclude control, extraction status, and character count. Mutates
    `included`/`role` directly on the package dict's file records (the
    caller re-stores the same dict object back into session_state) --
    editable=True is used for the live pre-audit manifest; editable=False
    renders a frozen snapshot without checkboxes."""
    files = package.get("files", [])
    summary = summarize_submission_package(files)

    st.markdown("##### Submission Package Manifest")
    m = st.columns(7)
    m[0].markdown(metric_card("Supplied", summary["files_supplied"]), unsafe_allow_html=True)
    m[1].markdown(metric_card("Included", summary["files_included"]), unsafe_allow_html=True)
    m[2].markdown(metric_card("Excluded", summary["files_excluded"]), unsafe_allow_html=True)
    m[3].markdown(metric_card("Extracted", summary["files_extracted"]), unsafe_allow_html=True)
    m[4].markdown(metric_card("Unsupported", summary["files_unsupported"], color="#E67E22" if summary["files_unsupported"] else None), unsafe_allow_html=True)
    m[5].markdown(metric_card("Failed", summary["files_failed"], color="#C0392B" if summary["files_failed"] else None), unsafe_allow_html=True)
    m[6].markdown(metric_card("Duplicates", summary["files_duplicate"]), unsafe_allow_html=True)

    if not files:
        st.caption("No files supplied yet.")
        return

    hdr = st.columns([2.4, 0.7, 1.1, 1, 1.1, 2.2])
    for col_w, label in zip(hdr, ["File / Package Path", "Type", "Status", "Include", "Content", "Notes"]):
        col_w.markdown(f'<span style="font-size:.68rem;color:#6E6C66;text-transform:uppercase;font-weight:600">{label}</span>', unsafe_allow_html=True)
    st.markdown('<hr class="section-divider" style="margin:.2rem 0">', unsafe_allow_html=True)

    for f in files:
        row = st.columns([2.4, 0.7, 1.1, 1, 1.1, 2.2])
        primary_tag = " ⭐ Primary" if f.get("role") == "primary" else ""
        row[0].markdown(
            f'<span style="font-size:.8rem;color:#EDEAE3">{f["filename"]}{primary_tag}</span><br>'
            f'<span style="font-size:.68rem;color:#6E6C66">{f["package_path"]}</span>',
            unsafe_allow_html=True,
        )
        row[1].markdown(f'<span style="font-size:.76rem;color:#A9A69D">{f["file_type"].upper()}</span>', unsafe_allow_html=True)
        label, colour = _MANIFEST_STATUS_LABEL.get(f["lifecycle_status"], (f["lifecycle_status"], "#A9A69D"))
        row[2].markdown(f'<span style="font-size:.76rem;color:{colour};font-weight:600">{label}</span>', unsafe_allow_html=True)

        if f["lifecycle_status"] in ("duplicate", "rejected"):
            row[3].markdown('<span style="font-size:.72rem;color:#6E6C66">Excluded</span>', unsafe_allow_html=True)
            f["included"] = False
        elif editable:
            f["included"] = row[3].checkbox("Include", value=f.get("included", True), key=f"align_inc_{bid_id}_{f['file_id']}", label_visibility="collapsed")
        else:
            row[3].markdown('<span style="font-size:.72rem">Included</span>' if f.get("included") else '<span style="font-size:.72rem;color:#6E6C66">Excluded</span>', unsafe_allow_html=True)

        row[4].markdown(f'<span style="font-size:.76rem;color:#A9A69D">{f["char_count"]:,} chars</span>' if f["char_count"] else '<span style="font-size:.76rem;color:#6E6C66">—</span>', unsafe_allow_html=True)

        note = f.get("unusable_reason") or ""
        row[5].markdown(f'<span style="font-size:.72rem;color:#C0392B">{note}</span>' if note else "", unsafe_allow_html=True)

    if editable:
        eligible = [f for f in files if f["lifecycle_status"] == "extracted" and f.get("included")]
        if len(eligible) == 1:
            for f in files:
                f["role"] = "primary" if f is eligible[0] else None
            st.caption(f"⭐ Primary Technical Proposal (auto-selected, only included file): **{eligible[0]['filename']}**")
        elif len(eligible) > 1:
            id_to_file = {f["file_id"]: f for f in eligible}
            options = ["(none selected)"] + list(id_to_file.keys())
            current = next((fid for fid, f in id_to_file.items() if f.get("role") == "primary"), "(none selected)")
            choice = st.selectbox(
                "⭐ Primary Technical Proposal (affects presentation/provenance only -- every included file is still analyzed)",
                options,
                index=options.index(current) if current in options else 0,
                format_func=lambda fid: "(none selected)" if fid == "(none selected)" else f'{id_to_file[fid]["filename"]} ({id_to_file[fid]["package_path"]})',
                key=f"align_primary_{bid_id}",
            )
            for f in files:
                f["role"] = "primary" if f["file_id"] == choice else None
        else:
            for f in files:
                f["role"] = None


def _build_procurement_context(brief_row: dict, requirements: list[dict]) -> str:
    """Canonical, already-extracted procurement intelligence for the
    Proposal Alignment Analyzer -- NOT bid.notes (a short free-text
    field, not the tender corpus). Built from bid_briefs (itself derived
    from the tender documents at ingestion) plus the compliance matrix
    already loaded for this page. Raw Storage/document reads are
    explicitly out of scope for this remediation (Package 4)."""
    def _fmt(label, val):
        if not val:
            return ""
        if isinstance(val, (list, dict)):
            try:
                val = json.dumps(val)[:1500]
            except Exception:
                val = str(val)[:1500]
        else:
            val = str(val)[:1500]
        return f"{label}: {val}\n"

    parts = [
        _fmt("Opportunity Type", brief_row.get("opportunity_type")),
        _fmt("Procurement Model", brief_row.get("procurement_model")),
        _fmt("Contract Term", brief_row.get("contract_term")),
        _fmt("Executive Summary (RFP)", brief_row.get("executive_summary")),
        _fmt("Scope Categories", brief_row.get("scope_categories")),
        _fmt("Deliverables Summary", brief_row.get("deliverables_summary")),
        _fmt("Qualification Gates", brief_row.get("qualification_gates")),
        _fmt("Evaluation Breakdown", brief_row.get("evaluation_breakdown")),
        _fmt("Commercial Structure", brief_row.get("commercial_structure")),
        _fmt("Contract Risks", brief_row.get("contract_risks")),
        _fmt("Submission Requirements", brief_row.get("submission_requirements")),
        _fmt("Source Citations", brief_row.get("source_citations")),
    ]
    has_brief_content = any(parts)
    if not has_brief_content and not requirements:
        return "No canonical procurement intelligence has been extracted for this bid yet."
    mandatory_count = sum(1 for r in requirements if (r.get("category") or "").lower() == "mandatory")
    parts.append(f"Mandatory Requirements Count: {mandatory_count}\n")
    return "".join(p for p in parts if p)


def page_check(bid_id: int):
    _token, _org_id = _current_access_token_and_org()
    bid = tenancy.get_bid_authenticated(_token, bid_id)
    if not bid:
        st.error("Opportunity not found.")
        return

    reqs = tenancy.get_requirements_authenticated(_token, bid_id)
    docs = tenancy.get_documents_authenticated(_token, bid_id)
    outline = tenancy.get_outline_authenticated(_token, bid_id)
    clars = tenancy.get_clarifications_authenticated(_token, bid_id)

    st.markdown('<div style="font-size:.72rem;color:#C9A96E;text-transform:uppercase;letter-spacing:.12em;font-weight:600">STAGE 4 · CHECK</div>', unsafe_allow_html=True)
    st.markdown(f"# Bid Review & Quality Gate")
    st.markdown(f'<div style="font-size:1rem;color:#A9A69D">{bid["client"]} — {bid["title"]}</div>', unsafe_allow_html=True)
    st.markdown('<div class="gold-rule"></div>', unsafe_allow_html=True)

    procurement_state = tenancy.get_procurement_state_for_organization(bid_id, _org_id)
    banner_html = procurement_staleness_banner(
        procurement_state, context_label="The compliance matrix used on this page",
    )
    if banner_html:
        st.markdown(banner_html, unsafe_allow_html=True)

    brief_row = tenancy.get_bid_brief_authenticated(_token, bid_id) or {}
    raw_q_gates = brief_row.get("qualification_gates")
    qual_gates = []
    if isinstance(raw_q_gates, list):
        qual_gates = raw_q_gates
    elif isinstance(raw_q_gates, str):
        try:
            qual_gates = json.loads(raw_q_gates) if raw_q_gates.strip().startswith("[") else []
        except Exception:
            qual_gates = []

    # ── READINESS SCORE STRIP ─────────────────────────────────────────────────
    # A. True Supplier Qualification Gates
    qual_reqs = select_qualification_requirements(reqs, qual_gates)
    q_pass = sum(1 for r in qual_reqs if r.get("qual_status") == "PASS")
    q_fail = sum(1 for r in qual_reqs if r.get("qual_status") == "FAIL")
    q_unknown = sum(1 for r in qual_reqs if r.get("qual_status", "UNKNOWN") == "UNKNOWN")

    # B. Overall Mandatory Compliance
    mand_reqs = [r for r in reqs if r.get("category") == "Mandatory"]
    m_pass = sum(1 for r in mand_reqs if r.get("qual_status") == "PASS")
    m_unverified = sum(1 for r in mand_reqs if r.get("qual_status", "UNKNOWN") in ("UNKNOWN", "CONCERN"))

    k1, k2, k3, k4 = st.columns(4)
    k1.markdown(metric_card("Qualification Gates", f"{q_pass}/{len(qual_reqs)}", "verified PASS" if qual_reqs else "none identified"), unsafe_allow_html=True)
    k2.markdown(metric_card("Mandatory Compliance", f"{m_pass}/{len(mand_reqs)}", "verified PASS" if mand_reqs else "none"), unsafe_allow_html=True)
    k3.markdown(metric_card("Qualification FAILs", q_fail, "disqualification blocker", "#C0392B" if q_fail else "#27AE60"), unsafe_allow_html=True)
    k4.markdown(metric_card("Unverified Mandatory", m_unverified, "needs evidence before submit", "#E67E22" if m_unverified else "#27AE60"), unsafe_allow_html=True)
    st.markdown("")

    tab_alignment, tab_risk, tab_matrix, tab_clar_audit = st.tabs([
        "🔬 Proposal Alignment Analyzer",
        "🛡️ Compliance & Evidence Risk Scan",
        "📋 Full Compliance Matrix Sheet",
        "❓ Clarification & Addenda Audit"
    ])

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 1: PROPOSAL ALIGNMENT ANALYZER
    # ══════════════════════════════════════════════════════════════════════════
    with tab_alignment:
        st.markdown("### Proposal Alignment & Compliance Audit")
        st.markdown(
            '<div style="font-size:.82rem;color:#A9A69D;margin-bottom:.8rem">'
            'Upload the complete submission package — the main technical proposal plus any mandatory schedules, '
            'response forms, pricing schedules, CV/team annexes, and declarations (as individual files and/or one '
            'or more .zip archives). Claude analyzes every included file in traceable sections against the '
            'compliance matrix and the canonical procurement intelligence already extracted for this bid '
            '(qualification gates, evaluation criteria, commercial requirements) — not the physical tender '
            'documents directly. A requirement satisfied anywhere in the package counts, not only in the main '
            'proposal. Findings are classified into Proposal Submission, Negotiation, Execution, or Delivery stages.'
            '</div>',
            unsafe_allow_html=True
        )

        pkg_key = _align_package_key(bid_id)
        fingerprint_key = f"{pkg_key}_fingerprint"

        uploaded = st.file_uploader(
            "Upload submission package files (PDF, DOCX, XLSX, XLS, CSV, TXT, MD) and/or .zip archive(s). "
            "PPTX is unsupported in this version.",
            type=["pdf", "docx", "xlsx", "xls", "csv", "txt", "md", "zip"],
            accept_multiple_files=True,
            key="prop_align_files",
        )
        if uploaded:
            fingerprint = tuple((f.name, f.size) for f in uploaded)
            if st.session_state.get(fingerprint_key) != fingerprint:
                raw_files = [(f.name, f.read()) for f in uploaded]
                with st.spinner("Extracting submission package…"):
                    st.session_state[pkg_key] = build_alignment_submission_package(raw_files)
                st.session_state[fingerprint_key] = fingerprint

        package = st.session_state.get(pkg_key)
        if package:
            _render_submission_package_manifest(package, bid_id, editable=True)
            st.markdown("")

        if package:
            run_disabled = not any(
                f["lifecycle_status"] == "extracted" and f.get("included") for f in package["files"]
            )
        else:
            run_disabled = True

        # ── PROPOSAL INTELLIGENCE: discover a persisted run on reload ───────
        # Session state is not the durable owner of a completed audit
        # anymore (PI-1) -- if this browser session has no in-memory
        # result yet (a reload, a new tab, a different device), recover
        # the most recent USABLE (COMPLETE/INCOMPLETE) persisted Proposal
        # Intelligence run instead of forcing a re-run -- a later FAILED
        # attempt must never hide it (PI-1.1 instruction 9). Never
        # overwrites an in-memory result from a run just completed THIS
        # session. Also restores the HISTORICAL full package manifest
        # (PI-1.1 instruction 8) so the manifest view, primary-file
        # selection, and PDF export all reflect exactly what was audited,
        # not whatever the live uploader currently shows.
        if _align_result_key(bid_id) not in st.session_state:
            _token, _org_id = _current_access_token_and_org()
            try:
                latest_run = tenancy.get_latest_usable_proposal_intelligence_run_authenticated(_token, bid_id)
            except Exception:
                latest_run = None
            if latest_run:
                assessments = tenancy.get_proposal_requirement_assessments_authenticated(_token, latest_run["id"])
                findings = tenancy.get_proposal_intelligence_findings_authenticated(_token, latest_run["id"])
                st.session_state[_align_result_key(bid_id)] = proposal_intelligence.reconstruct_legacy_align_result(
                    latest_run, assessments, findings)
                st.session_state[_align_pi_run_key(bid_id)] = latest_run
                try:
                    historical_snapshot = tenancy.get_proposal_package_snapshot_authenticated(
                        _token, bid_id, latest_run["proposal_package_snapshot_id"])
                except Exception:
                    historical_snapshot = None
                if historical_snapshot:
                    st.session_state[_align_result_snapshot_key(bid_id)] = \
                        proposal_intelligence.restore_package_manifest_dict(historical_snapshot)

        pi_run = st.session_state.get(_align_pi_run_key(bid_id))
        if pi_run:
            # PROPOSAL_CHANGED can only be detected when a package is
            # actually present in THIS session -- compare its full-
            # manifest digest against the persisted run's own snapshot
            # digest (re-derived from the manifest already cached under
            # _align_result_snapshot_key, never a fresh DB write just to
            # check staleness). When digests match, pass the run's own
            # real snapshot id through so staleness_reasons reports
            # "current"; when they differ, pass a value guaranteed unequal
            # to it. Never fabricate PROPOSAL_CHANGED when no package is
            # uploaded (instruction 10): the persisted run may still be
            # accurately CURRENT relative to its own historical package,
            # so the badge below only ever claims what is actually known.
            current_package_snapshot_id = pi_run.get("proposal_package_snapshot_id")
            if package:
                current_digest = proposal_intelligence.compute_package_digest(package["files"])
                run_snapshot = st.session_state.get(_align_result_snapshot_key(bid_id))
                run_snapshot_digest = proposal_intelligence.compute_package_digest(
                    (run_snapshot or {}).get("files") or [])
                if current_digest != run_snapshot_digest:
                    current_package_snapshot_id = None  # guaranteed != a real snapshot id
            stale_reasons = proposal_intelligence.staleness_reasons(
                pi_run, current_procurement_revision=procurement_state.get("procurement_revision"),
                current_package_snapshot_id=current_package_snapshot_id)
            proc_stale = proposal_intelligence.STALE_PROCUREMENT_CHANGED in stale_reasons
            proposal_stale = package is not None and proposal_intelligence.STALE_PROPOSAL_CHANGED in stale_reasons
            if proc_stale or proposal_stale:
                reasons_label = " & ".join(
                    r for r, is_stale in (("procurement basis", proc_stale), ("proposal package", proposal_stale))
                    if is_stale)
                badge_color, badge_text = "#E67E22", f"⚠️ {reasons_label} changed since this audit"
            else:
                badge_color = "#6E6C66"
                badge_text = ("✅ Current relative to its own historical package"
                              if not package else "✅ Current procurement basis and proposal package")
            st.markdown(
                f'<div style="font-size:.74rem;color:{badge_color};margin-bottom:.4rem">'
                f'Proposal Intelligence run #{pi_run["id"]} · {pi_run.get("status")} · {badge_text}</div>',
                unsafe_allow_html=True)

        if st.button("🚀 Run Alignment Audit", use_container_width=True, type="primary", key="btn_run_align", disabled=run_disabled):
            if not (api_key_configured() or st.session_state.get("anthropic_api_key")):
                st.error("Configure Anthropic API key.")
            else:
                included_files = [
                    f for f in package["files"]
                    if f.get("included") and f["lifecycle_status"] in ("extracted", "failed", "unsupported")
                ]
                package_files_for_analysis = [
                    {
                        "file_id": f["file_id"], "filename": f["filename"], "package_path": f["package_path"],
                        "file_type": f["file_type"], "text": f["text"], "analyzable": f["analyzable"],
                        "unusable_reason": f["unusable_reason"], "extraction_meta": f["extraction_meta"],
                        # Analysis-input identity fields (not read by the
                        # analyzer itself) -- proposal_intelligence.py's
                        # compute_package_digest() needs these to establish
                        # the exact proposal package snapshot this run is
                        # tied to.
                        "content_hash": f["content_hash"], "included": f.get("included"), "role": f.get("role"),
                    }
                    for f in included_files
                ]
                with st.spinner(f"Analyzing {len(included_files)} included file(s) in traceable sections against procurement intelligence… 30–90s"):
                    try:
                        procurement_context = _build_procurement_context(brief_row, reqs)
                        _token, _org_id = _current_access_token_and_org()
                        session = auth_session.current_session()
                        # Authorization boundary + persistence (PI-1) in
                        # front of the EXISTING, unchanged Proposal
                        # Alignment Analyzer -- see
                        # tenancy.run_proposal_intelligence_for_organization.
                        # Establishes/reuses the proposal package snapshot
                        # identity, runs analyze_proposal_alignment_package
                        # exactly as before, and persists the durable
                        # Proposal Intelligence run/assessments/findings.
                        pi_result = tenancy.run_proposal_intelligence_for_organization(
                            bid_id, _org_id, package_files=package_files_for_analysis,
                            requirements=reqs, rfp_text=procurement_context, bid_info=bid,
                            full_package_manifest=package["files"],
                            user_id=session.get("user_id"),
                        )
                        align_res = pi_result["alignment_result"]
                        # Stamped at analysis time (migration 010) so the
                        # exported PDF can later compare "what revision was
                        # this audit run against" to whatever the bid's
                        # procurement_revision has become by download time,
                        # even though `reqs` itself is always the live/
                        # current compliance matrix by construction.
                        align_res["based_on_procurement_revision"] = procurement_state.get("procurement_revision")
                        st.session_state[_align_result_key(bid_id)] = align_res
                        st.session_state[_align_pi_run_key(bid_id)] = pi_result["run"]
                        # Frozen, SLIM snapshot of the package manifest AS IT
                        # WAS AUDITED -- the manifest shown in the exported
                        # PDF (and any re-download without re-running) must
                        # reflect what was actually analyzed, not whatever
                        # the live, still-editable uploader/checkboxes show
                        # afterward. Deliberately carries only report-safe
                        # manifest fields (build_report_manifest), never the
                        # raw extracted text/extraction_meta payloads the
                        # live in-session package holds for analysis.
                        st.session_state[_align_result_snapshot_key(bid_id)] = {
                            "files": build_report_manifest(package["files"])
                        }
                        if align_res.get("status") == "complete":
                            st.success("Audit complete.")
                        else:
                            st.warning(align_res.get("message", "Alignment audit incomplete — no reliable score available"))
                        st.rerun()
                    except tenancy.AccessDeniedError as e:
                        st.error(f"Not authorized: {e}")
                    except Exception as e:
                        st.error(f"Audit failed: {e}")

        # Display alignment results
        align_data = st.session_state.get(_align_result_key(bid_id))
        result_package_snapshot = st.session_state.get(_align_result_snapshot_key(bid_id))
        if align_data:
            st.markdown('<hr class="section-divider">', unsafe_allow_html=True)

            # Export control -- near the top, always available once a
            # result exists (including an incomplete one). Deterministic:
            # renders exactly the already-computed align_data, no new LLM
            # call, no re-analysis, no Storage write -- generated fresh
            # in memory on every render so it can never drift from what's
            # on screen, but nothing about the underlying audit reruns.
            report_client = _sanitize_filename_component(bid.get("client"))
            report_date = date.today().isoformat()
            primary_filename = next(
                (f["filename"] for f in (result_package_snapshot or {}).get("files", []) if f.get("role") == "primary"),
                "",
            )
            st.download_button(
                "📄 Download Alignment Audit Report",
                data=generate_alignment_audit_pdf(
                    bid, align_data,
                    proposal_filename=primary_filename,
                    package_manifest=(result_package_snapshot or {}).get("files", []),
                ),
                file_name=f"Alignment_Audit_{report_client}_{report_date}.pdf",
                mime="application/pdf",
                key="btn_download_alignment_pdf",
            )
            st.markdown("")

            if result_package_snapshot:
                with st.expander("Submission Package Manifest (as audited)", expanded=False):
                    _render_submission_package_manifest(result_package_snapshot, bid_id, editable=False)

            is_complete = align_data.get("status") == "complete"
            cov = align_data.get("coverage_metadata") or {}
            mandatory_failures = align_data.get("mandatory_failures", [])
            req_coverage = align_data.get("requirement_coverage", [])
            findings = align_data.get("findings", [])
            unresolved_items = align_data.get("unresolved_items") or []
            priority_actions = align_data.get("priority_actions") or []
            partial_summary = align_data.get("partial_summary")
            assessed_count = sum(1 for r in req_coverage if r.get("coverage") != "Cannot Assess")

            if not is_complete:
                st.markdown(
                    f'<div class="warn-box" style="border-left:4px solid #C0392B">'
                    f'⛔ <strong>Alignment audit incomplete — no reliable score available</strong>'
                    f'<div style="font-size:.8rem;color:#A9A69D;margin-top:.4rem">{align_data.get("reason","")}</div>'
                    f'</div>',
                    unsafe_allow_html=True
                )
                skipped_files = cov.get("skipped_files") or []
                if skipped_files:
                    skipped_names = ", ".join(f["filename"] for f in skipped_files)
                    st.markdown(
                        f'<div style="font-size:.78rem;color:#C0392B;font-weight:600;margin-top:.4rem">'
                        f'⚠️ Not fully analyzed (package ceiling): {skipped_names}</div>',
                        unsafe_allow_html=True
                    )
                if req_coverage or findings:
                    st.markdown(
                        '<div style="font-size:.74rem;color:#6E6C66;margin-top:.3rem">'
                        'Findings and requirement coverage below reflect only the sections that were '
                        'successfully analyzed — treat as a partial sample, not a complete scored audit.</div>',
                        unsafe_allow_html=True
                    )

                # ── DETERMINISTIC PARTIAL AUDIT SUMMARY ─────────────────────────
                # Purely structured -- zero LLM calls. Distinguishes CONFIRMED
                # gaps from genuine UNKNOWNS rather than blending the two.
                if partial_summary:
                    ps = partial_summary
                    st.markdown(
                        f'<div style="background:#1A1500;border:1px solid #3A2E00;border-left:4px solid #E67E22;'
                        f'border-radius:0 4px 4px 0;padding:.8rem 1rem;margin:.6rem 0">'
                        f'<strong style="color:#E67E22">{ps.get("headline","")}</strong>'
                        f'<div style="font-size:.8rem;color:#EDEAE3;margin-top:.4rem">'
                        f'📊 Coverage: <strong>{ps.get("coverage_percentage",0)}%</strong> &nbsp;·&nbsp; '
                        f'Sections analyzed: <strong>{ps.get("sections_analyzed","")}</strong> &nbsp;·&nbsp; '
                        f'Failed: <strong>{ps.get("sections_failed",0)}</strong> &nbsp;·&nbsp; '
                        f'Ceiling-skipped: <strong>{ps.get("sections_ceiling_skipped",0)}</strong>'
                        f'</div>'
                        f'<div style="font-size:.8rem;color:#EDEAE3;margin-top:.3rem">'
                        f'✅ Fully Addressed: <strong>{ps.get("requirements_fully_addressed",0)}</strong> &nbsp;·&nbsp; '
                        f'🟠 Partially Addressed: <strong>{ps.get("requirements_partially_addressed",0)}</strong> &nbsp;·&nbsp; '
                        f'❓ Cannot Assess: <strong>{ps.get("requirements_cannot_assess",0)}</strong>'
                        f'</div>'
                        f'</div>',
                        unsafe_allow_html=True
                    )

                # ── FAILED / SKIPPED SECTION DIAGNOSTICS ────────────────────────
                # Safe categories only -- filename, section label, and a
                # closed-vocabulary reason category. Never prompts, proposal
                # text, or raw exception bodies. Distinguishes analysis-
                # engine failures from package-ceiling budget limits.
                diagnostics = cov.get("failed_chunk_diagnostics") or []
                if diagnostics:
                    with st.expander(f"Sections Not Analyzed ({len(diagnostics)})", expanded=False):
                        for d in diagnostics:
                            is_ceiling = d.get("category") == "beyond_analysis_ceiling"
                            label = "Package ceiling" if is_ceiling else "Analysis engine"
                            col = "#6E6C66" if is_ceiling else "#C0392B"
                            st.markdown(
                                f'<div style="font-size:.76rem;color:#A9A69D;margin:.2rem 0">'
                                f'<span style="color:{col};font-weight:600">[{label}]</span> '
                                f'{d.get("filename") or "—"} — {d.get("section","")} '
                                f'<span style="color:#6E6C66">({d.get("category","")})</span></div>',
                                unsafe_allow_html=True
                            )

            if is_complete:
                # ── A. ALIGNMENT SCORE & CONFIDENCE ─────────────────────────────
                o_score = align_data.get("overall_score")
                score_display = f"{o_score:.0f}/100" if o_score is not None else "N/A"
                rec = align_data.get("recommendation", "REVISE BEFORE SUBMITTING")
                rec_col = (
                    "#27AE60" if "SUBMIT" in rec
                    else "#E67E22" if "REVISE" in rec
                    else "#2980B9" if "NO EVALUATIVE CRITERIA" in rec  # informational, not an alarm
                    else "#C0392B"
                )
                basis_label = align_data.get("score_basis") or ""

                c_sc1, c_sc2 = st.columns([1, 3])
                c_sc1.markdown(
                    f'<div style="text-align:center;background:#111118;border:2px solid {rec_col};border-radius:6px;padding:1rem">'
                    f'<div style="font-size:.7rem;color:#A9A69D;text-transform:uppercase">Alignment Score</div>'
                    f'<div style="font-size:2.2rem;font-weight:700;color:{rec_col}">{score_display}</div>'
                    f'<div style="font-size:.8rem;color:#EDEAE3;font-weight:600;margin-top:.3rem">{rec}</div>'
                    f'<div style="font-size:.68rem;color:#6E6C66;margin-top:.3rem">{basis_label}</div>'
                    f'</div>',
                    unsafe_allow_html=True
                )
                with c_sc2:
                    st.markdown(f"**Score Rationale:** {align_data.get('score_rationale','')}")
                    st.markdown(
                        f'<div style="font-size:.78rem;color:#A9A69D;margin-top:.4rem">'
                        f'📊 Proposal coverage: <strong>{cov.get("percentage_covered",0)}%</strong> '
                        f'({cov.get("chars_processed",0):,}/{cov.get("chars_total",0):,} characters, '
                        f'{cov.get("successful_chunks",0)}/{cov.get("chunk_count",0)} sections analyzed'
                        f'{", " + str(cov.get("failed_or_skipped_chunks",0)) + " skipped" if cov.get("failed_or_skipped_chunks") else ""})'
                        f'<br>✅ Requirements assessed: <strong>{assessed_count}/{len(req_coverage)}</strong>'
                        f'</div>',
                        unsafe_allow_html=True
                    )

                st.markdown("")

                # ── B. EXECUTIVE SUMMARY ────────────────────────────────────────
                st.markdown("#### Executive Summary")
                st.markdown(align_data.get("executive_summary") or "_Not available._")

            # ── PRIORITY ACTIONS BEFORE SUBMISSION ──────────────────────────────
            # Deterministic, bounded (max 10): established mandatory/
            # qualification failures first, then Critical/High/Medium
            # Proposal-Submission-stage findings. Never negotiation/
            # execution/contractual-obligation items or Cannot-Assess
            # unresolved items -- those aren't actionable before submission.
            if priority_actions:
                st.markdown(f"#### 🎯 Priority Actions Before Submission ({len(priority_actions)})")
                for i, pa in enumerate(priority_actions, 1):
                    sev = pa.get("severity", "Medium")
                    sev_col = "#C0392B" if sev == "Critical" else "#E67E22" if sev == "High" else "#2980B9"
                    rec = pa.get("recommendation", "")
                    st.markdown(
                        f'<div style="background:#111118;border:1px solid #292832;border-left:3px solid {sev_col};'
                        f'border-radius:0 4px 4px 0;padding:.6rem 1rem;margin:.3rem 0">'
                        f'<span style="color:{sev_col};font-weight:700;font-size:.72rem">#{i} · [{sev.upper()}]</span> '
                        f'<span style="color:#C9A96E;font-size:.72rem">Req: {pa.get("req_id") or "—"}</span> '
                        f'<strong>{pa.get("title","")}</strong>'
                        f'<div style="font-size:.8rem;color:#EDEAE3;margin-top:.2rem">{pa.get("detail","")}</div>'
                        + (f'<div style="font-size:.76rem;color:#27AE60;margin-top:.2rem">💡 {rec}</div>' if rec else "")
                        + f'</div>',
                        unsafe_allow_html=True
                    )
                st.markdown("")

            # ── C. MANDATORY / DISQUALIFICATION RISKS ─────────────────────────────
            # Renders regardless of status -- but mandatory_failures is only ever
            # non-empty on a complete, coverage-complete audit (Cannot Assess
            # never becomes a mandatory failure), so this is naturally empty for
            # an incomplete result.
            if mandatory_failures:
                st.markdown("#### ⛔ Mandatory / Disqualification Risks")
                for mf in mandatory_failures:
                    st.markdown(
                        f'<div style="background:#1A0000;border:1px solid #3A0000;border-left:4px solid #C0392B;'
                        f'border-radius:0 4px 4px 0;padding:.6rem 1rem;margin:.3rem 0">'
                        f'<span style="color:#C0392B;font-weight:700;font-size:.78rem">[{mf.get("req_id","")}] MANDATORY — NOT ADDRESSED</span>'
                        f'<div style="font-size:.8rem;color:#EDEAE3;margin-top:.2rem">{mf.get("description","")}</div>'
                        f'<div style="font-size:.76rem;color:#E57373;margin-top:.2rem">{mf.get("reason","")}</div>'
                        f'</div>',
                        unsafe_allow_html=True
                    )

            # ── D. AUDIT FINDINGS ────────────────────────────────────────────────
            # Renamed from "Critical Findings" -- this list already contains
            # Critical, High, Medium, AND Low items, sorted in that order.
            # Positive findings from successfully-analyzed sections are shown
            # even on an incomplete-coverage result (instruction 2: preserve
            # established positive findings, just don't present them as a
            # complete scored audit). Reconciled against package-wide
            # coverage and deduplicated -- see analyst._reconcile_findings_
            # with_package_evidence()/_deduplicate_findings().
            if findings:
                sev_counts = {"Critical": 0, "High": 0, "Medium": 0, "Low": 0}
                for f in findings:
                    sev_counts[f.get("severity", "Medium")] = sev_counts.get(f.get("severity", "Medium"), 0) + 1
                st.markdown(f"#### Audit Findings ({len(findings)} items)")
                st.markdown(
                    f'<div style="font-size:.78rem;color:#A9A69D;margin-bottom:.5rem">'
                    f'<span style="color:#C0392B;font-weight:600">Critical: {sev_counts["Critical"]}</span> &nbsp;·&nbsp; '
                    f'<span style="color:#E67E22;font-weight:600">High: {sev_counts["High"]}</span> &nbsp;·&nbsp; '
                    f'<span style="color:#2980B9;font-weight:600">Medium: {sev_counts["Medium"]}</span> &nbsp;·&nbsp; '
                    f'<span style="color:#6E6C66;font-weight:600">Low: {sev_counts["Low"]}</span>'
                    f'</div>',
                    unsafe_allow_html=True
                )
                for f in findings:
                    sev = f.get("severity", "Medium")
                    stage = f.get("stage", "Proposal Submission")
                    sev_col = "#C0392B" if sev == "Critical" else "#E67E22" if sev == "High" else "#2980B9"
                    st.markdown(
                        f'<div style="background:#111118;border:1px solid #292832;border-left:3px solid {sev_col};'
                        f'border-radius:0 4px 4px 0;padding:.6rem 1rem;margin:.35rem 0">'
                        f'<span style="color:{sev_col};font-weight:700;font-size:.72rem">[{sev.upper()}]</span> '
                        f'<span style="color:#C9A96E;font-size:.72rem">Req: {f.get("req_id") or "—"} · Stage: {stage}</span> '
                        f'<strong>{f.get("title","")}</strong>'
                        f'<div style="font-size:.8rem;color:#EDEAE3;margin-top:.2rem">{f.get("issue","")}</div>'
                        f'<div style="font-size:.74rem;color:#6E6C66;margin-top:.2rem">📍 {f.get("proposal_location","")}</div>'
                        f'<div style="font-size:.76rem;color:#27AE60;margin-top:.2rem">💡 {f.get("recommendation","")} '
                        f'<span style="color:#6E6C66">(Effort: {f.get("effort","")})</span></div>'
                        f'</div>',
                        unsafe_allow_html=True
                    )

            # ── NEEDS VERIFICATION / CANNOT ASSESS ──────────────────────────────
            # Deliberately separate from Audit Findings -- these are NOT
            # established compliance defects, only requirements the package
            # coverage couldn't confirm or deny.
            if unresolved_items:
                st.markdown(f"#### 🔍 Needs Verification / Cannot Assess ({len(unresolved_items)})")
                for u in unresolved_items:
                    st.markdown(
                        f'<div style="background:#111118;border:1px solid #292832;border-left:3px solid #6E6C66;'
                        f'border-radius:0 4px 4px 0;padding:.6rem 1rem;margin:.3rem 0">'
                        f'<span style="color:#A9A69D;font-weight:700;font-size:.72rem">[{u.get("req_id","")}] {u.get("category","")}</span>'
                        f'<div style="font-size:.8rem;color:#EDEAE3;margin-top:.2rem">{u.get("reason","")}</div>'
                        f'</div>',
                        unsafe_allow_html=True
                    )

            # ── E. REQUIREMENT COVERAGE ─────────────────────────────────────────
            if req_coverage:
                st.markdown(f"#### Requirement Coverage ({len(req_coverage)} requirements)")
                cov_col = {
                    "Fully Addressed": "#27AE60", "Partially Addressed": "#E67E22",
                    "Not Addressed": "#C0392B", "Cannot Assess": "#6E6C66",
                }
                hdr = st.columns([1, 1, 1.2, 1, 2, 2.3])
                for col_w, label in zip(hdr, ["Requirement", "Category", "Coverage", "Confidence", "Evidence / Location", "Gap / Action"]):
                    col_w.markdown(f'<span style="font-size:.7rem;color:#6E6C66;text-transform:uppercase;font-weight:600">{label}</span>', unsafe_allow_html=True)
                st.markdown('<hr class="section-divider" style="margin:.2rem 0">', unsafe_allow_html=True)
                for r in req_coverage:
                    cc = cov_col.get(r.get("coverage", ""), "#6E6C66")
                    row = st.columns([1, 1, 1.2, 1, 2, 2.3])
                    row[0].markdown(f'<span style="font-size:.8rem;color:#C9A96E">{r.get("req_id","")}</span>', unsafe_allow_html=True)
                    row[1].markdown(f'<span style="font-size:.78rem;color:#A9A69D">{r.get("category","")}</span>', unsafe_allow_html=True)
                    row[2].markdown(f'<span style="color:{cc};font-size:.78rem;font-weight:600">{r.get("coverage","")}</span>', unsafe_allow_html=True)
                    row[3].markdown(f'<span style="font-size:.76rem;color:#A9A69D">{r.get("confidence","")}</span>', unsafe_allow_html=True)
                    row[4].markdown(f'<span style="font-size:.76rem">{r.get("evidence_location") or "—"}</span>', unsafe_allow_html=True)
                    row[5].markdown(f'<span style="font-size:.76rem;color:#A9A69D">{r.get("notes","")}</span>', unsafe_allow_html=True)
                    st.markdown('<hr class="section-divider" style="margin:.15rem 0">', unsafe_allow_html=True)

            # ── PROPOSAL INTELLIGENCE (PI-2A) ───────────────────────────────────
            # A single, clearly separated surface for the richer durable
            # intelligence PI-2A adds on top of the unchanged CHECK audit
            # above -- never a redesign of CHECK, never a proposal quality
            # score. Renders from whatever is already on `align_data`
            # (either a freshly-run PI-2 result or a reload of a historical
            # PI-1/PI-2 run via proposal_intelligence.reconstruct_legacy_
            # align_result) -- no new model call, no re-analysis. Every
            # sub-section is hidden entirely when it has nothing to show
            # (never an empty section), and every field access is defensive
            # so a historical PI-1 run (no evidence_strength, no structured
            # refs, no observations) renders without error.
            weak_or_moderate_evidence = [
                r for r in req_coverage
                if r.get("evidence_strength") in ("WEAK", "MODERATE") and r.get("coverage") in
                ("Fully Addressed", "Partially Addressed")
            ]
            observations = align_data.get("proposal_observations") or []
            # `f.get("finding_type")` on a raw analyzer/payload finding dict
            # is the pre-existing, UNRELATED deterministic theme label
            # (e.g. "Pricing completeness") -- the PI-2A chunk-level
            # deficiency classification lives under its own key,
            # `deficiency_type`, and must never be confused with it here.
            typed_findings = [f for f in findings if f.get("deficiency_type") not in (None, "OTHER")]
            # PI-2B1 step 21/22: whole-package findings -- persisted
            # separately by proposal_intelligence.reconstruct_legacy_align_
            # result as `package_findings` (payload["scope"] == "package"),
            # never mixed into the LOCAL `typed_findings` list above even
            # though the finding_type vocabulary overlaps (CONTRADICTION/
            # INTERNAL_INCONSISTENCY/UNSUPPORTED_CLAIM). Renders purely
            # from persisted rows -- no rerun, no model call -- and a
            # historical run with none renders nothing (never an empty
            # section, step 22).
            package_findings = align_data.get("package_findings") or []
            if weak_or_moderate_evidence or observations or typed_findings or package_findings:
                st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
                st.markdown("### 🔎 Proposal Intelligence")

                if weak_or_moderate_evidence:
                    st.markdown(f"#### Evidence Quality ({len(weak_or_moderate_evidence)} requirement(s))")
                    for r in weak_or_moderate_evidence:
                        strength = r.get("evidence_strength", "")
                        s_col = "#E67E22" if strength == "MODERATE" else "#C0392B"
                        refs = r.get("proposal_source_refs") or []
                        loc = refs[0].get("filename") or refs[0].get("section") or "" if refs else r.get("evidence_location", "")
                        st.markdown(
                            f'<div style="background:#111118;border:1px solid #292832;border-left:3px solid {s_col};'
                            f'border-radius:0 4px 4px 0;padding:.5rem 1rem;margin:.25rem 0">'
                            f'<span style="color:#C9A96E;font-size:.72rem">Req: {r.get("req_id","")}</span> '
                            f'<span style="color:{s_col};font-weight:700;font-size:.72rem">[{strength}]</span> '
                            f'<span style="font-size:.78rem;color:#A9A69D">{r.get("coverage","")}</span>'
                            f'<div style="font-size:.76rem;color:#6E6C66;margin-top:.15rem">📍 {loc or "—"}</div>'
                            f'</div>',
                            unsafe_allow_html=True,
                        )

                if observations:
                    commitments = [o for o in observations if o.get("observation_type") == "DELIVERY_COMMITMENT"]
                    exposures = [o for o in observations if o.get("observation_type") == "COMMERCIAL_EXPOSURE"]
                    st.markdown(f"#### Commitments & Commercial Exposure ({len(observations)})")
                    for label, group, color in (("Delivery Commitment", commitments, "#27AE60"),
                                                ("Commercial Exposure", exposures, "#E67E22")):
                        for o in group:
                            refs = o.get("proposal_source_refs") or []
                            loc = (refs[0].get("filename") or refs[0].get("section")) if refs else o.get("proposal_location", "")
                            st.markdown(
                                f'<div style="background:#111118;border:1px solid #292832;border-left:3px solid {color};'
                                f'border-radius:0 4px 4px 0;padding:.5rem 1rem;margin:.25rem 0">'
                                f'<span style="color:{color};font-weight:700;font-size:.72rem">[{label.upper()}]</span> '
                                f'<span style="color:#C9A96E;font-size:.72rem">Req: {o.get("req_id") or "—"}</span> '
                                f'<strong style="font-size:.8rem">{o.get("title") or ""}</strong>'
                                f'<div style="font-size:.78rem;color:#EDEAE3;margin-top:.15rem">{o.get("statement") or o.get("message") or ""}</div>'
                                + (f'<div style="font-size:.74rem;color:#A9A69D;margin-top:.1rem">{o.get("implication") or o.get("explanation") or ""}</div>'
                                   if (o.get("implication") or o.get("explanation")) else "")
                                + f'<div style="font-size:.7rem;color:#6E6C66;margin-top:.15rem">📍 {loc or "—"}</div>'
                                + f'</div>',
                                unsafe_allow_html=True,
                            )

                if typed_findings:
                    st.markdown(f"#### Typed Findings ({len(typed_findings)})")
                    for f in typed_findings:
                        dtype = f.get("deficiency_type") or f.get("finding_type") or "OTHER"
                        st.markdown(
                            f'<div style="font-size:.76rem;color:#A9A69D;margin:.15rem 0">'
                            f'<span style="color:#C9A96E;font-weight:600">[{dtype}]</span> '
                            f'{f.get("title","")} <span style="color:#6E6C66">— Req: {f.get("req_id") or "—"}</span></div>',
                            unsafe_allow_html=True,
                        )

                if package_findings:
                    _pkg_severity_color = {
                        "Critical": "#C0392B", "High": "#E67E22", "Medium": "#C9A96E", "Low": "#6E6C66",
                    }
                    st.markdown(f"#### Whole-Package Consistency ({len(package_findings)})")
                    st.caption("Package-level -- reasoned across the whole proposal package, not a single section.")
                    for pf in package_findings:
                        ftype = pf.get("finding_type") or "OTHER"
                        sev = pf.get("severity") or "Medium"
                        sev_color = _pkg_severity_color.get(sev, "#C9A96E")
                        refs = pf.get("proposal_source_refs") or []
                        sources_html = "".join(
                            f'<div style="font-size:.7rem;color:#6E6C66">📍 '
                            f'{r.get("filename") or r.get("package_path") or "—"}'
                            + (f' — {r.get("section")}' if r.get("section") else "")
                            + '</div>'
                            for r in refs
                        ) or '<div style="font-size:.7rem;color:#6E6C66">📍 —</div>'
                        st.markdown(
                            f'<div style="background:#111118;border:1px solid #292832;border-left:3px solid {sev_color};'
                            f'border-radius:0 4px 4px 0;padding:.5rem 1rem;margin:.25rem 0">'
                            f'<span style="color:{sev_color};font-weight:700;font-size:.72rem">[{ftype}] {sev}</span> '
                            f'<span style="color:#C9A96E;font-size:.72rem">Req: {pf.get("req_id") or "—"}</span> '
                            f'<span style="background:#2A2836;color:#A9A69D;font-size:.62rem;padding:1px 5px;'
                            f'border-radius:3px;margin-left:.35rem">PACKAGE-LEVEL</span>'
                            f'<div style="font-weight:600;font-size:.82rem;margin-top:.2rem">{pf.get("title") or ""}</div>'
                            f'<div style="font-size:.78rem;color:#EDEAE3;margin-top:.15rem">{pf.get("explanation") or ""}</div>'
                            + (f'<div style="font-size:.74rem;color:#A9A69D;margin-top:.1rem">→ {pf.get("recommended_action")}</div>'
                               if pf.get("recommended_action") else "")
                            + sources_html
                            + '</div>',
                            unsafe_allow_html=True,
                        )

            if is_complete:
                # ── F. STRENGTHS ──────────────────────────────────────────────────
                strengths = align_data.get("strengths", [])
                if strengths:
                    st.markdown("#### Strengths")
                    st.markdown(" · ".join(f"<span style='color:#27AE60'>✓ {s}</span>" for s in strengths), unsafe_allow_html=True)

                # ── G. PRIORITIZED NEXT STEPS ─────────────────────────────────────
                next_steps = align_data.get("next_steps", [])
                if next_steps:
                    st.markdown("#### Prioritized Next Steps")
                    for step in sorted(next_steps, key=lambda x: x.get("priority", 99)):
                        st.markdown(
                            f'<div style="background:#111118;border:1px solid #292832;border-left:3px solid #C9A96E;'
                            f'border-radius:0 4px 4px 0;padding:.6rem 1rem;margin:.3rem 0">'
                            f'<span style="color:#C9A96E;font-weight:700;font-size:.8rem">#{step.get("priority","")}</span> '
                            f'<span style="font-size:.85rem;color:#EDEAE3">{step.get("action","")}</span> '
                            f'<span style="font-size:.7rem;color:#A9A69D">({step.get("when","")})</span>'
                            f'<div style="font-size:.76rem;color:#A9A69D;margin-top:.15rem">{step.get("rationale","")}</div>'
                            f'</div>',
                            unsafe_allow_html=True
                        )

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 2: MISSING EVIDENCE SCAN
    # ══════════════════════════════════════════════════════════════════════════
    with tab_risk:
        st.markdown("### Compliance & Evidence Risk Scan")
        if st.button("🔍 Scan Compliance Matrix for At-Risk Items", key="btn_scan_ev", type="primary"):
            if not (api_key_configured() or st.session_state.get("anthropic_api_key")):
                st.error("Configure Anthropic API key.")
            else:
                with st.spinner("Scanning requirement matrix…"):
                    try:
                        ev_res = missing_evidence(reqs, bid)
                        st.session_state["evidence_scan"] = ev_res
                        st.rerun()
                    except Exception as e:
                        st.error(f"Scan failed: {e}")

        ev_data = st.session_state.get("evidence_scan")
        if ev_data:
            st.markdown(f"**Risk Assessment:** {ev_data.get('summary','')}")
            crit = ev_data.get("critical", [])
            if crit:
                for c_ in crit:
                    st.markdown(
                        f'<div class="warn-box">'
                        f'⛔ <strong>[{c_.get("req_id","")}] Critical Risk:</strong> {c_.get("reason","")}'
                        f'<br><strong>Action:</strong> {c_.get("action","")} (by {c_.get("by_when","ASAP")})'
                        f'</div>',
                        unsafe_allow_html=True
                    )

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 3: FULL COMPLIANCE MATRIX SHEET
    # ══════════════════════════════════════════════════════════════════════════
    with tab_matrix:
        st.markdown("### Compliance Matrix Control Sheet")
        c_m1, c_m2 = st.columns([3, 1])
        c_m1.markdown(f"Total requirements tracked: **{len(reqs)}**")

        # PDF Export
        from pdf_export import generate_compliance_pdf
        pdf_data = generate_compliance_pdf(bid, reqs)
        c_m2.download_button("📥 Export Matrix PDF", data=pdf_data, file_name=f"compliance_matrix_{bid_id}.pdf", mime="application/pdf", use_container_width=True)

        for r in reqs:
            st.markdown(
                f'<div style="display:flex;justify-content:space-between;align-items:center;background:#111118;'
                f'border:1px solid #292832;border-radius:4px;padding:.5rem .9rem;margin:.25rem 0">'
                f'<span><strong style="color:#C9A96E">{r.get("req_id","")}</strong> [{r.get("category","")}] {r.get("description","")[:75]}…</span>'
                f'<span>{qual_badge(r.get("qual_status","UNKNOWN"))} {evidence_badge(r.get("evidence_status","MISSING"))} {status_badge(r.get("status","Not Started"))}</span>'
                f'</div>',
                unsafe_allow_html=True
            )

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 4: CLARIFICATION & ADDENDA AUDIT
    # ══════════════════════════════════════════════════════════════════════════
    with tab_clar_audit:
        st.markdown("### Clarification & Addenda Audit")
        if clars:
            answered = sum(1 for q in clars if q.get("answer"))
            st.markdown(f"Clarifications Status: **{answered}/{len(clars)} answered**")
            for q in clars:
                st.markdown(f"• **{q.get('question_id','Q')}**: {q.get('question','')} → *{q.get('answer') or 'Awaiting client response'}*")
        else:
            st.markdown('<div class="empty-state">No clarification questions submitted.</div>', unsafe_allow_html=True)

    # ── NEXT STAGE CTA ────────────────────────────────────────────────────────
    st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
    c1, c2 = st.columns([3, 1])
    c1.markdown('<div style="color:#A9A69D;font-size:.85rem;padding-top:.4rem">Checks passed? Proceed to final submission assembly and release.</div>', unsafe_allow_html=True)
    if c2.button("Proceed to SUBMIT →", use_container_width=True, type="primary"):
        st.session_state.page = "stage_submit"
        st.rerun()
