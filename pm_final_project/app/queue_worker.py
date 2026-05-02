from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from queue import Queue
from threading import Lock, Thread

from app.database import SessionLocal, write_audit_log
from app.models import User


@dataclass(slots=True)
class OrderEvent:
    order_id: int
    region: str
    created_by: str


event_queue: Queue[OrderEvent] = Queue()
notification_store: deque[dict[str, object]] = deque(maxlen=100)
worker_lock = Lock()
worker_started = False


def _notification_worker() -> None:
    while True:
        event = event_queue.get()
        timestamp = datetime.now(UTC)
        notification = {
            "id": f"notif-{event.order_id}-{int(timestamp.timestamp())}",
            "message": f"Warehouse notified for Order #{event.order_id}",
            "order_id": event.order_id,
            "region": event.region,
            "created_at": timestamp.isoformat(),
        }
        notification_store.appendleft(notification)

        with SessionLocal() as db:
            warehouse_user = db.query(User).filter(User.allowed_region == event.region).first()
            target_name = warehouse_user.username if warehouse_user else "warehouse"
            write_audit_log(
                db,
                username="system",
                role="system",
                action="warehouse_notified",
                entity_type="order",
                entity_id=str(event.order_id),
                details=(
                    f"Queued event from {event.created_by} processed and regional "
                    f"warehouse user {target_name} was notified."
                ),
            )
        event_queue.task_done()


def start_worker() -> None:
    global worker_started

    with worker_lock:
        if worker_started:
            return
        thread = Thread(target=_notification_worker, daemon=True, name="order-notification-worker")
        thread.start()
        worker_started = True


def enqueue_order_event(order_id: int, region: str, created_by: str) -> None:
    event_queue.put(OrderEvent(order_id=order_id, region=region, created_by=created_by))


def list_notifications_for_user(user: User, limit: int = 15) -> list[dict[str, object]]:
    relevant = list(notification_store)
    if user.role == "warehouse":
        relevant = [item for item in relevant if item["region"] == user.allowed_region]
    return relevant[:limit]
