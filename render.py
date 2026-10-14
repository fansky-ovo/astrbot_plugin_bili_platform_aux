"""PIL 渲染发布预览卡片。"""

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

CARD_WIDTH = 760
MARGIN = 20
PADDING = 30
BG = (242, 243, 245)
WHITE = (255, 255, 255)
TEXT = (28, 32, 38)
SECONDARY = (122, 128, 138)
ACCENT = (51, 112, 255)
TOPIC_BG = (235, 242, 255)
LINE = (232, 234, 238)
AVATAR_FALLBACK = (208, 214, 224)

_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF"
    "\u2b00-\u2bff]+"
)
_SKIP_CHARS = "\ufe0f\u200d\u20e3"
_ZERO_WIDTH = {"\ufe0f", "\u200d"}

_REGULAR_FONTS = [
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 2),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 0),
    ("C:/Windows/Fonts/msyh.ttc", 0),
    ("C:/Windows/Fonts/simhei.ttf", 0),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 0),
]
_BOLD_FONTS = [
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 2),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 0),
    ("C:/Windows/Fonts/msyhbd.ttc", 0),
    ("C:/Windows/Fonts/msyh.ttc", 0),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 0),
]
_EMOJI_FONTS = [
    "NotoColorEmoji.ttf",
    "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
    "C:/Windows/Fonts/seguiemj.ttf",
    "C:/Windows/Fonts/segoeuiemoji.ttf",
]

_BITMAP_CACHE: dict[str, Image.Image | None] = {}
_FONT_CACHE: dict[tuple[str, int, int], Any] = {}


def _plugin_resources() -> Path:
    return Path(__file__).resolve().parent / "resources"


def clean_text(value: Any) -> str:
    """去掉 emoji（没有 emoji 字体时的兜底）并收敛空白。"""

    text = "" if value is None else str(value)
    text = _EMOJI_RE.sub(" ", text)
    for char in _SKIP_CHARS:
        text = text.replace(char, "")
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def _raw_text(value: Any) -> str:
    text = "" if value is None else str(value)
    for char in _SKIP_CHARS:
        text = text.replace(char, "")
    return text.strip()


def _load_font(size: int, *, bold: bool = False):
    key = ("bold" if bold else "regular", size, 0)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    result = None
    for path, index in _BOLD_FONTS if bold else _REGULAR_FONTS:
        candidate = Path(path)
        if not candidate.exists():
            continue
        try:
            result = ImageFont.truetype(str(candidate), size, index=index)
            break
        except Exception:
            continue
    if result is None:
        result = ImageFont.load_default()
    _FONT_CACHE[key] = result
    return result


def load_emoji_font(extra_paths: list[str] | None = None):
    """返回 (font, 基准字号) 或 None。NotoColorEmoji 只支持 109px。"""

    candidates: list[str] = []
    for item in extra_paths or []:
        if item:
            candidates.append(item)
    resources = _plugin_resources()
    for name in _EMOJI_FONTS:
        path = Path(name)
        candidates.append(str(path if path.is_absolute() else resources / name))
    for candidate in candidates:
        path = Path(candidate)
        if not path.exists():
            continue
        for size in (109, 64, 32):
            try:
                return ImageFont.truetype(str(path), size), size
            except Exception:
                continue
    return None


def _is_emoji(char: str) -> bool:
    return bool(_EMOJI_RE.match(char))


