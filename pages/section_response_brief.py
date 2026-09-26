"""
pages/section_response_brief.py -- BUILD Response Brief (formerly the
PI-3C "Section Drafting Workspace", pages/section_drafting_workspace.py).

PRODUCT BOUNDARY: Bid Intelligence no longer generates proposal narrative.
This panel tells the HUMAN writer, for ONE requirement: what the evaluator
asks, what evidence exists and how trustworthy it is, what is still
missing, contradictions/caveats, what needs SME/human confirmation, and
which response constraints apply. It never writes the response.

Rendering calls ONLY tenancy.get_section_draft_status_for_organization
(read-only: never calls a model, never calls Organizational Memory
retrieval, never writes). There is no generate/refine/regenerate action.
Historical AI drafts persisted before the decommission (section_drafts,
migrations 018/019) are shown read-only in a collapsed, explicitly-labelled
"retired capability" expander so lineage is never hidden or destroyed.
"""
import streamlit as st

import auth_session
import tenancy


_TRUST_LABELS = {
    "APPROVED_FIRM_KNOWLEDGE": ("✅ Approved Firm Knowledge", "#27AE60"),
    "SOURCE_MEMORY": ("📄 Source Material (unapproved)", "#C9A96E"),
}

_RELATIONSHIP_LABELS = {
    "DIRECT_SUPPORT": "Direct support",
    "PARTIAL_SUPPORT": "Partial support",
    "CONTEXT": "Context only",
    "CONTRADICTION": "⚠ Contradiction",
}

_GAP_LABELS = {
    "MISSING": ("🔴 Missing", "#C0392B"),
    "PARTIAL": ("🟠 Partial", "#E67E22"),
    "WEAK": ("🟠 Weak", "#E67E22"),
    "CONFLICTED": ("🔴 Conflicted", "#C0392B"),
    "SUFFICIENT": ("🟢 Sufficient", "#27AE60"),
}

_CLAIM_TYPE_LABELS = {
    "VERIFIED_FACT": "Verified fact",
    "ORGANIZATIONAL_KNOWLEDGE": "Organizational knowledge",
    "PROPOSED_APPROACH": "Proposed approach",
    "UNSUPPORTED_GAP": "Unsupported gap",
}

_SUPPORT_STATUS_LABELS = {
    "SUPPORTED": ("Supported", "#27AE60"),
    "PARTIALLY_SUPPORTED": ("Partially supported", "#E67E22"),
    "UNSUPPORTED": ("Unsupported", "#C0392B"),
    "COMMITMENT": ("Future commitment", "#2980B9"),
}


def _current_access_and_org():
    session = auth_session.current_session()
    ctx = auth_session.current_auth_context()
    return session["access_token"], ctx.organization_id, ctx.user_id


def _render_evidence_item(item: dict):
    trust_label, trust_color = _TRUST_LABELS.get(item.get("memory_class"), (item.get("memory_class"), "#6E6C66"))
    rel_label = _RELATIONSHIP_LABELS.get(item.get("relationship"), item.get("relationship"))
    caveat_html = (
        f'<div style="font-size:.76rem;color:#E67E22;margin-top:.15rem">⚠ {item["caveat"]}</div>'
        if item.get("caveat") else ""
    )
    st.markdown(
        f'<div style="border-left:3px solid {trust_color};padding:.3rem .6rem;margin:.3rem 0;'
        f'background:#111118;border-radius:0 4px 4px 0">'
        f'<strong>{item.get("title","")}</strong> '
        f'<span style="font-size:.72rem;color:{trust_color};font-weight:600">{trust_label}</span> '
        f'<span style="font-size:.72rem;color:#A9A69D">· {rel_label}</span>'
        f'<div style="font-size:.78rem;color:#A9A69D;margin-top:.15rem">{item.get("rationale","")}</div>'
        f'{caveat_html}'
        f'</div>', unsafe_allow_html=True)


def _render_claim(claim: dict):
    type_label = _CLAIM_TYPE_LABELS.get(claim.get("claim_type"), claim.get("claim_type"))
    status_label, status_color = _SUPPORT_STATUS_LABELS.get(claim.get("support_status"), (claim.get("support_status"), "#6E6C66"))
    evidence_ids = claim.get("evidence_ids") or []
    evidence_html = (
        f'<div style="font-size:.72rem;color:#A9A69D;margin-top:.15rem">Evidence: {", ".join(evidence_ids)}</div>'
        if evidence_ids else
        '<div style="font-size:.72rem;color:#C0392B;margin-top:.15rem">No supporting evidence in this brief</div>'
    )
    st.markdown(
        f'<div style="border-left:3px solid {status_color};padding:.3rem .6rem;margin:.4rem 0;'
        f'background:#111118;border-radius:0 4px 4px 0">'
        f'<div style="font-size:.85rem;color:#EDEAE3">{claim.get("claim_text","")}</div>'
        f'<span style="font-size:.7rem;color:#A9A69D">{type_label}</span> '
        f'<span style="font-size:.7rem;font-weight:600;color:{status_color}">{status_label}</span>'
        f'{evidence_html}'
        f'</div>', unsafe_allow_html=True)


