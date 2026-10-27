"""日历图片渲染（日 / 周 / 月 / 日程列表）。"""

from __future__ import annotations

from datetime import datetime, time

from PIL import ImageDraw

from berrystudio.config import get_settings
from berrystudio.db.models import BookingStatus
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
)
from berrystudio.services.schedule import CalendarData, CalendarEntry
from berrystudio.utils.format import WEEKDAY_CN, fmt_hours, status_label

WIDTH = 1080
MARGIN = 36
CONTENT_WIDTH = WIDTH - MARGIN * 2


def _draw_header(
    draw: ImageDraw.ImageDraw,
    data: CalendarData,
    *,
    subtitle: str,
) -> int:
    right = WIDTH - MARGIN
    owner_label = f"身份 · {data.owner_label}"
    owner_width = text_width(owner_label, 17) + 24
    pill(
        draw,
        right - owner_width,
        34,
        owner_label,
        fg=PALETTE.muted,
        size=17,
    )
    view_width = text_width(data.view_label, 17) + 24 + 14
    pill(
        draw,
        right - owner_width - 8 - view_width,
        34,
        data.view_label,
        fg=PALETTE.accent,
        bg=mix(PALETTE.accent, PALETTE.card, 0.14),
        size=17,
        dot_color=PALETTE.accent,
    )

    text(draw, MARGIN, 30, "BERRY STUDIO", size=17, color=PALETTE.accent, bold=True)
    text(draw, MARGIN + 136, 31, "/ 排练日历", size=17, color=PALETTE.muted)

    text(
        draw,
        MARGIN,
        64,
        data.range_label,
        size=42,
        color=PALETTE.text,
        bold=True,
        max_width=CONTENT_WIDTH - 200,
    )
    text(draw, MARGIN, 122, subtitle, size=18, color=PALETTE.muted)

    stat_tiles = [(item.label, item.value, item.hint) for item in data.stats]
    _stat_tiles(draw, MARGIN, 158, CONTENT_WIDTH, stat_tiles)
    divider(draw, MARGIN, WIDTH - MARGIN, 270)
    return 286


def _stat_tiles(
    draw: ImageDraw.ImageDraw,
    x: float,
    y: float,
    width: float,
    stats: list[tuple[str, str, str]],
) -> None:
    from berrystudio.render.theme import stat_tiles

    stat_tiles(draw, x, y, width, stats, height=88, gap=12)


def _scene_legend(
    draw: ImageDraw.ImageDraw,
    x: float,
    y: float,
    width: float,
    data: CalendarData,
) -> int:
    """绘制场景色卡，返回占用高度。"""
    cursor_x = x
    cursor_y = y
    row_height = 30
    for scene in data.scenes:
        label = f"{scene.name}"
        width_needed = text_width(label, 15) + 24 + 14
        if cursor_x + width_needed > x + width:
            cursor_x = x
            cursor_y += row_height
        pill(
            draw,
            cursor_x,
            cursor_y,
            label,
            size=15,
            fg=PALETTE.muted,
            bg=PALETTE.card,
            pad_x=10,
            pad_y=4,
            dot_color=rgb(scene.color),
        )
        cursor_x += width_needed + 8
    return cursor_y - y + row_height


def _entry_fill(entry: CalendarEntry) -> tuple[int, int, int]:
    base = mix(entry.scene_color, PALETTE.card_deep, 0.35)
    if entry.status == BookingStatus.PENDING:
        return mix(PALETTE.pending, PALETTE.card_deep, 0.28)
    return base


def _assign_lanes(entries: list[CalendarEntry]) -> dict[str, tuple[int, int]]:
    """把时间重叠的预约分到不同泳道，返回 code -> (lane, lane_count)。"""
    if not entries:
        return {}
    lanes: list[list[CalendarEntry]] = []
    placement: dict[str, int] = {}
    for entry in sorted(entries, key=lambda item: (item.start, item.end)):
        for index, lane in enumerate(lanes):
            if lane[-1].end <= entry.start:
                lane.append(entry)
                placement[entry.code] = index
                break
        else:
            lanes.append([entry])
            placement[entry.code] = len(lanes) - 1
    return {code: (index, len(lanes)) for code, index in placement.items()}


