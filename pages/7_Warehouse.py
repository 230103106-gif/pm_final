from __future__ import annotations

import streamlit as st

from core.database import get_session
from core.utils import initialize_page, render_metric_card, render_page_header
from services import order_service, warehouse_service


user = initialize_page("Warehouse", icon="🏭", allowed_roles=["admin", "warehouse_manager"])
render_page_header(
    "Warehouse Event Queue",
    "Process newly created orders into the fulfillment pipeline and keep regional intake under control.",
    "Pending events act as the operational handshake between customer checkout and downstream warehouse execution.",
)

with get_session() as session:
    summary = warehouse_service.queue_summary(session, user)
    metrics = st.columns(3)
    with metrics[0]:
        render_metric_card("Pending Events", str(summary["pending_events"]), "Orders waiting for warehouse intake")
    with metrics[1]:
        render_metric_card("Processed Events", str(summary["processed_events"]), "Queue items already acknowledged")
    with metrics[2]:
        render_metric_card("Coverage", summary["covered_region"], "Current operational visibility")

    status_filter = st.selectbox("Event status", ["All", "pending", "processed", "failed"])
    events = warehouse_service.list_events(session, user, event_status=status_filter, limit=200)
    st.dataframe(
        [
            {
                "Event ID": row["id"],
                "Order": row["order_number"],
                "Event": row["event_type"],
                "Region": row["region_label"],
                "Order Status": row["order_status"],
                "Queue Status": row["status"],
            }
            for row in events
        ],
        use_container_width=True,
        hide_index=True,
    )

    if events:
        event_map = {f"#{row['id']} · {row['order_number']} · {row['status']}": row["id"] for row in events}
        selected_label = st.selectbox("Select queue item", list(event_map.keys()))
        selected_id = event_map[selected_label]
        selected_event = next(row for row in events if row["id"] == selected_id)

        left, right = st.columns([1.0, 1.0], gap="large")
        with left:
            st.markdown(
                f"""
                <div class="surface-card">
                    <strong>{selected_event['order_number']}</strong><br>
                    <span class="mini-note">{selected_event['event_type']} · {selected_event['region_label']}</span><br>
                    <span class="mini-note">Current order status: {selected_event['order_status']}</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with right:
            if selected_event["status"] == "pending":
                with st.form("process_event_form"):
                    confirm = st.checkbox("I confirm this order is ready for warehouse intake processing.")
                    submit = st.form_submit_button("Process queue item", type="primary")
                    if submit:
                        if not confirm:
                            st.error("Please confirm before processing the queue item.")
                        else:
                            processed_event = warehouse_service.process_event(session, user, selected_id)
                            if processed_event.status == "failed":
                                st.warning(processed_event.last_error or "The queue item could not be processed.")
                            else:
                                st.success("Warehouse event processed.")
                            st.rerun()
            else:
                st.info("This queue item has already been handled.")

    st.subheader("Regional backlog")
    backlog = [
        row
        for row in order_service.list_orders(session, user, include_cancelled=False)
        if row["status"] != "Delivered"
    ][:20]
    st.dataframe(
        [
            {
                "Order": row["order_number"],
                "Product": row["product_name"],
                "Status": row["status"],
                "City": row["city"],
                "Region": row["region_label"],
            }
            for row in backlog
        ],
        use_container_width=True,
        hide_index=True,
    )
