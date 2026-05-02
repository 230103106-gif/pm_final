from __future__ import annotations

import json
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

import h3
import streamlit as st

from core.config import (
    DEFAULT_PAGE_BY_ROLE,
    ROLE_ADMIN,
    ROLE_CUSTOMER,
    ROLE_LABELS,
    ROLE_NAVIGATION,
    ROLE_WAREHOUSE,
    SEED_DATA_PATH,
    STATUS_COLORS,
    settings,
)


class AppError(Exception):
    """Base application exception."""


class AuthenticationError(AppError):
    """Raised when a login attempt or session is invalid."""


class AuthorizationError(AppError):
    """Raised when an actor is not allowed to perform an action."""


class ValidationError(AppError):
    """Raised when a business rule or input validation fails."""


class NotFoundError(AppError):
    """Raised when an expected entity does not exist."""


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def json_dumps(payload: dict[str, Any] | list[Any] | None) -> str:
    return json.dumps(payload or {}, default=str, ensure_ascii=True)


def json_loads(payload: str | None) -> dict[str, Any]:
    if not payload:
        return {}
    return json.loads(payload)


def currency(amount: float) -> str:
    return f"${amount:,.2f}"


def configure_page(title: str, icon: str = "🪑", sidebar_state: str = "expanded") -> None:
    st.set_page_config(
        page_title=f"{title} | {settings.app_name}",
        page_icon=icon,
        layout="wide",
        initial_sidebar_state=sidebar_state,
    )


