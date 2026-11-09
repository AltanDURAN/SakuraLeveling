"""Visuels des cartes à collectionner (09/11/2026) : la carte, son dos,
l'album, le résultat d'un booster et son animation d'ouverture (GIF).

Même direction artistique que la bannière /profil : cadre à la couleur de la
rareté (celles de l'équipement), Bangers pour les noms, pétales en filigrane.

Une BRILLANTE est « PLEINE CARTE » et holographique (demande de l'auteur,
10/11/2026) : l'illustration couvre toute la carte (celle de l'auteur,
`<code>_fullart.png`, sinon l'image de la carte sur le décor de son
chapitre), le texte passe sur un panneau de verre dépoli, et un FOIL la
recouvre — prisme arc-en-ciel gravé de fines lignes, reflet de lumière,
paillettes, bord irisé. Animée (`card_gif`), le prisme glisse et le reflet
passe comme quand on incline la carte. La mythique l'est toujours.

Les faces sont gardées en mémoire (PNG compressés) et refaites dès que la
carte change (texte, image, décor, réglages de la série).

L'ouverture : les cartes arrivent face cachée, chacune s'allume à la couleur
de sa rareté avant de se retourner, de la moins rare à la plus rare — la
dernière se fait attendre ; éclat de lumière pour un légendaire, pétales et
tremblement pour la mythique, et une brillante scintille (son foil prend la
lumière).
"""

from __future__ import annotations

import colorsys
import io
import json
import math
import random
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from app.bot.rendering.pillow_utils import draw_sakura_petals, try_font
from app.domain.services import card_service as cs
from app.infrastructure.cards import card_loader
from app.shared.enums import ELEMENT_LABELS

ASSETS = card_loader.ASSETS
BANGERS = ASSETS / "fonts" / "Bangers-Regular.ttf"
W, H = 360, 504
RADIUS = 22
PANEL = (24, 20, 34)
#: Taille d'envoi maximale (Discord, sans boost : 10 Mo).
MAX_GIF_BYTES = 9_000_000
GOLD = (255, 214, 120)
PINK = (255, 150, 190)


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
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _open(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data)).convert("RGBA")


# ---------------------------------------------------------------- la face --
def _art_window(card: cs.CardDef, size: tuple[int, int]) -> Image.Image:
    color = _color(card.rarity)
    path = card_loader.decor_path(card.chapter)
    if path is not None:
        with Image.open(path) as source:
            window = _cover(source.convert("RGB"), size).convert("RGBA")
        window = Image.blend(window, Image.new("RGBA", size, (*_shade(color, 0.35), 255)), 0.45)
    else:
        window = _gradient(size, _shade(color, 0.55), _shade(color, 0.16))
        draw_sakura_petals(window, seed=card.number, count=8, size_range=(26, 46))
    art = card_loader.art_path(card)
    if art is None:
        draw = ImageDraw.Draw(window)
        font = _bangers(130)
        draw.text((size[0] / 2, size[1] / 2), "?", font=font, anchor="mm", fill=(*_shade(color, 1.2), 150))
        return window
    with Image.open(art) as source:
        image = source.convert("RGBA")
    alpha_min = image.getchannel("A").getextrema()[0]
    if alpha_min >= 250:                       # portrait opaque : il remplit le cadre
        return _cover(image, size)
    image.thumbnail((size[0] - 16, size[1] - 10), Image.LANCZOS)
    x, y = (size[0] - image.width) // 2, size[1] - image.height - 4
    shadow = Image.new("RGBA", size, (0, 0, 0, 0))
    shadow.paste((0, 0, 0, 150), (x + 4, y + 6), image.getchannel("A"))
    window.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(6)))
    window.alpha_composite(image, (x, y))
    return window


