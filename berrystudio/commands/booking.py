"""预约提交 / 取消 / 我的预约。"""

from __future__ import annotations

import re
from datetime import datetime, time, timedelta

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, Message, MessageEvent
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from nonebot.rule import to_me

from berrystudio.commands.common import (
    finish_image,
    require_bound,
    source_group_id,
)
from berrystudio.config import get_settings
from berrystudio.db.session import session_scope
from berrystudio.notify import notify_admins_new_booking, notify_user_cancelled
from berrystudio.permissions import has_admin_rights
from berrystudio.render.cards import BookingListData, render_booking_list
from berrystudio.services.bands import resolve_band, user_bands
from berrystudio.services.bookings import (
    cancel_booking,
    create_booking,
    get_booking_by_code,
    pending_count,
    user_bookings,
)
from berrystudio.services.dto import booking_view
from berrystudio.services.errors import BerryError
from berrystudio.services.scenes import resolve_scene
from berrystudio.services.users import admin_user_qqs
from berrystudio.utils.format import (
    fmt_range,
    fmt_hours,
    month_bounds,
    week_bounds,
)
from berrystudio.utils.timeparse import (
    parse_booking_args,
    parse_date,
    parse_duration,
    parse_time_range,
)

book_cmd = on_command(
    "预约", aliases={"预订", "book"}, rule=to_me(), priority=10, block=True
)
cancel_cmd = on_command(
    "取消", aliases={"取消预约", "cancel"}, rule=to_me(), priority=10, block=True
)
my_bookings_cmd = on_command(
    "我的预约", aliases={"预约记录", "mybooking"}, rule=to_me(), priority=10, block=True
)

USAGE = (
    "用法：/预约 场景 日期 时段 [乐队=名称] [人数=4] [用途=xxx] [备注=xxx]\n"
    "示例：/预约 排练室A 明天 19:00-21:00\n"
    "      /预约 录音棚 2026-10-28 14:00+3h 乐队=草莓汽水 人数=5\n"
    "      /预约 排练 周三 19点-21点"
)


@book_cmd.handle()
async def handle_book(
    bot: Bot,
    matcher: Matcher,
    event: MessageEvent,
    args: Message = CommandArg(),
) -> None:
    text = args.extract_plain_text().strip()
    if not text:
        await matcher.finish(USAGE)

    settings = get_settings()
    tz = settings.tz
    today = datetime.now(tz).date()

    try:
        scene_token, day, slot_token, options = parse_booking_args(text, today)
        with session_scope() as session:
            user = require_bound(session, event)
            if scene_token:
                scene = resolve_scene(session, scene_token)
            else:
                from berrystudio.services.scenes import list_scenes

                candidates = list_scenes(session)
                if len(candidates) == 1:
                    scene = candidates[0]
                elif not candidates:
                    raise BerryError("当前没有可预约场景，请联系管理员")
                else:
                    names = "、".join(f"{item.name}({item.code})" for item in candidates)
                    raise BerryError(f"请指定场景：{names}")

            if slot_token is None:
                raise BerryError(USAGE)

            try:
                start_local, end_local = parse_time_range(
                    slot_token,
                    day,
                    default_minutes=settings.default_duration_minutes,
                )
            except ValueError as exc:
                raise BerryError(str(exc)) from exc

            duration_token = (
                options.get("时长")
                or options.get("duration")
                or options.get("多久")
            )
            if duration_token:
                duration = parse_duration(duration_token)
                if duration is None:
                    raise BerryError("时长格式无法识别，例如 时长=2h 或 时长=90分钟")
                end_local = start_local + duration

            band = None
            band_token = options.get("乐队") or options.get("band")
            if band_token:
                band = resolve_band(session, band_token)
                if not any(item.id == band.id for item in user_bands(session, user)):
                    raise BerryError(
                        f"你不在「{band.name}」里，发送 /加入乐队 {band.invite_code} 加入"
                    )
            else:
                bands = user_bands(session, user)
                if len(bands) == 1:
                    band = bands[0]

            attendees_raw = options.get("人数") or options.get("attendees") or "1"
            try:
                attendees = int(attendees_raw)
            except ValueError as exc:
                raise BerryError("人数需要填写数字，例如 人数=4") from exc

            title = options.get("用途") or options.get("标题") or " ".join(
                filter(None, [options.get("_extra", ""), band.name if band else ""])
            )
            note = options.get("备注") or options.get("note") or ""

            booking = create_booking(
                session,
                user,
                scene,
                start_local,
                end_local,
                band=band,
                title=title,
                note=note,
                attendees=attendees,
                group_id=source_group_id(event),
                source="bot",
            )
            view = booking_view(booking)
            admin_qqs = admin_user_qqs(session)
            remaining = pending_count(session)
            owner_label = user.name

        image = render_booking_list(
            BookingListData(
                title="预约已提交",
                subtitle="等待管理员审核，通过后才会正式占用时段",
                owner_label=owner_label,
                bookings=[view],
                empty_hint="",
                notes=["如信息有误：发送 /取消 编号 撤销申请"],
            )
        )
        notified = await notify_admins_new_booking(
            bot, view, admin_qqs, pending_total=remaining
        )
        caption = (
            f"已通知 {notified} 位管理员审核。"
            if notified
            else "管理员暂时未收到私聊提醒，请耐心等待（管理员可发送 /审核 查看）。"
        )
        await finish_image(matcher, image, caption)
    except BerryError as exc:
        await matcher.finish(str(exc))


