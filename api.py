from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Iterator

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlmodel import Session

from core.config import ROLE_ADMIN, ROLE_WAREHOUSE, settings
from core.database import get_session, init_db
from core.utils import AppError, AuthenticationError, AuthorizationError, NotFoundError, ValidationError
from models.user import User
from services import analytics_service, audit_service, order_service, product_service, user_service, warehouse_service


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(
    title=settings.app_name,
    description=(
        "Backend API for furniture order intake, H3 regional assignment, "
        "warehouse event simulation, RBAC/ABAC enforcement, analytics, and audit logging."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

bearer_scheme = HTTPBearer(auto_error=False)


class UserOut(BaseModel):
    id: int
    username: str
    full_name: str
    role: str
    assigned_region: str | None
    is_active: bool


class LoginRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class ProductOut(BaseModel):
    id: int
    sku: str
    name: str
    category: str
    material: str
    description: str
    price: float
    stock_quantity: int
    dimensions: str
    is_active: bool


class ProductCreate(BaseModel):
    sku: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=120)
    category: str = Field(min_length=1, max_length=80)
    material: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=500)
    price: float = Field(gt=0)
    stock_quantity: int = Field(ge=0)
    dimensions: str = Field(min_length=1, max_length=80)


class ProductUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    category: str = Field(min_length=1, max_length=80)
    material: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=500)
    price: float = Field(gt=0)
    stock_quantity: int = Field(ge=0)
    dimensions: str = Field(min_length=1, max_length=80)
    is_active: bool


class OrderCreate(BaseModel):
    product_id: int
    quantity: int = Field(gt=0)
    recipient_name: str = Field(min_length=1, max_length=120)
    phone: str = Field(min_length=1, max_length=40)
    address_line1: str = Field(min_length=1, max_length=180)
    address_line2: str = Field(default="", max_length=180)
    city: str = Field(min_length=1, max_length=80)
    state: str = Field(min_length=1, max_length=80)
    postal_code: str = Field(min_length=1, max_length=20)
    country: str = Field(default="USA", min_length=1, max_length=80)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    notes: str = Field(default="", max_length=400)


class OrderRow(BaseModel):
    id: int
    order_number: str
    product_name: str
    customer_name: str
    quantity: int
    unit_price: float
    total_amount: float
    status: str
    city: str
    state: str
    h3_region: str
    region_label: str
    recipient_name: str
    phone: str
    created_at: datetime
    updated_at: datetime
    notes: str
    address: str


class OrderDetail(BaseModel):
    id: int
    order_number: str
    status: str
    product_name: str
    customer_name: str
    quantity: int
    unit_price: float
    total_amount: float
    h3_region: str
    region_label: str
    recipient_name: str
    phone: str
    address_line1: str
    address_line2: str
    city: str
    state: str
    postal_code: str
    country: str
    notes: str
    created_at: datetime
    updated_at: datetime
    confirmed_at: datetime | None
    assigned_at: datetime | None
    packed_at: datetime | None
    out_for_delivery_at: datetime | None
    delivered_at: datetime | None
    cancelled_at: datetime | None
    cancellation_reason: str | None


class StatusUpdate(BaseModel):
    new_status: str = Field(min_length=1)
    reason: str | None = None


class WarehouseEventOut(BaseModel):
    id: int
    event_type: str
    status: str
    region: str
    region_label: str
    order_id: int
    order_number: str
    order_status: str
    city: str
    total_amount: float
    created_at: datetime
    processed_at: datetime | None


class KpiOut(BaseModel):
    orders: float
    revenue: float
    average_order_value: float
    delivered_rate: float
    active_pipeline: float
    pending_events: float


class AuditLogOut(BaseModel):
    id: int
    created_at: datetime
    actor: str
    action: str
    entity_type: str
    entity_id: str
    details: dict[str, Any]


def get_db() -> Iterator[Session]:
    with get_session() as session:
        yield session


def app_error_status(exc: AppError) -> int:
    if isinstance(exc, AuthenticationError):
        return status.HTTP_401_UNAUTHORIZED
    if isinstance(exc, AuthorizationError):
        return status.HTTP_403_FORBIDDEN
    if isinstance(exc, NotFoundError):
        return status.HTTP_404_NOT_FOUND
    if isinstance(exc, ValidationError):
        return status.HTTP_400_BAD_REQUEST
    return status.HTTP_500_INTERNAL_SERVER_ERROR


@app.exception_handler(AppError)
async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(status_code=app_error_status(exc), content={"detail": str(exc)})


def serialize_user(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "username": user.username,
        "full_name": user.full_name,
        "role": user.role,
        "assigned_region": user.assigned_region,
        "is_active": user.is_active,
    }