def inject_styles() -> None:
    st.markdown(
        """
        <style>
            .stApp {
                background:
                    radial-gradient(circle at top left, rgba(23, 98, 79, 0.10), transparent 28%),
                    radial-gradient(circle at top right, rgba(24, 34, 45, 0.07), transparent 22%),
                    linear-gradient(180deg, #f7f4ef 0%, #f2efe8 100%);
                color: #18222d;
                font-family: "Avenir Next", "Segoe UI", "Helvetica Neue", sans-serif;
            }
            .block-container {
                padding-top: 1.4rem;
                padding-bottom: 2rem;
            }
            [data-testid="stSidebarNav"],
            [data-testid="stSidebarNavSeparator"] {
                display: none !important;
            }
            header[data-testid="stHeader"],
            [data-testid="stToolbar"],
            [data-testid="stDecoration"],
            [data-testid="stStatusWidget"],
            button[kind="header"],
            #MainMenu,
            footer {
                display: none !important;
                visibility: hidden !important;
            }
            .hero-card, .metric-card, .surface-card, .table-card {
                border: 1px solid rgba(24, 34, 45, 0.08);
                border-radius: 20px;
                background: rgba(255, 255, 255, 0.92);
                box-shadow: 0 18px 42px rgba(24, 34, 45, 0.08);
            }
            .hero-card {
                padding: 1.5rem 1.5rem 1.25rem 1.5rem;
                background:
                    linear-gradient(135deg, rgba(255, 255, 255, 0.98), rgba(248, 245, 240, 0.98)),
                    rgba(255,255,255,0.94);
            }
            .metric-card {
                padding: 1rem 1.1rem;
                min-height: 122px;
            }
            .metric-label {
                color: #5b6875;
                font-size: 0.84rem;
                letter-spacing: 0.04em;
                text-transform: uppercase;
                margin-bottom: 0.35rem;
            }
            .metric-value {
                font-size: 1.85rem;
                font-weight: 700;
                color: #12202b;
                line-height: 1.2;
            }
            .metric-note {
                color: #415262;
                font-size: 0.92rem;
                margin-top: 0.45rem;
            }
            .page-eyebrow {
                color: #17624f;
                font-size: 0.82rem;
                letter-spacing: 0.08em;
                text-transform: uppercase;
                font-weight: 700;
                margin-bottom: 0.25rem;
            }
            .page-title {
                font-size: 2rem;
                font-weight: 700;
                color: #152534;
                margin-bottom: 0.25rem;
            }
            .page-subtitle {
                color: #4d5d6d;
                font-size: 1rem;
                margin-bottom: 0;
            }
            .surface-card, .table-card {
                padding: 1rem 1.1rem;
            }
            .status-pill {
                display: inline-flex;
                align-items: center;
                gap: 0.4rem;
                padding: 0.28rem 0.72rem;
                border-radius: 999px;
                color: white;
                font-size: 0.84rem;
                font-weight: 600;
                line-height: 1.1;
            }
            .mini-note {
                color: #5f6c79;
                font-size: 0.88rem;
            }
            .sidebar-user {
                border: 1px solid rgba(24, 34, 45, 0.08);
                border-radius: 18px;
                background: rgba(255, 255, 255, 0.86);
                padding: 0.9rem 1rem;
                margin-bottom: 0.9rem;
            }
            .sidebar-nav-title {
                color: #5b6875;
                font-size: 0.76rem;
                letter-spacing: 0.08em;
                text-transform: uppercase;
                font-weight: 700;
                margin: 0.4rem 0 0.6rem 0.1rem;
            }
            .detail-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
                gap: 0.9rem;
                margin-top: 0.8rem;
            }
            .detail-item {
                border: 1px solid rgba(24, 34, 45, 0.07);
                border-radius: 16px;
                padding: 0.75rem 0.85rem;
                background: rgba(247, 244, 239, 0.7);
            }
            .detail-label {
                color: #607180;
                font-size: 0.78rem;
                letter-spacing: 0.03em;
                text-transform: uppercase;
            }
            .detail-value {
                color: #172532;
                font-weight: 600;
                margin-top: 0.2rem;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def initialize_page(
    title: str,
    icon: str = "🪑",
    allowed_roles: list[str] | None = None,
    anonymous: bool = False,
    sidebar_state: str = "expanded",
):
    from core.auth import ensure_authenticated, get_current_user
    from core.database import init_db

    configure_page(title, icon, sidebar_state=sidebar_state)
    inject_styles()
    init_db()
    user = get_current_user() if anonymous else ensure_authenticated(allowed_roles)
    render_sidebar(user)
    return user


def render_sidebar(user) -> None:
    import core.auth as auth

    if not user:
        return

    with st.sidebar:
        st.markdown(
            f"""
            <div class="sidebar-user">
                <div class="page-eyebrow">Furniture Operations</div>
                <div style="font-size:1.1rem;font-weight:700;color:#152534;">{user.full_name}</div>
                <div class="mini-note">{ROLE_LABELS.get(user.role, "Account")}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown('<div class="sidebar-nav-title">Navigation</div>', unsafe_allow_html=True)
        for item in ROLE_NAVIGATION.get(user.role, []):
            st.page_link(item["path"], label=item["label"], icon=item["icon"])
        if st.button("Log out", type="secondary", use_container_width=True):
            auth.logout_current_user()
            st.switch_page("pages/1_Login.py")


def render_page_header(eyebrow: str, title: str, subtitle: str) -> None:
    st.markdown(
        f"""
        <div class="hero-card">
            <div class="page-eyebrow">{eyebrow}</div>
            <div class="page-title">{title}</div>
            <p class="page-subtitle">{subtitle}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_metric_card(label: str, value: str, note: str) -> None:
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label">{label}</div>
            <div class="metric-value">{value}</div>
            <div class="metric-note">{note}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_status_badge(status: str) -> str:
    color = STATUS_COLORS.get(status, "#344054")
    return f'<span class="status-pill" style="background:{color};">{status}</span>'


def render_detail_grid(details: dict[str, str]) -> None:
    body = "".join(
        f"""
        <div class="detail-item">
            <div class="detail-label">{label}</div>
            <div class="detail-value">{value}</div>
        </div>
        """
        for label, value in details.items()
    )
    st.markdown(f'<div class="detail-grid">{body}</div>', unsafe_allow_html=True)


def parse_seed_reference() -> dict[str, str]:
    if not SEED_DATA_PATH.exists():
        return {}
    payload = json.loads(SEED_DATA_PATH.read_text(encoding="utf-8"))
    mapping: dict[str, str] = {}
    for city in payload.get("cities", []):
        region = h3.latlng_to_cell(city["latitude"], city["longitude"], settings.h3_resolution)
        mapping[region] = f'{city["name"]}, {city["state"]}'
    return mapping


@lru_cache(maxsize=1)
def region_label_map() -> dict[str, str]:
    return parse_seed_reference()


def region_label(region: str | None) -> str:
    if not region:
        return "Unassigned"
    mapping = region_label_map()
    if region in mapping:
        return mapping[region]
    return f"{region[:7]}…"


def next_page_for_role(role: str) -> str:
    return DEFAULT_PAGE_BY_ROLE[role]