@cancel_cmd.handle()
async def handle_cancel(
    bot: Bot,
    matcher: Matcher,
    event: MessageEvent,
    args: Message = CommandArg(),
) -> None:
    text = args.extract_plain_text().strip()
    match = re.search(r"[Bb]\d{6,}", text)
    if not match:
        await matcher.finish("用法：/取消 预约编号\n例如：/取消 B261028001")
    code = match.group(0).upper()
    reason = text.replace(match.group(0), "").strip()
    notify_admin = False
    try:
        with session_scope() as session:
            user = require_bound(session, event)
            booking = get_booking_by_code(session, code)
            is_admin = has_admin_rights(user)
            cancel_booking(
                session,
                booking,
                user,
                reason=reason,
                by_admin=is_admin and booking.user_id != user.id,
            )
            view = booking_view(booking)
            notify_admin = booking.user_id != user.id
        if notify_admin:
            await notify_user_cancelled(bot, view, by_admin=True, reason=reason)
        await matcher.finish(
            f"已取消预约 {view.code}\n"
            f"{view.scene_name}｜{fmt_range(view.start, view.end, get_settings().tz)}"
        )
    except BerryError as exc:
        await matcher.finish(str(exc))


@my_bookings_cmd.handle()
async def handle_my_bookings(
    matcher: Matcher, event: MessageEvent, args: Message = CommandArg()
) -> None:
    settings = get_settings()
    tz = settings.tz
    now = datetime.now(tz)
    today = now.date()
    tokens = args.extract_plain_text().strip().split()

    start: datetime | None = datetime.combine(
        today - timedelta(days=7), time(0), tzinfo=tz
    )
    end: datetime | None = datetime.combine(
        today + timedelta(days=61), time(0), tzinfo=tz
    )
    statuses: tuple[str, ...] | None = None
    scope_label = "近 60 天"
    anchor = today

    for token in tokens:
        if token in {"全部", "all"}:
            start = None
            end = None
            scope_label = "全部记录"
        elif token in {"周", "本周", "week"}:
            week_start, week_end = week_bounds(today)
            start = datetime.combine(week_start, datetime.min.time(), tzinfo=tz)
            end = datetime.combine(week_end, datetime.min.time(), tzinfo=tz)
            scope_label = f"{week_start:%m-%d} ~ {week_end - timedelta(days=1):%m-%d}"
        elif token in {"月", "本月", "month"}:
            month_start, month_end = month_bounds(today)
            start = datetime.combine(month_start, datetime.min.time(), tzinfo=tz)
            end = datetime.combine(month_end, datetime.min.time(), tzinfo=tz)
            scope_label = f"{month_start.year} 年 {month_start.month} 月"
        elif token in {"待审", "待审核", "pending"}:
            statuses = ("pending",)
            scope_label = "待审核"
        elif token in {"已通过", "通过", "approved"}:
            statuses = ("approved", "completed")
            scope_label = "已通过"
        elif token in {"已驳回", "驳回", "rejected"}:
            statuses = ("rejected",)
            scope_label = "已驳回"
        elif token in {"已取消", "取消", "cancelled"}:
            statuses = ("cancelled",)
            scope_label = "已取消"
        else:
            parsed = parse_date(token, today)
            if parsed:
                anchor = parsed
                start = datetime.combine(parsed, datetime.min.time(), tzinfo=tz)
                end = datetime.combine(parsed + timedelta(days=1), datetime.min.time(), tzinfo=tz)
                scope_label = f"{parsed:%Y-%m-%d}"

    with session_scope() as session:
        user = require_bound(session, event)
        bookings = user_bookings(
            session,
            user,
            statuses=statuses,
            start=start,
            end=end,
            limit=13,
            newest_first=False,
        )
        if bookings:
            bookings = sorted(
                bookings,
                key=lambda item: (
                    item.start_at.astimezone(tz) < now,
                    item.start_at,
                ),
            )
        views = [booking_view(item) for item in bookings]
        owner_label = user.name
        total_minutes = sum(
            item.duration_minutes
            for item in views
            if item.status in {"approved", "completed"}
        )

    image = render_booking_list(
        BookingListData(
            title="我的预约",
            subtitle=f"{scope_label}｜{len(views)} 条｜生效 {fmt_hours(total_minutes)}",
            owner_label=owner_label,
            bookings=views,
            empty_hint="发送 /预约 场景 日期 时段 提交新的申请",
            notes=["/我的预约 周/月/全部 切换范围 · /取消 编号 撤销预约"],
        )
    )
    await finish_image(matcher, image)
