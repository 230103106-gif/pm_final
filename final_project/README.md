# Geo-Optimized Furniture Order Management System

A complete university capstone project that combines a **FastAPI backend**, **Streamlit frontend**, **SQLite database**, **SQLAlchemy ORM**, **H3 geospatial indexing**, **Plotly analytics**, and a **queue-driven notification worker**.

The system is designed for furniture stores that want to stop handling orders manually. It supports:

- Customers placing furniture orders online
- Admins managing every order and viewing full analytics
- Warehouse managers tracking orders only inside their assigned H3 region
- Audit logging for user actions and order lifecycle events
- Event-driven warehouse notification simulation

## Key Features

- Authentication with demo accounts and JWT-based login
- RBAC dashboards for Admin, Customer, and Warehouse Manager
- ABAC rule: warehouse managers can only access orders assigned to their allowed H3 region
- Furniture order creation, viewing, searching, filtering, updating, and cancellation
- Automatic H3 region generation from latitude and longitude
- Plotly analytics:
  - Orders by region
  - Orders by status
  - Revenue by region
  - Daily orders trend
  - Top furniture products
- Queue + threading notification simulation for new orders
- Audit log page for authentication and order actions
- Downloadable CSV reports
- Light/dark mode switch
- Professional landing page and polished Streamlit UI
- Swagger/OpenAPI docs when the FastAPI app is run directly

## Demo Credentials

- `admin / admin123`
- `customer / customer123`
- `warehouse / warehouse123`

## Project Structure

```text
final_project/
├── app/
│   ├── __init__.py
│   ├── auth.py
│   ├── database.py
│   ├── main.py
│   ├── models.py
│   ├── queue_worker.py
│   └── routes.py
├── frontend/
│   └── streamlit_app.py
├── tests/
│   └── test_api.py
├── .env.example
├── .gitignore
├── .streamlit/config.toml
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
```

## Architecture Overview

### Backend

- **FastAPI** exposes the REST API and Swagger docs
- **SQLAlchemy** manages the `users`, `orders`, and `audit_logs` tables
- **SQLite** stores application data
- **Pydantic** validates API input/output
- **H3** converts delivery coordinates into hexagonal regional cells
- **Queue + daemon worker thread** simulate event-driven warehouse notifications

### Frontend

- **Streamlit** provides the public web application
- **Plotly** powers dashboards and charts
- **PyDeck + Streamlit map components** visualize order locations and H3 regions

## API Endpoints

- `POST /login`
- `GET /me`
- `GET /orders`
- `POST /orders`
- `GET /orders/{id}`
- `PUT /orders/{id}`
- `POST /orders/{id}/cancel`
- `GET /analytics`
- `GET /audit-logs`
- `GET /docs` for Swagger UI when FastAPI runs directly

## Database Schema

### `users`

- `id`
- `username`
- `full_name`
- `role`
- `hashed_password`
- `allowed_h3_region`
- `created_at`

### `orders`

- `id`
- `customer_id`
- `customer_name`
- `product_type`
- `quantity`
- `price`
- `latitude`
- `longitude`
- `h3_region`
- `status`
- `notes`
- `created_at`
- `updated_at`

### `audit_logs`

- `id`
- `actor_user_id`
- `actor_username`
- `action`
- `target_type`
- `target_id`
- `description`
- `metadata_json`
- `created_at`

## How to Run Locally

### 1. Create and activate a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Run the FastAPI backend

```bash
uvicorn app.main:app --reload
```

The backend will be available at:

- API root: [http://localhost:8000](http://localhost:8000)
- Swagger docs: [http://localhost:8000/docs](http://localhost:8000/docs)

### 4. Run the Streamlit frontend

Open a new terminal and run:

```bash
export BACKEND_URL=http://localhost:8000
streamlit run frontend/streamlit_app.py
```

The frontend will be available at:

- [http://localhost:8501](http://localhost:8501)

## One-Command Local Run with Docker Compose

```bash
docker compose up --build
```

Services:

- Streamlit frontend: [http://localhost:8501](http://localhost:8501)
- FastAPI backend: [http://localhost:8000](http://localhost:8000)

## Streamlit Cloud Deployment

This project supports **two deployment modes**.

### Option A: Easiest deployment on Streamlit Cloud

Deploy only the Streamlit app using:

- App file: `frontend/streamlit_app.py`

In this mode, do **not** set `BACKEND_URL`. The Streamlit app automatically starts an **embedded FastAPI backend** inside the same deployment process, which makes demos and grading very simple.

Why this is useful:

- No second hosting service is required
- SQLite still works for lightweight demos
- The UI and backend logic remain in the same GitHub repo

### Option B: Split deployment for public production demos

1. Deploy the FastAPI backend on Render, Railway, Fly.io, or another Python host.
2. Set `BACKEND_URL` in Streamlit Cloud secrets or environment variables.
3. Deploy the Streamlit frontend separately on Streamlit Cloud.

Recommended environment variables:

- `BACKEND_URL=https://your-backend-url`
- `SECRET_KEY=your-secret`
- `DATABASE_URL=sqlite:///./geo_furniture.db`
- `H3_RESOLUTION=7`

## Running Tests

```bash
pytest
```

The tests cover:

- Demo account login
- Order creation
- Queue-driven warehouse notification creation
- Warehouse regional access control
- Input validation

## Seed Data

The application auto-seeds:

- 3 demo users
- Sample furniture orders across multiple regions
- Realistic order statuses for analytics and dashboard previews

## Teacher-Facing Highlights

- Clear separation between frontend and backend
- Geospatial optimization using H3 hex indexing
- Real role-based and attribute-based access control
- Event-driven simulation using queue/threading
- Professional dashboard design and analytics
- Deployment flexibility for Streamlit Cloud and split hosting
- Auditability and test coverage

## Suggested GitHub Repository Description

`Geo-optimized furniture order management system built with FastAPI, Streamlit, SQLite, SQLAlchemy, H3, Plotly, and queue-driven notifications.`
