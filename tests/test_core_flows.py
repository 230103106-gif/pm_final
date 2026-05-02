from __future__ import annotations

import h3
import pytest
from sqlmodel import select

from core import auth
from core.database import get_session, init_db, reset_database_url, set_database_url
from core.utils import AuthorizationError
from models.product import Product
from models.user import User
from models.warehouse_event import WarehouseEvent
from services import order_service, user_service


@pytest.fixture()
def seeded_database(tmp_path):
    db_path = tmp_path / "test_app.db"
    set_database_url(f"sqlite:///{db_path}")
    init_db()
    try:
        yield db_path
    finally:
        reset_database_url()


def test_login_flow_with_persistent_session(seeded_database):
    with get_session() as session:
        user = user_service.authenticate_user(session, "admin", "Admin@123")
        assert user.role == "admin"

        token = user_service.start_user_session(session, user)
        resolved = user_service.user_from_session_token(session, token)
        assert resolved is not None
        assert resolved.username == "admin"
        detached_copy = resolved

    assert detached_copy.role == "admin"


def test_order_creation_persists_and_generates_event(seeded_database):
    with get_session() as session:
        customer = session.exec(select(User).where(User.username == "customer")).first()
        product = session.exec(select(Product).where(Product.is_active == True)).first()
        stock_before = product.stock_quantity

        order = order_service.create_order(
            session,
            customer,
            product_id=product.id,
            quantity=2,
            recipient_name="Taylor Green",
            phone="+1 312 555 0182",
            address_line1="1717 N Halsted Street",
            address_line2="Suite 210",
            city="Chicago",
            state="IL",
            postal_code="60614",
            country="USA",
            latitude=41.9145,
            longitude=-87.6486,
            notes="Freight elevator booking confirmed for 4 PM.",
        )

        refreshed_product = session.get(Product, product.id)
        event = session.exec(select(WarehouseEvent).where(WarehouseEvent.order_id == order.id)).first()

        assert order.status == "Created"
        assert refreshed_product.stock_quantity == stock_before - 2
        assert event is not None
        assert event.status == "pending"


def test_h3_region_assignment_matches_coordinates(seeded_database):
    with get_session() as session:
        customer = session.exec(select(User).where(User.username == "customer")).first()
        product = session.exec(select(Product).where(Product.is_active == True)).first()
        latitude = 47.608013
        longitude = -122.335167

        order = order_service.create_order(
            session,
            customer,
            product_id=product.id,
            quantity=1,
            recipient_name="Sam Rivera",
            phone="+1 206 555 0107",
            address_line1="121 Stewart Street",
            address_line2="Floor 6",
            city="Seattle",
            state="WA",
            postal_code="98101",
            country="USA",
            latitude=latitude,
            longitude=longitude,
            notes="Coordinate with loading dock before unloading.",
        )

        assert order.h3_region == h3.latlng_to_cell(latitude, longitude, order_service.settings.h3_resolution)


def test_customer_account_registration_creates_active_customer(seeded_database):
    with get_session() as session:
        created = user_service.create_user(
            session,
            username="new_customer",
            full_name="New Customer",
            password="StrongPass123",
            role="customer",
        )

        resolved = session.exec(select(User).where(User.username == "new_customer")).first()
        assert resolved is not None
        assert created.role == "customer"
        assert resolved.is_active is True


def test_browser_session_cookie_round_trip(seeded_database):
    with get_session() as session:
        user = session.exec(select(User).where(User.username == "customer")).first()
        cookie_value = auth.build_browser_session_cookie(user, "opaque-session-token")
        payload = auth.parse_browser_session_cookie(cookie_value)

        assert payload is not None
        assert payload["user_id"] == user.id
        assert payload["username"] == "customer"
        assert payload["role"] == "customer"
        assert payload["session_token"] == "opaque-session-token"


def test_warehouse_rbac_blocks_out_of_region_orders(seeded_database):
    with get_session() as session:
        warehouse_user = session.exec(select(User).where(User.username == "warehouse")).first()
        visible_orders = order_service.list_orders(session, warehouse_user, include_cancelled=True)
        assert visible_orders
        assert all(row["h3_region"] == warehouse_user.assigned_region for row in visible_orders)

        foreign_order = session.exec(select(order_service.Order).where(order_service.Order.h3_region != warehouse_user.assigned_region)).first()
        with pytest.raises(AuthorizationError):
            order_service.get_order(session, warehouse_user, foreign_order.id)
