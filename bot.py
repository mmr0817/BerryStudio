"""BerryStudio QQ 群机器人入口。

启动：

    .venv/bin/python bot.py

运行前请确认 OneBot v11 实现（NapCat / Lagrange / go-cqhttp 等）已连接，
并在 ``.env`` 中配置好 ``DRIVER=~fastapi``、``PORT`` 与管理员 QQ。
"""

from __future__ import annotations

from pathlib import Path

import nonebot
from nonebot.adapters.onebot.v11 import Adapter
from nonebot.log import logger

nonebot.init()
driver = nonebot.get_driver()
driver.register_adapter(Adapter)

from berrystudio.config import get_settings  # noqa: E402
from berrystudio.db.migrate import schema_version  # noqa: E402
from berrystudio.db.session import get_engine, init_database, session_scope  # noqa: E402
from berrystudio.services.bookings import archive_past_bookings  # noqa: E402


@driver.on_startup
async def startup() -> None:
    settings = get_settings()
    applied = init_database()
    logger.info(
        "BerryStudio 数据库就绪：{}（schema v{}，本次应用迁移 {}）",
        settings.db_path,
        schema_version(get_engine()),
        applied or "无",
    )
    with session_scope() as session:
        archived = archive_past_bookings(session)
    if archived:
        logger.info("已自动归档 {} 条已结束预约", archived)
    if not settings.admin_qqs:
        logger.warning(
            "尚未配置管理员：请在 .env 设置 SUPERUSERS 或 BERRY_ADMIN_QQ，"
            "否则新预约无法自动推送审核"
        )


# 注册 HTTP 后台（FastAPI driver 才可用）
server_app = getattr(driver, "server_app", None)
if server_app is not None:
    from berrystudio.webadmin import build_router  # noqa: E402

    server_app.include_router(build_router(get_settings()))

    @server_app.get("/health", tags=["berrystudio"])
    async def health() -> dict[str, str]:
        return {"status": "ok", "app": "berrystudio"}

    logger.info("HTTP 后台已注册：/admin/api/*（令牌见 BERRY_ADMIN_API_TOKEN）")

plugin_dir = Path(__file__).resolve().parent / "berrystudio" / "commands"
nonebot.load_plugins(str(plugin_dir))

if __name__ == "__main__":
    nonebot.run()
