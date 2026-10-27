from __future__ import annotations

from datetime import datetime, time, timedelta

import pytest
from sqlalchemy import select

from berrystudio.db.models import BookingStatus, Scene
from berrystudio.db.session import session_scope
from berrystudio.services.bookings import (
    approve_booking,
    archive_past_bookings,
    cancel_booking,
    create_booking,
    free_slots,
    get_booking_by_code,
    reject_booking,
    user_bookings,
)
from berrystudio.services.dto import booking_view
from berrystudio.services.errors import BerryError, ConflictError
from berrystudio.services.scenes import create_scene
from berrystudio.services.users import get_or_create_user
from tests.conftest import load_band, load_scene, load_user


def test_booking_lifecycle(db, tz):
    day = (datetime.now(tz) + timedelta(days=2)).date()
    start = datetime.combine(day, time(19, 0), tzinfo=tz)
    end = datetime.combine(day, time(21, 0), tzinfo=tz)

    with session_scope() as session:
        user = get_or_create_user(session, "10001", display_name="小明")
        scene = session.scalar(select(Scene).where(Scene.code == "REH-A"))
        booking = create_booking(session, user, scene, start, end)
        code = booking.code
        assert booking.status == BookingStatus.PENDING
        assert code.startswith("B")
        # 数据库存 UTC，展示时转回本地时区
        assert booking.start_at.astimezone(tz).hour == 19
        assert booking.price_estimate == 160  # 2h × ¥80

        # 同一时段不能重复预约
        with pytest.raises(ConflictError):
            create_booking(session, user, scene, start, end)

        # 相邻时段可以预约
        later = create_booking(
            session,
            user,
            scene,
            end,
            end + timedelta(hours=1),
        )
        assert later.code != code

        view = booking_view(booking)
        assert view.duration_minutes == 120
        assert view.status_label == "待审核"
        assert view.scene_name == "排练室·A"

    # 管理员审核通过
    with session_scope() as session:
        booking = get_booking_by_code(session, code)
        admin = get_or_create_user(session, "90001", display_name="店长")
        approve_booking(session, booking, admin, note="已确认")
        assert booking.status == BookingStatus.APPROVED
        assert booking.reviewed_by_id == admin.id
        assert booking.review_note == "已确认"

    # 审核通过后不能再取消别人的预约
    with session_scope() as session:
        booking = get_booking_by_code(session, code)
        other = get_or_create_user(session, "10002", display_name="小红")
        with pytest.raises(BerryError):
            cancel_booking(session, booking, other)

    # 本人可以在开始前取消
    with session_scope() as session:
        booking = get_booking_by_code(session, code)
        owner = load_user(session, booking.user_id)
        cancel_booking(session, booking, owner, reason="临时有事")
        assert booking.status == BookingStatus.CANCELLED


def test_conflict_recheck_on_approve(db, tz):
    day = (datetime.now(tz) + timedelta(days=3)).date()
    with session_scope() as session:
        user = get_or_create_user(session, "10001", display_name="小明")
        scene = session.scalar(select(Scene).where(Scene.code == "REH-A"))
        first = create_booking(
            session,
            user,
            scene,
            datetime.combine(day, time(10, 0), tzinfo=tz),
            datetime.combine(day, time(12, 0), tzinfo=tz),
        )
        second = create_booking(
            session,
            user,
            scene,
            datetime.combine(day, time(12, 0), tzinfo=tz),
            datetime.combine(day, time(14, 0), tzinfo=tz),
        )
        admin = get_or_create_user(session, "90001", display_name="店长")

        # 人为制造冲突：把第一条延长到 13:00
        first.end_at = datetime.combine(day, time(13, 0), tzinfo=tz).astimezone(
            first.end_at.tzinfo
        )
        session.flush()

        with pytest.raises(ConflictError):
            approve_booking(session, second, admin)
        assert second.status == BookingStatus.PENDING


def test_reject_frees_slot(db, tz):
    day = (datetime.now(tz) + timedelta(days=4)).date()
    start = datetime.combine(day, time(15, 0), tzinfo=tz)
    end = datetime.combine(day, time(17, 0), tzinfo=tz)
    with session_scope() as session:
        user = get_or_create_user(session, "10001", display_name="小明")
        scene = session.scalar(select(Scene).where(Scene.code == "REH-A"))
        booking = create_booking(session, user, scene, start, end)
        admin = get_or_create_user(session, "90001", display_name="店长")
        reject_booking(session, booking, admin, reason="设备维护")
        assert booking.status == BookingStatus.REJECTED
        replacement = create_booking(session, user, scene, start, end)
        assert replacement.status == BookingStatus.PENDING


