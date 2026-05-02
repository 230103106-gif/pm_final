from __future__ import annotations

import streamlit as st

from core import auth
from core.database import init_db
from core.utils import AuthenticationError, configure_page, inject_styles, render_page_header, render_sidebar


configure_page("Login", icon="🔐")
inject_styles()
init_db()

current_user = auth.get_current_user()
if current_user:
    auth.redirect_after_login(current_user)

render_sidebar(None)
render_page_header(
    "Secure Access",
    "Sign in to the Geo-Optimized Furniture OMS",
    "Use one of the demo personas to explore the customer storefront, admin control room, or regional warehouse queue.",
)

left, center, right = st.columns([0.9, 1.2, 0.9])
with center:
    st.markdown('<div class="surface-card">', unsafe_allow_html=True)
    st.subheader("Login")
    with st.form("login_form", clear_on_submit=False):
        username = st.text_input("Username", placeholder="admin")
        password = st.text_input("Password", type="password", placeholder="Enter your password")
        submitted = st.form_submit_button("Sign in", type="primary", use_container_width=True)
    if submitted:
        try:
            user = auth.login_user(username, password)
            st.success("Login successful. Redirecting to your workspace.")
            auth.redirect_after_login(user)
        except AuthenticationError as exc:
            st.error(str(exc))
    st.markdown("---")
    st.caption("Demo credentials: admin / Admin@123, customer / Customer@123, warehouse / Warehouse@123")
    st.markdown("</div>", unsafe_allow_html=True)