def _month_view(data: CalendarData) -> bytes:
    rows = 6
    cell_gap = 6
    cell_width = (CONTENT_WIDTH - cell_gap * 6) / 7
    cell_height = 132
    grid_top = 316
    grid_bottom = grid_top + rows * (cell_height + cell_gap) - cell_gap
    legend_y = grid_bottom + 24
    legend_height = max(30, _legend_height(data))
    footer_y = legend_y + legend_height + 6
    height = int(footer_y + 62)

    image, draw = new_canvas(WIDTH, height)
    subtitle = (
        f"{len(data.entries)} 条预约 · 累计 "
        f"{fmt_hours(sum(int((e.end - e.start).total_seconds() // 60) for e in data.entries))}"
    )
    _draw_header(draw, data, subtitle=subtitle)

    for index, day in enumerate(data.days):
        column = index % 7
        x = MARGIN + column * (cell_width + cell_gap)
        text(
            draw,
            x + cell_width / 2,
            286,
            WEEKDAY_CN[index % 7],
            size=16,
            color=PALETTE.faint,
            anchor="ma",
        )

    today = datetime.now(get_settings().tz).date()
    first_of_month = data.anchor.replace(day=1)
    for index, day in enumerate(data.days):
        row, column = divmod(index, 7)
        x = MARGIN + column * (cell_width + cell_gap)
        y = grid_top + row * (cell_height + cell_gap)
        in_month = day.month == first_of_month.month and day.year == first_of_month.year
        is_today = day == today
        card(
            draw,
            (x, y, x + cell_width, y + cell_height),
            radius=14,
            fill=PALETTE.card if in_month else PALETTE.card_deep,
            outline=PALETTE.accent if is_today else None,
            width=2 if is_today else 1,
        )
        text(
            draw,
            x + 12,
            y + 10,
            f"{day.day}",
            size=20 if is_today else 18,
            color=PALETTE.accent if is_today else (PALETTE.text if in_month else PALETTE.faint),
            bold=is_today,
        )
        if is_today:
            text(
                draw,
                x + cell_width - 10,
                y + 14,
                "今天",
                size=13,
                color=PALETTE.accent,
                anchor="ra",
            )

        day_entries = [entry for entry in data.entries if entry.start.date() == day]
        day_entries.sort(key=lambda item: item.start)
        shown = day_entries[:3]
        for entry_index, entry in enumerate(shown):
            bar_y = y + 42 + entry_index * 26
            bar_x0 = x + 10
            bar_x1 = x + cell_width - 10
            draw.rounded_rectangle(
                (bar_x0, bar_y, bar_x1, bar_y + 22),
                radius=6,
                fill=_entry_fill(entry),
            )
            draw.rectangle((bar_x0, bar_y + 3, bar_x0 + 3, bar_y + 19), fill=rgb(entry.scene_color))
            label = (
                f"{entry.start:%H:%M} {entry.scene_name.replace('·', '')} "
                f"{entry.label if entry.label != '已占用' else ''}".strip()
            )
            text(
                draw,
                bar_x0 + 9,
                bar_y + 11,
                label,
                size=13,
                color=PALETTE.text,
                anchor="lm",
                max_width=cell_width - 32,
            )
        if len(day_entries) > len(shown):
            text(
                draw,
                x + cell_width - 12,
                y + cell_height - 16,
                f"+{len(day_entries) - len(shown)} 条",
                size=12,
                color=PALETTE.faint,
                anchor="rs",
            )
        if not day_entries and in_month:
            text(
                draw,
                x + 12,
                y + 46,
                "空闲",
                size=13,
                color=PALETTE.faint,
            )

    _scene_legend(draw, MARGIN, legend_y, CONTENT_WIDTH, data)
    footer(
        draw,
        WIDTH,
        footer_y,
        note="颜色代表场景 · /日历 周 /日历 日 查看更细粒度",
        generated_at=f"{datetime.now(get_settings().tz):%Y-%m-%d %H:%M} 生成",
    )
    return to_png_bytes(image)


