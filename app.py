from __future__ import annotations

from html import escape
from textwrap import dedent

import h3
import plotly.express as px
import streamlit as st

from core import auth
from core.config import (
    DEFAULT_VIEW_BY_ROLE,
    ROLE_ADMIN,
    ROLE_CUSTOMER,
    ROLE_LABELS,
    ROLE_NAVIGATION,
    ROLE_WAREHOUSE,
)
from core.database import get_session, init_db
from core.utils import (
    ValidationError,
    configure_page,
    currency,
    format_timestamp,
    inject_styles,
    region_label,
    render_detail_grid,
    render_metric_card,
    render_page_header,
    render_section_title,
    render_status_badge,
)
from services import analytics_service, audit_service, order_service, product_service, user_service, warehouse_service


PLOTLY_CONFIG = {"displayModeBar": False, "responsive": True}
ROLE_VIEWS = {role: {item["view"] for item in items} for role, items in ROLE_NAVIGATION.items()}


def current_view() -> str:
    raw = st.query_params.get("view", "")
    if isinstance(raw, list):
        raw = raw[0] if raw else ""
    return str(raw or "")


def set_view(view: str, rerun: bool = False) -> None:
    auth.set_active_view(view)
    if rerun:
        st.rerun()


def resolve_active_view(user) -> str:
    requested = current_view()
    if not user:
        if requested and requested != "auth":
            set_view("auth", rerun=True)
        return "auth"

    default_view = DEFAULT_VIEW_BY_ROLE[user.role]
    if not requested:
        return default_view
    if requested not in ROLE_VIEWS[user.role]:
        set_view(default_view, rerun=True)
    return requested


