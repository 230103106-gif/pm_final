from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

TEST_DB_PATH = Path(__file__).resolve().parent / "test_app.db"
ROOT_DIR = Path(__file__).resolve().parent.parent
if TEST_DB_PATH.exists():
    TEST_DB_PATH.unlink()

os.environ["APP_DB_PATH"] = str(TEST_DB_PATH)
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as test_client:
        yield test_client


def login(client: TestClient, username: str, password: str) -> str:
    response = client.post("/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return response.json()["token"]


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_demo_accounts_can_log_in(client: TestClient):
    for username, password in [
        ("admin", "admin123"),
        ("customer", "customer123"),
        ("warehouse", "warehouse123"),
    ]:
        response = client.post("/login", json={"username": username, "password": password})
        assert response.status_code == 200
        payload = response.json()
        assert payload["token"]
        assert payload["user"]["username"] == username


def test_customer_only_sees_own_orders(client: TestClient):
    token = login(client, "customer", "customer123")
    response = client.get("/orders", headers=auth_header(token))
    assert response.status_code == 200
    orders = response.json()
    assert orders
    customer_ids = {order["customer_id"] for order in orders}
    assert len(customer_ids) == 1


def test_warehouse_abac_limits_orders_to_allowed_region(client: TestClient):
    token = login(client, "warehouse", "warehouse123")
    me = client.get("/me", headers=auth_header(token)).json()
    response = client.get("/orders", headers=auth_header(token))
    assert response.status_code == 200
    orders = response.json()
    assert orders
    assert all(order["h3_region"] == me["allowed_region"] for order in orders)


def test_customer_can_create_order_with_h3_region(client: TestClient):
    token = login(client, "customer", "customer123")
    response = client.post(
        "/orders",
        headers=auth_header(token),
        json={
            "customer_name": "Aruzhan Customer",
            "product_type": "Desk",
            "quantity": 2,
            "price": 420.0,
            "latitude": 43.2440,
            "longitude": 76.9012,
        },
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "Pending"
    assert payload["h3_region"]