def _normal_face(card: cs.CardDef) -> Image.Image:
    color = _color(card.rarity)
    image = _gradient((W, H), _shade(color, 1.15), _shade(color, 0.55))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, W - 1, H - 1), radius=RADIUS, outline=_shade(color, 1.4), width=3)
    draw.rounded_rectangle((12, 12, W - 13, H - 13), radius=16, fill=PANEL)
    # Nom et numéro
    name_font = _fit(draw, card.name, W - 96, 32, 18)
    draw.text((26, 38), card.name, font=name_font, anchor="lm", fill=(0, 0, 0), stroke_width=0)
    draw.text((24, 36), card.name, font=name_font, anchor="lm", fill=(255, 255, 255))
    draw.text((W - 26, 37), f"#{card.number:02d}", font=try_font(15, bold=True), anchor="rm", fill=_shade(color, 1.3))
    # Image
    window = _art_window(card, (W - 44, 236))
    image.paste(window, (22, 60), _rounded_mask(window.size, 12))
    draw.rounded_rectangle((22, 60, W - 23, 296), radius=12, outline=_shade(color, 1.1), width=2)
    # Sous-titre et rareté
    label = cs.RARITY_LABELS.get(card.rarity, "").upper()
    subtitle_font = try_font(14)
    room = W - 52 - draw.textlength(label, font=try_font(13, bold=True)) - 12
    subtitle = card.title
    while subtitle and draw.textlength(subtitle, font=subtitle_font) > room:
        subtitle = subtitle[:-1]
    if subtitle != card.title:
        subtitle = subtitle.rstrip() + "…"
    draw.text((26, 312), subtitle, font=subtitle_font, anchor="lm", fill=(205, 200, 220))
    draw.text((W - 26, 312), label, font=try_font(13, bold=True), anchor="rm", fill=_shade(color, 1.3))
    # Effet
    box = (22, 326, W - 23, 412)
    draw.rounded_rectangle(box, radius=10, fill=(*_shade(color, 0.32), 255), outline=_shade(color, 0.9))
    effect_font = try_font(15, bold=True)
    lines = _wrap(draw, cs.effect_text(card), effect_font, box[2] - box[0] - 20, 3)
    top = box[1] + (box[3] - box[1] - 20 * len(lines)) // 2
    for i, line in enumerate(lines):
        draw.text((box[0] + 10, top + 20 * i), line, font=effect_font, fill=(250, 246, 255))
    # Texte d'ambiance
    flavor_font = try_font(12)
    for i, line in enumerate(_wrap(draw, card.flavor, flavor_font, W - 52, 2)):
        draw.text((26, 422 + 16 * i), line, font=flavor_font, fill=(190, 180, 210))
    # Pied
    element = ELEMENT_LABELS.get(card.element, "") if card.element else ""
    draw.text((26, H - 28), _footer(card), font=try_font(12), anchor="lm", fill=(150, 140, 170))
    if element:
        draw.text((W - 26, H - 28), element, font=try_font(12, bold=True), anchor="rm", fill=(170, 160, 195))
    image.putalpha(ImageChops.multiply(image.getchannel("A"), _rounded_mask((W, H), RADIUS)))
    return image


def _footer(card: cs.CardDef) -> str:
    series = card_loader.get_series()
    return f"Série {series.number} · {card.number}/{series.total}"


# ------------------------------------------------- la brillante (foil) --
#: La phase du foil sur l'image fixe (album, résultat d'un booster).
STILL_PHASE = 0.3
#: Images de l'animation d'une brillante (en boucle).
HOLO_FRAMES = 16
HOLO_FRAME_MS = 80
#: Panneau de verre dépoli du texte.
FOIL_PANEL = (18, 352, W - 19, H - 19)
#: Part de transparence au-delà de laquelle une image est un « personnage
#: détouré » (posé sur le décor) plutôt qu'une illustration (qui couvre tout).
SPRITE_TRANSPARENCY = 0.25
INK = (20, 10, 30)


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


def _is_sprite(image: Image.Image) -> bool:
    """Un personnage détouré (beaucoup de transparence), pas une illustration."""
    hist = image.getchannel("A").histogram()
    return hist[0] / max(1, sum(hist)) >= SPRITE_TRANSPARENCY


def _backdrop(card: cs.CardDef, size: tuple[int, int]) -> Image.Image:
    """Le fond d'une brillante : le décor du chapitre, sinon un halo de la rareté."""
    color = _color(card.rarity)
    path = card_loader.decor_path(card.chapter)
    if path is not None:
        with Image.open(path) as source:
            backdrop = _cover(source.convert("RGB"), size).convert("RGBA")
        return Image.blend(backdrop, Image.new("RGBA", size, (*_shade(color, 0.3), 255)), 0.3)
    backdrop = _gradient(size, _shade(color, 0.7), _shade(color, 0.12))
    halo = Image.new("L", size, 0)
    ImageDraw.Draw(halo).ellipse((-60, 40, size[0] + 60, 400), fill=150)
    backdrop.alpha_composite(Image.merge("RGBA", (*Image.new("RGB", size, _shade(color, 1.4)).split(),
                                                  halo.filter(ImageFilter.GaussianBlur(60)))))
    draw_sakura_petals(backdrop, seed=card.number, count=10, size_range=(26, 50))
    return backdrop


def _shifted_cover(art: Image.Image, size: tuple[int, int], shift: int = 36) -> Image.Image:
    """L'illustration couvre la carte, un peu descendue (le nom ne mange pas
    la tête) ; le haut découvert est une extension floue de l'image."""
    cover = _cover(art, size)
    out = cover.filter(ImageFilter.GaussianBlur(14))
    out.alpha_composite(cover.crop((0, 0, size[0], size[1] - shift)), (0, shift))
    return out