def _render_draft_result(result: dict, assurance: dict | None, is_stale: bool, key_suffix: str):
    badges = []
    if assurance is not None:
        if assurance.get("passed"):
            badges.append(("🟢 Assurance passed", "#27AE60"))
        else:
            badges.append(("🔴 Assurance — requires remediation", "#C0392B"))
    if result.get("human_confirmation_required"):
        badges.append(("🟡 Human confirmation required", "#C9A96E"))
    if is_stale:
        badges.append(("🟠 Stale — based on an older intelligence state", "#E67E22"))
    if badges:
        st.markdown(
            " &nbsp;&nbsp; ".join(
                f'<span style="font-size:.75rem;font-weight:600;color:{c}">{t}</span>' for t, c in badges
            ), unsafe_allow_html=True)

    st.text_area(
        "Historical AI draft text (read-only record)",
        value=result.get("draft_text", ""), height=240,
        key=f"draft_view_{key_suffix}", disabled=True)

    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"**Word count:** {result.get('word_count') if result.get('word_count') is not None else '—'}")
        if result.get("requirements_addressed"):
            st.markdown("**Requirements addressed:** " + ", ".join(result["requirements_addressed"]))
        if result.get("requirements_missing"):
            st.markdown(f':red[**Requirements missing:** {", ".join(result["requirements_missing"])}]')
        if result.get("evaluation_criteria_addressed"):
            st.markdown("**Evaluation criteria addressed:** " + ", ".join(result["evaluation_criteria_addressed"]))
    with c2:
        if result.get("unsupported_or_unresolved_points"):
            st.markdown("**Unresolved points:**")
            for p in result["unsupported_or_unresolved_points"]:
                st.markdown(f"- {p}")
        if result.get("contradictions_or_caveats"):
            st.markdown("**Contradictions / caveats:**")
            for c in result["contradictions_or_caveats"]:
                st.markdown(f"- ⚠ {c}")

    if assurance is not None and assurance.get("issues"):
        with st.expander("Assurance issues", expanded=not assurance.get("passed")):
            for issue in assurance["issues"]:
                st.markdown(f"- {issue}")

    claims = result.get("material_claims") or []
    if claims:
        with st.expander(f"🔗 Evidence behind material claims ({len(claims)})", expanded=False):
            st.caption(
                "Which evidence item supports THIS specific claim -- not just which evidence "
                "was used somewhere in the draft.")
            for c in claims:
                _render_claim(c)
    elif result.get("draft_text"):
        st.caption(
            "No claim-level evidence mapping recorded for this draft (an older draft, or the "
            "claim-mapping schema addition is not yet live -- see migrations/019_section_draft_"
            "claim_mappings.sql).")


