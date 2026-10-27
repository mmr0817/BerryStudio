"""管理员命令：审核、用户 / 场景 / 管理员管理、统计与审计。"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, Message, MessageEvent
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from nonebot.rule import to_me

from berrystudio.commands.common import finish_image, message_qq, require_admin_event
from berrystudio.config import get_settings
from berrystudio.db.models import BookingStatus, UserStatus
from berrystudio.db.session import session_scope
from berrystudio.notify import notify_user_cancelled, notify_user_result
from berrystudio.permissions import is_super_admin
from berrystudio.render.cards import (
    BookingListData,
    StatsCardData,
    render_booking_list,
    render_stats_card,
)
from berrystudio.services import audit
from berrystudio.services.bands import user_bands
from berrystudio.services.bookings import (
    approve_booking,
    cancel_booking,
    get_booking_by_code,
    pending_bookings,
    pending_count,
    recent_bookings,
    reject_booking,
)
from berrystudio.services.dto import BookingView, booking_view
from berrystudio.services.errors import BerryError, NotFoundError
from berrystudio.services.scenes import (
    EDITABLE_FIELDS,
    create_scene,
    get_scene,
    list_scenes,
    set_bookable,
    update_scene,
)
from berrystudio.services.stats import studio_stats, user_stats
from berrystudio.services.users import (
    add_admin,
    get_user,
    list_admins,
    list_users,
    remove_admin,
    set_status,
    user_since_text,
)
from berrystudio.utils.format import (
    fmt_hours,
    fmt_range,
    role_label,
    scene_kind_label,
    status_label,
    user_status_label,
)
from berrystudio.utils.timeparse import parse_date

review_cmd = on_command(
    "审核", aliases={"待审核", "审核列表"}, rule=to_me(), priority=9, block=True
)
approve_cmd = on_command(
    "通过", aliases={"审核通过", "approve"}, rule=to_me(), priority=9, block=True
)
reject_cmd = on_command(
    "驳回", aliases={"拒绝", "reject"}, rule=to_me(), priority=9, block=True
)
manage_cmd = on_command(
    "管理", aliases={"admin", "后台"}, rule=to_me(), priority=9, block=True
)

MANAGE_USAGE = (
    "后台管理命令：\n"
    "/管理 用户 列表 [关键字]\n"
    "/管理 用户 <QQ|@某人> [查看|封禁|解封|设为管理员|取消管理员]\n"
    "/管理 预约 列表 [待审|已通过|全部]\n"
    "/管理 预约 <编号> [查看|取消 原因]\n"
    "/管理 场景 列表\n"
    "/管理 场景 添加 代码 名称 类型 [时价] [开放=9-23] [最短=60] [最长=240] [粒度=30] [容量=8] [颜色=#5EEAD4]\n"
    "/管理 场景 编辑 代码 名称=xx 价格=90 开放=10-23 ...\n"
    "/管理 场景 关闭|开启 代码\n"
    "/管理 管理员 列表|添加 QQ [昵称]|移除 QQ\n"
    "/管理 统计 [开始日期] [结束日期]\n"
    "/管理 审计 [数量]"
)

_CODE_RE = re.compile(r"[Bb]\d{6,}")


def _extract_codes(text: str) -> tuple[list[str], str]:
    codes = [match.group(0).upper() for match in _CODE_RE.finditer(text)]
    note = _CODE_RE.sub(" ", text).strip()
    return codes, note


@review_cmd.handle()
async def handle_review(matcher: Matcher, event: MessageEvent) -> None:
    try:
        with session_scope() as session:
            admin = require_admin_event(session, event)
            bookings = pending_bookings(session, limit=13)
            total = pending_count(session)
            if not bookings:
                await matcher.finish("当前没有待审核的预约 🎉")
            views = [booking_view(booking) for booking in bookings]
            image = render_booking_list(
                BookingListData(
                    title="待审核预约",
                    subtitle=f"共 {total} 条待审核，审核结果会自动通知申请人",
                    owner_label=admin.name,
                    bookings=views,
                    empty_hint="当前没有待审核预约",
                    notes=["/通过 编号 或 /驳回 编号 原因"],
                    show_owner=True,
                )
            )
    except BerryError as exc:
        await matcher.finish(str(exc))
    await finish_image(matcher, image, "审核通过后预约立即生效并同步到服务器")


@approve_cmd.handle()
async def handle_approve(
    bot: Bot, matcher: Matcher, event: MessageEvent, args: Message = CommandArg()
) -> None:
    codes, note = _extract_codes(args.extract_plain_text())
    if not codes:
        await matcher.finish("用法：/通过 预约编号 [备注]\n例如：/通过 B261028001")
    results: list[str] = []
    views: list[BookingView] = []
    pending_after = 0
    try:
        with session_scope() as session:
            admin = require_admin_event(session, event)
            for code in codes:
                try:
                    booking = get_booking_by_code(session, code)
                    approve_booking(session, booking, admin, note=note)
                    audit.record(
                        session,
                        admin,
                        "booking.approve",
                        target_type="booking",
                        target_id=booking.code,
                        detail={"note": note},
                    )
                    results.append(f"✅ {booking.code} 已通过")
                    views.append(booking_view(booking))
                except BerryError as exc:
                    results.append(f"❌ {code}：{exc}")
            pending_after = pending_count(session)
    except BerryError as exc:
        await matcher.finish(str(exc))

    for view in views:
        await notify_user_result(bot, view, approved=True, note=note)
    if pending_after:
        results.append(f"仍有 {pending_after} 条待审核")
    await matcher.finish("\n".join(results))


@reject_cmd.handle()
async def handle_reject(
    bot: Bot, matcher: Matcher, event: MessageEvent, args: Message = CommandArg()
) -> None:
    codes, reason = _extract_codes(args.extract_plain_text())
    if not codes:
        await matcher.finish("用法：/驳回 预约编号 原因\n例如：/驳回 B261028001 该时段已有演出")
    if not reason:
        await matcher.finish("请填写驳回原因，申请人会收到说明")
    results: list[str] = []
    views: list[BookingView] = []
    pending_after = 0
    try:
        with session_scope() as session:
            admin = require_admin_event(session, event)
            for code in codes:
                try:
                    booking = get_booking_by_code(session, code)
                    reject_booking(session, booking, admin, reason=reason)
                    audit.record(
                        session,
                        admin,
                        "booking.reject",
                        target_type="booking",
                        target_id=booking.code,
                        detail={"reason": reason},
                    )
                    results.append(f"✅ {booking.code} 已驳回")
                    views.append(booking_view(booking))
                except BerryError as exc:
                    results.append(f"❌ {code}：{exc}")
            pending_after = pending_count(session)
    except BerryError as exc:
        await matcher.finish(str(exc))

    for view in views:
        await notify_user_result(bot, view, approved=False, note=reason)
    if pending_after:
        results.append(f"仍有 {pending_after} 条待审核")
    await matcher.finish("\n".join(results))


def _resolve_admin_target(
    session, event: MessageEvent, tokens: list[str]
) -> tuple[str | None, str | None]:
    """从命令参数 / @ 中解析目标 QQ 与操作词。"""
    actions = {"查看", "封禁", "解封", "设为管理员", "取消管理员", "查看资料"}
    qq: str | None = None
    action: str | None = None
    for token in tokens:
        cleaned = token.lstrip("@")
        if cleaned.isdigit():
            qq = cleaned
        elif token in actions:
            action = token
        elif token.startswith("备注="):
            continue
    if qq is None:
        qq = message_qq(event)
    return qq, action


def _user_info_text(session, user, tz) -> str:
    bands = user_bands(session, user)
    stats = user_stats(session, user)
    return (
        f"QQ：{user.qq}\n"
        f"昵称：{user.name}\n"
        f"角色：{role_label(user.role)}{'（超级管理员）' if is_super_admin(user.qq) else ''}\n"
        f"状态：{user_status_label(user.status)}\n"
        f"乐队：{('、'.join(b.name for b in bands)) or '暂无'}\n"
        f"预约：总计 {stats.total_bookings} 条｜待审 {stats.pending_bookings} 条｜"
        f"生效时长 {fmt_hours(stats.total_minutes)}\n"
        f"加入时间：{user_since_text(user, tz)}"
    )


def _handle_manage_user(session, event: MessageEvent, admin, tokens: list[str]) -> str:
    tz = get_settings().tz
    if tokens and tokens[0] in {"列表", "list"}:
        keyword = tokens[1] if len(tokens) > 1 else ""
        users = list_users(session, keyword=keyword, limit=20)
        if not users:
            return "没有匹配的用户"
        lines = [f"用户列表（{len(users)} 条）："]
        for user in users:
            lines.append(
                f"· {user.name}（{user.qq}）{role_label(user.role)} · "
                f"{user_status_label(user.status)} · {user_since_text(user, tz)} 加入"
            )
        return "\n".join(lines)

    qq, action = _resolve_admin_target(session, event, tokens)
    if not qq:
        raise BerryError("请提供 QQ 号或 @ 一位用户，例如：/管理 用户 123456 封禁")
    user = get_user(session, qq)
    if user is None:
        raise NotFoundError(f"未找到 QQ {qq} 对应的用户")

    if action in {None, "查看", "查看资料"}:
        return _user_info_text(session, user, tz)

    if action == "封禁":
        set_status(session, user, UserStatus.BANNED, actor=admin)
        audit.record(session, admin, "user.ban", target_type="user", target_id=user.qq)
        return f"已封禁 {user.name}（{user.qq}）"
    if action == "解封":
        set_status(session, user, UserStatus.ACTIVE, actor=admin)
        audit.record(session, admin, "user.unban", target_type="user", target_id=user.qq)
        return f"已解封 {user.name}（{user.qq}）"
    if action == "设为管理员":
        add_admin(session, user.qq)
        audit.record(session, admin, "user.set_admin", target_type="user", target_id=user.qq)
        return f"已将 {user.name} 设为管理员"
    if action == "取消管理员":
        if user.id == admin.id and not is_super_admin(admin.qq):
            raise BerryError("不能取消自己的管理员权限")
        remove_admin(session, user.qq)
        audit.record(session, admin, "user.remove_admin", target_type="user", target_id=user.qq)
        return f"已取消 {user.name} 的管理员权限"
    raise BerryError(MANAGE_USAGE)


def _handle_manage_booking(
    session, event: MessageEvent, admin, tokens: list[str]
) -> tuple[str, BookingView | None]:
    tz = get_settings().tz
    if not tokens:
        raise BerryError("用法：/管理 预约 列表 或 /管理 预约 编号 取消 原因")
    if tokens[0] in {"列表", "list"}:
        status_token = tokens[1] if len(tokens) > 1 else ""
        statuses = {
            "待审": (BookingStatus.PENDING,),
            "待审核": (BookingStatus.PENDING,),
            "已通过": (BookingStatus.APPROVED, BookingStatus.COMPLETED),
            "驳回": (BookingStatus.REJECTED,),
            "取消": (BookingStatus.CANCELLED,),
        }.get(status_token)
        bookings = recent_bookings(session, statuses=statuses, limit=12)
        if not bookings:
            return "没有匹配的预约", None
        lines = [f"最近预约（{len(bookings)} 条）："]
        for booking in bookings:
            lines.append(
                f"· {booking.code}｜{booking.scene.name}｜"
                f"{fmt_range(booking.start_at, booking.end_at, tz)}｜"
                f"{status_label(booking.status)}｜{booking.user.name}"
            )
        return "\n".join(lines), None

    code = tokens[0].lstrip("#").upper()
    booking = get_booking_by_code(session, code)
    action = tokens[1] if len(tokens) > 1 else "查看"
    reason = " ".join(tokens[2:]) if len(tokens) > 2 else ""
    if action == "取消":
        cancel_booking(session, booking, admin, reason=reason, by_admin=True)
        audit.record(
            session,
            admin,
            "booking.cancel",
            target_type="booking",
            target_id=booking.code,
            detail={"reason": reason},
        )
        return f"已取消预约 {booking.code}", booking_view(booking)
    if action == "查看":
        view = booking_view(booking)
        return (
            f"编号：{view.code}\n"
            f"场景：{view.scene_name}\n"
            f"时间：{fmt_range(view.start, view.end, tz)}\n"
            f"申请人：{view.owner_name}（{view.owner_qq}）\n"
            f"乐队：{view.band_name or '个人'}\n"
            f"状态：{view.status_label}\n"
            f"人数：{view.attendees}｜预估 ¥{view.price_estimate}\n"
            f"用途：{view.title or '未填写'}\n"
            f"备注：{view.note or '无'}\n"
            f"审核备注：{view.review_note or '无'}"
        ), None
    raise BerryError("预约操作只支持：查看 / 取消")


def _scene_options(tokens: list[str]) -> dict:
    options: dict = {}
    for token in tokens:
        if "=" not in token:
            continue
        key, _, value = token.partition("=")
        key = key.strip()
        value = value.strip()
        if key in {"开放", "开放时间", "open"} and "-" in value:
            start, _, end = value.partition("-")
            options["open_hour"] = start
            options["close_hour"] = end
        elif key in {"时长", "minutes"} and "-" in value:
            shortest, _, longest = value.partition("-")
            options["min_minutes"] = shortest
            options["max_minutes"] = longest
        elif key == "时价":
            options["hourly_price"] = value
        else:
            field = EDITABLE_FIELDS.get(key)
            if field is None:
                raise BerryError(
                    f"不认识的字段「{key}」，可用：开放/最短/最长/粒度/容量/颜色/描述/时长/时价"
                )
            options[field] = value
    return options


def _handle_manage_scene(session, admin, tokens: list[str]) -> str:
    if not tokens:
        raise BerryError("用法：/管理 场景 列表|添加|编辑|关闭|开启")
    action = tokens[0]
    rest = tokens[1:]
    tz = get_settings().tz
    if action in {"列表", "list"}:
        scenes = list_scenes(session, bookable_only=False)
        if not scenes:
            return "还没有场景"
        lines = [f"场景列表（{len(scenes)} 个）："]
        for scene in scenes:
            state = "开放" if scene.is_bookable else "关闭"
            lines.append(
                f"· {scene.name}（{scene.code}）{scene_kind_label(scene.kind)}·{state}\n"
                f"  {scene.open_hour:02d}-{scene.close_hour:02d}｜¥{scene.hourly_price}/h｜"
                f"容量 {scene.capacity}｜{scene.min_minutes}-{scene.max_minutes} 分钟｜"
                f"{scene.slot_minutes} 分钟粒度"
            )
        return "\n".join(lines)

    if action == "添加":
        if len(rest) < 3:
            raise BerryError(
                "用法：/管理 场景 添加 代码 名称 类型 [时价] [开放=9-23] [最短=60] [最长=240] [粒度=30] [容量=8] [颜色=#5EEAD4]"
            )
        code, name, kind = rest[0], rest[1], rest[2]
        positional = rest[3:]
        price_tokens = [token for token in positional if token.isdigit()]
        options = _scene_options(positional)
        fields = {
            "code": code,
            "name": name,
            "kind": kind,
            "hourly_price": int(price_tokens[0]) if price_tokens else 0,
        }
        fields.update(options)
        scene = create_scene(session, **fields)
        audit.record(
            session,
            admin,
            "scene.create",
            target_type="scene",
            target_id=scene.code,
            detail=fields,
        )
        return (
            f"已添加场景 {scene.name}（{scene.code}）\n"
            f"类型：{scene_kind_label(scene.kind)}｜{scene.open_hour:02d}-{scene.close_hour:02d}｜"
            f"¥{scene.hourly_price}/h｜{scene.min_minutes}-{scene.max_minutes} 分钟"
        )

    if action == "编辑":
        if len(rest) < 2:
            raise BerryError("用法：/管理 场景 编辑 代码 名称=xx 价格=90 开放=10-23")
        scene = get_scene(session, rest[0])
        if scene is None:
            raise NotFoundError(f"没有找到场景 {rest[0]}")
        updates = _scene_options(rest[1:])
        if not updates:
            raise BerryError("请提供需要修改的字段，例如 价格=90")
        update_scene(session, scene, updates)
        audit.record(
            session,
            admin,
            "scene.update",
            target_type="scene",
            target_id=scene.code,
            detail={key: str(value) for key, value in updates.items()},
        )
        return f"已更新场景 {scene.name}（{scene.code}）"

    if action in {"关闭", "开启"}:
        if not rest:
            raise BerryError(f"用法：/管理 场景 {action} 代码")
        scene = get_scene(session, rest[0])
        if scene is None:
            raise NotFoundError(f"没有找到场景 {rest[0]}")
        set_bookable(session, scene, action == "开启")
        audit.record(
            session,
            admin,
            "scene.open" if action == "开启" else "scene.close",
            target_type="scene",
            target_id=scene.code,
        )
        return f"已{action}场景 {scene.name}（{scene.code}）"

    scene = get_scene(session, action)
    if scene is not None:
        return (
            f"场景 {scene.name}（{scene.code}）\n"
            f"类型：{scene_kind_label(scene.kind)}｜{'开放' if scene.is_bookable else '关闭'}\n"
            f"营业时间：{scene.open_hour:02d}-{scene.close_hour:02d}\n"
            f"价格：¥{scene.hourly_price}/h｜容量 {scene.capacity}\n"
            f"时长限制：{scene.min_minutes}-{scene.max_minutes} 分钟｜粒度 {scene.slot_minutes} 分钟\n"
            f"颜色：{scene.color}｜描述：{scene.description or '无'}"
        )
    raise BerryError(MANAGE_USAGE)


def _handle_manage_admin(session, event: MessageEvent, admin, tokens: list[str]) -> str:
    if not tokens or tokens[0] in {"列表", "list"}:
        admins = list_admins(session)
        lines = [f"数据库管理员（{len(admins)} 人）："]
        for user in admins:
            lines.append(f"· {user.name}（{user.qq}）")
        if get_settings().admin_qqs:
            lines.append(
                "配置中的超级管理员：" + "、".join(get_settings().admin_qqs)
            )
        return "\n".join(lines)

    action = tokens[0]
    qq, _ = _resolve_admin_target(session, event, tokens[1:])
    if qq is None and len(tokens) > 1 and tokens[1].lstrip("@").isdigit():
        qq = tokens[1].lstrip("@")
    if qq is None:
        raise BerryError("请提供 QQ 号，例如：/管理 管理员 添加 123456 店长")
    if action == "添加":
        nickname = tokens[2] if len(tokens) > 2 else ""
        user = add_admin(session, qq, display_name=nickname)
        audit.record(session, admin, "admin.add", target_type="user", target_id=qq)
        return f"已添加管理员 {user.name}（{user.qq}）"
    if action == "移除":
        if qq == admin.qq and not is_super_admin(admin.qq):
            raise BerryError("不能移除自己的管理员权限")
        user = remove_admin(session, qq)
        audit.record(session, admin, "admin.remove", target_type="user", target_id=qq)
        note = (
            "\n注意：该 QQ 仍在 .env 的 SUPERUSERS / BERRY_ADMIN_QQ 中，权限仍然有效。"
            if is_super_admin(qq)
            else ""
        )
        return f"已移除管理员 {user.name}（{user.qq}）{note}"
    raise BerryError(MANAGE_USAGE)


def _handle_manage_stats(session, tokens: list[str]) -> bytes:
    tz = get_settings().tz
    today = datetime.now(tz).date()
    dates = [parse_date(token, today) for token in tokens]
    dates = [item for item in dates if item is not None]
    if dates:
        start_day = dates[0]
        end_day = (dates[1] if len(dates) > 1 else dates[0]) + timedelta(days=1)
    else:
        start_day = today.replace(day=1)
        if start_day.month == 12:
            end_day = start_day.replace(year=start_day.year + 1, month=1)
        else:
            end_day = start_day.replace(month=start_day.month + 1)
    start = datetime.combine(start_day, datetime.min.time(), tzinfo=tz)
    end = datetime.combine(end_day, datetime.min.time(), tzinfo=tz)
    stats = studio_stats(session, start, end)
    tiles = [
        ("预约总数", f"{stats.total_bookings}", f"通过 {stats.approved}"),
        ("生效时长", fmt_hours(stats.minutes), f"{stats.active_users} 位用户"),
        ("预估收入", f"¥{stats.revenue}", "按小时价估算"),
        ("场地占用", f"{stats.occupancy * 100:.1f}%", f"待审 {stats.pending}"),
    ]
    return render_stats_card(
        StatsCardData(
            title="工作室运营统计",
            range_label=f"{start_day:%Y-%m-%d} ~ {end_day - timedelta(days=1):%Y-%m-%d}",
            tiles=tiles,
            scene_stats=stats.scene_stats,
            top_bands=stats.top_bands,
            occupancy=stats.occupancy,
            generated_label="",
            notes=[
                f"驳回 {stats.rejected} · 取消 {stats.cancelled} · 统计仅包含服务器数据库记录"
            ],
        )
    )


def _handle_manage_audit(session, tokens: list[str]) -> str:
    limit = 10
    if tokens and tokens[0].isdigit():
        limit = min(30, max(1, int(tokens[0])))
    logs = audit.recent(session, limit=limit)
    if not logs:
        return "暂无后台操作记录"
    tz = get_settings().tz
    lines = [f"最近 {len(logs)} 条后台操作："]
    for log in logs:
        local = log.created_at.astimezone(tz)
        lines.append(
            f"· {local:%m-%d %H:%M}｜{log.actor_qq or '-'}｜{log.action}｜"
            f"{log.target_type}:{log.target_id}"
        )
    return "\n".join(lines)


@manage_cmd.handle()
async def handle_manage(
    bot: Bot,
    matcher: Matcher,
    event: MessageEvent,
    args: Message = CommandArg(),
) -> None:
    tokens = args.extract_plain_text().strip().split()
    if not tokens:
        await matcher.finish(MANAGE_USAGE)
    scope = tokens[0]
    rest = tokens[1:]
    reply_text = ""
    reply_image: bytes | None = None
    reply_caption = ""
    cancelled_view: BookingView | None = None
    try:
        with session_scope() as session:
            admin = require_admin_event(session, event)
            if scope in {"用户", "user", "users"}:
                reply_text = _handle_manage_user(session, event, admin, rest)
            elif scope in {"预约", "booking", "bookings"}:
                reply_text, cancelled_view = _handle_manage_booking(
                    session, event, admin, rest
                )
            elif scope in {"场景", "scene", "scenes"}:
                reply_text = _handle_manage_scene(session, admin, rest)
            elif scope in {"管理员", "admin", "admins"}:
                reply_text = _handle_manage_admin(session, event, admin, rest)
            elif scope in {"统计", "stats"}:
                reply_image = _handle_manage_stats(session, rest)
                reply_caption = "统计口径：已通过 / 已完成预约"
            elif scope in {"审计", "日志", "audit"}:
                reply_text = _handle_manage_audit(session, rest)
            else:
                reply_text = MANAGE_USAGE
    except BerryError as exc:
        await matcher.finish(str(exc))

    if cancelled_view is not None:
        await notify_user_cancelled(bot, cancelled_view, by_admin=True)
    if reply_image is not None:
        await finish_image(matcher, reply_image, reply_caption)
    await matcher.finish(reply_text)
