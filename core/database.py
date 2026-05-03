from __future__ import annotations

import json
import random
from datetime import timedelta
from pathlib import Path

import h3
from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine, select

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
from core.security import hash_password
from core.utils import json_dumps, utcnow
from models.audit_log import AuditLog
from models.order import Order
from models.product import Product
from models.user import User, UserSession
from models.warehouse_event import WarehouseEvent


_engine = None
_database_url_override: str | None = None


def _create_app_engine(database_url: str):
    if database_url.startswith("sqlite"):
        engine = create_engine(
            database_url,
            echo=False,
            connect_args={"check_same_thread": False, "timeout": 30},
        )
        event.listen(engine, "connect", _configure_sqlite_connection)
        return engine
    engine = create_engine(database_url, echo=False)
    return engine


def _configure_sqlite_connection(dbapi_connection, _) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


def get_engine():
    global _engine
    if _engine is None:
        database_url = _database_url_override or settings.database_url
        _engine = _create_app_engine(database_url)
    return _engine


def set_database_url(database_url: str) -> None:
    global _engine, _database_url_override
    _database_url_override = database_url
    _engine = _create_app_engine(database_url)


def reset_database_url() -> None:
    global _engine, _database_url_override
    _database_url_override = None
    _engine = None


def get_session() -> Session:
    # Streamlit pages often return ORM objects beyond the session scope.
    # Keep loaded attributes available after commit/close to avoid
    # DetachedInstanceError during page initialization and redirects.
    return Session(get_engine(), expire_on_commit=False)


def init_db() -> None:
    Path(settings.database_path).parent.mkdir(parents=True, exist_ok=True)
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    SQLModel.metadata.create_all(get_engine())
    if settings.demo_seed:
        seed_database_if_empty()


