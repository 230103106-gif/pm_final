from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from core.database import init_db, reset_database_url, set_database_url
from services import order_service


@pytest.fixture()
def api_client(tmp_path):
    db_path = tmp_path / "api_test.db"
    set_database_url(f"sqlite:///{db_path}")
    init_db()
    from api import app

    with TestClient(app) as client:
        yield client
    reset_database_url()


@pytest.fixture()
def service_database(tmp_path):
    db_path = tmp_path / "service_test.db"
    set_database_url(f"sqlite:///{db_path}")
    init_db()
    try:
        yield
    finally:
        reset_database_url()


def auth_headers(client: TestClient, username: str, password: str) -> dict[str, str]:
    response = client.post("/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_health_and_swagger_are_available(api_client):
    assert api_client.get("/health").json() == {"status": "ok"}
    docs = api_client.get("/docs")
    assert docs.status_code == 200
    assert "Swagger UI" in docs.text


def test_customer_can_create_order_and_admin_can_process_event(api_client):
    customer_headers = auth_headers(api_client, "customer", "Customer@123")
    products = api_client.get("/products", headers=customer_headers).json()
    product = next(row for row in products if row["stock_quantity"] > 0)

    create_response = api_client.post(
        "/orders",
        headers=customer_headers,
        json={
            "product_id": product["id"],
            "quantity": 1,
            "recipient_name": "Taylor Green",
            "phone": "+1 312 555 0182",
            "address_line1": "1717 N Halsted Street",
            "address_line2": "Suite 210",
            "city": "Chicago",
            "state": "IL",
            "postal_code": "60614",
            "country": "USA",
            "latitude": 41.8781,
            "longitude": -87.6298,
            "notes": "Freight elevator available.",
        },
    )
    assert create_response.status_code == 201
    order = create_response.json()
    assert order["status"] == "Created"
    assert order["h3_region"]

    admin_headers = auth_headers(api_client, "admin", "Admin@123")
    events = api_client.get("/warehouse/events", headers=admin_headers, params={"status": "pending"}).json()
    event = next(row for row in events if row["order_id"] == order["id"])

    process_response = api_client.post(f"/warehouse/events/{event['id']}/process", headers=admin_headers)
    assert process_response.status_code == 200
    assert process_response.json()["status"] == "processed"

    detail_response = api_client.get(f"/orders/{order['id']}", headers=admin_headers)
    assert detail_response.json()["status"] == "Confirmed"


def test_api_enforces_warehouse_abac_scope(api_client):
    admin_headers = auth_headers(api_client, "admin", "Admin@123")
    warehouse_headers = auth_headers(api_client, "warehouse", "Warehouse@123")

    warehouse_user = api_client.get("/users/me", headers=warehouse_headers).json()
    visible_orders = api_client.get("/orders", headers=warehouse_headers).json()
    assert visible_orders
    assert all(row["h3_region"] == warehouse_user["assigned_region"] for row in visible_orders)

    all_orders = api_client.get("/orders", headers=admin_headers).json()
    foreign_order = next(row for row in all_orders if row["h3_region"] != warehouse_user["assigned_region"])
    response = api_client.get(f"/orders/{foreign_order['id']}", headers=warehouse_headers)
    assert response.status_code == 403


def test_api_blocks_customer_from_operations_data(api_client):
    customer_headers = auth_headers(api_client, "customer", "Customer@123")

    assert api_client.get("/warehouse/events", headers=customer_headers).status_code == 403
    assert api_client.get("/audit/logs", headers=customer_headers).status_code == 403
    assert api_client.get("/analytics/kpis", headers=customer_headers).status_code == 403


def test_blank_order_fields_are_rejected_by_service(service_database):
    from sqlmodel import select

    from core.database import get_session
    from core.utils import ValidationError
    from models.product import Product
    from models.user import User

    with get_session() as session:
        customer = session.exec(select(User).where(User.username == "customer")).first()
        product = session.exec(select(Product).where(Product.is_active == True)).first()

        with pytest.raises(ValidationError):
            order_service.create_order(
                session,
                customer,
                product_id=product.id,
                quantity=1,
                recipient_name="",
                phone="+1 312 555 0182",
                address_line1="1717 N Halsted Street",
                address_line2="",
                city="Chicago",
                state="IL",
                postal_code="60614",
                country="USA",
                latitude=41.8781,
                longitude=-87.6298,
            )
