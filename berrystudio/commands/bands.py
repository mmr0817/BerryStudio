"""乐队注册 / 查询 / 加入 / 退出。"""

from __future__ import annotations

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Message, MessageEvent
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from nonebot.rule import to_me

from berrystudio.commands.common import require_bound
from berrystudio.config import get_settings
from berrystudio.db.session import session_scope
from berrystudio.services.bands import (
    band_members,
    create_band,
    join_band,
    leave_band,
    resolve_band,
    user_band_membership,
    user_bands,
)
from berrystudio.services.dto import band_view
from berrystudio.services.errors import BerryError
from berrystudio.utils.format import fmt_date, to_local

create_cmd = on_command(
    "创建乐队", aliases={"建团", "新建乐队"}, rule=to_me(), priority=10, block=True
)
band_cmd = on_command(
    "乐队", aliases={"乐队列表", "查乐队"}, rule=to_me(), priority=10, block=True
)
join_cmd = on_command("加入乐队", aliases={"进队"}, rule=to_me(), priority=10, block=True)
leave_cmd = on_command(
    "退出乐队", aliases={"退队"}, rule=to_me(), priority=10, block=True
)


@create_cmd.handle()
async def handle_create(
    matcher: Matcher, event: MessageEvent, args: Message = CommandArg()
) -> None:
    parts = args.extract_plain_text().strip().split(maxsplit=2)
    if not parts:
        await matcher.finish("用法：/创建乐队 名称 [风格] [简介]\n例如：/创建乐队 草莓汽水 独立摇滚")
    name = parts[0]
    style = parts[1] if len(parts) > 1 else ""
    description = parts[2] if len(parts) > 2 else ""
    try:
        with session_scope() as session:
            user = require_bound(session, event)
            band = create_band(session, user, name, style=style, description=description)
            view = band_view(band, member_count=1)
        await matcher.finish(
            f"乐队创建成功！\n"
            f"编号：#{view.id}\n"
            f"名称：{view.name}\n"
            f"风格：{view.style or '未填写'}\n"
            f"邀请码：{view.invite_code}\n"
            f"把邀请码发给队友，他们发送 /加入乐队 {view.invite_code} 即可加入。"
        )
    except BerryError as exc:
        await matcher.finish(str(exc))


@band_cmd.handle()
async def handle_band(
    matcher: Matcher, event: MessageEvent, args: Message = CommandArg()
) -> None:
    keyword = args.extract_plain_text().strip()
    try:
        with session_scope() as session:
            user = require_bound(session, event)
            if not keyword:
                bands = user_bands(session, user)
                if not bands:
                    await matcher.finish(
                        "你还没有加入乐队。\n"
                        "发送 /创建乐队 名称 创建一支，或用 /加入乐队 邀请码 加入已有乐队。"
                    )
                lines = ["你的乐队："]
                for band in bands:
                    members = len(band_members(session, band))
                    role = "队长" if band.leader_id == user.id else "成员"
                    lines.append(
                        f"· #{band.id} {band.name}｜{role}｜{members} 人｜邀请码 {band.invite_code}"
                    )
                lines.append("发送 /乐队 名称 查看详情")
                await matcher.finish("\n".join(lines))

            band = resolve_band(session, keyword)
            members = band_members(session, band)
            is_member = user_band_membership(session, band, user) is not None
            lines = [
                f"#{band.id} {band.name}",
                f"风格：{band.style or '未填写'}",
                f"简介：{band.description or '暂无'}",
                f"队长：{band.leader.name if band.leader else '未知'}",
                f"成员：{len(members)} 人",
            ]
            if is_member or user.role == "admin":
                lines.append(f"邀请码：{band.invite_code}")
            lines.append("成员列表：")
            for member in members:
                role = "队长" if member.role == "leader" else "成员"
                instrument = f" · {member.instrument}" if member.instrument else ""
                lines.append(
                    f"· {member.user.name}（QQ {member.user.qq}）{role}{instrument}"
                )
            lines.append(
                f"创建于 {fmt_date(to_local(band.created_at, get_settings().tz), with_year=True)}"
            )
            if not is_member:
                lines.append(f"发送 /加入乐队 {band.invite_code} 加入")
            await matcher.finish("\n".join(lines))
    except BerryError as exc:
        await matcher.finish(str(exc))


@join_cmd.handle()
async def handle_join(
    matcher: Matcher, event: MessageEvent, args: Message = CommandArg()
) -> None:
    tokens = args.extract_plain_text().strip().split()
    if not tokens:
        await matcher.finish("用法：/加入乐队 乐队名称或邀请码 [乐器]")
    instrument = tokens[1] if len(tokens) > 1 else ""
    try:
        with session_scope() as session:
            user = require_bound(session, event)
            band = resolve_band(session, tokens[0])
            join_band(session, band, user, instrument=instrument)
            band_name = band.name
        await matcher.finish(
            f"已加入「{band_name}」！\n发送 /乐队 {band_name} 查看成员，/预约 时可以带上 乐队={band_name}"
        )
    except BerryError as exc:
        await matcher.finish(str(exc))


@leave_cmd.handle()
async def handle_leave(
    matcher: Matcher, event: MessageEvent, args: Message = CommandArg()
) -> None:
    keyword = args.extract_plain_text().strip()
    try:
        with session_scope() as session:
            user = require_bound(session, event)
            if keyword:
                band = resolve_band(session, keyword)
            else:
                bands = user_bands(session, user)
                if len(bands) == 1:
                    band = bands[0]
                elif not bands:
                    await matcher.finish("你还没有加入任何乐队")
                else:
                    names = "、".join(item.name for item in bands)
                    await matcher.finish(f"你加入了多支乐队：{names}，请指定 /退出乐队 名称")
            message = leave_band(session, band, user)
        await matcher.finish(message)
    except BerryError as exc:
        await matcher.finish(str(exc))
