"""Dorure holographique des cartes brillantes (arcs-en-ciel croisés, gravure,
reflet, paillettes, bord irisé) et petits outils de dessin des cartes.
Sortis de `card_render.py` le 28/11/2026 (audit) : texte inchangé."""

from __future__ import annotations

import colorsys
import io
import math
import random
from functools import lru_cache
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from app.bot.rendering.pillow_utils import try_font
from app.domain.services import card_service as cs
from app.infrastructure.cards import card_loader
ASSETS = card_loader.ASSETS


BANGERS = ASSETS / "fonts" / "Bangers-Regular.ttf"


RADIUS = 22


# ---------------------------------------------------------------- outils --
@lru_cache(maxsize=32)
def _bangers(size: int):
    try:
        return ImageFont.truetype(str(BANGERS), size)
    except OSError:
        return try_font(size, bold=True)


def _color(rarity: str) -> tuple[int, int, int]:
    return cs.CARD_RARITY_COLORS.get(rarity, (176, 176, 186))


def _shade(color, factor: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, int(c * factor))) for c in color)


def _rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=255)
    return mask


def _wrap(draw, text: str, font, max_w: int, max_lines: int) -> list[str]:
    words, lines, line = (text or "").split(), [], ""
    for word in words:
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=font) <= max_w:
            line = trial
            continue
        if line:
            lines.append(line)
        line = word
        if len(lines) == max_lines:
            break
    if line and len(lines) < max_lines:
        lines.append(line)
    consumed = sum(len(x.split()) for x in lines)
    if consumed < len(words) and lines:
        last = lines[-1]
        while last and draw.textlength(last + "…", font=font) > max_w:
            last = last[:-1]
        lines[-1] = last.rstrip() + "…"
    return lines


def _fit(draw, text: str, max_w: int, start: int, minimum: int):
    size = start
    while size > minimum and draw.textlength(text, font=_bangers(size)) > max_w:
        size -= 1
    return _bangers(size)


def _gradient(size, top, bottom) -> Image.Image:
    small = Image.new("RGB", (1, 64))
    for y in range(64):
        t = y / 63
        small.putpixel((0, y), tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)))
    return small.resize(size, Image.BILINEAR).convert("RGBA")


def _cover(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    ratio = max(size[0] / image.width, size[1] / image.height)
    resized = image.resize((max(1, int(image.width * ratio)), max(1, int(image.height * ratio))), Image.LANCZOS)
    left, top = (resized.width - size[0]) // 2, (resized.height - size[1]) // 3
    return resized.crop((left, top, left + size[0], top + size[1]))


def _star(draw, cx: float, cy: float, r: float, fill) -> None:
    points = []
    for i in range(8):
        angle = math.pi / 4 * i - math.pi / 2
        radius = r if i % 2 == 0 else r * 0.28
        points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    draw.polygon(points, fill=fill)


def _png(image: Image.Image) -> bytes:
    # Sans `optimize` : 2 % plus lourd, mais 4 à 5 fois plus rapide à écrire
    # (une ouverture de booster dessine jusqu'à 5 faces).
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", compress_level=6)
    return buffer.getvalue()


def _open(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data)).convert("RGBA")


@lru_cache(maxsize=8)
def _rainbow_strip(length: int, period: int, sat: float) -> Image.Image:
    strip = Image.new("RGB", (length, 4))
    pixels = strip.load()
    for x in range(length):
        r, g, b = colorsys.hsv_to_rgb((x / period) % 1.0, sat, 1.0)
        for y in range(4):
            pixels[x, y] = (int(r * 255), int(g * 255), int(b * 255))
    return strip


def _rainbow(size: tuple[int, int], phase: float, period: int = 170, slope: float = 0.6,
             sat: float = 0.9) -> Image.Image:
    """Bandes arc-en-ciel en diagonale, décalées de `phase` (0 → 1 = une période)."""
    w, h = size
    length = w + int(abs(slope) * h) + period + 8
    dx = (phase % 1.0) * period + (abs(slope) * h if slope < 0 else 0)
    return _rainbow_strip(length, period, sat).transform(size, Image.AFFINE, (1, slope, dx, 0, 0, 2),
                                                         resample=Image.BILINEAR)


def _prism(size: tuple[int, int], phase: float) -> Image.Image:
    """Deux arcs-en-ciel croisés qui glissent en sens contraire : le moiré
    d'un foil qu'on incline."""
    return Image.blend(_rainbow(size, phase, 170, 0.6), _rainbow(size, -phase * 0.7 + 0.3, 260, -1.3), 0.4)


