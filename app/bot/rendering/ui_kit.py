"""Briques de dessin communes aux écrans du bot (DA de `/affinites`, `/stats`,
de la bannière et des PNJ) : fond de nuit à pétales, panneaux translucides,
barres lumineuses, pastilles, texte qui tient dans sa case.

Un écran = un canevas, un en-tête, des panneaux, un pied. Tout ce qui écrit un
texte venu du jeu (pseudo, nom d'objet, quête) passe par `fit` / `clip` /
`wrap` : rien ne doit déborder, quelle que soit la longueur.
"""

from __future__ import annotations

from PIL import Image, ImageDraw, ImageFilter

from app.bot.rendering.emoji_text import draw_text_with_emojis, measure_text_with_emojis
from app.bot.rendering.pillow_utils import (
    draw_sakura_petals,
    draw_text_with_shadow,
    gradient_background,
    try_font,
)

WIDTH = 1024
PAD = 28
GAP = 16

TEXT = (245, 242, 250, 255)
MUTED = (176, 170, 194, 255)
DIM = (128, 122, 144, 255)
GOLD = (240, 196, 92)
GREEN = (120, 220, 140)
SHADOW = (0, 0, 0, 170)
LILAC = (150, 120, 210)


def canvas(height: int, seed: int = 0) -> Image.Image:
    img = gradient_background(WIDTH, height, (26, 22, 40, 255), (16, 14, 26, 255))
    draw_sakura_petals(img, seed=seed)
    return img


def lighten(color, f: float):
    return tuple(int(c + (255 - c) * f) for c in color[:3])


def panel(img, xy, size, radius=16, fill=(28, 24, 40, 205), outline=None, width=1) -> None:
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle(
        [xy, (xy[0] + size[0], xy[1] + size[1])], radius=radius, fill=fill, outline=outline, width=width)
    img.alpha_composite(layer)


def tinted_card(img, xy, size, color, radius=16) -> None:
    """Panneau sombre teinté d'une couleur, avec un liseré en haut."""
    x, y = xy
    w, h = size
    panel(img, (x, y), (w, h), radius=radius, fill=(24, 20, 36, 220), outline=(*color[:3], 110))
    tint = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(tint).rounded_rectangle([(x, y), (x + w, y + h)], radius=radius, fill=(*color[:3], 24))
    img.alpha_composite(tint)
    panel(img, (x + 14, y), (w - 28, 5), radius=3, fill=(*color[:3], 255))


def bar(img, xy, size, ratio, color, track=(60, 54, 78, 220), glow=False) -> None:
    x, y = xy
    w, h = size
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rounded_rectangle([(x, y), (x + w, y + h)], radius=h // 2, fill=track)
    filled = int(w * max(0.0, min(1.0, ratio)))
    if filled > 2:
        if glow:
            g = Image.new("RGBA", img.size, (0, 0, 0, 0))
            ImageDraw.Draw(g).rounded_rectangle([(x, y - 2), (x + filled, y + h + 2)], radius=h,
                                                fill=(*color[:3], 120))
            img.alpha_composite(g.filter(ImageFilter.GaussianBlur(5)))
        d.rounded_rectangle([(x, y), (x + filled, y + h)], radius=h // 2, fill=(*color[:3], 255))
    img.alpha_composite(layer)


def fit(draw, text: str, size: int, max_w: float, bold: bool = True, floor: int = 12):
    """La plus grande police (≤ `size`) dans laquelle `text` tient en `max_w`."""
    while size > floor and draw.textlength(text, font=try_font(size, bold=bold)) > max_w:
        size -= 1
    return try_font(size, bold=bold)


def clip(draw, text: str, font, max_w: float) -> str:
    if draw.textlength(text, font=font) <= max_w:
        return text
    while text and draw.textlength(text + "…", font=font) > max_w:
        text = text[:-1]
    return text.rstrip() + "…"


def wrap(draw, text: str, font, max_w: float, max_lines: int = 2) -> list[str]:
    """Coupe `text` en lignes de `max_w` au plus ; la dernière finit par « … »
    si le texte ne tient pas."""
    words, lines, current = (text or "").split(), [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=font) <= max_w:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word
        if len(lines) == max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) == max_lines and " ".join(lines) != " ".join(words):
        lines[-1] = clip(draw, lines[-1] + " …", font, max_w)
    return [clip(draw, line, font, max_w) for line in lines]


def chip(img, x, y, text, font, fill=(40, 32, 60, 220), outline=(*LILAC, 120), ink=TEXT, emoji=16, h=32) -> int:
    w = measure_text_with_emojis(text, font, emoji) + 28
    panel(img, (int(x), y), (int(w), h), radius=h // 2, fill=fill, outline=outline)
    draw_text_with_emojis(img, (int(x) + 14, y + (h - emoji) // 2 - 1), text, font, fill=ink, emoji_size=emoji)
    return int(w)


def gold_chip(img, x, y, text, font) -> int:
    return chip(img, x, y, text, font, fill=(92, 70, 20, 235), outline=(*GOLD, 220), ink=(*GOLD, 255))


def header(img, title: str, subtitle: str = "") -> int:
    """Titre et sous-titre ; renvoie l'ordonnée sous l'en-tête."""
    draw = ImageDraw.Draw(img)
    f_title = try_font(32, bold=True)
    draw_text_with_emojis(img, (PAD, PAD), clip(draw, title, f_title, WIDTH - 2 * PAD - 40), f_title,
                          fill=TEXT, emoji_size=32)
    if subtitle:
        f_sub = try_font(17)
        draw_text_with_emojis(img, (PAD, PAD + 46), clip(draw, subtitle, f_sub, WIDTH - 2 * PAD), f_sub,
                              fill=MUTED, emoji_size=17)
        return PAD + 78
    return PAD + 50


def footer(img, y: int, text: str, h: int = 56) -> None:
    panel(img, (PAD, y), (WIDTH - 2 * PAD, h), radius=16, fill=(36, 28, 54, 215), outline=(*LILAC, 110))
    f = try_font(16)
    draw = ImageDraw.Draw(img)
    draw_text_with_emojis(img, (PAD + 20, y + (h - 17) // 2), clip(draw, text, f, WIDTH - 2 * PAD - 40), f,
                          fill=MUTED, emoji_size=17)


def shadow_text(draw, xy, text, font, fill=TEXT) -> None:
    draw_text_with_shadow(draw, xy, text, font, fill=fill, shadow=SHADOW)


def save(img: Image.Image, output_path: str) -> None:
    img.convert("RGB").save(output_path, "PNG", optimize=True)
