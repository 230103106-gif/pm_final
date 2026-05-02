from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
EXPORT_DIR = DATA_DIR / "exports"
SEED_DATA_PATH = DATA_DIR / "seed_data.json"

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
        return DATA_DIR / self.database_filename

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.database_path}"


settings = Settings()

ROLE_LABELS = {
    ROLE_ADMIN: "Administrator",
    ROLE_CUSTOMER: "Customer",
    ROLE_WAREHOUSE: "Warehouse Manager",
}

ROLE_NAVIGATION = {
    ROLE_ADMIN: [
        {"path": "app.py", "label": "Overview", "icon": "🏠"},
        {"path": "pages/4_Admin_Dashboard.py", "label": "Dashboard", "icon": "📈"},
        {"path": "pages/5_Order_Management.py", "label": "Orders", "icon": "📦"},
        {"path": "pages/6_Products.py", "label": "Catalog", "icon": "🪑"},
        {"path": "pages/7_Warehouse.py", "label": "Fulfillment", "icon": "🏭"},
        {"path": "pages/8_Analytics.py", "label": "Analytics", "icon": "🗺️"},
        {"path": "pages/9_Audit.py", "label": "Audit Trail", "icon": "📜"},
        {"path": "pages/10_Settings.py", "label": "Account", "icon": "⚙️"},
    ],
    ROLE_CUSTOMER: [
        {"path": "app.py", "label": "Overview", "icon": "🏠"},
        {"path": "pages/2_Shop.py", "label": "Catalog", "icon": "🛒"},
        {"path": "pages/3_My_Orders.py", "label": "Orders", "icon": "📋"},
        {"path": "pages/10_Settings.py", "label": "Account", "icon": "⚙️"},
    ],
    ROLE_WAREHOUSE: [
        {"path": "app.py", "label": "Overview", "icon": "🏠"},
        {"path": "pages/5_Order_Management.py", "label": "Orders", "icon": "📦"},
        {"path": "pages/7_Warehouse.py", "label": "Fulfillment", "icon": "🏭"},
        {"path": "pages/8_Analytics.py", "label": "Analytics", "icon": "🗺️"},
        {"path": "pages/10_Settings.py", "label": "Account", "icon": "⚙️"},
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

DEFAULT_PAGE_BY_ROLE = {
    ROLE_ADMIN: "pages/4_Admin_Dashboard.py",
    ROLE_CUSTOMER: "pages/2_Shop.py",
    ROLE_WAREHOUSE: "pages/7_Warehouse.py",
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
