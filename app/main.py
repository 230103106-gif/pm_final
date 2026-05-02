from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import init_db
from app.queue_worker import start_queue_worker
from app.routes import router


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    start_queue_worker()
    yield


app = FastAPI(
    title="Geo-Optimized Furniture Order Management System",
    version="1.0.0",
    description=(
        "A capstone-ready furniture order management platform with role-based access control, "
        "H3 geospatial clustering, analytics, and event-driven warehouse notifications."
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

app.include_router(router)


@app.get("/", tags=["System"])
def root():
    return {
        "project": "Geo-Optimized Furniture Order Management System",
        "status": "ok",
        "docs": "/docs",
    }


@app.get("/health", tags=["System"])
def health_check():
    return {"status": "healthy"}
