"""后台操作审计。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from berrystudio.db.models import AuditLog, User


def record(
    session: Session,
    actor: User | None,
    action: str,
    *,
    target_type: str = "",
    target_id: str = "",
    detail: dict[str, Any] | None = None,
) -> AuditLog:
    log = AuditLog(
        actor_id=actor.id if actor else None,
        actor_qq=actor.qq if actor else "",
        action=action,
        target_type=target_type,
        target_id=str(target_id),
        detail=detail or {},
    )
    session.add(log)
    session.flush()
    return log


def recent(session: Session, limit: int = 20) -> list[AuditLog]:
    return list(
        session.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit))
    )
