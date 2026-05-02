from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Enum as SqlEnum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class RoleEnum(str, Enum):
    admin = "admin"
    customer = "customer"
    warehouse_manager = "warehouse_manager"


class OrderStatus(str, Enum):
    pending = "Pending"
    processing = "Processing"
    shipped = "Shipped"
    delivered = "Delivered"
    cancelled = "Cancelled"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    full_name = Column(String(120), nullable=False)
    role = Column(SqlEnum(RoleEnum, name="role_enum"), nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    allowed_h3_region = Column(String(32), nullable=True, index=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    orders = relationship("Order", back_populates="customer", passive_deletes=True)
    audit_logs = relationship("AuditLog", back_populates="actor_user")


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    customer_name = Column(String(120), nullable=False, index=True)
    product_type = Column(String(120), nullable=False, index=True)
    quantity = Column(Integer, nullable=False)
    price = Column(Float, nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    h3_region = Column(String(32), nullable=False, index=True)
    status = Column(SqlEnum(OrderStatus, name="order_status"), default=OrderStatus.pending, nullable=False, index=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    customer = relationship("User", back_populates="orders")

    __table_args__ = (
        Index("ix_orders_region_status", "h3_region", "status"),
        Index("ix_orders_customer_created", "customer_id", "created_at"),
    )

    @property
    def total_amount(self) -> float:
        return round(float(self.price) * int(self.quantity), 2)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    actor_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    actor_username = Column(String(50), nullable=False, index=True)
    action = Column(String(64), nullable=False, index=True)
    target_type = Column(String(64), nullable=True, index=True)
    target_id = Column(Integer, nullable=True, index=True)
    description = Column(String(255), nullable=False)
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False, index=True)

    actor_user = relationship("User", back_populates="audit_logs")
