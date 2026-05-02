from __future__ import annotations

import plotly.express as px
import streamlit as st

from core.database import get_session
from core.utils import currency, initialize_page, render_metric_card, render_page_header
from services import analytics_service, audit_service, order_service, product_service, warehouse_service


user = initialize_page("Admin Dashboard", icon="📈", allowed_roles=["admin"])
render_page_header(
    "Executive Control Room",
    "Monitor demand, fulfillment velocity, inventory posture, and queue health across all regions.",
    "This view aggregates every order and event in the system and exposes operational exports for downstream analysis.",
)

with get_session() as session:
    metrics_payload = analytics_service.kpis(session, user)
    low_stock = [product for product in product_service.list_products(session, include_inactive=True) if product.stock_quantity <= 10]
    metrics = st.columns(4)
    with metrics[0]:
        render_metric_card("Total Orders", f"{int(metrics_payload['orders'])}", "Current order volume across every region")
    with metrics[1]:
        render_metric_card("Revenue", currency(metrics_payload["revenue"]), "Gross order value booked into SQLite")
    with metrics[2]:
        render_metric_card("Active Pipeline", f"{int(metrics_payload['active_pipeline'])}", "Orders not yet completed")
    with metrics[3]:
        render_metric_card("Low Stock SKUs", str(len(low_stock)), "Products at or below 10 units")

    orders_trend = analytics_service.orders_over_time(session, user)
    status_mix = analytics_service.status_distribution(session, user)
    left, right = st.columns(2, gap="large")
    with left:
        if not orders_trend.empty:
            fig = px.area(
                orders_trend,
                x="created_date",
                y="orders",
                title="Orders over time",
                color_discrete_sequence=["#17624f"],
            )
            st.plotly_chart(fig, use_container_width=True)
    with right:
        if not status_mix.empty:
            fig = px.pie(
                status_mix,
                values="orders",
                names="status",
                title="Status distribution",
                hole=0.45,
            )
            st.plotly_chart(fig, use_container_width=True)

    export_cols = st.columns(3)
    order_export_path, order_export_payload = order_service.export_orders_csv(session, user)
    product_export_path, product_export_payload = product_service.export_products_json(session)
    log_export_path, log_export_payload = audit_service.export_logs_json(session)
    with export_cols[0]:
        st.download_button("Export orders.csv", data=order_export_payload, file_name=order_export_path.name, mime="text/csv")
    with export_cols[1]:
        st.download_button("Export products.json", data=product_export_payload, file_name=product_export_path.name, mime="application/json")
    with export_cols[2]:
        st.download_button("Export logs.json", data=log_export_payload, file_name=log_export_path.name, mime="application/json")

    recent_orders = order_service.list_orders(session, user, include_cancelled=True)[:10]
    queue_rows = warehouse_service.list_events(session, user, event_status="pending", limit=10)
    bottom_left, bottom_right = st.columns(2, gap="large")
    with bottom_left:
        st.subheader("Recent orders")
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
                for row in recent_orders
            ],
            use_container_width=True,
            hide_index=True,
        )
    with bottom_right:
        st.subheader("Pending warehouse events")
        st.dataframe(
            [
                {
                    "Order": row["order_number"],
                    "Event": row["event_type"],
                    "Region": row["region_label"],
                    "Order Status": row["order_status"],
                }
                for row in queue_rows
            ],
            use_container_width=True,
            hide_index=True,
        )
