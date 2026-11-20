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
SHADOW = (0, 0, 0, 170)

# ---------------------------------------------------------------- palette --
# UNE couleur par SENS, la même sur tous les écrans (demande de l'auteur,
# 21/11/2026 : des écrans colorés, et cohérents). Les stats reprennent les
# couleurs des cartes de la bannière `/profil`.
GOLD = (240, 196, 92)        # or, récompenses, ce qui est à toi
XP = (110, 190, 255)         # expérience, niveau
HP = (235, 80, 90)           # PV, soins
ATK = (255, 140, 50)         # attaque, DPS
DEF = (90, 160, 230)         # défense, tank
MANA = (90, 150, 255)
SPEED = (120, 220, 200)
CRIT = (255, 215, 100)
CRIT_DMG = (220, 100, 220)
DODGE = (180, 200, 255)
REGEN = (120, 220, 130)      # régénération, soutien
GREEN = (120, 220, 140)      # réussi, disponible
TIME = (90, 210, 230)        # temps, attentes
ITEM = (190, 140, 255)       # objets, butin
FIRE = (255, 130, 60)        # série, flamme
PINK = (255, 150, 200)       # cartes, cosmétiques, sakura
EARTH = (205, 150, 95)       # matériaux
LILAC = (150, 120, 210)      # neutre (cadres)


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


def header(img, title: str, subtitle: str = "", accent=None) -> int:
    """Titre et sous-titre ; renvoie l'ordonnée sous l'en-tête. `accent` : la
    couleur de l'écran, en filet lumineux sous le titre."""
    draw = ImageDraw.Draw(img)
    f_title = try_font(32, bold=True)
    title = clip(draw, title, f_title, WIDTH - 2 * PAD - 40)
    draw_text_with_emojis(img, (PAD, PAD), title, f_title, fill=TEXT, emoji_size=32)
    if accent is not None:
        tw = min(measure_text_with_emojis(title, f_title, 32), WIDTH - 2 * PAD)
        bar(img, (PAD, PAD + 41), (int(tw), 4), 1.0, accent, track=(0, 0, 0, 0), glow=True)
    shift = 8 if accent is not None else 0         # de la place pour le filet
    if subtitle:
        f_sub = try_font(17)
        draw_text_with_emojis(img, (PAD, PAD + 46 + shift), clip(draw, subtitle, f_sub, WIDTH - 2 * PAD), f_sub,
                              fill=MUTED, emoji_size=17)
        return PAD + 78 + shift
    return PAD + 50 + shift


def footer(img, y: int, text: str, h: int = 56, color=LILAC) -> None:
    panel(img, (PAD, y), (WIDTH - 2 * PAD, h), radius=16, fill=(36, 28, 54, 215), outline=(*color[:3], 140))
    panel(img, (PAD, y + 12), (4, h - 24), radius=2, fill=(*color[:3], 255))
    f = try_font(16)
    draw = ImageDraw.Draw(img)
    draw_text_with_emojis(img, (PAD + 20, y + (h - 17) // 2), clip(draw, text, f, WIDTH - 2 * PAD - 40), f,
                          fill=MUTED, emoji_size=17)


def segments(img, xy, parts, font, emoji: int = 16, gap: int = 18, max_w: float | None = None) -> int:
    """Une ligne en plusieurs couleurs : `parts` = [(texte, couleur), …].
    S'arrête avant de dépasser `max_w`. Renvoie la largeur dessinée."""
    x, y = xy
    start = x
    for text, color in parts:
        w = measure_text_with_emojis(text, font, emoji)
        if max_w is not None and x - start + w > max_w:
            break
        ink = color if len(color) == 4 else (*color, 255)
        draw_text_with_emojis(img, (int(x), y), text, font, fill=ink, emoji_size=emoji)
        x += w + gap
    return int(x - start - gap)


def shadow_text(draw, xy, text, font, fill=TEXT) -> None:
    draw_text_with_shadow(draw, xy, text, font, fill=fill, shadow=SHADOW)


def save(img: Image.Image, output_path: str) -> None:
    img.convert("RGB").save(output_path, "PNG", optimize=True)
