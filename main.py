from __future__ import annotations

import hashlib
import json
import queue
import secrets
import sqlite3
import threading
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Literal

import h3
from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "capstone.db"

H3_RESOLUTION = 7
EVENT_QUEUE: queue.Queue[dict[str, Any]] = queue.Queue()
WORKER_STOP = threading.Event()
WORKER_THREAD: threading.Thread | None = None

Role = Literal["admin", "customer", "warehouse_manager"]
OrderStatus = Literal[
    "pending",
    "queued_for_warehouse",
    "processing",
    "ready_for_dispatch",
    "delivered",
    "cancelled",
]
Priority = Literal["standard", "express"]

DEMO_CREDENTIALS = {
    "admin@saturnpro.local": "Admin#1234",
    "customer@saturnpro.local": "Customer#1234",
    "warehouse@saturnpro.local": "Warehouse#1234",
}


class LoginRequest(BaseModel):
    email: str
    password: str


class UserCreate(BaseModel):
    full_name: str = Field(min_length=3)
    email: str = Field(min_length=5)
    password: str = Field(min_length=8)
    role: Role


class OrderItemInput(BaseModel):
    product_name: str = Field(min_length=2)
    sku: str = Field(min_length=2)
    quantity: int = Field(gt=0, le=500)
    unit_price: float = Field(gt=0)


class OrderCreate(BaseModel):
    customer_id: int | None = None
    address_line: str = Field(min_length=5)
    city: str = Field(min_length=2)
    latitude: float
    longitude: float
    priority: Priority = "standard"
    notes: str = ""
    items: list[OrderItemInput] = Field(min_length=1, max_length=8)

    @field_validator("latitude")
    @classmethod
    def validate_latitude(cls, value: float) -> float:
        if not -90 <= value <= 90:
            raise ValueError("Latitude must be between -90 and 90.")
        return value

    @field_validator("longitude")
    @classmethod
    def validate_longitude(cls, value: float) -> float:
        if not -180 <= value <= 180:
            raise ValueError("Longitude must be between -180 and 180.")
        return value


class OrderUpdate(BaseModel):
    status: OrderStatus | None = None
    priority: Priority | None = None
    notes: str | None = None
    address_line: str | None = None
    city: str | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_connection() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


@contextmanager
def db_cursor() -> sqlite3.Connection:
    connection = get_connection()
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        120_000,
    ).hex()
    return f"{salt}${digest}"


def verify_password(password: str, password_hash: str) -> bool:
    salt, digest = password_hash.split("$", 1)
    comparison = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        120_000,
    ).hex()
    return secrets.compare_digest(comparison, digest)


def init_db() -> None:
    with db_cursor() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('admin', 'customer', 'warehouse_manager')),
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_number TEXT NOT NULL UNIQUE,
                customer_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                address_line TEXT NOT NULL,
                city TEXT NOT NULL,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                region_h3 TEXT NOT NULL,
                priority TEXT NOT NULL CHECK(priority IN ('standard', 'express')),
                status TEXT NOT NULL CHECK(status IN ('pending', 'queued_for_warehouse', 'processing', 'ready_for_dispatch', 'delivered', 'cancelled')),
                notes TEXT NOT NULL DEFAULT '',
                total_price REAL NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS order_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
                product_name TEXT NOT NULL,
                sku TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                unit_price REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
                warehouse_region TEXT NOT NULL,
                message TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'new',
                created_at TEXT NOT NULL,
                processed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                actor_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                action TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id INTEGER,
                detail_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
            CREATE INDEX IF NOT EXISTS idx_orders_customer_id ON orders(customer_id);
            CREATE INDEX IF NOT EXISTS idx_orders_region_h3 ON orders(region_h3);
            CREATE INDEX IF NOT EXISTS idx_notifications_order_id ON notifications(order_id);
            CREATE INDEX IF NOT EXISTS idx_audit_logs_entity ON audit_logs(entity_type, entity_id);
            """
        )
        seed_demo_data(connection)


def public_user(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "full_name": row["full_name"],
        "email": row["email"],
        "role": row["role"],
        "created_at": row["created_at"],
    }


def write_audit_log(
    connection: sqlite3.Connection,
    actor_user_id: int | None,
    action: str,
    entity_type: str,
    entity_id: int | None,
    detail: dict[str, Any],
) -> None:
    connection.execute(
        """
        INSERT INTO audit_logs (actor_user_id, action, entity_type, entity_id, detail_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            actor_user_id,
            action,
            entity_type,
            entity_id,
            json.dumps(detail),
            utc_now(),
        ),
    )


