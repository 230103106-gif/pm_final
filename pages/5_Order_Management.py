from __future__ import annotations

import streamlit as st

from core.database import get_session
from core.utils import ValidationError, currency, initialize_page, render_detail_grid, render_page_header, render_status_badge
from services import order_service


user = initialize_page("Order Management", icon="📦", allowed_roles=["admin", "warehouse_manager"])
render_page_header(
    "Order Management",
    "Review the operational pipeline and move orders one valid state at a time.",
    "Backend enforcement prevents invalid status jumps, customer overreach, and region leakage for warehouse operators.",
)

with get_session() as session:
    filters = st.columns([0.25, 0.25, 0.5], gap="large")
    with filters[0]:
        status_filter = st.selectbox("Status", ["All"] + order_service.settings.order_statuses)
    with filters[1]:
        city_filter = st.selectbox("City", ["All"] + [city["name"] for city in order_service.city_catalog()])
    with filters[2]:
        search_filter = st.text_input("Search orders", placeholder="Order number, recipient, or city")

    rows = order_service.list_orders(session, user, status=status_filter, city=city_filter, search=search_filter, include_cancelled=True)
    st.dataframe(
        [
            {
                "Order": row["order_number"],
                "Customer": row["customer_name"],
                "Product": row["product_name"],
                "Status": row["status"],
                "Region": row["region_label"],
                "Total": currency(row["total_amount"]),
            }
            for row in rows
        ],
        use_container_width=True,
        hide_index=True,
    )

    if not rows:
        st.info("No orders are available within your current scope.")
        st.stop()

    order_options = {f"{row['order_number']} · {row['product_name']} · {row['status']}": row["id"] for row in rows}
    selected_label = st.selectbox("Select order", list(order_options.keys()))
    selected_order = order_service.get_order(session, user, order_options[selected_label])
    detail = order_service.order_detail(session, user, selected_order.id)

    left, right = st.columns([1.1, 0.9], gap="large")
    with left:
        st.markdown(render_status_badge(detail["status"]), unsafe_allow_html=True)
        render_detail_grid(
            {
                "Order Number": detail["order_number"],
                "Product": detail["product_name"],
                "Customer": detail["customer_name"],
                "Quantity": str(detail["quantity"]),
                "Total": currency(detail["total_amount"]),
                "Region": detail["region_label"],
                "H3 Region": detail["h3_region"],
                "Destination": f"{detail['city']}, {detail['state']}",
            }
        )
        st.markdown(
            f"""
            <div class="surface-card" style="margin-top:1rem;">
                <strong>Delivery profile</strong>
                <div class="mini-note">{detail['recipient_name']} · {detail['phone']}</div>
                <div class="mini-note">{detail['address_line1']} {detail['address_line2']}</div>
                <div class="mini-note">{detail['city']}, {detail['state']} {detail['postal_code']}</div>
                <div class="mini-note">Notes: {detail['notes'] or 'No special instructions'}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with right:
        st.subheader("Timeline")
        for label, timestamp in order_service.order_timeline(detail):
            state = timestamp.strftime("%Y-%m-%d %H:%M") if timestamp else "Pending"
            st.markdown(f"**{label}**  \n{state}")

        allowed_updates = order_service.allowed_status_updates(user, selected_order)
        if allowed_updates:
            st.markdown("---")
            st.subheader("Apply status update")
            with st.form("status_update_form"):
                new_status = st.selectbox("Next status", allowed_updates)
                reason = st.text_area("Reason or operational note", height=100, placeholder="Optional unless cancelling.")
                confirm = st.checkbox("I confirm this update follows the operational handoff.")
                submit = st.form_submit_button("Apply update", type="primary")
                if submit:
                    if not confirm:
                        st.error("Please confirm the handoff before applying the update.")
                    else:
                        try:
                            order_service.update_order_status(
                                session,
                                user,
                                selected_order.id,
                                new_status,
                                reason=reason,
                            )
                            st.success("Order status updated.")
                            st.rerun()
                        except ValidationError as exc:
                            st.error(str(exc))
        else:
            st.info("No further updates are allowed from the current state.")
