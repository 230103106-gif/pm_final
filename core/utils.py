from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from functools import lru_cache
from html import escape
from typing import Any

import h3
import streamlit as st
import streamlit.components.v1 as components

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
    theme = st.session_state.get("app_theme", "light")
    st.markdown(
        """
        <style>
            :root {
                --primary: #B45309;
                --primary-soft: #FFF3D7;
                --secondary: #0F766E;
                --accent: #D97706;
                --warning: #F59E0B;
                --background: #FBF7F0;
                --app-background: linear-gradient(180deg, #FFF8ED 0%, #F6E8D0 56%, #FFFDF8 100%);
                --surface: rgba(255, 252, 246, 0.96);
                --surface-alt: #FFF7ED;
                --field-bg: #FFFDF8;
                --field-border: rgba(120, 79, 45, 0.14);
                --progress-track: #E9DED1;
                --text: #1F2933;
                --muted: #756A5B;
                --border: rgba(120, 79, 45, 0.16);
                --shadow: 0 18px 48px rgba(92, 55, 25, 0.12);
                --radius-xl: 18px;
                --radius-lg: 16px;
                --radius-md: 12px;
            }
            :root[data-theme="dark"] {
                --primary: #FBBF24;
                --primary-soft: rgba(251, 191, 36, 0.16);
                --secondary: #5EEAD4;
                --accent: #F97316;
                --warning: #F59E0B;
                --background: #16130F;
                --app-background: linear-gradient(180deg, #15110D 0%, #23180F 55%, #11100E 100%);
                --surface: rgba(38, 32, 25, 0.94);
                --surface-alt: rgba(56, 46, 34, 0.92);
                --field-bg: rgba(30, 26, 22, 0.92);
                --field-border: rgba(255, 237, 213, 0.14);
                --progress-track: rgba(255, 237, 213, 0.14);
                --text: #FFF7ED;
                --muted: #D6C7B5;
                --border: rgba(255, 237, 213, 0.16);
                --shadow: 0 18px 52px rgba(0, 0, 0, 0.36);
            }
            .stApp {
                background: var(--app-background);
                color: var(--text);
                font-family: "Inter", "Segoe UI", "Helvetica Neue", sans-serif;
            }
            .block-container {
                max-width: 1220px;
                padding-top: 1.2rem;
                padding-bottom: 5rem;
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
                padding: 1.55rem 1.7rem;
                margin-bottom: 1.15rem;
            }
            .topbar-card {
                border: 1px solid var(--border);
                border-radius: var(--radius-lg);
                background: var(--surface);
                box-shadow: var(--shadow);
                padding: 1.05rem 1.15rem;
                margin-bottom: 1.15rem;
                backdrop-filter: blur(10px);
                min-height: 7.4rem;
                display: flex;
                flex-direction: column;
                justify-content: center;
            }
            .scope-card {
                border: 1px solid var(--border);
                border-radius: var(--radius-lg);
                background: var(--surface);
                box-shadow: var(--shadow);
                min-height: 3.35rem;
                padding: 0.55rem 0.8rem;
                margin-bottom: 0.7rem;
                display: flex;
                align-items: center;
                justify-content: center;
                backdrop-filter: blur(10px);
            }
            .metric-card {
                padding: 1.1rem 1.1rem 1rem 1.1rem;
                min-height: 122px;
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
            .section-gap {
                height: 1.6rem;
            }
            .section-heading {
                margin: 0.25rem 0 1rem 0;
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
                grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
                gap: 0.8rem;
                margin: 0.35rem 0 1rem 0;
            }
            .detail-item {
                border-radius: var(--radius-md);
                border: 1px solid var(--field-border);
                background: var(--field-bg);
                padding: 0.8rem 0.9rem;
                min-width: 0;
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
                overflow-wrap: anywhere;
            }
            .order-list {
                display: grid;
                gap: 0.85rem;
                margin: 0.45rem 0 1.05rem 0;
            }
            .order-card {
                border: 1px solid var(--border);
                border-radius: var(--radius-lg);
                background: var(--surface);
                box-shadow: var(--shadow);
                padding: 1rem 1.05rem;
            }
            .order-card-head {
                display: flex;
                justify-content: space-between;
                align-items: flex-start;
                gap: 0.9rem;
            }
            .order-title {
                color: var(--text);
                font-size: 1rem;
                font-weight: 800;
                line-height: 1.25;
                overflow-wrap: anywhere;
            }
            .order-subtitle {
                color: var(--muted);
                font-size: 0.9rem;
                margin-top: 0.2rem;
            }
            .order-card-grid {
                display: grid;
                grid-template-columns: repeat(4, minmax(0, 1fr));
                gap: 0.65rem;
                margin-top: 0.85rem;
            }
            .order-field {
                border-radius: 10px;
                background: var(--field-bg);
                border: 1px solid var(--field-border);
                padding: 0.62rem 0.68rem;
                min-width: 0;
            }
            .order-field-label {
                color: var(--muted);
                font-size: 0.68rem;
                font-weight: 800;
                letter-spacing: 0.06em;
                text-transform: uppercase;
            }
            .order-field-value {
                color: var(--text);
                font-size: 0.88rem;
                font-weight: 700;
                margin-top: 0.16rem;
                overflow-wrap: anywhere;
            }
            .focus-stack {
                display: grid;
                gap: 0.9rem;
                margin-top: 0.35rem;
            }
            .focus-card {
                border: 1px solid var(--border);
                border-radius: var(--radius-lg);
                background: var(--surface);
                box-shadow: var(--shadow);
                padding: 1.05rem 1.15rem;
            }
            .focus-card-value {
                color: var(--text);
                font-size: 1.45rem;
                font-weight: 850;
                line-height: 1;
                margin-bottom: 0.35rem;
            }
            .shortcut-spacer {
                height: 1rem;
            }
            .analytics-card {
                border: 1px solid var(--border);
                border-radius: var(--radius-lg);
                background: var(--surface);
                box-shadow: var(--shadow);
                padding: 1rem 1rem 0.75rem 1rem;
                margin-bottom: 1.05rem;
                overflow: hidden;
            }
            .status-breakdown,
            .region-list,
            .h3-list,
            .detail-list {
                display: grid;
                gap: 0.65rem;
                margin-top: 0.65rem;
            }
            .status-row,
            .region-row,
            .h3-row,
            .detail-row {
                border: 1px solid rgba(15, 23, 42, 0.08);
                border-radius: 12px;
                background: var(--surface);
                padding: 0.78rem 0.85rem;
            }
            .region-row {
                display: grid;
                grid-template-columns: minmax(0, 1fr) auto;
                gap: 1rem;
                align-items: center;
            }
            .h3-row {
                display: grid;
                grid-template-columns: minmax(0, 1fr) minmax(130px, 0.65fr) auto;
                gap: 1rem;
                align-items: center;
            }
            .detail-row {
                display: grid;
                gap: 0.35rem;
            }
            .row-title {
                color: var(--text);
                font-weight: 800;
                overflow-wrap: anywhere;
            }
            .row-note {
                color: var(--muted);
                font-size: 0.84rem;
                margin-top: 0.14rem;
                overflow-wrap: anywhere;
            }
            .row-number {
                color: var(--text);
                font-size: 1.05rem;
                font-weight: 850;
                text-align: right;
                white-space: nowrap;
            }
            .progress-track {
                width: 100%;
                height: 9px;
                border-radius: 999px;
                background: var(--progress-track);
                overflow: hidden;
                margin-top: 0.55rem;
            }
            .progress-bar {
                height: 100%;
                border-radius: inherit;
                background: linear-gradient(90deg, var(--primary), var(--secondary));
            }
            .product-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(245px, 1fr));
                gap: 0.85rem;
                margin: 0.75rem 0 1.1rem 0;
            }
            .product-list-image {
                min-height: 154px;
                border-radius: 14px;
                background-size: cover;
                background-position: center;
                border: 1px solid var(--field-border);
                display: flex;
                align-items: flex-start;
                justify-content: flex-start;
                padding: 0.78rem;
                margin-bottom: 0.88rem;
                overflow: hidden;
            }
            .product-list-card,
            .event-card,
            .audit-card {
                border: 1px solid var(--border);
                border-radius: var(--radius-lg);
                background: var(--surface);
                box-shadow: var(--shadow);
                padding: 1rem 1.05rem;
                min-width: 0;
            }
            .product-card-top,
            .event-card-top,
            .audit-card-top {
                display: flex;
                justify-content: space-between;
                align-items: flex-start;
                gap: 0.85rem;
            }
            .product-meta-grid,
            .event-meta-grid,
            .audit-meta-grid {
                display: grid;
                grid-template-columns: repeat(2, minmax(0, 1fr));
                gap: 0.62rem;
                margin-top: 0.78rem;
            }
            .event-list,
            .audit-list {
                display: grid;
                gap: 0.8rem;
                margin: 0.75rem 0 1rem 0;
            }
            .mini-pill {
                display: inline-flex;
                align-items: center;
                justify-content: center;
                border-radius: 999px;
                padding: 0.28rem 0.62rem;
                background: #EEF2FF;
                color: #3730A3;
                font-size: 0.74rem;
                font-weight: 800;
                white-space: nowrap;
            }
            .mini-pill.is-warning {
                background: #FEF3C7;
                color: #92400E;
            }
            .mini-pill.is-muted {
                background: #F1F5F9;
                color: #475569;
            }
            .mini-pill.is-danger {
                background: #FEE2E2;
                color: #B42318;
            }
            .product-art {
                min-height: 148px;
                border-radius: 18px;
                background:
                    linear-gradient(140deg, rgba(180, 83, 9, 0.12), rgba(15, 118, 110, 0.12)),
                    linear-gradient(180deg, var(--surface) 0%, var(--surface-alt) 100%);
                background-size: cover;
                background-position: center;
                border: 1px solid var(--field-border);
                display: flex;
                align-items: flex-start;
                justify-content: flex-start;
                padding: 1rem;
                margin-bottom: 0.9rem;
                overflow: hidden;
            }
            .product-art-badge {
                border-radius: 999px;
                background: rgba(255, 248, 237, 0.92);
                color: var(--primary);
                font-size: 0.76rem;
                font-weight: 700;
                padding: 0.35rem 0.65rem;
                box-shadow: 0 8px 24px rgba(38, 32, 25, 0.12);
            }
            .product-art-mark {
                font-size: 2rem;
                font-weight: 800;
                color: rgba(17, 24, 39, 0.84);
            }
            .app-chip {
                display: inline-flex;
                align-items: center;
                justify-content: center;
                gap: 0.45rem;
                border-radius: 999px;
                padding: 0.48rem 0.78rem;
                background: var(--primary-soft);
                color: var(--primary);
                font-size: 0.84rem;
                font-weight: 700;
                width: 100%;
                text-align: center;
            }
            div[data-baseweb="input"] > div,
            div[data-baseweb="base-input"] > div,
            div[data-baseweb="select"] > div,
            .stTextArea textarea {
                border-radius: 14px !important;
                border-color: var(--field-border) !important;
                background: var(--field-bg) !important;
                color: var(--text) !important;
            }
            input,
            textarea,
            [data-baseweb="select"] {
                color: var(--text) !important;
            }
            input::placeholder,
            textarea::placeholder {
                color: var(--muted) !important;
                opacity: 0.9 !important;
            }
            [data-testid="stWidgetLabel"] p,
            [data-testid="stWidgetLabel"] label,
            .stRadio label,
            .stCheckbox label,
            .stToggle label,
            .stSelectbox label,
            .stTextInput label,
            .stTextArea label,
            .stNumberInput label {
                color: var(--text) !important;
            }
            .stRadio p,
            .stCheckbox p,
            .stToggle p {
                color: var(--text) !important;
            }
            .stButton > button,
            .stDownloadButton > button {
                border-radius: 14px !important;
                font-weight: 700 !important;
                min-height: 2.8rem;
                border: 1px solid var(--border) !important;
                background: var(--surface) !important;
                color: var(--text) !important;
                white-space: nowrap !important;
                overflow: hidden !important;
                text-overflow: ellipsis !important;
            }
            .stButton > button[kind="primary"],
            .stDownloadButton > button[kind="primary"],
            .stFormSubmitButton button[kind="primary"],
            button[data-testid="stBaseButton-primary"] {
                background: linear-gradient(135deg, var(--primary), var(--secondary)) !important;
                color: white !important;
                border: none !important;
            }
            button[role="tab"][aria-selected="true"] p {
                color: var(--primary) !important;
                font-weight: 800 !important;
            }
            div[data-baseweb="tab-highlight"] {
                background-color: var(--primary) !important;
            }
            button[data-signout-button="true"] {
                background: #FEF2F2 !important;
                color: #B42318 !important;
                border: 1px solid #FDA29B !important;
                box-shadow: 0 10px 26px rgba(180, 35, 24, 0.10) !important;
                min-height: 3.35rem !important;
            }
            button[data-signout-button="true"]:hover {
                background: #FEE4E2 !important;
                border-color: #F97066 !important;
                color: #912018 !important;
            }
            div[data-testid="stDataFrame"] {
                border: 1px solid var(--border);
                border-radius: var(--radius-md);
                overflow: hidden;
                box-shadow: 0 8px 24px rgba(15, 23, 42, 0.05);
            }
            div[data-testid="stForm"] {
                border-radius: var(--radius-lg);
                border-color: var(--border);
                background: color-mix(in srgb, var(--surface) 76%, transparent);
            }
            .top-nav-shell {
                margin: 0 0 0.42rem 0;
            }
            .auth-backdrop {
                position: fixed;
                inset: 0;
                z-index: 0;
                background-size: cover;
                background-position: center;
            }
            .auth-tint {
                position: fixed;
                inset: 0;
                z-index: 0;
                background:
                    radial-gradient(circle at 76% 18%, rgba(255, 237, 213, 0.75), transparent 34%),
                    linear-gradient(180deg, rgba(255, 248, 237, 0.18), rgba(255, 248, 237, 0.48));
                pointer-events: none;
            }
            .block-container {
                position: relative;
                z-index: 1;
            }
            .auth-copy {
                min-height: 58vh;
                display: flex;
                flex-direction: column;
                justify-content: center;
                color: #FFF7ED;
                padding: 2rem 0 2rem 0;
            }
            .auth-pill {
                width: fit-content;
                border: 1px solid rgba(255, 247, 237, 0.34);
                border-radius: 999px;
                background: rgba(255, 247, 237, 0.14);
                color: #FFF7ED;
                font-weight: 800;
                padding: 0.52rem 0.8rem;
                backdrop-filter: blur(12px);
            }
            .auth-title {
                max-width: 650px;
                color: #FFF7ED;
                font-size: clamp(2.6rem, 6vw, 5rem);
                line-height: 0.98;
                font-weight: 900;
                margin-top: 1.3rem;
                letter-spacing: 0;
            }
            .auth-subtitle {
                max-width: 620px;
                color: rgba(255, 247, 237, 0.88);
                font-size: 1.08rem;
                line-height: 1.55;
                margin-top: 1.15rem;
            }
            .auth-stats {
                display: grid;
                grid-template-columns: repeat(3, minmax(0, 1fr));
                gap: 0.85rem;
                max-width: 540px;
                margin-top: 1.45rem;
            }
            .auth-stats div {
                border: 1px solid rgba(255, 247, 237, 0.2);
                border-radius: 16px;
                background: rgba(42, 27, 15, 0.34);
                padding: 0.9rem 1rem;
                backdrop-filter: blur(12px);
            }
            .auth-stats strong {
                display: block;
                color: #FFE8A3;
                font-size: 1.05rem;
            }
            .auth-stats span {
                color: rgba(255, 247, 237, 0.78);
                font-size: 0.82rem;
            }
            .auth-panel-heading {
                border: 1px solid var(--border);
                border-radius: 24px;
                background: color-mix(in srgb, var(--surface) 88%, transparent);
                box-shadow: var(--shadow);
                padding: 1.35rem 1.45rem;
                margin-top: 5.7rem;
                margin-bottom: 1rem;
                backdrop-filter: blur(18px);
            }
            .auth-panel-title {
                color: var(--text);
                font-size: 2rem;
                font-weight: 900;
                line-height: 1.1;
            }
            .auth-panel-note {
                color: var(--muted);
                margin-top: 0.45rem;
                font-size: 0.96rem;
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
                .order-card-grid,
                .region-row,
                .h3-row,
                .detail-row,
                .product-meta-grid,
                .event-meta-grid,
                .audit-meta-grid {
                    grid-template-columns: 1fr;
                }
                .row-number {
                    text-align: left;
                }
                .auth-copy {
                    min-height: auto;
                    padding-top: 1rem;
                }
                .auth-title {
                    font-size: 2.4rem;
                }
                .auth-stats {
                    grid-template-columns: 1fr;
                }
                .auth-panel-heading {
                    margin-top: 0;
                }
            }
        </style>
        """,
        unsafe_allow_html=True,
    )
    components.html(
        """
        <script>
            const appTheme = __APP_THEME__;
            const removeSubmitHints = () => {
                const doc = window.parent.document;
                doc.documentElement.dataset.theme = appTheme;
                doc.querySelectorAll('[title="Press Enter to submit form"]').forEach((node) => {
                    node.removeAttribute('title');
                });
                doc.querySelectorAll('button').forEach((button) => {
                    if (button.textContent.trim() === 'Sign out') {
                        button.dataset.signoutButton = 'true';
                    }
                });
            };
            removeSubmitHints();
            new MutationObserver(removeSubmitHints).observe(window.parent.document.body, {
                childList: true,
                subtree: true,
                attributes: true,
                attributeFilter: ['title']
            });
        </script>
        """.replace("__APP_THEME__", json.dumps(theme)),
        height=0,
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
        f'<div class="detail-item"><div class="detail-label">{escape(label)}</div>'
        f'<div class="detail-value">{escape(value)}</div></div>'
        for label, value in details.items()
    )
    st.markdown(f'<div class="detail-grid">{body}</div>', unsafe_allow_html=True)