def render_requirement_response_brief(bid_id: int, requirement: dict, outline_section: dict | None = None):
    """The public entry point, called from pages/stage_build.py for ONE
    selected requirement. `requirement` must be a `requirements` table row
    (needs at least `id`/`req_id`); `outline_section` is the currently
    active outline_sections row/dict, if any, used only for word_limit/
    title/notes context (never fetched by this module itself)."""
    requirement_id = requirement.get("id")
    if not requirement_id:
        st.caption("This requirement has no saved id yet -- save it before opening its response brief.")
        return

    _token, org_id, user_id = _current_access_and_org()

    try:
        status = tenancy.get_section_draft_status_for_organization(
            bid_id, org_id, requirement_id, outline_section=outline_section)
    except tenancy.AccessDeniedError as e:
        st.error(f"Not authorized: {e}")
        return
    except Exception as e:
        st.error(f"Could not load requirement intelligence: {e}")
        return

    brief = status["brief"]

    # ── Requirement ──────────────────────────────────────────────────────
    mandatory_tag = " 🔴 **MANDATORY**" if brief.get("is_mandatory") else ""
    st.markdown(f"###### 🎯 [{brief.get('req_id','')}] {brief.get('category') or ''}{mandatory_tag}")
    st.markdown(brief.get("description") or "")
    if brief.get("related_requirements"):
        with st.expander(f"Related requirements ({len(brief['related_requirements'])})", expanded=False):
            for r in brief["related_requirements"]:
                st.markdown(f"- [{r.get('req_id','')}] {r.get('description','')}")

    # ── Evaluation intent ────────────────────────────────────────────────
    with st.expander("📐 What will the evaluator look for?", expanded=True):
        ev = brief.get("evaluation") or {}
        if ev.get("criterion_label"):
            weight_str = f" · Weight: **{ev['weight']}**" if ev.get("weight") else ""
            min_str = f" · Minimum score: **{ev['minimum_score']}**" if ev.get("minimum_score") else ""
            st.markdown(f"**Criterion:** {ev['criterion_label']}{weight_str}{min_str}")
        else:
            st.caption("No evaluation criterion matched from Fast Analysis for this requirement.")
        if ev.get("response_guideline"):
            st.markdown(f"**Response guidance:** {ev['response_guideline']}")
        rc = brief.get("response_constraints") or {}
        if rc.get("word_limit"):
            st.markdown(f"**Word limit:** {rc['word_limit']}")

    # ── Evidence state ───────────────────────────────────────────────────
    with st.expander("🔬 What evidence do we have, and how trustworthy is it?", expanded=True):
        gap_kind = brief.get("evidence_gap_kind")
        gap_label, gap_color = _GAP_LABELS.get(gap_kind, (gap_kind or "Unknown", "#6E6C66"))
        st.markdown(f'Current-bid evidence gap: <span style="color:{gap_color};font-weight:700">{gap_label}</span>',
                    unsafe_allow_html=True)

        bse = brief.get("bid_specific_evidence") or {}
        if bse:
            st.markdown(
                f"Bid-specific (current proposal) evidence — Status: "
                f"**{bse.get('assessment_status') or 'Unknown'}** · "
                f"Strength: **{bse.get('evidence_strength') or 'Unknown'}**")
            if bse.get("explanation"):
                st.caption(bse["explanation"])
        else:
            st.caption("No current-bid (Proposal Intelligence) assessment recorded yet for this requirement.")

        om_evidence = brief.get("organizational_evidence") or []
        if om_evidence:
            st.markdown("**Organizational Memory evidence:**")
            for item in om_evidence:
                _render_evidence_item(item)
        else:
            st.caption("No Organizational Memory enrichment persisted yet for this requirement.")

        if brief.get("remaining_gaps"):
            st.markdown("**What is still missing:**")
            for g in brief["remaining_gaps"]:
                st.markdown(f"- {g}")

    # ── Human confirmation / caveats / constraints ───────────────────────
    with st.expander("🧑‍⚖️ What must a human confirm, and what constraints apply?", expanded=True):
        needs_confirmation = bool(
            brief.get("requires_human_confirmation_from_enrichment")
            or brief.get("evidence_gap_kind") in ("MISSING", "CONFLICTED")
            or brief.get("remaining_gaps")
            or any(e.get("relationship") == "CONTRADICTION" for e in (brief.get("organizational_evidence") or [])))
        if needs_confirmation:
            st.markdown("🟡 **SME / human confirmation required** before any claim on this requirement is made.")
        contradictions = [e for e in (brief.get("organizational_evidence") or []) if e.get("relationship") == "CONTRADICTION"]
        for c in contradictions:
            st.markdown(f"- ⚠ Contradiction: **{c.get('title','')}** — {c.get('caveat') or c.get('rationale') or ''}")
        for f in brief.get("proposal_intelligence_findings") or []:
            st.markdown(f"- [{f.get('finding_type')}] {f.get('title') or ''}: {f.get('message') or ''}")
        rc = brief.get("response_constraints") or {}
        parts = []
        if rc.get("word_limit"):
            parts.append(f"Word limit: **{rc['word_limit']}**")
        if rc.get("section_title"):
            parts.append(f"Section: **{rc['section_title']}**")
        st.markdown(" · ".join(parts) if parts else "No explicit response constraints recorded.")
        st.caption("Bid Intelligence does not write the response — use this brief to guide your team's writing, "
                   "then assess the written section with the Section Analyzer or in CHECK.")

    # ── Historical AI drafts (retired capability; read-only) ─────────────
    history = status.get("history") or []
    if history:
        with st.expander(f"🗄 Historical AI draft records — retired capability ({len(history)})", expanded=False):
            st.caption("Created before Bid Intelligence stopped generating proposal narrative. Kept read-only "
                       "for lineage; not a recommended response and never regenerated.")
            labels = [f"v{len(history) - i} · {(h.get('created_at') or '')[:19].replace('T', ' ')}"
                      for i, h in enumerate(history)]
            choice = st.selectbox("Record", labels, index=0, key=f"draft_history_pick_{requirement_id}")
            chosen = history[labels.index(choice)]
            _render_draft_result(
                chosen["result"], chosen["assurance"],
                is_stale=(labels.index(choice) == 0 and bool(status.get("is_stale"))),
                key_suffix=f"hist_{requirement_id}_{chosen.get('id')}")
