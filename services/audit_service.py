from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from core.config import EXPORT_DIR
from core.utils import json_dumps
from models.audit_log import AuditLog


def log_action(
    session: Session,
    actor,
    action: str,
    entity_type: str,
    entity_id: str,
    details: dict[str, Any] | None = None,
    *,
    commit: bool = True,
) -> AuditLog:
    log = AuditLog(
        actor_user_id=getattr(actor, "id", None),
        actor_username=getattr(actor, "username", "system"),
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details_json=json_dumps(details),
    )
    session.add(log)
    if commit:
        session.commit()
        session.refresh(log)
    return log


def list_logs(
    session: Session,
    *,
    actor_username: str | None = None,
    action: str | None = None,
    entity_type: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    query = select(AuditLog).order_by(AuditLog.created_at.desc())
    if actor_username:
        query = query.where(AuditLog.actor_username == actor_username)
    if action and action != "All":
        query = query.where(AuditLog.action == action)
    if entity_type and entity_type != "All":
        query = query.where(AuditLog.entity_type == entity_type)

    logs = session.exec(query.limit(limit)).all()
    return [
        {
            "id": log.id,
            "created_at": log.created_at,
            "actor": log.actor_username,
            "action": log.action,
            "entity_type": log.entity_type,
            "entity_id": log.entity_id,
            "details": json.loads(log.details_json or "{}"),
        }
        for log in logs
    ]


def export_logs_json(session: Session) -> tuple[Path, bytes]:
    logs = list_logs(session, limit=5000)
    payload = json.dumps(logs, default=str, indent=2).encode("utf-8")
    export_path = EXPORT_DIR / "logs.json"
    export_path.write_bytes(payload)
    return export_path, payload
