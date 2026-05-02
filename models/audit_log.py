from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel

from core.utils import utcnow


class AuditLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    actor_user_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
    actor_username: str = Field(index=True, max_length=80)
    action: str = Field(index=True, max_length=80)
    entity_type: str = Field(index=True, max_length=80)
    entity_id: str = Field(index=True, max_length=80)
    details_json: str
    created_at: datetime = Field(default_factory=utcnow, index=True)
