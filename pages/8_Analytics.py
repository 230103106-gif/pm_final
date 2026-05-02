from __future__ import annotations

import plotly.express as px
import streamlit as st

from core.database import get_session
from core.utils import currency, initialize_page, render_metric_card, render_page_header
from services import analytics_service


user = initialize_page("Analytics", icon="🗺️", allowed_roles=["admin", "warehouse_manager"])
render_page_header(
    "Regional Analytics",
    "Analyze order density, fulfillment mix, and revenue patterns across H3 service regions.",
    "Charts are automatically scoped to the actor's accessible geography, keeping regional warehouse data fenced.",
)

with get_session() as session:
    metrics_payload = analytics_service.kpis(session, user)
    metric_cols = st.columns(4)
    with metric_cols[0]:
        render_metric_card("Orders", f"{int(metrics_payload['orders'])}", "Orders in current analytics scope")
    with metric_cols[1]:
        render_metric_card("Revenue", currency(metrics_payload["revenue"]), "Gross order value by accessible region")
    with metric_cols[2]:
        render_metric_card("AOV", currency(metrics_payload["average_order_value"]), "Average order value")
    with metric_cols[3]:
        render_metric_card("Delivered Rate", f"{metrics_payload['delivered_rate']:.1f}%", "Share of delivered orders")

    orders_region = analytics_service.orders_per_region(session, user)
    revenue_region = analytics_service.revenue_per_region(session, user)
    status_mix = analytics_service.status_distribution(session, user)
    orders_trend = analytics_service.orders_over_time(session, user)
    top_regions = analytics_service.top_regions(session, user)
    frame = analytics_service.order_dataframe(session, user)

    top_left, top_right = st.columns(2, gap="large")
    with top_left:
        if not orders_region.empty:
            fig = px.bar(
                orders_region,
                x="region_label",
                y="orders",
                title="Orders per H3 region",
                color_discrete_sequence=["#17624f"],
            )
            st.plotly_chart(fig, use_container_width=True)
    with top_right:
        if not revenue_region.empty:
            fig = px.bar(
                revenue_region,
                x="region_label",
                y="revenue",
                title="Revenue per region",
                color_discrete_sequence=["#ad7d4b"],
            )
            st.plotly_chart(fig, use_container_width=True)

    mid_left, mid_right = st.columns(2, gap="large")
    with mid_left:
        if not status_mix.empty:
            fig = px.pie(status_mix, values="orders", names="status", title="Status distribution", hole=0.35)
            st.plotly_chart(fig, use_container_width=True)
    with mid_right:
        if not orders_trend.empty:
            fig = px.line(
                orders_trend,
                x="created_date",
                y="orders",
                title="Orders over time",
                markers=True,
                color_discrete_sequence=["#155eef"],
            )
            st.plotly_chart(fig, use_container_width=True)

    st.subheader("Top regions")
    st.dataframe(top_regions, use_container_width=True, hide_index=True)

    if not frame.empty:
        st.subheader("H3 region detail")
        region_detail = (
            frame.groupby(["region_label", "h3_region"], as_index=False)
            .agg(orders=("order_number", "count"), revenue=("total_amount", "sum"))
            .sort_values("orders", ascending=False)
        )
        st.dataframe(region_detail, use_container_width=True, hide_index=True)
