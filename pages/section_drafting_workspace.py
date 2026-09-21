"""
pages/section_drafting_workspace.py -- PI-3C: Section Drafting Workspace.

The first user-facing proposal-writing experience in Bid Intelligence.
Renders, for ONE requirement, the flow this phase's own authorization
names: requirement -> evaluation intent -> evidence -> gaps -> grounded
draft -> assurance -> evidence behind material claims.

NOT a standalone page/global-nav entry -- reused as a rendering function
from pages/stage_build.py's existing BUILD/Section Analyzer experience
(the smallest coherent integration point: a user already viewing an
outline section's mapped requirements can open this workspace for one of
them, without navigating to a disconnected screen).

Token/execution discipline (instruction 12): rendering this workspace
calls ONLY tenancy.get_section_draft_status_for_organization, a read-only
function that never calls Anthropic, never calls Organizational Memory
retrieval, and never re-runs Proposal Alignment/Fast Analysis -- every
field shown here comes from already-persisted, already-bounded
intelligence. Generating or refreshing a draft is an explicit user action
(a button click) that calls tenancy.get_or_generate_section_draft, which
may make a real drafting call only when no fresh persisted draft already
exists for the current intelligence state.

Explicitly NOT built here (PI-3C scope, see docs/current/SYSTEM_STATE.md):
whole-proposal generation, a collaborative editor (the draft is read-only
this phase), visual version diffing, Word export, Ask CapOS, Red Team.
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
        "Generated draft (read-only — see instruction 11: no editor in this phase)",
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


def render_requirement_drafting_workspace(bid_id: int, requirement: dict, outline_section: dict | None = None):
    """The public entry point, called from pages/stage_build.py for ONE
    selected requirement. `requirement` must be a `requirements` table row
    (needs at least `id`/`req_id`); `outline_section` is the currently
    active outline_sections row/dict, if any, used only for word_limit/
    title/notes context (never fetched by this module itself)."""
    requirement_id = requirement.get("id")
    if not requirement_id:
        st.caption("This requirement has no saved id yet -- save it before opening its drafting workspace.")
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

    # ── Draft state + generation ─────────────────────────────────────────
    st.markdown("##### ✍️ Section Draft")
    latest = status.get("latest_draft")
    is_stale = status.get("is_stale")

    if latest is None:
        st.info("No draft generated yet for the current intelligence state.")
        gen_label = "✨ Generate Section Draft"
    elif is_stale:
        st.warning(
            "🟠 Stale — the intelligence behind this requirement has changed since this draft "
            "was generated (a prior immutable version, still viewable below).")
        gen_label = "🔄 Generate Updated Draft"
    else:
        st.success("🟢 This draft is current with the latest intelligence.")
        gen_label = "🔄 Generate New Version"

    if st.button(gen_label, key=f"gen_draft_{requirement_id}", type="primary"):
        with st.spinner("Drafting section against buyer requirements…"):
            try:
                tenancy.get_or_generate_section_draft(
                    bid_id, org_id, requirement_id, outline_section=outline_section,
                    created_by_user_id=user_id)
                st.rerun()
            except tenancy.AccessDeniedError as e:
                st.error(f"Not authorized: {e}")
            except Exception as e:
                st.error(f"Draft generation failed: {e}")

    if latest is not None:
        _render_draft_result(latest, status.get("latest_draft_assurance"), is_stale, key_suffix=f"latest_{requirement_id}")

    # ── Draft history (instruction 10 -- minimal, no visual diffing) ─────
    history = status.get("history") or []
    if len(history) > 1:
        with st.expander(f"📜 Draft history ({len(history)} version{'s' if len(history) != 1 else ''})", expanded=False):
            labels = [
                f"v{len(history) - i} · {h['created_at'][:19].replace('T', ' ')}"
                + (" (latest)" if i == 0 else "")
                for i, h in enumerate(history)
            ]
            choice = st.selectbox(
                "View an earlier version", labels, index=0, key=f"draft_history_pick_{requirement_id}")
            chosen = history[labels.index(choice)]
            if labels.index(choice) != 0:
                st.caption("Viewing a prior, superseded version — read-only, never regenerated automatically.")
                _render_draft_result(
                    chosen["result"], chosen["assurance"], is_stale=False,
                    key_suffix=f"hist_{requirement_id}_{chosen['id']}")
