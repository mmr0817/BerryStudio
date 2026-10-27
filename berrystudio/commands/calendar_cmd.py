"""日历图片命令。"""

from __future__ import annotations

from datetime import datetime

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Message, MessageEvent
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from nonebot.rule import to_me

from berrystudio.commands.common import (
    can_view_details,
    finish_image,
    require_bound,
)
from berrystudio.config import get_settings
from berrystudio.db.session import session_scope
from berrystudio.render.calendar import render_calendar
from berrystudio.services.errors import BerryError
from berrystudio.services.schedule import VIEW_ALIASES, build_calendar_data
from berrystudio.services.scenes import resolve_scene
from berrystudio.utils.timeparse import parse_date

calendar_cmd = on_command(
    "日历", aliases={"calendar", "查日历"}, rule=to_me(), priority=10, block=True
)


@calendar_cmd.handle()
async def handle_calendar(
    matcher: Matcher, event: MessageEvent, args: Message = CommandArg()
) -> None:
    tokens = args.extract_plain_text().strip().split()
    settings = get_settings()
    today = datetime.now(settings.tz).date()
    view = "week"
    anchor = today
    scene_token = ""
    for token in tokens:
        key = token.strip().lower()
        if key in VIEW_ALIASES:
            view = VIEW_ALIASES[key]
            continue
        parsed = parse_date(token, today)
        if parsed is not None:
            anchor = parsed
            continue
        scene_token = token

    try:
        with session_scope() as session:
            user = require_bound(session, event)
            scene = resolve_scene(session, scene_token) if scene_token else None
            data = build_calendar_data(
                session,
                view=view,
                anchor=anchor,
                scene=scene,
                viewer=user,
                can_view_details=can_view_details(user),
            )
            image = render_calendar(data)
    except BerryError as exc:
        await matcher.finish(str(exc))

    hint = (
        "用法：/日历 日|周|月|列表 [日期] [场景]\n"
        "例如：/日历 月 · /日历 周 排练室A · /日历 日 明天 录音棚"
    )
    await finish_image(matcher, image, hint)
