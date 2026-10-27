"""资料卡 / 预约列表 / 审核卡 / 运营统计卡渲染。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from PIL import ImageDraw

from berrystudio.config import get_settings
from berrystudio.render.theme import (
    PALETTE,
    card,
    divider,
    footer,
    mix,
    new_canvas,
    pill,
    rgb,
    status_pill,
    text,
    text_width,
    to_png_bytes,
    wrapped_text,
)
from berrystudio.services.dto import BookingView
from berrystudio.services.stats import SceneStat
from berrystudio.utils.format import fmt_hours, fmt_range


@dataclass
class ProfileCardData:
    owner_name: str
    qq: str
    role_title: str
    rank: str
    bands: list[str]
    stats: list[tuple[str, str, str]]
    upcoming: list[BookingView]
    created_label: str
    generated_label: str
    total_minutes: int = 0


@dataclass
class BookingListData:
    title: str
    subtitle: str
    owner_label: str
    bookings: list[BookingView]
    empty_hint: str
    notes: list[str] = field(default_factory=list)
    generated_label: str = ""
    show_owner: bool = False


@dataclass
class ReviewCardData:
    booking: BookingView
    pending_total: int
    generated_label: str


@dataclass
class StatsCardData:
    title: str
    range_label: str
    tiles: list[tuple[str, str, str]]
    scene_stats: list[SceneStat]
    top_bands: list[tuple[str, int]]
    occupancy: float
    generated_label: str
    notes: list[str] = field(default_factory=list)


def _now_label() -> str:
    return f"{datetime.now(get_settings().tz):%Y-%m-%d %H:%M} 生成"


WIDTH_RIGHT = 1044.0


def _section_title(
    draw: ImageDraw.ImageDraw,
    x: float,
    y: float,
    title: str,
    extra: str = "",
    *,
    right: float = WIDTH_RIGHT,
) -> None:
    draw.rectangle((x, y + 4, x + 4, y + 20), fill=PALETTE.accent)
    text(draw, x + 14, y, title, size=20, color=PALETTE.text, bold=True)
    if extra:
        text(draw, right, y + 4, extra, size=14, color=PALETTE.faint, anchor="ra")

def _empty_card(
    draw: ImageDraw.ImageDraw,
    x: float,
    y: float,
    width: float,
    message: str,
    hint: str,
    *,
    height: int = 116,
) -> None:
    card(draw, (x, y, x + width, y + height), radius=16, fill=PALETTE.card)
    text(draw, x + 24, y + 28, message, size=20, color=PALETTE.text, bold=True)
    text(draw, x + 24, y + 64, hint, size=15, color=PALETTE.muted, max_width=width - 48)


def _booking_row(
    draw: ImageDraw.ImageDraw,
    x: float,
    y: float,
    width: float,
    booking: BookingView,
    *,
    tz,
    show_owner: bool = False,
    height: int = 96,
) -> None:
    card(draw, (x, y, x + width, y + height), radius=14)
    draw.rounded_rectangle(
        (x, y + 8, x + 5, y + height - 8), radius=3, fill=rgb(booking.scene_color)
    )
    text(
        draw,
        x + 20,
        y + 14,
        f"{booking.code} · {booking.scene_name}",
        size=16,
        color=PALETTE.muted,
        max_width=width - 180,
    )
    title = booking.band_name or booking.title or booking.owner_name
    if show_owner:
        title = f"{booking.owner_name} · {booking.band_name or '个人'}"
    text(
        draw,
        x + 20,
        y + 42,
        title,
        size=20,
        color=PALETTE.text,
        bold=True,
        max_width=width - 200,
    )
    time_label = fmt_range(booking.start, booking.end, tz)
    text(
        draw,
        x + 20,
        y + 72,
        time_label,
        size=14,
        color=PALETTE.faint,
        max_width=width - 200,
    )
    status_pill(
        draw,
        x + width - 132,
        y + 18,
        booking.status,
        booking.status_label,
        size=15,
    )
    text(
        draw,
        x + width - 20,
        y + height - 22,
        f"¥{booking.price_estimate} · {booking.attendees} 人",
        size=14,
        color=PALETTE.faint,
        anchor="ra",
    )


def render_profile_card(data: ProfileCardData) -> bytes:
    tz = get_settings().tz
    width = 1000
    margin = 36
    content_width = width - margin * 2
    upcoming = data.upcoming[:4]
    rows_height = len(upcoming) * 106 if upcoming else 116
    tiles_y = 200
    section_y = tiles_y + 112
    rows_y = section_y + 44
    footer_y = rows_y + rows_height + 26
    height = int(footer_y + 64)

    image, draw = new_canvas(width, height)

    # 头像
    draw.ellipse((margin, 40, margin + 90, 130), fill=mix(PALETTE.accent, PALETTE.card, 0.5))
    draw.ellipse(
        (margin + 4, 44, margin + 86, 126),
        outline=PALETTE.accent,
        width=2,
    )
    initial = (data.owner_name or "莓")[:1]
    text(
        draw,
        margin + 45,
        85,
        initial,
        size=40,
        color=PALETTE.bg_bottom,
        anchor="mm",
        bold=True,
    )

    text(
        draw,
        margin + 112,
        42,
        data.owner_name,
        size=34,
        color=PALETTE.text,
        bold=True,
        max_width=content_width - 360,
    )
    text(
        draw,
        margin + 112,
        84,
        f"QQ {data.qq} · 加入于 {data.created_label}",
        size=15,
        color=PALETTE.muted,
    )
    role_width = pill(
        draw,
        margin + 112,
        110,
        data.role_title,
        size=15,
        fg=PALETTE.accent,
        bg=mix(PALETTE.accent, PALETTE.card, 0.14),
        dot_color=PALETTE.accent,
    )
    band_x = margin + 112 + role_width + 8
    for band in data.bands[:2]:
        band_width = text_width(f"乐队 · {band}", 15) + 24
        if band_x + band_width > width - margin:
            break
        pill(
            draw,
            band_x,
            110,
            f"乐队 · {band}",
            size=15,
            fg=PALETTE.accent2,
            bg=mix(PALETTE.accent2, PALETTE.card, 0.14),
        )
        band_x += band_width + 8

    text(
        draw,
        width - margin,
        52,
        data.rank,
        size=20,
        color=PALETTE.gold,
        anchor="ra",
        bold=True,
    )
    text(
        draw,
        width - margin,
        84,
        f"累计 {fmt_hours(data.total_minutes)}",
        size=15,
        color=PALETTE.faint,
        anchor="ra",
    )
    divider(draw, margin, width - margin, 152)

    from berrystudio.render.theme import stat_tiles

    stat_tiles(draw, margin, tiles_y, content_width, data.stats, height=88, gap=14)

    _section_title(
        draw,
        margin,
        section_y,
        "即将到来",
        extra=f"{len(upcoming)} 条",
        right=width - margin,
    )
    if upcoming:
        for index, booking in enumerate(upcoming):
            _booking_row(
                draw,
                margin,
                rows_y + index * 106,
                content_width,
                booking,
                tz=tz,
            )
    else:
        _empty_card(
            draw,
            margin,
            rows_y,
            content_width,
            "还没有进行中的预约",
            "发送：/预约 排练室A 明天 19:00-21:00",
        )

    footer(
        draw,
        width,
        footer_y,
        note="用 /日历 查看完整时段 · /我的 刷新资料",
        generated_at=data.generated_label or _now_label(),
        margin=margin,
    )
    return to_png_bytes(image)


def render_booking_list(data: BookingListData) -> bytes:
    tz = get_settings().tz
    width = 1080
    margin = 36
    content_width = width - margin * 2
    shown = data.bookings[:12]
    row_height = 96
    rows_y = 152
    rows_height = (
        len(shown) * (row_height + 10) - 10 if shown else 132
    )
    footer_y = rows_y + rows_height + 30
    height = int(footer_y + 64)

    image, draw = new_canvas(width, height)
    text(
        draw,
        margin,
        36,
        data.title,
        size=36,
        color=PALETTE.text,
        bold=True,
        max_width=content_width - 240,
    )
    text(draw, margin, 88, data.subtitle, size=17, color=PALETTE.muted, max_width=content_width - 240)
    owner_width = text_width(data.owner_label, 16) + 24
    pill(
        draw,
        width - margin - owner_width,
        40,
        data.owner_label,
        size=16,
        fg=PALETTE.muted,
    )
    divider(draw, margin, width - margin, 132)

    if shown:
        for index, booking in enumerate(shown):
            _booking_row(
                draw,
                margin,
                rows_y + index * (row_height + 10),
                content_width,
                booking,
                tz=tz,
                show_owner=data.show_owner,
            )
    else:
        _empty_card(
            draw,
            margin,
            rows_y,
            content_width,
            "这里还没有预约记录",
            data.empty_hint,
            height=132,
        )

    if len(data.bookings) > len(shown):
        text(
            draw,
            width - margin,
            footer_y - 22,
            f"还有 {len(data.bookings) - len(shown)} 条未显示",
            size=14,
            color=PALETTE.faint,
            anchor="ra",
        )

    footer(
        draw,
        width,
        footer_y,
        note=data.notes[0] if data.notes else "状态与服务器数据实时同步",
        generated_at=data.generated_label or _now_label(),
        margin=margin,
    )
    return to_png_bytes(image)


def render_review_card(data: ReviewCardData) -> bytes:
    tz = get_settings().tz
    booking = data.booking
    width = 1080
    margin = 36
    content_width = width - margin * 2
    height = 860

    image, draw = new_canvas(width, height)
    draw.rectangle((margin, 36, width - margin, 40), fill=PALETTE.warn)
    text(draw, margin, 58, "新的预约申请", size=38, color=PALETTE.text, bold=True)
    text(
        draw,
        margin,
        112,
        "请管理员核对信息后通过或驳回",
        size=16,
        color=PALETTE.muted,
    )
    pending_width = text_width(f"待审核 {data.pending_total} 条", 16) + 24
    pill(
        draw,
        width - margin - pending_width,
        60,
        f"待审核 {data.pending_total} 条",
        size=16,
        fg=PALETTE.warn,
        bg=mix(PALETTE.warn, PALETTE.card, 0.15),
        dot_color=PALETTE.warn,
    )

    card(draw, (margin, 140, width - margin, 280), radius=18, fill=PALETTE.card_soft)
    text(draw, margin + 24, 172, booking.scene_name, size=20, color=PALETTE.muted)
    text(
        draw,
        margin + 24,
        196,
        booking.code,
        size=36,
        color=PALETTE.accent,
        bold=True,
    )
    text(
        draw,
        margin + 24,
        248,
        f"{booking.start:%Y-%m-%d %H:%M} - {booking.end:%H:%M} · {fmt_hours(booking.duration_minutes)}",
        size=16,
        color=PALETTE.muted,
        anchor="la",
    )
    status_pill(
        draw,
        width - margin - 96,
        176,
        booking.status,
        booking.status_label,
        size=16,
    )
    text(
        draw,
        width - margin - 24,
        210,
        f"预估 ¥{booking.price_estimate}",
        size=18,
        color=PALETTE.text,
        anchor="ra",
        bold=True,
    )

    detail_y = 300
    tile_width = (content_width - 14) / 2
    details = [
        ("预约人", f"{booking.owner_name} ({booking.owner_qq})"),
        ("乐队", booking.band_name or "个人预约"),
        ("使用场景", f"{booking.scene_name} ({booking.scene_code})"),
        ("人数", f"{booking.attendees} 人"),
        ("用途", booking.title or "未填写"),
        ("时长", f"{booking.duration_minutes} 分钟"),
    ]
    for index, (label, value) in enumerate(details):
        row, column = divmod(index, 2)
        x = margin + column * (tile_width + 14)
        y = detail_y + row * 82
        card(draw, (x, y, x + tile_width, y + 70), radius=12, fill=PALETTE.card)
        text(draw, x + 16, y + 12, label, size=14, color=PALETTE.faint)
        text(
            draw,
            x + 16,
            y + 38,
            value,
            size=17,
            color=PALETTE.text,
            max_width=tile_width - 32,
        )

    note_y = detail_y + 3 * 82 + 6
    card(draw, (margin, note_y, width - margin, note_y + 88), radius=14, fill=PALETTE.card)
    text(draw, margin + 18, note_y + 14, "备注", size=14, color=PALETTE.faint)
    wrapped_text(
        draw,
        margin + 18,
        note_y + 38,
        booking.note or "无",
        size=15,
        color=PALETTE.muted,
        max_width=content_width - 36,
        line_height=24,
    )

    command_y = note_y + 112
    card(draw, (margin, command_y, width - margin, command_y + 108), radius=16, fill=PALETTE.card_deep)
    text(
        draw,
        margin + 18,
        command_y + 16,
        "管理员操作",
        size=14,
        color=PALETTE.faint,
    )
    approve_label = f"/通过 {booking.code}"
    reject_label = f"/驳回 {booking.code} 原因"
    pill(
        draw,
        margin + 18,
        command_y + 42,
        approve_label,
        size=17,
        fg=PALETTE.ok,
        bg=mix(PALETTE.ok, PALETTE.card, 0.16),
        dot_color=PALETTE.ok,
    )
    pill(
        draw,
        margin + 18 + text_width(approve_label, 17) + 60,
        command_y + 42,
        reject_label,
        size=17,
        fg=PALETTE.danger,
        bg=mix(PALETTE.danger, PALETTE.card, 0.16),
        dot_color=PALETTE.danger,
    )
    text(
        draw,
        width - margin - 18,
        command_y + 62,
        "也可发送 /审核 查看全部待审",
        size=14,
        color=PALETTE.faint,
        anchor="ra",
    )

    footer(
        draw,
        width,
        height - 74,
        note="审核通过后预约立即生效并同步给用户",
        generated_at=data.generated_label or _now_label(),
        margin=margin,
    )
    return to_png_bytes(image)


def render_stats_card(data: StatsCardData) -> bytes:
    width = 1080
    margin = 36
    content_width = width - margin * 2
    scene_rows = data.scene_stats[:6]
    section_y = 260
    scene_y = section_y + 46
    scene_height = len(scene_rows) * 74 if scene_rows else 90
    band_y = scene_y + scene_height + 24
    band_height = 92
    footer_y = band_y + band_height + 24
    height = int(footer_y + 64)

    image, draw = new_canvas(width, height)
    text(draw, margin, 36, data.title, size=36, color=PALETTE.text, bold=True)
    text(draw, margin, 88, data.range_label, size=17, color=PALETTE.muted)
    occupancy_width = text_width(f"占用率 {data.occupancy * 100:.1f}%", 16) + 24
    pill(
        draw,
        width - margin - occupancy_width,
        48,
        f"占用率 {data.occupancy * 100:.1f}%",
        size=16,
        fg=PALETTE.accent,
        bg=mix(PALETTE.accent, PALETTE.card, 0.14),
        dot_color=PALETTE.accent,
    )

    from berrystudio.render.theme import stat_tiles

    stat_tiles(draw, margin, 132, content_width, data.tiles, height=96, gap=14)

    _section_title(draw, margin, section_y, "场景使用情况", extra=f"{len(scene_rows)} 个场地")
    if scene_rows:
        max_minutes = max((item.minutes for item in scene_rows), default=1) or 1
        for index, scene in enumerate(scene_rows):
            y = scene_y + index * 74
            card(draw, (margin, y, width - margin, y + 64), radius=12)
            draw.ellipse((margin + 16, y + 22, margin + 28, y + 34), fill=rgb(scene.color))
            text(
                draw,
                margin + 38,
                y + 18,
                scene.name,
                size=17,
                color=PALETTE.text,
                bold=True,
                max_width=content_width - 360,
            )
            text(
                draw,
                margin + 38,
                y + 40,
                f"{scene.bookings} 单 · {fmt_hours(scene.minutes)} · ¥{scene.revenue}",
                size=13,
                color=PALETTE.faint,
            )
            bar_x0 = margin + content_width * 0.58
            bar_x1 = width - margin - 20
            bar_w = bar_x1 - bar_x0
            draw.rounded_rectangle(
                (bar_x0, y + 27, bar_x1, y + 37), radius=5, fill=PALETTE.card_deep
            )
            fill_w = max(6, bar_w * scene.minutes / max_minutes)
            draw.rounded_rectangle(
                (bar_x0, y + 27, bar_x0 + fill_w, y + 37),
                radius=5,
                fill=rgb(scene.color),
            )
    else:
        _empty_card(
            draw,
            margin,
            scene_y,
            content_width,
            "区间内还没有生效的预约",
            "通过 /审核 处理待审核预约后会出现在这里",
            height=90,
        )

    card(draw, (margin, band_y, width - margin, band_y + band_height), radius=14)
    text(draw, margin + 18, band_y + 16, "活跃乐队 / 个人", size=14, color=PALETTE.faint)
    if data.top_bands:
        cursor_x = margin + 18
        for name, count in data.top_bands:
            label = f"{name} × {count}"
            width_needed = text_width(label, 15) + 24
            if cursor_x + width_needed > width - margin - 18:
                break
            pill(
                draw,
                cursor_x,
                band_y + 44,
                label,
                size=15,
                fg=PALETTE.accent2,
                bg=mix(PALETTE.accent2, PALETTE.card, 0.14),
            )
            cursor_x += width_needed + 8
    else:
        text(
            draw,
            margin + 18,
            band_y + 50,
            "暂无数据",
            size=15,
            color=PALETTE.muted,
        )

    footer(
        draw,
        width,
        footer_y,
        note=data.notes[0] if data.notes else "统计口径：已通过 / 已完成预约",
        generated_at=data.generated_label or _now_label(),
        margin=margin,
    )
    return to_png_bytes(image)
