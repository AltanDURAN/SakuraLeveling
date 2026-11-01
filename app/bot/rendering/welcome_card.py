"""Carte de bienvenue (31/10/2026, demande de l'auteur : « c'est la première
chose qu'on voit en rejoignant le serveur, il faut que ça donne envie »).

Le ciel du Grand Cerisier (`horizon_celeste.png`, la bande du soleil et de la
cité, sans le cadre du décor), l'avatar du nouveau venu cerclé de rose,
« BIENVENUE » en Bangers et son numéro d'aventurier. Pétales en filigrane.
"""

from __future__ import annotations

import io
import math
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from app.bot.rendering.image_utils import crop_to_circle, download_image
from app.bot.rendering.pillow_utils import draw_sakura_petals, try_font
from app.shared.paths import ASSETS_DIR, LANDSCAPES_ASSETS_DIR

WIDTH = 1200
HEIGHT = 540

BACKGROUND = LANDSCAPES_ASSETS_DIR / "horizon_celeste.png"
#: Bande du décor (1024 × 1536) retenue : le soleil et la cité, sans le cadre.
_BAND = (0, 520, 1024, 1000)
_FONT_PATH = ASSETS_DIR / "fonts" / "Bangers-Regular.ttf"

_PINK = (255, 150, 195)
_GOLD = (255, 214, 120)
_TEXT = (255, 250, 252, 255)
_MUTED = (238, 220, 236, 255)
_AVATAR = 196


