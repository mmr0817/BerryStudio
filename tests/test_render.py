from __future__ import annotations

import struct
from datetime import timedelta

import pytest

from berrystudio.db.session import session_scope
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
from berrystudio.services.bookings import approve_booking, create_booking
from berrystudio.services.dto import booking_view
from berrystudio.services.schedule import build_calendar_data
from berrystudio.services.stats import studio_stats, user_rank_text, user_stats
from berrystudio.services.users import get_or_create_user
from berrystudio.utils.format import fmt_hours
from tests.conftest import load_scene, load_user


def _assert_png(data: bytes) -> None:
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    width, height = struct.unpack(">II", data[16:24])
    assert width >= 1000
    assert height >= 300
    assert len(data) > 10_000


def test_calendar_views(db, sample, tz):
    with session_scope() as session:
        user = load_user(session, sample["user_id"])
        scene = load_scene(session, sample["scene_id"])
        booking = create_booking(session, user, scene, sample["start"], sample["end"])
        admin = get_or_create_user(session, "90001", display_name="店长")
        approve_booking(session, booking, admin, note="已确认")

        pending = create_booking(
            session,
            user,
            scene,
            sample["start"].replace(hour=21),
            sample["start"].replace(hour=22),
        )
        assert pending.status == "pending"

        for view in ("day", "week", "month", "agenda"):
            data = build_calendar_data(
                session,
                view=view,
                anchor=sample["day"],
                scene=scene,
                viewer=user,
                can_view_details=True,
            )
            assert data.view == view
            assert data.entries
            _assert_png(render_calendar(data))

        empty = build_calendar_data(
            session,
            view="month",
            anchor=sample["day"].replace(day=1),
            scene=scene,
            viewer=user,
            can_view_details=False,
        )
        _assert_png(render_calendar(empty))


def test_profile_and_review_cards(db, sample):
    with session_scope() as session:
        user = load_user(session, sample["user_id"])
        scene = load_scene(session, sample["scene_id"])
        booking = create_booking(session, user, scene, sample["start"], sample["end"])
        stats = user_stats(session, user)
        view = booking_view(booking)
        profile = render_profile_card(
            ProfileCardData(
                owner_name=user.name,
                qq=user.qq,
                role_title="用户",
                rank=user_rank_text(stats),
                bands=["草莓汽水"],
                stats=[
                    ("本月预约", "1 条", "2h"),
                    ("累计时长", "2h", "通过 0 次"),
                    ("常驻场景", "排练室·A", "按累计时长"),
                    ("待审核", "1 条", "等待管理员"),
                ],
                upcoming=[view],
                created_label="2026-10-27",
                generated_label="",
                total_minutes=120,
            )
        )
        _assert_png(profile)

        review = render_review_card(
            ReviewCardData(booking=view, pending_total=3, generated_label="")
        )
        _assert_png(review)

        listing = render_booking_list(
            BookingListData(
                title="我的预约",
                subtitle="近 60 天｜1 条",
                owner_label=user.name,
                bookings=[view],
                empty_hint="发送 /预约 场景 日期 时段",
            )
        )
        _assert_png(listing)


def test_stats_card(db, sample):
    with session_scope() as session:
        user = load_user(session, sample["user_id"])
        scene = load_scene(session, sample["scene_id"])
        booking = create_booking(session, user, scene, sample["start"], sample["end"])
        admin = get_or_create_user(session, "90001", display_name="店长")
        approve_booking(session, booking, admin)
        stats = studio_stats(
            session,
            sample["start"].replace(hour=0),
            sample["start"].replace(hour=0) + timedelta(days=1),
        )
        image = render_stats_card(
            StatsCardData(
                title="工作室运营统计",
                range_label="2026-10-01 ~ 2026-10-31",
                tiles=[
                    ("预约总数", "1", "通过 1"),
                    ("生效时长", fmt_hours(stats.minutes), "1 位用户"),
                    ("预估收入", f"¥{stats.revenue}", "按小时价估算"),
                    ("场地占用", f"{stats.occupancy * 100:.1f}%", "待审 0"),
                ],
                scene_stats=stats.scene_stats,
                top_bands=stats.top_bands,
                occupancy=stats.occupancy,
                generated_label="",
            )
        )
        _assert_png(image)
