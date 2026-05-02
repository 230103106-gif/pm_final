from __future__ import annotations

import streamlit as st

from core.config import DEFAULT_PAGE_BY_ROLE
from core.database import get_session
from core.utils import AuthenticationError
from services import audit_service, user_service


SESSION_TOKEN_KEY = "geo_app_session_token"
CURRENT_USER_KEY = "geo_app_user_id"


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
    return user


def logout_current_user() -> None:
    token = st.session_state.get(SESSION_TOKEN_KEY)
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


def get_current_user():
    token = st.session_state.get(SESSION_TOKEN_KEY)
    if not token:
        return None
    with get_session() as session:
        return user_service.user_from_session_token(session, token)


def ensure_authenticated(allowed_roles: list[str] | None = None):
    user = get_current_user()
    if not user:
        st.switch_page("pages/1_Login.py")
        st.stop()
    if allowed_roles and user.role not in allowed_roles:
        st.switch_page(DEFAULT_PAGE_BY_ROLE[user.role])
        st.stop()
    return user


def redirect_after_login(user) -> None:
    destination = DEFAULT_PAGE_BY_ROLE[user.role]
    st.switch_page(destination)


def require_anonymous() -> None:
    user = get_current_user()
    if user:
        st.switch_page(DEFAULT_PAGE_BY_ROLE[user.role])
        st.stop()
