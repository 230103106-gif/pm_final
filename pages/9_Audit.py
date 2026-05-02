from __future__ import annotations

import streamlit as st

from core.database import get_session
from core.utils import initialize_page, render_page_header
from services import audit_service


user = initialize_page("Audit Logs", icon="📜", allowed_roles=["admin"])
render_page_header(
    "Audit Trail",
    "Inspect authentication, product, order, and warehouse actions captured by the platform.",
    "Every meaningful operational change is written to SQLite and can be exported for compliance or offline review.",
)

with get_session() as session:
    filters = st.columns(3, gap="large")
    with filters[0]:
        action_filter = st.selectbox(
            "Action",
            [
                "All",
                "auth.login",
                "auth.logout",
                "order.created",
                "order.status_updated",
                "product.created",
                "product.updated",
                "warehouse.event_processed",
                "warehouse.event_failed",
            ],
        )
    with filters[1]:
        entity_filter = st.selectbox("Entity", ["All", "user", "order", "product", "warehouse_event"])
    with filters[2]:
        actor_filter = st.text_input("Actor username", placeholder="Optional exact username")

    logs = audit_service.list_logs(
        session,
        actor_username=actor_filter or None,
        action=action_filter,
        entity_type=entity_filter,
        limit=1000,
    )
    st.dataframe(
        [
            {
                "Timestamp": row["created_at"],
                "Actor": row["actor"],
                "Action": row["action"],
                "Entity": row["entity_type"],
                "Entity ID": row["entity_id"],
            }
            for row in logs
        ],
        use_container_width=True,
        hide_index=True,
    )

    export_path, export_payload = audit_service.export_logs_json(session)
    st.download_button("Download logs.json", data=export_payload, file_name=export_path.name, mime="application/json")

    if logs:
        log_map = {
            f"{row['created_at']} · {row['actor']} · {row['action']}": row
            for row in logs[:100]
        }
        selected_label = st.selectbox("Inspect log entry", list(log_map.keys()))
        selected = log_map[selected_label]
        st.json(selected["details"])