def render_section_title(kicker: str, title: str, subtitle: str | None = None) -> None:
    subtitle_block = f'<div class="section-subtitle">{escape(subtitle)}</div>' if subtitle else ""
    st.markdown(
        f"""
        <div class="section-heading">
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
def seed_city_reference() -> list[dict[str, Any]]:
    if not SEED_DATA_PATH.exists():
        return []
    payload = json.loads(SEED_DATA_PATH.read_text(encoding="utf-8"))
    return payload.get("cities", [])


@lru_cache(maxsize=1)
def region_label_map() -> dict[str, str]:
    return parse_seed_reference()


def region_label(region: str | None) -> str:
    if not region:
        return "Unassigned"
    mapped = region_label_map().get(region)
    if mapped:
        return mapped
    try:
        latitude, longitude = h3.cell_to_latlng(region)
    except ValueError:
        return region
    cities = seed_city_reference()
    if not cities:
        return region
    nearest = min(
        cities,
        key=lambda city: math.hypot(float(city["latitude"]) - latitude, float(city["longitude"]) - longitude),
    )
    distance = math.hypot(float(nearest["latitude"]) - latitude, float(nearest["longitude"]) - longitude)
    if distance <= 0.45:
        return f'{nearest["name"]}, {nearest["state"]}'
    return region
