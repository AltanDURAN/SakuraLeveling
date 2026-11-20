"""Image de `/stats` : la feuille de personnage (demande de l'auteur, 20/11/2026).

Même grammaire visuelle que `/affinites`, la bannière et les PNJ : dégradé de
nuit, pétales de sakura, panneaux translucides. Ce que le joueur vient y faire
passe en premier : les points à placer (en or s'il y en a), puis les trois
stats de BASE — chacune avec sa valeur finale, son socle et la part que lui
ajoutent équipement, arbre et titres (une barre en deux tons) — et, en
dessous, les stats secondaires.
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
from app.shared.formatters import format_int

WIDTH = 1024
_PAD = 28
_GAP = 16

_TEXT = (245, 242, 250, 255)
_MUTED = (176, 170, 194, 255)
_DIM = (128, 122, 144, 255)
_GOLD = (240, 196, 92)
_SHADOW = (0, 0, 0, 170)

#: Mêmes couleurs que les cartes de la bannière `/profil`.
BASE_STATS = (
    ("attack", "ATTAQUE", "⚔️", (255, 140, 50)),
    ("defense", "DÉFENSE", "🛡️", (90, 160, 230)),
    ("max_hp", "PV MAX", "❤️", (235, 80, 90)),
)
SECONDARY = (
    ("speed", "Vitesse", "💨", (120, 220, 200), ""),
    ("crit_chance", "Critique", "🎯", (255, 215, 100), " %"),
    ("crit_damage", "Dégâts crit.", "💥", (220, 100, 220), " %"),
    ("dodge", "Esquive", "🌀", (180, 200, 255), " %"),
    ("hp_regeneration", "Régén. PV", "🌿", (120, 220, 130), "/min"),
    ("mana_max", "Mana", "🔷", (90, 150, 255), ""),
)


def _panel(img, xy, size, radius=16, fill=(28, 24, 40, 205), outline=None, width=1):
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle(
        [xy, (xy[0] + size[0], xy[1] + size[1])], radius=radius, fill=fill, outline=outline, width=width)
    img.alpha_composite(layer)


def _bar(img, xy, size, ratio, color, track=(60, 54, 78, 220), glow=False):
    x, y = xy
    w, h = size
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rounded_rectangle([(x, y), (x + w, y + h)], radius=h // 2, fill=track)
    filled = int(w * max(0.0, min(1.0, ratio)))
    if filled > 2:
        if glow:
            g = Image.new("RGBA", img.size, (0, 0, 0, 0))
            ImageDraw.Draw(g).rounded_rectangle([(x, y - 2), (x + filled, y + h + 2)], radius=h, fill=(*color, 120))
            img.alpha_composite(g.filter(ImageFilter.GaussianBlur(5)))
        d.rounded_rectangle([(x, y), (x + filled, y + h)], radius=h // 2, fill=(*color, 255))
    img.alpha_composite(layer)


def _lighten(color, f):
    return tuple(int(c + (255 - c) * f) for c in color)


def _fit(draw, text: str, size: int, max_w: float, bold: bool = True, floor: int = 12):
    """La plus grande police (≤ `size`) dans laquelle `text` tient en `max_w`."""
    while size > floor and draw.textlength(text, font=try_font(size, bold=bold)) > max_w:
        size -= 1
    return try_font(size, bold=bold)


def _clip_name(draw, name: str, font, max_w: float) -> str:
    if draw.textlength(name, font=font) <= max_w:
        return name
    while name and draw.textlength(name + "…", font=font) > max_w:
        name = name[:-1]
    return name + "…"


def _chip(img, x, y, text, font, fill, outline, ink, emoji=16) -> int:
    w = measure_text_with_emojis(text, font, emoji) + 28
    _panel(img, (int(x), y), (int(w), 32), radius=16, fill=fill, outline=outline)
    draw_text_with_emojis(img, (int(x) + 14, y + 7), text, font, fill=ink, emoji_size=emoji)
    return int(w)


def _base_card(img, xy, size, key, label, icon, color, data, gain: int) -> None:
    x, y = xy
    w, h = size
    draw = ImageDraw.Draw(img)
    final, base, invested = data["final"][key], data["base"][key], data["points"][key]
    bonus = max(0, final - base)

    _panel(img, (x, y), (w, h), radius=18, fill=(24, 20, 36, 220), outline=(*color, 110))
    tint = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(tint).rounded_rectangle([(x, y), (x + w, y + h)], radius=18, fill=(*color, 24))
    img.alpha_composite(tint)
    _panel(img, (x + 14, y), (w - 28, 5), radius=3, fill=(*color, 255))

    f_label = try_font(17, bold=True)
    f_big = try_font(46, bold=True)
    f_small = try_font(15)
    f_small_b = try_font(15, bold=True)

    draw_text_with_emojis(img, (x + 20, y + 22), f"{icon} {label}", f_label, fill=(*_lighten(color, 0.25), 255),
                          emoji_size=19)
    value = format_int(final)
    f_big = _fit(draw, value, 46, w - 40)
    draw_text_with_shadow(draw, (x + 20, y + 52 + (46 - f_big.size) // 2), value, f_big, fill=_TEXT, shadow=_SHADOW)

    # Barre en deux tons : le socle (points), puis ce qu'ajoutent équipement,
    # arbre et titres — l'équipement MULTIPLIE le socle, il ne s'y ajoute pas.
    bar_y, bar_w = y + 120, w - 40
    total = max(final, 1)
    _bar(img, (x + 20, bar_y), (bar_w, 12), 1.0, _lighten(color, 0.55), glow=False)
    _bar(img, (x + 20, bar_y), (bar_w, 12), base / total, color, track=(0, 0, 0, 0), glow=True)
    draw_text_with_shadow(draw, (x + 20, bar_y + 22), f"socle {format_int(base)}", f_small_b,
                          fill=(*_lighten(color, 0.2), 255), shadow=_SHADOW)
    extra = f"+{format_int(bonus)} bonus" if bonus else "aucun bonus"
    ew = draw.textlength(extra, font=f_small)
    draw_text_with_shadow(draw, (x + 20 + bar_w - ew, bar_y + 22), extra, f_small,
                          fill=_MUTED if bonus else _DIM, shadow=_SHADOW)

    points = f"{invested} point{'s' if invested > 1 else ''} placé{'s' if invested > 1 else ''}"
    draw_text_with_shadow(draw, (x + 20, y + h - 34), points, f_small, fill=_MUTED, shadow=_SHADOW)
    per = f"+{gain} / point"
    pw = draw.textlength(per, font=f_small_b)
    draw_text_with_shadow(draw, (x + w - 20 - pw, y + h - 34), per, f_small_b,
                          fill=(*_lighten(color, 0.3), 255), shadow=_SHADOW)


def compose_stats_sheet(output_path: str, data: dict, *, gains: dict[str, int], seed: int = 0) -> None:
    """`data` : le dictionnaire de `stats_cog._load` (avec `secondary`)."""
    header_h, card_h, sec_h, foot_h = 150, 230, 112, 64
    height = _PAD + header_h + card_h + _GAP + sec_h + _GAP + foot_h + _PAD
    img = gradient_background(WIDTH, height, (26, 22, 40, 255), (16, 14, 26, 255))
    draw_sakura_petals(img, seed=seed)
    draw = ImageDraw.Draw(img)

    f_title = try_font(32, bold=True)
    f_sub = try_font(17)
    f_chip = try_font(16, bold=True)

    # ------------------------------------------------------------------ en-tête
    name = _clip_name(draw, data["display_name"], f_title, WIDTH - 2 * _PAD - 250)
    draw_text_with_emojis(img, (_PAD, _PAD), f"💪 Feuille de {name}", f_title, fill=_TEXT, emoji_size=32)
    level = data["level"]
    if data.get("xp_required"):
        sub = f"Niveau {level}   ·   {format_int(data['xp'])} / {format_int(data['xp_required'])} XP"
        ratio = data["xp"] / max(data["xp_required"], 1)
    else:
        sub, ratio = f"Niveau {level}   ·   palier maximum de la saison", 1.0
    draw_text_with_emojis(img, (_PAD, _PAD + 46), sub, f_sub, fill=_MUTED, emoji_size=17)
    _bar(img, (_PAD, _PAD + 76), (WIDTH - 2 * _PAD, 8), ratio, (110, 190, 255), glow=True)

    points = data["stat_points"]
    cy = _PAD + 98
    if points:
        _chip(img, _PAD, cy, f"✨ {points} point{'s' if points > 1 else ''} à placer", f_chip,
              fill=(92, 70, 20, 235), outline=(*_GOLD, 220), ink=(*_GOLD, 255))
    else:
        _chip(img, _PAD, cy, "Aucun point à placer · un par niveau", f_chip,
              fill=(40, 32, 60, 220), outline=(150, 120, 210, 120), ink=_MUTED)

    # ------------------------------------------------------------- stats de base
    top = _PAD + header_h
    card_w = (WIDTH - 2 * _PAD - 2 * _GAP) // 3
    for i, (key, label, icon, color) in enumerate(BASE_STATS):
        _base_card(img, (_PAD + i * (card_w + _GAP), top), (card_w, card_h), key, label, icon, color,
                   data, gains.get(key, 0))

    # --------------------------------------------------------- stats secondaires
    sy = top + card_h + _GAP
    _panel(img, (_PAD, sy), (WIDTH - 2 * _PAD, sec_h), radius=16, fill=(28, 24, 40, 205),
           outline=(150, 120, 210, 90))
    draw_text_with_shadow(draw, (_PAD + 20, sy + 14), "STATS SECONDAIRES · arbre, équipement, titres",
                          try_font(13, bold=True), fill=_DIM, shadow=_SHADOW)
    secondary = data.get("secondary") or {}
    col_w = (WIDTH - 2 * _PAD - 40) / len(SECONDARY)
    f_lab = try_font(14)
    for i, (key, label, icon, color, unit) in enumerate(SECONDARY):
        cx = int(_PAD + 20 + i * col_w)
        value = secondary.get(key, 0)
        text = f"{format_int(value)}{unit}"
        f_val = _fit(draw, text, 24, col_w - 40)
        draw_text_with_emojis(img, (cx, sy + 44), f"{icon}", try_font(24, bold=True), fill=_TEXT, emoji_size=22)
        draw_text_with_shadow(draw, (cx + 30, sy + 42 + (24 - f_val.size) // 2), text, f_val,
                              fill=(*_lighten(color, 0.15), 255), shadow=_SHADOW)
        draw_text_with_shadow(draw, (cx, sy + 78), label, f_lab, fill=_MUTED, shadow=_SHADOW)

    # ---------------------------------------------------------------------- pied
    fy = sy + sec_h + _GAP
    _panel(img, (_PAD, fy), (WIDTH - 2 * _PAD, foot_h), radius=16, fill=(36, 28, 54, 215),
           outline=(150, 120, 210, 110))
    note = ("📜 Un point placé est définitif : seul le parchemin d'oubli de Sorn les rend."
            if points else "📈 Combats, quêtes et tour font monter de niveau : un point de stats à chaque fois.")
    draw_text_with_emojis(img, (_PAD + 20, fy + 21), note, try_font(16), fill=_MUTED, emoji_size=17)

    img.convert("RGB").save(output_path, "PNG", optimize=True)