def _legend_height(data: CalendarData) -> int:
    rows = 1
    cursor = 0.0
    for scene in data.scenes:
        width_needed = text_width(scene.name, 15) + 38
        if cursor + width_needed > CONTENT_WIDTH:
            rows += 1
            cursor = 0.0
        cursor += width_needed + 8
    return rows * 30


def _hour_bounds(data: CalendarData) -> tuple[int, int]:
    if not data.scenes:
        return 9, 23
    open_hour = min(scene.open_hour for scene in data.scenes)
    close_hour = max(scene.close_hour for scene in data.scenes)
    return max(0, open_hour), min(24, max(open_hour + 1, close_hour))


def _week_view(data: CalendarData) -> bytes:
    tz = get_settings().tz
    open_hour, close_hour = _hour_bounds(data)
    hours = close_hour - open_hour
    hour_height = 50
    axis_width = 62
    grid_left = MARGIN + axis_width
    column_width = (CONTENT_WIDTH - axis_width) / 7
    header_y = 284
    header_height = 54
    grid_top = header_y + header_height + 8
    grid_bottom = grid_top + hours * hour_height
    legend_y = grid_bottom + 24
    legend_height = max(30, _legend_height(data))
    footer_y = legend_y + legend_height + 6
    height = int(footer_y + 62)

    image, draw = new_canvas(WIDTH, height)
    today = datetime.now(tz).date()
    week_entries = [entry for entry in data.entries]
    subtitle = (
        f"共 {len(data.entries)} 条预约 · 每天 {open_hour:02d}:00-{close_hour:02d}:00"
    )
    _draw_header(draw, data, subtitle=subtitle)

    for column, day in enumerate(data.days):
        x = grid_left + column * column_width
        is_today = day == today
        card(
            draw,
            (x + 2, header_y, x + column_width - 2, header_y + header_height),
            radius=12,
            fill=PALETTE.card_soft if is_today else PALETTE.card,
            outline=PALETTE.accent if is_today else None,
            width=2 if is_today else 1,
        )
        text(
            draw,
            x + column_width / 2,
            header_y + 14,
            WEEKDAY_CN[day.weekday()],
            size=14,
            color=PALETTE.accent if is_today else PALETTE.faint,
            anchor="ma",
        )
        text(
            draw,
            x + column_width / 2,
            header_y + 34,
            f"{day.month:02d}/{day.day:02d}",
            size=18,
            color=PALETTE.text if is_today else PALETTE.muted,
            anchor="ma",
            bold=is_today,
        )

    draw.rectangle(
        (grid_left, grid_top, WIDTH - MARGIN, grid_bottom),
        fill=PALETTE.card_deep,
    )
    for hour in range(open_hour, close_hour + 1):
        y = grid_top + (hour - open_hour) * hour_height
        divider(draw, grid_left, WIDTH - MARGIN, y, color=PALETTE.line)
        if hour < close_hour:
            text(
                draw,
                grid_left - 12,
                y + hour_height / 2,
                f"{hour:02d}:00",
                size=14,
                color=PALETTE.faint,
                anchor="rm",
            )
    for column in range(1, 7):
        x = grid_left + column * column_width
        draw.line((x, grid_top, x, grid_bottom), fill=PALETTE.line, width=1)

    for column, day in enumerate(data.days):
        day_entries = [entry for entry in week_entries if entry.start.date() == day]
        lanes = _assign_lanes(day_entries)
        x = grid_left + column * column_width
        day_start = datetime.combine(day, time(open_hour), tzinfo=tz)
        for entry in day_entries:
            lane_index, lane_count = lanes.get(entry.code, (0, 1))
            lane_width = column_width / lane_count
            block_x0 = x + lane_index * lane_width + 2
            block_x1 = block_x0 + lane_width - 4
            start_minutes = (entry.start - day_start).total_seconds() / 60
            end_minutes = (entry.end - day_start).total_seconds() / 60
            start_minutes = max(0.0, start_minutes)
            end_minutes = min(float(hours * 60), end_minutes)
            if end_minutes <= start_minutes:
                continue
            block_y0 = grid_top + start_minutes / 60 * hour_height
            block_y1 = grid_top + end_minutes / 60 * hour_height
            block_y1 = max(block_y1, block_y0 + 20)
            draw.rounded_rectangle(
                (block_x0, block_y0, block_x1, block_y1),
                radius=7,
                fill=_entry_fill(entry),
                outline=(
                    PALETTE.pending if entry.status == BookingStatus.PENDING else None
                ),
                width=1,
            )
            draw.rectangle(
                (block_x0, block_y0 + 3, block_x0 + 3, min(block_y1 - 3, block_y0 + 30)),
                fill=rgb(entry.scene_color),
            )
            label = entry.label if entry.label != "已占用" else entry.scene_name.replace("·", "")
            if block_y1 - block_y0 >= 46:
                text(
                    draw,
                    block_x0 + 8,
                    block_y0 + 14,
                    f"{entry.start:%H:%M}-{entry.end:%H:%M}",
                    size=12,
                    color=PALETTE.muted,
                    max_width=block_x1 - block_x0 - 12,
                )
                text(
                    draw,
                    block_x0 + 8,
                    block_y0 + 31,
                    label,
                    size=13,
                    color=PALETTE.text,
                    bold=True,
                    max_width=block_x1 - block_x0 - 12,
                )
            else:
                text(
                    draw,
                    block_x0 + 8,
                    (block_y0 + block_y1) / 2,
                    label,
                    size=12,
                    color=PALETTE.text,
                    anchor="lm",
                    max_width=block_x1 - block_x0 - 12,
                )

    _scene_legend(draw, MARGIN, legend_y, CONTENT_WIDTH, data)
    footer(
        draw,
        WIDTH,
        footer_y,
        note="蓝色边框代表待审核 · 实心块代表已生效预约",
        generated_at=f"{datetime.now(get_settings().tz):%Y-%m-%d %H:%M} 生成",
    )
    return to_png_bytes(image)


