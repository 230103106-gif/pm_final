from __future__ import annotations

import json
from datetime import UTC, datetime
from functools import lru_cache
from html import escape
from typing import Any

import h3
import streamlit as st

from core.config import SEED_DATA_PATH, STATUS_COLORS, settings


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


def format_timestamp(value: datetime | None) -> str:
    return value.strftime("%b %d, %Y %H:%M") if value else "Pending"


def configure_page(title: str, icon: str = "🪑", sidebar_state: str = "collapsed") -> None:
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
            :root {
                --primary: #4F46E5;
                --primary-soft: #EEF2FF;
                --secondary: #06B6D4;
                --background: #F9FAFB;
                --surface: rgba(255, 255, 255, 0.96);
                --surface-alt: #F3F4F6;
                --text: #111827;
                --muted: #6B7280;
                --border: rgba(79, 70, 229, 0.10);
                --shadow: 0 18px 48px rgba(15, 23, 42, 0.08);
                --radius-xl: 28px;
                --radius-lg: 22px;
                --radius-md: 16px;
            }
            .stApp {
                background:
                    radial-gradient(circle at top left, rgba(79, 70, 229, 0.09), transparent 22%),
                    radial-gradient(circle at top right, rgba(6, 182, 212, 0.08), transparent 18%),
                    linear-gradient(180deg, #F9FAFB 0%, #EEF2FF 100%);
                color: var(--text);
                font-family: "Inter", "Segoe UI", "Helvetica Neue", sans-serif;
            }
            .block-container {
                max-width: 1180px;
                padding-top: 1rem;
                padding-bottom: 7.5rem;
            }
            section[data-testid="stSidebar"],
            button[data-testid="collapsedControl"],
            [data-testid="stSidebarNav"],
            [data-testid="stSidebarNavSeparator"] {
                display: none !important;
                visibility: hidden !important;
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
            div[data-testid="stVerticalBlockBorderWrapper"] {
                border-radius: var(--radius-md);
            }
            .hero-card,
            .metric-card,
            .surface-card,
            .table-card,
            .auth-card,
            .product-card {
                border: 1px solid var(--border);
                border-radius: var(--radius-lg);
                background: var(--surface);
                box-shadow: var(--shadow);
            }
            .hero-card {
                padding: 1.65rem 1.75rem;
                margin-bottom: 1rem;
            }
            .topbar-card {
                border: 1px solid var(--border);
                border-radius: var(--radius-lg);
                background: rgba(255, 255, 255, 0.84);
                box-shadow: 0 14px 40px rgba(15, 23, 42, 0.06);
                padding: 1rem 1.15rem;
                margin-bottom: 1rem;
                backdrop-filter: blur(10px);
            }
            .metric-card {
                padding: 1.1rem 1.1rem 1rem 1.1rem;
                min-height: 126px;
            }
            .metric-label {
                color: var(--muted);
                font-size: 0.8rem;
                text-transform: uppercase;
                letter-spacing: 0.08em;
                font-weight: 700;
            }
            .metric-value {
                color: var(--text);
                font-size: 1.9rem;
                line-height: 1.15;
                font-weight: 700;
                margin-top: 0.3rem;
            }
            .metric-note {
                color: var(--muted);
                font-size: 0.92rem;
                margin-top: 0.42rem;
            }
            .page-eyebrow {
                color: var(--secondary);
                font-size: 0.8rem;
                text-transform: uppercase;
                letter-spacing: 0.1em;
                font-weight: 700;
                margin-bottom: 0.35rem;
            }
            .page-title {
                color: var(--text);
                font-size: 2.2rem;
                line-height: 1.06;
                font-weight: 800;
                margin-bottom: 0.35rem;
            }
            .page-subtitle {
                color: var(--muted);
                font-size: 1rem;
                margin: 0;
                max-width: 860px;
            }
            .surface-card,
            .table-card,
            .auth-card,
            .product-card {
                padding: 1.15rem;
            }
            .section-kicker {
                color: var(--secondary);
                font-size: 0.78rem;
                text-transform: uppercase;
                letter-spacing: 0.08em;
                font-weight: 700;
                margin-bottom: 0.2rem;
            }
            .section-title {
                color: var(--text);
                font-size: 1.12rem;
                font-weight: 700;
                margin-bottom: 0.2rem;
            }
            .section-subtitle,
            .mini-note {
                color: var(--muted);
                font-size: 0.92rem;
            }
            .status-pill {
                display: inline-flex;
                align-items: center;
                justify-content: center;
                gap: 0.35rem;
                padding: 0.34rem 0.78rem;
                border-radius: 999px;
                color: white;
                font-size: 0.82rem;
                font-weight: 700;
                line-height: 1;
            }
            .detail-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
                gap: 0.8rem;
                margin-top: 0.8rem;
            }
            .detail-item {
                border-radius: var(--radius-md);
                border: 1px solid rgba(17, 24, 39, 0.06);
                background: linear-gradient(180deg, #FFFFFF 0%, #F9FAFB 100%);
                padding: 0.8rem 0.9rem;
            }
            .detail-label {
                color: var(--muted);
                font-size: 0.76rem;
                text-transform: uppercase;
                letter-spacing: 0.06em;
                font-weight: 700;
            }
            .detail-value {
                color: var(--text);
                font-weight: 700;
                margin-top: 0.22rem;
            }
            .product-art {
                min-height: 148px;
                border-radius: 18px;
                background:
                    linear-gradient(140deg, rgba(79, 70, 229, 0.10), rgba(6, 182, 212, 0.12)),
                    linear-gradient(180deg, #FFFFFF 0%, #EEF2FF 100%);
                border: 1px solid rgba(79, 70, 229, 0.08);
                display: flex;
                align-items: flex-end;
                justify-content: space-between;
                padding: 1rem;
                margin-bottom: 0.9rem;
            }
            .product-art-badge {
                border-radius: 999px;
                background: rgba(79, 70, 229, 0.12);
                color: var(--primary);
                font-size: 0.76rem;
                font-weight: 700;
                padding: 0.35rem 0.65rem;
            }
            .product-art-mark {
                font-size: 2rem;
                font-weight: 800;
                color: rgba(17, 24, 39, 0.84);
            }
            .app-chip {
                display: inline-flex;
                align-items: center;
                gap: 0.45rem;
                border-radius: 999px;
                padding: 0.42rem 0.78rem;
                background: rgba(79, 70, 229, 0.10);
                color: var(--primary);
                font-size: 0.84rem;
                font-weight: 700;
            }
            div[data-baseweb="input"] > div,
            div[data-baseweb="base-input"] > div,
            div[data-baseweb="select"] > div,
            .stTextArea textarea {
                border-radius: 14px !important;
                border-color: rgba(17, 24, 39, 0.12) !important;
                background: rgba(255, 255, 255, 0.95) !important;
            }
            .stButton > button,
            .stDownloadButton > button {
                border-radius: 14px !important;
                font-weight: 700 !important;
                min-height: 2.8rem;
                border: 1px solid rgba(17, 24, 39, 0.08) !important;
            }
            .stButton > button[kind="primary"],
            .stDownloadButton > button[kind="primary"] {
                background: linear-gradient(135deg, #4F46E5, #06B6D4) !important;
                color: white !important;
                border: none !important;
            }
            div[data-testid="stDataFrame"] {
                border: 1px solid var(--border);
                border-radius: var(--radius-md);
                overflow: hidden;
                box-shadow: 0 8px 24px rgba(15, 23, 42, 0.05);
            }
            @media (max-width: 720px) {
                .block-container {
                    padding-top: 0.8rem;
                    padding-bottom: 4rem;
                }
                .hero-card {
                    padding: 1.2rem;
                }
                .page-title {
                    font-size: 1.75rem;
                }
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
    sidebar_state: str = "collapsed",
):
    from core.auth import ensure_authenticated, get_current_user
    from core.database import init_db

    configure_page(title, icon, sidebar_state=sidebar_state)
    inject_styles()
    init_db()
    return get_current_user() if anonymous else ensure_authenticated(allowed_roles)


def render_page_header(eyebrow: str, title: str, subtitle: str) -> None:
    st.markdown(
        f"""
        <div class="hero-card">
            <div class="page-eyebrow">{escape(eyebrow)}</div>
            <div class="page-title">{escape(title)}</div>
            <p class="page-subtitle">{escape(subtitle)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_metric_card(label: str, value: str, note: str) -> None:
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label">{escape(label)}</div>
            <div class="metric-value">{escape(value)}</div>
            <div class="metric-note">{escape(note)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_status_badge(status: str) -> str:
    color = STATUS_COLORS.get(status, "#344054")
    return f'<span class="status-pill" style="background:{color};">{escape(status)}</span>'


def render_detail_grid(details: dict[str, str]) -> None:
    body = "".join(
        f"""
        <div class="detail-item">
            <div class="detail-label">{escape(label)}</div>
            <div class="detail-value">{escape(value)}</div>
        </div>
        """
        for label, value in details.items()
    )
    st.markdown(f'<div class="detail-grid">{body}</div>', unsafe_allow_html=True)


def render_section_title(kicker: str, title: str, subtitle: str | None = None) -> None:
    subtitle_block = f'<div class="section-subtitle">{escape(subtitle)}</div>' if subtitle else ""
    st.markdown(
        f"""
        <div style="margin-bottom:0.85rem;">
            <div class="section-kicker">{escape(kicker)}</div>
            <div class="section-title">{escape(title)}</div>
            {subtitle_block}
        </div>
        """,
        unsafe_allow_html=True,
    )


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
    return region_label_map().get(region, region)
