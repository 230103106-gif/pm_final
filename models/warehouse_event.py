from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel

from core.utils import utcnow


class WarehouseEvent(SQLModel, table=True):
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    order_id: int = Field(foreign_key="order.id", index=True)
    event_type: str = Field(index=True, max_length=80)
    region: str = Field(index=True, max_length=32)
    payload_json: str
    status: str = Field(default="pending", index=True, max_length=20)
    processed_by_user_id: Optional[int] = Field(default=None, foreign_key="user.id")
    processed_at: Optional[datetime] = None
    last_error: Optional[str] = Field(default=None, max_length=240)
    created_at: datetime = Field(default_factory=utcnow, index=True)
