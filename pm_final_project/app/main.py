from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import init_db, seed_demo_data
from app.queue_worker import start_worker
from app.routes import router


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    seed_demo_data()
    start_worker()
    yield


app = FastAPI(
    title="Geo-Optimized Furniture Order Management System API",
    description=(
        "FastAPI backend for furniture order processing, H3 regional grouping, "
        "role-aware dashboards, audit trails, and event-driven notifications."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/")
def root() -> dict[str, str]:
    return {
        "message": "Geo-Optimized Furniture Order Management System API",
        "docs": "/docs",
        "health": "/health",
    }
