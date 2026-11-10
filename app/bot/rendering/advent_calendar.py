"""Le calendrier de l'Avent d'un joueur, en image (décembre 2026).

24 portes sur une nuit d'hiver : celles déjà ouvertes montrent leur
récompense, celle du jour brille, les manquées sont grisées, les suivantes
attendent, rouges et vertes. ~50 ms, PNG.
"""

from __future__ import annotations

import io
import random
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from app.bot.rendering.emoji_text import draw_text_with_emojis
from app.bot.rendering.pillow_utils import try_font
from app.domain.services import seasonal_service as ss
from app.shared.paths import ASSETS_DIR

BANGERS = ASSETS_DIR / "fonts" / "Bangers-Regular.ttf"
WIDTH, COLS = 1000, 6
MARGIN, GAP, TOP = 40, 14, 150
DOOR_W = (WIDTH - 2 * MARGIN - (COLS - 1) * GAP) // COLS
DOOR_H = 128
GOLD = (255, 212, 110)
RED, GREEN = (150, 28, 44), (26, 104, 60)
SNOW = (235, 242, 255)

#: Emoji d'une récompense (première de la case) sur sa porte ouverte.
ITEM_EMOJIS = {"booster_offert": "🎴", "sucre_d_orge": "🍬", "sablier_fidelite": "⏳",
               "parchemin_oubli": "📜"}


@lru_cache(maxsize=16)
def _bangers(size: int):
    try:
        return ImageFont.truetype(str(BANGERS), size)
    except OSError:
        return try_font(size, bold=True)


def reward_emoji(rewards) -> str:
    if not rewards:
        return "🎁"
    r = rewards[0]
    if r.kind != ss.ITEM:
        return "💰"
    if r.item in ITEM_EMOJIS:
        return ITEM_EMOJIS[r.item]
    if r.item.startswith(("potion", "grande_potion")):
        return "🧪"
    if r.item.startswith("elixir"):
        return "⚗️"
    if r.item.startswith(("fond_", "cadre_", "titre_")):
        return "🎀"
    return "🎁"


def _background(height: int) -> Image.Image:
    top, bottom = (14, 24, 58), (8, 40, 34)
    image = Image.new("RGB", (WIDTH, height))
    draw = ImageDraw.Draw(image)
    for y in range(height):
        t = y / max(1, height - 1)
        draw.line([(0, y), (WIDTH, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)))
    flakes = Image.new("RGBA", (WIDTH, height), (0, 0, 0, 0))
    fd = ImageDraw.Draw(flakes)
    rng = random.Random(24)        # la même neige pour tout le monde
    for _ in range(140):
        x, y, r = rng.randint(0, WIDTH), rng.randint(0, height), rng.choice((1, 1, 2, 2, 3))
        fd.ellipse((x - r, y - r, x + r, y + r), fill=(*SNOW, rng.randint(70, 170)))
    image.paste(flakes, (0, 0), flakes)
    return image.convert("RGBA")


def _centered(draw, box, text, font, fill, shadow=(0, 0, 0, 170)):
    x0, y0, x1, y1 = box
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    x = x0 + (x1 - x0 - (right - left)) // 2 - left
    y = y0 + (y1 - y0 - (bottom - top)) // 2 - top
    if shadow:
        draw.text((x + 2, y + 2), text, font=font, fill=shadow)
    draw.text((x, y), text, font=font, fill=fill)


def _door(layer: Image.Image, box, n: int, state: str, emoji: str) -> None:
    draw = ImageDraw.Draw(layer)
    x0, y0, x1, y1 = box
    if state == ss.TODAY:
        glow = Image.new("RGBA", layer.size, (0, 0, 0, 0))
        ImageDraw.Draw(glow).rounded_rectangle((x0 - 6, y0 - 6, x1 + 6, y1 + 6), 18, fill=(*GOLD, 200))
        layer.alpha_composite(glow.filter(ImageFilter.GaussianBlur(9)))
        draw.rounded_rectangle(box, 14, fill=(196, 54, 64), outline=GOLD, width=5)
        _centered(draw, (x0, y0 + 4, x1, y1 - 26), str(n), _bangers(64), (255, 248, 230))
        _centered(draw, (x0, y1 - 32, x1, y1 - 6), "AUJOURD'HUI", _bangers(22), GOLD)
    elif state == ss.OPENED:
        draw.rounded_rectangle(box, 14, fill=(44, 32, 26), outline=(214, 170, 90), width=3)
        draw.rounded_rectangle((x0 + 8, y0 + 8, x1 - 8, y1 - 8), 10, fill=(70, 50, 36))
        size = 54
        draw_text_with_emojis(layer, (x0 + (x1 - x0 - size) // 2, y0 + (y1 - y0 - size) // 2 + 4), emoji,
                              _bangers(size), emoji_size=size, shadow=None)
        draw.text((x0 + 14, y0 + 10), str(n), font=_bangers(26), fill=GOLD)
        _centered(draw, (x1 - 40, y0 + 8, x1 - 10, y0 + 36), "✓", try_font(22, bold=True), (140, 230, 150), None)
    elif state == ss.MISSED:
        draw.rounded_rectangle(box, 14, fill=(52, 54, 66), outline=(90, 92, 106), width=2)
        _centered(draw, (x0, y0, x1, y1), str(n), _bangers(56), (120, 122, 136), None)
        _centered(draw, (x0, y1 - 30, x1, y1 - 6), "manquée", try_font(16), (150, 150, 165), None)
    else:
        color = RED if n % 2 else GREEN
        draw.rounded_rectangle(box, 14, fill=color, outline=(*GOLD, 255), width=2)
        # Ruban doré en croix, comme un paquet.
        cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
        draw.rectangle((cx - 5, y0 + 2, cx + 5, y1 - 2), fill=(222, 178, 84))
        draw.rectangle((x0 + 2, cy - 5, x1 - 2, cy + 5), fill=(222, 178, 84))
        _centered(draw, (x0, y0, x1, y1), str(n), _bangers(52), (255, 246, 228))


def render_advent(status, player_name: str = "") -> bytes:
    """`status` : `seasonal.AdventStatus` (cases ouvertes, case du jour)."""
    advent = status.advent
    rows = max(1, -(-advent.size // COLS))
    height = TOP + rows * DOOR_H + (rows - 1) * GAP + MARGIN + 10
    image = _background(height)
    draw = ImageDraw.Draw(image)
    _centered(draw, (0, 18, WIDTH, 92), advent.name.upper(), _bangers(64), GOLD, (60, 10, 20, 220))
    opened = len(status.opened)
    subtitle = f"{player_name} — " if player_name else ""
    subtitle += f"{opened} / {advent.size} case{'s' if opened > 1 else ''} ouverte{'s' if opened > 1 else ''}"
    _centered(draw, (0, 92, WIDTH, 128), subtitle, try_font(24, bold=True), SNOW)
    for i, state in enumerate(status.states):
        n = i + 1
        col, row = i % COLS, i // COLS
        x0 = MARGIN + col * (DOOR_W + GAP)
        y0 = TOP + row * (DOOR_H + GAP)
        _door(image, (x0, y0, x0 + DOOR_W, y0 + DOOR_H), n, state, reward_emoji(advent.rewards(n)))
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="PNG", optimize=False, compress_level=6)
    return buffer.getvalue()
