from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from core.config import EXPORT_DIR
from core.utils import NotFoundError, ValidationError, currency, utcnow
from models.product import Product
from services import audit_service


REQUIRED_TEXT_FIELDS = ("sku", "name", "category", "material", "description", "dimensions")


def _validate_required_text(payload: dict[str, Any], fields: tuple[str, ...]) -> None:
    for field in fields:
        value = str(payload.get(field, "")).strip()
        if not value:
            raise ValidationError(f"{field.replace('_', ' ').title()} is required.")


def get_product(session: Session, product_id: int) -> Product:
    product = session.get(Product, product_id)
    if not product:
        raise NotFoundError("Product was not found.")
    return product


def list_products(
    session: Session,
    *,
    include_inactive: bool = False,
    category: str | None = None,
    search: str | None = None,
) -> list[Product]:
    query = select(Product).order_by(Product.name)
    if not include_inactive:
        query = query.where(Product.is_active == True)
    if category and category != "All":
        query = query.where(Product.category == category)
    products = session.exec(query).all()
    if search:
        needle = search.strip().lower()
        products = [
            product
            for product in products
            if needle in product.name.lower()
            or needle in product.sku.lower()
            or needle in product.description.lower()
        ]
    return products


def categories(session: Session) -> list[str]:
    products = session.exec(select(Product.category).distinct().order_by(Product.category)).all()
    return [value for value in products if value]


def product_rows(products: list[Product]) -> list[dict[str, Any]]:
    return [
        {
            "id": product.id,
            "sku": product.sku,
            "name": product.name,
            "category": product.category,
            "material": product.material,
            "price": currency(product.price),
            "stock": product.stock_quantity,
            "dimensions": product.dimensions,
            "active": "Yes" if product.is_active else "No",
        }
        for product in products
    ]


def create_product(session: Session, actor, payload: dict[str, Any]) -> Product:
    _validate_required_text(payload, REQUIRED_TEXT_FIELDS)
    sku = payload["sku"].strip().upper()
    existing = session.exec(select(Product).where(Product.sku == sku)).first()
    if existing:
        raise ValidationError("SKU already exists.")
    if payload["price"] <= 0:
        raise ValidationError("Price must be greater than zero.")
    if payload["stock_quantity"] < 0:
        raise ValidationError("Stock quantity cannot be negative.")

    product = Product(
        sku=sku,
        name=payload["name"].strip(),
        category=payload["category"].strip(),
        material=payload["material"].strip(),
        description=payload["description"].strip(),
        price=float(payload["price"]),
        stock_quantity=int(payload["stock_quantity"]),
        dimensions=payload["dimensions"].strip(),
        is_active=True,
    )
    session.add(product)
    session.commit()
    session.refresh(product)
    audit_service.log_action(
        session,
        actor=actor,
        action="product.created",
        entity_type="product",
        entity_id=str(product.id),
        details={"sku": product.sku, "name": product.name},
    )
    return product


def update_product(session: Session, actor, product_id: int, payload: dict[str, Any]) -> Product:
    product = get_product(session, product_id)
    _validate_required_text(payload, REQUIRED_TEXT_FIELDS[1:])
    if payload["price"] <= 0:
        raise ValidationError("Price must be greater than zero.")
    if payload["stock_quantity"] < 0:
        raise ValidationError("Stock quantity cannot be negative.")

    product.name = payload["name"].strip()
    product.category = payload["category"].strip()
    product.material = payload["material"].strip()
    product.description = payload["description"].strip()
    product.price = float(payload["price"])
    product.stock_quantity = int(payload["stock_quantity"])
    product.dimensions = payload["dimensions"].strip()
    product.is_active = bool(payload["is_active"])
    product.updated_at = utcnow()

    session.add(product)
    session.commit()
    session.refresh(product)
    audit_service.log_action(
        session,
        actor=actor,
        action="product.updated",
        entity_type="product",
        entity_id=str(product.id),
        details={
            "sku": product.sku,
            "price": product.price,
            "stock_quantity": product.stock_quantity,
            "is_active": product.is_active,
        },
    )
    return product


def export_products_json(session: Session) -> tuple[Path, bytes]:
    products = list_products(session, include_inactive=True)
    payload = json.dumps(
        [
            {
                "id": product.id,
                "sku": product.sku,
                "name": product.name,
                "category": product.category,
                "material": product.material,
                "description": product.description,
                "price": product.price,
                "stock_quantity": product.stock_quantity,
                "dimensions": product.dimensions,
                "is_active": product.is_active,
            }
            for product in products
        ],
        indent=2,
    ).encode("utf-8")
    export_path = EXPORT_DIR / "products.json"
    export_path.write_bytes(payload)
    return export_path, payload
