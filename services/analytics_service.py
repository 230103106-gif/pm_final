from __future__ import annotations

import pandas as pd
from sqlmodel import Session

from core.config import ORDER_STATUS_DELIVERED
from services import order_service, warehouse_service


def order_dataframe(session: Session, actor) -> pd.DataFrame:
    rows = order_service.list_orders(session, actor, include_cancelled=True)
    if not rows:
        return pd.DataFrame(
            columns=[
                "order_number",
                "product_name",
                "quantity",
                "total_amount",
                "status",
                "city",
                "h3_region",
                "created_at",
            ]
        )
    frame = pd.DataFrame(rows)
    frame["created_at"] = pd.to_datetime(frame["created_at"])
    frame["created_date"] = frame["created_at"].dt.date
    return frame


def kpis(session: Session, actor) -> dict[str, float]:
    frame = order_dataframe(session, actor)
    events = warehouse_service.list_events(session, actor, event_status="All", limit=1000)
    delivered = frame[frame["status"] == ORDER_STATUS_DELIVERED]
    pending = frame[~frame["status"].isin([ORDER_STATUS_DELIVERED, "Cancelled"])]
    return {
        "orders": float(len(frame.index)),
        "revenue": float(frame["total_amount"].sum()) if not frame.empty else 0.0,
        "average_order_value": float(frame["total_amount"].mean()) if not frame.empty else 0.0,
        "delivered_rate": float((len(delivered.index) / len(frame.index)) * 100) if len(frame.index) else 0.0,
        "active_pipeline": float(len(pending.index)),
        "pending_events": float(len([event for event in events if event["status"] == "pending"])),
    }


def orders_per_region(session: Session, actor) -> pd.DataFrame:
    frame = order_dataframe(session, actor)
    if frame.empty:
        return pd.DataFrame(columns=["region_label", "orders"])
    return (
        frame.groupby("region_label", as_index=False)
        .agg(orders=("order_number", "count"))
        .sort_values("orders", ascending=False)
    )


def revenue_per_region(session: Session, actor) -> pd.DataFrame:
    frame = order_dataframe(session, actor)
    if frame.empty:
        return pd.DataFrame(columns=["region_label", "revenue"])
    return (
        frame.groupby("region_label", as_index=False)
        .agg(revenue=("total_amount", "sum"))
        .sort_values("revenue", ascending=False)
    )


def status_distribution(session: Session, actor) -> pd.DataFrame:
    frame = order_dataframe(session, actor)
    if frame.empty:
        return pd.DataFrame(columns=["status", "orders"])
    return frame.groupby("status", as_index=False).agg(orders=("order_number", "count"))


def orders_over_time(session: Session, actor) -> pd.DataFrame:
    frame = order_dataframe(session, actor)
    if frame.empty:
        return pd.DataFrame(columns=["created_date", "orders", "revenue"])
    return (
        frame.groupby("created_date", as_index=False)
        .agg(orders=("order_number", "count"), revenue=("total_amount", "sum"))
        .sort_values("created_date")
    )


def top_regions(session: Session, actor) -> pd.DataFrame:
    frame = order_dataframe(session, actor)
    if frame.empty:
        return pd.DataFrame(columns=["region_label", "orders", "revenue"])
    return (
        frame.groupby("region_label", as_index=False)
        .agg(orders=("order_number", "count"), revenue=("total_amount", "sum"))
        .sort_values(["orders", "revenue"], ascending=[False, False])
        .head(5)
    )
