"""日历数据组装（供图片渲染使用，与渲染实现解耦）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from sqlalchemy.orm import Session

from berrystudio.config import get_settings
from berrystudio.db.models import Booking, BookingStatus, Scene, User
from berrystudio.services.dto import SceneView, scene_view
from berrystudio.services.errors import BerryError
from berrystudio.services.scenes import list_scenes
from berrystudio.services.bookings import bookings_between
from berrystudio.utils.format import month_bounds, week_bounds

VIEW_ALIASES = {
    "日": "day",
    "天": "day",
    "day": "day",
    "日视图": "day",
    "周": "week",
    "星期": "week",
    "week": "week",
    "周视图": "week",
    "月": "month",
    "month": "month",
    "月视图": "month",
    "列表": "agenda",
    "日程": "agenda",
    "agenda": "agenda",
    "list": "agenda",
}

VIEW_LABELS = {"day": "日视图", "week": "周视图", "month": "月视图", "agenda": "日程列表"}


@dataclass
class CalendarEntry:
    code: str
    scene_id: int
    scene_name: str
    scene_color: str
    start: datetime
    end: datetime
    status: str
    label: str
    is_mine: bool
    is_free_hint: bool = False


@dataclass
class CalendarStat:
    label: str
    value: str
    hint: str = ""


@dataclass
class CalendarData:
    view: str
    view_label: str
    anchor: date
    start: datetime
    end: datetime
    entries: list[CalendarEntry]
    scenes: list[SceneView]
    stats: list[CalendarStat]
    owner_label: str
    can_view_details: bool
    days: list[date] = field(default_factory=list)
    range_label: str = ""
    note: str = ""


def normalize_view(value: str) -> str:
    key = (value or "").strip().lower()
    if key in VIEW_ALIASES:
        return VIEW_ALIASES[key]
    raise BerryError("视图只支持：日 / 周 / 月 / 列表")


def _range_for(view: str, anchor: date) -> tuple[datetime, datetime, list[date], str]:
    tz = get_settings().tz

    if view == "day":
        start_day = anchor
        end_day = anchor + timedelta(days=1)
        label = f"{anchor:%Y-%m-%d} 周{'一二三四五六日'[anchor.weekday()]}"
        days = [anchor]
    elif view == "week":
        start_day, end_day = week_bounds(anchor)
        label = f"{start_day:%m-%d} ~ {end_day - timedelta(days=1):%m-%d}"
        days = [start_day + timedelta(days=i) for i in range(7)]
    elif view == "month":
        first, next_month = month_bounds(anchor)
        start_day = first - timedelta(days=first.weekday())
        end_day = start_day + timedelta(days=42)
        label = f"{first.year} 年 {first.month} 月"
        days = [start_day + timedelta(days=i) for i in range(42)]
    else:  # agenda
        start_day = anchor
        end_day = anchor + timedelta(days=14)
        label = f"{anchor:%m-%d} 起 14 天"
        days = [start_day + timedelta(days=i) for i in range(14)]

    start = datetime.combine(start_day, time(0), tzinfo=tz)
    end = datetime.combine(end_day, time(0), tzinfo=tz)
    return start, end, days, label


def build_calendar_data(
    session: Session,
    *,
    view: str,
    anchor: date,
    scene: Scene | None = None,
    viewer: User | None = None,
    can_view_details: bool = False,
) -> CalendarData:
    view = normalize_view(view)
    start, end, days, range_label = _range_for(view, anchor)
    tz = get_settings().tz

    scenes = list_scenes(session, bookable_only=not can_view_details)
    scene_ids = [scene.id] if scene else [item.id for item in scenes]

    raw = bookings_between(
        session,
        start,
        end,
        scene_ids=scene_ids,
        statuses=(
            BookingStatus.APPROVED,
            BookingStatus.COMPLETED,
            BookingStatus.PENDING,
        ),
    )

    entries: list[CalendarEntry] = []
    for booking in raw:
        is_mine = viewer is not None and booking.user_id == viewer.id
        if booking.status == BookingStatus.PENDING and not (can_view_details or is_mine):
            # 别人的待审核预约不展示，避免泄露隐私
            continue
        if can_view_details:
            label = booking.band.name if booking.band else booking.user.name
        elif is_mine:
            label = "我的预约"
        else:
            label = "已占用"
        entries.append(
            CalendarEntry(
                code=booking.code,
                scene_id=booking.scene_id,
                scene_name=booking.scene.name,
                scene_color=booking.scene.color,
                start=booking.start_at.astimezone(tz),
                end=booking.end_at.astimezone(tz),
                status=booking.status,
                label=label,
                is_mine=is_mine,
            )
        )

    entries.sort(key=lambda item: item.start)
    total_minutes = sum(
        int((entry.end - entry.start).total_seconds() // 60) for entry in entries
    )
    my_entries = sum(1 for entry in entries if entry.is_mine)
    pending_count = sum(
        1 for entry in entries if entry.status == BookingStatus.PENDING
    )

    stats: list[CalendarStat] = [
        CalendarStat("区间预约", f"{len(entries)} 条", f"累计 {total_minutes / 60:.1f} 小时"),
        CalendarStat("我的预约", f"{my_entries} 条", viewer.name if viewer else "未绑定"),
    ]
    if can_view_details:
        stats.append(CalendarStat("待审核", f"{pending_count} 条", "需要处理"))
    else:
        stats.append(CalendarStat("场地", f"{len(scenes)} 个", "可预约"))
    stats.append(
        CalendarStat("视图", VIEW_LABELS[view], range_label)
    )

    return CalendarData(
        view=view,
        view_label=VIEW_LABELS[view],
        anchor=anchor,
        start=start,
        end=end,
        entries=entries,
        scenes=[scene_view(item) for item in (scenes if scene is None else [scene])],
        stats=stats,
        owner_label=viewer.name if viewer else "访客",
        can_view_details=can_view_details,
        days=days,
        range_label=range_label,
        note="发送 /预约 场景 日期 时段 提交新的预约申请" if view != "day" else "",
    )


def entry_minutes(entry: CalendarEntry) -> int:
    return int((entry.end - entry.start).total_seconds() // 60)
