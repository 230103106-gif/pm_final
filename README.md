# Geo-Optimized Furniture Order Management System

This repository contains a capstone-ready full-stack demo built from the provided brief:

- `Backend`: FastAPI + SQLite
- `Frontend`: responsive single-page dashboard served by FastAPI
- `Geospatial indexing`: H3 (`latlng_to_cell`)
- `Event simulation`: Python `queue.Queue` + background worker
- `Security`: role-based access with seeded sessions and password hashing

## Scope

This is a solid capstone MVP size:

- 3 user roles: `Admin`, `Customer`, `Warehouse Manager`
- full order lifecycle with region assignment
- audit trail for login, user creation, order creation, status changes, and warehouse notifications
- region analytics grouped by H3 hex zone
- frontend dashboard for placing orders, reviewing queues, managing users, and inspecting logs
- Swagger UI at `/docs` for API demoing

## Demo Credentials

- `admin@saturnpro.local` / `Admin#1234`
- `customer@saturnpro.local` / `Customer#1234`
- `warehouse@saturnpro.local` / `Warehouse#1234`

## Run

1. Create or activate a virtual environment.
2. Install dependencies:

```bash
./.venv/bin/pip install -r requirements.txt
```

3. Start the app:

```bash
./.venv/bin/uvicorn app.main:app --reload
```

4. Open:

- `http://127.0.0.1:8000/` for the frontend
- `http://127.0.0.1:8000/docs` for Swagger UI

## Project Structure

```text
app/
  main.py        # FastAPI app, SQLite schema, auth, queue worker, APIs
static/
  index.html     # Frontend shell
  styles.css     # Dashboard styling
  app.js         # Frontend behavior
data/
  capstone.db    # Auto-generated SQLite database
```

## Key Features

- Customers can create furniture orders with multiple line items and delivery coordinates.
- Every order is assigned to an H3 region for warehouse grouping.
- Admin users can create accounts, inspect all orders, and review the audit log.
- Warehouse managers can monitor event-driven notifications and update order status.
- Seed data provides immediate demo content on first run.