def serialize_product(product) -> dict[str, Any]:
    return {
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


def frame_records(frame) -> list[dict[str, Any]]:
    return jsonable_encoder(frame.to_dict(orient="records"))


def require_token(credentials: HTTPAuthorizationCredentials | None) -> str:
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: Session = Depends(get_db),
) -> User:
    token = require_token(credentials)
    user = user_service.user_from_session_token(session, token)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session token is invalid or expired.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_roles(actor: User, allowed_roles: set[str]) -> None:
    if actor.role not in allowed_roles:
        raise AuthorizationError("Your role cannot perform this action.")


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest, session: Session = Depends(get_db)) -> dict[str, Any]:
    user = user_service.authenticate_user(session, payload.username, payload.password)
    token = user_service.start_user_session(session, user)
    audit_service.log_action(
        session,
        actor=user,
        action="auth.login",
        entity_type="user",
        entity_id=str(user.id),
        details={"username": user.username},
    )
    return {"access_token": token, "token_type": "bearer", "user": serialize_user(user)}


@app.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    actor: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Response:
    token = require_token(credentials)
    user_service.end_user_session(session, token)
    audit_service.log_action(
        session,
        actor=actor,
        action="auth.logout",
        entity_type="user",
        entity_id=str(actor.id),
        details={"username": actor.username},
    )
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@app.get("/users/me", response_model=UserOut)
def me(actor: User = Depends(get_current_user)) -> dict[str, Any]:
    return serialize_user(actor)


@app.get("/products", response_model=list[ProductOut])
def list_products(
    include_inactive: bool = False,
    category: str | None = None,
    search: str | None = None,
    actor: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    if include_inactive and actor.role != ROLE_ADMIN:
        raise AuthorizationError("Only administrators can view inactive products.")
    products = product_service.list_products(
        session,
        include_inactive=include_inactive,
        category=category,
        search=search,
    )
    return [serialize_product(product) for product in products]


@app.post("/products", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
def create_product(
    payload: ProductCreate,
    actor: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    require_roles(actor, {ROLE_ADMIN})
    product = product_service.create_product(session, actor, payload.model_dump())
    return serialize_product(product)


@app.patch("/products/{product_id}", response_model=ProductOut)
def update_product(
    product_id: int,
    payload: ProductUpdate,
    actor: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    require_roles(actor, {ROLE_ADMIN})
    product = product_service.update_product(session, actor, product_id, payload.model_dump())
    return serialize_product(product)


@app.get("/orders", response_model=list[OrderRow])
def list_orders(
    status_filter: str | None = Query(default=None, alias="status"),
    city: str | None = None,
    search: str | None = None,
    include_cancelled: bool = True,
    actor: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    return order_service.list_orders(
        session,
        actor,
        status=status_filter,
        city=city,
        search=search,
        include_cancelled=include_cancelled,
    )


@app.post("/orders", response_model=OrderDetail, status_code=status.HTTP_201_CREATED)
def create_order(
    payload: OrderCreate,
    actor: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    order = order_service.create_order(session, actor, **payload.model_dump())
    return order_service.order_detail(session, actor, order.id)


@app.get("/orders/{order_id}", response_model=OrderDetail)
def get_order(
    order_id: int,
    actor: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    return order_service.order_detail(session, actor, order_id)


@app.patch("/orders/{order_id}/status", response_model=OrderDetail)
def update_order_status(
    order_id: int,
    payload: StatusUpdate,
    actor: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    order = order_service.update_order_status(session, actor, order_id, payload.new_status, reason=payload.reason)
    return order_service.order_detail(session, actor, order.id)


@app.get("/analytics/kpis", response_model=KpiOut)
def analytics_kpis(
    actor: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> dict[str, float]:
    require_roles(actor, {ROLE_ADMIN, ROLE_WAREHOUSE})
    return analytics_service.kpis(session, actor)


@app.get("/analytics/orders-per-region")
def analytics_orders_per_region(
    actor: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    require_roles(actor, {ROLE_ADMIN, ROLE_WAREHOUSE})
    return frame_records(analytics_service.orders_per_region(session, actor))


@app.get("/analytics/revenue-per-region")
def analytics_revenue_per_region(
    actor: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    require_roles(actor, {ROLE_ADMIN, ROLE_WAREHOUSE})
    return frame_records(analytics_service.revenue_per_region(session, actor))


@app.get("/warehouse/events", response_model=list[WarehouseEventOut])
def list_warehouse_events(
    event_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=300, ge=1, le=1000),
    actor: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    require_roles(actor, {ROLE_ADMIN, ROLE_WAREHOUSE})
    return warehouse_service.list_events(session, actor, event_status=event_status, limit=limit)


@app.post("/warehouse/events/{event_id}/process", response_model=WarehouseEventOut)
def process_warehouse_event(
    event_id: int,
    actor: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    require_roles(actor, {ROLE_ADMIN, ROLE_WAREHOUSE})
    processed = warehouse_service.process_event(session, actor, event_id)
    matching = [event for event in warehouse_service.list_events(session, actor, event_status="All", limit=1000) if event["id"] == processed.id]
    if not matching:
        raise NotFoundError("Warehouse event was not found after processing.")
    return matching[0]


@app.get("/audit/logs", response_model=list[AuditLogOut])
def list_audit_logs(
    action: str | None = None,
    entity_type: str | None = None,
    actor_username: str | None = None,
    limit: int = Query(default=500, ge=1, le=5000),
    actor: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    require_roles(actor, {ROLE_ADMIN})
    return audit_service.list_logs(
        session,
        actor_username=actor_username,
        action=action,
        entity_type=entity_type,
        limit=limit,
    )
