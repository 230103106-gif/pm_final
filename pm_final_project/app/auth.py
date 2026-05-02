from __future__ import annotations

import os
import secrets
from datetime import UTC, datetime, timedelta
from threading import Lock

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Order, User, UserRole

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)
token_lock = Lock()
token_store: dict[str, dict[str, datetime | int]] = {}
TOKEN_TTL_HOURS = int(os.getenv("TOKEN_TTL_HOURS", "12"))


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(user: User) -> str:
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + timedelta(hours=TOKEN_TTL_HOURS)
    with token_lock:
        token_store[token] = {"user_id": user.id, "expires_at": expires_at}
    return token


def revoke_token(token: str) -> None:
    with token_lock:
        token_store.pop(token, None)


def _get_token_payload(token: str) -> dict[str, datetime | int] | None:
    with token_lock:
        payload = token_store.get(token)
        if not payload:
            return None

        expires_at = payload["expires_at"]
        if isinstance(expires_at, datetime) and expires_at <= datetime.now(UTC):
            token_store.pop(token, None)
            return None
        return payload


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials were not provided.",
        )

    payload = _get_token_payload(credentials.credentials)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token.",
        )

    user_id = payload["user_id"]
    user = db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user no longer exists.",
        )
    return user


def require_roles(*roles: UserRole | str):
    accepted = {role.value if isinstance(role, UserRole) else role for role in roles}

    def dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in accepted:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action.",
            )
        return current_user

    return dependency


def can_access_order(user: User, order: Order) -> bool:
    if user.role == UserRole.ADMIN.value:
        return True
    if user.role == UserRole.CUSTOMER.value:
        return order.customer_id == user.id
    if user.role == UserRole.WAREHOUSE.value:
        return bool(user.allowed_region) and order.h3_region == user.allowed_region
    return False


def verify_order_access(user: User, order: Order, action: str = "view") -> None:
    if can_access_order(user, order):
        return

    if user.role == UserRole.WAREHOUSE.value:
        detail = (
            "ABAC rule blocked access: warehouse managers can only access orders "
            "assigned to their allowed H3 region."
        )
    elif user.role == UserRole.CUSTOMER.value:
        detail = "Customers can only access their own orders."
    else:
        detail = f"You do not have permission to {action} this order."

    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)
