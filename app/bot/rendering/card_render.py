"""Visuels des cartes à collectionner (09/11/2026) : la carte, son dos,
l'album, le résultat d'un booster et son animation d'ouverture (GIF).

Même direction artistique que la bannière /profil : cadre à la couleur de la
rareté (celles de l'équipement), Bangers pour les noms, pétales en filigrane.
Une BRILLANTE porte un reflet holographique et des éclats ; la mythique l'est
toujours. Les faces sont gardées en mémoire (PNG compressés) et refaites quand
l'image de la carte change.

L'ouverture : les cartes arrivent face cachée, chacune s'allume à la couleur
de sa rareté avant de se retourner, de la moins rare à la plus rare — la
dernière se fait attendre ; éclat de lumière pour un légendaire, pétales et
tremblement pour la mythique, reflet qui passe sur une brillante.
"""

from __future__ import annotations

import colorsys
import io
import math
import random
from collections import OrderedDict
from collections.abc import Callable
from functools import lru_cache

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
BACK_FILE = card_loader.CARD_ART / "_dos.png"
#: Décor du cadre de l'image, par chapitre (sinon un dégradé).
LANDSCAPES = {
    "clairiere": "clairiere_sinistre.png",
    "cimetiere": "cimetiere_abandonne_lumiere.png",
    "berceau": "berceau_cataclysmique.png",
    "divinites": "horizon_celeste.png",
    "legendes": "fracture_elementaire.png",
}
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
    landscape = LANDSCAPES.get(card.chapter)
    path = ASSETS / "landscapes" / landscape if landscape else None
    if path is not None and path.is_file():
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


def _holo(phase: float, size: tuple[int, int] = (W, H)) -> Image.Image:
    """Reflet holographique : arc-en-ciel en diagonale et bande de lumière."""
    small = Image.new("RGB", (48, 48))
    for y in range(48):
        for x in range(48):
            r, g, b = colorsys.hsv_to_rgb(((x + y) / 96 + phase) % 1.0, 0.5, 1.0)
            small.putpixel((x, y), (int(r * 255), int(g * 255), int(b * 255)))
    layer = small.resize(size, Image.BILINEAR).convert("RGBA")
    layer.putalpha(52)
    w, h = size
    band = Image.new("L", size, 0)
    center = int(phase % 1.0 * (w + h)) - h // 2
    ImageDraw.Draw(band).polygon([(center, 0), (center + 60, 0), (center + 60 - h, h), (center - h, h)], fill=110)
    shine = Image.new("RGBA", size, (255, 255, 255, 0))
    shine.putalpha(band.filter(ImageFilter.GaussianBlur(16)))
    layer.alpha_composite(shine)
    return layer


def _sparkles(image: Image.Image, seed: int, count: int = 6) -> None:
    rng = random.Random(seed)
    draw = ImageDraw.Draw(image)
    w, h = image.size
    for _ in range(count):
        _star(draw, rng.uniform(20, w - 20), rng.uniform(20, h - 20), rng.uniform(5, 11),
              (255, 255, 255, rng.randint(170, 240)))


def _face(card: cs.CardDef, brillante: bool, holo_phase: float = 0.3) -> Image.Image:
    color = _color(card.rarity)
    image = _gradient((W, H), _shade(color, 1.15), _shade(color, 0.55))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, W - 1, H - 1), radius=RADIUS, outline=GOLD if brillante else _shade(color, 1.4),
                           width=4 if brillante else 3)
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
    draw.text((26, H - 28), f"Série 1 · {card.number}/61", font=try_font(12), anchor="lm", fill=(150, 140, 170))
    if brillante:
        _star(draw, W - 108, H - 28, 9, GOLD)
        draw.text((W - 96, H - 28), "BRILLANTE", font=try_font(12, bold=True), anchor="lm", fill=GOLD)
    elif element:
        draw.text((W - 26, H - 28), element, font=try_font(12, bold=True), anchor="rm", fill=(170, 160, 195))
    if brillante:
        image.alpha_composite(_holo(holo_phase))
        _sparkles(image, card.number, 7)
        if card.rarity == "mythic":
            draw_sakura_petals(image, seed=card.number + 7, count=10, size_range=(18, 34))
    image.putalpha(ImageChops.multiply(image.getchannel("A"), _rounded_mask((W, H), RADIUS)))
    return image


def _art_stamp(card: cs.CardDef) -> float:
    path = card_loader.art_path(card)
    try:
        return path.stat().st_mtime if path else 0.0
    except OSError:
        return 0.0


_FACES: OrderedDict[tuple, bytes] = OrderedDict()
#: Faces gardées en mémoire (PNG compressés, ~100 Ko chacune).
FACE_CACHE = 160


def _face_png(card: cs.CardDef, brillante: bool, stamp: float) -> bytes:
    key = (card.code, card.number, card.rarity, card.name, brillante, stamp)
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
    image = _open(_face_png(card, brillante or card.always_brillante, _art_stamp(card)))
    return image if size is None else image.resize(size, Image.LANCZOS)


def card_png(card: cs.CardDef, brillante: bool = False) -> bytes:
    return _face_png(card, brillante or card.always_brillante, _art_stamp(card))


def card_gif(card: cs.CardDef, frames: int = 14) -> bytes:
    """Une brillante qui scintille : le reflet passe sur la carte (en boucle)."""
    images = [_face(card, True, holo_phase=i / frames).convert("RGB") for i in range(frames)]
    palette = images[0].quantize(colors=255, method=Image.Quantize.MEDIANCUT)
    quantized = [img.quantize(palette=palette, dither=Image.Dither.NONE) for img in images]
    buffer = io.BytesIO()
    quantized[0].save(buffer, format="GIF", save_all=True, append_images=quantized[1:],
                      duration=90, loop=0, optimize=False)
    return buffer.getvalue()


# ------------------------------------------------------------------ le dos --
@lru_cache(maxsize=4)
def _back_png(size: tuple[int, int]) -> bytes:
    if BACK_FILE.is_file():
        with Image.open(BACK_FILE) as source:
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
    return _open(_back_png(size))


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
            for k in range(3):
                def shine(image, k=k, x=x, y=y, i=i):
                    face = faces[i].copy()
                    face.alpha_composite(_holo(0.15 + k * 0.3, SMALL))
                    face.putalpha(faces[i].getchannel("A"))
                    image.alpha_composite(face, (x, y))
                gif.push(frame(over=shine), 80)
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
            total += 0.24
    return total + 1.5
