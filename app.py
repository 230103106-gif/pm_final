from __future__ import annotations

import streamlit as st

from core.database import get_session
from core.utils import currency, initialize_page, render_metric_card, render_page_header, render_status_badge
from services import analytics_service, order_service, warehouse_service


user = initialize_page("Workspace Home", icon="🪑", anonymous=True)

render_page_header(
    "Operations Workspace",
    "Furniture fulfillment built around real regions, real stock, and real workflow gates.",
    "Manage customer demand, warehouse intake, and delivery lifecycle progress from a single Streamlit control plane.",
)

if not user:
    left, right = st.columns([1.2, 0.8], gap="large")
    with left:
        st.markdown(
            """
            <div class="surface-card">
                <h3 style="margin-top:0;">What this workspace includes</h3>
                <p class="mini-note">Customer ordering, order lifecycle enforcement, H3 geospatial assignment, warehouse queue processing, audit logging, exports, and role-restricted analytics.</p>
                <ul>
                    <li>Persistent SQLite storage with seeded demo data</li>
                    <li>RBAC plus region-based ABAC checks on order access</li>
                    <li>Warehouse event queue that confirms intake before downstream fulfillment</li>
                    <li>Operations dashboards and regional reporting with Plotly</li>
                </ul>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Open login", type="primary"):
            st.switch_page("pages/1_Login.py")
    with right:
        st.markdown(
            """
            <div class="surface-card">
                <h3 style="margin-top:0;">Demo credentials</h3>
                <p><strong>admin</strong> / <code>Admin@123</code></p>
                <p><strong>customer</strong> / <code>Customer@123</code></p>
                <p><strong>warehouse</strong> / <code>Warehouse@123</code></p>
            </div>
            """,
            unsafe_allow_html=True,
        )
else:
    with get_session() as session:
        if user.role == "customer":
            orders = order_service.list_orders(session, user, include_cancelled=True)
            open_orders = [row for row in orders if row["status"] not in {"Delivered", "Cancelled"}]
            delivered = [row for row in orders if row["status"] == "Delivered"]
            total_spend = sum(row["total_amount"] for row in orders)
            metrics = st.columns(4)
            with metrics[0]:
                render_metric_card("Total Orders", str(len(orders)), "Orders linked to your account")
            with metrics[1]:
                render_metric_card("Open Orders", str(len(open_orders)), "Actively moving through fulfillment")
            with metrics[2]:
                render_metric_card("Delivered", str(len(delivered)), "Completed deliveries")
            with metrics[3]:
                render_metric_card("Spend", currency(total_spend), "Lifetime value across all orders")

            recent_orders = orders[:5]
            left, right = st.columns([1.2, 0.8], gap="large")
            with left:
                st.subheader("Recent orders")
                if recent_orders:
                    for row in recent_orders:
                        st.markdown(
                            f"""
                            <div class="surface-card" style="margin-bottom:0.75rem;">
                                <div style="display:flex;justify-content:space-between;align-items:center;gap:1rem;">
                                    <div>
                                        <div style="font-weight:700;">{row['order_number']} · {row['product_name']}</div>
                                        <div class="mini-note">{row['address']}</div>
                                    </div>
                                    <div>{render_status_badge(row['status'])}</div>
                                </div>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )
                else:
                    st.info("No orders yet. Start with the shop to create your first request.")
            with right:
                st.subheader("Next actions")
                st.page_link("pages/2_Shop.py", label="Create a new order", icon="🛒")
                st.page_link("pages/3_My_Orders.py", label="Review existing orders", icon="📋")
        else:
            metrics_payload = analytics_service.kpis(session, user)
            queue = warehouse_service.queue_summary(session, user)
            metrics = st.columns(4)
            with metrics[0]:
                render_metric_card("Orders", f"{int(metrics_payload['orders'])}", "Orders in current operational scope")
            with metrics[1]:
                render_metric_card("Revenue", currency(metrics_payload["revenue"]), "Gross order value")
            with metrics[2]:
                render_metric_card("Open Pipeline", f"{int(metrics_payload['active_pipeline'])}", "Orders not yet completed")
            with metrics[3]:
                render_metric_card("Pending Events", f"{int(metrics_payload['pending_events'])}", queue["covered_region"])

            orders = order_service.list_orders(session, user, include_cancelled=True)[:8]
            events = warehouse_service.list_events(session, user, event_status="pending", limit=8)
            left, right = st.columns(2, gap="large")
            with left:
                st.subheader("Recent orders")
                if orders:
                    st.dataframe(
                        [
                            {
                                "Order": row["order_number"],
                                "Customer": row["customer_name"],
                                "Product": row["product_name"],
                                "Status": row["status"],
                                "Region": row["region_label"],
                            }
                            for row in orders
                        ],
                        use_container_width=True,
                        hide_index=True,
                    )
                else:
                    st.info("No orders available yet.")
            with right:
                st.subheader("Queue snapshot")
                if events:
                    st.dataframe(
                        [
                            {
                                "Order": row["order_number"],
                                "Event": row["event_type"],
                                "Region": row["region_label"],
                                "Status": row["status"],
                            }
                            for row in events
                        ],
                        use_container_width=True,
                        hide_index=True,
                    )
                else:
                    st.success("No pending warehouse events right now.")

            st.subheader("Workspace shortcuts")
            if user.role == "admin":
                cols = st.columns(4)
                with cols[0]:
                    st.page_link("pages/4_Admin_Dashboard.py", label="Dashboard", icon="📈")
                with cols[1]:
                    st.page_link("pages/5_Order_Management.py", label="Orders", icon="📦")
                with cols[2]:
                    st.page_link("pages/7_Warehouse.py", label="Warehouse", icon="🏭")
                with cols[3]:
                    st.page_link("pages/8_Analytics.py", label="Analytics", icon="🗺️")
            else:
                cols = st.columns(3)
                with cols[0]:
                    st.page_link("pages/5_Order_Management.py", label="Regional Orders", icon="📦")
                with cols[1]:
                    st.page_link("pages/7_Warehouse.py", label="Warehouse Queue", icon="🏭")
                with cols[2]:
                    st.page_link("pages/8_Analytics.py", label="Regional Analytics", icon="🗺️")
