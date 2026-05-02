from __future__ import annotations

from typing import Any

from sqlmodel import Session, select

from core.abac import can_access_order
from core.config import ORDER_STATUS_CANCELLED, ORDER_STATUS_CONFIRMED, ROLE_ADMIN, ROLE_WAREHOUSE
from core.utils import AuthorizationError, NotFoundError, ValidationError, region_label, utcnow
from models.order import Order
from models.warehouse_event import WarehouseEvent
from services import audit_service, order_service


def list_events(session: Session, actor, *, event_status: str | None = None, limit: int = 300) -> list[dict[str, Any]]:
    query = select(WarehouseEvent).order_by(WarehouseEvent.created_at.desc())
    if event_status and event_status != "All":
        query = query.where(WarehouseEvent.status == event_status)
    if actor.role == ROLE_WAREHOUSE:
        query = query.where(WarehouseEvent.region == actor.assigned_region)

    events = session.exec(query.limit(limit)).all()
    rows: list[dict[str, Any]] = []
    for event in events:
        order = session.get(Order, event.order_id)
        if not order:
            continue
        if actor.role == ROLE_WAREHOUSE and not can_access_order(actor, order):
            continue
        rows.append(
            {
                "id": event.id,
                "event_type": event.event_type,
                "status": event.status,
                "region": event.region,
                "region_label": region_label(event.region),
                "order_id": order.id,
                "order_number": order.order_number,
                "order_status": order.status,
                "city": order.city,
                "total_amount": order.total_amount,
                "created_at": event.created_at,
                "processed_at": event.processed_at,
            }
        )
    return rows


def process_event(session: Session, actor, event_id: int) -> WarehouseEvent:
    if actor.role not in {ROLE_ADMIN, ROLE_WAREHOUSE}:
        raise AuthorizationError("Only operations users can process warehouse events.")
    event = session.get(WarehouseEvent, event_id)
    if not event:
        raise NotFoundError("Warehouse event was not found.")
    if event.status != "pending":
        raise ValidationError("Only pending events can be processed.")
    order = session.get(Order, event.order_id)
    if not order:
        raise NotFoundError("Related order was not found.")
    if actor.role == ROLE_WAREHOUSE and not can_access_order(actor, order):
        raise AuthorizationError("This event belongs to a different region.")

    if order.status == ORDER_STATUS_CREATED:
        order_service.update_order_status(session, actor, order.id, ORDER_STATUS_CONFIRMED)
    elif order.status == ORDER_STATUS_CANCELLED:
        event.status = "failed"
        event.last_error = "Order was cancelled before warehouse intake."
        event.processed_by_user_id = actor.id
        event.processed_at = utcnow()
        session.add(event)
        session.commit()
        audit_service.log_action(
            session,
            actor=actor,
            action="warehouse.event_failed",
            entity_type="warehouse_event",
            entity_id=str(event.id),
            details={"order_number": order.order_number, "reason": event.last_error},
        )
        return event

    event.status = "processed"
    event.processed_by_user_id = actor.id
    event.processed_at = utcnow()
    session.add(event)
    session.commit()
    session.refresh(event)

    audit_service.log_action(
        session,
        actor=actor,
        action="warehouse.event_processed",
        entity_type="warehouse_event",
        entity_id=str(event.id),
        details={"order_number": order.order_number, "event_type": event.event_type},
    )
    return event


def queue_summary(session: Session, actor) -> dict[str, Any]:
    events = list_events(session, actor, event_status="All", limit=1000)
    pending = [event for event in events if event["status"] == "pending"]
    processed = [event for event in events if event["status"] == "processed"]
    return {
        "pending_events": len(pending),
        "processed_events": len(processed),
        "covered_region": region_label(getattr(actor, "assigned_region", None)) if actor.role == ROLE_WAREHOUSE else "All regions",
    }
