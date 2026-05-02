from __future__ import annotations

import logging
import threading
from queue import Queue
from time import sleep

from app.database import SessionLocal, create_audit_log

logger = logging.getLogger(__name__)
event_queue: Queue[dict] = Queue()
_worker_thread: threading.Thread | None = None
_worker_lock = threading.Lock()


def enqueue_order_event(order_id: int, h3_region: str, customer_name: str) -> None:
    event_queue.put(
        {
            "event_type": "order_created",
            "order_id": order_id,
            "h3_region": h3_region,
            "customer_name": customer_name,
        }
    )


def _process_events_forever() -> None:
    while True:
        event = event_queue.get()
        try:
            sleep(0.35)
            if event.get("event_type") == "order_created":
                with SessionLocal() as db:
                    description = f"Warehouse notified for Order #{event['order_id']}"
                    create_audit_log(
                        db,
                        action="warehouse_notification",
                        description=description,
                        target_type="order",
                        target_id=event["order_id"],
                        actor_username="system",
                        metadata={
                            "h3_region": event["h3_region"],
                            "customer_name": event["customer_name"],
                        },
                    )
        except Exception:
            logger.exception("Queue worker failed to process event: %s", event)
        finally:
            event_queue.task_done()


def start_queue_worker() -> None:
    global _worker_thread

    with _worker_lock:
        if _worker_thread and _worker_thread.is_alive():
            return

        _worker_thread = threading.Thread(
            target=_process_events_forever,
            name="geo-furniture-queue-worker",
            daemon=True,
        )
        _worker_thread.start()
