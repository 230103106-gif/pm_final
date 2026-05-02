from __future__ import annotations

import os
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

import h3
import pandas as pd
import plotly.express as px
import pydeck as pdk
import requests
import streamlit as st

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

st.set_page_config(
    page_title="Geo-Optimized Furniture OMS",
    page_icon="🪑",
    layout="wide",
    initial_sidebar_state="expanded",
)

BACKEND_URL = os.getenv("BACKEND_URL", "").rstrip("/")
STATUS_SEQUENCE = ["Pending", "Processing", "Shipped", "Delivered", "Cancelled"]
STATUS_COLORS = {
    "Pending": [201, 111, 45, 220],
    "Processing": [13, 148, 136, 220],
    "Shipped": [2, 132, 199, 220],
    "Delivered": [34, 197, 94, 220],
    "Cancelled": [239, 68, 68, 220],
}
ROLE_LABELS = {
    "admin": "Admin",
    "customer": "Customer",
    "warehouse_manager": "Warehouse Manager",
}
CITY_PRESETS = {
    "Almaty Hub": (43.238949, 76.889709),
    "Astana North": (51.160523, 71.470356),
    "Shymkent South": (42.341685, 69.590101),
    "Karaganda Central": (49.802816, 73.087749),
}


class ApiError(Exception):
    def __init__(self, message: str, status_code: int = 500):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def init_session_state() -> None:
    st.session_state.setdefault("theme_mode", "light")
    st.session_state.setdefault("auth_token", None)
    st.session_state.setdefault("current_user", None)
    st.session_state.setdefault("seen_notification_ids", [])
    st.session_state.setdefault("login_username", "customer")
    st.session_state.setdefault("login_password", "customer123")
    st.session_state.setdefault("login_demo_role", "Customer")
    st.session_state.setdefault("create_location_preset", "Almaty Hub")


@st.cache_resource(show_spinner=False)
def get_embedded_client():
    from fastapi.testclient import TestClient

    from app.database import init_db
    from app.main import app
    from app.queue_worker import start_queue_worker

    init_db()
    start_queue_worker()
    return TestClient(app)


def backend_mode_label() -> str:
    return "Remote FastAPI" if BACKEND_URL else "Embedded FastAPI"


def api_request(
    method: str,
    path: str,
    *,
    token: str | None = None,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
) -> Any:
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    try:
        if BACKEND_URL:
            response = requests.request(
                method,
                f"{BACKEND_URL}{path}",
                headers=headers,
                params=params,
                json=json_body,
                timeout=20,
            )
        else:
            client = get_embedded_client()
            response = client.request(
                method,
                path,
                headers=headers,
                params=params,
                json=json_body,
            )
    except requests.RequestException as exc:
        raise ApiError(f"Unable to reach the backend: {exc}", status_code=503) from exc
    except Exception as exc:
        raise ApiError(f"Unexpected application error: {exc}", status_code=500) from exc

    payload: Any
    if response.content:
        try:
            payload = response.json()
        except ValueError:
            payload = response.text
    else:
        payload = None

    if response.status_code >= 400:
        if isinstance(payload, dict):
            detail = payload.get("detail", "Request failed.")
        else:
            detail = str(payload)
        raise ApiError(detail, status_code=response.status_code)
    return payload


def login_user(username: str, password: str) -> None:
    payload = api_request("POST", "/login", json_body={"username": username, "password": password})
    st.session_state.auth_token = payload["access_token"]
    st.session_state.current_user = payload["user"]


def logout_user() -> None:
    st.session_state.auth_token = None
    st.session_state.current_user = None
    st.session_state.seen_notification_ids = []


def require_login() -> dict[str, Any]:
    user = st.session_state.current_user
    token = st.session_state.auth_token
    if not user or not token:
        raise ApiError("Please sign in to continue.", status_code=401)
    return user


def safe_fetch(path: str, *, params: dict[str, Any] | None = None) -> Any:
    require_login()
    return api_request("GET", path, token=st.session_state.auth_token, params=params)


def format_currency(amount: float) -> str:
    return f"${amount:,.2f}"


def friendly_role(role: str) -> str:
    return ROLE_LABELS.get(role, role.replace("_", " ").title())


def short_region(region: str) -> str:
    return f"{region[:8]}...{region[-4:]}" if region and len(region) > 14 else region


