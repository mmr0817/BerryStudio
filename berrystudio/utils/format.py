"""展示层格式化工具。"""

from __future__ import annotations

from datetime import date, datetime, timedelta, tzinfo

from berrystudio.db.models import BookingStatus, SceneKind, UserRole, UserStatus

WEEKDAY_CN = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def to_local(dt: datetime, tz: tzinfo) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


def fmt_date(value: date, *, with_year: bool = False, with_weekday: bool = False) -> str:
    text = f"{value.year}-{value.month:02d}-{value.day:02d}" if with_year else f"{value.month:02d}-{value.day:02d}"
    if with_weekday:
        text += f" {WEEKDAY_CN[value.weekday()]}"
    return text


def fmt_time(value: datetime) -> str:
    return f"{value.hour:02d}:{value.minute:02d}"


def fmt_datetime(value: datetime, tz: tzinfo, *, with_year: bool = False) -> str:
    local = to_local(value, tz)
    return f"{fmt_date(local.date(), with_year=with_year, with_weekday=True)} {fmt_time(local)}"


def fmt_range(
    start: datetime,
    end: datetime,
    tz: tzinfo,
    *,
    with_year: bool = False,
) -> str:
    local_start = to_local(start, tz)
    local_end = to_local(end, tz)
    date_part = fmt_date(local_start.date(), with_year=with_year, with_weekday=True)
    if local_start.date() == local_end.date():
        return f"{date_part} {fmt_time(local_start)}-{fmt_time(local_end)}"
    return (
        f"{date_part} {fmt_time(local_start)} ~ "
        f"{fmt_date(local_end.date(), with_year=with_year)} {fmt_time(local_end)}"
    )


def fmt_duration(minutes: int) -> str:
    minutes = max(0, int(minutes))
    hours, rest = divmod(minutes, 60)
    if rest == 0:
        return f"{hours} 小时"
    if hours == 0:
        return f"{rest} 分钟"
    return f"{hours} 小时 {rest} 分"


def fmt_hours(minutes: int) -> str:
    hours = minutes / 60
    if abs(hours - round(hours)) < 0.01:
        return f"{int(round(hours))}h"
    return f"{hours:.1f}h"


def fmt_money(yuan: int) -> str:
    return f"¥{int(yuan)}"


def status_label(status: str) -> str:
    return BookingStatus.LABELS.get(status, status)


def scene_kind_label(kind: str) -> str:
    return SceneKind.LABELS.get(kind, kind)


def role_label(role: str) -> str:
    return UserRole.LABELS.get(role, role)


def user_status_label(status: str) -> str:
    return UserStatus.LABELS.get(status, status)


def humanize_minutes(minutes: int) -> str:
    return fmt_duration(minutes)


def month_bounds(anchor: date) -> tuple[date, date]:
    """返回包含 anchor 的月份起止日期（左闭右开）。"""
    first = anchor.replace(day=1)
    if first.month == 12:
        next_month = date(first.year + 1, 1, 1)
    else:
        next_month = date(first.year, first.month + 1, 1)
    return first, next_month


def week_bounds(anchor: date) -> tuple[date, date]:
    monday = anchor - timedelta(days=anchor.weekday())
    return monday, monday + timedelta(days=7)
