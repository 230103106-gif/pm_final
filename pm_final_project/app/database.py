from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import h3
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, declarative_base, sessionmaker

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.getenv("APP_DB_PATH", BASE_DIR / "app.db")).expanduser().resolve()
DATABASE_URL = f"sqlite:///{DB_PATH}"
H3_RESOLUTION = int(os.getenv("H3_RESOLUTION", "5"))

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    future=True,
)
SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    future=True,
)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)


def write_audit_log(
    db: Session,
    *,
    username: str,
    role: str,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    details: str = "",
    user_id: int | None = None,
) -> None:
    from app.models import AuditLog

    db.add(
        AuditLog(
            user_id=user_id,
            username=username,
            role=role,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details,
        )
    )
    db.commit()


def seed_demo_data() -> None:
    from app.auth import hash_password
    from app.models import AuditLog, Order, OrderStatus, User, UserRole

    demo_users = [
        {
            "username": "admin",
            "full_name": "System Administrator",
            "password": "admin123",
            "role": UserRole.ADMIN.value,
            "allowed_region": None,
        },
        {
            "username": "customer",
            "full_name": "Aruzhan Customer",
            "password": "customer123",
            "role": UserRole.CUSTOMER.value,
            "allowed_region": None,
        },
        {
            "username": "warehouse",
            "full_name": "Regional Warehouse Manager",
            "password": "warehouse123",
            "role": UserRole.WAREHOUSE.value,
            "allowed_region": h3.latlng_to_cell(43.238949, 76.889709, H3_RESOLUTION),
        },
    ]

    sample_orders = [
        {
            "product_type": "Sofa",
            "quantity": 2,
            "price": 550.0,
            "latitude": 43.2389,
            "longitude": 76.8897,
            "status": OrderStatus.PENDING.value,
            "days_ago": 5,
        },
        {
            "product_type": "Wardrobe",
            "quantity": 1,
            "price": 780.0,
            "latitude": 43.2567,
            "longitude": 76.9286,
            "status": OrderStatus.PROCESSING.value,
            "days_ago": 4,
        },
        {
            "product_type": "Dining Table",
            "quantity": 1,
            "price": 690.0,
            "latitude": 51.1605,
            "longitude": 71.4704,
            "status": OrderStatus.SHIPPED.value,
            "days_ago": 3,
        },
        {
            "product_type": "Office Chair",
            "quantity": 4,
            "price": 140.0,
            "latitude": 42.3417,
            "longitude": 69.5901,
            "status": OrderStatus.DELIVERED.value,
            "days_ago": 2,
        },
        {
            "product_type": "Bookshelf",
            "quantity": 2,
            "price": 230.0,
            "latitude": 51.1274,
            "longitude": 71.4304,
            "status": OrderStatus.PENDING.value,
            "days_ago": 1,
        },
    ]

    with SessionLocal() as db:
        existing_users = {
            user.username: user for user in db.scalars(select(User)).all()
        }

        for demo_user in demo_users:
            if demo_user["username"] in existing_users:
                user = existing_users[demo_user["username"]]
                if demo_user["allowed_region"] and not user.allowed_region:
                    user.allowed_region = demo_user["allowed_region"]
                continue

            db.add(
                User(
                    username=demo_user["username"],
                    full_name=demo_user["full_name"],
                    password_hash=hash_password(demo_user["password"]),
                    role=demo_user["role"],
                    allowed_region=demo_user["allowed_region"],
                )
            )

        db.commit()

        all_users = {user.username: user for user in db.scalars(select(User)).all()}
        customer_user = all_users["customer"]

        existing_order = db.scalars(select(Order).limit(1)).first()
        if existing_order:
            return

        now = datetime.now(UTC)
        seeded_orders: list[Order] = []
        for item in sample_orders:
            created_at = now - timedelta(days=item["days_ago"])
            seeded_orders.append(
                Order(
                    customer_id=customer_user.id,
                    customer_name=customer_user.full_name,
                    product_type=item["product_type"],
                    quantity=item["quantity"],
                    price=item["price"],
                    latitude=item["latitude"],
                    longitude=item["longitude"],
                    h3_region=h3.latlng_to_cell(
                        item["latitude"],
                        item["longitude"],
                        H3_RESOLUTION,
                    ),
                    status=item["status"],
                    created_at=created_at,
                    updated_at=created_at,
                )
            )

        db.add_all(seeded_orders)
        db.flush()

        for order in seeded_orders:
            db.add(
                AuditLog(
                    user_id=customer_user.id,
                    username=customer_user.username,
                    role=customer_user.role,
                    action="seed_order_create",
                    entity_type="order",
                    entity_id=str(order.id),
                    details=f"Seeded demo order for {order.product_type}.",
                    created_at=order.created_at,
                )
            )

        db.commit()
