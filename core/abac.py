from __future__ import annotations

from core.config import ROLE_ADMIN, ROLE_CUSTOMER, ROLE_WAREHOUSE
from models.order import Order
from models.user import User


def can_access_order(user: User, order: Order) -> bool:
    if user.role == ROLE_ADMIN:
        return True
    if user.role == ROLE_CUSTOMER:
        return order.customer_id == user.id
    if user.role == ROLE_WAREHOUSE:
        return bool(user.assigned_region) and order.h3_region == user.assigned_region
    return False


def apply_order_scope(query, user: User):
    if user.role == ROLE_ADMIN:
        return query
    if user.role == ROLE_CUSTOMER:
        return query.where(Order.customer_id == user.id)
    if user.role == ROLE_WAREHOUSE:
        return query.where(Order.h3_region == user.assigned_region)
    return query.where(Order.id == -1)