def seed_database_if_empty() -> None:
    with get_session() as session:
        has_users = session.exec(select(User.id)).first()
        if has_users:
            return

        seed_payload = json.loads(SEED_DATA_PATH.read_text(encoding="utf-8"))
        city_payload = seed_payload["cities"]
        city_regions = {
            city["name"]: h3.latlng_to_cell(city["latitude"], city["longitude"], settings.h3_resolution)
            for city in city_payload
        }

        users: list[User] = []
        for raw_user in seed_payload["users"]:
            user = User(
                username=raw_user["username"].strip().lower(),
                full_name=raw_user["full_name"],
                password_hash=hash_password(raw_user["password"]),
                role=raw_user["role"],
                assigned_region=city_regions.get(raw_user.get("assigned_city")),
                is_active=True,
            )
            users.append(user)
        session.add_all(users)
        session.commit()

        products: list[Product] = []
        for raw_product in seed_payload["products"]:
            product = Product(
                sku=raw_product["sku"],
                name=raw_product["name"],
                category=raw_product["category"],
                material=raw_product["material"],
                description=raw_product["description"],
                price=raw_product["price"],
                stock_quantity=raw_product["stock_quantity"],
                dimensions=raw_product["dimensions"],
                is_active=True,
            )
            products.append(product)
        session.add_all(products)
        session.commit()

        admin_user = session.exec(select(User).where(User.role == ROLE_ADMIN)).first()
        customer_user = session.exec(select(User).where(User.role == ROLE_CUSTOMER)).first()

        product_map = {product.sku: product for product in session.exec(select(Product)).all()}
        product_skus = list(product_map.keys())
        rng = random.Random(seed_payload.get("seed", 42))
        status_pool = [
            ORDER_STATUS_CREATED,
            ORDER_STATUS_CONFIRMED,
            ORDER_STATUS_ASSIGNED,
            ORDER_STATUS_PACKED,
            ORDER_STATUS_OUT_FOR_DELIVERY,
            ORDER_STATUS_DELIVERED,
            ORDER_STATUS_CANCELLED,
        ]
        weights = [7, 8, 8, 7, 6, 12, 2]

        customer_profiles = seed_payload.get("customer_profiles", [])
        order_count = seed_payload.get("order_count", 50)

        created_orders: list[Order] = []
        audit_logs: list[AuditLog] = []
        warehouse_events: list[WarehouseEvent] = []

        for index in range(order_count):
            city = rng.choice(city_payload)
            address = rng.choice(city["street_samples"])
            buyer = rng.choice(customer_profiles)
            product = product_map[rng.choice(product_skus)]
            quantity = rng.randint(1, 3)
            status = rng.choices(status_pool, weights=weights, k=1)[0]
            created_at = utcnow() - timedelta(days=rng.randint(1, 120), hours=rng.randint(0, 20))
            latitude = city["latitude"] + rng.uniform(-0.03, 0.03)
            longitude = city["longitude"] + rng.uniform(-0.03, 0.03)
            h3_region = h3.latlng_to_cell(latitude, longitude, settings.h3_resolution)
            order_number = f"FG-{created_at.strftime('%y%m')}-{index + 1000}"
            total_amount = round(product.price * quantity, 2)

            if status != ORDER_STATUS_CANCELLED:
                product.stock_quantity = max(product.stock_quantity - quantity, 0)

            order = Order(
                order_number=order_number,
                customer_id=customer_user.id,
                product_id=product.id,
                quantity=quantity,
                unit_price=product.price,
                total_amount=total_amount,
                status=status,
                recipient_name=buyer["name"],
                phone=buyer["phone"],
                address_line1=address,
                address_line2=buyer.get("address_line2", ""),
                city=city["name"],
                state=city["state"],
                postal_code=buyer["postal_code"],
                country=city["country"],
                latitude=latitude,
                longitude=longitude,
                h3_region=h3_region,
                notes=rng.choice(seed_payload["order_notes"]),
                created_at=created_at,
                updated_at=created_at,
            )

            if status in {
                ORDER_STATUS_CONFIRMED,
                ORDER_STATUS_ASSIGNED,
                ORDER_STATUS_PACKED,
                ORDER_STATUS_OUT_FOR_DELIVERY,
                ORDER_STATUS_DELIVERED,
            }:
                order.confirmed_at = created_at + timedelta(hours=8)
            if status in {
                ORDER_STATUS_ASSIGNED,
                ORDER_STATUS_PACKED,
                ORDER_STATUS_OUT_FOR_DELIVERY,
                ORDER_STATUS_DELIVERED,
            }:
                order.assigned_at = created_at + timedelta(days=1)
            if status in {ORDER_STATUS_PACKED, ORDER_STATUS_OUT_FOR_DELIVERY, ORDER_STATUS_DELIVERED}:
                order.packed_at = created_at + timedelta(days=2)
            if status in {ORDER_STATUS_OUT_FOR_DELIVERY, ORDER_STATUS_DELIVERED}:
                order.out_for_delivery_at = created_at + timedelta(days=3)
            if status == ORDER_STATUS_DELIVERED:
                order.delivered_at = created_at + timedelta(days=5)
            if status == ORDER_STATUS_CANCELLED:
                order.cancelled_at = created_at + timedelta(hours=16)
                order.cancellation_reason = "Cancelled during intake review."

            created_orders.append(order)

        session.add_all(created_orders)
        session.commit()

        for order in created_orders:
            event = create_order_created_event(order)
            if order.status in {
                ORDER_STATUS_CONFIRMED,
                ORDER_STATUS_ASSIGNED,
                ORDER_STATUS_PACKED,
                ORDER_STATUS_OUT_FOR_DELIVERY,
                ORDER_STATUS_DELIVERED,
            }:
                event.status = "processed"
                event.processed_by_user_id = session.exec(select(User.id).where(User.role == ROLE_WAREHOUSE)).first()
                event.processed_at = order.confirmed_at or order.created_at
            warehouse_events.append(event)
            audit_logs.append(
                AuditLog(
                    actor_user_id=admin_user.id,
                    actor_username=admin_user.username,
                    action="seed.order_created",
                    entity_type="order",
                    entity_id=str(order.id),
                    details_json=json_dumps(
                        {
                            "order_number": order.order_number,
                            "status": order.status,
                            "city": order.city,
                            "total_amount": order.total_amount,
                        }
                    ),
                    created_at=order.created_at,
                )
            )
            if order.status != ORDER_STATUS_CREATED:
                audit_logs.append(
                    AuditLog(
                        actor_user_id=admin_user.id,
                        actor_username=admin_user.username,
                        action="seed.order_status_snapshot",
                        entity_type="order",
                        entity_id=str(order.id),
                        details_json=json_dumps(
                            {
                                "order_number": order.order_number,
                                "status": order.status,
                            }
                        ),
                        created_at=order.updated_at,
                    )
                )

        for product in session.exec(select(Product)).all():
            audit_logs.append(
                AuditLog(
                    actor_user_id=admin_user.id,
                    actor_username=admin_user.username,
                    action="seed.product_loaded",
                    entity_type="product",
                    entity_id=str(product.id),
                    details_json=json_dumps(
                        {
                            "sku": product.sku,
                            "name": product.name,
                            "stock_quantity": product.stock_quantity,
                        }
                    ),
                    created_at=utcnow(),
                )
            )

        session.add_all(warehouse_events)
        session.add_all(audit_logs)
        session.commit()
