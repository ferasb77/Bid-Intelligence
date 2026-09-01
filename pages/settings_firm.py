"""
Settings & Bidding Firm Profile
Configures the bidding organization's capability profile, standard credentials,
insurance defaults, and ethical AI usage disclosure to power generic AI prompts.
"""
import streamlit as st
from database import get_firm_profile, save_firm_profile
from config import api_key_configured


def page_settings_firm():
    st.markdown('<div style="font-size:.72rem;color:#C9A96E;text-transform:uppercase;letter-spacing:.12em;font-weight:600">SETTINGS & PROFILE</div>', unsafe_allow_html=True)
    st.markdown("# Firm Profile & System Configuration")
    st.markdown('<div class="gold-rule"></div>', unsafe_allow_html=True)

    st.markdown(
        '<div class="info-box">'
        'Configure your organization profile, core capabilities, standard insurance coverage, and credentials. '
        'This information is dynamically injected into AI qualification scoring, clarification generation, and proposal drafting engines.'
        '</div>',
        unsafe_allow_html=True
    )

    profile = get_firm_profile()

    with st.form("firm_profile_form"):
        st.markdown("### 🏢 Organization Identity")
        c1, c2 = st.columns(2)
        company_name = c1.text_input("Bidding Entity / Company Name *", value=profile.get("company_name", "Enable My Growth"))
        locations = c2.text_input("Primary Operating Locations / Jurisdictions", value=profile.get("locations", "Canada, International"))

        overview = st.text_area("Corporate Overview & Value Proposition", value=profile.get("overview", ""), height=80,
                                placeholder="Describe your firm's core focus, history, and client value proposition...")

        st.markdown("### 🎯 Core Capabilities & Sector Experience")
        core_cap = st.text_area("Core Service & Technical Capabilities", value=profile.get("core_capabilities", ""), height=80,
                               placeholder="e.g. Strategic advisory, program delivery, technology enablement, change management...")

        c_s1, c_s2 = st.columns(2)
        key_sectors = c_s1.text_input("Key Sectors / Client Domains", value=profile.get("key_sectors", "Public Sector, Healthcare, Financial Services, Non-Profit"))
        languages = c_s2.text_input("Languages Supported", value=profile.get("languages", "English, French"))

        st.markdown("### 🛡️ Credentials, Clearances & Insurance Defaults")
        c_c1, c_c2 = st.columns(2)
        certs = c_c1.text_area("Certifications, Accreditations & Designations", value=profile.get("certifications", ""), height=70,
                               placeholder="e.g. ISO 9001, CMC, PMI, PMP, Security Clearances...")
        ins = c_c2.text_area("Standard Insurance Coverage & Limits", value=profile.get("insurance_defaults", ""), height=70,
                             placeholder="e.g. Commercial General Liability $5,000,000 | Professional E&O $2,000,000...")

        st.markdown("### 🤖 Ethical AI Usage & Disclosure Policy")
        ai_pol = st.text_area("AI Transparency & Disclosure Statement", value=profile.get("ai_disclosure_policy", ""), height=60,
                             placeholder="Standard disclosure for tender submissions regarding ethical AI usage...")

        if st.form_submit_button("Save Firm Profile", use_container_width=True, type="primary"):
            save_firm_profile({
                "company_name": company_name,
                "overview": overview,
                "core_capabilities": core_cap,
                "key_sectors": key_sectors,
                "languages": languages,
                "locations": locations,
                "certifications": certs,
                "insurance_defaults": ins,
                "ai_disclosure_policy": ai_pol,
            })
            st.success("Firm profile saved successfully!")
            st.rerun()

    # Anthropic API Key Status
    st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
    st.markdown("### 🔑 AI Service Configuration")
    if api_key_configured():
        st.markdown('<div class="success-box">✓ <strong>Anthropic API Key Active:</strong> Claude 3.5 / Haiku intelligence engines configured.</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="warn-box">⚠️ <strong>No API Key Configured:</strong> Set <code>ANTHROPIC_API_KEY</code> in <code>.env</code>, Streamlit secrets, or below.</div>', unsafe_allow_html=True)
        key_in = st.text_input("Temporary Session API Key", type="password")
        if st.button("Apply Key to Session"):
            st.session_state["anthropic_api_key"] = key_in
            st.success("Applied.")
            st.rerun()
