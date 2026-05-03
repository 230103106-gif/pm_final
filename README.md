# Geo-Optimized Furniture Order Management System

A FastAPI backend plus optional Streamlit workspace for furniture order intake, regional warehouse operations, and fulfillment analytics. The system combines persistent SQLite storage, H3 geospatial assignment, role-aware operations workflows, and a full audit trail.
his project provides a practical and secure furniture order management system that combines FastAPI, Streamlit, SQLite, and H3 geospatial logic. It supports customers, admins, and warehouse managers with role-based workflows, order tracking, analytics, and audit logging.

## What It Does

Exposes a Swagger/Postman-ready API for authentication, orders, products, warehouse events, analytics, and audit logs

Runs an optional customer storefront for placing furniture orders through a staged confirmation flow

Manages a realistic order lifecycle: 
`Created -> Confirmed -> Assigned -> Packed -> Out for Delivery -> Delivered`

Enforces both role-based access control and region-based attribute access control

Uses H3 geospatial indexing to map delivery coordinates into operational regions

Persists all users, products, orders, warehouse events, sessions, and audit logs in SQLite

Simulates an event-driven warehouse queue when orders are created

Provides exportable operational data: `orders.csv`, `products.json`, and `logs.json`

Includes initial operational data for immediate use

## Architecture

```text
Presentation Layer (Streamlit)
  app.py
  pages/1_Login.py
  pages/2_Shop.py
  pages/3_My_Orders.py
  pages/4_Admin_Dashboard.py
  pages/5_Order_Management.py
  pages/6_Products.py
  pages/7_Warehouse.py
  pages/8_Analytics.py
  pages/9_Audit.py
  pages/10_Settings.py

Service Layer
  services/user_service.py
  services/product_service.py
  services/order_service.py
  services/warehouse_service.py
  services/analytics_service.py
  services/audit_service.py

Core Layer
  core/database.py
  core/security.py
  core/auth.py
  core/rbac.py
  core/abac.py
  core/events.py
  core/config.py
  core/utils.py

Data Layer
  models/user.py
  models/product.py
  models/order.py
  models/audit_log.py
  models/warehouse_event.py
  SQLite: data/app.db

API Layer (FastAPI)
  api.py
  Swagger UI: /docs
  OpenAPI schema: /openapi.json
```

## Technology Stack
- Back-end: fast API, sqLite
- Front-end: StreamLit
- Geospatial Logic: H3 Indexing

## Key Features

### Customer ordering flow

- Product browsing with search and category filters
- Step-based order creation
- Delivery details capture with address, quantity, notes, and coordinates
- H3 region assignment before order creation
- Review and confirmation gate before submission
- Personal order tracking and early-stage cancellation

### Admin operations

- KPI dashboard with recent order and warehouse queue visibility
- Full order management across all regions
- Product catalog and inventory administration
- Audit log inspection
- Export center for operational datasets

### Warehouse operations

- Region-scoped event queue
- Warehouse intake processing for newly created orders
- Region-based order visibility and status progression
- Regional analytics constrained by assigned H3 region

### Security and governance

- BCrypt password hashing
- Persistent session records in SQLite
- RBAC for admin, customer, and warehouse manager roles
- ABAC for warehouse users based on `order.h3_region == user.assigned_region`
- Audit logging for logins, logouts, product changes, order creation, status transitions, and warehouse processing

## Seeded Demo Data

The app auto-seeds on first run with:

- 3 users
- 20 products
- 50 orders
- Multiple US cities with H3 region assignment
- Warehouse queue records and audit logs

## Seed Accounts

- `admin` / `Admin@123`
- `customer` / `Customer@123`
- `warehouse` / `Warehouse@123`

## Setup

### Local run

```bash
pip install -r requirements.txt
uvicorn api:app --reload
```

Open the API docs at `http://127.0.0.1:8000/docs`.

### Optional Streamlit workspace

```bash
pip install -r requirements.txt
streamlit run app.py
```

The first application start creates and seeds `data/app.db`.

### API demo flow

1. `POST /auth/login` with one of the seed accounts.
2. Authorize in Swagger with the returned bearer token.
3. Use `/orders`, `/products`, `/warehouse/events`, `/analytics/kpis`, and `/audit/logs` according to the account role.

### Run tests

```bash
pytest
```

## Deployment Notes

### GitHub

1. Push the repository to GitHub.
2. Ensure `requirements.txt` is present at the repo root.
3. Commit the Streamlit pages and core modules as-is.

### Streamlit Community Cloud

1. Create a new app from this repository.
2. Set the entrypoint to `app.py`.
3. Deploy with the default Python environment.
4. The SQLite database will be created automatically inside `data/app.db` at startup.

## Exports

- `orders.csv`: generated from the current order scope
- `products.json`: full product catalog snapshot
- `logs.json`: audit trail export

Files are written to `data/exports/` and also exposed through Streamlit download buttons.

## Project Structure

```text
final_project/
  api.py
  app.py
  requirements.txt
  README.md
  .gitignore
  .streamlit/config.toml
  core/
  models/
  services/
  pages/
  data/
  tests/
```

## Team Members
- Didar Nuray 230103268 – PM & System Architect
- Ayaulym Serik 230103106 – Backend Developer
- Srazha Ayaulym 230103181 - Data Engineer
- Amangeldi Fariza 230103153 - Frontend Developer
