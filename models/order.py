from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel

from core.utils import utcnow


class Order(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    order_number: str = Field(index=True, unique=True, max_length=40)
    customer_id: int = Field(foreign_key="user.id", index=True)
    product_id: int = Field(foreign_key="product.id", index=True)
    quantity: int
    unit_price: float
    total_amount: float
    status: str = Field(index=True, max_length=40)
    recipient_name: str = Field(max_length=120)
    phone: str = Field(max_length=40)
    address_line1: str = Field(max_length=180)
    address_line2: str = Field(default="", max_length=180)
    city: str = Field(index=True, max_length=80)
    state: str = Field(max_length=80)
    postal_code: str = Field(max_length=20)
    country: str = Field(default="USA", max_length=80)
    latitude: float
    longitude: float
    h3_region: str = Field(index=True, max_length=32)
    notes: str = Field(default="", max_length=400)
    cancellation_reason: Optional[str] = Field(default=None, max_length=400)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    confirmed_at: Optional[datetime] = None
    assigned_at: Optional[datetime] = None
    packed_at: Optional[datetime] = None
    out_for_delivery_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
