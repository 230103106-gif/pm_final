from __future__ import annotations

import streamlit as st

from core.database import get_session
from core.utils import ValidationError, currency, initialize_page, render_detail_grid, render_page_header, render_status_badge
from services import order_service


user = initialize_page("My Orders", icon="📋", allowed_roles=["customer"])
render_page_header(
    "Customer Orders",
    "Track the lifecycle of every order linked to your account.",
    "Cancellation is only available while the order is still in early intake stages, and status changes are enforced in the backend.",
)

with get_session() as session:
    filters = st.columns([0.25, 0.75], gap="large")
    with filters[0]:
        status_filter = st.selectbox("Status", ["All"] + [status for status in order_service.settings.order_statuses])
    with filters[1]:
        search_filter = st.text_input("Search", placeholder="Order number, recipient, or city")

    rows = order_service.list_orders(session, user, status=status_filter, search=search_filter, include_cancelled=True)
    st.dataframe(
        [
            {
                "Order": row["order_number"],
                "Product": row["product_name"],
                "Quantity": row["quantity"],
                "Total": currency(row["total_amount"]),
                "Status": row["status"],
                "City": row["city"],
                "Created": row["created_at"],
            }
            for row in rows
        ],
        use_container_width=True,
        hide_index=True,
    )

    export_path, export_payload = order_service.export_orders_csv(session, user)
    st.download_button(
        "Download my orders CSV",
        data=export_payload,
        file_name=export_path.name,
        mime="text/csv",
    )

    if not rows:
        st.info("No orders match the current filters.")
        st.stop()

    labels = {f"{row['order_number']} · {row['product_name']} · {row['status']}": row["id"] for row in rows}
    selected_label = st.selectbox("Select an order", list(labels.keys()))
    detail = order_service.order_detail(session, user, labels[selected_label])

    left, right = st.columns([1.1, 0.9], gap="large")
    with left:
        st.markdown(render_status_badge(detail["status"]), unsafe_allow_html=True)
        render_detail_grid(
            {
                "Order Number": detail["order_number"],
                "Product": detail["product_name"],
                "Quantity": str(detail["quantity"]),
                "Total": currency(detail["total_amount"]),
                "Region": detail["region_label"],
                "Recipient": detail["recipient_name"],
                "Phone": detail["phone"],
                "Destination": f"{detail['city']}, {detail['state']}",
            }
        )
        st.markdown(
            f"""
            <div class="surface-card" style="margin-top:1rem;">
                <strong>Delivery address</strong>
                <div class="mini-note">{detail['address_line1']} {detail['address_line2']}</div>
                <div class="mini-note">{detail['city']}, {detail['state']} {detail['postal_code']}</div>
                <div class="mini-note">Notes: {detail['notes'] or 'No additional instructions'}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with right:
        st.subheader("Lifecycle timeline")
        for label, timestamp in order_service.order_timeline(detail):
            state = timestamp.strftime("%Y-%m-%d %H:%M") if timestamp else "Pending"
            st.markdown(f"**{label}**  \n{state}")
        if detail["status"] in order_service.settings.early_cancellable_statuses:
            st.markdown("---")
            st.subheader("Cancel order")
            with st.form("cancel_order_form"):
                reason = st.text_area("Cancellation reason", height=100)
                confirm = st.checkbox("I understand this restores reserved stock and closes the order.")
                submit = st.form_submit_button("Cancel this order", type="primary")
                if submit:
                    if not confirm:
                        st.error("Please confirm the cancellation policy.")
                    else:
                        try:
                            order_service.cancel_order(session, user, detail["id"], reason or "Customer changed delivery request.")
                            st.success("The order was cancelled.")
                            st.rerun()
                        except ValidationError as exc:
                            st.error(str(exc))
