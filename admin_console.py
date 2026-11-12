"""
admin_console.py — Bid Intelligence Super Admin console (Super Admin MVP).

A SEPARATE Streamlit entrypoint, deployed as its own container/hostname,
never mounted inside the client application (app.py). Layers of control:

  1. Network: own loopback port; external exposure only through a dedicated
     owner-only Cloudflare Access application (separately authorized).
  2. Deployment flag: refuses to run unless PLATFORM_ADMIN_CONSOLE_ENABLED=1.
  3. Identity: Supabase Auth password sign-in (server-side).
  4. Authority: public.platform_admins membership, re-checked on every
     action inside platform_admin.py. Organization roles never qualify.

All privileged work happens server-side in platform_admin.py. No key, token,
or credential is placed in the page beyond the admin's own session tokens in
Streamlit's server-side session state.
"""
import os

import streamlit as st

st.set_page_config(page_title="Bid Intelligence — Platform Admin", page_icon="◈", layout="wide")

if os.getenv("PLATFORM_ADMIN_CONSOLE_ENABLED") != "1":
    st.error("The platform admin console is not enabled in this deployment.")
    st.stop()

import auth_session  # noqa: E402
import platform_admin as pa  # noqa: E402

APP_BASE_URL = os.getenv("CLIENT_APP_BASE_URL", "")
CF_ACCESS_POLICY_HINT = os.getenv("CLIENT_ACCESS_POLICY_NAME", "Phoenix Beta allowlist")


def _sign_in_gate():
    st.markdown("## Platform admin sign-in")
    st.caption("Restricted to platform administrators. Every action is recorded in the audit trail.")
    with st.form("admin_sign_in", clear_on_submit=True):
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in", type="primary")
    if submitted:
        result = auth_session.sign_in(email, password)
        if not result.ok:
            st.error("Sign-in failed.")
            return
        st.rerun()


session = auth_session.restore_session()
if not session.ok:
    _sign_in_gate()
    st.stop()

ACTOR_ID, ACTOR_EMAIL = session.user_id, session.email or ""

try:
    pa.require_platform_admin(ACTOR_ID, ACTOR_EMAIL, "open_console")
except pa.PlatformAdminDenied:
    auth_session.sign_out()
    st.error("This account is not a platform administrator. Access denied and recorded.")
    st.stop()

with st.sidebar:
    st.markdown("### Platform admin")
    st.caption(ACTOR_EMAIL)
    if st.button("Sign out"):
        auth_session.sign_out()
        st.rerun()


def _guard(fn, *args, success: str | None = None, **kwargs):
    try:
        out = fn(ACTOR_ID, ACTOR_EMAIL, *args, **kwargs)
    except pa.PlatformAdminDenied:
        auth_session.sign_out()
        st.error("Platform administrator authority is no longer present. Signed out.")
        st.stop()
    except pa.PlatformAdminError as e:
        st.error(str(e))
        return None
    except Exception:
        st.error("Unexpected error. Check the audit trail before retrying.")
        return None
    if success:
        st.success(success)
    return out


def _fmt_memberships(ms):
    return "; ".join(f"{m['organization_name']} ({pa.ROLE_LABELS.get(m['role'], m['role'])})" for m in ms) or "—"


tab_users, tab_orgs, tab_audit = st.tabs(["Users", "Organizations", "Audit trail"])

orgs = _guard(pa.list_organizations) or []
org_label = {o["id"]: f"{o['name']} ({o['slug']})" for o in orgs}

# ── Organizations ────────────────────────────────────────────────────────
with tab_orgs:
    st.markdown("#### Client organizations")
    st.dataframe(
        [{"Name": o["name"], "Slug": o["slug"], "Members": o["member_count"],
          "Admins": o["admin_count"], "Created": o.get("created_at")} for o in orgs],
        use_container_width=True, hide_index=True)
    with st.form("create_org", clear_on_submit=True):
        st.markdown("**Create organization**")
        name = st.text_input("Name")
        slug = st.text_input("Slug (lowercase, digits, hyphens)")
        if st.form_submit_button("Create organization"):
            if _guard(pa.create_organization, name, slug, success=f"Organization '{name}' created."):
                st.rerun()

