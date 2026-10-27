"""统一的深色霓虹视觉主题与 Pillow 绘制辅助函数。"""

from __future__ import annotations

import io
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageColor, ImageDraw, ImageFilter, ImageFont

from berrystudio.config import get_settings
from berrystudio.db.models import BookingStatus

FONT_CANDIDATES: tuple[str, ...] = (
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/LanguageSupport/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)


@dataclass(frozen=True)
class Palette:
    bg_top: tuple[int, int, int] = (18, 15, 34)
    bg_bottom: tuple[int, int, int] = (7, 7, 14)
    card: tuple[int, int, int] = (28, 25, 46)
    card_soft: tuple[int, int, int] = (39, 35, 61)
    card_deep: tuple[int, int, int] = (22, 20, 36)
    line: tuple[int, int, int] = (58, 53, 88)
    text: tuple[int, int, int] = (240, 240, 250)
    muted: tuple[int, int, int] = (155, 152, 182)
    faint: tuple[int, int, int] = (108, 105, 136)
    accent: tuple[int, int, int] = (94, 234, 212)
    accent2: tuple[int, int, int] = (167, 139, 250)
    pink: tuple[int, int, int] = (244, 114, 182)
    gold: tuple[int, int, int] = (250, 204, 21)
    ok: tuple[int, int, int] = (74, 222, 128)
    pending: tuple[int, int, int] = (96, 165, 250)
    danger: tuple[int, int, int] = (248, 113, 113)
    warn: tuple[int, int, int] = (251, 191, 36)


PALETTE = Palette()

STATUS_COLORS: dict[str, tuple[int, int, int]] = {
    BookingStatus.PENDING: PALETTE.pending,
    BookingStatus.APPROVED: PALETTE.ok,
    BookingStatus.COMPLETED: PALETTE.accent2,
    BookingStatus.REJECTED: PALETTE.danger,
    BookingStatus.CANCELLED: PALETTE.faint,
    BookingStatus.NO_SHOW: PALETTE.warn,
}


def status_color(status: str) -> tuple[int, int, int]:
    return STATUS_COLORS.get(status, PALETTE.muted)


def rgb(color: str | tuple[int, int, int]) -> tuple[int, int, int]:
    if isinstance(color, tuple):
        return color
    try:
        return ImageColor.getrgb(color)  # type: ignore[return-value]
    except ValueError:
        return PALETTE.accent


def mix(
    color: str | tuple[int, int, int],
    base: str | tuple[int, int, int],
    ratio: float,
) -> tuple[int, int, int]:
    """把 color 按 ratio 混入 base（ratio=1 得到 color）。"""
    c = rgb(color)
    b = rgb(base)
    ratio = max(0.0, min(1.0, ratio))
    return tuple(int(c[i] * ratio + b[i] * (1 - ratio)) for i in range(3))  # type: ignore[return-value]


def resolve_font_path() -> str:
    settings = get_settings()
    if settings.font_path:
        path = Path(settings.font_path).expanduser()
        if path.exists():
            return str(path)
    for candidate in FONT_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    return ""


@lru_cache(maxsize=64)
def load_font(size: int) -> ImageFont.ImageFont:
    path = resolve_font_path()
    if path:
        try:
            return ImageFont.truetype(path, size=size)
        except Exception:  # pragma: no cover - 字体损坏时退回默认字体
            pass
    return ImageFont.load_default()


def text_width(content: str, size: int) -> float:
    font = load_font(size)
    try:
        return font.getlength(content)
    except AttributeError:  # pragma: no cover
        return size * len(content) * 0.6


def ellipsize(content: str, size: int, max_width: float) -> str:
    if max_width <= 0:
        return ""
    if text_width(content, size) <= max_width:
        return content
    ellipsis = "…"
    low, high = 0, len(content)
    while low < high:
        mid = (low + high + 1) // 2
        if text_width(content[:mid] + ellipsis, size) <= max_width:
            low = mid
        else:
            high = mid - 1
    return content[:low] + ellipsis if low else ellipsis


def text(
    draw: ImageDraw.ImageDraw,
    x: float,
    y: float,
    content: str,
    *,
    size: int = 24,
    color: tuple[int, int, int] = PALETTE.text,
    anchor: str = "la",
    bold: bool = False,
    max_width: float | None = None,
) -> float:
    """绘制单行文本并返回实际宽度（支持按宽度省略）。"""
    if not content:
        return 0.0
    font = load_font(size)
    if max_width is not None:
        content = ellipsize(content, size, max_width)
    draw.text(
        (x, y),
        content,
        font=font,
        fill=color,
        anchor=anchor,  # type: ignore[arg-type]
        stroke_width=1 if bold else 0,
        stroke_fill=color,
    )
    try:
        return font.getlength(content)
    except AttributeError:  # pragma: no cover
        return 0.0


def wrapped_text(
    draw: ImageDraw.ImageDraw,
    x: float,
    y: float,
    content: str,
    *,
    size: int = 20,
    color: tuple[int, int, int] = PALETTE.text,
    max_width: float = 300,
    line_height: int | None = None,
) -> int:
    """按字符折行（适合中文），返回占用高度。"""
    line_height = line_height or int(size * 1.5)
    lines: list[str] = []
    current = ""
    for char in content:
        if char == "\n":
            lines.append(current)
            current = ""
            continue
        if text_width(current + char, size) > max_width and current:
            lines.append(current)
            current = char
        else:
            current += char
    if current:
        lines.append(current)
    for index, line in enumerate(lines):
        text(draw, x, y + index * line_height, line, size=size, color=color)
    return len(lines) * line_height


