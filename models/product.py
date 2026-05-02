from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel

from core.utils import utcnow


class Product(SQLModel, table=True):
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    sku: str = Field(index=True, unique=True, max_length=40)
    name: str = Field(index=True, max_length=120)
    category: str = Field(index=True, max_length=80)
    material: str = Field(max_length=80)
    description: str = Field(max_length=500)
    price: float
    stock_quantity: int
    dimensions: str = Field(max_length=80)
    is_active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
