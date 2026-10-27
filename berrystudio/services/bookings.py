"""预约核心服务：创建（待审核）→ 管理员审核 → 生效 → 查询 / 取消。"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone, tzinfo
from math import ceil

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from berrystudio.config import get_settings
from berrystudio.db.models import (
    Band,
    BandMember,
    Booking,
    BookingLog,
    BookingStatus,
    Scene,
    User,
)
from berrystudio.db.session import write_lock
from berrystudio.services.dto import BookingView, booking_view
from berrystudio.services.errors import BerryError, ConflictError, NotFoundError
from berrystudio.services.users import ensure_active
from berrystudio.utils.format import fmt_range, status_label


def _localize(value: datetime, tz: tzinfo) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=tz)
    return value.astimezone(tz)


def _to_utc(value: datetime, tz: tzinfo) -> datetime:
    return _localize(value, tz).astimezone(timezone.utc)


def _ceil_to_slot(value: datetime, minutes: int) -> datetime:
    if minutes <= 0:
        return value
    discard = (value.minute % minutes) * 60 + value.second
    if discard == 0 and value.microsecond == 0:
        return value
    return value + timedelta(seconds=60 * minutes - discard if discard else 0) - timedelta(
        microseconds=value.microsecond
    )


def _next_code(session: Session, start_local: datetime) -> str:
    prefix = f"B{start_local:%y%m%d}"
    existing = set(
        session.scalars(select(Booking.code).where(Booking.code.like(f"{prefix}%")))
    )
    sequence = 1
    while f"{prefix}{sequence:03d}" in existing:
        sequence += 1
    return f"{prefix}{sequence:03d}"


def get_booking_by_code(session: Session, code: str) -> Booking:
    normalized = (code or "").strip().lstrip("#").upper()
    booking = session.scalar(select(Booking).where(Booking.code == normalized))
    if booking is None:
        raise NotFoundError(f"没有找到编号为 {normalized or code} 的预约")
    return booking


def find_conflict(
    session: Session,
    scene_id: int,
    start_utc: datetime,
    end_utc: datetime,
    *,
    exclude_id: int | None = None,
    statuses: tuple[str, ...] = BookingStatus.OCCUPYING,
) -> Booking | None:
    stmt = select(Booking).where(
        Booking.scene_id == scene_id,
        Booking.status.in_(statuses),
        Booking.start_at < end_utc,
        Booking.end_at > start_utc,
    )
    if exclude_id is not None:
        stmt = stmt.where(Booking.id != exclude_id)
    return session.scalar(stmt.limit(1))


def _check_alignment(value: datetime, slot_minutes: int, label: str) -> None:
    if slot_minutes <= 0:
        return
    if value.minute % slot_minutes != 0 or value.second or value.microsecond:
        raise BerryError(
            f"{label}需要按 {slot_minutes} 分钟对齐，例如 "
            f"{value.hour:02d}:{(value.minute // slot_minutes) * slot_minutes:02d}"
        )


def create_booking(
    session: Session,
    user: User,
    scene: Scene,
    start_local: datetime,
    end_local: datetime,
    *,
    band: Band | None = None,
    title: str = "",
    note: str = "",
    attendees: int = 1,
    group_id: str = "",
    source: str = "bot",
) -> Booking:
    """创建一笔待审核预约（不会立即生效，需管理员审核）。"""
    settings = get_settings()
    tz = settings.tz
    start = _localize(start_local, tz)
    end = _localize(end_local, tz)
    now = datetime.now(tz)

    ensure_active(user)
    if not scene.is_bookable:
        raise BerryError(f"「{scene.name}」当前暂停预约")
    if band is not None:
        membership = session.scalar(
            select(BandMember).where(
                BandMember.band_id == band.id,
                BandMember.user_id == user.id,
            )
        )
        if membership is None:
            raise BerryError(f"你不在「{band.name}」里，无法以该乐队名义预约")
    if end <= start:
        raise BerryError("结束时间必须晚于开始时间")
    midnight_close = (
        end.date() == start.date() + timedelta(days=1)
        and end.time() == time(0)
    )
    if start.date() != end.date() and not midnight_close:
        raise BerryError("暂不支持跨天预约，请拆成两段")

    duration_minutes = int((end - start).total_seconds() // 60)
    if duration_minutes < scene.min_minutes:
        raise BerryError(f"「{scene.name}」最短需要预约 {scene.min_minutes} 分钟")
    if duration_minutes > scene.max_minutes:
        raise BerryError(f"「{scene.name}」单次最多预约 {scene.max_minutes} 分钟")

    _check_alignment(start, scene.slot_minutes, "开始时间")
    _check_alignment(end, scene.slot_minutes, "结束时间")

    close_dt = (
        datetime.combine(start.date(), time(0), tzinfo=tz) + timedelta(days=1)
        if scene.close_hour >= 24
        else datetime.combine(start.date(), time(scene.close_hour), tzinfo=tz)
    )
    open_dt = datetime.combine(start.date(), time(scene.open_hour), tzinfo=tz)
    if start < open_dt or end > close_dt:
        raise BerryError(
            f"「{scene.name}」开放时间为 {scene.open_hour:02d}:00-{scene.close_hour:02d}:00"
        )
    if start < now + timedelta(minutes=settings.min_lead_minutes):
        raise BerryError(
            f"最早只能预约 {settings.min_lead_minutes} 分钟之后的时段，"
            f"当前时间 {now:%m-%d %H:%M}"
        )
    if (start.date() - now.date()).days > settings.max_advance_days:
        raise BerryError(f"最多只能提前 {settings.max_advance_days} 天预约")

    attendees = int(attendees or 1)
    if attendees < 1:
        raise BerryError("人数至少为 1")
    if attendees > scene.capacity:
        raise BerryError(f"「{scene.name}」最多容纳 {scene.capacity} 人")

    pending_count = session.scalar(
        select(func.count(Booking.id)).where(
            Booking.user_id == user.id, Booking.status == BookingStatus.PENDING
        )
    )
    if int(pending_count or 0) >= settings.max_pending_per_user:
        raise BerryError(
            f"你还有 {pending_count} 条待审核预约，请等待管理员处理后再提交新的预约"
        )

    start_utc = _to_utc(start, tz)
    end_utc = _to_utc(end, tz)

    with write_lock():
        conflict = find_conflict(session, scene.id, start_utc, end_utc)
        if conflict is not None:
            conflict_local = _localize(conflict.start_at, tz)
            raise ConflictError(
                f"该时段已被占用（{conflict.code} · "
                f"{conflict_local:%m-%d %H:%M} 起，状态：{status_label(conflict.status)}），"
                "发送 /日历 查看空闲时段"
            )

        booking = Booking(
            code=_next_code(session, start),
            user_id=user.id,
            band_id=band.id if band else None,
            scene_id=scene.id,
            start_at=start_utc,
            end_at=end_utc,
            status=BookingStatus.PENDING,
            title=(title or "").strip()[:64],
            note=(note or "").strip()[:255],
            attendees=attendees,
            hourly_price=scene.hourly_price,
            price_estimate=ceil(duration_minutes / 60) * scene.hourly_price,
            group_id=str(group_id) if group_id else "",
            source=source,
        )
        session.add(booking)
        session.flush()
        session.add(
            BookingLog(
                booking_id=booking.id,
                from_status="",
                to_status=BookingStatus.PENDING,
                actor_id=user.id,
                note="用户提交预约",
            )
        )
        session.flush()
        return booking


def approve_booking(
    session: Session,
    booking: Booking,
    admin: User | None,
    *,
    note: str = "",
) -> Booking:
    """审核通过：再次校验冲突后生效。"""
    settings = get_settings()
    tz = settings.tz
    if booking.status != BookingStatus.PENDING:
        raise BerryError(
            f"预约 {booking.code} 当前状态为「{status_label(booking.status)}」，无法审核",
            code="invalid_state",
        )
    if _localize(booking.end_at, tz) <= datetime.now(tz):
        raise BerryError(
            f"预约 {booking.code} 的时间已经过去，无法通过，请使用 /驳回"
        )

    with write_lock():
        conflict = find_conflict(
            session,
            booking.scene_id,
            booking.start_at,
            booking.end_at,
            exclude_id=booking.id,
        )
        if conflict is not None:
            conflict_local = _localize(conflict.start_at, tz)
            raise ConflictError(
                f"预约 {booking.code} 与 {conflict.code} 时段冲突"
                f"（{conflict_local:%m-%d %H:%M}），请先处理冲突预约"
            )

        booking.status = BookingStatus.APPROVED
        booking.reviewed_by_id = admin.id if admin else None
        booking.reviewed_at = datetime.now(timezone.utc)
        booking.review_note = (note or "").strip()[:255]
        session.add(
            BookingLog(
                booking_id=booking.id,
                from_status=BookingStatus.PENDING,
                to_status=BookingStatus.APPROVED,
                actor_id=admin.id if admin else None,
                note=booking.review_note,
            )
        )
        session.flush()
        return booking


def reject_booking(
    session: Session,
    booking: Booking,
    admin: User | None,
    *,
    reason: str = "",
) -> Booking:
    if booking.status != BookingStatus.PENDING:
        raise BerryError(
            f"预约 {booking.code} 当前状态为「{status_label(booking.status)}」，无法审核",
            code="invalid_state",
        )
    booking.status = BookingStatus.REJECTED
    booking.reviewed_by_id = admin.id if admin else None
    booking.reviewed_at = datetime.now(timezone.utc)
    booking.review_note = (reason or "").strip()[:255]
    session.add(
        BookingLog(
            booking_id=booking.id,
            from_status=BookingStatus.PENDING,
            to_status=BookingStatus.REJECTED,
            actor_id=admin.id if admin else None,
            note=booking.review_note,
        )
    )
    session.flush()
    return booking


def cancel_booking(
    session: Session,
    booking: Booking,
    actor: User | None,
    *,
    reason: str = "",
    by_admin: bool = False,
) -> Booking:
    if booking.status not in BookingStatus.CANCELABLE:
        raise BerryError(
            f"预约 {booking.code} 当前状态为「{status_label(booking.status)}」，无法取消",
            code="invalid_state",
        )
    if not by_admin and (actor is None or booking.user_id != actor.id):
        raise BerryError("只能取消自己的预约", code="permission_denied")
    tz = get_settings().tz
    if _localize(booking.start_at, tz) <= datetime.now(tz):
        raise BerryError("该预约已经开始，无法取消")

    previous = booking.status
    booking.status = BookingStatus.CANCELLED
    booking.cancelled_at = datetime.now(timezone.utc)
    booking.cancelled_by_id = actor.id if actor else None
    if reason:
        booking.review_note = reason.strip()[:255]
    session.add(
        BookingLog(
            booking_id=booking.id,
            from_status=previous,
            to_status=BookingStatus.CANCELLED,
            actor_id=actor.id if actor else None,
            note=reason[:255],
        )
    )
    session.flush()
    return booking


def pending_bookings(session: Session, *, limit: int = 20) -> list[Booking]:
    return list(
        session.scalars(
            select(Booking)
            .where(Booking.status == BookingStatus.PENDING)
            .order_by(Booking.start_at)
            .limit(limit)
        )
    )


def recent_bookings(
    session: Session,
    *,
    statuses: tuple[str, ...] | None = None,
    limit: int = 12,
) -> list[Booking]:
    stmt = select(Booking).order_by(Booking.created_at.desc()).limit(limit)
    if statuses:
        stmt = stmt.where(Booking.status.in_(statuses))
    return list(session.scalars(stmt))


def pending_count(session: Session) -> int:
    return int(
        session.scalar(
            select(func.count(Booking.id)).where(
                Booking.status == BookingStatus.PENDING
            )
        )
        or 0
    )


def user_bookings(
    session: Session,
    user: User,
    *,
    statuses: tuple[str, ...] | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 20,
    newest_first: bool = True,
) -> list[Booking]:
    tz = get_settings().tz
    stmt = select(Booking).where(Booking.user_id == user.id)
    if statuses:
        stmt = stmt.where(Booking.status.in_(statuses))
    if start is not None:
        stmt = stmt.where(Booking.end_at >= _to_utc(start, tz))
    if end is not None:
        stmt = stmt.where(Booking.start_at < _to_utc(end, tz))
    order = Booking.start_at.desc() if newest_first else Booking.start_at
    return list(session.scalars(stmt.order_by(order).limit(limit)))


def bookings_between(
    session: Session,
    start: datetime,
    end: datetime,
    *,
    scene_ids: list[int] | None = None,
    statuses: tuple[str, ...] = (BookingStatus.APPROVED, BookingStatus.PENDING),
    limit: int = 500,
) -> list[Booking]:
    tz = get_settings().tz
    stmt = (
        select(Booking)
        .where(
            Booking.status.in_(statuses),
            Booking.start_at < _to_utc(end, tz),
            Booking.end_at > _to_utc(start, tz),
        )
        .order_by(Booking.start_at)
        .limit(limit)
    )
    if scene_ids:
        stmt = stmt.where(Booking.scene_id.in_(scene_ids))
    return list(session.scalars(stmt))


def free_slots(
    session: Session,
    scene: Scene,
    day: date,
    *,
    ignore_min_duration: bool = True,
) -> list[tuple[datetime, datetime]]:
    """返回某天该场景的空闲时间段（本地时区 aware）。"""
    tz = get_settings().tz
    now = datetime.now(tz)

    open_dt = datetime.combine(day, time(scene.open_hour), tzinfo=tz)
    if scene.close_hour >= 24:
        close_dt = datetime.combine(day, time(0), tzinfo=tz) + timedelta(days=1)
    else:
        close_dt = datetime.combine(day, time(scene.close_hour), tzinfo=tz)
    if close_dt <= now:
        return []
    if open_dt < now:
        open_dt = min(
            _ceil_to_slot(now, scene.slot_minutes) + timedelta(minutes=scene.slot_minutes),
            close_dt,
        )

    bookings = bookings_between(
        session,
        open_dt,
        close_dt,
        scene_ids=[scene.id],
    )
    cursor = open_dt
    gaps: list[tuple[datetime, datetime]] = []
    for booking in bookings:
        start = _localize(booking.start_at, tz)
        end = _localize(booking.end_at, tz)
        if start > cursor:
            gaps.append((cursor, min(start, close_dt)))
        cursor = max(cursor, end)
        if cursor >= close_dt:
            break
    if cursor < close_dt:
        gaps.append((cursor, close_dt))

    minimum = scene.slot_minutes if ignore_min_duration else scene.min_minutes
    return [
        (start, end)
        for start, end in gaps
        if int((end - start).total_seconds() // 60) >= minimum
    ]


def archive_past_bookings(
    session: Session, *, now: datetime | None = None
) -> int:
    """把已结束的“已通过”预约标记为已完成（可由定时任务或 CLI 调用）。"""
    now_utc = now or datetime.now(timezone.utc)
    stmt = select(Booking).where(
        Booking.status == BookingStatus.APPROVED, Booking.end_at < now_utc
    )
    bookings = list(session.scalars(stmt))
    for booking in bookings:
        booking.status = BookingStatus.COMPLETED
        session.add(
            BookingLog(
                booking_id=booking.id,
                from_status=BookingStatus.APPROVED,
                to_status=BookingStatus.COMPLETED,
                note="系统自动归档",
            )
        )
    session.flush()
    return len(bookings)


def booking_view_for(booking: Booking) -> BookingView:
    return booking_view(booking)


def describe(booking: Booking, tz: tzinfo | None = None) -> str:
    tz = tz or get_settings().tz
    return (
        f"{booking.code}｜{booking.scene.name}｜"
        f"{fmt_range(booking.start_at, booking.end_at, tz)}｜"
        f"{status_label(booking.status)}"
    )


def overlap_minutes(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> int:
    start = max(a_start, b_start)
    end = min(a_end, b_end)
    return max(0, int((end - start).total_seconds() // 60))
