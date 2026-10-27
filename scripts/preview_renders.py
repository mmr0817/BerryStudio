"""生成一组示例图片，便于检查渲染效果（不参与 bot 运行）。

运行：

    .venv/bin/python scripts/preview_renders.py
"""

from __future__ import annotations

import sys
from datetime import datetime, time, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from berrystudio.config import get_settings
from berrystudio.db.migrate import run_migrations
from berrystudio.db.models import Scene
from berrystudio.db.seed import seed_default_scenes
from berrystudio.db.session import configure, session_scope
from berrystudio.render.calendar import render_calendar
from berrystudio.render.cards import (
    BookingListData,
    ProfileCardData,
    ReviewCardData,
    StatsCardData,
    render_booking_list,
    render_profile_card,
    render_review_card,
    render_stats_card,
)
from berrystudio.services.bands import create_band
from berrystudio.services.bookings import (
    approve_booking,
    cancel_booking,
    create_booking,
    pending_bookings,
    recent_bookings,
    reject_booking,
)
from berrystudio.services.dto import booking_view
from berrystudio.services.schedule import build_calendar_data
from berrystudio.services.stats import studio_stats, user_rank_text, user_stats
from berrystudio.services.users import get_or_create_user
from berrystudio.utils.format import fmt_hours

from PIL import Image
import io