def render_topbar(user) -> None:
    header_left, header_right = st.columns([0.8, 0.2], gap="small")
    with header_left:
        st.markdown(
            f"""
            <div class="topbar-card">
                <div class="section-kicker">Geo Furniture Ops</div>
                <div class="section-title" style="font-size:1.25rem;">Regional order management and warehouse execution</div>
                <div class="section-subtitle">{escape(user.full_name)} · {escape(ROLE_LABELS.get(user.role, "Account"))}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with header_right:
        st.markdown(
            f"""
            <div class="topbar-card" style="display:flex;flex-direction:column;gap:0.7rem;justify-content:center;min-height:100%;">
                <span class="app-chip">{escape(region_label(getattr(user, "assigned_region", None))) if user.role == ROLE_WAREHOUSE else "Enterprise scope"}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Sign out", key="topbar_logout", use_container_width=True):
            auth.logout_current_user()
            set_view("auth", rerun=True)


def render_bottom_nav(user, active_view: str) -> None:
    items = ROLE_NAVIGATION[user.role]
    st.markdown("---")
    rows = [items[index : index + 4] for index in range(0, len(items), 4)]
    for row_index, row_items in enumerate(rows):
        row_columns = st.columns(len(row_items), gap="small")
        for column, item in zip(row_columns, row_items):
            with column:
                clicked = st.button(
                    item["label"],
                    key=f"bottom_nav_{user.role}_{row_index}_{item['view']}",
                    type="primary" if item["view"] == active_view else "secondary",
                    use_container_width=True,
                )
                if clicked and item["view"] != active_view:
                    set_view(item["view"], rerun=True)


def render_shortcuts(views: list[str], role: str) -> None:
    items = [item for item in ROLE_NAVIGATION[role] if item["view"] in views]
    if not items:
        return
    shortcut_columns = st.columns(len(items), gap="small")
    active_view = current_view()
    for column, item in zip(shortcut_columns, items):
        with column:
            clicked = st.button(
                item["label"],
                key=f"shortcut_{role}_{item['view']}",
                type="primary" if item["view"] == active_view else "secondary",
                use_container_width=True,
            )
            if clicked and item["view"] != active_view:
                set_view(item["view"], rerun=True)


def render_auth_view() -> None:
    left, center, right = st.columns([1.0, 0.9, 1.0], gap="large")
    with center:
        st.markdown(
            dedent(
                """
                <div class="hero-card" style="text-align:center; margin-top:2.5rem; margin-bottom:1.25rem;">
                    <div class="page-eyebrow">Geo Furniture Ops</div>
                    <div class="page-title" style="font-size:2rem; margin-bottom:0.15rem;">Sign in</div>
                    <p class="page-subtitle">Access your workspace</p>
                </div>
                """
            ).strip(),
            unsafe_allow_html=True,
        )
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
                except Exception as exc:
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
                            role=ROLE_CUSTOMER,
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


def render_customer_overview(user) -> None:
    render_page_header(
        "Overview",
        "Account snapshot",
        "Track open orders, delivered volume, and recent activity from a single customer workspace.",
    )
    with get_session() as session:
        orders = order_service.list_orders(session, user, include_cancelled=True)
        open_orders = [row for row in orders if row["status"] not in {"Delivered", "Cancelled"}]
        delivered = [row for row in orders if row["status"] == "Delivered"]
        total_spend = sum(row["total_amount"] for row in orders)

        metrics = st.columns(4, gap="medium")
        with metrics[0]:
            render_metric_card("Orders", str(len(orders)), "Orders linked to your customer profile")
        with metrics[1]:
            render_metric_card("Open", str(len(open_orders)), "Orders still moving through fulfillment")
        with metrics[2]:
            render_metric_card("Delivered", str(len(delivered)), "Completed deliveries")
        with metrics[3]:
            render_metric_card("Spend", currency(total_spend), "Booked order value")

        left, right = st.columns([1.15, 0.85], gap="large")
        with left:
            render_section_title("Recent activity", "Latest orders", "Recent customer orders and current status.")
            recent_orders = orders[:5]
            if recent_orders:
                for row in recent_orders:
                    st.markdown(
                        f"""
                        <div class="surface-card" style="margin-bottom:0.8rem;">
                            <div style="display:flex;justify-content:space-between;gap:1rem;align-items:flex-start;">
                                <div>
                                    <div class="section-title" style="margin-bottom:0.1rem;">{escape(row["order_number"])} · {escape(row["product_name"])}</div>
                                    <div class="section-subtitle">{escape(row["address"])}</div>
                                </div>
                                <div>{render_status_badge(row["status"])}</div>
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
            else:
                st.info("No orders have been created yet.")
        with right:
            st.markdown(
                f"""
                <div class="surface-card">
                    <div class="section-kicker">Service region</div>
                    <div class="section-title">Latest delivery coverage</div>
                    <div class="section-subtitle">{escape(region_label(open_orders[0]["h3_region"])) if open_orders else "No active delivery region yet"}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            render_shortcuts(["shop", "orders", "profile"], user.role)


def render_admin_overview(user) -> None:
    render_page_header(
        "Overview",
        "Operations command center",
        "Review platform health, identify pending work, and move directly into administrative workflows.",
    )
    with get_session() as session:
        metrics_payload = analytics_service.kpis(session, user)
        low_stock = [product for product in product_service.list_products(session, include_inactive=True) if product.stock_quantity <= 10]
        queue = warehouse_service.queue_summary(session, user)
        metrics = st.columns(4, gap="medium")
        with metrics[0]:
            render_metric_card("Orders", f"{int(metrics_payload['orders'])}", "System-wide order volume")
        with metrics[1]:
            render_metric_card("Revenue", currency(metrics_payload["revenue"]), "Gross booked order value")
        with metrics[2]:
            render_metric_card("Pending events", str(queue["pending_events"]), "Warehouse intake items awaiting processing")
        with metrics[3]:
            render_metric_card("Low stock", str(len(low_stock)), "SKUs at or below 10 units")

        left, right = st.columns([1.1, 0.9], gap="large")
        with left:
            render_section_title("Recent activity", "Latest orders", "The newest commercial orders across every region.")
            recent_orders = order_service.list_orders(session, user, include_cancelled=True)[:8]
            st.dataframe(
                [
                    {
                        "Order": row["order_number"],
                        "Customer": row["customer_name"],
                        "Product": row["product_name"],
                        "Status": row["status"],
                        "Region": row["region_label"],
                    }
                    for row in recent_orders
                ],
                use_container_width=True,
                hide_index=True,
            )
        with right:
            render_section_title("Immediate focus", "Operational priorities", "Items that usually require administrative attention.")
            st.markdown(
                f"""
                <div class="surface-card" style="margin-bottom:0.8rem;">
                    <div class="section-title">Queue backlog</div>
                    <div class="section-subtitle">{queue["pending_events"]} pending warehouse events require acknowledgement.</div>
                </div>
                <div class="surface-card" style="margin-bottom:0.8rem;">
                    <div class="section-title">Inventory posture</div>
                    <div class="section-subtitle">{len(low_stock)} products are currently below the preferred stock threshold.</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            render_shortcuts(["dashboard", "orders", "catalog", "fulfillment"], user.role)


def render_warehouse_overview(user) -> None:
    render_page_header(
        "Overview",
        "Regional fulfillment control",
        "Monitor queue intake, active backlog, and service-region performance from one operational view.",
    )
    with get_session() as session:
        metrics_payload = analytics_service.kpis(session, user)
        queue = warehouse_service.queue_summary(session, user)
        active_orders = [
            row
            for row in order_service.list_orders(session, user, include_cancelled=False)
            if row["status"] != "Delivered"
        ]

        metrics = st.columns(4, gap="medium")
        with metrics[0]:
            render_metric_card("Region", region_label(user.assigned_region), "Assigned fulfillment coverage")
        with metrics[1]:
            render_metric_card("Pending events", str(queue["pending_events"]), "Queue items waiting for intake")
        with metrics[2]:
            render_metric_card("Open orders", str(len(active_orders)), "Orders not yet delivered")
        with metrics[3]:
            render_metric_card("Revenue", currency(metrics_payload["revenue"]), "Booked value within this region")

        left, right = st.columns([1.1, 0.9], gap="large")
        with left:
            render_section_title("Backlog", "Regional order queue", "Orders currently visible inside this assigned region.")
            st.dataframe(
                [
                    {
                        "Order": row["order_number"],
                        "Product": row["product_name"],
                        "Status": row["status"],
                        "City": row["city"],
                    }
                    for row in active_orders[:10]
                ],
                use_container_width=True,
                hide_index=True,
            )
        with right:
            render_section_title("Next actions", "Operational shortcuts", "Move directly into queue processing or analytics.")
            render_shortcuts(["orders", "fulfillment", "analytics", "profile"], user.role)


def render_overview_view(user) -> None:
    if user.role == ROLE_CUSTOMER:
        render_customer_overview(user)
    elif user.role == ROLE_ADMIN:
        render_admin_overview(user)
    else:
        render_warehouse_overview(user)


def render_dashboard_view(user) -> None:
    render_page_header(
        "Dashboard",
        "Executive performance",
        "Analyze order flow, queue health, and inventory pressure with an enterprise-wide management view.",
    )
    with get_session() as session:
        metrics_payload = analytics_service.kpis(session, user)
        low_stock = [product for product in product_service.list_products(session, include_inactive=True) if product.stock_quantity <= 10]
        orders_trend = analytics_service.orders_over_time(session, user)
        status_mix = analytics_service.status_distribution(session, user)

        metrics = st.columns(4, gap="medium")
        with metrics[0]:
            render_metric_card("Orders", f"{int(metrics_payload['orders'])}", "Total order volume")
        with metrics[1]:
            render_metric_card("Revenue", currency(metrics_payload["revenue"]), "Gross order value")
        with metrics[2]:
            render_metric_card("AOV", currency(metrics_payload["average_order_value"]), "Average order value")
        with metrics[3]:
            render_metric_card("Delivered", f"{metrics_payload['delivered_rate']:.1f}%", "Delivered order rate")

        charts = st.columns(2, gap="large")
        with charts[0]:
            if not orders_trend.empty:
                fig = px.area(
                    orders_trend,
                    x="created_date",
                    y="orders",
                    title="Orders over time",
                    color_discrete_sequence=["#4F46E5"],
                )
                fig.update_layout(margin=dict(l=10, r=10, t=50, b=10), paper_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)
        with charts[1]:
            if not status_mix.empty:
                fig = px.pie(
                    status_mix,
                    values="orders",
                    names="status",
                    title="Status distribution",
                    hole=0.45,
                    color_discrete_sequence=["#4F46E5", "#06B6D4", "#818CF8", "#22C55E", "#F59E0B", "#EF4444", "#A855F7"],
                )
                fig.update_layout(margin=dict(l=10, r=10, t=50, b=10), paper_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)

        lower = st.columns([0.95, 1.05], gap="large")
        with lower[0]:
            render_section_title("Inventory", "Low-stock products", "Products that may constrain new order intake.")
            st.dataframe(
                [
                    {
                        "SKU": product.sku,
                        "Product": product.name,
                        "Stock": product.stock_quantity,
                        "Category": product.category,
                    }
                    for product in low_stock
                ],
                use_container_width=True,
                hide_index=True,
            )
        with lower[1]:
            render_section_title("Exports", "Data extracts", "Download the current order, catalog, and audit datasets.")
            export_cols = st.columns(3, gap="small")
            order_export_path, order_export_payload = order_service.export_orders_csv(session, user)
            product_export_path, product_export_payload = product_service.export_products_json(session)
            log_export_path, log_export_payload = audit_service.export_logs_json(session)
            with export_cols[0]:
                st.download_button("orders.csv", data=order_export_payload, file_name=order_export_path.name, mime="text/csv", use_container_width=True)
            with export_cols[1]:
                st.download_button("products.json", data=product_export_payload, file_name=product_export_path.name, mime="application/json", use_container_width=True)
            with export_cols[2]:
                st.download_button("logs.json", data=log_export_payload, file_name=log_export_path.name, mime="application/json", use_container_width=True)


def render_shop_view(user) -> None:
    render_page_header(
        "Shop",
        "Order from the active catalog",
        "Select a product, enter validated delivery details, review the regional assignment, and submit the order after confirmation.",
    )

    if "shop_step" not in st.session_state:
        st.session_state.shop_step = 1
    if "shop_product_id" not in st.session_state:
        st.session_state.shop_product_id = None
    if "shop_draft" not in st.session_state:
        st.session_state.shop_draft = {}

    with get_session() as session:
        filters = st.columns([0.28, 0.72], gap="large")
        with filters[0]:
            selected_category = st.selectbox("Category", ["All"] + product_service.categories(session))
        with filters[1]:
            search_term = st.text_input("Search products", placeholder="Search by SKU, name, or description")

        products = product_service.list_products(session, category=selected_category, search=search_term)
        if not products:
            st.info("No active products match the current filter set.")
            return

        render_section_title("Catalog", "Available products", "Select a product to begin the order workflow.")
        product_columns = st.columns(3, gap="large")
        for index, product in enumerate(products):
            with product_columns[index % 3]:
                st.markdown(
                    f"""
                    <div class="product-card">
                        <div class="product-art">
                            <span class="product-art-badge">{escape(product.category)}</span>
                            <span class="product-art-mark">{escape(product.name[:2].upper())}</span>
                        </div>
                        <div class="section-title">{escape(product.name)}</div>
                        <div class="section-subtitle">{escape(product.material)} · {escape(product.dimensions)}</div>
                        <div style="margin-top:0.65rem;font-size:1.2rem;font-weight:800;color:#111827;">{currency(product.price)}</div>
                        <div class="mini-note" style="margin-top:0.4rem;">{escape(product.description)}</div>
                        <div class="mini-note" style="margin-top:0.65rem;">{product.stock_quantity} units available</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                if st.button("Start order", key=f"pick_product_{product.id}", type="primary", use_container_width=True):
                    st.session_state.shop_product_id = product.id
                    st.session_state.shop_step = 2
                    st.rerun()

        if not st.session_state.shop_product_id:
            return

        selected_product = product_service.get_product(session, st.session_state.shop_product_id)
        st.markdown("---")
        render_section_title("Order workflow", "Create a delivery order", "Each step validates product, address, quantity, and final confirmation.")

        progress_cols = st.columns(3, gap="medium")
        step_titles = ["1. Product selected", "2. Delivery details", "3. Review and confirm"]
        for idx, title in enumerate(step_titles, start=1):
            with progress_cols[idx - 1]:
                emphasis = " · active" if st.session_state.shop_step == idx else ""
                st.markdown(
                    f"""
                    <div class="surface-card">
                        <div class="section-title">{escape(title)}</div>
                        <div class="section-subtitle">{'Current step' if st.session_state.shop_step == idx else 'Ready'}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

        city_options = {city["name"]: city for city in order_service.city_catalog()}
        draft = st.session_state.shop_draft

        if st.session_state.shop_step == 2:
            default_city_name = draft.get("city", next(iter(city_options)))
            with st.form("shop_delivery_form", clear_on_submit=False):
                st.markdown(
                    f"""
                    <div class="surface-card" style="margin-bottom:1rem;">
                        <div class="section-title">{escape(selected_product.name)}</div>
                        <div class="section-subtitle">{escape(selected_product.category)} · {escape(selected_product.material)} · {currency(selected_product.price)}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                recipient_name = st.text_input("Recipient name", value=draft.get("recipient_name", user.full_name))
                phone = st.text_input("Phone", value=draft.get("phone", "+1 "))
                address_line1 = st.text_input("Address line 1", value=draft.get("address_line1", ""))
                address_line2 = st.text_input("Address line 2", value=draft.get("address_line2", ""))
                city_name = st.selectbox("City", list(city_options.keys()), index=list(city_options.keys()).index(default_city_name))
                city = city_options[city_name]
                postal_code = st.text_input("Postal code", value=draft.get("postal_code", ""))
                quantity = st.number_input("Quantity", min_value=1, max_value=max(selected_product.stock_quantity, 1), value=int(draft.get("quantity", 1)))
                latitude = st.number_input("Latitude", min_value=-90.0, max_value=90.0, value=float(draft.get("latitude", city["latitude"])), format="%.6f")
                longitude = st.number_input("Longitude", min_value=-180.0, max_value=180.0, value=float(draft.get("longitude", city["longitude"])), format="%.6f")
                notes = st.text_area("Delivery instructions", value=draft.get("notes", ""), height=110)
                action_cols = st.columns(3, gap="small")
                with action_cols[0]:
                    back = st.form_submit_button("Change product", use_container_width=True)
                with action_cols[2]:
                    continue_review = st.form_submit_button("Review order", type="primary", use_container_width=True)
                if back:
                    st.session_state.shop_product_id = None
                    st.session_state.shop_step = 1
                    st.rerun()
                if continue_review:
                    st.session_state.shop_draft = {
                        "recipient_name": recipient_name,
                        "phone": phone,
                        "address_line1": address_line1,
                        "address_line2": address_line2,
                        "city": city_name,
                        "state": city["state"],
                        "postal_code": postal_code,
                        "country": city["country"],
                        "quantity": int(quantity),
                        "latitude": float(latitude),
                        "longitude": float(longitude),
                        "notes": notes,
                    }
                    st.session_state.shop_step = 3
                    st.rerun()

        elif st.session_state.shop_step == 3:
            draft_region = h3.latlng_to_cell(
                st.session_state.shop_draft["latitude"],
                st.session_state.shop_draft["longitude"],
                order_service.settings.h3_resolution,
            )
            left, right = st.columns([1.08, 0.92], gap="large")
            with left:
                render_detail_grid(
                    {
                        "Product": selected_product.name,
                        "SKU": selected_product.sku,
                        "Quantity": str(st.session_state.shop_draft["quantity"]),
                        "Unit price": currency(selected_product.price),
                        "Order total": currency(selected_product.price * st.session_state.shop_draft["quantity"]),
                        "Recipient": st.session_state.shop_draft["recipient_name"],
                        "City": f"{st.session_state.shop_draft['city']}, {st.session_state.shop_draft['state']}",
                        "H3 region": draft_region,
                    }
                )
                st.markdown(
                    f"""
                    <div class="surface-card" style="margin-top:1rem;">
                        <div class="section-title">Delivery destination</div>
                        <div class="section-subtitle">{escape(st.session_state.shop_draft["address_line1"])} {escape(st.session_state.shop_draft["address_line2"])}</div>
                        <div class="section-subtitle">{escape(st.session_state.shop_draft["city"])}, {escape(st.session_state.shop_draft["state"])} {escape(st.session_state.shop_draft["postal_code"])}</div>
                        <div class="section-subtitle">Phone: {escape(st.session_state.shop_draft["phone"])}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            with right:
                with st.form("confirm_order_form", clear_on_submit=False):
                    confirm = st.checkbox("I confirm the product, quantity, address, and delivery region are correct.")
                    action_cols = st.columns(2, gap="small")
                    with action_cols[0]:
                        back = st.form_submit_button("Back", use_container_width=True)
                    with action_cols[1]:
                        create = st.form_submit_button("Create order", type="primary", use_container_width=True)
                    if back:
                        st.session_state.shop_step = 2
                        st.rerun()
                    if create:
                        if not confirm:
                            st.error("Please confirm the order details before submission.")
                        else:
                            try:
                                order = order_service.create_order(
                                    session,
                                    user,
                                    product_id=selected_product.id,
                                    quantity=st.session_state.shop_draft["quantity"],
                                    recipient_name=st.session_state.shop_draft["recipient_name"],
                                    phone=st.session_state.shop_draft["phone"],
                                    address_line1=st.session_state.shop_draft["address_line1"],
                                    address_line2=st.session_state.shop_draft["address_line2"],
                                    city=st.session_state.shop_draft["city"],
                                    state=st.session_state.shop_draft["state"],
                                    postal_code=st.session_state.shop_draft["postal_code"],
                                    country=st.session_state.shop_draft["country"],
                                    latitude=st.session_state.shop_draft["latitude"],
                                    longitude=st.session_state.shop_draft["longitude"],
                                    notes=st.session_state.shop_draft["notes"],
                                )
                                st.session_state.shop_step = 1
                                st.session_state.shop_product_id = None
                                st.session_state.shop_draft = {}
                                st.success(f"Order {order.order_number} was created.")
                                set_view("orders", rerun=True)
                            except ValidationError as exc:
                                st.error(str(exc))


def render_orders_view(user) -> None:
    render_page_header(
        "Orders",
        "Order tracking and control",
        "Review order status, inspect delivery details, and apply only the updates allowed by business rules and role scope.",
    )

    with get_session() as session:
        filter_cols = st.columns([0.24, 0.24, 0.52] if user.role != ROLE_CUSTOMER else [0.3, 0.7], gap="large")
        with filter_cols[0]:
            status_filter = st.selectbox("Status", ["All"] + order_service.settings.order_statuses)
        city_filter = "All"
        search_filter = ""
        if user.role != ROLE_CUSTOMER:
            with filter_cols[1]:
                city_filter = st.selectbox("City", ["All"] + [city["name"] for city in order_service.city_catalog()])
            with filter_cols[2]:
                search_filter = st.text_input("Search orders", placeholder="Order number, recipient, or city")
        else:
            with filter_cols[1]:
                search_filter = st.text_input("Search orders", placeholder="Order number, recipient, or city")

        rows = order_service.list_orders(
            session,
            user,
            status=status_filter,
            city=city_filter,
            search=search_filter,
            include_cancelled=True,
        )
        open_orders = [row for row in rows if row["status"] not in {"Delivered", "Cancelled"}]
        delivered_orders = [row for row in rows if row["status"] == "Delivered"]
        metrics = st.columns(4, gap="medium")
        with metrics[0]:
            render_metric_card("Visible orders", str(len(rows)), "Orders available in the current scope")
        with metrics[1]:
            render_metric_card("Open", str(len(open_orders)), "Orders still progressing through the workflow")
        with metrics[2]:
            render_metric_card("Delivered", str(len(delivered_orders)), "Orders already completed")
        with metrics[3]:
            render_metric_card("Value", currency(sum(row["total_amount"] for row in rows)), "Total value of visible orders")

        export_path, export_payload = order_service.export_orders_csv(session, user)
        st.download_button("Export orders.csv", data=export_payload, file_name=export_path.name, mime="text/csv")

        if not rows:
            st.info("No orders match the selected filters.")
            return

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

        selection_map = {f"{row['order_number']} · {row['product_name']} · {row['status']}": row["id"] for row in rows}
        selected_label = st.selectbox("Inspect order", list(selection_map.keys()))
        selected_order = order_service.get_order(session, user, selection_map[selected_label])
        detail = order_service.order_detail(session, user, selected_order.id)

        left, right = st.columns([1.08, 0.92], gap="large")
        with left:
            st.markdown(render_status_badge(detail["status"]), unsafe_allow_html=True)
            render_detail_grid(
                {
                    "Order number": detail["order_number"],
                    "Product": detail["product_name"],
                    "Customer": detail["customer_name"],
                    "Quantity": str(detail["quantity"]),
                    "Total": currency(detail["total_amount"]),
                    "Region": detail["region_label"],
                    "Destination": f"{detail['city']}, {detail['state']}",
                }
            )
            st.markdown(
                f"""
                <div class="surface-card" style="margin-top:1rem;">
                    <div class="section-title">Delivery profile</div>
                    <div class="section-subtitle">{escape(detail['recipient_name'])} · {escape(detail['phone'])}</div>
                    <div class="section-subtitle">{escape(detail['address_line1'])} {escape(detail['address_line2'])}</div>
                    <div class="section-subtitle">{escape(detail['city'])}, {escape(detail['state'])} {escape(detail['postal_code'])}</div>
                    <div class="section-subtitle">Instructions: {escape(detail['notes'] or 'No additional instructions')}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with right:
            render_section_title("Timeline", "Lifecycle progress", "Each timestamp represents a validated handoff.")
            for label, timestamp in order_service.order_timeline(detail):
                st.markdown(
                    f"""
                    <div class="surface-card" style="margin-bottom:0.65rem;">
                        <div class="section-title">{escape(label)}</div>
                        <div class="section-subtitle">{escape(format_timestamp(timestamp))}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

            allowed_updates = order_service.allowed_status_updates(user, selected_order)
            if user.role == ROLE_CUSTOMER and detail["status"] in order_service.settings.early_cancellable_statuses:
                with st.form("cancel_order_form"):
                    reason = st.text_area("Cancellation reason", height=100)
                    confirm = st.checkbox("I understand this closes the order and restores reserved stock.")
                    submitted = st.form_submit_button("Cancel order", type="primary", use_container_width=True)
                    if submitted:
                        if not confirm:
                            st.error("Please confirm the cancellation policy.")
                        else:
                            try:
                                order_service.cancel_order(session, user, detail["id"], reason or "Customer request")
                                st.success("The order was cancelled.")
                                st.rerun()
                            except ValidationError as exc:
                                st.error(str(exc))
            elif allowed_updates:
                with st.form("status_update_form"):
                    new_status = st.selectbox("Next status", allowed_updates)
                    reason = st.text_area("Operational note", height=100, placeholder="Optional unless cancelling.")
                    confirm = st.checkbox("I confirm this update matches the real operational handoff.")
                    submitted = st.form_submit_button("Apply status update", type="primary", use_container_width=True)
                    if submitted:
                        if not confirm:
                            st.error("Please confirm the status change before applying it.")
                        else:
                            try:
                                order_service.update_order_status(session, user, selected_order.id, new_status, reason=reason)
                                st.success("Order status updated.")
                                st.rerun()
                            except ValidationError as exc:
                                st.error(str(exc))


def render_catalog_view(user) -> None:
    render_page_header(
        "Catalog",
        "Inventory and product governance",
        "Maintain commercial SKUs, pricing, catalog visibility, and stock posture without losing historical order references.",
    )
    with get_session() as session:
        all_products = product_service.list_products(session, include_inactive=True)
        search_filter = st.text_input("Search products", placeholder="Search by SKU, name, or description")
        products = product_service.list_products(session, include_inactive=True, search=search_filter)

        active_products = [product for product in all_products if product.is_active]
        low_stock = [product for product in active_products if product.stock_quantity <= 10]
        metrics = st.columns(4, gap="medium")
        with metrics[0]:
            render_metric_card("Catalog SKUs", str(len(all_products)), "Total products tracked in the catalog")
        with metrics[1]:
            render_metric_card("Active", str(len(active_products)), "Products currently available for ordering")
        with metrics[2]:
            render_metric_card("Low stock", str(len(low_stock)), "Products at or below 10 units")
        with metrics[3]:
            average_price = sum(product.price for product in active_products) / len(active_products) if active_products else 0.0
            render_metric_card("Average price", currency(average_price), "Mean active product price")

        export_path, export_payload = product_service.export_products_json(session)
        st.download_button("Export products.json", data=export_payload, file_name=export_path.name, mime="application/json")
        st.dataframe(product_service.product_rows(products), use_container_width=True, hide_index=True)

        create_tab, edit_tab = st.tabs(["Create product", "Edit product"])
        with create_tab:
            with st.form("create_product_form"):
                sku = st.text_input("SKU")
                name = st.text_input("Name")
                category = st.text_input("Category")
                material = st.text_input("Material")
                dimensions = st.text_input("Dimensions")
                price = st.number_input("Price", min_value=0.01, value=499.0)
                stock_quantity = st.number_input("Stock quantity", min_value=0, value=10, step=1)
                description = st.text_area("Description", height=110)
                submit = st.form_submit_button("Create product", type="primary")
                if submit:
                    try:
                        product_service.create_product(
                            session,
                            user,
                            {
                                "sku": sku,
                                "name": name,
                                "category": category,
                                "material": material,
                                "dimensions": dimensions,
                                "price": price,
                                "stock_quantity": int(stock_quantity),
                                "description": description,
                            },
                        )
                        st.success("Product created.")
                        st.rerun()
                    except ValidationError as exc:
                        st.error(str(exc))

        with edit_tab:
            if not products:
                st.info("No products are available to edit.")
            else:
                selection_map = {f"{product.sku} · {product.name}": product.id for product in products}
                selected_label = st.selectbox("Select product", list(selection_map.keys()))
                product = product_service.get_product(session, selection_map[selected_label])
                with st.form("edit_product_form"):
                    name = st.text_input("Name", value=product.name)
                    category = st.text_input("Category", value=product.category)
                    material = st.text_input("Material", value=product.material)
                    dimensions = st.text_input("Dimensions", value=product.dimensions)
                    price = st.number_input("Price", min_value=0.01, value=float(product.price))
                    stock_quantity = st.number_input("Stock quantity", min_value=0, value=int(product.stock_quantity), step=1)
                    is_active = st.checkbox("Active in catalog", value=product.is_active)
                    description = st.text_area("Description", value=product.description, height=110)
                    submit = st.form_submit_button("Save changes", type="primary")
                    if submit:
                        try:
                            product_service.update_product(
                                session,
                                user,
                                product.id,
                                {
                                    "name": name,
                                    "category": category,
                                    "material": material,
                                    "dimensions": dimensions,
                                    "price": price,
                                    "stock_quantity": int(stock_quantity),
                                    "is_active": is_active,
                                    "description": description,
                                },
                            )
                            st.success("Product updated.")
                            st.rerun()
                        except ValidationError as exc:
                            st.error(str(exc))


def render_fulfillment_view(user) -> None:
    render_page_header(
        "Fulfillment",
        "Warehouse event processing",
        "Acknowledge incoming order events, move them into the operational pipeline, and monitor the regional backlog.",
    )
    with get_session() as session:
        summary = warehouse_service.queue_summary(session, user)
        metrics = st.columns(4, gap="medium")
        with metrics[0]:
            render_metric_card("Pending events", str(summary["pending_events"]), "Events waiting for processing")
        with metrics[1]:
            render_metric_card("Processed events", str(summary["processed_events"]), "Events already acknowledged")
        with metrics[2]:
            render_metric_card("Coverage", summary["covered_region"], "Current fulfillment visibility")
        with metrics[3]:
            active_backlog = len([row for row in order_service.list_orders(session, user, include_cancelled=False) if row["status"] != "Delivered"])
            render_metric_card("Backlog", str(active_backlog), "Orders not yet delivered")

        status_filter = st.selectbox("Queue status", ["All", "pending", "processed", "failed"])
        events = warehouse_service.list_events(session, user, event_status=status_filter, limit=200)
        st.dataframe(
            [
                {
                    "Event ID": row["id"],
                    "Order": row["order_number"],
                    "Event": row["event_type"],
                    "Region": row["region_label"],
                    "Order status": row["order_status"],
                    "Queue status": row["status"],
                }
                for row in events
            ],
            use_container_width=True,
            hide_index=True,
        )

        if events:
            selection_map = {f"#{row['id']} · {row['order_number']} · {row['status']}": row["id"] for row in events}
            selected_label = st.selectbox("Inspect queue item", list(selection_map.keys()))
            selected_event = next(row for row in events if row["id"] == selection_map[selected_label])
            left, right = st.columns([1.0, 1.0], gap="large")
            with left:
                st.markdown(
                    f"""
                    <div class="surface-card">
                        <div class="section-title">{escape(selected_event['order_number'])}</div>
                        <div class="section-subtitle">{escape(selected_event['event_type'])} · {escape(selected_event['region_label'])}</div>
                        <div class="section-subtitle">Current order status: {escape(selected_event['order_status'])}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            with right:
                if selected_event["status"] == "pending":
                    with st.form("process_event_form"):
                        confirm = st.checkbox("I confirm this order is ready for warehouse intake processing.")
                        submitted = st.form_submit_button("Process event", type="primary", use_container_width=True)
                        if submitted:
                            if not confirm:
                                st.error("Please confirm before processing this event.")
                            else:
                                processed_event = warehouse_service.process_event(session, user, selected_event["id"])
                                if processed_event.status == "failed":
                                    st.warning(processed_event.last_error or "This queue item could not be processed.")
                                else:
                                    st.success("Warehouse event processed.")
                                st.rerun()
                else:
                    st.info("This queue item has already been handled.")

        render_section_title("Backlog", "Active regional orders", "Orders still moving through the regional execution pipeline.")
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


def render_analytics_view(user) -> None:
    render_page_header(
        "Analytics",
        "Regional performance analytics",
        "Explore order density, revenue, lifecycle mix, and time-series performance across the regions visible to your role.",
    )
    with get_session() as session:
        metrics_payload = analytics_service.kpis(session, user)
        orders_region = analytics_service.orders_per_region(session, user)
        revenue_region = analytics_service.revenue_per_region(session, user)
        status_mix = analytics_service.status_distribution(session, user)
        orders_trend = analytics_service.orders_over_time(session, user)
        top_regions = analytics_service.top_regions(session, user)
        frame = analytics_service.order_dataframe(session, user)

        metric_cols = st.columns(4, gap="medium")
        with metric_cols[0]:
            render_metric_card("Orders", f"{int(metrics_payload['orders'])}", "Orders in the current analytics scope")
        with metric_cols[1]:
            render_metric_card("Revenue", currency(metrics_payload["revenue"]), "Gross order value")
        with metric_cols[2]:
            render_metric_card("AOV", currency(metrics_payload["average_order_value"]), "Average order value")
        with metric_cols[3]:
            render_metric_card("Delivered rate", f"{metrics_payload['delivered_rate']:.1f}%", "Share of delivered orders")

        top_left, top_right = st.columns(2, gap="large")
        with top_left:
            if not orders_region.empty:
                fig = px.bar(
                    orders_region,
                    x="region_label",
                    y="orders",
                    title="Orders per region",
                    color_discrete_sequence=["#4F46E5"],
                )
                fig.update_layout(margin=dict(l=10, r=10, t=50, b=10), paper_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)
        with top_right:
            if not revenue_region.empty:
                fig = px.bar(
                    revenue_region,
                    x="region_label",
                    y="revenue",
                    title="Revenue per region",
                    color_discrete_sequence=["#06B6D4"],
                )
                fig.update_layout(margin=dict(l=10, r=10, t=50, b=10), paper_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)

        middle_left, middle_right = st.columns(2, gap="large")
        with middle_left:
            if not status_mix.empty:
                fig = px.pie(
                    status_mix,
                    values="orders",
                    names="status",
                    title="Status distribution",
                    hole=0.35,
                    color_discrete_sequence=["#4F46E5", "#06B6D4", "#818CF8", "#22C55E", "#F59E0B", "#EF4444", "#A855F7"],
                )
                fig.update_layout(margin=dict(l=10, r=10, t=50, b=10), paper_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)
        with middle_right:
            if not orders_trend.empty:
                fig = px.line(
                    orders_trend,
                    x="created_date",
                    y="orders",
                    title="Orders over time",
                    markers=True,
                    color_discrete_sequence=["#4F46E5"],
                )
                fig.update_layout(margin=dict(l=10, r=10, t=50, b=10), paper_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)

        render_section_title("Regions", "Top regions", "Highest-volume regions in the current analytical scope.")
        st.dataframe(top_regions, use_container_width=True, hide_index=True)

        if not frame.empty:
            region_detail = (
                frame.groupby(["region_label", "h3_region"], as_index=False)
                .agg(orders=("order_number", "count"), revenue=("total_amount", "sum"))
                .sort_values("orders", ascending=False)
            )
            render_section_title("H3 detail", "Region reference", "Exact H3 cells and aggregate order value.")
            st.dataframe(region_detail, use_container_width=True, hide_index=True)


def render_audit_view(user) -> None:
    render_page_header(
        "Audit Trail",
        "Operational traceability",
        "Review authentication events, product changes, order state transitions, and warehouse processing records.",
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
                    "auth.register",
                    "order.created",
                    "order.status_updated",
                    "product.created",
                    "product.updated",
                    "warehouse.event_processed",
                    "warehouse.event_failed",
                    "user.profile_updated",
                    "user.password_changed",
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
        export_path, export_payload = audit_service.export_logs_json(session)
        st.download_button("Export logs.json", data=export_payload, file_name=export_path.name, mime="application/json")
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
        if logs:
            log_map = {f"{row['created_at']} · {row['actor']} · {row['action']}": row for row in logs[:100]}
            selected_label = st.selectbox("Inspect log entry", list(log_map.keys()))
            st.json(log_map[selected_label]["details"])


def render_profile_view(user) -> None:
    render_page_header(
        "Profile",
        "Account and security",
        "Maintain account information, rotate credentials, and review the access scope assigned to this user profile.",
    )
    with get_session() as session:
        current = user_service.get_user_by_id(session, user.id)
        left, right = st.columns([1.0, 1.0], gap="large")
        with left:
            render_detail_grid(
                {
                    "Full name": current.full_name,
                    "Username": current.username,
                    "Role": ROLE_LABELS.get(current.role, current.role),
                    "Assigned region": region_label(current.assigned_region),
                    "Status": "Active" if current.is_active else "Inactive",
                }
            )
            with st.form("profile_form"):
                full_name = st.text_input("Full name", value=current.full_name)
                submitted = st.form_submit_button("Save profile", type="primary", use_container_width=True)
                if submitted:
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
                submitted = st.form_submit_button("Change password", type="primary", use_container_width=True)
                if submitted:
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

        st.markdown("---")
        logout_cols = st.columns([0.32, 0.68], gap="large")
        with logout_cols[0]:
            if st.button("Sign out", use_container_width=True):
                auth.logout_current_user()
                set_view("auth", rerun=True)
        with logout_cols[1]:
            st.markdown(
                """
                <div class="surface-card">
                    <div class="section-title">Access scope</div>
                    <div class="section-subtitle">Customer accounts can place and monitor their own orders. Administrative accounts can manage catalog, analytics, audits, and all order activity. Warehouse accounts are constrained to their assigned H3 service region.</div>
                </div>
                """,
                unsafe_allow_html=True,
            )


def dispatch_view(user, active_view: str) -> None:
    if active_view == "overview":
        render_overview_view(user)
    elif active_view == "dashboard" and user.role == ROLE_ADMIN:
        render_dashboard_view(user)
    elif active_view == "shop" and user.role == ROLE_CUSTOMER:
        render_shop_view(user)
    elif active_view == "orders":
        render_orders_view(user)
    elif active_view == "catalog" and user.role == ROLE_ADMIN:
        render_catalog_view(user)
    elif active_view == "fulfillment" and user.role in {ROLE_ADMIN, ROLE_WAREHOUSE}:
        render_fulfillment_view(user)
    elif active_view == "analytics" and user.role in {ROLE_ADMIN, ROLE_WAREHOUSE}:
        render_analytics_view(user)
    elif active_view == "audit" and user.role == ROLE_ADMIN:
        render_audit_view(user)
    elif active_view == "profile":
        render_profile_view(user)
    else:
        set_view(DEFAULT_VIEW_BY_ROLE[user.role], rerun=True)


configure_page("Geo Furniture Ops", icon="🪑", sidebar_state="collapsed")
inject_styles()
init_db()

current_user = auth.get_current_user()
auth.sync_browser_session(current_user)
active_view = resolve_active_view(current_user)

if not current_user:
    render_auth_view()
else:
    render_topbar(current_user)
    dispatch_view(current_user, active_view)
    render_bottom_nav(current_user, active_view)