def _full_art(card: cs.CardDef) -> tuple[Image.Image, Image.Image | None]:
    """L'illustration pleine carte (RGB) et, pour un personnage détouré, son
    masque (le foil le touche moins)."""
    size = (W, H)
    own = card_loader.full_art_path(card)
    if own is not None:                          # l'illustration pleine carte de l'auteur
        with Image.open(own) as source:
            art = source.convert("RGBA")
        canvas = _backdrop(card, size)
        canvas.alpha_composite(_cover(art, size))
        return canvas.convert("RGB"), None
    canvas = _backdrop(card, size)
    path = card_loader.art_path(card)
    if path is None:
        draw = ImageDraw.Draw(canvas)
        draw.text((W / 2, H / 2 - 40), "?", font=_bangers(200), anchor="mm", fill=(255, 255, 255, 120))
        return canvas.convert("RGB"), None
    with Image.open(path) as source:
        art = source.convert("RGBA")
    if not _is_sprite(art):                      # illustration : elle couvre tout
        canvas.alpha_composite(_shifted_cover(art, size))
        return canvas.convert("RGB"), None
    art.thumbnail((W - 24, 300), Image.LANCZOS)  # personnage détouré, en grand sur le décor
    x, y = (W - art.width) // 2, 360 - art.height
    alpha = art.getchannel("A")
    placed = Image.new("L", size, 0)
    placed.paste(alpha, (x, y))
    rim = placed.filter(ImageFilter.GaussianBlur(10)).point(lambda v: int(v * 0.75))
    canvas.alpha_composite(Image.merge("RGBA", (*Image.new("RGB", size, (255, 232, 248)).split(), rim)))
    shadow = Image.new("L", size, 0)
    ImageDraw.Draw(shadow).ellipse((x + art.width * 0.12, 342, x + art.width * 0.88, 372), fill=170)
    canvas.alpha_composite(Image.merge("RGBA", (*Image.new("RGB", size, (0, 0, 0)).split(),
                                                shadow.filter(ImageFilter.GaussianBlur(8)))))
    canvas.alpha_composite(art, (x, y))
    return canvas.convert("RGB"), placed


_BASES: OrderedDict[tuple, tuple[Image.Image, Image.Image | None]] = OrderedDict()


def _foil_base(card: cs.CardDef) -> tuple[Image.Image, Image.Image | None]:
    """L'illustration pleine carte, gardée pour les images de l'animation."""
    key = _render_key(card, True)
    hit = _BASES.get(key)
    if hit is None:
        hit = _BASES[key] = _full_art(card)
        while len(_BASES) > 4:
            _BASES.popitem(last=False)
    else:
        _BASES.move_to_end(key)
    return hit


def _brillante_face(card: cs.CardDef, phase: float = STILL_PHASE,
                    base: tuple[Image.Image, Image.Image | None] | None = None) -> Image.Image:
    color = _color(card.rarity)
    rgb, sprite = base or _foil_base(card)
    image = _foil(rgb, phase, sprite).convert("RGBA")
    _glitter(image, card.number, phase)
    shade = Image.linear_gradient("L").resize((W, 120)).point(lambda v: int((255 - v) * 0.75))
    top = Image.new("RGBA", (W, H), (10, 6, 18, 0))
    mask = Image.new("L", (W, H), 0)
    mask.paste(shade, (0, 0))
    top.putalpha(mask)
    image.alpha_composite(top)
    if card.rarity == "mythic":
        draw_sakura_petals(image, seed=card.number + 7, count=12, size_range=(18, 34))
    # Panneau de verre dépoli
    box = FOIL_PANEL
    glass = image.crop(box).filter(ImageFilter.GaussianBlur(7))
    glass = Image.blend(glass, Image.new("RGBA", glass.size, (14, 8, 24, 255)), 0.58)
    image.paste(glass, box[:2], _rounded_mask(glass.size, 14))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(box, radius=14, outline=(255, 226, 150, 210), width=1)
    # Nom, numéro, sous-titre, rareté
    name_font = _fit(draw, card.name, W - 110, 36, 20)
    draw.text((24, 40), card.name, font=name_font, anchor="lm", fill=(255, 255, 255), stroke_width=3, stroke_fill=INK)
    draw.text((W - 24, 40), f"#{card.number:02d}", font=_bangers(24), anchor="rm", fill=_shade(color, 1.35),
              stroke_width=3, stroke_fill=INK)
    label = cs.RARITY_LABELS.get(card.rarity, "").upper()
    label_font = try_font(13, bold=True)
    room = W - 49 - draw.textlength(label, font=label_font) - 12
    subtitle = card.title
    while subtitle and draw.textlength(subtitle, font=label_font) > room:
        subtitle = subtitle[:-1]
    if subtitle != card.title:
        subtitle = subtitle.rstrip() + "…"
    draw.text((25, 68), subtitle, font=label_font, anchor="lm", fill=(240, 235, 250), stroke_width=2, stroke_fill=INK)
    draw.text((W - 24, 68), label, font=label_font, anchor="rm", fill=_shade(color, 1.35), stroke_width=2,
              stroke_fill=INK)
    # Effet, ambiance, pied
    effect_font = try_font(15, bold=True)
    lines = _wrap(draw, cs.effect_text(card), effect_font, box[2] - box[0] - 24, 3)
    for i, line in enumerate(lines):
        draw.text((box[0] + 12, box[1] + 12 + 19 * i), line, font=effect_font, fill=(255, 250, 255))
    flavor_font = try_font(12)
    flavor_top = box[1] + 16 + 19 * len(lines)
    for i, line in enumerate(_wrap(draw, card.flavor, flavor_font, box[2] - box[0] - 24, 2)):
        draw.text((box[0] + 12, flavor_top + 15 * i), line, font=flavor_font, fill=(220, 210, 236))
    draw.text((box[0] + 12, box[3] - 14), _footer(card), font=try_font(12), anchor="lm", fill=(190, 180, 210))
    _star(draw, box[2] - 96, box[3] - 14, 8, GOLD)
    draw.text((box[2] - 84, box[3] - 14), "BRILLANTE", font=try_font(12, bold=True), anchor="lm", fill=GOLD)
    _foil_border(image, phase)
    image.putalpha(ImageChops.multiply(image.getchannel("A"), _rounded_mask((W, H), RADIUS)))
    return image


