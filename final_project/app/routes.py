from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app import models
from app.auth import authenticate_user, create_access_token, get_current_user
from app.database import create_audit_log, get_db, lat_lon_to_h3
from app.queue_worker import enqueue_order_event

router = APIRouter(tags=["Geo Furniture"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=6, max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    full_name: str
    role: models.RoleEnum
    allowed_h3_region: str | None = None


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class OrderCreate(BaseModel):
    customer_name: str | None = Field(default=None, min_length=2, max_length=120)
    product_type: str = Field(min_length=2, max_length=120)
    quantity: int = Field(gt=0, le=1000)
    price: float = Field(gt=0)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    notes: str | None = Field(default=None, max_length=1000)


class OrderUpdate(BaseModel):
    customer_name: str | None = Field(default=None, min_length=2, max_length=120)
    product_type: str | None = Field(default=None, min_length=2, max_length=120)
    quantity: int | None = Field(default=None, gt=0, le=1000)
    price: float | None = Field(default=None, gt=0)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    status: models.OrderStatus | None = None
    notes: str | None = Field(default=None, max_length=1000)


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int | None
    customer_name: str
    product_type: str
    quantity: int
    price: float
    total_amount: float
    latitude: float
    longitude: float
    h3_region: str
    status: models.OrderStatus
    notes: str | None
    created_at: datetime
    updated_at: datetime


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    actor_user_id: int | None
    actor_username: str
    action: str
    target_type: str | None
    target_id: int | None
    description: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class AnalyticsResponse(BaseModel):
    summary: dict[str, Any]
    orders_by_region: list[dict[str, Any]]
    orders_by_status: list[dict[str, Any]]
    revenue_by_region: list[dict[str, Any]]
    daily_orders_trend: list[dict[str, Any]]
    top_products: list[dict[str, Any]]
    map_points: list[dict[str, Any]]


def order_to_response(order: models.Order) -> OrderOut:
    return OrderOut(
        id=order.id,
        customer_id=order.customer_id,
        customer_name=order.customer_name,
        product_type=order.product_type,
        quantity=order.quantity,
        price=round(float(order.price), 2),
        total_amount=order.total_amount,
        latitude=order.latitude,
        longitude=order.longitude,
        h3_region=order.h3_region,
        status=order.status,
        notes=order.notes,
        created_at=order.created_at,
        updated_at=order.updated_at,
    )


def audit_to_response(audit_log: models.AuditLog) -> AuditLogOut:
    return AuditLogOut(
        id=audit_log.id,
        actor_user_id=audit_log.actor_user_id,
        actor_username=audit_log.actor_username,
        action=audit_log.action,
        target_type=audit_log.target_type,
        target_id=audit_log.target_id,
        description=audit_log.description,
        metadata=audit_log.metadata_json or {},
        created_at=audit_log.created_at,
    )


def scoped_orders_query(db: Session, user: models.User):
    query = db.query(models.Order)
    if user.role == models.RoleEnum.admin:
        return query
    if user.role == models.RoleEnum.customer:
        return query.filter(models.Order.customer_id == user.id)
    return query.filter(models.Order.h3_region == user.allowed_h3_region)


def ensure_order_access(current_user: models.User, order: models.Order) -> None:
    if current_user.role == models.RoleEnum.admin:
        return
    if current_user.role == models.RoleEnum.customer and order.customer_id == current_user.id:
        return
    if (
        current_user.role == models.RoleEnum.warehouse_manager
        and current_user.allowed_h3_region
        and order.h3_region == current_user.allowed_h3_region
    ):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You do not have access to this order.",
    )


def get_order_or_404(db: Session, order_id: int) -> models.Order:
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.")
    return order


@router.post("/login", response_model=LoginResponse, tags=["Authentication"])
def login(payload: LoginRequest, db: Annotated[Session, Depends(get_db)]):
    user = authenticate_user(db, payload.username, payload.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
        )

    access_token = create_access_token(
        {"sub": str(user.id), "username": user.username, "role": user.role.value}
    )
    create_audit_log(
        db,
        actor_user=user,
        action="login",
        description=f"{user.username} logged in successfully.",
        target_type="user",
        target_id=user.id,
        metadata={"role": user.role.value},
    )
    return LoginResponse(access_token=access_token, user=user)


@router.get("/me", response_model=UserOut, tags=["Authentication"])
def read_me(current_user: Annotated[models.User, Depends(get_current_user)]):
    return current_user


@router.get("/orders", response_model=list[OrderOut], tags=["Orders"])
def list_orders(
    current_user: Annotated[models.User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    search: str | None = Query(default=None),
    status_filter: models.OrderStatus | None = Query(default=None, alias="status"),
    region: str | None = Query(default=None),
    product_type: str | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
):
    query = scoped_orders_query(db, current_user)

    if search:
        search_like = f"%{search.strip()}%"
        filters = [
            models.Order.product_type.ilike(search_like),
            models.Order.customer_name.ilike(search_like),
        ]
        if search.isdigit():
            filters.append(models.Order.id == int(search))
        query = query.filter(or_(*filters))

    if status_filter:
        query = query.filter(models.Order.status == status_filter)
    if region:
        query = query.filter(models.Order.h3_region == region)
    if product_type:
        query = query.filter(models.Order.product_type.ilike(f"%{product_type.strip()}%"))
    if date_from:
        query = query.filter(models.Order.created_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        query = query.filter(models.Order.created_at <= datetime.combine(date_to, datetime.max.time()))

    orders = query.order_by(models.Order.created_at.desc()).all()
    return [order_to_response(order) for order in orders]


@router.post("/orders", response_model=OrderOut, status_code=status.HTTP_201_CREATED, tags=["Orders"])
def create_order(
    payload: OrderCreate,
    current_user: Annotated[models.User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    h3_region = lat_lon_to_h3(payload.latitude, payload.longitude)

    if (
        current_user.role == models.RoleEnum.warehouse_manager
        and current_user.allowed_h3_region != h3_region
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Warehouse managers can only create orders for their assigned region.",
        )

    customer_id = current_user.id if current_user.role == models.RoleEnum.customer else None
    customer_name = payload.customer_name or current_user.full_name

    order = models.Order(
        customer_id=customer_id,
        customer_name=customer_name,
        product_type=payload.product_type,
        quantity=payload.quantity,
        price=payload.price,
        latitude=payload.latitude,
        longitude=payload.longitude,
        h3_region=h3_region,
        status=models.OrderStatus.pending,
        notes=payload.notes,
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    create_audit_log(
        db,
        actor_user=current_user,
        action="order_create",
        description=f"Order #{order.id} created for {order.customer_name}.",
        target_type="order",
        target_id=order.id,
        metadata={"h3_region": order.h3_region, "status": order.status.value},
    )
    enqueue_order_event(order.id, order.h3_region, order.customer_name)
    return order_to_response(order)


@router.get("/orders/{order_id}", response_model=OrderOut, tags=["Orders"])
def get_order(
    order_id: int,
    current_user: Annotated[models.User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    order = get_order_or_404(db, order_id)
    ensure_order_access(current_user, order)
    return order_to_response(order)


@router.put("/orders/{order_id}", response_model=OrderOut, tags=["Orders"])
def update_order(
    order_id: int,
    payload: OrderUpdate,
    current_user: Annotated[models.User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    order = get_order_or_404(db, order_id)
    ensure_order_access(current_user, order)

    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No updates were provided.")

    if current_user.role == models.RoleEnum.customer:
        non_status_fields = {"product_type", "quantity", "price", "latitude", "longitude", "notes"}
        requested_fields = set(updates)
        if "status" in updates and updates["status"] != models.OrderStatus.cancelled:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Customers can only cancel their own orders.",
            )
        if requested_fields.intersection(non_status_fields) and order.status != models.OrderStatus.pending:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Customers can edit order details only while the order is Pending.",
            )

    if current_user.role == models.RoleEnum.warehouse_manager:
        allowed_fields = {"status"}
        if set(updates) - allowed_fields:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Warehouse managers can only update order status.",
            )
        if updates.get("status") == models.OrderStatus.cancelled:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Warehouse managers cannot cancel orders.",
            )

    if order.status == models.OrderStatus.delivered and current_user.role != models.RoleEnum.admin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Delivered orders are locked and can only be changed by an admin.",
        )

    new_latitude = updates.get("latitude", order.latitude)
    new_longitude = updates.get("longitude", order.longitude)
    if "latitude" in updates or "longitude" in updates:
        recalculated_region = lat_lon_to_h3(new_latitude, new_longitude)
        if (
            current_user.role == models.RoleEnum.warehouse_manager
            and recalculated_region != current_user.allowed_h3_region
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Warehouse managers cannot move an order outside their assigned region.",
            )
        order.h3_region = recalculated_region

    if "customer_name" in updates and current_user.role != models.RoleEnum.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can change the customer name on an order.",
        )

    for field_name, value in updates.items():
        setattr(order, field_name, value)

    db.commit()
    db.refresh(order)

    create_audit_log(
        db,
        actor_user=current_user,
        action="order_update",
        description=f"Order #{order.id} was updated.",
        target_type="order",
        target_id=order.id,
        metadata={"updated_fields": sorted(list(updates.keys())), "status": order.status.value},
    )
    return order_to_response(order)


@router.post("/orders/{order_id}/cancel", response_model=OrderOut, tags=["Orders"])
def cancel_order(
    order_id: int,
    current_user: Annotated[models.User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    order = get_order_or_404(db, order_id)
    ensure_order_access(current_user, order)

    if current_user.role == models.RoleEnum.warehouse_manager:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Warehouse managers cannot cancel orders.",
        )

    if order.status in {models.OrderStatus.cancelled, models.OrderStatus.delivered}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Order cannot be cancelled because it is already {order.status.value}.",
        )

    order.status = models.OrderStatus.cancelled
    db.commit()
    db.refresh(order)

    create_audit_log(
        db,
        actor_user=current_user,
        action="order_cancel",
        description=f"Order #{order.id} was cancelled.",
        target_type="order",
        target_id=order.id,
        metadata={"status": order.status.value},
    )
    return order_to_response(order)


@router.get("/analytics", response_model=AnalyticsResponse, tags=["Analytics"])
def get_analytics(
    current_user: Annotated[models.User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    orders = scoped_orders_query(db, current_user).all()
    if not orders:
        return AnalyticsResponse(
            summary={
                "total_orders": 0,
                "total_revenue": 0.0,
                "pending_orders": 0,
                "delivered_orders": 0,
                "unique_regions": 0,
            },
            orders_by_region=[],
            orders_by_status=[],
            revenue_by_region=[],
            daily_orders_trend=[],
            top_products=[],
            map_points=[],
        )

    rows = [
        {
            "id": order.id,
            "customer_name": order.customer_name,
            "product_type": order.product_type,
            "quantity": order.quantity,
            "price": float(order.price),
            "revenue": float(order.price) * int(order.quantity),
            "latitude": order.latitude,
            "longitude": order.longitude,
            "h3_region": order.h3_region,
            "status": order.status.value,
            "created_at": order.created_at,
        }
        for order in orders
    ]
    frame = pd.DataFrame(rows)
    frame["created_at"] = pd.to_datetime(frame["created_at"])
    frame["order_date"] = frame["created_at"].dt.strftime("%Y-%m-%d")

    summary = {
        "total_orders": int(len(frame)),
        "total_revenue": round(float(frame["revenue"].sum()), 2),
        "pending_orders": int((frame["status"] == models.OrderStatus.pending.value).sum()),
        "delivered_orders": int((frame["status"] == models.OrderStatus.delivered.value).sum()),
        "unique_regions": int(frame["h3_region"].nunique()),
    }

    orders_by_region = (
        frame.groupby("h3_region")
        .size()
        .reset_index(name="orders")
        .sort_values("orders", ascending=False)
        .to_dict("records")
    )
    orders_by_status = (
        frame.groupby("status")
        .size()
        .reset_index(name="orders")
        .sort_values("orders", ascending=False)
        .to_dict("records")
    )
    revenue_by_region = (
        frame.groupby("h3_region", as_index=False)["revenue"]
        .sum()
        .sort_values("revenue", ascending=False)
        .round({"revenue": 2})
        .to_dict("records")
    )
    daily_orders_trend = (
        frame.groupby("order_date", as_index=False)
        .agg(orders=("id", "count"), revenue=("revenue", "sum"))
        .sort_values("order_date")
        .round({"revenue": 2})
        .to_dict("records")
    )
    top_products = (
        frame.groupby("product_type", as_index=False)
        .agg(orders=("id", "count"), revenue=("revenue", "sum"))
        .sort_values(["orders", "revenue"], ascending=[False, False])
        .head(10)
        .round({"revenue": 2})
        .to_dict("records")
    )
    map_points = frame[
        ["id", "customer_name", "product_type", "latitude", "longitude", "h3_region", "status", "revenue"]
    ].rename(columns={"id": "order_id"}).to_dict("records")

    return AnalyticsResponse(
        summary=summary,
        orders_by_region=orders_by_region,
        orders_by_status=orders_by_status,
        revenue_by_region=revenue_by_region,
        daily_orders_trend=daily_orders_trend,
        top_products=top_products,
        map_points=map_points,
    )


@router.get("/audit-logs", response_model=list[AuditLogOut], tags=["Audit"])
def list_audit_logs(
    current_user: Annotated[models.User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(default=100, ge=1, le=500),
    action: str | None = Query(default=None),
):
    query = db.query(models.AuditLog)
    if action:
        query = query.filter(models.AuditLog.action == action)

    if current_user.role != models.RoleEnum.admin:
        visible_order_ids = [order.id for order in scoped_orders_query(db, current_user).all()]
        filters = [models.AuditLog.actor_user_id == current_user.id]
        if visible_order_ids:
            filters.append(
                (models.AuditLog.target_type == "order") & (models.AuditLog.target_id.in_(visible_order_ids))
            )
        query = query.filter(or_(*filters))

    logs = query.order_by(models.AuditLog.created_at.desc()).limit(limit).all()
    return [audit_to_response(log) for log in logs]
