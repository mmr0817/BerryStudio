"""权限判定（不依赖 NoneBot，便于 HTTP 后台 / CLI 复用）。"""

from __future__ import annotations

from berrystudio.config import get_settings
from berrystudio.db.models import User, UserRole
from berrystudio.services.errors import PermissionDenied


def is_super_admin(qq: str) -> bool:
    return str(qq) in get_settings().admin_qqs


def has_admin_rights(user: User | None) -> bool:
    if user is None:
        return False
    return user.role == UserRole.ADMIN or is_super_admin(user.qq)


def require_admin(user: User | None) -> User:
    if user is None:
        raise PermissionDenied("请先使用 /绑定 注册后再试")
    if not has_admin_rights(user):
        raise PermissionDenied("这个操作只有管理员可以使用")
    return user


def admin_title(user: User | None) -> str:
    if user is None:
        return ""
    if is_super_admin(user.qq):
        return "超级管理员"
    return "管理员" if user.role == UserRole.ADMIN else "用户"