def _day_view(data: CalendarData) -> bytes:
    tz = get_settings().tz
    open_hour, close_hour = _hour_bounds(data)
    hours = close_hour - open_hour
    hour_height = 58
    axis_width = 62
    scenes = data.scenes[:5]
    if not scenes:
        scenes = []
    column_count = max(1, len(scenes))
    grid_left = MARGIN + axis_width
    column_width = (CONTENT_WIDTH - axis_width) / column_count
    header_y = 284
    header_height = 58
    grid_top = header_y + header_height + 8
    grid_bottom = grid_top + hours * hour_height
    legend_y = grid_bottom + 24
    legend_height = max(30, _legend_height(data))
    footer_y = legend_y + legend_height + 6
    height = int(footer_y + 62)

    image, draw = new_canvas(WIDTH, height)
    subtitle = f"共 {len(data.entries)} 条预约 · 按场景分列展示"
    _draw_header(draw, data, subtitle=subtitle)

    anchor_day = data.anchor

    if not scenes:
        text(
            draw,
            MARGIN,
            330,
            "还没有可预约场景，请管理员先添加。",
            size=20,
            color=PALETTE.muted,
        )
    else:
        # 先画网格，再画预约块，避免网格线盖住色块
        draw.rectangle(
            (grid_left, grid_top, WIDTH - MARGIN, grid_bottom),
            fill=PALETTE.card_deep,
        )
        for hour in range(open_hour, close_hour + 1):
            y = grid_top + (hour - open_hour) * hour_height
            divider(draw, grid_left, WIDTH - MARGIN, y)
            if hour < close_hour:
                text(
                    draw,
                    grid_left - 12,
                    y + hour_height / 2,
                    f"{hour:02d}:00",
                    size=14,
                    color=PALETTE.faint,
                    anchor="rm",
                )
        for column in range(1, column_count):
            x = grid_left + column * column_width
            draw.line((x, grid_top, x, grid_bottom), fill=PALETTE.line, width=1)

    for column, scene in enumerate(scenes):
        x = grid_left + column * column_width
        card(
            draw,
            (x + 3, header_y, x + column_width - 3, header_y + header_height),
            radius=12,
            fill=PALETTE.card,
        )
        draw.ellipse((x + 14, header_y + 16, x + 24, header_y + 26), fill=rgb(scene.color))
        text(
            draw,
            x + 30,
            header_y + 12,
            scene.name,
            size=15,
            color=PALETTE.text,
            bold=True,
            max_width=column_width - 44,
        )
        text(
            draw,
            x + 14,
            header_y + 34,
            f"{scene.code} · ¥{scene.hourly_price}/h",
            size=12,
            color=PALETTE.faint,
            max_width=column_width - 24,
        )

        # 非营业时间遮罩
        open_y = grid_top + (max(open_hour, scene.open_hour) - open_hour) * hour_height
        close_y = grid_top + (min(close_hour, scene.close_hour) - open_hour) * hour_height
        draw.rectangle(
            (x + 2, grid_top, x + column_width - 2, open_y),
            fill=mix(PALETTE.bg_bottom, PALETTE.card_deep, 0.55),
        )
        draw.rectangle(
            (x + 2, close_y, x + column_width - 2, grid_bottom),
            fill=mix(PALETTE.bg_bottom, PALETTE.card_deep, 0.55),
        )

        day_entries = [
            entry
            for entry in data.entries
            if entry.scene_id == scene.id and entry.start.date() == anchor_day
        ]
        lanes = _assign_lanes(day_entries)
        day_start = datetime.combine(anchor_day, time(open_hour), tzinfo=tz)
        for entry in day_entries:
            lane_index, lane_count = lanes.get(entry.code, (0, 1))
            lane_width = (column_width - 6) / lane_count
            block_x0 = x + 3 + lane_index * lane_width
            block_x1 = block_x0 + lane_width - 3
            start_minutes = max(0.0, (entry.start - day_start).total_seconds() / 60)
            end_minutes = min(
                float(hours * 60),
                (entry.end - day_start).total_seconds() / 60,
            )
            if end_minutes <= start_minutes:
                continue
            block_y0 = grid_top + start_minutes / 60 * hour_height
            block_y1 = grid_top + end_minutes / 60 * hour_height
            block_y1 = max(block_y1, block_y0 + 26)
            draw.rounded_rectangle(
                (block_x0, block_y0, block_x1, block_y1),
                radius=8,
                fill=_entry_fill(entry),
                outline=PALETTE.pending if entry.status == BookingStatus.PENDING else None,
                width=2,
            )
            draw.rectangle(
                (block_x0, block_y0 + 4, block_x0 + 4, max(block_y0 + 8, block_y1 - 4)),
                fill=rgb(entry.scene_color),
            )
            text(
                draw,
                block_x0 + 10,
                block_y0 + 12,
                f"{entry.start:%H:%M}-{entry.end:%H:%M}",
                size=13,
                color=PALETTE.muted,
                max_width=block_x1 - block_x0 - 16,
            )
            text(
                draw,
                block_x0 + 10,
                block_y0 + 32,
                entry.label,
                size=15,
                color=PALETTE.text,
                bold=True,
                max_width=block_x1 - block_x0 - 16,
            )
            if block_y1 - block_y0 >= 72:
                text(
                    draw,
                    block_x0 + 10,
                    block_y0 + 54,
                    f"{entry.code} · {status_label(entry.status)}",
                    size=12,
                    color=PALETTE.faint,
                    max_width=block_x1 - block_x0 - 16,
                )
            if entry.status == BookingStatus.PENDING and block_y0 + 40 < block_y1:
                status_pill(
                    draw,
                    block_x1 - 62,
                    block_y0 + 8,
                    entry.status,
                    "待审",
                    size=12,
                )

    _scene_legend(draw, MARGIN, legend_y, CONTENT_WIDTH, data)
    footer(
        draw,
        WIDTH,
        footer_y,
        note="深色区域为非营业时间 · 蓝色边框为待审核",
        generated_at=f"{datetime.now(get_settings().tz):%Y-%m-%d %H:%M} 生成",
    )
    return to_png_bytes(image)


