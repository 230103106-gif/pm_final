from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import h3
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session

from app.auth import (
    create_access_token,
    get_current_user,
    require_roles,
    revoke_token,
    security,
    verify_order_access,
    verify_password,
)
from app.database import H3_RESOLUTION, get_db, write_audit_log
from app.models import AuditLog, Order, OrderStatus, User, UserRole
from app.queue_worker import enqueue_order_event, list_notifications_for_user

router = APIRouter()

VALID_STATUS_TRANSITIONS = {
    OrderStatus.PENDING.value: {OrderStatus.PROCESSING.value, OrderStatus.CANCELLED.value},
    OrderStatus.PROCESSING.value: {OrderStatus.SHIPPED.value, OrderStatus.CANCELLED.value},
    OrderStatus.SHIPPED.value: {OrderStatus.DELIVERED.value},
    OrderStatus.DELIVERED.value: set(),
    OrderStatus.CANCELLED.value: set(),
}


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=6, max_length=128)


class UserOut(BaseModel):
    id: int
    username: str
    full_name: str
    role: str
    allowed_region: str | None = None

    model_config = ConfigDict(from_attributes=True)


class LoginResponse(BaseModel):
    token: str
    user: UserOut


class OrderCreate(BaseModel):
    customer_name: str | None = Field(default=None, max_length=120)
    product_type: str = Field(min_length=2, max_length=120)
    quantity: int = Field(ge=1, le=500)
    price: float = Field(gt=0)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)

    @field_validator("product_type")
    @classmethod
    def clean_product_type(cls, value: str) -> str:
        return value.strip()

    @field_validator("customer_name")
    @classmethod
    def clean_customer_name(cls, value: str | None) -> str | None:
        return value.strip() if value else value


class OrderUpdate(BaseModel):
    product_type: str | None = Field(default=None, min_length=2, max_length=120)
    quantity: int | None = Field(default=None, ge=1, le=500)
    price: float | None = Field(default=None, gt=0)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    status: OrderStatus | None = None

    @field_validator("product_type")
    @classmethod
    def clean_product_type(cls, value: str | None) -> str | None:
        return value.strip() if value else value


class OrderOut(BaseModel):
    id: int
    customer_id: int
    customer_name: str
    product_type: str
    quantity: int
    price: float
    total_amount: float
    latitude: float
    longitude: float
    h3_region: str
    status: str
    created_at: datetime
    updated_at: datetime


class AuditLogOut(BaseModel):
    id: int
    username: str
    role: str
    action: str
    entity_type: str
    entity_id: str | None
    details: str
    created_at: datetime


class NotificationOut(BaseModel):
    id: str
    message: str
    order_id: int
    region: str
    created_at: str


def serialize_order(order: Order) -> OrderOut:
    return OrderOut(
        id=order.id,
        customer_id=order.customer_id,
        customer_name=order.customer_name,
        product_type=order.product_type,
        quantity=order.quantity,
        price=order.price,
        total_amount=round(order.quantity * order.price, 2),
        latitude=order.latitude,
        longitude=order.longitude,
        h3_region=order.h3_region,
        status=order.status,
        created_at=order.created_at,
        updated_at=order.updated_at,
    )


def get_scoped_order_query(current_user: User):
    query = select(Order)
    if current_user.role == UserRole.CUSTOMER.value:
        query = query.where(Order.customer_id == current_user.id)
    elif current_user.role == UserRole.WAREHOUSE.value:
        query = query.where(Order.h3_region == current_user.allowed_region)
    return query


def get_order_or_404(db: Session, order_id: int) -> Order:
    order = db.scalar(select(Order).where(Order.id == order_id))
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.")
    return order


def validate_status_transition(current_status: str, new_status: str, actor_role: str) -> None:
    if current_status == new_status:
        return
    if actor_role == UserRole.WAREHOUSE.value and new_status == OrderStatus.CANCELLED.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Warehouse managers cannot cancel orders.",
        )
    if new_status not in VALID_STATUS_TRANSITIONS[current_status]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status transition from {current_status} to {new_status}.",
        )


@router.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    user = db.scalar(select(User).where(User.username == payload.username))
    if user is None or not verify_password(payload.password, user.password_hash):
        write_audit_log(
            db,
            username=payload.username,
            role="anonymous",
            action="login_failed",
            entity_type="user",
            details="Invalid credentials submitted.",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
        )

    token = create_access_token(user)
    write_audit_log(
        db,
        username=user.username,
        role=user.role,
        action="login",
        entity_type="user",
        entity_id=str(user.id),
        details="User logged into the platform.",
        user_id=user.id,
    )
    return LoginResponse(token=token, user=UserOut.model_validate(user))


