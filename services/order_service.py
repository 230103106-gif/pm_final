from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

import h3
from sqlmodel import Session, select

from core.abac import apply_order_scope, can_access_order
from core.config import (
    EXPORT_DIR,
    ORDER_STATUS_ASSIGNED,
    ORDER_STATUS_CANCELLED,
    ORDER_STATUS_CONFIRMED,
    ORDER_STATUS_CREATED,
    ORDER_STATUS_DELIVERED,
    ORDER_STATUS_OUT_FOR_DELIVERY,
    ORDER_STATUS_PACKED,
    ROLE_ADMIN,
    ROLE_CUSTOMER,
    ROLE_WAREHOUSE,
    SEED_DATA_PATH,
    settings,
)
from core.events import create_order_created_event
from core.rbac import any_permission
from core.utils import AuthorizationError, NotFoundError, ValidationError, region_label, utcnow
from models.order import Order
from models.product import Product
from models.user import User
from services import audit_service


def city_catalog() -> list[dict[str, Any]]:
    payload = json.loads(SEED_DATA_PATH.read_text(encoding="utf-8"))
    return payload["cities"]


def valid_transitions_for(order: Order) -> list[str]:
    return sorted(settings.allowed_transitions.get(order.status, set()))


def validate_coordinates(latitude: float, longitude: float) -> None:
    if not (-90 <= latitude <= 90):
        raise ValidationError("Latitude must be between -90 and 90.")
    if not (-180 <= longitude <= 180):
        raise ValidationError("Longitude must be between -180 and 180.")


def get_order(session: Session, actor: User, order_id: int) -> Order:
    order = session.get(Order, order_id)
    if not order:
        raise NotFoundError("Order was not found.")
    if not can_access_order(actor, order):
        raise AuthorizationError("You do not have access to this order.")
    return order


def next_order_number(session: Session) -> str:
    existing_order_ids = session.exec(select(Order.id)).all()
    sequence = len(existing_order_ids) + 1001
    return f"FG-{utcnow().strftime('%y%m')}-{sequence}"


def create_order(
    session: Session,
    actor: User,
    *,
    product_id: int,
    quantity: int,
    recipient_name: str,
    phone: str,
    address_line1: str,
    address_line2: str,
    city: str,
    state: str,
    postal_code: str,
    country: str,
    latitude: float,
    longitude: float,
    notes: str = "",
) -> Order:
    if actor.role != ROLE_CUSTOMER:
        raise AuthorizationError("Only customer accounts can place new orders.")
    if quantity <= 0:
        raise ValidationError("Quantity must be greater than zero.")
    validate_coordinates(latitude, longitude)

    product = session.get(Product, product_id)
    if not product or not product.is_active:
        raise NotFoundError("Selected product is unavailable.")
    if product.stock_quantity < quantity:
        raise ValidationError("Insufficient stock for the requested quantity.")

    region = h3.latlng_to_cell(latitude, longitude, settings.h3_resolution)
    order = Order(
        order_number=next_order_number(session),
        customer_id=actor.id,
        product_id=product.id,
        quantity=quantity,
        unit_price=product.price,
        total_amount=round(product.price * quantity, 2),
        status=ORDER_STATUS_CREATED,
        recipient_name=recipient_name.strip(),
        phone=phone.strip(),
        address_line1=address_line1.strip(),
        address_line2=address_line2.strip(),
        city=city.strip(),
        state=state.strip(),
        postal_code=postal_code.strip(),
        country=country.strip() or "USA",
        latitude=float(latitude),
        longitude=float(longitude),
        h3_region=region,
        notes=notes.strip(),
    )

    product.stock_quantity -= quantity
    product.updated_at = utcnow()

    session.add(product)
    session.add(order)
    session.commit()
    session.refresh(order)

    event = create_order_created_event(order)
    session.add(event)
    session.commit()

    audit_service.log_action(
        session,
        actor=actor,
        action="order.created",
        entity_type="order",
        entity_id=str(order.id),
        details={
            "order_number": order.order_number,
            "product_id": product.id,
            "quantity": quantity,
            "h3_region": order.h3_region,
        },
    )
    return order


def list_orders(
    session: Session,
    actor: User,
    *,
    status: str | None = None,
    city: str | None = None,
    search: str | None = None,
    include_cancelled: bool = True,
) -> list[dict[str, Any]]:
    query = apply_order_scope(select(Order).order_by(Order.created_at.desc()), actor)
    if status and status != "All":
        query = query.where(Order.status == status)
    if city and city != "All":
        query = query.where(Order.city == city)
    if not include_cancelled:
        query = query.where(Order.status != ORDER_STATUS_CANCELLED)

    orders = session.exec(query).all()
    if search:
        needle = search.strip().lower()
        orders = [
            order
            for order in orders
            if needle in order.order_number.lower()
            or needle in order.recipient_name.lower()
            or needle in order.city.lower()
        ]
    return enrich_orders(session, orders)


def enrich_orders(session: Session, orders: list[Order]) -> list[dict[str, Any]]:
    product_ids = {order.product_id for order in orders}
    customer_ids = {order.customer_id for order in orders}
    products = {product.id: product for product in session.exec(select(Product).where(Product.id.in_(product_ids))).all()} if product_ids else {}
    customers = {user.id: user for user in session.exec(select(User).where(User.id.in_(customer_ids))).all()} if customer_ids else {}

    rows: list[dict[str, Any]] = []
    for order in orders:
        product = products.get(order.product_id)
        customer = customers.get(order.customer_id)
        rows.append(
            {
                "id": order.id,
                "order_number": order.order_number,
                "product_name": product.name if product else "Unknown Product",
                "customer_name": customer.full_name if customer else "Unknown User",
                "quantity": order.quantity,
                "unit_price": order.unit_price,
                "total_amount": order.total_amount,
                "status": order.status,
                "city": order.city,
                "state": order.state,
                "h3_region": order.h3_region,
                "region_label": region_label(order.h3_region),
                "recipient_name": order.recipient_name,
                "phone": order.phone,
                "created_at": order.created_at,
                "updated_at": order.updated_at,
                "notes": order.notes,
                "address": ", ".join(
                    value for value in [order.address_line1, order.address_line2, order.city, order.state] if value
                ),
            }
        )
    return rows


