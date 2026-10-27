from __future__ import annotations

from datetime import date, datetime

import pytest

from berrystudio.utils.timeparse import (
    looks_like_date,
    looks_like_time,
    parse_booking_args,
    parse_date,
    parse_duration,
    parse_time_range,
    split_date_time,
)

TODAY = date(2026, 10, 27)  # 周二


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("今天", date(2026, 10, 27)),
        ("明天", date(2026, 10, 28)),
        ("后天", date(2026, 10, 29)),
        ("大后天", date(2026, 10, 30)),
        ("周三", date(2026, 10, 28)),
        ("星期三", date(2026, 10, 28)),
        ("礼拜三", date(2026, 10, 28)),
        ("本周一", date(2026, 10, 26)),
        ("下周三", date(2026, 11, 4)),
        ("上周五", date(2026, 10, 23)),
        ("2026-11-02", date(2026, 11, 2)),
        ("2026/12/01", date(2026, 12, 1)),
        ("11-05", date(2026, 11, 5)),
        ("10月30日", date(2026, 10, 30)),
        ("2026年12月24号", date(2026, 12, 24)),
    ],
)
def test_parse_date(text: str, expected: date) -> None:
    assert parse_date(text, TODAY) == expected


def test_invalid_date() -> None:
    assert parse_date("19:00", TODAY) is None
    assert parse_date("19-21", TODAY) is None
    assert parse_date("2026-02-30", TODAY) is None


def test_weekday_rolls_forward_for_plain_weekday() -> None:
    # 周二当天说“周二”指今天；“周一”已经过去，则指向下周一
    assert parse_date("周二", TODAY) == date(2026, 10, 27)
    assert parse_date("周一", TODAY) == date(2026, 11, 2)


@pytest.mark.parametrize(
    ("text", "minutes"),
    [
        ("2h", 120),
        ("2小时", 120),
        ("90分钟", 90),
        ("1.5h", 90),
        ("3", 180),
        ("45", 45),
    ],
)
def test_parse_duration(text: str, minutes: int) -> None:
    duration = parse_duration(text)
    assert duration is not None
    assert int(duration.total_seconds() // 60) == minutes


def test_time_range_variants() -> None:
    start, end = parse_time_range("19:00-21:00", TODAY)
    assert (start.hour, start.minute) == (19, 0)
    assert (end.hour, end.minute) == (21, 0)

    start, end = parse_time_range("19点-21点", TODAY)
    assert (start.hour, end.hour) == (19, 21)

    start, end = parse_time_range("19:00+2h", TODAY)
    assert end - start == parse_duration("2h")

    start, end = parse_time_range("19:30", TODAY, default_minutes=90)
    assert (start.minute, (end - start).seconds // 60) == (30, 90)


def test_invalid_time_range() -> None:
    with pytest.raises(ValueError):
        parse_time_range("21:00-19:00", TODAY)
    with pytest.raises(ValueError):
        parse_time_range("25:00-26:00", TODAY)
    with pytest.raises(ValueError):
        parse_time_range("晚上", TODAY)


def test_looks_like_helpers() -> None:
    assert looks_like_date("明天", TODAY)
    assert not looks_like_date("19:00", TODAY)
    assert looks_like_time("19:00-21:00")
    assert looks_like_time("19-21")
    assert not looks_like_time("排练室A")


def test_split_date_time() -> None:
    day, rest = split_date_time("明天19:00-21:00", TODAY)
    assert day == date(2026, 10, 28)
    assert rest == "19:00-21:00"

    day, rest = split_date_time("2026-12-01", TODAY)
    assert day == date(2026, 12, 1)
    assert rest == ""

    day, rest = split_date_time("排练室A", TODAY)
    assert day is None
    assert rest == "排练室A"


def test_parse_booking_args_is_order_independent() -> None:
    scene, day, slot, options = parse_booking_args(
        "排练室A 明天 19:00-21:00 人数=4 乐队=草莓汽水", TODAY
    )
    assert scene == "排练室A"
    assert day == date(2026, 10, 28)
    assert slot == "19:00-21:00"
    assert options == {"人数": "4", "乐队": "草莓汽水"}

    scene, day, slot, options = parse_booking_args(
        "明天19:00-21:00 排练室A", TODAY
    )
    assert scene == "排练室A"
    assert day == date(2026, 10, 28)
    assert slot == "19:00-21:00"

    scene, day, slot, _ = parse_booking_args("排练室A 19点-21点", TODAY)
    assert scene == "排练室A"
    assert day == TODAY
    assert slot == "19点-21点"


def test_parse_month_only_date() -> None:
    assert parse_date("2026-10", TODAY) == date(2026, 10, 1)
    assert parse_date("11月", TODAY) == date(2026, 11, 1)
    # 单独的两位数字不应被当成月份
    assert parse_date("10", TODAY) is None