def main() -> None:
    settings = get_settings()
    tz = settings.tz
    db_path = settings.base_dir / "data" / "preview.db"
    if db_path.exists():
        db_path.unlink()
    engine = configure(f"sqlite+pysqlite:///{db_path}")
    run_migrations(engine)

    now = datetime.now(tz)
    today = now.date()

    with session_scope() as session:
        seed_default_scenes(session)
        scenes = {scene.code: scene for scene in session.scalars(select(Scene))}
        users = [
            get_or_create_user(session, "10001", display_name="小明"),
            get_or_create_user(session, "10002", display_name="小红"),
            get_or_create_user(session, "10003", display_name="阿杰"),
            get_or_create_user(session, "90001", display_name="店长"),
        ]
        bands = [
            create_band(session, users[0], "草莓汽水", style="独立摇滚"),
            create_band(session, users[1], "午夜电波", style="City Pop"),
            create_band(session, users[2], "纸飞机", style="民谣"),
        ]
        admin = users[3]

        specs = [
            # (day offset, hour, duration, scene code, user index, status)
            (1, 19, 2, "REH-A", 0, "approved"),
            (1, 21, 1, "REH-A", 1, "approved"),
            (1, 14, 3, "REC-A", 2, "approved"),
            (2, 10, 2, "REH-B", 1, "approved"),
            (2, 19, 2, "REH-A", 2, "pending"),
            (2, 15, 2, "LIVE", 0, "approved"),
            (3, 13, 4, "REC-A", 0, "approved"),
            (3, 19, 2, "REH-A", 1, "approved"),
            (4, 9, 2, "REH-B", 0, "approved"),
            (4, 18, 3, "REH-A", 2, "approved"),
            (5, 11, 2, "REH-A", 1, "approved"),
            (5, 20, 2, "LIVE", 2, "pending"),
            (6, 16, 2, "REH-B", 2, "approved"),
            (7, 19, 2, "REH-A", 0, "approved"),
            (8, 10, 3, "REC-A", 1, "approved"),
            (9, 19, 2, "REH-A", 2, "approved"),
            (10, 15, 2, "REH-B", 0, "approved"),
            (12, 19, 2, "REH-A", 1, "approved"),
            (14, 14, 2, "LIVE", 0, "approved"),
            (17, 19, 2, "REH-A", 2, "approved"),
        ]
        created = []
        for offset, hour, duration, code, user_index, status in specs:
            start = datetime.combine(today + timedelta(days=offset), time(hour, 0), tzinfo=tz)
            band = bands[user_index]
            booking = create_booking(
                session,
                users[user_index],
                scenes[code],
                start,
                start + timedelta(hours=duration),
                band=band,
                title="常规排练" if code.startswith("REH") else "录音 / 演出",
                note="需要准备备用鼓棒" if user_index == 1 else "",
                attendees=min(scenes[code].capacity, 3 + user_index),
            )
            if status == "approved":
                approve_booking(session, booking, admin, note="确认档期")
            elif status == "rejected":
                reject_booking(session, booking, admin, reason="设备维护")
            created.append(booking)

        # 一条已取消的预约
        cancelled = create_booking(
            session,
            users[0],
            scenes["REH-B"],
            datetime.combine(today + timedelta(days=2), time(18, 0), tzinfo=tz),
            datetime.combine(today + timedelta(days=2), time(20, 0), tzinfo=tz),
            band=bands[0],
        )
        cancel_booking(session, cancelled, users[0], reason="队员临时加班")

        user = users[0]
        profile_stats = user_stats(session, user)
        profile = render_profile_card(
            ProfileCardData(
                owner_name=user.name,
                qq=user.qq,
                role_title="用户",
                rank=user_rank_text(profile_stats),
                bands=[band.name for band in bands[:1]],
                stats=[
                    ("本月预约", f"{profile_stats.month_bookings} 条", fmt_hours(profile_stats.month_minutes)),
                    ("累计时长", fmt_hours(profile_stats.total_minutes), f"通过 {profile_stats.approved_bookings} 次"),
                    ("常驻场景", profile_stats.favourite_scene, "按累计时长"),
                    ("待审核", f"{profile_stats.pending_bookings} 条", "等待管理员"),
                ],
                upcoming=profile_stats.upcoming,
                created_label="2026-10-01",
                generated_label="",
                total_minutes=profile_stats.total_minutes,
            )
        )
        save_png_image(profile, "preview_profile.png")

        pending_views = [booking_view(item) for item in pending_bookings(session, limit=5)]
        review = render_review_card(
            ReviewCardData(
                booking=pending_views[0],
                pending_total=len(pending_views),
                generated_label="",
            )
        )
        save_png_image(review, "preview_review.png")

        listing = render_booking_list(
            BookingListData(
                title="待审核预约",
                subtitle=f"共 {len(pending_views)} 条待审核，审核结果会自动通知申请人",
                owner_label="店长",
                bookings=pending_views,
                empty_hint="当前没有待审核预约",
                notes=["/通过 编号 或 /驳回 编号 原因"],
                show_owner=True,
            )
        )
        save_png_image(listing, "preview_review_list.png")

        my_views = [booking_view(item) for item in recent_bookings(session, limit=5)]
        my_list = render_booking_list(
            BookingListData(
                title="最近预约",
                subtitle="全场景｜按提交时间",
                owner_label="店长",
                bookings=my_views,
                empty_hint="暂无预约",
                notes=["管理员后台视图示例"],
                show_owner=True,
            )
        )
        save_png_image(my_list, "preview_booking_list.png")

        month = build_calendar_data(
            session,
            view="month",
            anchor=today,
            viewer=admin,
            can_view_details=True,
        )
        save_png_image(render_calendar(month), "preview_calendar_month.png")

        week = build_calendar_data(
            session,
            view="week",
            anchor=today,
            viewer=admin,
            can_view_details=True,
        )
        save_png_image(render_calendar(week), "preview_calendar_week.png")

        day = build_calendar_data(
            session,
            view="day",
            anchor=today + timedelta(days=1),
            viewer=admin,
            can_view_details=True,
        )
        save_png_image(render_calendar(day), "preview_calendar_day.png")

        agenda = build_calendar_data(
            session,
            view="agenda",
            anchor=today,
            viewer=admin,
            can_view_details=True,
        )
        save_png_image(render_calendar(agenda), "preview_calendar_agenda.png")

        month_first = today.replace(day=1)
        if month_first.month == 12:
            next_month = month_first.replace(year=month_first.year + 1, month=1)
        else:
            next_month = month_first.replace(month=month_first.month + 1)
        stats = studio_stats(
            session,
            datetime.combine(month_first, time(0), tzinfo=tz),
            datetime.combine(next_month, time(0), tzinfo=tz),
        )
        stats_image = render_stats_card(
            StatsCardData(
                title="工作室运营统计",
                range_label=f"{month_first:%Y-%m-%d} ~ {next_month - timedelta(days=1):%Y-%m-%d}",
                tiles=[
                    ("预约总数", str(stats.total_bookings), f"通过 {stats.approved}"),
                    ("生效时长", fmt_hours(stats.minutes), f"{stats.active_users} 位用户"),
                    ("预估收入", f"¥{stats.revenue}", "按小时价估算"),
                    ("场地占用", f"{stats.occupancy * 100:.1f}%", f"待审 {stats.pending}"),
                ],
                scene_stats=stats.scene_stats,
                top_bands=stats.top_bands,
                occupancy=stats.occupancy,
                generated_label="",
            )
        )
        save_png_image(stats_image, "preview_stats.png")

    print(f"示例图片已输出到 {settings.image_dir}")


def save_png_image(data: bytes, name: str) -> None:
    directory = get_settings().image_dir
    directory.mkdir(parents=True, exist_ok=True)
    Image.open(io.BytesIO(data)).save(directory / name)


if __name__ == "__main__":
    main()
