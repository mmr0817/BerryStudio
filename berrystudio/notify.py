"""QQ 通知：新预约推送管理员、审核结果推送申请人。"""

from __future__ import annotations

import asyncio
from typing import Iterable

from nonebot import logger
from nonebot.adapters.onebot.v11 import Bot, Message, MessageSegment

from berrystudio.config import get_settings
from berrystudio.render.cards import ReviewCardData, render_review_card
from berrystudio.services.dto import BookingView
from berrystudio.utils.format import fmt_range, status_label


def _image_message(image: bytes, caption: str) -> Message:
    return MessageSegment.image(image) + "\n" + caption


async def notify_admins_new_booking(
    bot: Bot,
    booking: BookingView,
    admin_qqs: Iterable[str],
    *,
    pending_total: int = 1,
) -> int:
    """给所有管理员私聊推送审核卡，返回成功人数。"""
    qqs = [qq for qq in dict.fromkeys(admin_qqs) if str(qq).isdigit()]
    if not qqs:
        logger.warning("没有配置管理员，预约 {} 无法推送审核", booking.code)
        return 0

    settings = get_settings()
    image = render_review_card(
        ReviewCardData(
            booking=booking,
            pending_total=pending_total,
            generated_label="",
        )
    )
    caption = (
        f"待审核预约 {booking.code}\n"
        f"/通过 {booking.code} 或 /驳回 {booking.code} 原因"
    )
    message = _image_message(image, caption)

    async def send(qq: str) -> bool:
        try:
            await asyncio.wait_for(
                bot.send_private_msg(user_id=int(qq), message=message), timeout=15
            )
            return True
        except Exception as exc:  # noqa: BLE001 - 单个管理员失败不影响其他人
            logger.warning("向管理员 {} 推送审核消息失败：{}", qq, exc)
            return False

    results = await asyncio.gather(*(send(qq) for qq in qqs))
    success = sum(1 for item in results if item)

    if not success and settings.notify_fallback_group and booking.group_id:
        try:
            await bot.send_group_msg(
                group_id=int(booking.group_id),
                message=(
                    f"有新的待审核预约 {booking.code}（{booking.scene_name} · "
                    f"{fmt_range(booking.start, booking.end, settings.tz)}），"
                    "请管理员发送 /审核 处理。"
                ),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("群聊回落提醒失败：{}", exc)
    return success


async def notify_user_result(
    bot: Bot,
    booking: BookingView,
    *,
    approved: bool,
    note: str = "",
) -> bool:
    """把审核结果私聊发给申请人。"""
    settings = get_settings()
    title = "预约已通过" if approved else "预约被驳回"
    lines = [
        f"【{title}】{booking.code}",
        f"场景：{booking.scene_name}",
        f"时间：{fmt_range(booking.start, booking.end, settings.tz)}",
        f"状态：{status_label(booking.status)}",
    ]
    if note:
        lines.append(f"备注：{note}")
    if approved:
        lines.append("请按时到场，发送 /我的预约 可随时查看。")
    else:
        lines.append("可以重新选择时段提交预约。")
    message = "\n".join(lines)

    try:
        await asyncio.wait_for(
            bot.send_private_msg(user_id=int(booking.owner_qq), message=message),
            timeout=15,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("向 {} 推送审核结果失败：{}", booking.owner_qq, exc)
        if settings.notify_fallback_group and booking.group_id:
            try:
                await bot.send_group_msg(
                    group_id=int(booking.group_id),
                    message=MessageSegment.at(booking.owner_qq) + f"\n{message}",
                )
                return True
            except Exception as group_exc:  # noqa: BLE001
                logger.warning("群聊回落审核结果失败：{}", group_exc)
        return False


async def notify_user_cancelled(
    bot: Bot,
    booking: BookingView,
    *,
    by_admin: bool = False,
    reason: str = "",
) -> bool:
    settings = get_settings()
    lines = [
        f"【预约已取消】{booking.code}",
        f"场景：{booking.scene_name}",
        f"时间：{fmt_range(booking.start, booking.end, settings.tz)}",
    ]
    if by_admin:
        lines.append("取消人：管理员")
    if reason:
        lines.append(f"原因：{reason}")
    message = "\n".join(lines)
    try:
        await asyncio.wait_for(
            bot.send_private_msg(user_id=int(booking.owner_qq), message=message),
            timeout=15,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("取消通知发送失败：{}", exc)
        return False