def customer_cancellable(order: Order) -> bool:
    return order.status in settings.early_cancellable_statuses


def allowed_status_updates(actor: User, order: Order) -> list[str]:
    if actor.role == ROLE_CUSTOMER:
        return [ORDER_STATUS_CANCELLED] if customer_cancellable(order) and order.customer_id == actor.id else []
    transitions = list(settings.allowed_transitions.get(order.status, set()))
    if actor.role == ROLE_WAREHOUSE:
        transitions = [status for status in transitions if status != ORDER_STATUS_CANCELLED]
    return transitions


def update_order_status(
    session: Session,
    actor: User,
    order_id: int,
    new_status: str,
    *,
    reason: str | None = None,
) -> Order:
    order = get_order(session, actor, order_id)
    allowed = allowed_status_updates(actor, order)
    if new_status not in allowed:
        raise ValidationError(f"Cannot move order from {order.status} to {new_status}.")

    if actor.role == ROLE_CUSTOMER and new_status != ORDER_STATUS_CANCELLED:
        raise AuthorizationError("Customers can only cancel their own early-stage orders.")
    if actor.role == ROLE_WAREHOUSE and new_status == ORDER_STATUS_CANCELLED:
        raise AuthorizationError("Warehouse managers cannot cancel orders.")
    if actor.role == ROLE_CUSTOMER and order.customer_id != actor.id:
        raise AuthorizationError("You can only manage your own orders.")

    now = utcnow()
    order.status = new_status
    order.updated_at = now

    if new_status == ORDER_STATUS_CONFIRMED:
        order.confirmed_at = now
    elif new_status == ORDER_STATUS_ASSIGNED:
        order.assigned_at = now
    elif new_status == ORDER_STATUS_PACKED:
        order.packed_at = now
    elif new_status == ORDER_STATUS_OUT_FOR_DELIVERY:
        order.out_for_delivery_at = now
    elif new_status == ORDER_STATUS_DELIVERED:
        order.delivered_at = now
    elif new_status == ORDER_STATUS_CANCELLED:
        order.cancelled_at = now
        order.cancellation_reason = reason or "Cancelled by customer request."
        product = session.get(Product, order.product_id)
        if product:
            product.stock_quantity += order.quantity
            product.updated_at = now
            session.add(product)

    session.add(order)
    session.commit()
    session.refresh(order)

    audit_service.log_action(
        session,
        actor=actor,
        action="order.status_updated",
        entity_type="order",
        entity_id=str(order.id),
        details={
            "order_number": order.order_number,
            "new_status": new_status,
            "reason": reason,
        },
    )
    return order


def cancel_order(session: Session, actor: User, order_id: int, reason: str) -> Order:
    return update_order_status(session, actor, order_id, ORDER_STATUS_CANCELLED, reason=reason)


def order_detail(session: Session, actor: User, order_id: int) -> dict[str, Any]:
    order = get_order(session, actor, order_id)
    product = session.get(Product, order.product_id)
    customer = session.get(User, order.customer_id)
    return {
        "id": order.id,
        "order_number": order.order_number,
        "status": order.status,
        "product_name": product.name if product else "Unknown Product",
        "customer_name": customer.full_name if customer else "Unknown User",
        "quantity": order.quantity,
        "unit_price": order.unit_price,
        "total_amount": order.total_amount,
        "h3_region": order.h3_region,
        "region_label": region_label(order.h3_region),
        "recipient_name": order.recipient_name,
        "phone": order.phone,
        "address_line1": order.address_line1,
        "address_line2": order.address_line2,
        "city": order.city,
        "state": order.state,
        "postal_code": order.postal_code,
        "country": order.country,
        "notes": order.notes,
        "created_at": order.created_at,
        "updated_at": order.updated_at,
        "confirmed_at": order.confirmed_at,
        "assigned_at": order.assigned_at,
        "packed_at": order.packed_at,
        "out_for_delivery_at": order.out_for_delivery_at,
        "delivered_at": order.delivered_at,
        "cancelled_at": order.cancelled_at,
        "cancellation_reason": order.cancellation_reason,
    }


def order_timeline(detail: dict[str, Any]) -> list[tuple[str, Any]]:
    return [
        ("Created", detail["created_at"]),
        ("Confirmed", detail["confirmed_at"]),
        ("Assigned", detail["assigned_at"]),
        ("Packed", detail["packed_at"]),
        ("Out for Delivery", detail["out_for_delivery_at"]),
        ("Delivered", detail["delivered_at"]),
        ("Cancelled", detail["cancelled_at"]),
    ]


def export_orders_csv(session: Session, actor: User) -> tuple[Path, bytes]:
    rows = list_orders(session, actor, include_cancelled=True)
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=[
            "order_number",
            "product_name",
            "customer_name",
            "quantity",
            "unit_price",
            "total_amount",
            "status",
            "city",
            "state",
            "h3_region",
            "recipient_name",
            "phone",
            "created_at",
            "updated_at",
        ],
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row.get(key) for key in writer.fieldnames})
    payload = buffer.getvalue().encode("utf-8")
    export_path = EXPORT_DIR / "orders.csv"
    export_path.write_bytes(payload)
    return export_path, payload
