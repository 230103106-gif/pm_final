from __future__ import annotations

from models.order import Order
from models.warehouse_event import WarehouseEvent

from core.utils import json_dumps


def create_order_created_event(order: Order) -> WarehouseEvent:
    payload = {
        "order_number": order.order_number,
        "product_id": order.product_id,
        "quantity": order.quantity,
        "total_amount": order.total_amount,
        "delivery_city": order.city,
        "status": order.status,
    }
    return WarehouseEvent(
        order_id=order.id,
        event_type="order.created",
        region=order.h3_region,
        payload_json=json_dumps(payload),
        status="pending",
    )
