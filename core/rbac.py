from __future__ import annotations

from core.config import ROLE_PERMISSIONS


def has_permission(role: str, permission: str) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, set())


def any_permission(role: str, permissions: list[str]) -> bool:
    return any(has_permission(role, permission) for permission in permissions)