def _background(width: int, height: int, palette: Palette = PALETTE) -> Image.Image:
    base = Image.new("RGB", (width, height), palette.bg_bottom)
    draw = ImageDraw.Draw(base)
    for y in range(height):
        ratio = y / max(1, height - 1)
        draw.line(
            [(0, y), (width, y)],
            fill=(
                int(palette.bg_top[0] * (1 - ratio) + palette.bg_bottom[0] * ratio),
                int(palette.bg_top[1] * (1 - ratio) + palette.bg_bottom[1] * ratio),
                int(palette.bg_top[2] * (1 - ratio) + palette.bg_bottom[2] * ratio),
            ),
        )

    image = base.convert("RGBA")
    glow = Image.new("RGBA", (180, 180), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    glow_draw.ellipse((30, 30, 150, 150), fill=(*palette.accent, 120))
    glow = glow.filter(ImageFilter.GaussianBlur(radius=26)).resize(
        (int(width * 0.9), int(height * 0.55)), Image.Resampling.BICUBIC
    )
    image.alpha_composite(glow, (int(width * 0.45), 0))

    glow2 = Image.new("RGBA", (180, 180), (0, 0, 0, 0))
    ImageDraw.Draw(glow2).ellipse((40, 40, 140, 140), fill=(*palette.accent2, 110))
    glow2 = glow2.filter(ImageFilter.GaussianBlur(radius=26)).resize(
        (int(width * 0.7), int(height * 0.45)), Image.Resampling.BICUBIC
    )
    image.alpha_composite(glow2, (0, int(height * 0.55)))
    return image


def new_canvas(width: int, height: int) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = _background(width, height)
    return image, ImageDraw.Draw(image)


def card(
    draw: ImageDraw.ImageDraw,
    box: tuple[float, float, float, float],
    *,
    radius: int = 18,
    fill: tuple[int, int, int] = PALETTE.card,
    outline: tuple[int, int, int] | None = None,
    width: int = 1,
) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def pill(
    draw: ImageDraw.ImageDraw,
    x: float,
    y: float,
    content: str,
    *,
    size: int = 18,
    fg: tuple[int, int, int] = PALETTE.text,
    bg: tuple[int, int, int] = PALETTE.card_soft,
    pad_x: int = 12,
    pad_y: int = 6,
    bold: bool = False,
    dot_color: tuple[int, int, int] | None = None,
) -> float:
    """绘制胶囊标签，返回宽度（自动从 x 向右排布调用方负责）。"""
    content = content or "-"
    width = text_width(content, size) + pad_x * 2
    if dot_color is not None:
        width += size * 0.7
    height = size + pad_y * 2
    draw.rounded_rectangle(
        (x, y, x + width, y + height), radius=height // 2, fill=bg
    )
    text_x = x + pad_x
    if dot_color is not None:
        dot_r = size * 0.22
        cy = y + height / 2
        draw.ellipse(
            (text_x, cy - dot_r, text_x + dot_r * 2, cy + dot_r), fill=dot_color
        )
        text_x += dot_r * 2 + size * 0.25
    text(
        draw,
        text_x,
        y + height / 2,
        content,
        size=size,
        color=fg,
        anchor="lm",
        bold=bold,
    )
    return width


def status_pill(
    draw: ImageDraw.ImageDraw,
    x: float,
    y: float,
    status: str,
    label: str,
    *,
    size: int = 17,
) -> float:
    color = status_color(status)
    return pill(
        draw,
        x,
        y,
        label,
        size=size,
        fg=color,
        bg=mix(color, PALETTE.card, 0.16),
        dot_color=color,
    )


def divider(
    draw: ImageDraw.ImageDraw,
    x0: float,
    x1: float,
    y: float,
    *,
    color: tuple[int, int, int] = PALETTE.line,
) -> None:
    draw.line((x0, y, x1, y), fill=color, width=1)


def stat_tiles(
    draw: ImageDraw.ImageDraw,
    x: float,
    y: float,
    width: float,
    stats: list[tuple[str, str, str]],
    *,
    height: int = 88,
    gap: int = 14,
) -> int:
    if not stats:
        return 0
    tile_width = (width - gap * (len(stats) - 1)) / len(stats)
    for index, (label, value, hint) in enumerate(stats):
        left = x + index * (tile_width + gap)
        card(draw, (left, y, left + tile_width, y + height), radius=16)
        draw.rectangle((left + 14, y + 16, left + 18, y + 22), fill=PALETTE.accent)
        text(draw, left + 26, y + 14, label, size=16, color=PALETTE.muted)
        text(
            draw,
            left + 16,
            y + height / 2 + 6,
            value,
            size=26,
            color=PALETTE.text,
            bold=True,
            anchor="lm",
            max_width=tile_width - 30,
        )
        if hint:
            text(
                draw,
                left + tile_width - 14,
                y + height - 14,
                hint,
                size=14,
                color=PALETTE.faint,
                anchor="rs",
                max_width=tile_width - 30,
            )
    return height


def footer(
    draw: ImageDraw.ImageDraw,
    width: int,
    y: float,
    *,
    note: str = "",
    generated_at: str = "",
    margin: int = 36,
) -> None:
    divider(draw, margin, width - margin, y)
    text(draw, margin, y + 16, "BERRY STUDIO", size=18, color=PALETTE.accent, bold=True)
    text(
        draw,
        margin + 172,
        y + 18,
        note,
        size=16,
        color=PALETTE.muted,
        max_width=width - 500,
    )
    text(
        draw,
        width - margin,
        y + 18,
        generated_at,
        size=16,
        color=PALETTE.faint,
        anchor="ra",
    )


def to_png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="PNG")
    return buffer.getvalue()


def save_png(image: Image.Image, name: str) -> Path:
    directory = get_settings().image_dir
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    image.convert("RGB").save(path, format="PNG")
    return path
