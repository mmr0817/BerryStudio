"""帮助与命令说明。"""

from __future__ import annotations

from nonebot import on_command
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.matcher import Matcher
from nonebot.rule import to_me

from berrystudio.commands.common import lookup_user
from berrystudio.db.session import session_scope
from berrystudio.permissions import has_admin_rights, is_super_admin

help_cmd = on_command(
    "帮助", aliases={"help", "命令", "菜单"}, rule=to_me(), priority=11, block=True
)

PUBLIC_HELP = (
    "🎸 BERRY STUDIO 排练预约助手\n"
    "\n"
    "【账号】\n"
    "/绑定 昵称        绑定 QQ 并创建账号\n"
    "/我的             个人资料卡（预约统计）\n"
    "\n"
    "【乐队】\n"
    "/创建乐队 名称 [风格] [简介]\n"
    "/乐队 [名称]      我的乐队 / 乐队详情\n"
    "/加入乐队 名称或邀请码 [乐器]\n"
    "/退出乐队 [名称]\n"
    "\n"
    "【预约】\n"
    "/场景             查看可预约场地\n"
    "/空闲 场景 日期    查询某天剩余时段\n"
    "/预约 场景 日期 时段 [乐队=xx 人数=4 用途=xx 备注=xx]\n"
    "/我的预约 [周|月|全部|待审|已通过]\n"
    "/取消 编号        撤销待审核/未开始的预约\n"
    "\n"
    "【日历】\n"
    "/日历 [日|周|月|列表] [日期] [场景]\n"
    "\n"
    "示例：\n"
    "/预约 排练室A 明天 19:00-21:00\n"
    "/预约 录音棚 2026-10-28 14:00+3h 乐队=草莓汽水 人数=5\n"
    "/日历 月 排练室A\n"
)

ADMIN_HELP = (
    "\n【管理员】\n"
    "/审核                      待审核列表\n"
    "/通过 编号 [备注]           审核通过\n"
    "/驳回 编号 原因            驳回申请\n"
    "/管理 用户 <QQ|@某人> [封禁|解封|设为管理员|取消管理员]\n"
    "/管理 预约 列表 [待审|已通过|全部]\n"
    "/管理 预约 编号 [查看|取消 原因]\n"
    "/管理 场景 列表 / 添加 / 编辑 / 关闭 / 开启\n"
    "/管理 管理员 列表 / 添加 QQ [昵称] / 移除 QQ\n"
    "/管理 统计 [开始日期] [结束日期]\n"
    "/管理 审计 [数量]\n"
)


@help_cmd.handle()
async def handle_help(matcher: Matcher, event: MessageEvent) -> None:
    is_admin = False
    with session_scope() as session:
        user = lookup_user(session, event)
        is_admin = has_admin_rights(user)
    if not is_admin:
        is_admin = is_super_admin(str(event.user_id))
    text = PUBLIC_HELP + (ADMIN_HELP if is_admin else "")
    text += "\n所有时间以服务器配置时区为准，预约提交后需管理员审核。"
    await matcher.finish(text)
