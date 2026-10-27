"""命令层公共工具（不注册 matcher）。"""

from __future__ import annotations

from typing import Iterator

from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, MessageEvent, MessageSegment
from nonebot.matcher import Matcher
from sqlalchemy.orm import Session

from berrystudio.db.models import User
from berrystudio.db.session import session_scope
from berrystudio.permissions import (
    admin_title,
    has_admin_rights,
    is_super_admin,
    require_admin,
)
from berrystudio.services.errors import PermissionDenied
from berrystudio.services.users import (
    ensure_active,
    get_or_create_user,
    get_user,
    require_user,
    touch_user,
)


def db_session() -> Iterator[Session]:
    return session_scope()


def sender_qq(event: MessageEvent) -> str:
    return str(event.user_id)


def sender_nickname(event: MessageEvent) -> str:
    sender = getattr(event, "sender", None)
    if sender is None:
        return ""
    card = getattr(sender, "card", "") or ""
    nickname = getattr(sender, "nickname", "") or ""
    return card or nickname


def source_group_id(event: MessageEvent) -> str:
    if isinstance(event, GroupMessageEvent):
        return str(event.group_id)
    return ""


def message_qq(event: MessageEvent) -> str | None:
    """提取消息里第一个被 @ 的 QQ。"""
    for segment in event.get_message():
        if segment.type == "at":
            qq = str(segment.data.get("qq", ""))
            if qq.isdigit():
                return qq
    return None


def lookup_user(session: Session, event: MessageEvent) -> User | None:
    user = get_user(session, event.user_id)
    if user is not None:
        touch_user(session, user, sender_nickname(event))
    return user


def require_bound(session: Session, event: MessageEvent) -> User:
    return require_user(session, event.user_id, sender_nickname(event))


def require_admin_event(session: Session, event: MessageEvent) -> User:
    user = get_user(session, event.user_id)
    if user is None:
        if not is_super_admin(str(event.user_id)):
            raise PermissionDenied("这个操作只有管理员可以使用")
        user = get_or_create_user(
            session,
            event.user_id,
            nickname=sender_nickname(event),
            display_name=f"管理员{str(event.user_id)[-4:]}",
        )
    ensure_active(user)
    return require_admin(user)


def can_view_details(user: User | None) -> bool:
    return has_admin_rights(user)


def role_title(user: User | None) -> str:
    return admin_title(user) or "用户"


async def finish_image(matcher: Matcher, image: bytes, caption: str = "") -> None:
    message: Message = MessageSegment.image(image)
    if caption:
        message = message + "\n" + caption
    await matcher.finish(message)