def generate_order_number() -> str:
    today = datetime.now().strftime("%Y%m%d")
    suffix = secrets.token_hex(2).upper()
    return f"FUR-{today}-{suffix}"


def create_session(connection: sqlite3.Connection, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    connection.execute(
        "INSERT INTO sessions (token, user_id, created_at) VALUES (?, ?, ?)",
        (token, user_id, utc_now()),
    )
    return token


def get_user_by_email(connection: sqlite3.Connection, email: str) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT * FROM users WHERE lower(email) = lower(?)",
        (email.strip(),),
    ).fetchone()


def get_user_by_id(connection: sqlite3.Connection, user_id: int) -> sqlite3.Row | None:
    return connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def get_user_by_token(token: str) -> dict[str, Any] | None:
    with db_cursor() as connection:
        row = connection.execute(
            """
            SELECT u.*
            FROM sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token = ?
            """,
            (token,),
        ).fetchone()
        return dict(row) if row else None


def require_bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token.",
        )
    return authorization.split(" ", 1)[1].strip()


def get_current_user(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    token = require_bearer_token(authorization)
    user = get_user_by_token(token)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session.",
        )
    return user


def get_current_token(authorization: str | None = Header(default=None)) -> str:
    return require_bearer_token(authorization)


CurrentUser = Annotated[dict[str, Any], Depends(get_current_user)]


def require_roles(*roles: Role):
    def dependency(user: CurrentUser) -> dict[str, Any]:
        if user["role"] not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to this resource.",
            )
        return user

    return dependency