def _emoji_bitmap(char: str, font: Any, base: int, target: int) -> Image.Image | None:
    key = f"{char}|{base}|{target}"
    if key in _BITMAP_CACHE:
        return _BITMAP_CACHE[key]
    result: Image.Image | None = None
    try:
        canvas = Image.new("RGBA", (base * 2, base * 2), (0, 0, 0, 0))
        ImageDraw.Draw(canvas).text((base // 2, base // 2), char, font=font, embedded_color=True)
        bbox = canvas.getbbox()
        if bbox:
            glyph = canvas.crop(bbox)
            scale = target / max(glyph.size)
            if scale != 1:
                glyph = glyph.resize(
                    (
                        max(1, round(glyph.size[0] * scale)),
                        max(1, round(glyph.size[1] * scale)),
                    ),
                    Image.LANCZOS,
                )
            result = glyph
    except Exception:
        result = None
    _BITMAP_CACHE[key] = result
    return result


def _char_width(char: str, font: Any, emoji: Any, emoji_px: int) -> float:
    if emoji and _is_emoji(char):
        glyph = _emoji_bitmap(char, emoji[0], emoji[1], emoji_px)
        if glyph:
            return glyph.size[0] + 2
    return font.getlength(char)


def _measure(text: str, font: Any, emoji: Any, emoji_px: int) -> float:
    return sum(_char_width(char, font, emoji, emoji_px) for char in text)


def _line_height(font: Any) -> int:
    try:
        ascent, descent = font.getmetrics()
        return int(ascent + descent)
    except Exception:
        return 32


def _wrap(draw, text: str, font: Any, max_width: int, emoji: Any = None, emoji_px: int = 0) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        if not paragraph.strip():
            lines.append("")
            continue
        current = ""
        current_width = 0.0
        for char in paragraph:
            width = _char_width(char, font, emoji, emoji_px)
            if current and current_width + width > max_width:
                lines.append(current)
                current = char
                current_width = width
            else:
                current += char
                current_width += width
        lines.append(current)
    return lines


def _draw_rich(
    card: Image.Image,
    draw,
    x: int,
    y: int,
    text: str,
    font: Any,
    fill,
    emoji: Any,
    emoji_px: int,
) -> None:
    if not text:
        return
    if not emoji:
        draw.text((x, y), text, font=font, fill=fill)
        return
    offset = (emoji_px - _line_height(font)) / 2
    cursor = float(x)
    for char in text:
        if _is_emoji(char):
            glyph = _emoji_bitmap(char, emoji[0], emoji[1], emoji_px)
            if glyph:
                card.paste(glyph, (round(cursor), round(y - offset)), glyph)
                cursor += glyph.size[0] + 2
                continue
            cursor += emoji_px * 0.6
            continue
        draw.text((cursor, y), char, font=font, fill=fill)
        cursor += font.getlength(char)


def _circle(image: Image.Image, size: int) -> Image.Image:
    image = image.convert("RGBA")
    side = min(image.size)
    left = (image.size[0] - side) // 2
    top = (image.size[1] - side) // 2
    image = image.crop((left, top, left + side, top + side)).resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    result = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    result.paste(image, (0, 0), mask)
    return result


def _open_image(data: bytes | None) -> Image.Image | None:
    if not data:
        return None
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
        return image.convert("RGB")
    except Exception:
        return None


def _scaled(image: Image.Image, width: int, max_height: int) -> Image.Image:
    height = max(1, round(image.size[1] * width / image.size[0]))
    if height > max_height:
        height = max_height
        width = max(1, round(image.size[0] * height / image.size[1]))
    return image.resize((width, height), Image.LANCZOS)


def _draw_avatar(card: Image.Image, data: bytes | None, name: str, box: tuple[int, int, int]) -> None:
    x, y, size = box
    avatar = _open_image(data)
    if avatar:
        circle = _circle(avatar, size)
        card.paste(circle, (x, y), circle)
        return
    fallback = Image.new("RGBA", (size, size), AVATAR_FALLBACK + (255,))
    draw = ImageDraw.Draw(fallback)
    font = _load_font(int(size * 0.5), bold=True)
    char = clean_text(name)[:1] or "B"
    width = draw.textlength(char, font=font)
    draw.text(((size - width) / 2, size * 0.22), char, font=font, fill=WHITE)
    circle = _circle(fallback, size)
    card.paste(circle, (x, y), circle)


def render_preview_card(data: dict) -> Image.Image:
    """把发布内容渲染成一张预览卡片。"""

    emoji = load_emoji_font(
        [
            data.get("emoji_font_path") or "",
            str(Path(data.get("resources_dir") or "") / "NotoColorEmoji.ttf")
            if data.get("resources_dir")
            else "",
        ]
    )
    sanitize = _raw_text if emoji else clean_text

    title = sanitize(data.get("title"))
    account_name = sanitize(data.get("account_name")) or "未命名账号"
    time_text = sanitize(data.get("time_text"))
    topic = sanitize(data.get("topic"))
    body = sanitize(data.get("text"))
    footer = sanitize(data.get("footer"))
    images = data.get("image_bytes") or []

    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    content_w = CARD_WIDTH - (MARGIN + PADDING) * 2
    title_font = _load_font(34, bold=True)
    name_font = _load_font(27, bold=True)
    small_font = _load_font(21)
    body_font = _load_font(25)
    hash_font = _load_font(22, bold=True)
    topic_font = _load_font(25, bold=True)

    title_lines = (
        _wrap(probe, title, title_font, content_w, emoji, 36) if title else []
    )
    body_lines = (
        _wrap(probe, body, body_font, content_w, emoji, 28) if body else []
    )

    open_images = [img for img in (_open_image(b) for b in images[:9]) if img]
    prepared: list[Image.Image] = []
    if open_images:
        single = len(open_images) == 1
        target_w = content_w if single else (content_w - 14) // 2
        max_h = 1500 if single else 720
        prepared = [_scaled(img, target_w, max_h) for img in open_images]

    y = MARGIN + PADDING
    if title_lines:
        y += len(title_lines) * _line_height(title_font) + 22
    header_h = 76
    y += header_h + 22
    if topic:
        y += 34 + 18
    if body_lines:
        y += len(body_lines) * _line_height(body_font) + 20
    if prepared:
        rows = [prepared] if len(prepared) == 1 else [
            prepared[index : index + 2] for index in range(0, len(prepared), 2)
        ]
        for row in rows:
            y += max(img.size[1] for img in row) + 14
        y += 8
    if footer:
        y += 34
    total_h = y + PADDING + MARGIN

    card = Image.new("RGB", (CARD_WIDTH, total_h), BG)
    draw = ImageDraw.Draw(card)
    draw.rounded_rectangle(
        (MARGIN, MARGIN, CARD_WIDTH - MARGIN, total_h - MARGIN), 22, fill=WHITE
    )

    cursor = MARGIN + PADDING
    for line in title_lines:
        _draw_rich(card, draw, MARGIN + PADDING, cursor, line, title_font, TEXT, emoji, 36)
        cursor += _line_height(title_font)
    if title_lines:
        cursor += 22

    avatar_size = header_h
    _draw_avatar(
        card,
        data.get("account_avatar"),
        account_name,
        (MARGIN + PADDING, cursor, avatar_size),
    )
    name_x = MARGIN + PADDING + avatar_size + 18
    _draw_rich(card, draw, name_x, cursor + 8, account_name, name_font, TEXT, emoji, 30)
    if time_text:
        draw.text(
            (name_x, cursor + 8 + _line_height(name_font) + 2),
            time_text,
            font=small_font,
            fill=SECONDARY,
        )

    cursor += avatar_size + 22

    if topic:
        chip_h = 34
        hash_w = int(draw.textlength("#", font=hash_font))
        block = hash_w + 20
        draw.rounded_rectangle(
            (MARGIN + PADDING, cursor, MARGIN + PADDING + block, cursor + chip_h),
            8,
            fill=ACCENT,
        )
        draw.text(
            (MARGIN + PADDING + (block - hash_w) / 2, cursor + 5),
            "#",
            font=hash_font,
            fill=WHITE,
        )
        _draw_rich(
            card,
            draw,
            MARGIN + PADDING + block + 10,
            cursor + 3,
            topic,
            topic_font,
            ACCENT,
            emoji,
            28,
        )
        cursor += chip_h + 18

    for line in body_lines:
        _draw_rich(card, draw, MARGIN + PADDING, cursor, line, body_font, TEXT, emoji, 28)
        cursor += _line_height(body_font)
    if body_lines:
        cursor += 20

    if prepared:
        rows = [prepared] if len(prepared) == 1 else [
            prepared[index : index + 2] for index in range(0, len(prepared), 2)
        ]
        for row in rows:
            row_h = max(img.size[1] for img in row)
            if len(row) == 1:
                x = MARGIN + PADDING + (content_w - row[0].size[0]) // 2
            else:
                gutter = 14
                total = sum(img.size[0] for img in row) + gutter * (len(row) - 1)
                x = MARGIN + PADDING + (content_w - total) // 2
            for img in row:
                card.paste(img, (x, cursor))
                x += img.size[0] + gutter if len(row) > 1 else img.size[0]
            cursor += row_h + 14
        cursor += 8

    if footer:
        _draw_rich(card, draw, MARGIN + PADDING, cursor, footer, small_font, SECONDARY, emoji, 24)

    return card