def apply_theme() -> None:
    dark_mode = st.session_state.theme_mode == "dark"
    palette = {
        "bg": "#f5efe8" if not dark_mode else "#0d1719",
        "surface": "rgba(255, 250, 244, 0.86)" if not dark_mode else "rgba(17, 29, 31, 0.82)",
        "panel": "#fffaf5" if not dark_mode else "#122225",
        "text": "#1f2d30" if not dark_mode else "#ebf5f4",
        "muted": "#617377" if not dark_mode else "#9cb3b7",
        "accent": "#0f766e" if not dark_mode else "#2dd4bf",
        "accent_soft": "rgba(15, 118, 110, 0.08)" if not dark_mode else "rgba(45, 212, 191, 0.12)",
        "secondary": "#b45309" if not dark_mode else "#f59e0b",
        "danger": "#dc2626" if not dark_mode else "#f87171",
        "border": "rgba(31, 45, 48, 0.10)" if not dark_mode else "rgba(191, 219, 223, 0.10)",
        "shadow": "0 20px 60px rgba(20, 32, 37, 0.10)" if not dark_mode else "0 24px 60px rgba(0, 0, 0, 0.28)",
    }
    plotly_template = "plotly_dark" if dark_mode else "plotly_white"
    st.session_state["plotly_template"] = plotly_template

    st.markdown(
        f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=DM+Sans:wght@400;500;700&display=swap');

        :root {{
            --bg: {palette["bg"]};
            --surface: {palette["surface"]};
            --panel: {palette["panel"]};
            --text: {palette["text"]};
            --muted: {palette["muted"]};
            --accent: {palette["accent"]};
            --accent-soft: {palette["accent_soft"]};
            --secondary: {palette["secondary"]};
            --danger: {palette["danger"]};
            --border: {palette["border"]};
            --shadow: {palette["shadow"]};
        }}

        html, body, [data-testid="stAppViewContainer"], [data-testid="stApp"] {{
            background:
                radial-gradient(circle at top left, rgba(15, 118, 110, 0.16), transparent 28%),
                radial-gradient(circle at top right, rgba(180, 83, 9, 0.15), transparent 24%),
                linear-gradient(180deg, var(--bg) 0%, var(--bg) 100%);
            color: var(--text);
            font-family: 'DM Sans', sans-serif;
        }}

        [data-testid="stSidebar"] {{
            background: linear-gradient(180deg, rgba(15,118,110,0.12) 0%, rgba(0,0,0,0) 22%), var(--panel);
            border-right: 1px solid var(--border);
        }}

        [data-testid="stSidebar"] * {{
            color: var(--text);
        }}

        .block-container {{
            max-width: 1320px;
            padding-top: 2rem;
            padding-bottom: 3rem;
        }}

        h1, h2, h3, h4, h5 {{
            font-family: 'Space Grotesk', sans-serif;
            color: var(--text);
            letter-spacing: -0.02em;
        }}

        .hero-shell, .glass-card, .metric-card, .soft-card, .timeline-card {{
            background: var(--surface);
            border: 1px solid var(--border);
            box-shadow: var(--shadow);
            border-radius: 24px;
            overflow: hidden;
        }}

        .hero-shell {{
            padding: 2.1rem;
            position: relative;
            animation: rise 0.55s ease-out both;
        }}

        .glass-card {{
            padding: 1.35rem 1.4rem;
            animation: rise 0.55s ease-out both;
        }}

        .metric-card {{
            padding: 1rem 1.15rem;
            min-height: 136px;
            position: relative;
            animation: rise 0.5s ease-out both;
        }}

        .metric-card::after {{
            content: "";
            position: absolute;
            inset: auto 18px 18px 18px;
            height: 4px;
            border-radius: 999px;
            background: linear-gradient(90deg, var(--accent), rgba(255,255,255,0));
        }}

        .soft-card {{
            padding: 1rem 1.15rem;
        }}

        .timeline-card {{
            padding: 0.95rem 1rem;
            margin-bottom: 0.75rem;
        }}

        .eyebrow {{
            text-transform: uppercase;
            letter-spacing: 0.18em;
            font-size: 0.78rem;
            color: var(--secondary);
            font-weight: 700;
        }}

        .hero-title {{
            font-size: 2.65rem;
            line-height: 1.05;
            margin: 0.35rem 0 0.8rem 0;
        }}

        .hero-copy, .muted-copy {{
            color: var(--muted);
            font-size: 1.02rem;
            line-height: 1.7;
        }}

        .chip-row {{
            display: flex;
            flex-wrap: wrap;
            gap: 0.55rem;
            margin-top: 1.1rem;
        }}

        .chip {{
            padding: 0.45rem 0.8rem;
            border-radius: 999px;
            border: 1px solid var(--border);
            background: var(--accent-soft);
            color: var(--text);
            font-size: 0.85rem;
            font-weight: 600;
        }}

        .metric-label {{
            color: var(--muted);
            font-size: 0.92rem;
            margin-bottom: 0.45rem;
        }}

        .metric-value {{
            font-size: 2rem;
            font-family: 'Space Grotesk', sans-serif;
            font-weight: 700;
            line-height: 1;
        }}

        .metric-footnote {{
            margin-top: 0.65rem;
            color: var(--muted);
            font-size: 0.84rem;
        }}

        .feature-grid {{
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 0.9rem;
            margin-top: 1rem;
        }}

        .feature-card {{
            border-radius: 20px;
            padding: 1rem;
            background: linear-gradient(180deg, var(--accent-soft) 0%, rgba(255,255,255,0.02) 100%);
            border: 1px solid var(--border);
        }}

        .feature-card h4 {{
            margin: 0 0 0.45rem 0;
            font-size: 1rem;
        }}

        .status-pill {{
            display: inline-flex;
            align-items: center;
            gap: 0.45rem;
            border-radius: 999px;
            padding: 0.35rem 0.75rem;
            font-weight: 700;
            font-size: 0.82rem;
            background: var(--accent-soft);
            border: 1px solid var(--border);
        }}

        .sidebar-brand {{
            padding: 0.2rem 0 1rem 0;
        }}

        .brand-title {{
            font-family: 'Space Grotesk', sans-serif;
            font-size: 1.15rem;
            font-weight: 700;
            line-height: 1.2;
        }}

        .brand-subtitle {{
            color: var(--muted);
            font-size: 0.88rem;
        }}

        .insight-list {{
            display: grid;
            gap: 0.7rem;
        }}

        .insight-row {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 0.75rem 0.95rem;
            border-radius: 18px;
            background: rgba(255,255,255,0.03);
            border: 1px solid var(--border);
        }}

        .small-muted {{
            color: var(--muted);
            font-size: 0.84rem;
        }}

        .divider-title {{
            margin-top: 0.4rem;
            margin-bottom: 0.75rem;
        }}

        .order-fact {{
            padding: 0.85rem 0.95rem;
            border-radius: 18px;
            background: rgba(255,255,255,0.03);
            border: 1px solid var(--border);
            height: 100%;
        }}

        .stButton button, .stDownloadButton button {{
            border-radius: 12px;
            border: 1px solid var(--border);
            box-shadow: none;
            font-weight: 600;
        }}

        .stButton button[kind="primary"] {{
            background: linear-gradient(135deg, var(--accent) 0%, var(--secondary) 100%);
            color: white;
            border: none;
        }}

        div[data-baseweb="select"] > div {{
            border-radius: 12px;
        }}

        @keyframes rise {{
            from {{
                opacity: 0;
                transform: translateY(8px);
            }}
            to {{
                opacity: 1;
                transform: translateY(0);
            }}
        }}

        @media (max-width: 1000px) {{
            .feature-grid {{
                grid-template-columns: 1fr;
            }}

            .hero-title {{
                font-size: 2.1rem;
            }}
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_metric_card(title: str, value: str, footnote: str) -> None:
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label">{title}</div>
            <div class="metric-value">{value}</div>
            <div class="metric-footnote">{footnote}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_section_title(title: str, subtitle: str) -> None:
    st.markdown(
        f"""
        <div class="divider-title">
            <div class="eyebrow">{title}</div>
            <div class="muted-copy">{subtitle}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar() -> str:
    current_user = st.session_state.current_user
    with st.sidebar:
        st.markdown(
            """
            <div class="sidebar-brand">
                <div class="brand-title">Geo Furniture Ops</div>
                <div class="brand-subtitle">H3-powered order intelligence for stores, admins, and warehouse teams.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        dark_mode = st.toggle("Dark mode", value=st.session_state.theme_mode == "dark")
        st.session_state.theme_mode = "dark" if dark_mode else "light"
        st.caption(f"Connected via {backend_mode_label()}")

        st.markdown(
            f"""
            <div class="glass-card">
                <div class="eyebrow">Signed In</div>
                <h4 style="margin:0.3rem 0 0.15rem 0;">{current_user["full_name"]}</h4>
                <div class="small-muted">{friendly_role(current_user["role"])}</div>
                <div style="margin-top:0.8rem;" class="status-pill">
                    Region scope: {short_region(current_user.get("allowed_h3_region") or "All regions")}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown("")

        page = st.radio(
            "Navigation",
            options=["Overview", "Orders", "Analytics", "Audit Logs"],
            label_visibility="collapsed",
        )
        if BACKEND_URL:
            st.markdown(f"[Open API docs]({BACKEND_URL}/docs)")
        else:
            st.caption("Embedded mode keeps the backend inside the Streamlit deployment for one-click demos.")

        if st.button("Refresh data", use_container_width=True):
            st.rerun()
        if st.button("Logout", type="primary", use_container_width=True):
            logout_user()
            st.rerun()
        return page


def prepare_order_frame(orders: list[dict[str, Any]]) -> pd.DataFrame:
    if not orders:
        return pd.DataFrame(
            columns=[
                "id",
                "customer_name",
                "product_type",
                "quantity",
                "price",
                "total_amount",
                "latitude",
                "longitude",
                "h3_region",
                "status",
                "notes",
                "created_at",
                "updated_at",
            ]
        )

    frame = pd.DataFrame(orders)
    frame["created_at"] = pd.to_datetime(frame["created_at"])
    frame["updated_at"] = pd.to_datetime(frame["updated_at"])
    frame["created_date"] = frame["created_at"].dt.strftime("%Y-%m-%d %H:%M")
    frame["price"] = frame["price"].astype(float)
    frame["total_amount"] = frame["total_amount"].astype(float)
    frame["region_short"] = frame["h3_region"].apply(short_region)
    return frame.sort_values("created_at", ascending=False)


def prepare_audit_frame(logs: list[dict[str, Any]]) -> pd.DataFrame:
    if not logs:
        return pd.DataFrame(columns=["id", "actor_username", "action", "description", "target_type", "target_id", "created_at"])
    frame = pd.DataFrame(logs)
    frame["created_at"] = pd.to_datetime(frame["created_at"])
    frame["created_display"] = frame["created_at"].dt.strftime("%Y-%m-%d %H:%M:%S")
    return frame.sort_values("created_at", ascending=False)


def make_h3_map(order_frame: pd.DataFrame):
    if order_frame.empty:
        return None

    regions = (
        order_frame.groupby("h3_region", as_index=False)
        .agg(
            orders=("id", "count"),
            revenue=("total_amount", "sum"),
            latitude=("latitude", "mean"),
            longitude=("longitude", "mean"),
        )
        .sort_values("orders", ascending=False)
    )

    polygon_rows = []
    for row in regions.to_dict("records"):
        boundary = h3.cell_to_boundary(row["h3_region"])
        polygon_rows.append(
            {
                "h3_region": row["h3_region"],
                "orders": int(row["orders"]),
                "revenue": round(float(row["revenue"]), 2),
                "polygon": [[lng, lat] for lat, lng in boundary],
            }
        )

    points = order_frame.copy()
    points["color"] = points["status"].map(STATUS_COLORS).apply(
        lambda value: value if isinstance(value, list) else [13, 148, 136, 220]
    )
    points["tooltip_label"] = points.apply(
        lambda row: f"Order #{row['id']} - {row['product_type']} ({row['status']})",
        axis=1,
    )

    polygon_layer = pdk.Layer(
        "PolygonLayer",
        polygon_rows,
        get_polygon="polygon",
        get_fill_color=[15, 118, 110, 60],
        get_line_color=[180, 83, 9, 200],
        pickable=True,
        auto_highlight=True,
    )
    scatter_layer = pdk.Layer(
        "ScatterplotLayer",
        points,
        get_position=["longitude", "latitude"],
        get_fill_color="color",
        get_line_color=[255, 255, 255],
        line_width_min_pixels=1,
        get_radius=5000,
        pickable=True,
    )

    view_state = pdk.ViewState(
        latitude=float(order_frame["latitude"].mean()),
        longitude=float(order_frame["longitude"].mean()),
        zoom=4.3,
        pitch=28,
    )

    return pdk.Deck(
        layers=[polygon_layer, scatter_layer],
        initial_view_state=view_state,
        map_style="dark" if st.session_state.theme_mode == "dark" else "light",
        tooltip={
            "html": "<b>{h3_region}</b><br/>Orders: {orders}<br/>Revenue: ${revenue}",
            "style": {"backgroundColor": "#102326", "color": "white"},
        },
    )


def show_recent_notification_toasts(audit_frame: pd.DataFrame) -> None:
    if audit_frame.empty:
        return

    seen_ids = set(st.session_state.seen_notification_ids)
    latest_notifications = audit_frame[audit_frame["action"] == "warehouse_notification"].head(5)
    for _, row in latest_notifications.iterrows():
        if int(row["id"]) not in seen_ids:
            st.toast(row["description"], icon=":material/local_shipping:")
            st.session_state.seen_notification_ids.append(int(row["id"]))


def poll_for_new_notification(order_id: int) -> None:
    for _ in range(6):
        time.sleep(0.5)
        logs = safe_fetch("/audit-logs", params={"limit": 20})
        match = next(
            (
                log
                for log in logs
                if log["action"] == "warehouse_notification" and int(log.get("target_id") or 0) == int(order_id)
            ),
            None,
        )
        if match:
            if match["id"] not in st.session_state.seen_notification_ids:
                st.toast(match["description"], icon=":material/notifications_active:")
                st.session_state.seen_notification_ids.append(match["id"])
            return


def render_theme_switch_for_public_page() -> None:
    top_left, top_right = st.columns([5, 1])
    with top_right:
        dark_mode = st.toggle("Dark mode", value=st.session_state.theme_mode == "dark")
        st.session_state.theme_mode = "dark" if dark_mode else "light"


def render_public_landing() -> None:
    render_theme_switch_for_public_page()
    apply_theme()
    hero_col, auth_col = st.columns([1.55, 1.0], gap="large")

    with hero_col:
        st.markdown(
            """
            <div class="hero-shell">
                <div class="eyebrow">University Capstone Project</div>
                <div class="hero-title">Geo-Optimized Furniture Order Management System</div>
                <div class="hero-copy">
                    A polished full-stack logistics platform that combines FastAPI, Streamlit, SQLite,
                    SQLAlchemy, H3 geospatial indexing, analytics, and asynchronous warehouse notifications.
                </div>
                <div class="chip-row">
                    <div class="chip">Role-Based Access Control</div>
                    <div class="chip">ABAC Region Scoping</div>
                    <div class="chip">H3 Hex Regions</div>
                    <div class="chip">Plotly Analytics</div>
                    <div class="chip">CSV Reports</div>
                    <div class="chip">Queue Worker Notifications</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown("")
        st.markdown(
            """
            <div class="feature-grid">
                <div class="feature-card">
                    <h4>Smart regional routing</h4>
                    <div class="muted-copy">Every order is converted into an H3 hex cell automatically, making regional warehouse assignment immediate and consistent.</div>
                </div>
                <div class="feature-card">
                    <h4>Role-aware operations</h4>
                    <div class="muted-copy">Admins manage the whole network, customers see only their orders, and warehouse managers stay locked to their assigned region.</div>
                </div>
                <div class="feature-card">
                    <h4>Event-driven workflow</h4>
                    <div class="muted-copy">New orders trigger a background queue event, which simulates warehouse notification without blocking the customer experience.</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown("")
        render_section_title("Platform Highlights", "A deployable open-source architecture designed to impress on functionality, innovation, and presentation.")
        insight_left, insight_right = st.columns(2, gap="large")
        with insight_left:
            st.markdown(
                """
                <div class="soft-card">
                    <div class="insight-list">
                        <div class="insight-row"><span>FastAPI backend with Swagger docs</span><strong>/docs</strong></div>
                        <div class="insight-row"><span>SQLite + SQLAlchemy ORM schema</span><strong>3 core tables</strong></div>
                        <div class="insight-row"><span>Production-ready Streamlit dashboard</span><strong>Responsive UI</strong></div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with insight_right:
            st.markdown(
                """
                <div class="soft-card">
                    <div class="insight-list">
                        <div class="insight-row"><span>Embedded mode for Streamlit Cloud</span><strong>Zero extra backend required</strong></div>
                        <div class="insight-row"><span>Analytics and report exports</span><strong>Plotly + CSV</strong></div>
                        <div class="insight-row"><span>Audit log visibility</span><strong>Traceable actions</strong></div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    with auth_col:
        st.markdown(
            """
            <div class="glass-card">
                <div class="eyebrow">Demo Access</div>
                <h3 style="margin:0.35rem 0 0.65rem 0;">Sign in to the live system</h3>
                <div class="muted-copy">Use the provided accounts to test the three role-specific experiences.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown("")

        preset_labels = {
            "Customer": ("customer", "customer123"),
            "Admin": ("admin", "admin123"),
            "Warehouse Manager": ("warehouse", "warehouse123"),
        }
        selected_demo = st.selectbox("Quick demo preset", list(preset_labels.keys()), key="login_demo_role")
        if st.button("Load selected demo account", use_container_width=True):
            st.session_state.login_username, st.session_state.login_password = preset_labels[selected_demo]

        with st.form("login_form", clear_on_submit=False):
            username = st.text_input("Username", key="login_username")
            password = st.text_input("Password", type="password", key="login_password")
            submitted = st.form_submit_button("Open dashboard", type="primary", use_container_width=True)

        if submitted:
            try:
                login_user(username, password)
                st.success("Login successful. Redirecting to your dashboard...")
                st.rerun()
            except ApiError as exc:
                st.error(exc.message)

        st.markdown("")
        st.markdown(
            """
            <div class="soft-card">
                <div class="eyebrow">Demo Credentials</div>
                <div class="muted-copy" style="margin-top:0.7rem;">
                    <strong>Admin:</strong> admin / admin123<br/>
                    <strong>Customer:</strong> customer / customer123<br/>
                    <strong>Warehouse:</strong> warehouse / warehouse123
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown("")
        st.caption(
            "Deployment note: without `BACKEND_URL`, the Streamlit app automatically uses the embedded FastAPI backend for simpler demos and Streamlit Cloud hosting."
        )


def render_overview_page() -> None:
    current_user = st.session_state.current_user
    orders = safe_fetch("/orders")
    analytics = safe_fetch("/analytics")
    audit_logs = safe_fetch("/audit-logs", params={"limit": 20})

    order_frame = prepare_order_frame(orders)
    audit_frame = prepare_audit_frame(audit_logs)
    show_recent_notification_toasts(audit_frame)

    st.markdown(
        f"""
        <div class="hero-shell">
            <div class="eyebrow">{friendly_role(current_user["role"])} Dashboard</div>
            <div class="hero-title">Operational visibility for {current_user["full_name"]}</div>
            <div class="hero-copy">
                Track furniture orders, regional demand, revenue movement, and warehouse activity from a single geospatial control center.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("")

    summary = analytics["summary"]
    metric_cols = st.columns(5)
    metrics = [
        ("Orders in scope", f"{summary['total_orders']:,}", "Total records visible under your role policy."),
        ("Revenue", format_currency(summary["total_revenue"]), "Calculated as quantity multiplied by unit price."),
        ("Pending", f"{summary['pending_orders']}", "Orders still awaiting warehouse completion."),
        ("Delivered", f"{summary['delivered_orders']}", "Completed deliveries in your visible scope."),
        ("Active regions", f"{summary['unique_regions']}", "Distinct H3 regions represented by current orders."),
    ]
    for column, metric in zip(metric_cols, metrics):
        with column:
            render_metric_card(*metric)

    st.markdown("")
    map_col, region_col = st.columns([1.7, 1.0], gap="large")
    with map_col:
        render_section_title("Regional Footprint", "Hex-region coverage based on H3 cells and precise order coordinates.")
        deck = make_h3_map(order_frame)
        if deck is None:
            st.info("No orders are available yet for the current scope.")
        else:
            st.pydeck_chart(deck, use_container_width=True)

    with region_col:
        render_section_title("Region Summary", "Top regions ranked by order concentration and revenue performance.")
        region_orders = pd.DataFrame(analytics["orders_by_region"])
        region_revenue = pd.DataFrame(analytics["revenue_by_region"])
        if region_orders.empty:
            st.info("Region-level metrics will appear here once orders are available.")
        else:
            merged = region_orders.merge(region_revenue, on="h3_region", how="left").fillna(0)
            merged["display_region"] = merged["h3_region"].apply(short_region)
            for _, row in merged.head(5).iterrows():
                st.markdown(
                    f"""
                    <div class="timeline-card">
                        <div class="small-muted">H3 region</div>
                        <h4 style="margin:0.2rem 0;">{row['display_region']}</h4>
                        <div class="muted-copy">{int(row['orders'])} orders · {format_currency(float(row['revenue']))} revenue</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

    st.markdown("")
    recent_col, activity_col = st.columns([1.3, 1.0], gap="large")
    with recent_col:
        render_section_title("Recent Orders", "The newest furniture orders in your accessible data scope.")
        if order_frame.empty:
            st.info("No recent orders to display.")
        else:
            st.dataframe(
                order_frame[
                    ["id", "customer_name", "product_type", "status", "quantity", "price", "total_amount", "region_short", "created_date"]
                ].rename(
                    columns={
                        "id": "Order ID",
                        "customer_name": "Customer",
                        "product_type": "Product",
                        "status": "Status",
                        "quantity": "Qty",
                        "price": "Unit Price",
                        "total_amount": "Total",
                        "region_short": "H3 Region",
                        "created_date": "Created",
                    }
                ),
                use_container_width=True,
                hide_index=True,
            )

    with activity_col:
        render_section_title("Activity Feed", "Audit entries and warehouse notifications processed by the event queue.")
        if audit_frame.empty:
            st.info("Audit activity will appear here after users and orders generate events.")
        else:
            for _, row in audit_frame.head(8).iterrows():
                st.markdown(
                    f"""
                    <div class="timeline-card">
                        <div class="eyebrow">{row['action'].replace('_', ' ')}</div>
                        <h4 style="margin:0.15rem 0 0.35rem 0;">{row['description']}</h4>
                        <div class="small-muted">{row['actor_username']} · {row['created_display']}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )


def render_order_create_form(current_user: dict[str, Any]) -> None:
    with st.expander("Create a new furniture order", expanded=current_user["role"] != "warehouse_manager"):
        preset_col, filler_col = st.columns([1.1, 1.5])
        with preset_col:
            chosen_preset = st.selectbox("Location preset", list(CITY_PRESETS.keys()), key="create_location_preset")
        latitude_default, longitude_default = CITY_PRESETS[chosen_preset]
        preview_region = h3.latlng_to_cell(latitude_default, longitude_default, 7)
        with filler_col:
            st.markdown(
                f"""
                <div class="soft-card">
                    <div class="eyebrow">Predicted H3 Region</div>
                    <h4 style="margin:0.2rem 0;">{short_region(preview_region)}</h4>
                    <div class="small-muted">Preview based on the selected delivery coordinates.</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        with st.form("create_order_form", clear_on_submit=True):
            left, right = st.columns(2, gap="large")
            with left:
                customer_name = st.text_input(
                    "Customer name",
                    value=current_user["full_name"] if current_user["role"] == "customer" else "",
                    disabled=current_user["role"] == "customer",
                )
                product_type = st.text_input("Furniture product", value="Custom Modular Sofa")
                quantity = st.number_input("Quantity", min_value=1, max_value=1000, value=1)
                price = st.number_input("Unit price (USD)", min_value=1.0, value=450.0, step=10.0)
            with right:
                latitude = st.number_input("Latitude", value=float(latitude_default), format="%.6f")
                longitude = st.number_input("Longitude", value=float(longitude_default), format="%.6f")
                notes = st.text_area("Order notes", placeholder="Assembly, delivery window, special handling...")
                st.caption(f"H3 region preview: `{h3.latlng_to_cell(latitude, longitude, 7)}`")

            submitted = st.form_submit_button("Submit order", type="primary", use_container_width=True)

        if submitted:
            payload = {
                "customer_name": customer_name.strip() or current_user["full_name"],
                "product_type": product_type.strip(),
                "quantity": int(quantity),
                "price": float(price),
                "latitude": float(latitude),
                "longitude": float(longitude),
                "notes": notes.strip() or None,
            }
            try:
                created_order = api_request(
                    "POST",
                    "/orders",
                    token=st.session_state.auth_token,
                    json_body=payload,
                )
                st.success(f"Order #{created_order['id']} created successfully.")
                poll_for_new_notification(created_order["id"])
                st.rerun()
            except ApiError as exc:
                st.error(exc.message)


def render_selected_order_management(order: dict[str, Any], current_user: dict[str, Any]) -> None:
    detail_tab, manage_tab = st.tabs(["Order details", "Manage order"])

    with detail_tab:
        metric_cols = st.columns(4)
        detail_metrics = [
            ("Order ID", f"#{order['id']}", order["product_type"]),
            ("Customer", order["customer_name"], friendly_role(current_user["role"])),
            ("Status", order["status"], short_region(order["h3_region"])),
            ("Total", format_currency(float(order["total_amount"])), f"{order['quantity']} units at {format_currency(float(order['price']))} each"),
        ]
        for column, metric in zip(metric_cols, detail_metrics):
            with column:
                render_metric_card(*metric)

        fact_cols = st.columns(3, gap="large")
        with fact_cols[0]:
            st.markdown(
                f"""
                <div class="order-fact">
                    <div class="eyebrow">Coordinates</div>
                    <h4 style="margin:0.25rem 0;">{order['latitude']:.5f}, {order['longitude']:.5f}</h4>
                    <div class="small-muted">Geolocation used for H3 assignment and warehouse routing.</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with fact_cols[1]:
            st.markdown(
                f"""
                <div class="order-fact">
                    <div class="eyebrow">Created</div>
                    <h4 style="margin:0.25rem 0;">{pd.to_datetime(order['created_at']).strftime('%Y-%m-%d %H:%M')}</h4>
                    <div class="small-muted">Last updated {pd.to_datetime(order['updated_at']).strftime('%Y-%m-%d %H:%M')}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with fact_cols[2]:
            st.markdown(
                f"""
                <div class="order-fact">
                    <div class="eyebrow">Notes</div>
                    <h4 style="margin:0.25rem 0;">{order.get('notes') or 'No notes added'}</h4>
                    <div class="small-muted">Operational notes are visible to the authorized workflow participants.</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        st.map(pd.DataFrame([{"lat": order["latitude"], "lon": order["longitude"]}]), latitude="lat", longitude="lon", zoom=11)

    with manage_tab:
        role = current_user["role"]
        if role == "warehouse_manager":
            allowed_statuses = ["Processing", "Shipped", "Delivered"]
            with st.form(f"warehouse_update_{order['id']}"):
                new_status = st.selectbox("Update regional order status", allowed_statuses, index=max(0, min(len(allowed_statuses) - 1, allowed_statuses.index(order["status"]) if order["status"] in allowed_statuses else 0)))
                submitted = st.form_submit_button("Save status", type="primary")
            if submitted:
                try:
                    api_request(
                        "PUT",
                        f"/orders/{order['id']}",
                        token=st.session_state.auth_token,
                        json_body={"status": new_status},
                    )
                    st.success("Order status updated.")
                    st.rerun()
                except ApiError as exc:
                    st.error(exc.message)
        else:
            is_admin = role == "admin"
            can_edit_fields = is_admin or order["status"] == "Pending"
            can_cancel = order["status"] not in {"Cancelled", "Delivered"}

            with st.form(f"manage_order_form_{order['id']}"):
                left, right = st.columns(2, gap="large")
                with left:
                    product_type = st.text_input("Furniture product", value=order["product_type"], disabled=not can_edit_fields)
                    quantity = st.number_input("Quantity", min_value=1, value=int(order["quantity"]), disabled=not can_edit_fields)
                    price = st.number_input("Unit price (USD)", min_value=1.0, value=float(order["price"]), step=10.0, disabled=not can_edit_fields)
                    customer_name = st.text_input(
                        "Customer name",
                        value=order["customer_name"],
                        disabled=not is_admin,
                    )
                with right:
                    latitude = st.number_input("Latitude", value=float(order["latitude"]), format="%.6f", disabled=not can_edit_fields)
                    longitude = st.number_input("Longitude", value=float(order["longitude"]), format="%.6f", disabled=not can_edit_fields)
                    notes = st.text_area("Notes", value=order.get("notes") or "", disabled=not can_edit_fields)
                    if is_admin:
                        status = st.selectbox("Status", STATUS_SEQUENCE, index=STATUS_SEQUENCE.index(order["status"]))
                    else:
                        status = order["status"]
                        st.caption(f"Current status: {status}")

                update_clicked = st.form_submit_button("Save changes", type="primary", disabled=not (is_admin or can_edit_fields))

            if update_clicked:
                update_payload = {}
                if is_admin or can_edit_fields:
                    update_payload.update(
                        {
                            "product_type": product_type.strip(),
                            "quantity": int(quantity),
                            "price": float(price),
                            "latitude": float(latitude),
                            "longitude": float(longitude),
                            "notes": notes.strip() or None,
                        }
                    )
                if is_admin:
                    update_payload["customer_name"] = customer_name.strip()
                    update_payload["status"] = status
                try:
                    api_request(
                        "PUT",
                        f"/orders/{order['id']}",
                        token=st.session_state.auth_token,
                        json_body=update_payload,
                    )
                    st.success("Order details updated.")
                    st.rerun()
                except ApiError as exc:
                    st.error(exc.message)

            if can_cancel:
                if st.button("Cancel order", use_container_width=True):
                    try:
                        api_request("POST", f"/orders/{order['id']}/cancel", token=st.session_state.auth_token)
                        st.success("Order cancelled successfully.")
                        st.rerun()
                    except ApiError as exc:
                        st.error(exc.message)


def render_orders_page() -> None:
    current_user = st.session_state.current_user
    st.markdown(
        """
        <div class="hero-shell">
            <div class="eyebrow">Order Management</div>
            <div class="hero-title">Create, filter, inspect, and manage furniture orders</div>
            <div class="hero-copy">Role-based actions are enforced here and mirrored by the FastAPI backend, including the warehouse region ABAC rule.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("")
    render_order_create_form(current_user)
    st.markdown("")

    filter_cols = st.columns([1.5, 1, 1, 1, 1], gap="large")
    with filter_cols[0]:
        search = st.text_input("Search", placeholder="Order ID, customer, or product")
    with filter_cols[1]:
        status_filter = st.selectbox("Status", ["All"] + STATUS_SEQUENCE)
    with filter_cols[2]:
        region_filter = st.text_input("Region filter", placeholder="Optional H3 cell")
    with filter_cols[3]:
        product_filter = st.text_input("Product filter", placeholder="e.g. sofa")
    with filter_cols[4]:
        date_range = st.date_input("Date range", value=())

    params: dict[str, Any] = {}
    if search:
        params["search"] = search
    if status_filter != "All":
        params["status"] = status_filter
    if region_filter:
        params["region"] = region_filter.strip()
    if product_filter:
        params["product_type"] = product_filter.strip()
    if isinstance(date_range, tuple) and len(date_range) == 2:
        if isinstance(date_range[0], date):
            params["date_from"] = str(date_range[0])
        if isinstance(date_range[1], date):
            params["date_to"] = str(date_range[1])

    orders = safe_fetch("/orders", params=params)
    order_frame = prepare_order_frame(orders)

    action_col, export_col = st.columns([4, 1])
    with action_col:
        st.caption(f"{len(order_frame)} orders returned for the current filters.")
    with export_col:
        csv_bytes = order_frame.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Download CSV",
            data=csv_bytes,
            file_name=f"orders_report_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv",
            use_container_width=True,
        )

    if order_frame.empty:
        st.info("No orders matched the selected filters.")
        return

    st.dataframe(
        order_frame[
            ["id", "customer_name", "product_type", "status", "quantity", "price", "total_amount", "region_short", "created_date"]
        ].rename(
            columns={
                "id": "Order ID",
                "customer_name": "Customer",
                "product_type": "Product",
                "status": "Status",
                "quantity": "Qty",
                "price": "Unit Price",
                "total_amount": "Total",
                "region_short": "H3 Region",
                "created_date": "Created",
            }
        ),
        use_container_width=True,
        hide_index=True,
    )
    st.markdown("")

    selector_options = {
        f"#{row['id']} · {row['product_type']} · {row['status']}": row["id"]
        for _, row in order_frame.iterrows()
    }
    selection = st.selectbox("Inspect an order", list(selector_options.keys()))
    selected_id = selector_options[selection]
    selected_order = next(order for order in orders if int(order["id"]) == int(selected_id))
    render_selected_order_management(selected_order, current_user)


def render_analytics_page() -> None:
    analytics = safe_fetch("/analytics")
    orders = safe_fetch("/orders")
    order_frame = prepare_order_frame(orders)

    st.markdown(
        """
        <div class="hero-shell">
            <div class="eyebrow">Analytics Dashboard</div>
            <div class="hero-title">Regional demand, revenue, and product intelligence</div>
            <div class="hero-copy">Plotly-powered analytics reveal how order volume and revenue move across H3 regions over time.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("")

    summary = analytics["summary"]
    summary_cols = st.columns(4)
    summary_metrics = [
        ("Total orders", f"{summary['total_orders']}", "Visible under the active role scope."),
        ("Revenue", format_currency(summary["total_revenue"]), "Computed from quantity and unit price."),
        ("Pending flow", f"{summary['pending_orders']}", "Orders waiting for operational completion."),
        ("Unique regions", f"{summary['unique_regions']}", "Distinct H3 cells represented in the dataset."),
    ]
    for column, metric in zip(summary_cols, summary_metrics):
        with column:
            render_metric_card(*metric)

    orders_by_region = pd.DataFrame(analytics["orders_by_region"])
    orders_by_status = pd.DataFrame(analytics["orders_by_status"])
    revenue_by_region = pd.DataFrame(analytics["revenue_by_region"])
    daily_trend = pd.DataFrame(analytics["daily_orders_trend"])
    top_products = pd.DataFrame(analytics["top_products"])

    plot_template = st.session_state.get("plotly_template", "plotly_white")
    chart_left, chart_right = st.columns(2, gap="large")

    with chart_left:
        if not orders_by_region.empty:
            fig = px.bar(
                orders_by_region,
                x="h3_region",
                y="orders",
                title="Orders by H3 region",
                color="orders",
                color_continuous_scale="Tealgrn",
                template=plot_template,
            )
            fig.update_layout(xaxis_title="H3 region", yaxis_title="Orders")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Orders by region will appear after data is available.")

        if not revenue_by_region.empty:
            fig = px.bar(
                revenue_by_region,
                x="h3_region",
                y="revenue",
                title="Revenue by H3 region",
                color="revenue",
                color_continuous_scale="Sunsetdark",
                template=plot_template,
            )
            fig.update_layout(xaxis_title="H3 region", yaxis_title="Revenue (USD)")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Revenue by region will appear after data is available.")

    with chart_right:
        if not orders_by_status.empty:
            fig = px.pie(
                orders_by_status,
                names="status",
                values="orders",
                hole=0.55,
                title="Orders by status",
                template=plot_template,
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Orders by status will appear after data is available.")

        if not top_products.empty:
            fig = px.bar(
                top_products,
                x="orders",
                y="product_type",
                orientation="h",
                title="Top furniture products",
                color="revenue",
                color_continuous_scale="Tealrose",
                template=plot_template,
            )
            fig.update_layout(yaxis_title="Product", xaxis_title="Orders")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Top products will appear after data is available.")

    if not daily_trend.empty:
        fig = px.line(
            daily_trend,
            x="order_date",
            y=["orders", "revenue"],
            markers=True,
            title="Daily orders and revenue trend",
            template=plot_template,
        )
        fig.update_layout(xaxis_title="Date", yaxis_title="Value")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Daily trend data will appear after enough orders exist.")

    st.markdown("")
    download_col1, download_col2 = st.columns(2)
    with download_col1:
        analytics_export = pd.DataFrame(
            [
                {"metric": "total_orders", "value": summary["total_orders"]},
                {"metric": "total_revenue", "value": summary["total_revenue"]},
                {"metric": "pending_orders", "value": summary["pending_orders"]},
                {"metric": "delivered_orders", "value": summary["delivered_orders"]},
                {"metric": "unique_regions", "value": summary["unique_regions"]},
            ]
        )
        st.download_button(
            "Download analytics summary CSV",
            data=analytics_export.to_csv(index=False).encode("utf-8"),
            file_name=f"analytics_summary_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv",
            use_container_width=True,
        )
    with download_col2:
        st.download_button(
            "Download detailed orders CSV",
            data=order_frame.to_csv(index=False).encode("utf-8"),
            file_name=f"analytics_orders_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv",
            use_container_width=True,
        )


def render_audit_page() -> None:
    action_filter = st.selectbox(
        "Audit action filter",
        ["All", "login", "order_create", "order_update", "order_cancel", "warehouse_notification"],
    )
    params = {"limit": 150}
    if action_filter != "All":
        params["action"] = action_filter

    logs = safe_fetch("/audit-logs", params=params)
    audit_frame = prepare_audit_frame(logs)

    st.markdown(
        """
        <div class="hero-shell">
            <div class="eyebrow">Audit Logs</div>
            <div class="hero-title">Traceable system activity across users, orders, and notifications</div>
            <div class="hero-copy">Every login, order creation, update, cancellation, and queue-driven notification is recorded for accountability.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("")

    if audit_frame.empty:
        st.info("No audit events are visible for the current scope.")
        return

    total_events = len(audit_frame)
    order_events = int(audit_frame["action"].str.startswith("order_").sum())
    login_events = int((audit_frame["action"] == "login").sum())
    notification_events = int((audit_frame["action"] == "warehouse_notification").sum())

    metric_cols = st.columns(4)
    metrics = [
        ("Events", str(total_events), "Audit rows returned with the current filters."),
        ("Order actions", str(order_events), "Create, update, and cancel operations."),
        ("Logins", str(login_events), "Successful authentication events."),
        ("Notifications", str(notification_events), "Queue-processed warehouse alerts."),
    ]
    for column, metric in zip(metric_cols, metrics):
        with column:
            render_metric_card(*metric)

    timeline_col, table_col = st.columns([1.0, 1.25], gap="large")
    with timeline_col:
        render_section_title("Recent Timeline", "The newest events appear first.")
        for _, row in audit_frame.head(12).iterrows():
            st.markdown(
                f"""
                <div class="timeline-card">
                    <div class="eyebrow">{row['action'].replace('_', ' ')}</div>
                    <h4 style="margin:0.15rem 0 0.3rem 0;">{row['description']}</h4>
                    <div class="small-muted">{row['actor_username']} · {row['created_display']}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    with table_col:
        render_section_title("Audit Table", "Structured log data for review and CSV export.")
        display_frame = audit_frame[
            ["id", "actor_username", "action", "description", "target_type", "target_id", "created_display"]
        ].rename(
            columns={
                "id": "Log ID",
                "actor_username": "Actor",
                "action": "Action",
                "description": "Description",
                "target_type": "Target Type",
                "target_id": "Target ID",
                "created_display": "Created",
            }
        )
        st.dataframe(display_frame, use_container_width=True, hide_index=True)
        st.download_button(
            "Download audit logs CSV",
            data=audit_frame.to_csv(index=False).encode("utf-8"),
            file_name=f"audit_logs_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv",
            use_container_width=True,
        )


def main() -> None:
    init_session_state()
    apply_theme()

    if not st.session_state.current_user:
        render_public_landing()
        return

    try:
        page = render_sidebar()
        apply_theme()
        if page == "Overview":
            render_overview_page()
        elif page == "Orders":
            render_orders_page()
        elif page == "Analytics":
            render_analytics_page()
        else:
            render_audit_page()
    except ApiError as exc:
        if exc.status_code == 401:
            logout_user()
            st.warning("Your session expired. Please sign in again.")
            st.rerun()
        st.error(exc.message)


if __name__ == "__main__":
    main()