def get_order_row(connection: sqlite3.Connection, order_id: int) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT
            o.*,
            u.full_name AS customer_name,
            u.email AS customer_email
        FROM orders o
        JOIN users u ON u.id = o.customer_id
        WHERE o.id = ?
        """,
        (order_id,),
    ).fetchone()


def get_order_items(connection: sqlite3.Connection, order_id: int) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT id, product_name, sku, quantity, unit_price
        FROM order_items
        WHERE order_id = ?
        ORDER BY id
        """,
        (order_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def serialize_order(connection: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    center_lat, center_lng = h3.cell_to_latlng(row["region_h3"])
    return {
        "id": row["id"],
        "order_number": row["order_number"],
        "customer": {
            "id": row["customer_id"],
            "full_name": row["customer_name"],
            "email": row["customer_email"],
        },
        "address_line": row["address_line"],
        "city": row["city"],
        "latitude": row["latitude"],
        "longitude": row["longitude"],
        "region_h3": row["region_h3"],
        "region_center": {"lat": center_lat, "lng": center_lng},
        "priority": row["priority"],
        "status": row["status"],
        "notes": row["notes"],
        "total_price": round(row["total_price"], 2),
        "items": get_order_items(connection, row["id"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_orders(
    connection: sqlite3.Connection,
    user: dict[str, Any],
    status_filter: str | None = None,
    region_filter: str | None = None,
) -> list[dict[str, Any]]:
    query = """
        SELECT
            o.*,
            u.full_name AS customer_name,
            u.email AS customer_email
        FROM orders o
        JOIN users u ON u.id = o.customer_id
        WHERE 1 = 1
    """
    parameters: list[Any] = []

    if user["role"] == "customer":
        query += " AND o.customer_id = ?"
        parameters.append(user["id"])

    if status_filter:
        query += " AND o.status = ?"
        parameters.append(status_filter)

    if region_filter:
        query += " AND o.region_h3 = ?"
        parameters.append(region_filter)

    query += " ORDER BY o.created_at DESC"
    rows = connection.execute(query, parameters).fetchall()
    return [serialize_order(connection, row) for row in rows]


def list_users(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT id, full_name, email, role, created_at
        FROM users
        ORDER BY created_at DESC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def list_notifications(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT
            n.*,
            o.order_number,
            o.status AS order_status
        FROM notifications n
        JOIN orders o ON o.id = n.order_id
        ORDER BY n.created_at DESC
        LIMIT 50
        """
    ).fetchall()
    return [dict(row) for row in rows]


def list_audit_logs(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT
            a.id,
            a.action,
            a.entity_type,
            a.entity_id,
            a.detail_json,
            a.created_at,
            u.full_name AS actor_name,
            u.email AS actor_email
        FROM audit_logs a
        LEFT JOIN users u ON u.id = a.actor_user_id
        ORDER BY a.created_at DESC
        LIMIT 100
        """
    ).fetchall()
    logs: list[dict[str, Any]] = []
    for row in rows:
        payload = dict(row)
        payload["detail"] = json.loads(payload.pop("detail_json"))
        logs.append(payload)
    return logs


def list_region_analytics(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT
            region_h3,
            COUNT(*) AS order_count,
            ROUND(SUM(total_price), 2) AS revenue_total,
            SUM(CASE WHEN status = 'queued_for_warehouse' THEN 1 ELSE 0 END) AS queued_count,
            SUM(CASE WHEN status = 'processing' THEN 1 ELSE 0 END) AS processing_count,
            SUM(CASE WHEN status = 'delivered' THEN 1 ELSE 0 END) AS delivered_count
        FROM orders
        GROUP BY region_h3
        ORDER BY order_count DESC, revenue_total DESC
        """
    ).fetchall()
    analytics: list[dict[str, Any]] = []
    for row in rows:
        center_lat, center_lng = h3.cell_to_latlng(row["region_h3"])
        analytics.append(
            {
                "region_h3": row["region_h3"],
                "order_count": row["order_count"],
                "revenue_total": row["revenue_total"] or 0,
                "queued_count": row["queued_count"],
                "processing_count": row["processing_count"],
                "delivered_count": row["delivered_count"],
                "center": {"lat": center_lat, "lng": center_lng},
            }
        )
    return analytics


def calculate_total(items: list[OrderItemInput]) -> float:
    return round(sum(item.quantity * item.unit_price for item in items), 2)


def create_order_record(
    connection: sqlite3.Connection,
    payload: OrderCreate,
    customer_id: int,
    actor_user_id: int | None,
) -> dict[str, Any]:
    total_price = calculate_total(payload.items)
    now = utc_now()
    region_h3 = h3.latlng_to_cell(payload.latitude, payload.longitude, H3_RESOLUTION)
    order_number = generate_order_number()

    cursor = connection.execute(
        """
        INSERT INTO orders (
            order_number,
            customer_id,
            address_line,
            city,
            latitude,
            longitude,
            region_h3,
            priority,
            status,
            notes,
            total_price,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            order_number,
            customer_id,
            payload.address_line,
            payload.city,
            payload.latitude,
            payload.longitude,
            region_h3,
            payload.priority,
            "pending",
            payload.notes.strip(),
            total_price,
            now,
            now,
        ),
    )
    order_id = cursor.lastrowid

    for item in payload.items:
        connection.execute(
            """
            INSERT INTO order_items (order_id, product_name, sku, quantity, unit_price)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                order_id,
                item.product_name.strip(),
                item.sku.strip().upper(),
                item.quantity,
                round(item.unit_price, 2),
            ),
        )

    write_audit_log(
        connection,
        actor_user_id=actor_user_id,
        action="order_created",
        entity_type="order",
        entity_id=order_id,
        detail={
            "order_number": order_number,
            "region_h3": region_h3,
            "line_items": len(payload.items),
            "total_price": total_price,
        },
    )

    row = get_order_row(connection, order_id)
    if row is None:
        raise HTTPException(status_code=500, detail="Failed to create order.")
    return serialize_order(connection, row)


def create_notification_for_order(order_id: int, actor_user_id: int | None) -> None:
    with db_cursor() as connection:
        order_row = get_order_row(connection, order_id)
        if not order_row:
            return

        message = (
            f"Warehouse alert: {order_row['order_number']} entered region "
            f"{order_row['region_h3']} and is ready for fulfillment."
        )
        connection.execute(
            """
            INSERT INTO notifications (order_id, warehouse_region, message, status, created_at, processed_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                order_id,
                order_row["region_h3"],
                message,
                "new",
                utc_now(),
                utc_now(),
            ),
        )
        connection.execute(
            """
            UPDATE orders
            SET status = CASE
                WHEN status = 'pending' THEN 'queued_for_warehouse'
                ELSE status
            END,
                updated_at = ?
            WHERE id = ?
            """,
            (utc_now(), order_id),
        )
        write_audit_log(
            connection,
            actor_user_id=actor_user_id,
            action="warehouse_notified",
            entity_type="order",
            entity_id=order_id,
            detail={
                "region_h3": order_row["region_h3"],
                "message": message,
                "channel": "python_queue",
            },
        )


def process_event(event: dict[str, Any]) -> None:
    if event["type"] == "order_created":
        create_notification_for_order(
            order_id=event["order_id"],
            actor_user_id=event.get("actor_user_id"),
        )


def worker_loop() -> None:
    while not WORKER_STOP.is_set():
        try:
            event = EVENT_QUEUE.get(timeout=0.5)
        except queue.Empty:
            continue

        try:
            process_event(event)
        finally:
            EVENT_QUEUE.task_done()


def start_worker() -> None:
    global WORKER_THREAD
    WORKER_STOP.clear()
    if WORKER_THREAD and WORKER_THREAD.is_alive():
        return
    WORKER_THREAD = threading.Thread(target=worker_loop, name="warehouse-event-worker", daemon=True)
    WORKER_THREAD.start()


def stop_worker() -> None:
    WORKER_STOP.set()
    if WORKER_THREAD and WORKER_THREAD.is_alive():
        WORKER_THREAD.join(timeout=2)


def ensure_customer_access(order_row: sqlite3.Row, user: dict[str, Any]) -> None:
    if user["role"] == "customer" and order_row["customer_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="You can only access your own orders.")


def compute_stats(
    orders: list[dict[str, Any]],
    notifications: list[dict[str, Any]],
    analytics: list[dict[str, Any]],
    user_count: int,
) -> dict[str, Any]:
    return {
        "total_orders": len(orders),
        "queued_orders": sum(order["status"] == "queued_for_warehouse" for order in orders),
        "processing_orders": sum(order["status"] == "processing" for order in orders),
        "delivered_orders": sum(order["status"] == "delivered" for order in orders),
        "total_revenue": round(sum(order["total_price"] for order in orders), 2),
        "active_regions": len(analytics),
        "pending_notifications": sum(item["status"] == "new" for item in notifications),
        "user_count": user_count,
    }


def seed_demo_data(connection: sqlite3.Connection) -> None:
    user_count = connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if user_count == 0:
        for email, password in DEMO_CREDENTIALS.items():
            if email.startswith("admin"):
                full_name, role = "Aruzhan Admin", "admin"
            elif email.startswith("customer"):
                full_name, role = "Nursultan Customer", "customer"
            else:
                full_name, role = "Madi Warehouse", "warehouse_manager"
            connection.execute(
                """
                INSERT INTO users (full_name, email, password_hash, role, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (full_name, email, hash_password(password), role, utc_now()),
            )

    order_count = connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    if order_count > 0:
        return

    customer = get_user_by_email(connection, "customer@saturnpro.local")
    if not customer:
        return

    demo_orders = [
        OrderCreate(
            address_line="12 Abai Avenue",
            city="Almaty",
            latitude=43.238949,
            longitude=76.889709,
            priority="express",
            notes="Need white-glove delivery for office setup.",
            items=[
                OrderItemInput(product_name="Executive Desk", sku="DSK-201", quantity=1, unit_price=620.0),
                OrderItemInput(product_name="Ergo Chair", sku="CHR-115", quantity=4, unit_price=180.0),
            ],
        ),
        OrderCreate(
            address_line="77 Mangilik El Avenue",
            city="Astana",
            latitude=51.128207,
            longitude=71.430420,
            priority="standard",
            notes="Customer wants assembly on delivery day.",
            items=[
                OrderItemInput(product_name="Storage Cabinet", sku="CBN-410", quantity=2, unit_price=310.0),
                OrderItemInput(product_name="Meeting Table", sku="TBL-720", quantity=1, unit_price=540.0),
            ],
        ),
    ]

    for payload in demo_orders:
        order = create_order_record(
            connection=connection,
            payload=payload,
            customer_id=customer["id"],
            actor_user_id=customer["id"],
        )
        connection.execute(
            """
            INSERT INTO notifications (order_id, warehouse_region, message, status, created_at, processed_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                order["id"],
                order["region_h3"],
                f"Warehouse alert: {order['order_number']} entered region {order['region_h3']} and is ready for fulfillment.",
                "new",
                utc_now(),
                utc_now(),
            ),
        )
        connection.execute(
            """
            UPDATE orders
            SET status = 'queued_for_warehouse', updated_at = ?
            WHERE id = ?
            """,
            (utc_now(), order["id"]),
        )
        write_audit_log(
            connection,
            actor_user_id=customer["id"],
            action="warehouse_notified",
            entity_type="order",
            entity_id=order["id"],
            detail={
                "region_h3": order["region_h3"],
                "message": "Seeded warehouse notification.",
                "channel": "seed_data",
            },
        )


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    start_worker()
    yield
    stop_worker()


app = FastAPI(
    title="Geo-Optimized Furniture Order Management System",
    version="1.0.0",
    description=(
        "Capstone project backend built with FastAPI, SQLite, H3 geospatial indexing, "
        "role-based access, audit logs, and a Python queue-driven warehouse notification simulation."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def healthcheck() -> dict[str, Any]:
    return {
        "status": "ok",
        "database": str(DB_PATH),
        "h3_resolution": H3_RESOLUTION,
        "queued_events": EVENT_QUEUE.qsize(),
    }


@app.post("/api/auth/login")
def login(payload: LoginRequest) -> dict[str, Any]:
    with db_cursor() as connection:
        user = get_user_by_email(connection, payload.email)
        if not user or not verify_password(payload.password, user["password_hash"]):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password.",
            )
        token = create_session(connection, user["id"])
        write_audit_log(
            connection,
            actor_user_id=user["id"],
            action="login",
            entity_type="session",
            entity_id=None,
            detail={"email": user["email"]},
        )
        return {"token": token, "user": public_user(user)}


@app.post("/api/auth/logout")
def logout(user: CurrentUser, token: Annotated[str, Depends(get_current_token)]) -> dict[str, str]:
    with db_cursor() as connection:
        connection.execute("DELETE FROM sessions WHERE token = ?", (token,))
        write_audit_log(
            connection,
            actor_user_id=user["id"],
            action="logout",
            entity_type="session",
            entity_id=None,
            detail={"email": user["email"]},
        )
    return {"message": "Logged out successfully."}


@app.get("/api/me")
def me(user: CurrentUser) -> dict[str, Any]:
    return public_user(user)


@app.get("/api/dashboard")
def dashboard(user: CurrentUser) -> dict[str, Any]:
    with db_cursor() as connection:
        orders = list_orders(connection, user)
        notifications = [] if user["role"] == "customer" else list_notifications(connection)
        analytics = (
            list_region_analytics(connection)
            if user["role"] in {"admin", "warehouse_manager"}
            else []
        )
        users = list_users(connection) if user["role"] == "admin" else []
        audit_logs = list_audit_logs(connection) if user["role"] == "admin" else []
        return {
            "user": public_user(user),
            "stats": compute_stats(
                orders=orders,
                notifications=notifications,
                analytics=analytics,
                user_count=len(users) if users else 1,
            ),
            "orders": orders,
            "notifications": notifications,
            "analytics": analytics,
            "users": users,
            "audit_logs": audit_logs,
            "h3_resolution": H3_RESOLUTION,
            "demo_credentials": DEMO_CREDENTIALS,
        }


@app.get("/api/orders")
def orders(
    user: CurrentUser,
    status_filter: str | None = None,
    region_filter: str | None = None,
) -> list[dict[str, Any]]:
    with db_cursor() as connection:
        return list_orders(connection, user, status_filter, region_filter)


@app.get("/api/orders/{order_id}")
def order_detail(order_id: int, user: CurrentUser) -> dict[str, Any]:
    with db_cursor() as connection:
        row = get_order_row(connection, order_id)
        if not row:
            raise HTTPException(status_code=404, detail="Order not found.")
        ensure_customer_access(row, user)
        return serialize_order(connection, row)


@app.post("/api/orders", status_code=status.HTTP_201_CREATED)
def create_order(payload: OrderCreate, user: CurrentUser) -> dict[str, Any]:
    with db_cursor() as connection:
        customer_id = user["id"]
        if user["role"] == "admin" and payload.customer_id:
            customer = get_user_by_id(connection, payload.customer_id)
            if not customer or customer["role"] != "customer":
                raise HTTPException(status_code=400, detail="customer_id must reference a customer user.")
            customer_id = customer["id"]
        elif user["role"] != "customer" and not payload.customer_id:
            customer_id = user["id"]

        order = create_order_record(
            connection=connection,
            payload=payload,
            customer_id=customer_id,
            actor_user_id=user["id"],
        )

    EVENT_QUEUE.put({"type": "order_created", "order_id": order["id"], "actor_user_id": user["id"]})
    return order


@app.patch("/api/orders/{order_id}")
def update_order(order_id: int, payload: OrderUpdate, user: CurrentUser) -> dict[str, Any]:
    if all(value is None for value in payload.model_dump().values()):
        raise HTTPException(status_code=400, detail="No updates were provided.")

    with db_cursor() as connection:
        row = get_order_row(connection, order_id)
        if not row:
            raise HTTPException(status_code=404, detail="Order not found.")

        ensure_customer_access(row, user)

        updates: list[str] = []
        values: list[Any] = []
        detail: dict[str, Any] = {"before": {}, "after": {}}

        if payload.status is not None:
            if user["role"] not in {"admin", "warehouse_manager"}:
                raise HTTPException(status_code=403, detail="Only admin or warehouse manager can update order status.")
            detail["before"]["status"] = row["status"]
            detail["after"]["status"] = payload.status
            updates.append("status = ?")
            values.append(payload.status)

        if payload.priority is not None:
            if user["role"] == "warehouse_manager":
                raise HTTPException(status_code=403, detail="Warehouse manager cannot change order priority.")
            detail["before"]["priority"] = row["priority"]
            detail["after"]["priority"] = payload.priority
            updates.append("priority = ?")
            values.append(payload.priority)

        if payload.notes is not None:
            detail["before"]["notes"] = row["notes"]
            detail["after"]["notes"] = payload.notes
            updates.append("notes = ?")
            values.append(payload.notes.strip())

        if payload.address_line is not None:
            if user["role"] != "admin":
                raise HTTPException(status_code=403, detail="Only admin can change the delivery address.")
            detail["before"]["address_line"] = row["address_line"]
            detail["after"]["address_line"] = payload.address_line
            updates.append("address_line = ?")
            values.append(payload.address_line.strip())

        if payload.city is not None:
            if user["role"] != "admin":
                raise HTTPException(status_code=403, detail="Only admin can change the city.")
            detail["before"]["city"] = row["city"]
            detail["after"]["city"] = payload.city
            updates.append("city = ?")
            values.append(payload.city.strip())

        if not updates:
            raise HTTPException(status_code=400, detail="No permitted updates were provided.")

        updates.append("updated_at = ?")
        values.append(utc_now())
        values.append(order_id)

        connection.execute(
            f"UPDATE orders SET {', '.join(updates)} WHERE id = ?",
            values,
        )
        write_audit_log(
            connection,
            actor_user_id=user["id"],
            action="order_updated",
            entity_type="order",
            entity_id=order_id,
            detail=detail,
        )
        updated = get_order_row(connection, order_id)
        if updated is None:
            raise HTTPException(status_code=500, detail="Failed to refresh updated order.")
        return serialize_order(connection, updated)


@app.get("/api/notifications")
def notifications(user: Annotated[dict[str, Any], Depends(require_roles("admin", "warehouse_manager"))]) -> list[dict[str, Any]]:
    with db_cursor() as connection:
        return list_notifications(connection)


@app.get("/api/analytics/regions")
def region_analytics(user: Annotated[dict[str, Any], Depends(require_roles("admin", "warehouse_manager"))]) -> list[dict[str, Any]]:
    with db_cursor() as connection:
        return list_region_analytics(connection)


@app.get("/api/users")
def users(user: Annotated[dict[str, Any], Depends(require_roles("admin"))]) -> list[dict[str, Any]]:
    with db_cursor() as connection:
        return list_users(connection)


@app.post("/api/users", status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreate, user: Annotated[dict[str, Any], Depends(require_roles("admin"))]) -> dict[str, Any]:
    with db_cursor() as connection:
        existing = get_user_by_email(connection, payload.email)
        if existing:
            raise HTTPException(status_code=409, detail="A user with this email already exists.")
        cursor = connection.execute(
            """
            INSERT INTO users (full_name, email, password_hash, role, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                payload.full_name.strip(),
                payload.email.strip().lower(),
                hash_password(payload.password),
                payload.role,
                utc_now(),
            ),
        )
        created_id = cursor.lastrowid
        created = get_user_by_id(connection, created_id)
        write_audit_log(
            connection,
            actor_user_id=user["id"],
            action="user_created",
            entity_type="user",
            entity_id=created_id,
            detail={"email": payload.email.strip().lower(), "role": payload.role},
        )
        if not created:
            raise HTTPException(status_code=500, detail="Failed to create user.")
        return public_user(created)


@app.get("/api/audit-logs")
def audit_logs(user: Annotated[dict[str, Any], Depends(require_roles("admin"))]) -> list[dict[str, Any]]:
    with db_cursor() as connection:
        return list_audit_logs(connection)