# ── Users ────────────────────────────────────────────────────────────────
with tab_users:
    users = _guard(pa.list_users) or []
    st.markdown("#### Users")
    st.dataframe(
        [{"Email": u["email"],
          "Status": "Disabled" if u["disabled"] else "Active",
          "Password set / signed in": "yes" if u["last_sign_in_at"] else "not yet",
          "Platform admin": "yes" if u["is_platform_admin"] else "",
          "Memberships": _fmt_memberships(u["memberships"]),
          "Last sign-in": u["last_sign_in_at"] or "—"} for u in users],
        use_container_width=True, hide_index=True)

    with st.form("create_user", clear_on_submit=True):
        st.markdown("**Create user** (no password is set; issue a setup link afterwards)")
        new_email = st.text_input("Email")
        new_org = st.selectbox("Organization", list(org_label), format_func=org_label.get, index=None)
        new_role = st.selectbox("Role", pa.ASSIGNABLE_ROLES, format_func=pa.ROLE_LABELS.get)
        if st.form_submit_button("Create user"):
            created = _guard(pa.create_user, new_email, new_org or "", new_role,
                             success=f"User {new_email} created.")
            if created:
                st.info(
                    f"Next steps: (1) add {created['email']} to the Cloudflare Access policy "
                    f"'{CF_ACCESS_POLICY_HINT}' (manual, separate approval); "
                    "(2) issue a password-setup link below and deliver it directly to the user.")

    st.markdown("#### Manage a user")
    user_label = {u["id"]: f"{u['email']}{' — DISABLED' if u['disabled'] else ''}" for u in users}
    target = st.selectbox("User", list(user_label), format_func=user_label.get, index=None)
    if target:
        tu = next(u for u in users if u["id"] == target)
        st.write(f"**Status:** {'Disabled' if tu['disabled'] else 'Active'} · "
                 f"**Memberships:** {_fmt_memberships(tu['memberships'])}")

        c1, c2 = st.columns(2)
        with c1:
            with st.form("set_membership"):
                st.markdown("**Add membership / change role**")
                m_org = st.selectbox("Organization", list(org_label), format_func=org_label.get, index=None)
                m_role = st.selectbox("Role", pa.ASSIGNABLE_ROLES, format_func=pa.ROLE_LABELS.get)
                if st.form_submit_button("Save membership") and m_org:
                    if _guard(pa.set_membership, target, m_org, m_role, success="Membership saved.") is None:
                        pass
            if tu["memberships"]:
                with st.form("remove_membership"):
                    st.markdown("**Remove membership**")
                    r_org = st.selectbox("Organization", [m["organization_id"] for m in tu["memberships"]],
                                         format_func=lambda i: org_label.get(i, i))
                    confirm = st.checkbox("I confirm removing this membership")
                    if st.form_submit_button("Remove") and confirm:
                        _guard(pa.remove_membership, target, r_org, success="Membership removed.")
        with c2:
            st.markdown("**Access**")
            if tu["disabled"]:
                if st.button("Re-enable user", key=f"enable_{target}"):
                    _guard(pa.enable_user, target, success="User re-enabled.")
            else:
                confirm_disable = st.checkbox("I confirm disabling this user", key=f"cd_{target}")
                if st.button("Disable user", key=f"disable_{target}") and confirm_disable:
                    _guard(pa.disable_user, target, success="User disabled. Active sessions end within seconds.")

            st.markdown("**Password setup link**")
            st.caption("Single-use; expires per the Auth server's link lifetime. Shown once; never stored. "
                       "Deliver directly to this user only. Issuing a new link invalidates earlier ones.")
            if st.button("Issue setup link", key=f"link_{target}"):
                link = _guard(pa.issue_password_setup_link, target, APP_BASE_URL)
                if link:
                    st.code(link, language=None)

# ── Audit trail ──────────────────────────────────────────────────────────
with tab_audit:
    rows = _guard(pa.list_audit_log, 300) or []
    st.dataframe(
        [{"When": r["occurred_at"], "Actor": r.get("actor_email"), "Action": r["action"],
          "Outcome": r["outcome"], "Target": r.get("target_email") or r.get("target_user_id"),
          "Organization": org_label.get(r.get("organization_id"), r.get("organization_id")),
          "Details": r.get("details")} for r in rows],
        use_container_width=True, hide_index=True)
