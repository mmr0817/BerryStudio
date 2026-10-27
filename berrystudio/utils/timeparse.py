"""中文自然语言日期 / 时间解析。

支持示例::

    今天 明天 后天 大后天
    周三 星期三 礼拜三 本周三 下周三 上周三
    2026-10-28 10/28 10月28日 2026年10月28日
    19:00 19:30 9点
    19:00-21:00 19-21 19点~21点
    19:00+2h 19:00+90分钟
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta

WEEKDAY_MAP = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
RELATIVE_DAYS = {"今天": 0, "今日": 0, "本日": 0, "明天": 1, "明日": 1, "后天": 2, "大后天": 3}

_RELATIVE_RE = re.compile(r"^(?P<rel>今天|今日|本日|明天|明日|后天|大后天)$")
_WEEKDAY_RE = re.compile(r"^(?P<prefix>下下|下|本|这|上)?(?:周|星期|礼拜)(?P<wd>[一二三四五六日天])$")
_DATE_RE = re.compile(
    r"^(?:(?P<year>\d{4})[年./-])?(?P<month>\d{1,2})[月./-](?P<day>\d{1,2})[日号]?$"
)
_MONTH_RE = re.compile(r"^(?:(?P<year>\d{4})[年./-])?(?P<month>\d{1,2})月?$")
_DATE_PREFIX_RE = re.compile(
    r"^(?P<date>"
    r"今天|今日|本日|明天|明日|后天|大后天|"
    r"(?:下下|下|本|这|上)?(?:周|星期|礼拜)[一二三四五六日天]|"
    r"\d{4}[年./-]\d{1,2}[月./-]\d{1,2}[日号]?|"
    r"\d{1,2}[月./-]\d{1,2}[日号]?"
    r")(?P<rest>.+)$"
)

_TIME_RANGE_RE = re.compile(
    r"^(?P<h1>\d{1,2})(?::(?P<m1>\d{1,2}))?-(?P<h2>\d{1,2})(?::(?P<m2>\d{1,2}))?$"
)
_TIME_START_DUR_RE = re.compile(r"^(?P<h>\d{1,2})(?::(?P<m>\d{1,2}))?\+(?P<dur>.+)$")
_TIME_SINGLE_RE = re.compile(r"^(?P<h>\d{1,2}):(?P<m>\d{1,2})$")
_DURATION_RE = re.compile(
    r"^(?P<num>\d+(?:\.\d+)?)\s*(?P<unit>h|hr|hrs|hour|hours|小时|m|min|mins|分钟|分)?$",
    re.IGNORECASE,
)


def normalize(text: str) -> str:
    """统一全角符号与常见中文写法，便于正则匹配。"""
    text = (text or "").strip()
    replacements = {
        "：": ":",
        "時": "点",
        "—": "-",
        "－": "-",
        "–": "-",
        "~": "-",
        "～": "-",
        "至": "-",
        "到": "-",
        "＋": "+",
        "　": "",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    # 19点30分 / 19点 / 19时30分 → 19:30 / 19:00
    text = re.sub(r"(\d{1,2})点(\d{1,2})分?", r"\1:\2", text)
    text = re.sub(r"(\d{1,2})点", r"\1:00", text)
    text = re.sub(r"(\d{1,2})时(\d{1,2})分?", r"\1:\2", text)
    text = re.sub(r"(\d{1,2})时", r"\1:00", text)
    text = re.sub(r"(\d{1,2}:\d{1,2})分", r"\1", text)
    return text.strip()


def parse_date(text: str, today: date | None = None) -> date | None:
    """解析日期，无法识别时返回 ``None``。"""
    if not text:
        return None
    today = today or date.today()
    raw = text.strip()

    match = _RELATIVE_RE.match(raw)
    if match:
        return today + timedelta(days=RELATIVE_DAYS[match.group("rel")])

    match = _WEEKDAY_RE.match(raw)
    if match:
        prefix = match.group("prefix") or ""
        target = WEEKDAY_MAP[match.group("wd")]
        monday = today - timedelta(days=today.weekday())
        if prefix in {"本", "这"}:
            return monday + timedelta(days=target)
        if prefix == "上":
            return monday - timedelta(days=7) + timedelta(days=target)
        if prefix == "下下":
            return monday + timedelta(days=14) + timedelta(days=target)
        if prefix == "下":
            return monday + timedelta(days=7) + timedelta(days=target)
        candidate = monday + timedelta(days=target)
        if candidate < today:
            candidate += timedelta(days=7)
        return candidate

    match = _DATE_RE.match(raw)
    if match:
        year = int(match.group("year")) if match.group("year") else today.year
        month = int(match.group("month"))
        day = int(match.group("day"))
        try:
            candidate = date(year, month, day)
        except ValueError:
            return None
        if not match.group("year") and candidate < today - timedelta(days=180):
            try:
                candidate = date(year + 1, month, day)
            except ValueError:
                return None
        return candidate

    # 只给月份：2026-10 / 2026年10月 / 10月（默认当月 1 号）
    match = _MONTH_RE.match(raw)
    if match and ("月" in raw or re.search(r"[./-]", raw)):
        month = int(match.group("month"))
        year = int(match.group("year")) if match.group("year") else today.year
        if not 1 <= month <= 12:
            return None
        try:
            return date(year, month, 1)
        except ValueError:
            return None

    return None


def parse_duration(text: str) -> timedelta | None:
    """解析时长：``2h`` / ``90分钟`` / ``1.5小时`` / ``2``（<=12 视为小时）。"""
    if not text:
        return None
    match = _DURATION_RE.match(normalize(text))
    if not match:
        return None
    amount = float(match.group("num"))
    unit = (match.group("unit") or "").lower()
    if unit in {"h", "hr", "hrs", "hour", "hours", "小时"}:
        minutes = amount * 60
    elif unit in {"m", "min", "mins", "分钟", "分"}:
        minutes = amount
    else:
        minutes = amount * 60 if amount <= 12 else amount
    minutes = int(round(minutes))
    if minutes <= 0:
        return None
    return timedelta(minutes=minutes)


def _build_time(hour: int, minute: int) -> time:
    if not 0 <= hour <= 23:
        raise ValueError("小时需要在 0-23 之间")
    if not 0 <= minute <= 59:
        raise ValueError("分钟需要在 0-59 之间")
    return time(hour=hour, minute=minute)


def parse_time_range(
    text: str,
    base_date: date,
    default_minutes: int = 120,
) -> tuple[datetime, datetime]:
    """解析时间段，返回本地朴素 ``datetime`` 起止时间。

    无法识别或时间非法时抛出 ``ValueError``（消息可直接回复用户）。
    """
    raw = normalize(text)
    if not raw:
        raise ValueError("请提供预约时段，例如 19:00-21:00")

    match = _TIME_RANGE_RE.match(raw)
    if match:
        start_t = _build_time(int(match.group("h1")), int(match.group("m1") or 0))
        end_t = _build_time(int(match.group("h2")), int(match.group("m2") or 0))
        start = datetime.combine(base_date, start_t)
        end = datetime.combine(base_date, end_t)
        if end <= start:
            raise ValueError("结束时间必须晚于开始时间，跨天预约请拆成两段")
        return start, end

    match = _TIME_START_DUR_RE.match(raw)
    if match:
        start_t = _build_time(int(match.group("h")), int(match.group("m") or 0))
        duration = parse_duration(match.group("dur"))
        if duration is None:
            raise ValueError("时长格式无法识别，例如 2h / 90分钟")
        start = datetime.combine(base_date, start_t)
        return start, start + duration

    match = _TIME_SINGLE_RE.match(raw)
    if match:
        start_t = _build_time(int(match.group("h")), int(match.group("m")))
        start = datetime.combine(base_date, start_t)
        return start, start + timedelta(minutes=default_minutes)

    raise ValueError("时间格式无法识别，示例：19:00-21:00 / 19:00+2h / 19点")


def looks_like_date(text: str, today: date | None = None) -> bool:
    return parse_date(text, today) is not None


def looks_like_time(text: str) -> bool:
    raw = normalize(text)
    return bool(
        _TIME_RANGE_RE.match(raw)
        or _TIME_START_DUR_RE.match(raw)
        or _TIME_SINGLE_RE.match(raw)
    )


def split_date_time(text: str, today: date | None = None) -> tuple[date | None, str]:
    """把 ``明天19:00-21:00`` 这样的连写拆成日期与时间。"""
    raw = text.strip()
    if not raw:
        return None, ""
    candidate_date = parse_date(raw, today)
    if candidate_date is not None:
        return candidate_date, ""
    match = _DATE_PREFIX_RE.match(raw)
    if match:
        candidate_date = parse_date(match.group("date"), today)
        if candidate_date is not None:
            return candidate_date, match.group("rest")
    return None, raw


def parse_booking_args(
    text: str,
    today: date,
) -> tuple[str | None, date, str | None, dict[str, str]]:
    """解析 ``/预约`` 参数，顺序可以自由排列。

    返回 ``(场景关键字, 日期, 时段文本, 选项字典)``。
    选项使用 ``key=value``，例如 ``乐队=草莓汽水 人数=5``。
    """
    tokens = (text or "").split()
    scene_token: str | None = None
    day: date | None = None
    slot_token: str | None = None
    options: dict[str, str] = {}
    leftovers: list[str] = []

    for token in tokens:
        if "=" in token:
            key, _, value = token.partition("=")
            if key.strip():
                options[key.strip()] = value.strip()
            continue
        parsed_day, rest = split_date_time(token, today)
        if parsed_day is not None:
            if day is None:
                day = parsed_day
            if rest:
                if slot_token is None and looks_like_time(rest):
                    slot_token = rest
                else:
                    leftovers.append(rest)
            continue
        if slot_token is None and looks_like_time(token):
            slot_token = token
            continue
        leftovers.append(token)

    if leftovers:
        scene_token = leftovers[0]
        extra = " ".join(leftovers[1:]).strip()
        if extra:
            options.setdefault("_extra", extra)
    return scene_token, day or today, slot_token, options
