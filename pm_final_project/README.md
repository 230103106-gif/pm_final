# Geo-Optimized Furniture Order Management System

A production-ready capstone project that combines a FastAPI backend, a polished Streamlit frontend, SQLite persistence, SQLAlchemy ORM, H3 geospatial indexing, audit logging, analytics, and queue-driven warehouse notifications.

## Why this project stands out

Furniture stores often manage orders manually, which creates delays, weak visibility, and poor regional coordination. This system solves that by:

- letting customers place orders online
- giving admins a full operational command center
- restricting warehouse managers to region-specific orders through RBAC + ABAC
- grouping orders by H3 hexagonal regions for smart geographic analysis
- generating analytics dashboards and downloadable reports
- simulating event-driven warehouse notifications with a background queue worker

## Core features

- FastAPI backend with documented endpoints and Swagger UI
- Streamlit frontend with a polished landing page and role-based dashboards
- SQLite database with `users`, `orders`, and `audit_logs`
- SQLAlchemy ORM models and seeded demo data
- H3 geospatial indexing from latitude and longitude
- RBAC for `admin`, `customer`, and `warehouse`
- ABAC rule: warehouse managers can only access orders in their allowed H3 region
- Order creation, status updates, cancellation, filtering, and detail views
- Plotly analytics for orders by region, status, revenue, trend, and products
- Queue and threading based background notifications
- Audit trail for logins, order events, admin actions, and warehouse notifications
- CSV downloads for orders, regional analytics, and audit logs
- Light and dark theme switch
- Automated test coverage for authentication, H3 creation, and access scoping

## Demo credentials

| Role | Username | Password |
| --- | --- | --- |
| Admin | `admin` | `admin123` |
| Customer | `customer` | `customer123` |
| Warehouse Manager | `warehouse` | `warehouse123` |

## Project structure

```text
.
├── app
│   ├── __init__.py
│   ├── auth.py
│   ├── database.py
│   ├── main.py
│   ├── models.py
│   ├── queue_worker.py
│   └── routes.py
├── frontend
│   └── streamlit_app.py
├── tests
│   └── test_api.py
├── .streamlit
│   └── config.toml
├── README.md
├── requirements.txt
└── runtime.txt
```

## Backend API

The FastAPI service exposes:

- `POST /login`
- `POST /logout`
- `GET /me`
- `GET /orders`
- `POST /orders`
- `GET /orders/{id}`
- `PATCH /orders/{id}`
- `DELETE /orders/{id}`
- `GET /analytics`
- `GET /audit-logs`
- `GET /notifications`
- `GET /docs`

Swagger UI is available at:

- `http://127.0.0.1:8000/docs`

## How to run locally

### 1. Create and activate a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Start the FastAPI backend

```bash
uvicorn app.main:app --reload
```

### 4. Start the Streamlit frontend

Open a second terminal and run:

```bash
streamlit run frontend/streamlit_app.py
```

### 5. Open the app

- Frontend: `http://localhost:8501`
- Backend docs: `http://127.0.0.1:8000/docs`

## One-command demo option

If you only start Streamlit, the frontend can still work in two ways:

- it tries to auto-start the FastAPI server locally for you
- if that is unavailable, it falls back to an embedded FastAPI `TestClient` so the UI still works for demos

This makes the project especially convenient for quick grading sessions.

## Deployment guide

### Option 1: Streamlit Cloud + separate FastAPI backend

This is the best choice if you want a public frontend and public Swagger docs.

1. Push the repository to GitHub.
2. Deploy the FastAPI backend on Render, Railway, Fly.io, or another Python host.
3. Use this backend start command:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

4. Deploy `frontend/streamlit_app.py` on Streamlit Cloud.
5. In Streamlit Cloud settings, add an environment variable:

```text
API_BASE_URL=https://your-backend-url
```

6. Redeploy the frontend.

Important deployment note:

- If your Streamlit entrypoint is `frontend/streamlit_app.py`, keep a dependency file either in the repository root or inside the `frontend/` folder.
- This project includes `frontend/requirements.txt` specifically to support nested Streamlit Cloud deployments.

### Option 2: Local or single-container hosting

For local presentations, classroom demos, or a VM deployment:

- run FastAPI and Streamlit side by side
- or rely on the frontend's built-in local API bootstrap behavior

## Analytics included

- orders by H3 region
- orders by workflow status
- revenue by H3 region
- daily orders trend
- top furniture products
- regional rollups with CSV export

## Security and access control

- `admin` can access everything
- `customer` can only access their own orders
- `warehouse` can only access orders assigned to their `allowed_region`
- audit logs are limited to admin users

The warehouse restriction is an ABAC rule because access depends on a user attribute (`allowed_region`) and an order attribute (`h3_region`).

## Testing

Run the automated checks with:

```bash
pytest
```

The included tests verify:

- demo account login
- customer order scoping
- warehouse ABAC region scoping
- order creation with automatic H3 assignment

## Technology stack

- Python
- FastAPI
- Streamlit
- SQLite
- SQLAlchemy
- Pydantic
- Pandas
- Plotly
- H3
- Queue and threading

## Notes for submission

- The database auto-seeds demo users and sample orders on first startup.
- The queue worker runs in the background and records warehouse notification events.
- The UI is designed to feel presentation-ready for a university capstone demo.
