from __future__ import annotations

import streamlit as st

from core.database import get_session
from core.utils import ValidationError, initialize_page, region_label, render_detail_grid, render_page_header
from services import audit_service, user_service


user = initialize_page("Settings", icon="⚙️", allowed_roles=["admin", "customer", "warehouse_manager"])
render_page_header(
    "Account Settings",
    "Maintain your profile, rotate credentials, and review role-specific operational context.",
    "Profile updates and password changes are persisted to SQLite and can be traced through the audit trail.",
)

with get_session() as session:
    current = user_service.get_user_by_id(session, user.id)
    left, right = st.columns([0.95, 1.05], gap="large")
    with left:
        render_detail_grid(
            {
                "Full Name": current.full_name,
                "Username": current.username,
                "Role": current.role,
                "Assigned Region": region_label(current.assigned_region),
                "Active": "Yes" if current.is_active else "No",
            }
        )
        with st.form("profile_form"):
            full_name = st.text_input("Full name", value=current.full_name)
            submit = st.form_submit_button("Save profile", type="primary")
            if submit:
                updated = user_service.update_profile(session, current, full_name=full_name)
                audit_service.log_action(
                    session,
                    actor=updated,
                    action="user.profile_updated",
                    entity_type="user",
                    entity_id=str(updated.id),
                    details={"full_name": updated.full_name},
                )
                st.success("Profile updated.")
                st.rerun()
    with right:
        with st.form("password_form"):
            current_password = st.text_input("Current password", type="password")
            new_password = st.text_input("New password", type="password")
            confirm_password = st.text_input("Confirm new password", type="password")
            submit = st.form_submit_button("Change password", type="primary")
            if submit:
                try:
                    if new_password != confirm_password:
                        raise ValidationError("New password confirmation does not match.")
                    user_service.change_password(session, current, current_password, new_password)
                    audit_service.log_action(
                        session,
                        actor=current,
                        action="user.password_changed",
                        entity_type="user",
                        entity_id=str(current.id),
                        details={"username": current.username},
                    )
                    st.success("Password changed successfully.")
                except ValidationError as exc:
                    st.error(str(exc))

    st.subheader("Operational context")
    if current.role == "admin":
        st.info("Administrator accounts have full access to dashboards, products, audit logs, exports, and all regional orders.")
    elif current.role == "warehouse_manager":
        st.info("Warehouse managers are limited to orders and events whose H3 region matches their assigned operational region.")
    else:
        st.info("Customer accounts can browse the catalog, place orders, review personal orders, and cancel only early-stage requests.")
