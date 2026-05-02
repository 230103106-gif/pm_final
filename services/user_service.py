from __future__ import annotations

from datetime import timedelta

from sqlmodel import Session, select

from core.config import ROLE_ADMIN, ROLE_CUSTOMER, ROLE_WAREHOUSE, settings
from core.security import generate_session_token, hash_password, hash_token, verify_password
from core.utils import AuthenticationError, NotFoundError, ValidationError, utcnow
from models.user import User, UserSession

VALID_ROLES = {ROLE_ADMIN, ROLE_CUSTOMER, ROLE_WAREHOUSE}


def normalize_username(username: str) -> str:
    return username.strip().lower()


def list_users(session: Session) -> list[User]:
    return session.exec(select(User).order_by(User.role, User.full_name)).all()


def get_user_by_id(session: Session, user_id: int) -> User:
    user = session.get(User, user_id)
    if not user:
        raise NotFoundError("User was not found.")
    return user


def authenticate_user(session: Session, username: str, password: str) -> User:
    normalized = normalize_username(username)
    user = session.exec(select(User).where(User.username == normalized)).first()
    if not user or not verify_password(password, user.password_hash):
        raise AuthenticationError("Invalid username or password.")
    if not user.is_active:
        raise AuthenticationError("This account is inactive.")
    user.updated_at = utcnow()
    session.add(user)
    session.commit()
    return user


def create_user(
    session: Session,
    *,
    username: str,
    full_name: str,
    password: str,
    role: str,
    assigned_region: str | None = None,
) -> User:
    normalized = normalize_username(username)
    if len(normalized) < 3:
        raise ValidationError("Username must contain at least 3 characters.")
    if not full_name.strip():
        raise ValidationError("Full name is required.")
    if role not in VALID_ROLES:
        raise ValidationError("Role is not supported.")
    if role == ROLE_WAREHOUSE and not assigned_region:
        raise ValidationError("Warehouse managers must be assigned to an H3 region.")
    if role != ROLE_WAREHOUSE and assigned_region:
        raise ValidationError("Only warehouse managers can have an assigned region.")
    if len(password) < 8:
        raise ValidationError("Password must be at least 8 characters.")
    existing = session.exec(select(User).where(User.username == normalized)).first()
    if existing:
        raise ValidationError("A user with that username already exists.")
    user = User(
        username=normalized,
        full_name=full_name.strip(),
        password_hash=hash_password(password),
        role=role,
        assigned_region=assigned_region,
        is_active=True,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def start_user_session(session: Session, user: User) -> str:
    token = generate_session_token()
    record = UserSession(
        user_id=user.id,
        session_hash=hash_token(token),
        expires_at=utcnow() + timedelta(hours=settings.session_duration_hours),
        last_seen_at=utcnow(),
    )
    session.add(record)
    session.commit()
    return token


def user_from_session_token(session: Session, token: str | None):
    if not token:
        return None
    record = session.exec(
        select(UserSession).where(
            UserSession.session_hash == hash_token(token),
            UserSession.is_active == True,
        )
    ).first()
    if not record:
        return None
    if record.expires_at <= utcnow():
        record.is_active = False
        session.add(record)
        session.commit()
        return None
    user = session.get(User, record.user_id)
    if not user or not user.is_active:
        return None
    record.last_seen_at = utcnow()
    session.add(record)
    session.commit()
    return user


def end_user_session(session: Session, token: str) -> None:
    record = session.exec(
        select(UserSession).where(UserSession.session_hash == hash_token(token), UserSession.is_active == True)
    ).first()
    if not record:
        return
    record.is_active = False
    record.last_seen_at = utcnow()
    session.add(record)
    session.commit()


def update_profile(session: Session, actor: User, *, full_name: str) -> User:
    if not full_name.strip():
        raise ValidationError("Full name is required.")
    actor.full_name = full_name.strip()
    actor.updated_at = utcnow()
    session.add(actor)
    session.commit()
    session.refresh(actor)
    return actor


def change_password(session: Session, actor: User, current_password: str, new_password: str) -> None:
    if not verify_password(current_password, actor.password_hash):
        raise ValidationError("Current password is incorrect.")
    if len(new_password) < 8:
        raise ValidationError("New password must be at least 8 characters.")
    actor.password_hash = hash_password(new_password)
    actor.updated_at = utcnow()
    session.add(actor)
    session.commit()
