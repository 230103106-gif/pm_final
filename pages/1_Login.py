from __future__ import annotations

import streamlit as st

from core import auth
from core.database import get_session, init_db
from core.utils import AuthenticationError, ValidationError, configure_page, inject_styles, render_page_header
from services import audit_service, user_service


configure_page("Login", icon="🔐", sidebar_state="collapsed")
inject_styles()
init_db()

current_user = auth.get_current_user()
if current_user:
    auth.redirect_after_login(current_user)

render_page_header(
    "Account Access",
    "Sign in to the furniture order operations platform",
    "Customer accounts can be created online. Administrative and warehouse access is provisioned by operations.",
)

left, center, right = st.columns([0.9, 1.2, 0.9])
with center:
    st.markdown('<div class="surface-card">', unsafe_allow_html=True)
    sign_in_tab, register_tab = st.tabs(["Sign in", "Create account"])

    with sign_in_tab:
        with st.form("login_form", clear_on_submit=False):
            username = st.text_input("Username", placeholder="Enter your username")
            password = st.text_input("Password", type="password", placeholder="Enter your password")
            submitted = st.form_submit_button("Sign in", type="primary", use_container_width=True)
        if submitted:
            try:
                user = auth.login_user(username, password)
                auth.redirect_after_login(user)
            except AuthenticationError as exc:
                st.error(str(exc))

    with register_tab:
        with st.form("register_form", clear_on_submit=False):
            full_name = st.text_input("Full name", placeholder="Enter your full name")
            username = st.text_input("Username", placeholder="Choose a username")
            password = st.text_input("Password", type="password", placeholder="Create a password")
            confirm_password = st.text_input("Confirm password", type="password", placeholder="Repeat your password")
            submitted = st.form_submit_button("Create customer account", type="primary", use_container_width=True)
        if submitted:
            try:
                if password != confirm_password:
                    raise ValidationError("Password confirmation does not match.")
                with get_session() as session:
                    created_user = user_service.create_user(
                        session,
                        username=username,
                        full_name=full_name,
                        password=password,
                        role="customer",
                    )
                    audit_service.log_action(
                        session,
                        actor=created_user,
                        action="auth.register",
                        entity_type="user",
                        entity_id=str(created_user.id),
                        details={"username": created_user.username, "role": created_user.role},
                    )
                user = auth.login_user(username, password)
                auth.redirect_after_login(user)
            except ValidationError as exc:
                st.error(str(exc))
    st.markdown("</div>", unsafe_allow_html=True)
