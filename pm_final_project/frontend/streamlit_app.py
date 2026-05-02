from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import h3
import pandas as pd
import plotly.express as px
import requests
import streamlit as st
import streamlit.components.v1 as components

LOCAL_API_URL = "http://127.0.0.1:8000"
ENV_API_URL = os.getenv("API_BASE_URL", "").strip().rstrip("/")
AUTO_START_LOCAL_API = os.getenv("AUTO_START_LOCAL_API", "true").lower() == "true"
H3_RESOLUTION = int(os.getenv("H3_RESOLUTION", "5"))

st.set_page_config(
    page_title="Geo-Optimized Furniture OMS",
    layout="wide",
    initial_sidebar_state="expanded",
)


class ApiError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def ensure_session_defaults() -> None:
    st.session_state.setdefault("auth_token", "")
    st.session_state.setdefault("user", None)
    st.session_state.setdefault("theme", "light")
    st.session_state.setdefault("last_notification_id", "")


def health_check(base_url: str) -> bool:
    try:
        response = requests.get(f"{base_url}/health", timeout=1.2)
        return response.ok
    except requests.RequestException:
        return False


def ensure_local_api_server() -> bool:
    if health_check(LOCAL_API_URL):
        return True
    if not AUTO_START_LOCAL_API:
        return False

    api_process = st.session_state.get("api_process")
    if api_process is not None and api_process.poll() is None:
        return wait_for_local_api()

    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
        "--log-level",
        "warning",
    ]
    st.session_state["api_process"] = subprocess.Popen(
        command,
        cwd=ROOT_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return wait_for_local_api()


def wait_for_local_api() -> bool:
    for _ in range(12):
        if health_check(LOCAL_API_URL):
            return True
        time.sleep(0.5)
    return False


@st.cache_resource(show_spinner=False)
def get_inprocess_client():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    client.__enter__()
    return client


def get_backend_mode() -> tuple[str, str | None]:
    if ENV_API_URL and health_check(ENV_API_URL):
        return "http", ENV_API_URL
    if ENV_API_URL and not health_check(ENV_API_URL):
        return "inprocess", None
    if ensure_local_api_server():
        return "http", LOCAL_API_URL
    return "inprocess", None


def api_request(
    method: str,
    path: str,
    *,
    auth_required: bool = True,
    json: dict | None = None,
    params: dict | None = None,
):
    headers: dict[str, str] = {}
    token = st.session_state.get("auth_token", "")
    if auth_required and token:
        headers["Authorization"] = f"Bearer {token}"

    mode, base_url = get_backend_mode()
    try:
        if mode == "http" and base_url:
            response = requests.request(
                method=method,
                url=f"{base_url}{path}",
                headers=headers,
                json=json,
                params=params,
                timeout=8,
            )
        else:
            response = get_inprocess_client().request(
                method=method,
                url=path,
                headers=headers,
                json=json,
                params=params,
            )
    except requests.RequestException as exc:
        raise ApiError(f"Could not reach the backend service: {exc}") from exc

    content_type = response.headers.get("content-type", "")
    payload = response.json() if "application/json" in content_type else response.text

    if response.status_code >= 400:
        if isinstance(payload, dict):
            message = payload.get("detail", "The request failed.")
        else:
            message = str(payload)
        raise ApiError(message, response.status_code)

    return payload


def clear_auth_state() -> None:
    st.session_state["auth_token"] = ""
    st.session_state["user"] = None


def apply_theme(theme: str) -> None:
    colors = {
        "light": {
            "bg": "#f4f0e8",
            "panel": "#fffaf2",
            "card": "rgba(255, 250, 242, 0.88)",
            "text": "#13263c",
            "muted": "#5d6d7d",
            "accent": "#0f766e",
            "accent_alt": "#c17b2c",
            "border": "rgba(19, 38, 60, 0.10)",
            "shadow": "0 24px 60px rgba(15, 35, 53, 0.10)",
            "hero": "linear-gradient(135deg, rgba(250, 239, 214, 0.96), rgba(228, 244, 239, 0.92))",
        },
        "dark": {
            "bg": "#0f1b2d",
            "panel": "#122338",
            "card": "rgba(18, 35, 56, 0.92)",
            "text": "#edf5ff",
            "muted": "#a6bdcf",
            "accent": "#34d399",
            "accent_alt": "#f3b562",
            "border": "rgba(237, 245, 255, 0.10)",
            "shadow": "0 24px 60px rgba(3, 7, 18, 0.35)",
            "hero": "linear-gradient(135deg, rgba(17, 33, 52, 0.96), rgba(10, 72, 69, 0.90))",
        },
    }[theme]

    st.markdown(
        f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;600;700;800&family=Space+Grotesk:wght@500;700&display=swap');

        :root {{
            --app-bg: {colors["bg"]};
            --panel-bg: {colors["panel"]};
            --card-bg: {colors["card"]};
            --text-color: {colors["text"]};
            --muted-color: {colors["muted"]};
            --accent-color: {colors["accent"]};
            --accent-alt: {colors["accent_alt"]};
            --border-color: {colors["border"]};
            --hero-bg: {colors["hero"]};
            --shadow: {colors["shadow"]};
        }}

        html, body, [data-testid="stAppViewContainer"], [data-testid="stApp"] {{
            background:
                radial-gradient(circle at top left, rgba(193, 123, 44, 0.08), transparent 32%),
                radial-gradient(circle at top right, rgba(15, 118, 110, 0.12), transparent 26%),
                var(--app-bg);
            color: var(--text-color);
            font-family: "Manrope", sans-serif;
        }}

        [data-testid="stSidebar"] {{
            background: linear-gradient(180deg, rgba(11, 28, 45, 0.96), rgba(14, 59, 63, 0.94));
            color: #f8fbff;
            border-right: 1px solid rgba(255, 255, 255, 0.08);
        }}

        [data-testid="stSidebar"] * {{
            color: #f8fbff !important;
            font-family: "Manrope", sans-serif;
        }}

        .block-container {{
            padding-top: 2rem;
            padding-bottom: 2.5rem;
        }}

        .hero-shell {{
            background: var(--hero-bg);
            border: 1px solid var(--border-color);
            border-radius: 28px;
            padding: 2.2rem;
            box-shadow: var(--shadow);
            margin-bottom: 1.4rem;
            overflow: hidden;
            position: relative;
        }}

        .hero-shell::after {{
            content: "";
            position: absolute;
            inset: auto -80px -90px auto;
            width: 220px;
            height: 220px;
            border-radius: 999px;
            background: rgba(15, 118, 110, 0.15);
            filter: blur(10px);
        }}

        .eyebrow {{
            text-transform: uppercase;
            letter-spacing: 0.18em;
            font-size: 0.78rem;
            color: var(--accent-color);
            font-weight: 800;
            margin-bottom: 0.6rem;
        }}

        .hero-title, .section-title {{
            font-family: "Space Grotesk", sans-serif;
            color: var(--text-color);
            line-height: 1.05;
            margin: 0;
        }}

        .hero-title {{
            font-size: clamp(2.2rem, 5vw, 4rem);
            max-width: 820px;
        }}

        .section-title {{
            font-size: 1.5rem;
            margin-bottom: 0.35rem;
        }}

        .hero-text, .muted-copy {{
            color: var(--muted-color);
            font-size: 1rem;
            line-height: 1.7;
        }}

        .glass-card {{
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 22px;
            padding: 1.15rem 1.2rem;
            box-shadow: var(--shadow);
            animation: floatIn 0.45s ease-out;
        }}

        .metric-card {{
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 24px;
            padding: 1.2rem 1.25rem;
            box-shadow: var(--shadow);
            min-height: 150px;
            animation: liftIn 0.55s ease-out;
        }}

        .metric-label {{
            color: var(--muted-color);
            font-size: 0.85rem;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            font-weight: 700;
        }}

        .metric-value {{
            font-family: "Space Grotesk", sans-serif;
            font-size: 2rem;
            color: var(--text-color);
            margin: 0.4rem 0;
        }}

        .metric-subtitle {{
            color: var(--muted-color);
            font-size: 0.92rem;
        }}

        .pill-row {{
            display: flex;
            flex-wrap: wrap;
            gap: 0.6rem;
            margin-top: 1rem;
        }}

        .pill {{
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            background: rgba(15, 118, 110, 0.10);
            color: var(--text-color);
            border: 1px solid rgba(15, 118, 110, 0.12);
            border-radius: 999px;
            padding: 0.55rem 0.85rem;
            font-size: 0.88rem;
            font-weight: 700;
        }}

        .credential-card {{
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 24px;
            padding: 1.1rem;
            box-shadow: var(--shadow);
            min-height: 160px;
        }}

        .credential-role {{
            font-family: "Space Grotesk", sans-serif;
            font-size: 1.15rem;
            margin-bottom: 0.55rem;
            color: var(--text-color);
        }}

        .notify-card {{
            background: linear-gradient(135deg, rgba(15, 118, 110, 0.14), rgba(193, 123, 44, 0.14));
            border: 1px solid var(--border-color);
            border-radius: 18px;
            padding: 0.95rem 1rem;
            margin-bottom: 0.7rem;
        }}

        .sidebar-brand {{
            font-family: "Space Grotesk", sans-serif;
            font-size: 1.3rem;
            font-weight: 700;
            margin-bottom: 0.2rem;
        }}

        .sidebar-sub {{
            color: rgba(248, 251, 255, 0.78);
            font-size: 0.92rem;
            line-height: 1.6;
        }}

        .stButton > button, .stDownloadButton > button {{
            border-radius: 999px;
            border: 0;
            background: linear-gradient(135deg, var(--accent-color), var(--accent-alt));
            color: white !important;
            font-weight: 700;
            padding: 0.65rem 1.15rem;
            box-shadow: 0 14px 28px rgba(15, 118, 110, 0.24);
        }}

        .stTextInput input, .stNumberInput input, .stSelectbox div[data-baseweb="select"],
        .stTextArea textarea, .stDateInput input {{
            border-radius: 16px !important;
        }}

        [data-testid="stMetricValue"] {{
            font-family: "Space Grotesk", sans-serif;
        }}

        [data-testid="stDataFrame"] {{
            border-radius: 18px;
            overflow: hidden;
        }}

        @keyframes liftIn {{
            from {{
                transform: translateY(14px);
                opacity: 0;
            }}
            to {{
                transform: translateY(0);
                opacity: 1;
            }}
        }}

        @keyframes floatIn {{
            from {{
                transform: scale(0.985);
                opacity: 0;
            }}
            to {{
                transform: scale(1);
                opacity: 1;
            }}
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_metric_card(title: str, value: str, subtitle: str) -> None:
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label">{title}</div>
            <div class="metric-value">{value}</div>
            <div class="metric-subtitle">{subtitle}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def display_api_error(error: ApiError) -> None:
    if error.status_code == 401:
        clear_auth_state()
        st.warning("Your session expired. Please sign in again.")
        st.rerun()
    st.error(str(error))


def render_sidebar():
    with st.sidebar:
        st.markdown('<div class="sidebar-brand">Geo Furniture OMS</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="sidebar-sub">H3-driven order routing, audit visibility, and role-aware control panels.</div>',
            unsafe_allow_html=True,
        )
        st.divider()

        dark_mode = st.toggle(
            "Dark mode",
            value=st.session_state["theme"] == "dark",
            help="Switch the interface appearance for demos or different lighting.",
        )
        st.session_state["theme"] = "dark" if dark_mode else "light"

        user = st.session_state.get("user")
        if not user:
            return None

        st.markdown("### Session")
        st.write(f"**Name:** {user['full_name']}")
        st.write(f"**Role:** {user['role'].title()}")
        if user.get("allowed_region"):
            st.caption(f"Allowed H3 region: {user['allowed_region']}")

        role_pages = {
            "admin": ["Overview", "Orders", "Create Order", "Audit Logs", "API Docs"],
            "customer": ["Overview", "Orders", "Create Order"],
            "warehouse": ["Overview", "Orders"],
        }
        page = st.radio("Navigation", role_pages[user["role"]], label_visibility="visible")
        st.divider()
        if st.button("Logout", use_container_width=True):
            try:
                api_request("POST", "/logout", auth_required=True)
            except ApiError:
                pass
            clear_auth_state()
            st.rerun()
        return page


def render_landing_page() -> None:
    st.markdown(
        """
        <section class="hero-shell">
            <div class="eyebrow">Capstone-ready smart logistics</div>
            <h1 class="hero-title">Geo-Optimized Furniture Order Management System</h1>
            <p class="hero-text">
                A polished public-facing platform that combines FastAPI, Streamlit,
                SQLite, SQLAlchemy, H3 geospatial indexing, analytics, and event-driven
                warehouse notifications into one cohesive experience.
            </p>
            <div class="pill-row">
                <span class="pill">H3 regional grouping</span>
                <span class="pill">RBAC + ABAC controls</span>
                <span class="pill">Plotly analytics</span>
                <span class="pill">Queue-driven notifications</span>
                <span class="pill">Audit-ready operations</span>
            </div>
        </section>
        """,
        unsafe_allow_html=True,
    )

    left, right = st.columns([1.45, 1], gap="large")
    with left:
        st.markdown('<h2 class="section-title">What makes this project stand out</h2>', unsafe_allow_html=True)
        st.markdown(
            """
            <div class="glass-card">
                <p class="muted-copy">
                    Orders are automatically converted into H3 hexagonal regions, which
                    lets the warehouse team monitor geography-aware demand, revenue, and
                    operational workload. Each role sees a focused dashboard instead of a
                    generic admin screen.
                </p>
                <p class="muted-copy">
                    The backend records every critical action, while a background queue
                    simulates warehouse notifications as soon as new orders are created.
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown('<h2 class="section-title">Demo access</h2>', unsafe_allow_html=True)
        creds_cols = st.columns(3, gap="medium")
        credentials = [
            ("Admin", "admin", "admin123", "Full system access, audit logs, and global analytics."),
            ("Customer", "customer", "customer123", "Place furniture orders and manage your own requests."),
            ("Warehouse", "warehouse", "warehouse123", "See regional H3-assigned orders only."),
        ]
        for col, (role, username, password, description) in zip(creds_cols, credentials, strict=True):
            with col:
                st.markdown(
                    f"""
                    <div class="credential-card">
                        <div class="credential-role">{role}</div>
                        <p class="muted-copy"><strong>Username:</strong> {username}<br>
                        <strong>Password:</strong> {password}</p>
                        <p class="muted-copy">{description}</p>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

    with right:
        st.markdown('<h2 class="section-title">Sign in</h2>', unsafe_allow_html=True)
        with st.form("login_form", clear_on_submit=False):
            username = st.text_input("Username", placeholder="admin")
            password = st.text_input("Password", type="password", placeholder="Enter your password")
            submitted = st.form_submit_button("Access Dashboard", use_container_width=True)

        if submitted:
            try:
                payload = api_request(
                    "POST",
                    "/login",
                    auth_required=False,
                    json={"username": username, "password": password},
                )
                st.session_state["auth_token"] = payload["token"]
                st.session_state["user"] = payload["user"]
                st.success("Login successful. Redirecting to your dashboard...")
                st.rerun()
            except ApiError as error:
                st.error(str(error))

        mode, base_url = get_backend_mode()
        backend_label = "HTTP API" if mode == "http" else "In-process API"
        target_text = base_url or "embedded TestClient"
        st.caption(f"Backend mode: {backend_label} ({target_text})")


def fetch_orders_for_page(search: str, status_filter: str, region: str) -> list[dict]:
    params: dict[str, str] = {}
    if search:
        params["search"] = search
    if status_filter != "All":
        params["status"] = status_filter
    if region:
        params["region"] = region
    return api_request("GET", "/orders", params=params)


def dataframe_to_csv_bytes(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=False).encode("utf-8")


def render_notifications(notifications: list[dict]) -> None:
    if not notifications:
        return
    st.markdown('<h2 class="section-title">Live notifications</h2>', unsafe_allow_html=True)
    for item in notifications[:4]:
        st.markdown(
            f"""
            <div class="notify-card">
                <strong>{item["message"]}</strong><br>
                <span class="muted-copy">Region: {item["region"]} | Created: {item["created_at"]}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )


def maybe_toast_notification(notifications: list[dict]) -> None:
    if not notifications:
        return
    latest_id = notifications[0]["id"]
    if latest_id != st.session_state.get("last_notification_id"):
        st.session_state["last_notification_id"] = latest_id
        st.toast(notifications[0]["message"])


def render_dashboard(user: dict) -> None:
    try:
        analytics = api_request("GET", "/analytics")
        notifications = api_request("GET", "/notifications")
    except ApiError as error:
        display_api_error(error)
        return

    maybe_toast_notification(notifications)

    st.markdown(
        f"""
        <section class="hero-shell">
            <div class="eyebrow">{user["role"].title()} workspace</div>
            <h1 class="hero-title">Operational clarity across furniture orders and H3 delivery regions.</h1>
            <p class="hero-text">
                Welcome back, {user["full_name"]}. This dashboard blends live order flow,
                geographic segmentation, and revenue intelligence in one view.
            </p>
        </section>
        """,
        unsafe_allow_html=True,
    )

    summary = analytics["summary"]
    metric_cols = st.columns(4, gap="medium")
    with metric_cols[0]:
        render_metric_card("Total Orders", str(summary["total_orders"]), "Scoped to your permissions")
    with metric_cols[1]:
        render_metric_card("Revenue", f"${summary['total_revenue']:,.0f}", "Calculated from quantity x unit price")
    with metric_cols[2]:
        render_metric_card("Pending", str(summary["pending_orders"]), "Orders waiting on processing")
    with metric_cols[3]:
        delivered = summary["delivered_orders"]
        note = "Completed deliveries"
        if user["role"] == "warehouse" and summary.get("warehouse_region"):
            note = f"Assigned region: {summary['warehouse_region']}"
        render_metric_card("Delivered", str(delivered), note)

    render_notifications(notifications)

    orders_by_status = pd.DataFrame(analytics["orders_by_status"])
    orders_by_region = pd.DataFrame(analytics["orders_by_region"])
    revenue_by_region = pd.DataFrame(analytics["revenue_by_region"])
    daily_trend = pd.DataFrame(analytics["daily_orders_trend"])
    top_products = pd.DataFrame(analytics["top_products"])
    region_rollup = pd.DataFrame(analytics["region_rollup"])
    map_points = pd.DataFrame(analytics["map_points"])

    template = "plotly_dark" if st.session_state["theme"] == "dark" else "plotly_white"

    chart_col_1, chart_col_2 = st.columns(2, gap="large")
    with chart_col_1:
        st.markdown('<h2 class="section-title">Orders by status</h2>', unsafe_allow_html=True)
        if not orders_by_status.empty:
            fig = px.pie(
                orders_by_status,
                names="status",
                values="orders",
                hole=0.56,
                template=template,
                color_discrete_sequence=["#0f766e", "#2f9e8f", "#c17b2c", "#f0b75a", "#7f8c8d"],
            )
            fig.update_layout(margin=dict(l=0, r=0, t=20, b=0))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No status analytics yet.")

    with chart_col_2:
        st.markdown('<h2 class="section-title">Daily order trend</h2>', unsafe_allow_html=True)
        if not daily_trend.empty:
            fig = px.line(
                daily_trend,
                x="created_date",
                y="orders",
                markers=True,
                template=template,
                color_discrete_sequence=["#c17b2c"],
            )
            fig.update_layout(margin=dict(l=0, r=0, t=20, b=0))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No order trend data available yet.")

    chart_col_3, chart_col_4 = st.columns(2, gap="large")
    with chart_col_3:
        st.markdown('<h2 class="section-title">Revenue by region</h2>', unsafe_allow_html=True)
        if not revenue_by_region.empty:
            fig = px.bar(
                revenue_by_region,
                x="h3_region",
                y="revenue",
                template=template,
                color="revenue",
                color_continuous_scale=["#0f766e", "#c17b2c"],
            )
            fig.update_layout(margin=dict(l=0, r=0, t=20, b=0), coloraxis_showscale=False)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No revenue by region data available yet.")

    with chart_col_4:
        st.markdown('<h2 class="section-title">Top furniture products</h2>', unsafe_allow_html=True)
        if not top_products.empty:
            fig = px.bar(
                top_products,
                x="product_type",
                y="quantity",
                template=template,
                color="quantity",
                color_continuous_scale=["#a7f3d0", "#0f766e"],
            )
            fig.update_layout(margin=dict(l=0, r=0, t=20, b=0), coloraxis_showscale=False)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No product analytics available yet.")

    map_col, table_col = st.columns([1.2, 1], gap="large")
    with map_col:
        st.markdown('<h2 class="section-title">Delivery geography</h2>', unsafe_allow_html=True)
        if not map_points.empty:
            fig = px.scatter_mapbox(
                map_points,
                lat="latitude",
                lon="longitude",
                color="status",
                size="quantity",
                hover_name="product_type",
                hover_data={
                    "customer_name": True,
                    "h3_region": True,
                    "total_amount": ":.2f",
                    "latitude": False,
                    "longitude": False,
                },
                zoom=3.5,
                height=430,
                mapbox_style="carto-positron",
            )
            fig.update_layout(margin=dict(l=0, r=0, t=20, b=0))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Create an order to populate the live map.")

    with table_col:
        st.markdown('<h2 class="section-title">Hex region rollup</h2>', unsafe_allow_html=True)
        if not region_rollup.empty:
            display_frame = region_rollup.rename(
                columns={
                    "h3_region": "H3 Region",
                    "orders": "Orders",
                    "customers": "Customers",
                    "revenue": "Revenue",
                }
            )
            st.dataframe(display_frame, use_container_width=True, hide_index=True)
            st.download_button(
                "Download region report",
                dataframe_to_csv_bytes(display_frame),
                "region_rollup.csv",
                "text/csv",
                use_container_width=True,
            )
        else:
            st.info("No region summary available.")


def render_orders_page(user: dict) -> None:
    st.markdown('<h1 class="section-title">Orders workspace</h1>', unsafe_allow_html=True)
    st.markdown(
        '<p class="muted-copy">Search, review, update, and export orders within your permission scope.</p>',
        unsafe_allow_html=True,
    )

    filter_cols = st.columns([1.2, 0.8, 1], gap="medium")
    search = filter_cols[0].text_input("Search orders", placeholder="Order ID, product, customer, or H3 region")
    status_filter = filter_cols[1].selectbox(
        "Status",
        ["All", "Pending", "Processing", "Shipped", "Delivered", "Cancelled"],
    )
    region = ""
    if user["role"] == "admin":
        region = filter_cols[2].text_input("Filter by H3 region", placeholder="Optional region hex")
    else:
        filter_cols[2].text_input(
            "Scoped region",
            value=user.get("allowed_region", "Your own orders"),
            disabled=True,
        )

    try:
        orders = fetch_orders_for_page(search, status_filter, region)
    except ApiError as error:
        display_api_error(error)
        return

    orders_df = pd.DataFrame(orders)
    if not orders_df.empty:
        orders_df["created_at"] = pd.to_datetime(orders_df["created_at"]).dt.strftime("%Y-%m-%d %H:%M")
        orders_df["updated_at"] = pd.to_datetime(orders_df["updated_at"]).dt.strftime("%Y-%m-%d %H:%M")

    summary_cols = st.columns(3, gap="medium")
    visible_revenue = float(orders_df["total_amount"].sum()) if not orders_df.empty else 0.0
    unique_regions = int(orders_df["h3_region"].nunique()) if not orders_df.empty else 0
    with summary_cols[0]:
        render_metric_card("Visible Orders", str(len(orders_df)), "Filtered result set")
    with summary_cols[1]:
        render_metric_card("Visible Revenue", f"${visible_revenue:,.0f}", "For the current filters")
    with summary_cols[2]:
        subtitle = "Unique H3 cells in view"
        if user["role"] == "warehouse":
            subtitle = "ABAC-limited regional view"
        render_metric_card("Regions", str(unique_regions), subtitle)

    if orders_df.empty:
        st.info("No orders matched the current filters.")
        return

    display_frame = orders_df.rename(
        columns={
            "id": "Order ID",
            "customer_name": "Customer",
            "product_type": "Product",
            "quantity": "Quantity",
            "price": "Unit Price",
            "total_amount": "Total",
            "latitude": "Latitude",
            "longitude": "Longitude",
            "h3_region": "H3 Region",
            "status": "Status",
            "created_at": "Created",
            "updated_at": "Updated",
        }
    )
    st.dataframe(display_frame, use_container_width=True, hide_index=True)
    st.download_button(
        "Download visible orders",
        dataframe_to_csv_bytes(display_frame),
        "orders_report.csv",
        "text/csv",
        use_container_width=False,
    )

    detail_options = {f"Order #{row['id']} - {row['product_type']}": row for row in orders}
    selected_label = st.selectbox("Inspect an order", list(detail_options.keys()))
    selected_order = detail_options[selected_label]

    info_col, action_col = st.columns([1.05, 0.95], gap="large")
    with info_col:
        st.markdown(
            f"""
            <div class="glass-card">
                <h3 class="section-title">Order #{selected_order["id"]}</h3>
                <p class="muted-copy">
                    <strong>Customer:</strong> {selected_order["customer_name"]}<br>
                    <strong>Product:</strong> {selected_order["product_type"]}<br>
                    <strong>Quantity:</strong> {selected_order["quantity"]}<br>
                    <strong>Unit Price:</strong> ${selected_order["price"]:,.2f}<br>
                    <strong>Total:</strong> ${selected_order["total_amount"]:,.2f}<br>
                    <strong>Status:</strong> {selected_order["status"]}<br>
                    <strong>H3 Region:</strong> {selected_order["h3_region"]}<br>
                    <strong>Coordinates:</strong> {selected_order["latitude"]}, {selected_order["longitude"]}
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        map_frame = pd.DataFrame([selected_order])
        fig = px.scatter_mapbox(
            map_frame,
            lat="latitude",
            lon="longitude",
            size="quantity",
            color="status",
            hover_name="product_type",
            hover_data={"h3_region": True, "customer_name": True, "latitude": False, "longitude": False},
            zoom=5.3,
            height=320,
            mapbox_style="carto-positron",
        )
        fig.update_layout(margin=dict(l=0, r=0, t=20, b=0))
        st.plotly_chart(fig, use_container_width=True)

    with action_col:
        if user["role"] in {"admin", "warehouse"}:
            st.markdown('<h2 class="section-title">Update status</h2>', unsafe_allow_html=True)
            allowed_statuses = ["Pending", "Processing", "Shipped", "Delivered", "Cancelled"]
            if user["role"] == "warehouse":
                allowed_statuses = ["Pending", "Processing", "Shipped", "Delivered"]
            if selected_order["status"] not in allowed_statuses:
                allowed_statuses = [selected_order["status"], *allowed_statuses]

            with st.form(f"status_form_{selected_order['id']}"):
                new_status = st.selectbox("New status", allowed_statuses, index=allowed_statuses.index(selected_order["status"]))
                submitted = st.form_submit_button("Apply update", use_container_width=True)
            if submitted:
                try:
                    api_request(
                        "PATCH",
                        f"/orders/{selected_order['id']}",
                        json={"status": new_status},
                    )
                    st.success("Order status updated successfully.")
                    st.rerun()
                except ApiError as error:
                    st.error(str(error))

        if user["role"] == "admin":
            st.markdown('<h2 class="section-title">Admin edit</h2>', unsafe_allow_html=True)
            with st.expander("Edit price, quantity, or coordinates"):
                with st.form(f"admin_edit_{selected_order['id']}"):
                    edit_product = st.text_input("Product type", value=selected_order["product_type"])
                    edit_quantity = st.number_input("Quantity", min_value=1, max_value=500, value=int(selected_order["quantity"]))
                    edit_price = st.number_input("Unit price", min_value=1.0, value=float(selected_order["price"]), step=10.0)
                    edit_lat = st.number_input("Latitude", min_value=-90.0, max_value=90.0, value=float(selected_order["latitude"]), format="%.6f")
                    edit_lon = st.number_input("Longitude", min_value=-180.0, max_value=180.0, value=float(selected_order["longitude"]), format="%.6f")
                    save_edit = st.form_submit_button("Save admin changes", use_container_width=True)
                if save_edit:
                    try:
                        api_request(
                            "PATCH",
                            f"/orders/{selected_order['id']}",
                            json={
                                "product_type": edit_product,
                                "quantity": int(edit_quantity),
                                "price": float(edit_price),
                                "latitude": float(edit_lat),
                                "longitude": float(edit_lon),
                            },
                        )
                        st.success("Order details updated.")
                        st.rerun()
                    except ApiError as error:
                        st.error(str(error))

        if user["role"] in {"admin", "customer"}:
            st.markdown('<h2 class="section-title">Cancel order</h2>', unsafe_allow_html=True)
            st.caption("Only pending or processing orders can be cancelled.")
            if st.button("Cancel selected order", use_container_width=True):
                try:
                    api_request("DELETE", f"/orders/{selected_order['id']}")
                    st.success("Order cancelled successfully.")
                    st.rerun()
                except ApiError as error:
                    st.error(str(error))


def render_create_order_page(user: dict) -> None:
    st.markdown('<h1 class="section-title">Create a furniture order</h1>', unsafe_allow_html=True)
    st.markdown(
        '<p class="muted-copy">Capture delivery coordinates, auto-generate the H3 region, and notify the warehouse workflow.</p>',
        unsafe_allow_html=True,
    )

    presets = {
        "Almaty City Center": (43.238949, 76.889709),
        "Astana Business District": (51.160523, 71.470356),
        "Shymkent Residential Zone": (42.3417, 69.5901),
        "Custom location": (43.238949, 76.889709),
    }
    preset_name = st.selectbox("Location preset", list(presets.keys()))
    default_lat, default_lon = presets[preset_name]

    product_options = [
        "Sofa",
        "Dining Table",
        "Office Chair",
        "Bookshelf",
        "Bed Frame",
        "Wardrobe",
        "Coffee Table",
        "Desk",
        "Custom request",
    ]

    with st.form("create_order_form"):
        product_choice = st.selectbox("Product type", product_options)
        custom_product = ""
        if product_choice == "Custom request":
            custom_product = st.text_input("Custom product name", placeholder="Enter the custom furniture type")
        customer_name = st.text_input(
            "Customer display name",
            value=user["full_name"],
            help="Admins can override the display name for demonstrations.",
        )
        quantity = st.number_input("Quantity", min_value=1, max_value=500, value=1)
        price = st.number_input("Unit price (USD)", min_value=1.0, value=350.0, step=25.0)
        lat_col, lon_col = st.columns(2)
        latitude = lat_col.number_input("Latitude", value=float(default_lat), format="%.6f")
        longitude = lon_col.number_input("Longitude", value=float(default_lon), format="%.6f")
        submit_order = st.form_submit_button("Create order", use_container_width=True)

    live_region = h3.latlng_to_cell(float(latitude), float(longitude), H3_RESOLUTION)
    st.caption(f"Predicted H3 region: {live_region}")

    preview_frame = pd.DataFrame([{"latitude": latitude, "longitude": longitude, "product_type": product_choice}])
    preview_fig = px.scatter_mapbox(
        preview_frame,
        lat="latitude",
        lon="longitude",
        zoom=4.8,
        height=300,
        mapbox_style="carto-positron",
        hover_name="product_type",
    )
    preview_fig.update_layout(margin=dict(l=0, r=0, t=20, b=0))
    st.plotly_chart(preview_fig, use_container_width=True)

    if submit_order:
        final_product = custom_product.strip() if product_choice == "Custom request" else product_choice
        if not final_product:
            st.error("Please provide a custom product name.")
            return
        try:
            payload = api_request(
                "POST",
                "/orders",
                json={
                    "customer_name": customer_name,
                    "product_type": final_product,
                    "quantity": int(quantity),
                    "price": float(price),
                    "latitude": float(latitude),
                    "longitude": float(longitude),
                },
            )
            st.success(
                f"Order #{payload['id']} created successfully in H3 region {payload['h3_region']}."
            )
            time.sleep(0.3)
            st.rerun()
        except ApiError as error:
            st.error(str(error))


def render_audit_logs_page() -> None:
    st.markdown('<h1 class="section-title">Audit log</h1>', unsafe_allow_html=True)
    st.markdown(
        '<p class="muted-copy">Track authentication, order lifecycle updates, cancellations, and backend notifications.</p>',
        unsafe_allow_html=True,
    )
    try:
        logs = api_request("GET", "/audit-logs")
    except ApiError as error:
        display_api_error(error)
        return

    logs_df = pd.DataFrame(logs)
    if logs_df.empty:
        st.info("No audit logs are available yet.")
        return

    logs_df["created_at"] = pd.to_datetime(logs_df["created_at"]).dt.strftime("%Y-%m-%d %H:%M:%S")
    search = st.text_input("Filter logs", placeholder="Action, username, entity, or details")
    filtered_df = logs_df
    if search:
        mask = logs_df.astype(str).apply(lambda col: col.str.contains(search, case=False, regex=False)).any(axis=1)
        filtered_df = logs_df[mask]

    stat_cols = st.columns(3, gap="medium")
    with stat_cols[0]:
        render_metric_card("Audit Entries", str(len(filtered_df)), "Visible after filters")
    with stat_cols[1]:
        render_metric_card("Unique Actors", str(filtered_df["username"].nunique()), "Users and system events")
    with stat_cols[2]:
        render_metric_card("Latest Action", filtered_df.iloc[0]["action"], "Most recent recorded event")

    st.dataframe(filtered_df, use_container_width=True, hide_index=True)
    st.download_button(
        "Download audit log CSV",
        dataframe_to_csv_bytes(filtered_df),
        "audit_logs.csv",
        "text/csv",
        use_container_width=False,
    )


def render_api_docs_page() -> None:
    st.markdown('<h1 class="section-title">API documentation</h1>', unsafe_allow_html=True)
    st.markdown(
        '<p class="muted-copy">Explore the FastAPI contract through Swagger UI. This is especially useful for grading and backend walkthroughs.</p>',
        unsafe_allow_html=True,
    )
    mode, base_url = get_backend_mode()
    docs_url = f"{base_url}/docs" if mode == "http" and base_url else ""
    if docs_url:
        st.link_button("Open Swagger docs in a new tab", docs_url, use_container_width=False)
        components.iframe(docs_url, height=820, scrolling=True)
    else:
        st.info(
            "The frontend is currently using the embedded backend mode. "
            "Run `uvicorn app.main:app --reload` locally to access public Swagger docs at /docs."
        )


def main() -> None:
    ensure_session_defaults()
    page = render_sidebar()
    apply_theme(st.session_state["theme"])

    user = st.session_state.get("user")
    if not user:
        render_landing_page()
        return

    if page == "Overview":
        render_dashboard(user)
    elif page == "Orders":
        render_orders_page(user)
    elif page == "Create Order":
        render_create_order_page(user)
    elif page == "Audit Logs":
        render_audit_logs_page()
    elif page == "API Docs":
        render_api_docs_page()


if __name__ == "__main__":
    main()