@router.post("/logout")
def logout(
    credentials=Depends(security),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    if credentials is not None:
        revoke_token(credentials.credentials)
    write_audit_log(
        db,
        username=current_user.username,
        role=current_user.role,
        action="logout",
        entity_type="user",
        entity_id=str(current_user.id),
        details="User logged out of the platform.",
        user_id=current_user.id,
    )
    return {"message": "Logged out successfully."}


@router.get("/me", response_model=UserOut)
def get_me(current_user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(current_user)


@router.get("/orders", response_model=list[OrderOut])
def list_orders(
    search: str | None = Query(default=None, max_length=120),
    status_filter: OrderStatus | None = Query(default=None, alias="status"),
    region: str | None = Query(default=None, max_length=32),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[OrderOut]:
    query = get_scoped_order_query(current_user)

    if search:
        pattern = f"%{search.lower()}%"
        query = query.where(
            or_(
                func.lower(Order.customer_name).like(pattern),
                func.lower(Order.product_type).like(pattern),
                func.lower(Order.h3_region).like(pattern),
                cast(Order.id, String).like(f"%{search}%"),
            )
        )

    if status_filter:
        query = query.where(Order.status == status_filter.value)

    if region:
        query = query.where(Order.h3_region == region)

    orders = db.scalars(query.order_by(Order.created_at.desc())).all()
    return [serialize_order(order) for order in orders]


@router.post(
    "/orders",
    response_model=OrderOut,
    status_code=status.HTTP_201_CREATED,
)
def create_order(
    payload: OrderCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.CUSTOMER)),
) -> OrderOut:
    customer_name = payload.customer_name or current_user.full_name
    h3_region = h3.latlng_to_cell(payload.latitude, payload.longitude, H3_RESOLUTION)

    order = Order(
        customer_id=current_user.id,
        customer_name=customer_name,
        product_type=payload.product_type,
        quantity=payload.quantity,
        price=payload.price,
        latitude=payload.latitude,
        longitude=payload.longitude,
        h3_region=h3_region,
        status=OrderStatus.PENDING.value,
    )

    db.add(order)
    db.commit()
    db.refresh(order)

    write_audit_log(
        db,
        username=current_user.username,
        role=current_user.role,
        action="order_create",
        entity_type="order",
        entity_id=str(order.id),
        details=f"Created order in H3 region {order.h3_region}.",
        user_id=current_user.id,
    )
    enqueue_order_event(order.id, order.h3_region, current_user.username)
    return serialize_order(order)


@router.get("/orders/{order_id}", response_model=OrderOut)
def get_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OrderOut:
    order = get_order_or_404(db, order_id)
    verify_order_access(current_user, order)
    return serialize_order(order)


@router.patch("/orders/{order_id}", response_model=OrderOut)
def update_order(
    order_id: int,
    payload: OrderUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OrderOut:
    order = get_order_or_404(db, order_id)
    verify_order_access(current_user, order, action="update")

    if current_user.role == UserRole.CUSTOMER.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Customers can cancel orders but cannot edit them.",
        )

    editable_fields = {
        "product_type": payload.product_type,
        "quantity": payload.quantity,
        "price": payload.price,
        "latitude": payload.latitude,
        "longitude": payload.longitude,
    }
    updates = {key: value for key, value in editable_fields.items() if value is not None}

    if current_user.role == UserRole.WAREHOUSE.value and updates:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Warehouse managers can only update order status.",
        )

    if payload.status is not None:
        validate_status_transition(order.status, payload.status.value, current_user.role)
        order.status = payload.status.value

    for field_name, value in updates.items():
        setattr(order, field_name, value)

    if payload.latitude is not None or payload.longitude is not None:
        latitude = payload.latitude if payload.latitude is not None else order.latitude
        longitude = payload.longitude if payload.longitude is not None else order.longitude
        order.h3_region = h3.latlng_to_cell(latitude, longitude, H3_RESOLUTION)

    order.updated_at = datetime.now(UTC)
    db.add(order)
    db.commit()
    db.refresh(order)

    write_audit_log(
        db,
        username=current_user.username,
        role=current_user.role,
        action="order_update",
        entity_type="order",
        entity_id=str(order.id),
        details="Updated order details or workflow status.",
        user_id=current_user.id,
    )
    return serialize_order(order)