def _face(card: cs.CardDef, brillante: bool) -> Image.Image:
    return _brillante_face(card) if brillante else _normal_face(card)


# ------------------------------------------------------ mémoire des faces --
def _stamp(path: Path | None) -> tuple[str, float]:
    if path is None:
        return ("", 0.0)
    try:
        return (str(path), path.stat().st_mtime)
    except OSError:
        return (str(path), 0.0)


def _render_key(card: cs.CardDef, brillante: bool) -> tuple:
    """Tout ce qui change l'image d'une carte : sa fiche, ses images, le décor
    de son chapitre et la série (numéro, nombre de cartes)."""
    series = card_loader.get_series()
    return (json.dumps(asdict(card), sort_keys=True, ensure_ascii=False), brillante,
            _stamp(card_loader.art_path(card)), _stamp(card_loader.full_art_path(card) if brillante else None),
            _stamp(card_loader.decor_path(card.chapter)), series.number, series.total)


def render_version(card: cs.CardDef, brillante: bool = False) -> str:
    """Empreinte courte de l'image d'une carte (pour les liens du site admin)."""
    import hashlib

    return hashlib.sha1(repr(_render_key(card, brillante)).encode()).hexdigest()[:12]


_FACES: OrderedDict[tuple, bytes] = OrderedDict()
#: Faces gardées en mémoire (PNG compressés, ~100 à 250 Ko chacune).
FACE_CACHE = 160


def _face_png(card: cs.CardDef, brillante: bool) -> bytes:
    key = _render_key(card, brillante)
    data = _FACES.get(key)
    if data is None:
        data = _FACES[key] = _png(_face(card, brillante))
        while len(_FACES) > FACE_CACHE:
            _FACES.popitem(last=False)
    else:
        _FACES.move_to_end(key)
    return data


def card_face(card: cs.CardDef, brillante: bool = False, size: tuple[int, int] | None = None) -> Image.Image:
    """La face de la carte (RGBA), à sa taille ou réduite."""
    image = _open(_face_png(card, brillante or card.always_brillante))
    return image if size is None else image.resize(size, Image.LANCZOS)


def card_png(card: cs.CardDef, brillante: bool = False) -> bytes:
    return _face_png(card, brillante or card.always_brillante)


def holo_frames(card: cs.CardDef, frames: int = HOLO_FRAMES, size: tuple[int, int] | None = None) -> list[Image.Image]:
    """Les images d'une brillante qui scintille (une période du foil)."""
    base = _foil_base(card)
    images = [_brillante_face(card, i / frames, base) for i in range(frames)]
    return images if size is None else [image.resize(size, Image.LANCZOS) for image in images]


_GIFS: OrderedDict[tuple, bytes] = OrderedDict()
#: Animations gardées en mémoire (~1,5 à 2 Mo chacune).
GIF_CACHE = 6


