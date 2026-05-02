from __future__ import annotations

import os
from importlib import import_module
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Generator

import h3
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = BASE_DIR / "geo_furniture.db"
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DEFAULT_DB_PATH}")
DEFAULT_H3_RESOLUTION = int(os.getenv("H3_RESOLUTION", "7"))

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def lat_lon_to_h3(latitude: float, longitude: float, resolution: int = DEFAULT_H3_RESOLUTION) -> str:
    return h3.latlng_to_cell(latitude, longitude, resolution)


def create_audit_log(
    db: Session,
    *,
    action: str,
    description: str,
    target_type: str | None = None,
    target_id: int | None = None,
    actor_user=None,
    actor_username: str | None = None,
    metadata: dict | None = None,
):
    models = import_module("app.models")

    audit_log = models.AuditLog(
        actor_user_id=getattr(actor_user, "id", None),
        actor_username=actor_username or getattr(actor_user, "username", "system"),
        action=action,
        target_type=target_type,
        target_id=target_id,
        description=description,
        metadata_json=metadata or {},
    )
    db.add(audit_log)
    db.commit()
    db.refresh(audit_log)
    return audit_log


def init_db() -> None:
    models = import_module("app.models")
    from app.auth import get_password_hash

    Base.metadata.create_all(bind=engine)

    with SessionLocal() as db:
        admin = db.query(models.User).filter(models.User.username == "admin").first()
        customer = db.query(models.User).filter(models.User.username == "customer").first()
        warehouse = db.query(models.User).filter(models.User.username == "warehouse").first()

        warehouse_region = lat_lon_to_h3(43.238949, 76.889709)

        if admin is None:
            admin = models.User(
                username="admin",
                full_name="Ariana Admin",
                role=models.RoleEnum.admin,
                hashed_password=get_password_hash("admin123"),
            )
            db.add(admin)

        if customer is None:
            customer = models.User(
                username="customer",
                full_name="Carter Customer",
                role=models.RoleEnum.customer,
                hashed_password=get_password_hash("customer123"),
            )
            db.add(customer)

        if warehouse is None:
            warehouse = models.User(
                username="warehouse",
                full_name="Wren Warehouse",
                role=models.RoleEnum.warehouse_manager,
                hashed_password=get_password_hash("warehouse123"),
                allowed_h3_region=warehouse_region,
            )
            db.add(warehouse)

        db.commit()
        db.refresh(admin)
        db.refresh(customer)
        db.refresh(warehouse)

        if warehouse.allowed_h3_region != warehouse_region:
            warehouse.allowed_h3_region = warehouse_region
            db.commit()

        if db.query(models.Order).count() == 0:
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            seed_orders = [
                {
                    "customer_id": customer.id,
                    "customer_name": customer.full_name,
                    "product_type": "Scandinavian Sofa",
                    "quantity": 1,
                    "price": 820.0,
                    "latitude": 43.238949,
                    "longitude": 76.889709,
                    "status": models.OrderStatus.pending,
                    "notes": "Deliver after 18:00.",
                    "created_at": now - timedelta(days=5),
                },
                {
                    "customer_id": customer.id,
                    "customer_name": customer.full_name,
                    "product_type": "Executive Office Desk",
                    "quantity": 2,
                    "price": 460.0,
                    "latitude": 43.238949,
                    "longitude": 76.889709,
                    "status": models.OrderStatus.processing,
                    "notes": "Assembly required.",
                    "created_at": now - timedelta(days=4),
                },
                {
                    "customer_id": customer.id,
                    "customer_name": customer.full_name,
                    "product_type": "Oak Dining Set",
                    "quantity": 1,
                    "price": 1190.0,
                    "latitude": 51.160523,
                    "longitude": 71.470356,
                    "status": models.OrderStatus.shipped,
                    "notes": "White glove delivery.",
                    "created_at": now - timedelta(days=3),
                },
                {
                    "customer_id": customer.id,
                    "customer_name": customer.full_name,
                    "product_type": "Minimalist Bed Frame",
                    "quantity": 1,
                    "price": 680.0,
                    "latitude": 42.341685,
                    "longitude": 69.590101,
                    "status": models.OrderStatus.delivered,
                    "notes": "Second floor apartment.",
                    "created_at": now - timedelta(days=2),
                },
                {
                    "customer_id": customer.id,
                    "customer_name": customer.full_name,
                    "product_type": "Lounge Armchair",
                    "quantity": 4,
                    "price": 210.0,
                    "latitude": 49.802816,
                    "longitude": 73.087749,
                    "status": models.OrderStatus.cancelled,
                    "notes": "Cancelled due to color mismatch.",
                    "created_at": now - timedelta(days=1),
                },
                {
                    "customer_id": customer.id,
                    "customer_name": customer.full_name,
                    "product_type": "Storage Cabinet",
                    "quantity": 3,
                    "price": 330.0,
                    "latitude": 43.250244,
                    "longitude": 76.927638,
                    "status": models.OrderStatus.pending,
                    "notes": "Requires loading dock access.",
                    "created_at": now,
                },
            ]

            for seed in seed_orders:
                db.add(
                    models.Order(
                        customer_id=seed["customer_id"],
                        customer_name=seed["customer_name"],
                        product_type=seed["product_type"],
                        quantity=seed["quantity"],
                        price=seed["price"],
                        latitude=seed["latitude"],
                        longitude=seed["longitude"],
                        h3_region=lat_lon_to_h3(seed["latitude"], seed["longitude"]),
                        status=seed["status"],
                        notes=seed["notes"],
                        created_at=seed["created_at"],
                        updated_at=seed["created_at"],
                    )
                )
            db.commit()
