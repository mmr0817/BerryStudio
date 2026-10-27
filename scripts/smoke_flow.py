"""端到端冒烟测试：不连接 QQ，直接走一遍绑定 → 建队 → 预约 → 审核 → 查询。

运行：

    .venv/bin/python scripts/smoke_flow.py
"""

from __future__ import annotations

import sys
from datetime import datetime, time, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from berrystudio.config import get_settings  # noqa: E402
from berrystudio.db.migrate import run_migrations  # noqa: E402
from berrystudio.db.models import BookingStatus, Scene  # noqa: E402
from berrystudio.db.seed import seed_default_scenes  # noqa: E402
from berrystudio.db.session import configure, session_scope  # noqa: E402
from berrystudio.services.bands import create_band, user_bands  # noqa: E402
from berrystudio.services.bookings import (  # noqa: E402
    approve_booking,
    create_booking,
    free_slots,
    get_booking_by_code,
    pending_bookings,
)
from berrystudio.services.errors import BerryError  # noqa: E402
from berrystudio.services.scenes import resolve_scene  # noqa: E402
from berrystudio.services.stats import studio_stats, user_stats  # noqa: E402
from berrystudio.services.users import add_admin, get_or_create_user  # noqa: E402
from berrystudio.utils.format import fmt_range  # noqa: E402
from berrystudio.utils.timeparse import (  # noqa: E402
    parse_booking_args,
    parse_time_range,
)


def main() -> None:
    settings = get_settings()
    tz = settings.tz
    db_path = settings.base_dir / "data" / "smoke.db"
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(db_path) + suffix)
        if candidate.exists():
            candidate.unlink()

    engine = configure(f"sqlite+pysqlite:///{db_path}")
    run_migrations(engine)
    now = datetime.now(tz)
    today = now.date()

    with session_scope() as session:
        seed_default_scenes(session)
        admin = add_admin(session, "90001", display_name="店长")
        user = get_or_create_user(session, "10001", display_name="小明")
        band = create_band(session, user, "草莓汽水", style="独立摇滚")
        print(f"用户：{user.name}（{user.qq}），乐队：{band.name}，邀请码 {band.invite_code}")

        scene_token, day, slot, options = parse_booking_args(
            "排练室A 明天 19:00-21:00 人数=3 用途=常规排练", today
        )
        print(f"解析预约参数：场景={scene_token} 日期={day} 时段={slot} 选项={options}")
        scene = resolve_scene(session, scene_token)
        start, end = parse_time_range(slot, day)
        booking = create_booking(
            session,
            user,
            scene,
            start,
            end,
            band=band,
            title=options.get("用途", ""),
            attendees=int(options.get("人数", 1)),
        )
        print(
            f"提交预约：{booking.code}（{booking.status}） "
            f"{fmt_range(booking.start_at, booking.end_at, tz)} 预估 ¥{booking.price_estimate}"
        )

        try:
            create_booking(session, user, scene, start, end)
        except BerryError as exc:
            print(f"冲突校验正常拦截：{exc}")

        approve_booking(session, booking, admin, note="冒烟测试通过")
        print(f"管理员审核：{booking.code} → {booking.status}")

        second = create_booking(
            session,
            user,
            scene,
            start + timedelta(days=1),
            end + timedelta(days=1),
            band=band,
            title="待审核示例",
        )
        print(f"另一条待审核预约：{second.code}（可用 CLI /bot 审核）")

        slots = free_slots(session, scene, day)
        print("当天剩余空闲：" + "、".join(f"{s:%H:%M}-{e:%H:%M}" for s, e in slots))

        stats = user_stats(session, user, now=start.replace(tzinfo=tz) - timedelta(hours=2))
        print(
            f"个人统计：预约 {stats.total_bookings} 条，累计 {stats.total_minutes} 分钟，"
            f"常驻场景 {stats.favourite_scene}"
        )

        range_start = datetime.combine(day, time(0), tzinfo=tz)
        studio = studio_stats(session, range_start, range_start + timedelta(days=1))
        print(
            f"工作室统计：通过 {studio.approved} 单，收入 ¥{studio.revenue}，"
            f"占用率 {studio.occupancy * 100:.1f}%"
        )

        pending = pending_bookings(session)
        if pending:
            print(f"待审核示例编号：{pending[0].code}")

    with session_scope() as session:
        reviewed = get_booking_by_code(session, booking.code)
        assert reviewed.status == BookingStatus.APPROVED
        assert get_or_create_user(session, "10001").id == user.id
        assert user_bands(session, user)
        assert session.scalar(select(Scene).where(Scene.code == scene.code))

    print(f"冒烟流程通过，数据库：{db_path}")


if __name__ == "__main__":
    main()