def card_gif(card: cs.CardDef, frames: int = HOLO_FRAMES) -> bytes:
    """Une brillante qui scintille, en boucle : le prisme glisse, le reflet
    passe, les paillettes s'allument."""
    key = (_render_key(card, True), frames)
    data = _GIFS.get(key)
    if data is not None:
        _GIFS.move_to_end(key)
        return data
    images = [image.convert("RGB") for image in holo_frames(card, frames)]
    picks = sorted({0, len(images) // 3, 2 * len(images) // 3})
    source = Image.new("RGB", (W * len(picks), H))
    for k, index in enumerate(picks):
        source.paste(images[index], (k * W, 0))
    palette = source.quantize(colors=256, method=Image.Quantize.MEDIANCUT)
    quantized = [image.quantize(palette=palette, dither=Image.Dither.NONE) for image in images]
    buffer = io.BytesIO()
    quantized[0].save(buffer, format="GIF", save_all=True, append_images=quantized[1:],
                      duration=HOLO_FRAME_MS, loop=0, optimize=False)
    data = _GIFS[key] = buffer.getvalue()
    while len(_GIFS) > GIF_CACHE:
        _GIFS.popitem(last=False)
    return data


# ------------------------------------------------------------------ le dos --
@lru_cache(maxsize=4)
def _back_png(size: tuple[int, int], stamp: tuple[str, float] = ("", 0.0)) -> bytes:
    back = Path(stamp[0]) if stamp[0] else None
    if back is not None and back.is_file():
        with Image.open(back) as source:
            image = _cover(source.convert("RGBA"), size)
    else:
        image = _gradient(size, (64, 34, 92), (18, 12, 32))
        draw_sakura_petals(image, seed=3, count=10, size_range=(size[0] // 9, size[0] // 5))
        draw = ImageDraw.Draw(image)
        cx, cy, r = size[0] / 2, size[1] * 0.44, size[0] * 0.2
        for i in range(5):
            angle = math.radians(-90 + i * 72)
            px, py = cx + r * 0.62 * math.cos(angle), cy + r * 0.62 * math.sin(angle)
            draw.ellipse((px - r * 0.42, py - r * 0.42, px + r * 0.42, py + r * 0.42), fill=(255, 176, 205, 235))
        draw.ellipse((cx - r * 0.2, cy - r * 0.2, cx + r * 0.2, cy + r * 0.2), fill=GOLD)
        draw.text((cx, size[1] * 0.74), "SAKURA", font=_bangers(max(14, size[0] // 7)), anchor="mm", fill=GOLD)
        draw.text((cx, size[1] * 0.83), "LEVELING", font=_bangers(max(10, size[0] // 12)), anchor="mm",
                  fill=(230, 210, 240))
    draw = ImageDraw.Draw(image)
    radius = max(8, int(RADIUS * size[0] / W))
    draw.rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=radius, outline=GOLD, width=3)
    image.putalpha(ImageChops.multiply(image.getchannel("A"), _rounded_mask(size, radius)))
    return _png(image)


def card_back(size: tuple[int, int] = (W, H)) -> Image.Image:
    back = card_loader.BACK_FILE
    return _open(_back_png(size, _stamp(back) if back.is_file() else ("", 0.0)))


# ----------------------------------------------------------------- l'album --
TILE = (220, 308)


def _badge(draw, xy: tuple[int, int], text: str, fill, color=(255, 255, 255)) -> None:
    font = try_font(16, bold=True)
    width = int(draw.textlength(text, font=font)) + 16
    x, y = xy
    draw.rounded_rectangle((x - width, y, x, y + 24), radius=12, fill=fill)
    draw.text((x - width / 2, y + 12), text, font=font, anchor="mm", fill=color)


def missing_tile(card: cs.CardDef, size: tuple[int, int] = TILE) -> Image.Image:
    """Une carte qu'on n'a pas : sa silhouette, son nom et sa rareté."""
    color = _color(card.rarity)
    tile = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(tile)
    draw.rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=14, fill=(30, 26, 42, 255),
                           outline=_shade(color, 0.75), width=2)
    art = card_loader.art_path(card)
    if art is not None:
        from app.bot.rendering.silhouette import silhouette_png

        shape = _open(silhouette_png(art))
        shape.thumbnail((size[0] - 40, size[1] - 110), Image.LANCZOS)
        tile.alpha_composite(shape, ((size[0] - shape.width) // 2, 44))
    else:
        draw.text((size[0] / 2, size[1] / 2 - 10), "?", font=_bangers(96), anchor="mm", fill=(*_shade(color, 0.8), 200))
    draw.text((12, 18), f"#{card.number:02d}", font=try_font(15, bold=True), anchor="lm", fill=_shade(color, 1.1))
    name_font = _fit(draw, card.name, size[0] - 20, 22, 13)
    draw.text((size[0] / 2, size[1] - 46), card.name, font=name_font, anchor="mm", fill=(150, 140, 170))
    draw.text((size[0] / 2, size[1] - 22), cs.RARITY_LABELS.get(card.rarity, ""), font=try_font(13, bold=True),
              anchor="mm", fill=_shade(color, 0.95))
    return tile


def owned_tile(card: cs.CardDef, normal: int, brillante: int, size: tuple[int, int] = TILE) -> Image.Image:
    tile = card_face(card, brillante > 0, size)
    draw = ImageDraw.Draw(tile)
    total = normal + brillante
    if total > 1:
        _badge(draw, (size[0] - 8, size[1] - 34), f"×{total}", (20, 16, 30, 230))
    if brillante and not card.always_brillante:
        _badge(draw, (size[0] - 8, 8), f"✦ {brillante}" if brillante > 1 else "✦", (120, 90, 20, 235), GOLD)
    return tile


def compose_album_page(cards: list[cs.CardDef], normal: dict[str, int], brillante: dict[str, int],
                       title: str, subtitle: str) -> bytes:
    columns = 3
    rows = max(1, math.ceil(len(cards) / columns))
    gap, margin, header = 14, 20, 74
    width = margin * 2 + columns * TILE[0] + (columns - 1) * gap
    height = header + margin + rows * TILE[1] + (rows - 1) * gap
    page = _gradient((width, height), (52, 30, 70), (16, 12, 26))
    draw_sakura_petals(page, seed=len(cards) + rows, count=14, size_range=(30, 60))
    draw = ImageDraw.Draw(page)
    draw.text((margin, 30), title, font=_bangers(36), anchor="lm", fill=(255, 255, 255))
    draw.text((margin, 60), subtitle, font=try_font(15), anchor="lm", fill=(220, 205, 235))
    for index, card in enumerate(cards):
        x = margin + (index % columns) * (TILE[0] + gap)
        y = header + (index // columns) * (TILE[1] + gap)
        n, b = normal.get(card.code, 0), brillante.get(card.code, 0)
        tile = owned_tile(card, n, b) if (n or b) else missing_tile(card)
        page.alpha_composite(tile, (x, y))
    return _png(page.convert("RGB"))


# --------------------------------------------------------------- un booster --
SMALL = (180, 252)


def _ribbon(draw, cx: float, y: float, text: str, fill) -> None:
    font = _bangers(20)
    width = draw.textlength(text, font=font) + 18
    draw.rounded_rectangle((cx - width / 2, y, cx + width / 2, y + 26), radius=13, fill=fill)
    draw.text((cx, y + 13), text, font=font, anchor="mm", fill=(255, 255, 255))


def _layout(count: int) -> tuple[tuple[int, int], list[tuple[int, int]]]:
    gap, margin, top = 12, 16, 40
    width = margin * 2 + count * SMALL[0] + (count - 1) * gap
    positions = [(margin + i * (SMALL[0] + gap), top) for i in range(count)]
    return (width, top + SMALL[1] + 16), positions


def _stage(size: tuple[int, int]) -> Image.Image:
    stage = _gradient(size, (46, 26, 64), (14, 10, 24))
    draw_sakura_petals(stage, seed=11, count=10, size_range=(26, 50))
    return stage


def _labels(image: Image.Image, opened, positions) -> None:
    draw = ImageDraw.Draw(image)
    for (x, y), card in zip(positions, opened):
        cx = x + SMALL[0] / 2
        if card.new:
            _ribbon(draw, cx, y - 34, "NOUVELLE !", (215, 70, 120))
        elif card.new_brillante:
            _ribbon(draw, cx, y - 34, "1re BRILLANTE !", (170, 120, 30))


def compose_booster_result(opened) -> bytes:
    """Les 5 cartes d'un booster, de la moins rare à la plus rare."""
    size, positions = _layout(len(opened))
    image = _stage(size)
    for (x, y), card in zip(positions, opened):
        image.alpha_composite(card_face(card.card, card.brillante, SMALL), (x, y))
    _labels(image, opened, positions)
    return _png(image.convert("RGB"))


def compose_many(opened, limit: int = 15) -> bytes:
    """Plusieurs boosters : les cartes obtenues (sans doublon), les plus rares
    d'abord, avec leur nombre."""
    counts: dict[tuple[str, bool], int] = {}
    first: dict[tuple[str, bool], object] = {}
    for card in opened:
        key = (card.card.code, card.brillante)
        counts[key] = counts.get(key, 0) + 1
        first.setdefault(key, card)
    ordered = sorted(first.values(), key=lambda c: (-cs.rarity_index(c.card.rarity), not c.brillante,
                                                     not c.new, c.card.number))[:limit]
    columns = 5
    rows = max(1, math.ceil(len(ordered) / columns))
    tile = (150, 210)
    gap, margin, top = 12, 16, 40
    width = margin * 2 + columns * tile[0] + (columns - 1) * gap
    height = top + rows * (tile[1] + 40) + 8
    image = _stage((width, height))
    draw = ImageDraw.Draw(image)
    for index, card in enumerate(ordered):
        x = margin + (index % columns) * (tile[0] + gap)
        y = top + (index // columns) * (tile[1] + 40)
        image.alpha_composite(card_face(card.card, card.brillante, tile), (x, y))
        count = counts[(card.card.code, card.brillante)]
        if count > 1:
            _badge(draw, (x + tile[0] - 6, y + tile[1] - 30), f"×{count}", (20, 16, 30, 230))
        if card.new:
            _ribbon(draw, x + tile[0] / 2, y - 32, "NOUVELLE !", (215, 70, 120))
        elif card.new_brillante:
            _ribbon(draw, x + tile[0] / 2, y - 32, "1re BRILLANTE !", (170, 120, 30))
    return _png(image.convert("RGB"))


# --------------------------------------------------------- l'animation GIF --
#: Une brillante qui vient de se retourner scintille (demi-période du foil).
SHIMMER_FRAMES = 8
SHIMMER_MS = 70


def _glow(color, alpha: int) -> Image.Image:
    pad = 28
    size = (SMALL[0] + 2 * pad, SMALL[1] + 2 * pad)
    glow = Image.new("RGBA", size, (*color, 0))
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((pad - 6, pad - 6, size[0] - pad + 6, size[1] - pad + 6), radius=20,
                                           fill=alpha)
    glow.putalpha(mask.filter(ImageFilter.GaussianBlur(12)))
    return glow


def _rays(size: tuple[int, int], center: tuple[float, float], color, alpha: int, turn: float) -> Image.Image:
    layer = Image.new("RGBA", size, (*color, 0))
    draw = ImageDraw.Draw(layer)
    cx, cy = center
    length = max(size) * 0.8
    for i in range(12):
        angle = turn + i * math.pi / 6
        a1, a2 = angle - 0.07, angle + 0.07
        draw.polygon([(cx, cy), (cx + length * math.cos(a1), cy + length * math.sin(a1)),
                      (cx + length * math.cos(a2), cy + length * math.sin(a2))], fill=(*color, alpha))
    return layer.filter(ImageFilter.GaussianBlur(3))


class _Gif:
    """Images quantifiées sur une palette commune ; ce qui ne change pas
    d'une image à l'autre devient transparent (le GIF ne garde que ce qui
    bouge)."""

    TRANSPARENT = 255

    def __init__(self, palette_source: Image.Image) -> None:
        base = palette_source.convert("RGB").quantize(colors=255, method=Image.Quantize.MEDIANCUT)
        colors = base.getpalette()[:765]
        colors += [0] * (765 - len(colors))
        self.colors = colors + [255, 0, 255]
        self.palette = Image.new("P", (1, 1))
        self.palette.putpalette(colors + [0, 0, 0])
        self.frames: list[Image.Image] = []
        self.durations: list[int] = []
        self._previous: Image.Image | None = None

    def push(self, image: Image.Image, ms: int) -> None:
        q = image.convert("RGB").quantize(palette=self.palette, dither=Image.Dither.NONE)
        q.putpalette(self.colors)
        previous, self._previous = self._previous, q
        if previous is not None:
            same = ImageChops.difference(Image.frombytes("L", q.size, q.tobytes()),
                                         Image.frombytes("L", q.size, previous.tobytes()))
            mask = same.point(lambda v: 255 if v == 0 else 0)
            q = q.copy()
            q.paste(self.TRANSPARENT, mask=mask)
        self.frames.append(q)
        self.durations.append(ms)

    def bytes(self) -> bytes:
        buffer = io.BytesIO()
        self.frames[0].save(buffer, format="GIF", save_all=True, append_images=self.frames[1:],
                            duration=self.durations, disposal=1, transparency=self.TRANSPARENT, optimize=False)
        return buffer.getvalue()


def animate_booster(opened) -> bytes | None:
    """L'ouverture d'UN booster, en GIF joué une fois (None : trop lourd)."""
    size, positions = _layout(len(opened))
    stage = _stage(size)
    back = card_back(SMALL)
    faces = [card_face(c.card, c.brillante, SMALL) for c in opened]
    final = stage.copy()
    for (x, y), face in zip(positions, faces):
        final.alpha_composite(face, (x, y))
    _labels(final, opened, positions)
    backs = stage.copy()
    for x, y in positions:
        backs.alpha_composite(back, (x, y))
    swatch = Image.new("RGB", (size[0], 40))
    draw = ImageDraw.Draw(swatch)
    for i, color in enumerate([*(cs.CARD_RARITY_COLORS[r] for r in cs.RARITIES), GOLD, PINK, (255, 255, 255)]):
        draw.rectangle((i * 40, 0, i * 40 + 39, 39), fill=color)
    source = Image.new("RGB", (size[0], size[1] * 2 + 40))
    source.paste(final.convert("RGB"), (0, 0))
    source.paste(backs.convert("RGB"), (0, size[1]))
    source.paste(swatch, (0, size[1] * 2))
    gif = _Gif(source)

    revealed: list[bool] = [False] * len(opened)

    def frame(under: Callable[[Image.Image], None] | None = None,
              over: Callable[[Image.Image], None] | None = None,
              hide: int | None = None, offset: tuple[int, int] = (0, 0)) -> Image.Image:
        """Une image : le décor, `under` (lueur, rayons), les cartes (sauf
        `hide`), puis `over` (carte qui se retourne, pétales, reflet)."""
        image = stage.copy()
        if under is not None:
            under(image)
        for i, ((x, y), face) in enumerate(zip(positions, faces)):
            if i != hide:
                image.alpha_composite(face if revealed[i] else back, (x + offset[0], y + offset[1]))
        if over is not None:
            over(image)
        return image

    # 1. Les cartes arrivent face cachée.
    start = (size[0] // 2 - SMALL[0] // 2, size[1])
    for step in range(1, 6):
        t = step / 5
        image = stage.copy()
        for x, y in positions:
            image.alpha_composite(back, (int(start[0] + (x - start[0]) * t), int(start[1] + (y - start[1]) * t)))
        gif.push(image, 70)
    gif.push(frame(), 300)

    # 2. Chacune s'allume puis se retourne, la meilleure en dernier.
    last = len(opened) - 1
    for i, card in enumerate(opened):
        color = _color(card.card.rarity)
        x, y = positions[i]
        rank = cs.rarity_index(card.card.rarity)
        pulses = 2 + (rank >= 2) + (rank >= 3) + (rank >= 4) * 2 + (i == last) * 2
        for p in range(pulses):
            alpha = 90 + int(150 * (p + 1) / pulses)

            def lit(image, alpha=alpha, color=color, x=x, y=y):
                image.alpha_composite(_glow(color, alpha), (x - 28, y - 28))
            gif.push(frame(under=lit), 150 if i == last else 90)

        for scale, face in ((0.55, False), (0.12, False), (0.12, True), (0.55, True)):
            def flip(image, scale=scale, face=face, x=x, y=y, i=i):
                width = max(2, int(SMALL[0] * scale))
                squeezed = (faces[i] if face else back).resize((width, SMALL[1]), Image.BILINEAR)
                image.alpha_composite(squeezed, (x + (SMALL[0] - width) // 2, y))
            gif.push(frame(over=flip, hide=i), 45)
        revealed[i] = True
        gif.push(frame(), 120)
        cx, cy = x + SMALL[0] / 2, y + SMALL[1] / 2
        if card.card.rarity in cs.TOP_RARITIES:
            burst = GOLD if card.card.rarity == "legendary" else PINK
            for k in range(4):
                shake = ((-6, 4), (5, -5), (-3, 2), (0, 0))[k] if card.card.rarity == "mythic" else (0, 0)

                def rays(image, k=k, burst=burst, cx=cx, cy=cy):
                    image.alpha_composite(_rays(size, (cx, cy), burst, 150 - 30 * k, k * 0.12))
                gif.push(frame(under=rays, offset=shake), 90)
            if card.card.rarity == "mythic":
                for k in range(4):
                    def petals(image, k=k):
                        draw_sakura_petals(image, seed=40 + k, count=18, size_range=(22, 44))
                    gif.push(frame(over=petals), 110)
        if card.brillante:
            # Le foil prend la lumière : le prisme glisse, le reflet passe.
            shimmer = holo_frames(card.card, SHIMMER_FRAMES * 2, SMALL)[:SHIMMER_FRAMES]
            for still in shimmer:
                def shine(image, still=still, x=x, y=y):
                    image.alpha_composite(still, (x, y))
                gif.push(frame(over=shine, hide=i), SHIMMER_MS)
    # 3. Le résultat, avec les rubans « NOUVELLE ! ».
    gif.push(final, 4000)
    data = gif.bytes()
    return data if len(data) <= MAX_GIF_BYTES else None


def animation_seconds(opened) -> float:
    """Durée approximative de l'animation (pour la remplacer ensuite)."""
    total = 0.65 + 0.3
    for i, card in enumerate(opened):
        rank = cs.rarity_index(card.card.rarity)
        pulses = 2 + (rank >= 2) + (rank >= 3) + (rank >= 4) * 2 + (i == len(opened) - 1) * 2
        total += pulses * (0.15 if i == len(opened) - 1 else 0.09) + 0.18 + 0.12
        if card.card.rarity in cs.TOP_RARITIES:
            total += 0.36 + (0.44 if card.card.rarity == "mythic" else 0)
        if card.brillante:
            total += SHIMMER_FRAMES * SHIMMER_MS / 1000
    return total + 1.5
