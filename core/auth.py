from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import timedelta
from html import escape

import streamlit as st
import streamlit.components.v1 as components

from core.config import DEFAULT_PAGE_BY_ROLE, DEFAULT_VIEW_BY_ROLE, settings
from core.database import get_session
from core.utils import NotFoundError, utcnow
from services import audit_service, user_service


SESSION_TOKEN_KEY = "geo_app_session_token"
CURRENT_USER_KEY = "geo_app_user_id"
LOGOUT_PENDING_KEY = "_geo_app_logout_pending"


def _cookie_name() -> str:
    return settings.browser_cookie_name


def _cookie_secret() -> bytes:
    return settings.cookie_secret.encode("utf-8")


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def _b64decode(raw: str) -> bytes:
    padding = "=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode(f"{raw}{padding}")


def build_browser_session_cookie(user, session_token: str) -> str:
    payload = {
        "user_id": user.id,
        "username": user.username,
        "role": user.role,
        "session_token": session_token,
        "expires_at": int((utcnow() + timedelta(hours=settings.session_duration_hours)).timestamp()),
    }
    encoded = _b64encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signature = hmac.new(_cookie_secret(), encoded.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"


def parse_browser_session_cookie(cookie_value: str | None) -> dict[str, str | int] | None:
    if not cookie_value or "." not in cookie_value:
        return None
    encoded, signature = cookie_value.rsplit(".", 1)
    expected = hmac.new(_cookie_secret(), encoded.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        payload = json.loads(_b64decode(encoded))
    except (ValueError, json.JSONDecodeError):
        return None
    expires_at = int(payload.get("expires_at", 0))
    if expires_at <= int(utcnow().timestamp()):
        return None
    return payload


def _browser_cookie_value() -> str | None:
    try:
        return st.context.cookies.get(_cookie_name())
    except Exception:
        return None


def _set_cookie_script(cookie_value: str) -> None:
    max_age_seconds = settings.session_duration_hours * 3600
    secure = "Secure;" if str(getattr(st.context, "url", "")).startswith("https://") else ""
    components.html(
        f"""
        <script>
            document.cookie = "{escape(_cookie_name())}={escape(cookie_value)}; path=/; max-age={max_age_seconds}; SameSite=Lax; {secure}";
        </script>
        """,
        height=0,
    )


def _clear_cookie_script() -> None:
    components.html(
        f"""
        <script>
            document.cookie = "{escape(_cookie_name())}=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT; SameSite=Lax";
        </script>
        """,
        height=0,
    )


def login_user(username: str, password: str):
    with get_session() as session:
        user = user_service.authenticate_user(session, username, password)
        token = user_service.start_user_session(session, user)
        audit_service.log_action(
            session,
            actor=user,
            action="auth.login",
            entity_type="user",
            entity_id=str(user.id),
            details={"username": user.username},
        )
    st.session_state[SESSION_TOKEN_KEY] = token
    st.session_state[CURRENT_USER_KEY] = user.id
    st.session_state.pop(LOGOUT_PENDING_KEY, None)
    return user


def logout_current_user() -> None:
    token = st.session_state.get(SESSION_TOKEN_KEY)
    if not token:
        payload = parse_browser_session_cookie(_browser_cookie_value())
        token = str(payload.get("session_token")) if payload else None

    with get_session() as session:
        current_user = user_service.user_from_session_token(session, token) if token else None
        if token:
            user_service.end_user_session(session, token)
        if current_user:
            audit_service.log_action(
                session,
                actor=current_user,
                action="auth.logout",
                entity_type="user",
                entity_id=str(current_user.id),
                details={"username": current_user.username},
            )

    st.session_state.pop(SESSION_TOKEN_KEY, None)
    st.session_state.pop(CURRENT_USER_KEY, None)
    st.session_state[LOGOUT_PENDING_KEY] = True


def _restore_from_browser_cookie():
    payload = parse_browser_session_cookie(_browser_cookie_value())
    if not payload:
        return None

    cookie_token = str(payload["session_token"])
    with get_session() as session:
        user = user_service.user_from_session_token(session, cookie_token)
        if not user:
            try:
                user = user_service.get_user_by_id(session, int(payload["user_id"]))
            except NotFoundError:
                return None
            if not user.is_active or user.username != payload["username"] or user.role != payload["role"]:
                return None
            cookie_token = user_service.start_user_session(session, user)

    st.session_state[SESSION_TOKEN_KEY] = cookie_token
    st.session_state[CURRENT_USER_KEY] = user.id
    st.session_state.pop(LOGOUT_PENDING_KEY, None)
    return user


def get_current_user():
    suppress_restore = st.session_state.get(LOGOUT_PENDING_KEY, False)
    if suppress_restore and not _browser_cookie_value():
        st.session_state.pop(LOGOUT_PENDING_KEY, None)
        suppress_restore = False

    token = st.session_state.get(SESSION_TOKEN_KEY)
    if token:
        with get_session() as session:
            user = user_service.user_from_session_token(session, token)
        if user:
            st.session_state[CURRENT_USER_KEY] = user.id
            st.session_state.pop(LOGOUT_PENDING_KEY, None)
            return user
        st.session_state.pop(SESSION_TOKEN_KEY, None)
        st.session_state.pop(CURRENT_USER_KEY, None)

    if suppress_restore:
        return None
    return _restore_from_browser_cookie()


def sync_browser_session(user) -> None:
    current_cookie = _browser_cookie_value()
    session_token = st.session_state.get(SESSION_TOKEN_KEY)

    if user and session_token:
        current_payload = parse_browser_session_cookie(current_cookie)
        cookie_matches_session = bool(
            current_payload
            and str(current_payload.get("session_token")) == session_token
            and int(current_payload.get("user_id", 0)) == int(user.id)
            and current_payload.get("role") == user.role
            and current_payload.get("username") == user.username
        )
        if not cookie_matches_session:
            desired_cookie = build_browser_session_cookie(user, session_token)
            _set_cookie_script(desired_cookie)
        st.session_state.pop(LOGOUT_PENDING_KEY, None)
        return

    if current_cookie or st.session_state.get(LOGOUT_PENDING_KEY):
        _clear_cookie_script()
    if not current_cookie:
        st.session_state.pop(LOGOUT_PENDING_KEY, None)


def set_active_view(view: str) -> None:
    st.query_params["view"] = view


def ensure_authenticated(allowed_roles: list[str] | None = None):
    user = get_current_user()
    if not user:
        set_active_view("auth")
        st.rerun()
    if allowed_roles and user.role not in allowed_roles:
        set_active_view(DEFAULT_VIEW_BY_ROLE[user.role])
        st.rerun()
    return user


def redirect_after_login(user) -> None:
    set_active_view(DEFAULT_VIEW_BY_ROLE[user.role])
    st.rerun()


def require_anonymous() -> None:
    user = get_current_user()
    if user:
        set_active_view(DEFAULT_VIEW_BY_ROLE[user.role])
        st.rerun()


def redirect_legacy_page(view: str) -> None:
    set_active_view(view)
    st.switch_page("app.py")


def default_app_path_for_role(role: str) -> str:
    return DEFAULT_PAGE_BY_ROLE[role]
