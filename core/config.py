from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
SEED_DATA_PATH = DATA_DIR / "seed_data.json"


def writable_data_dir() -> Path:
    explicit_dir = os.getenv("GEO_FURNITURE_DATA_DIR")
    if explicit_dir:
        return Path(explicit_dir).expanduser()
    if str(BASE_DIR).startswith("/mount/src/"):
        return Path(os.getenv("TMPDIR", "/tmp")) / "geo_furniture_ops"
    return DATA_DIR


EXPORT_DIR = writable_data_dir() / "exports"

ROLE_ADMIN = "admin"
ROLE_CUSTOMER = "customer"
ROLE_WAREHOUSE = "warehouse_manager"

ORDER_STATUS_CREATED = "Created"
ORDER_STATUS_CONFIRMED = "Confirmed"
ORDER_STATUS_ASSIGNED = "Assigned"
ORDER_STATUS_PACKED = "Packed"
ORDER_STATUS_OUT_FOR_DELIVERY = "Out for Delivery"
ORDER_STATUS_DELIVERED = "Delivered"
ORDER_STATUS_CANCELLED = "Cancelled"


@dataclass
class Settings:
    app_name: str = "Geo-Optimized Furniture OMS"
    database_filename: str = "app.db"
    session_duration_hours: int = 12
    browser_cookie_name: str = "geo_furniture_ops_session"
    cookie_secret: str = os.getenv("GEO_FURNITURE_COOKIE_SECRET", "geo-furniture-ops-dev-secret")
    h3_resolution: int = 7
    demo_seed: bool = True
    order_statuses: list[str] = field(
        default_factory=lambda: [
            ORDER_STATUS_CREATED,
            ORDER_STATUS_CONFIRMED,
            ORDER_STATUS_ASSIGNED,
            ORDER_STATUS_PACKED,
            ORDER_STATUS_OUT_FOR_DELIVERY,
            ORDER_STATUS_DELIVERED,
            ORDER_STATUS_CANCELLED,
        ]
    )
    early_cancellable_statuses: set[str] = field(
        default_factory=lambda: {
            ORDER_STATUS_CREATED,
            ORDER_STATUS_CONFIRMED,
        }
    )
    allowed_transitions: dict[str, set[str]] = field(
        default_factory=lambda: {
            ORDER_STATUS_CREATED: {ORDER_STATUS_CONFIRMED, ORDER_STATUS_CANCELLED},
            ORDER_STATUS_CONFIRMED: {ORDER_STATUS_ASSIGNED, ORDER_STATUS_CANCELLED},
            ORDER_STATUS_ASSIGNED: {ORDER_STATUS_PACKED},
            ORDER_STATUS_PACKED: {ORDER_STATUS_OUT_FOR_DELIVERY},
            ORDER_STATUS_OUT_FOR_DELIVERY: {ORDER_STATUS_DELIVERED},
            ORDER_STATUS_DELIVERED: set(),
            ORDER_STATUS_CANCELLED: set(),
        }
    )

    @property
    def database_path(self) -> Path:
        explicit_path = os.getenv("GEO_FURNITURE_DATABASE_PATH")
        if explicit_path:
            return Path(explicit_path).expanduser()
        return writable_data_dir() / self.database_filename

    @property
    def database_url(self) -> str:
        return os.getenv("GEO_FURNITURE_DATABASE_URL", f"sqlite:///{self.database_path}")


settings = Settings()

ROLE_LABELS = {
    ROLE_ADMIN: "Administrator",
    ROLE_CUSTOMER: "Customer",
    ROLE_WAREHOUSE: "Warehouse Manager",
}

ROLE_NAVIGATION = {
    ROLE_ADMIN: [
        {"view": "overview", "label": "Overview", "icon": "home"},
        {"view": "dashboard", "label": "Dashboard", "icon": "layout"},
        {"view": "orders", "label": "Orders", "icon": "package"},
        {"view": "catalog", "label": "Catalog", "icon": "grid"},
        {"view": "fulfillment", "label": "Fulfillment", "icon": "warehouse"},
        {"view": "analytics", "label": "Analytics", "icon": "chart"},
        {"view": "audit", "label": "Audit Trail", "icon": "shield"},
        {"view": "profile", "label": "Profile", "icon": "user"},
    ],
    ROLE_CUSTOMER: [
        {"view": "overview", "label": "Overview", "icon": "home"},
        {"view": "shop", "label": "Marketplace", "icon": "bag"},
        {"view": "orders", "label": "Orders", "icon": "package"},
        {"view": "profile", "label": "Profile", "icon": "user"},
    ],
    ROLE_WAREHOUSE: [
        {"view": "overview", "label": "Overview", "icon": "home"},
        {"view": "orders", "label": "Orders", "icon": "package"},
        {"view": "fulfillment", "label": "Fulfillment", "icon": "warehouse"},
        {"view": "analytics", "label": "Analytics", "icon": "chart"},
        {"view": "profile", "label": "Profile", "icon": "user"},
    ],
}

ROLE_PERMISSIONS = {
    ROLE_ADMIN: {
        "dashboard.view",
        "orders.view_all",
        "orders.update_all",
        "orders.cancel_all",
        "products.manage",
        "analytics.view_all",
        "warehouse.process_all",
        "audit.view",
        "exports.manage",
        "settings.manage_all",
    },
    ROLE_CUSTOMER: {
        "catalog.view",
        "orders.create",
        "orders.view_own",
        "orders.cancel_own",
        "settings.manage_self",
    },
    ROLE_WAREHOUSE: {
        "dashboard.view_region",
        "orders.view_region",
        "orders.update_region",
        "warehouse.process_region",
        "analytics.view_region",
        "settings.manage_self",
    },
}

DEFAULT_VIEW_BY_ROLE = {
    ROLE_ADMIN: "overview",
    ROLE_CUSTOMER: "overview",
    ROLE_WAREHOUSE: "overview",
}

DEFAULT_PAGE_BY_ROLE = {
    ROLE_ADMIN: "app.py",
    ROLE_CUSTOMER: "app.py",
    ROLE_WAREHOUSE: "app.py",
}

LEGACY_PAGE_VIEWS = {
    "1_Login.py": "auth",
    "2_Shop.py": "shop",
    "3_My_Orders.py": "orders",
    "4_Admin_Dashboard.py": "dashboard",
    "5_Order_Management.py": "orders",
    "6_Products.py": "catalog",
    "7_Warehouse.py": "fulfillment",
    "8_Analytics.py": "analytics",
    "9_Audit.py": "audit",
    "10_Settings.py": "profile",
}

STATUS_COLORS = {
    ORDER_STATUS_CREATED: "#6c7a89",
    ORDER_STATUS_CONFIRMED: "#0d6efd",
    ORDER_STATUS_ASSIGNED: "#155eef",
    ORDER_STATUS_PACKED: "#f79009",
    ORDER_STATUS_OUT_FOR_DELIVERY: "#875bf7",
    ORDER_STATUS_DELIVERED: "#039855",
    ORDER_STATUS_CANCELLED: "#d92d20",
}