@router.delete("/orders/{order_id}", response_model=OrderOut)
def cancel_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OrderOut:
    order = get_order_or_404(db, order_id)
    verify_order_access(current_user, order, action="cancel")

    if current_user.role == UserRole.WAREHOUSE.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Warehouse managers cannot cancel orders.",
        )
    if order.status in {
        OrderStatus.SHIPPED.value,
        OrderStatus.DELIVERED.value,
        OrderStatus.CANCELLED.value,
    }:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only pending or processing orders can be cancelled.",
        )

    order.status = OrderStatus.CANCELLED.value
    order.updated_at = datetime.now(UTC)
    db.add(order)
    db.commit()
    db.refresh(order)

    write_audit_log(
        db,
        username=current_user.username,
        role=current_user.role,
        action="order_cancel",
        entity_type="order",
        entity_id=str(order.id),
        details="Cancelled an active order.",
        user_id=current_user.id,
    )
    return serialize_order(order)


@router.get("/analytics")
def get_analytics(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    orders = db.scalars(get_scoped_order_query(current_user)).all()
    records = [
        {
            "id": order.id,
            "customer_name": order.customer_name,
            "product_type": order.product_type,
            "quantity": order.quantity,
            "price": order.price,
            "total_amount": round(order.quantity * order.price, 2),
            "latitude": order.latitude,
            "longitude": order.longitude,
            "h3_region": order.h3_region,
            "status": order.status,
            "created_at": order.created_at,
            "created_date": order.created_at.date().isoformat(),
        }
        for order in orders
    ]
    df = pd.DataFrame(records)

    if df.empty:
        return {
            "summary": {
                "total_orders": 0,
                "total_revenue": 0.0,
                "pending_orders": 0,
                "delivered_orders": 0,
                "warehouse_region": current_user.allowed_region,
            },
            "orders_by_region": [],
            "orders_by_status": [],
            "revenue_by_region": [],
            "daily_orders_trend": [],
            "top_products": [],
            "map_points": [],
            "region_rollup": [],
        }

    orders_by_region = (
        df.groupby("h3_region", as_index=False)
        .agg(orders=("id", "count"))
        .sort_values("orders", ascending=False)
    )
    orders_by_status = (
        df.groupby("status", as_index=False)
        .agg(orders=("id", "count"))
        .sort_values("orders", ascending=False)
    )
    revenue_by_region = (
        df.groupby("h3_region", as_index=False)
        .agg(revenue=("total_amount", "sum"))
        .sort_values("revenue", ascending=False)
    )
    daily_orders_trend = (
        df.groupby("created_date", as_index=False)
        .agg(orders=("id", "count"), revenue=("total_amount", "sum"))
        .sort_values("created_date")
    )
    top_products = (
        df.groupby("product_type", as_index=False)
        .agg(quantity=("quantity", "sum"), revenue=("total_amount", "sum"))
        .sort_values(["quantity", "revenue"], ascending=[False, False])
        .head(5)
    )
    region_rollup = (
        df.groupby("h3_region", as_index=False)
        .agg(
            orders=("id", "count"),
            customers=("customer_name", "nunique"),
            revenue=("total_amount", "sum"),
        )
        .sort_values("orders", ascending=False)
    )

    return {
        "summary": {
            "total_orders": int(df["id"].count()),
            "total_revenue": round(float(df["total_amount"].sum()), 2),
            "pending_orders": int((df["status"] == OrderStatus.PENDING.value).sum()),
            "delivered_orders": int((df["status"] == OrderStatus.DELIVERED.value).sum()),
            "warehouse_region": current_user.allowed_region,
        },
        "orders_by_region": orders_by_region.to_dict(orient="records"),
        "orders_by_status": orders_by_status.to_dict(orient="records"),
        "revenue_by_region": revenue_by_region.to_dict(orient="records"),
        "daily_orders_trend": daily_orders_trend.to_dict(orient="records"),
        "top_products": top_products.to_dict(orient="records"),
        "map_points": df.to_dict(orient="records"),
        "region_rollup": region_rollup.to_dict(orient="records"),
    }


@router.get("/audit-logs", response_model=list[AuditLogOut])
def get_audit_logs(
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN)),
) -> list[AuditLogOut]:
    logs = db.scalars(
        select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    ).all()
    return [
        AuditLogOut(
            id=log.id,
            username=log.username,
            role=log.role,
            action=log.action,
            entity_type=log.entity_type,
            entity_id=log.entity_id,
            details=log.details,
            created_at=log.created_at,
        )
        for log in logs
    ]


@router.get("/notifications", response_model=list[NotificationOut])
def get_notifications(
    current_user: User = Depends(get_current_user),
) -> list[NotificationOut]:
    return [NotificationOut(**item) for item in list_notifications_for_user(current_user)]