def test_validation_rules(db, tz):
    day = (datetime.now(tz) + timedelta(days=2)).date()
    with session_scope() as session:
        user = get_or_create_user(session, "10001", display_name="小明")
        scene = session.scalar(select(Scene).where(Scene.code == "REH-A"))

        with pytest.raises(BerryError):
            create_booking(
                session,
                user,
                scene,
                datetime.combine(day, time(19, 10), tzinfo=tz),
                datetime.combine(day, time(21, 0), tzinfo=tz),
            )
        with pytest.raises(BerryError):
            create_booking(
                session,
                user,
                scene,
                datetime.combine(day, time(6, 0), tzinfo=tz),
                datetime.combine(day, time(8, 0), tzinfo=tz),
            )
        with pytest.raises(BerryError):
            create_booking(
                session,
                user,
                scene,
                datetime.combine(day, time(19, 0), tzinfo=tz),
                datetime.combine(day, time(21, 0), tzinfo=tz),
                attendees=99,
            )
        # 过去的时间
        yesterday = day - timedelta(days=2)
        with pytest.raises(BerryError):
            create_booking(
                session,
                user,
                scene,
                datetime.combine(yesterday, time(19, 0), tzinfo=tz),
                datetime.combine(yesterday, time(21, 0), tzinfo=tz),
            )


def test_closed_scene_cannot_be_booked(db, sample, tz):
    day = sample["day"]
    with session_scope() as session:
        user = load_user(session, sample["user_id"])
        scene = load_scene(session, sample["scene_id"])
        scene.is_bookable = False
        session.flush()
        with pytest.raises(BerryError):
            create_booking(
                session,
                user,
                scene,
                datetime.combine(day, time(9, 0), tzinfo=tz),
                datetime.combine(day, time(11, 0), tzinfo=tz),
            )


def test_free_slots_and_archive(db, sample, tz):
    with session_scope() as session:
        user = load_user(session, sample["user_id"])
        scene = load_scene(session, sample["scene_id"])
        booking = create_booking(
            session, user, scene, sample["start"], sample["end"]
        )
        admin = get_or_create_user(session, "90001", display_name="店长")
        approve_booking(session, booking, admin)
        day = sample["day"]
        slots = free_slots(session, scene, day)
        # 19:00-21:00 已被占用
        assert all(
            not (start.hour <= 19 and end.hour >= 21) for start, end in slots
        )
        assert any(start.hour == 21 for start, _ in slots)

        archived = archive_past_bookings(
            session,
            now=datetime.combine(day, time(23, 0), tzinfo=tz),
        )
        assert archived == 1
        assert booking.status == BookingStatus.COMPLETED

    with session_scope() as session:
        user = load_user(session, sample["user_id"])
        bookings = user_bookings(session, user)
        assert bookings and bookings[0].status == BookingStatus.COMPLETED


def test_midnight_close_scene(db, tz):
    day = (datetime.now(tz) + timedelta(days=5)).date()
    with session_scope() as session:
        user = get_or_create_user(session, "10001", display_name="小明")
        scene = create_scene(
            session,
            code="NIGHT",
            name="夜场排练室",
            kind="rehearsal",
            open_hour=18,
            close_hour=24,
            min_minutes=60,
            max_minutes=240,
            slot_minutes=30,
            hourly_price=80,
        )
        booking = create_booking(
            session,
            user,
            scene,
            datetime.combine(day, time(23, 0), tzinfo=tz),
            datetime.combine(day + timedelta(days=1), time(0), tzinfo=tz),
        )
        assert booking.end_at.astimezone(tz).hour == 0
        assert booking.end_at.astimezone(tz).day == (day + timedelta(days=1)).day


def test_band_membership_required(db, sample, tz):
    with session_scope() as session:
        user = load_user(session, sample["user_id"])
        other = get_or_create_user(session, "10002", display_name="小红")
        band = load_band(session, sample["band_id"])
        scene = load_scene(session, sample["scene_id"])
        with pytest.raises(BerryError):
            create_booking(
                session,
                other,
                scene,
                sample["start"],
                sample["end"],
                band=band,
            )
