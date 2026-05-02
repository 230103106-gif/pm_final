from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel

from core.utils import utcnow


class User(SQLModel, table=True):
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True, max_length=80)
    full_name: str = Field(max_length=120)
    password_hash: str
    role: str = Field(index=True, max_length=40)
    assigned_region: Optional[str] = Field(default=None, index=True, max_length=32)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class UserSession(SQLModel, table=True):
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    session_hash: str = Field(index=True, unique=True, max_length=128)
    expires_at: datetime
    last_seen_at: datetime = Field(default_factory=utcnow)
    is_active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=utcnow)
