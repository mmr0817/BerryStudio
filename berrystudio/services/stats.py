"""统计服务：个人资料卡与工作室运营统计。"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from berrystudio.config import get_settings
from berrystudio.db.models import (
    Band,
    BandMember,
    Booking,
    BookingStatus,
    Scene,
    User,
)
from berrystudio.services.dto import BookingView, booking_view
from berrystudio.utils.format import fmt_hours


@dataclass
class UserStats:
    total_bookings: int = 0
    approved_bookings: int = 0
    pending_bookings: int = 0
    month_bookings: int = 0
    month_minutes: int = 0
    total_minutes: int = 0
    favourite_scene: str = "-"
    upcoming: list[BookingView] = field(default_factory=list)
    bands: list[str] = field(default_factory=list)


@dataclass
class SceneStat:
    name: str
    color: str
    bookings: int
    minutes: int
    revenue: int


@dataclass
class StudioStats:
    start: datetime
    end: datetime
    total_bookings: int = 0
    approved: int = 0
    pending: int = 0
    rejected: int = 0
    cancelled: int = 0
    minutes: int = 0
    revenue: int = 0
    occupancy: float = 0.0
    scene_stats: list[SceneStat] = field(default_factory=list)
    top_bands: list[tuple[str, int]] = field(default_factory=list)
    active_users: int = 0


def _month_start(day: date) -> date:
    return day.replace(day=1)


def user_stats(
    session: Session,
    user: User,
    *,
    now: datetime | None = None,
) -> UserStats:
    tz = get_settings().tz
    now = now or datetime.now(tz)
    if now.tzinfo is None:
        now = now.replace(tzinfo=tz)
    first_day = _month_start(now.date())
    month_start = datetime.combine(first_day, time(0), tzinfo=tz)
    if first_day.month == 12:
        next_month = date(first_day.year + 1, 1, 1)
    else:
        next_month = date(first_day.year, first_day.month + 1, 1)
    month_end = datetime.combine(next_month, time(0), tzinfo=tz)

    bookings = list(
        session.scalars(
            select(Booking)
            .where(Booking.user_id == user.id)
            .order_by(Booking.start_at.desc())
        )
    )
    stats = UserStats(total_bookings=len(bookings))

    scene_counter: Counter[str] = Counter()
    band_names: list[str] = []
    for booking in bookings:
        duration = int((booking.end_at - booking.start_at).total_seconds() // 60)
        if booking.status in {BookingStatus.APPROVED, BookingStatus.COMPLETED}:
            stats.approved_bookings += 1
            stats.total_minutes += duration
            scene_counter[booking.scene.name] += duration
            if booking.band and booking.band.name not in band_names:
                band_names.append(booking.band.name)
        if booking.status == BookingStatus.PENDING:
            stats.pending_bookings += 1
        start_local = booking.start_at.astimezone(tz)
        if month_start <= start_local < month_end and booking.status in {
            BookingStatus.APPROVED,
            BookingStatus.COMPLETED,
            BookingStatus.PENDING,
        }:
            stats.month_bookings += 1
            if booking.status != BookingStatus.PENDING:
                stats.month_minutes += duration

    if scene_counter:
        stats.favourite_scene = scene_counter.most_common(1)[0][0]

    upcoming = [
        booking
        for booking in bookings
        if booking.status in BookingStatus.OCCUPYING
        and booking.end_at.astimezone(tz) >= now
    ]
    upcoming.sort(key=lambda b: b.start_at)
    stats.upcoming = [booking_view(booking) for booking in upcoming[:5]]

    bands = session.scalars(
        select(Band.name)
        .join(BandMember, BandMember.band_id == Band.id)
        .where(BandMember.user_id == user.id)
    )
    stats.bands = list(dict.fromkeys(bands))
    return stats


def studio_stats(
    session: Session,
    start: datetime,
    end: datetime,
    *,
    scene_ids: list[int] | None = None,
) -> StudioStats:
    tz = get_settings().tz
    if start.tzinfo is None:
        start = start.replace(tzinfo=tz)
    if end.tzinfo is None:
        end = end.replace(tzinfo=tz)
    start_utc = start.astimezone(timezone.utc)
    end_utc = end.astimezone(timezone.utc)

    stmt = select(Booking).where(
        Booking.start_at < end_utc, Booking.end_at > start_utc
    )
    if scene_ids:
        stmt = stmt.where(Booking.scene_id.in_(scene_ids))
    bookings = list(session.scalars(stmt))

    stats = StudioStats(start=start, end=end, total_bookings=len(bookings))
    per_scene: dict[int, SceneStat] = {}
    band_counter: Counter[str] = Counter()
    user_ids: set[int] = set()

    for booking in bookings:
        duration = int((booking.end_at - booking.start_at).total_seconds() // 60)
        scene_stat = per_scene.get(booking.scene_id)
        if scene_stat is None:
            scene_stat = SceneStat(
                name=booking.scene.name, color=booking.scene.color, bookings=0, minutes=0, revenue=0
            )
            per_scene[booking.scene_id] = scene_stat
        if booking.status == BookingStatus.APPROVED:
            stats.approved += 1
            stats.minutes += duration
            stats.revenue += booking.price_estimate
            scene_stat.bookings += 1
            scene_stat.minutes += duration
            scene_stat.revenue += booking.price_estimate
            user_ids.add(booking.user_id)
            if booking.band:
                band_counter[booking.band.name] += 1
        elif booking.status == BookingStatus.PENDING:
            stats.pending += 1
        elif booking.status == BookingStatus.REJECTED:
            stats.rejected += 1
        elif booking.status == BookingStatus.CANCELLED:
            stats.cancelled += 1

    stats.scene_stats = sorted(
        (item for item in per_scene.values() if item.bookings > 0),
        key=lambda item: item.minutes,
        reverse=True,
    )
    stats.top_bands = band_counter.most_common(5)
    stats.active_users = len(user_ids)

    scenes = list(
        session.scalars(
            select(Scene).where(Scene.is_bookable.is_(True))
            if not scene_ids
            else select(Scene).where(Scene.id.in_(scene_ids))
        )
    )
    days = max(1, (end.date() - start.date()).days + 1)
    available = sum(
        max(0, (scene.close_hour - scene.open_hour)) * 60 * days for scene in scenes
    )
    if available:
        stats.occupancy = min(1.0, stats.minutes / available)
    return stats


def user_rank_text(stats: UserStats) -> str:
    """根据累计时长给出一个轻量的“乐手等级”文案。"""
    hours = stats.total_minutes / 60
    if hours >= 100:
        return "传奇制作人"
    if hours >= 50:
        return "常驻乐手"
    if hours >= 20:
        return "成熟乐手"
    if hours >= 5:
        return "排练新人"
    return "初来乍到"


def stats_summary_lines(stats: StudioStats, tz) -> list[str]:
    return [
        f"区间：{stats.start:%Y-%m-%d} ~ {stats.end - timedelta(days=1):%Y-%m-%d}",
        f"预约总数：{stats.total_bookings}（通过 {stats.approved} / 待审 {stats.pending} / 驳回 {stats.rejected} / 取消 {stats.cancelled}）",
        f"生效时长：{fmt_hours(stats.minutes)}，预估收入：¥{stats.revenue}",
        f"场地占用率：{stats.occupancy * 100:.1f}%",
        f"活跃用户：{stats.active_users}",
    ]