@lru_cache(maxsize=4)
def _etched(size: tuple[int, int], spacing: int = 3, angle: float = -28) -> Image.Image:
    """Les fines lignes gravées du foil (masque)."""
    w, h = size
    d = int(math.hypot(w, h)) + 8
    big = Image.new("L", (d, d), 0)
    draw = ImageDraw.Draw(big)
    for i, y in enumerate(range(0, d, spacing)):
        draw.line((0, y, d, y), fill=255 if i % 2 == 0 else 70, width=1)
    big = big.rotate(angle, resample=Image.BILINEAR)
    left, top = (d - w) // 2, (d - h) // 2
    return big.crop((left, top, left + w, top + h))


@lru_cache(maxsize=4)
def _glare_band(size: tuple[int, int], width: int = 70) -> Image.Image:
    w, h = size
    span = w * 3 + h
    slant = h * 0.45
    c = span // 2

    def band(half: float, alpha: int, blur: int) -> Image.Image:
        layer = Image.new("L", (span, h), 0)
        ImageDraw.Draw(layer).polygon([(c - half, 0), (c + half, 0), (c + half + slant, h), (c - half + slant, h)],
                                      fill=alpha)
        return layer.filter(ImageFilter.GaussianBlur(blur))
    return ImageChops.lighter(band(width * 1.6, 70, 26), band(width * 0.35, 150, 9))


def _glare(size: tuple[int, int], phase: float) -> Image.Image:
    """Le reflet de lumière (masque) : il traverse la carte quand `phase` va de 0 à 1."""
    w, h = size
    band = _glare_band(size)
    center = -0.8 * w + (phase % 1.0) * 2.6 * w
    left = int(band.width // 2 - center)
    return band.crop((left, 0, left + w, h))


def _glitter(image: Image.Image, seed: int, phase: float, count: int = 150) -> None:
    """Paillettes qui scintillent chacune à son rythme."""
    rng = random.Random(seed)
    draw = ImageDraw.Draw(image)
    w, h = image.size
    for _ in range(count):
        x, y = rng.uniform(6, w - 6), rng.uniform(6, h - 6)
        offset, speed, size = rng.random(), rng.choice((1, 1, 2)), rng.choice((1.5, 2, 2, 2.5, 3, 4.5))
        hue = rng.random()
        t = max(0.0, math.cos(2 * math.pi * (phase * speed + offset))) ** 6
        if t < 0.12:
            continue
        r, g, b = colorsys.hsv_to_rgb(hue, 0.25, 1.0)
        rad = size * (0.6 + 0.7 * t)
        k = rad * 0.16
        draw.polygon([(x - rad, y), (x - k, y - k), (x, y - rad), (x + k, y - k), (x + rad, y), (x + k, y + k),
                      (x, y + rad), (x - k, y + k)], fill=(int(r * 255), int(g * 255), int(b * 255), int(255 * t)))


def _foil(rgb: Image.Image, phase: float, sprite: Image.Image | None, strength: float = 0.62) -> Image.Image:
    """Le foil holographique sur l'illustration : prisme gravé + reflet. Le
    personnage détouré en prend moins (il reste lisible)."""
    size = rgb.size
    prism = _prism(size, phase)
    tinted = ImageChops.screen(ImageChops.soft_light(rgb, prism), Image.blend(prism, Image.new("RGB", size), 0.72))
    mask = _etched(size).point(lambda v: int(255 * strength * (0.35 + 0.65 * v / 255)))
    if sprite is not None:
        mask = ImageChops.subtract(mask, sprite.point(lambda v: int(v * strength * 0.5)))
    out = Image.composite(tinted, rgb, mask)
    light = _glare(size, phase)
    return ImageChops.screen(out, Image.merge("RGB", (light, light, light)))


def _foil_border(image: Image.Image, phase: float) -> None:
    w, h = image.size
    bright = ImageChops.screen(_rainbow((w, h), phase * 1.3 + 0.35, period=150, slope=0.9, sat=0.7),
                               Image.new("RGB", (w, h), (80, 70, 80)))
    light = _glare((w, h), phase)
    bright = ImageChops.screen(bright, Image.merge("RGB", (light, light, light)))
    ring = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(ring)
    draw.rounded_rectangle((0, 0, w - 1, h - 1), radius=RADIUS, fill=255)
    draw.rounded_rectangle((7, 7, w - 8, h - 8), radius=16, fill=0)
    image.paste(bright, (0, 0), ring)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((7, 7, w - 8, h - 8), radius=16, outline=(255, 236, 170), width=2)
    draw.rounded_rectangle((9, 9, w - 10, h - 10), radius=15, outline=(40, 20, 50), width=1)
