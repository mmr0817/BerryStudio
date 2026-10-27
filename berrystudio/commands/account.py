"""账号绑定与个人资料卡。"""

from __future__ import annotations

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Message, MessageEvent
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from nonebot.rule import to_me

from berrystudio.commands.common import (
    finish_image,
    require_bound,
    role_title,
    sender_nickname,
)
from berrystudio.config import get_settings
from berrystudio.db.session import session_scope
from berrystudio.render.cards import ProfileCardData, render_profile_card
from berrystudio.services.bands import user_bands
from berrystudio.services.errors import BerryError
from berrystudio.services.stats import user_rank_text, user_stats
from berrystudio.services.users import bind_user, user_since_text
from berrystudio.utils.format import fmt_hours

bind_cmd = on_command(
    "绑定", aliases={"注册", "bind"}, rule=to_me(), priority=10, block=True
)
profile_cmd = on_command(
    "我的",
    aliases={"我的信息", "个人资料", "me", "profile"},
    rule=to_me(),
    priority=10,
    block=True,
)


@bind_cmd.handle()
async def handle_bind(
    matcher: Matcher, event: MessageEvent, args: Message = CommandArg()
) -> None:
    name = args.extract_plain_text().strip() or sender_nickname(event)
    if not name:
        await matcher.finish("用法：/绑定 你的昵称\n例如：/绑定 小明")
    try:
        with session_scope() as session:
            user = bind_user(
                session,
                event.user_id,
                name,
                nickname=sender_nickname(event),
            )
            bands = user_bands(session, user)
            display_name = user.name
            qq = user.qq
            band_names = "、".join(band.name for band in bands) or "暂无"
        settings = get_settings()
        await matcher.finish(
            f"绑定成功！\n"
            f"昵称：{display_name}\n"
            f"QQ：{qq}\n"
            f"乐队：{band_names}\n"
            f"可用命令：/我的 · /创建乐队 · /场景 · /预约 · /日历 · /帮助\n"
            f"时间基准：{settings.timezone_name}"
        )
    except BerryError as exc:
        await matcher.finish(str(exc))


@profile_cmd.handle()
async def handle_profile(matcher: Matcher, event: MessageEvent) -> None:
    with session_scope() as session:
        user = require_bound(session, event)
        stats = user_stats(session, user)
        bands = [band.name for band in user_bands(session, user)]
        tz = get_settings().tz
        tiles = [
            ("本月预约", f"{stats.month_bookings} 条", fmt_hours(stats.month_minutes)),
            ("累计时长", fmt_hours(stats.total_minutes), f"通过 {stats.approved_bookings} 次"),
            ("常驻场景", stats.favourite_scene, "按累计时长"),
            ("待审核", f"{stats.pending_bookings} 条", "等待管理员"),
        ]
        data = ProfileCardData(
            owner_name=user.name,
            qq=user.qq,
            role_title=role_title(user),
            rank=user_rank_text(stats),
            bands=bands,
            stats=tiles,
            upcoming=stats.upcoming,
            created_label=user_since_text(user, tz),
            generated_label="",
            total_minutes=stats.total_minutes,
        )
        image = render_profile_card(data)
    await finish_image(
        matcher,
        image,
        "资料与预约状态实时来自服务器数据库。",
    )