def _agenda_view(data: CalendarData) -> bytes:
    shown = data.entries[:10]
    empty = not shown
    row_height = 104
    rows_height = (row_height + 10) * max(1, len(shown))
    legend_y = 300 + rows_height + 12
    legend_height = max(30, _legend_height(data))
    footer_y = legend_y + legend_height + 6
    height = int(footer_y + 62)

    image, draw = new_canvas(WIDTH, height)
    subtitle = f"共 {len(data.entries)} 条预约 · 未来 14 天"
    _draw_header(draw, data, subtitle=subtitle)

    if empty:
        card(draw, (MARGIN, 300, WIDTH - MARGIN, 440), radius=18, fill=PALETTE.card)
        text(
            draw,
            WIDTH / 2,
            356,
            "这段时间还没有预约",
            size=26,
            color=PALETTE.text,
            anchor="ma",
            bold=True,
        )
        text(
            draw,
            WIDTH / 2,
            396,
            "发送：/预约 排练室A 明天 19:00-21:00",
            size=17,
            color=PALETTE.muted,
            anchor="ma",
        )

    for index, entry in enumerate(shown):
        y = 300 + index * (row_height + 10)
        card(draw, (MARGIN, y, WIDTH - MARGIN, y + row_height), radius=16)
        draw.rounded_rectangle(
            (MARGIN, y + 8, MARGIN + 5, y + row_height - 8),
            radius=3,
            fill=rgb(entry.scene_color),
        )
        text(
            draw,
            MARGIN + 20,
            y + 22,
            f"{entry.start:%m/%d}",
            size=22,
            color=PALETTE.text,
            bold=True,
        )
        text(
            draw,
            MARGIN + 20,
            y + 54,
            WEEKDAY_CN[entry.start.weekday()],
            size=14,
            color=PALETTE.faint,
        )
        draw.line(
            (MARGIN + 108, y + 16, MARGIN + 108, y + row_height - 16),
            fill=PALETTE.line,
            width=1,
        )
        text(
            draw,
            MARGIN + 128,
            y + 20,
            f"{entry.start:%H:%M} - {entry.end:%H:%M}",
            size=22,
            color=PALETTE.text,
            bold=True,
        )
        text(
            draw,
            MARGIN + 128,
            y + 54,
            f"{entry.scene_name} · {entry.label}",
            size=16,
            color=PALETTE.muted,
            max_width=CONTENT_WIDTH - 340,
        )
        text(
            draw,
            MARGIN + 128,
            y + 78,
            f"{entry.code} · {fmt_hours(int((entry.end - entry.start).total_seconds() // 60))}",
            size=13,
            color=PALETTE.faint,
        )
        status_pill(
            draw,
            WIDTH - MARGIN - 118,
            y + row_height / 2 - 16,
            entry.status,
            {BookingStatus.PENDING: "待审核", BookingStatus.APPROVED: "已通过", BookingStatus.COMPLETED: "已完成"}.get(entry.status, entry.status),
            size=16,
        )

    if len(data.entries) > len(shown):
        text(
            draw,
            WIDTH - MARGIN,
            legend_y - 4,
            f"还有 {len(data.entries) - len(shown)} 条未显示，使用 /日历 周 查看",
            size=14,
            color=PALETTE.faint,
            anchor="ra",
        )

    _scene_legend(draw, MARGIN, legend_y, CONTENT_WIDTH, data)
    footer(
        draw,
        WIDTH,
        footer_y,
        note=data.note or "日程列表按开始时间排序",
        generated_at=f"{datetime.now(get_settings().tz):%Y-%m-%d %H:%M} 生成",
    )
    return to_png_bytes(image)


def render_calendar(data: CalendarData) -> bytes:
    if data.view == "month":
        return _month_view(data)
    if data.view == "week":
        return _week_view(data)
    if data.view == "day":
        return _day_view(data)
    return _agenda_view(data)
