"""场景列表与空闲时段查询。"""

from __future__ import annotations

from datetime import date, datetime

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Message, MessageEvent
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from nonebot.rule import to_me

from berrystudio.commands.common import require_bound
from berrystudio.config import get_settings
from berrystudio.db.session import session_scope
from berrystudio.services.bookings import free_slots
from berrystudio.services.errors import BerryError
from berrystudio.services.scenes import list_scenes, resolve_scene
from berrystudio.utils.format import WEEKDAY_CN, fmt_duration, scene_kind_label
from berrystudio.utils.timeparse import parse_date

scene_cmd = on_command(
    "场景", aliases={"场地", "场景列表"}, rule=to_me(), priority=10, block=True
)
free_cmd = on_command(
    "空闲", aliases={"空闲时段", "空档"}, rule=to_me(), priority=10, block=True
)


@scene_cmd.handle()
async def handle_scenes(matcher: Matcher, event: MessageEvent) -> None:
    with session_scope() as session:
        require_bound(session, event)
        scenes = list_scenes(session)
    if not scenes:
        await matcher.finish("当前还没有开放预约的场景，请联系管理员。")
    lines = ["可预约场景："]
    for scene in scenes:
        lines.append(
            f"· {scene.name}（{scene.code}）\n"
            f"  {scene_kind_label(scene.kind)}｜{scene.open_hour:02d}:00-{scene.close_hour:02d}:00｜"
            f"¥{scene.hourly_price}/小时｜容纳 {scene.capacity} 人\n"
            f"  时长 {scene.min_minutes}-{scene.max_minutes} 分钟｜按 {scene.slot_minutes} 分钟对齐"
        )
    lines.append("示例：/预约 排练室A 明天 19:00-21:00")
    await matcher.finish("\n".join(lines))


@free_cmd.handle()
async def handle_free(
    matcher: Matcher, event: MessageEvent, args: Message = CommandArg()
) -> None:
    tokens = args.extract_plain_text().strip().split()
    if not tokens:
        await matcher.finish("用法：/空闲 场景 [日期]\n例如：/空闲 排练室A 明天")
    settings = get_settings()
    tz = settings.tz
    today = datetime.now(tz).date()
    day: date = today
    scene_token = ""
    date_seen = False
    for token in tokens:
        parsed = parse_date(token, today)
        if parsed is not None and not date_seen:
            day = parsed
            date_seen = True
        elif parsed is None:
            scene_token = token
    if not scene_token:
        await matcher.finish("用法：/空闲 场景 [日期]\n例如：/空闲 排练室A 明天")
    try:
        with session_scope() as session:
            require_bound(session, event)
            scene = resolve_scene(session, scene_token)
            slots = free_slots(session, scene, day)
            scene_name = scene.name
            open_hour, close_hour = scene.open_hour, scene.close_hour
    except BerryError as exc:
        await matcher.finish(str(exc))

    header = f"{scene_name}｜{day:%Y-%m-%d} {WEEKDAY_CN[day.weekday()]}"
    if not slots:
        await matcher.finish(f"{header}\n当天已约满或已过营业时间。")
    lines = [header, f"营业时间 {open_hour:02d}:00-{close_hour:02d}:00，空闲时段："]
    for start, end in slots:
        minutes = int((end - start).total_seconds() // 60)
        lines.append(f"· {start:%H:%M}-{end:%H:%M}（{fmt_duration(minutes)}）")
    lines.append("发送 /预约 场景 日期 时段 提交申请")
    await matcher.finish("\n".join(lines))
