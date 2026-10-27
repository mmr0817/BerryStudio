"""默认数据：初始场景与管理员的自动补齐。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from berrystudio.config import get_settings
from berrystudio.db.models import Scene, SceneKind, User, UserRole
from berrystudio.db.session import session_scope

DEFAULT_SCENES: tuple[dict, ...] = (
    {
        "code": "REH-A",
        "name": "排练室·A",
        "kind": SceneKind.REHEARSAL,
        "description": "大排练室，含全套音箱与鼓组",
        "capacity": 8,
        "hourly_price": 80,
        "open_hour": 9,
        "close_hour": 23,
        "min_minutes": 60,
        "max_minutes": 240,
        "slot_minutes": 30,
        "color": "#5EEAD4",
        "sort_order": 10,
    },
    {
        "code": "REH-B",
        "name": "排练室·B",
        "kind": SceneKind.REHEARSAL,
        "description": "小排练室，适合 3-4 人小编制",
        "capacity": 4,
        "hourly_price": 60,
        "open_hour": 9,
        "close_hour": 23,
        "min_minutes": 60,
        "max_minutes": 180,
        "slot_minutes": 30,
        "color": "#A78BFA",
        "sort_order": 20,
    },
    {
        "code": "REC-A",
        "name": "录音棚·A",
        "kind": SceneKind.RECORDING,
        "description": "分轨录音，含控制室与调音师",
        "capacity": 6,
        "hourly_price": 150,
        "open_hour": 10,
        "close_hour": 23,
        "min_minutes": 120,
        "max_minutes": 360,
        "slot_minutes": 60,
        "color": "#F472B6",
        "sort_order": 30,
    },
    {
        "code": "LIVE",
        "name": "小演出厅",
        "kind": SceneKind.PERFORMANCE,
        "description": "80 人容量，含灯光与返听",
        "capacity": 30,
        "hourly_price": 200,
        "open_hour": 10,
        "close_hour": 22,
        "min_minutes": 120,
        "max_minutes": 360,
        "slot_minutes": 60,
        "color": "#FACC15",
        "sort_order": 40,
    },
)


def seed_default_scenes(session: Session) -> int:
    """场景表为空时写入默认场景，返回新增数量。"""
    existing = session.scalar(select(Scene.id).limit(1))
    if existing is not None:
        return 0
    for item in DEFAULT_SCENES:
        session.add(Scene(**item))
    session.flush()
    return len(DEFAULT_SCENES)


def ensure_admin_users(session: Session) -> int:
    """把配置里的管理员 QQ 自动登记为管理员账号。"""
    created = 0
    for qq in get_settings().admin_qqs:
        user = session.scalar(select(User).where(User.qq == qq))
        if user is None:
            session.add(
                User(
                    qq=qq,
                    display_name=f"管理员{qq[-4:]}",
                    role=UserRole.ADMIN,
                )
            )
            created += 1
        elif user.role != UserRole.ADMIN:
            user.role = UserRole.ADMIN
    session.flush()
    return created


def ensure_default_data() -> None:
    with session_scope() as session:
        seed_default_scenes(session)
        ensure_admin_users(session)