@lru_cache(maxsize=8)
def _bangers(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype(str(_FONT_PATH), size)
    except Exception:
        return try_font(size, bold=True)


def _background() -> Image.Image:
    try:
        bg = Image.open(BACKGROUND).convert("RGBA").crop(_BAND)
        bg = bg.resize((WIDTH, round(WIDTH * bg.height / bg.width)), Image.LANCZOS)
        top = (bg.height - HEIGHT) // 2
        bg = bg.crop((0, top, WIDTH, top + HEIGHT))
    except Exception:
        bg = Image.new("RGBA", (WIDTH, HEIGHT), (58, 34, 78, 255))
    # Voile sombre, plus marqué en bas (le texte) et sur les bords.
    veil = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    d = ImageDraw.Draw(veil)
    for y in range(HEIGHT):
        t = y / HEIGHT
        d.line((0, y, WIDTH, y), fill=(18, 8, 30, int(70 + 130 * t ** 1.6)))
    bg.alpha_composite(veil)
    edges = Image.new("L", (WIDTH, HEIGHT), 0)
    ImageDraw.Draw(edges).ellipse((-WIDTH * 0.15, -HEIGHT * 0.4, WIDTH * 1.15, HEIGHT * 1.3), fill=255)
    edges = edges.filter(ImageFilter.GaussianBlur(90))
    dark = Image.new("RGBA", (WIDTH, HEIGHT), (10, 4, 20, 170))
    dark.putalpha(Image.eval(edges, lambda v: 170 - v * 170 // 255))
    bg.alpha_composite(dark)
    return bg


def _glow_text(img: Image.Image, center_x: int, y: int, text: str, font,
               fill, glow: tuple[int, int, int], radius: int = 10) -> int:
    """Texte centré avec un halo coloré ; renvoie sa hauteur."""
    draw = ImageDraw.Draw(img)
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    x = center_x - (right - left) // 2 - left
    halo = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(halo).text((x, y), text, font=font, fill=(*glow, 230))
    img.alpha_composite(halo.filter(ImageFilter.GaussianBlur(radius)))
    draw.text((x + 3, y + 4), text, font=font, fill=(20, 6, 30, 200))
    draw.text((x, y), text, font=font, fill=fill)
    return bottom - top


def _avatar(img: Image.Image, avatar_url: str | None, center: tuple[int, int]) -> None:
    source = None
    if avatar_url:
        try:
            source = download_image(avatar_url)
        except Exception:
            source = None
    if source is None:
        source = Image.new("RGBA", (_AVATAR, _AVATAR), (120, 70, 140, 255))
    cx, cy = center
    r = _AVATAR // 2
    # Halo rose, puis double anneau (or fin à l'extérieur, rose épais).
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((cx - r - 26, cy - r - 26, cx + r + 26, cy + r + 26), fill=(*_PINK, 200))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(22)))
    d = ImageDraw.Draw(img)
    d.ellipse((cx - r - 12, cy - r - 12, cx + r + 12, cy + r + 12), fill=(*_GOLD, 255))
    d.ellipse((cx - r - 8, cy - r - 8, cx + r + 8, cy + r + 8), fill=(*_PINK, 255))
    img.alpha_composite(crop_to_circle(source, _AVATAR), (cx - r, cy - r))
    # Une fleur de cerisier posée sur l'anneau, en bas à droite.
    fx, fy = cx + int(r * math.cos(math.radians(40))) + 6, cy + int(r * math.sin(math.radians(40))) + 6
    for i in range(5):
        a = math.radians(-90 + i * 72)
        px, py = fx + 13 * math.cos(a), fy + 13 * math.sin(a)
        d.ellipse((px - 12, py - 12, px + 12, py + 12), fill=(255, 196, 220, 255), outline=(214, 92, 150, 255), width=2)
    d.ellipse((fx - 6, fy - 6, fx + 6, fy + 6), fill=(*_GOLD, 255))


def _ordinal(n: int) -> str:
    return "1er" if n == 1 else f"{n:,}e".replace(",", " ")


def compose_welcome_card(display_name: str, avatar_url: str | None,
                         member_number: int | None = None) -> bytes:
    """PNG de la carte de bienvenue."""
    img = _background()
    draw_sakura_petals(img, seed=hash(display_name) & 0xFFFF, count=22, size_range=(26, 58),
                       palette=[(255, 196, 220, 110), (255, 170, 205, 95), (255, 226, 236, 90)])
    _avatar(img, avatar_url, (WIDTH // 2, 156))

    y = 278
    y += _glow_text(img, WIDTH // 2, y, "BIENVENUE", _bangers(104), (*_GOLD, 255), (255, 120, 170), 14) + 30
    name_font = try_font(46, bold=True)
    name = display_name
    while ImageDraw.Draw(img).textlength(name, font=name_font) > WIDTH - 160 and len(name) > 4:
        name = name[:-2].rstrip() + "…" if not name.endswith("…") else name[:-2] + "…"
    y += _glow_text(img, WIDTH // 2, y, name, name_font, _TEXT, (190, 80, 150), 8) + 22
    line = "au Grand Cerisier"
    if member_number:
        line = f"{_ordinal(member_number)} aventurier du Grand Cerisier"
    _glow_text(img, WIDTH // 2, y, line, try_font(30), _MUTED, (90, 30, 90), 6)

    out = io.BytesIO()
    img.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue()


def _blossom(img: Image.Image, center: tuple[int, int], radius: int) -> None:
    """Une grande fleur de cerisier (cinq pétales en cœur, cœur doré,
    étamines) et son halo."""
    cx, cy = center
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((cx - radius * 1.5, cy - radius * 1.5, cx + radius * 1.5, cy + radius * 1.5),
                                 fill=(*_PINK, 170))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(radius // 2)))
    # Chaque pétale : deux lobes (l'échancrure vient seule) et une pointe
    # vers le cœur ; posés un par un, contour rose puis pétale clair, pour
    # qu'ils se chevauchent comme une vraie fleur.
    lobe = radius * 0.3
    for i in range(5):
        a = math.radians(-90 + i * 72)
        ux, uy = math.cos(a), math.sin(a)
        shape = Image.new("L", img.size, 0)
        ds = ImageDraw.Draw(shape)
        for side in (-1, 1):
            px = cx + radius * 0.66 * ux - side * radius * 0.15 * uy
            py = cy + radius * 0.66 * uy + side * radius * 0.15 * ux
            ds.ellipse((px - lobe, py - lobe, px + lobe, py + lobe), fill=255)
        w = radius * 0.4
        ds.polygon([(cx + radius * 0.08 * ux, cy + radius * 0.08 * uy),
                    (cx + radius * 0.6 * ux - w * uy, cy + radius * 0.6 * uy + w * ux),
                    (cx + radius * 0.6 * ux + w * uy, cy + radius * 0.6 * uy - w * ux)], fill=255)
        img.paste((214, 92, 150, 255), (0, 0), shape.filter(ImageFilter.MaxFilter(5)))
        img.paste((255, 200, 224, 255), (0, 0), shape)
    d = ImageDraw.Draw(img)
    for i in range(5):     # nervure claire au milieu de chaque pétale
        a = math.radians(-90 + i * 72)
        d.line((cx + radius * 0.3 * math.cos(a), cy + radius * 0.3 * math.sin(a),
                cx + radius * 0.78 * math.cos(a), cy + radius * 0.78 * math.sin(a)), fill=(255, 228, 240, 255), width=3)
    core = radius * 0.2
    for i in range(10):    # étamines
        a = math.radians(i * 36 + 18)
        x2, y2 = cx + radius * 0.42 * math.cos(a), cy + radius * 0.42 * math.sin(a)
        d.line((cx, cy, x2, y2), fill=(214, 92, 150, 255), width=2)
        d.ellipse((x2 - 4, y2 - 4, x2 + 4, y2 + 4), fill=(*_GOLD, 255))
    d.ellipse((cx - core, cy - core, cx + core, cy + core), fill=(*_GOLD, 255), outline=(214, 150, 60, 255), width=2)


def compose_season_card(season: int, subtitle: str = "Le Grand Cerisier refleurit") -> bytes:
    """PNG de l'annonce d'une nouvelle saison (`/admin lancer_saison`)."""
    img = _background()
    draw_sakura_petals(img, seed=season * 7919, count=34, size_range=(24, 62),
                       palette=[(255, 196, 220, 120), (255, 170, 205, 105), (255, 226, 236, 100)])
    _blossom(img, (WIDTH // 2, 150), 92)

    y = 266
    y += _glow_text(img, WIDTH // 2, y, f"SAISON {season}", _bangers(132), (*_GOLD, 255), (255, 120, 170), 16) + 26
    y += _glow_text(img, WIDTH // 2, y, subtitle, try_font(44, bold=True), _TEXT, (190, 80, 150), 8) + 20
    _glow_text(img, WIDTH // 2, y, "Tout le monde repart du Rang F — la course recommence",
               try_font(28), _MUTED, (90, 30, 90), 6)

    out = io.BytesIO()
    img.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue()
