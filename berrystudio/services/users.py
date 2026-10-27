"""用户账号服务。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from berrystudio.config import get_settings
from berrystudio.db.models import User, UserRole, UserStatus, utcnow
from berrystudio.services.dto import UserView, user_view
from berrystudio.services.errors import BerryError, NotFoundError


def normalize_qq(qq: str | int) -> str:
    text = str(qq).strip()
    if not text.isdigit():
        raise BerryError("QQ 号格式不正确")
    return text


def get_user(session: Session, qq: str | int) -> User | None:
    return session.scalar(select(User).where(User.qq == normalize_qq(qq)))


def get_or_create_user(
    session: Session,
    qq: str | int,
    *,
    nickname: str = "",
    display_name: str = "",
) -> User:
    user = get_user(session, qq)
    if user is not None:
        if nickname and nickname != user.nickname:
            user.nickname = nickname
        user.last_seen_at = utcnow()
        return user
    user = User(
        qq=normalize_qq(qq),
        nickname=nickname,
        display_name=display_name,
        role=UserRole.USER,
        status=UserStatus.ACTIVE,
    )
    session.add(user)
    session.flush()
    return user


def bind_user(
    session: Session,
    qq: str | int,
    display_name: str,
    *,
    nickname: str = "",
) -> User:
    """绑定 / 更新昵称。已绑定用户再次执行时视为修改昵称。"""
    name = (display_name or "").strip()
    if len(name) > 24:
        raise BerryError("昵称太长了，请控制在 24 个字符以内")
    user = get_or_create_user(session, qq, nickname=nickname, display_name=name)
    if name:
        user.display_name = name
    user.last_seen_at = utcnow()
    session.flush()
    return user


def touch_user(session: Session, user: User, nickname: str = "") -> None:
    user.last_seen_at = utcnow()
    if nickname and nickname != user.nickname:
        user.nickname = nickname
    session.flush()


def require_user(session: Session, qq: str | int, nickname: str = "") -> User:
    user = get_user(session, qq)
    if user is None:
        raise BerryError("你还没有绑定账号，请先发送：/绑定 你的昵称", code="not_bound")
    touch_user(session, user, nickname)
    return user


def ensure_active(user: User) -> None:
    if user.status == UserStatus.BANNED:
        raise BerryError("你的账号已被管理员封禁，请联系工作室", code="banned")


def set_role(session: Session, user: User, role: str, *, actor: User | None = None) -> User:
    if role not in {UserRole.USER, UserRole.ADMIN}:
        raise BerryError("角色只能是 user 或 admin")
    if actor is not None and actor.id == user.id and role != UserRole.ADMIN:
        raise BerryError("不能取消自己的管理员权限")
    user.role = role
    session.flush()
    return user


def set_status(
    session: Session,
    user: User,
    status: str,
    *,
    actor: User | None = None,
) -> User:
    if status not in {UserStatus.ACTIVE, UserStatus.BANNED}:
        raise BerryError("状态只能是 active 或 banned")
    if actor is not None and actor.id == user.id and status == UserStatus.BANNED:
        raise BerryError("不能封禁自己")
    user.status = status
    session.flush()
    return user


def list_users(
    session: Session,
    *,
    keyword: str = "",
    role: str | None = None,
    limit: int = 50,
) -> list[User]:
    stmt = select(User).order_by(User.created_at.desc()).limit(limit)
    if keyword:
        like = f"%{keyword.strip()}%"
        stmt = stmt.where(
            or_(User.qq.like(like), User.display_name.like(like), User.nickname.like(like))
        )
    if role:
        stmt = stmt.where(User.role == role)
    return list(session.scalars(stmt))


def list_admins(session: Session) -> list[User]:
    return list(
        session.scalars(
            select(User).where(User.role == UserRole.ADMIN).order_by(User.created_at)
        )
    )


def admin_user_qqs(session: Session) -> list[str]:
    """数据库管理员 + 配置中的超级管理员（去重）。"""
    qqs = {
        user.qq
        for user in list_admins(session)
        if user.status != UserStatus.BANNED
    }
    qqs.update(get_settings().admin_qqs)
    return sorted(qqs)


def add_admin(
    session: Session,
    qq: str | int,
    *,
    display_name: str = "",
) -> User:
    user = get_or_create_user(session, qq, display_name=display_name)
    user.role = UserRole.ADMIN
    if display_name:
        user.display_name = display_name
    session.flush()
    return user


def remove_admin(session: Session, qq: str | int) -> User:
    user = get_user(session, qq)
    if user is None:
        raise NotFoundError(f"未找到 QQ {qq} 对应的用户")
    user.role = UserRole.USER
    session.flush()
    return user


def find_user_by_token(session: Session, token: str) -> User:
    """支持 ``@QQ`` / ``QQ`` / 昵称 三种检索方式。"""
    token = (token or "").strip().lstrip("@")
    if token.isdigit():
        user = get_user(session, token)
        if user is None:
            raise NotFoundError(f"未找到 QQ {token} 对应的用户")
        return user
    user = session.scalar(select(User).where(User.display_name == token))
    if user is None:
        user = session.scalar(select(User).where(User.nickname == token))
    if user is None:
        raise NotFoundError(f"未找到昵称为「{token}」的用户")
    return user


def user_since_text(user: User, tz) -> str:
    created = user.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    local = created.astimezone(tz)
    return f"{local.year}-{local.month:02d}-{local.day:02d}"


def views(users: list[User]) -> list[UserView]:
    return [user_view(user) for user in users]
