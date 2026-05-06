"""Bannière /profile générée avec Pillow.

Génère un PNG qui sert d'illustration au-dessus de l'embed /profile :
avatar du joueur, nom, niveau, rang dans un badge coloré, score de
puissance et stats principales.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.bot.rendering.image_utils import (
    crop_to_circle,
    download_image,
    add_outline,
)


WIDTH = 1024
HEIGHT = 480


# Couleur dominante par classe de rang (F → SSS+). Le code prend la 1re
# lettre du rang et regarde dans cette table ; le suffixe -/+ ajoute une
# variation d'intensité côté code.
_RANK_BASE_COLOR = {
    "F": (140, 140, 145),   # gris
    "E": (120, 180, 130),   # vert sage
    "D": (90, 160, 220),    # bleu
    "C": (180, 130, 220),   # violet
    "B": (220, 140, 100),   # orange
    "A": (220, 200, 80),    # or
    "S": (250, 70, 70),     # rouge vif
}


def _rank_color(rank_label: str) -> tuple[int, int, int]:
    if not rank_label:
        return (140, 140, 145)
    # Premier caractère = lettre principale (F, E, D, C, B, A, S, S, S)
    letter = rank_label[0].upper()
    base = _RANK_BASE_COLOR.get(letter, (140, 140, 145))
    return base


def _gradient_background(width: int, height: int) -> Image.Image:
    """Fond dégradé bleu nuit, sobre, ne distrait pas du contenu."""
    bg = Image.new("RGBA", (width, height), (15, 15, 30, 255))
    draw = ImageDraw.Draw(bg)
    for y in range(height):
        ratio = y / max(1, height - 1)
        r = int(15 + ratio * 10)
        g = int(15 + ratio * 25)
        b = int(40 + ratio * 50)
        draw.line((0, y, width, y), fill=(r, g, b, 255))
    return bg


def _try_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
        "DejaVuSans.ttf",
    ]
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _draw_text_with_shadow(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font,
    fill=(255, 255, 255, 255),
    shadow=(0, 0, 0, 200),
    shadow_offset: tuple[int, int] = (2, 2),
) -> None:
    x, y = xy
    sx, sy = shadow_offset
    draw.text((x + sx, y + sy), text, font=font, fill=shadow)
    draw.text(xy, text, font=font, fill=fill)


def _stat_block(
    draw: ImageDraw.ImageDraw,
    origin: tuple[int, int],
    label: str,
    value: str,
    font_label,
    font_value,
    box_size: tuple[int, int] = (180, 70),
) -> None:
    x, y = origin
    w, h = box_size

    # Carte de stat avec un fond semi-transparent
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_draw.rounded_rectangle(
        [(0, 0), (w - 1, h - 1)],
        radius=12,
        fill=(0, 0, 0, 110),
        outline=(255, 255, 255, 35),
        width=1,
    )
    draw._image.alpha_composite(overlay, (x, y))

    _draw_text_with_shadow(
        draw, (x + 14, y + 6), label, font_label,
        fill=(180, 200, 230, 255),
    )
    _draw_text_with_shadow(
        draw, (x + 14, y + 26), value, font_value,
        fill=(255, 255, 255, 255),
    )


def compose_profile_banner(
    output_path: str,
    *,
    display_name: str,
    avatar_url: str | None,
    level: int,
    xp: int,
    gold: int,
    rank_label: str,
    power_score: str,
    class_name: str | None,
    stats: dict,
    active_title: str | None = None,
) -> None:
    """Rend la bannière de profil et l'écrit sur disque (PNG)."""
    bg = _gradient_background(WIDTH, HEIGHT)
    draw = ImageDraw.Draw(bg)

    title_font = _try_font(40, bold=True)
    subtitle_font = _try_font(22)
    label_font = _try_font(14)
    value_font = _try_font(20, bold=True)
    rank_font = _try_font(64, bold=True)
    big_score_font = _try_font(28, bold=True)

    # --- Avatar circulaire ---
    avatar_size = 220
    avatar_x = 40
    avatar_y = (HEIGHT - avatar_size) // 2

    avatar_img = None
    if avatar_url:
        try:
            avatar_img = download_image(avatar_url)
        except Exception:
            avatar_img = None
    if avatar_img is None:
        avatar_img = Image.new("RGBA", (avatar_size, avatar_size), (60, 60, 80, 255))

    avatar_circle = crop_to_circle(avatar_img, avatar_size)
    avatar_outlined = add_outline(
        avatar_circle,
        outline_size=6,
        outline_color=(255, 255, 255, 220),
    )
    bg.alpha_composite(avatar_outlined, (avatar_x - 6, avatar_y - 6))

    # --- Nom + niveau ---
    name_x = avatar_x + avatar_size + 30
    name_y = avatar_y - 4
    if active_title:
        _draw_text_with_shadow(
            draw, (name_x, name_y - 26), active_title, subtitle_font,
            fill=(212, 175, 55, 255),
        )
    _draw_text_with_shadow(
        draw, (name_x, name_y), display_name, title_font,
        fill=(255, 255, 255, 255),
    )
    level_text = f"Niveau {level}"
    if class_name:
        level_text += f"  ·  {class_name}"
    _draw_text_with_shadow(
        draw, (name_x, name_y + 50), level_text, subtitle_font,
        fill=(180, 200, 230, 255),
    )

    # --- Badge de rang ---
    badge_size = 130
    badge_x = WIDTH - badge_size - 40
    badge_y = avatar_y - 8
    rank_color = _rank_color(rank_label)

    badge_overlay = Image.new("RGBA", (badge_size, badge_size), (0, 0, 0, 0))
    bo_draw = ImageDraw.Draw(badge_overlay)
    # Anneau extérieur
    bo_draw.ellipse(
        (0, 0, badge_size - 1, badge_size - 1),
        fill=(rank_color[0], rank_color[1], rank_color[2], 220),
        outline=(255, 255, 255, 255),
        width=4,
    )
    # Cercle intérieur foncé
    inset = 12
    bo_draw.ellipse(
        (inset, inset, badge_size - 1 - inset, badge_size - 1 - inset),
        fill=(0, 0, 0, 180),
    )

    # Texte du rang centré dans le badge
    text_w = bo_draw.textlength(rank_label, font=rank_font)
    text_x = (badge_size - text_w) // 2
    # Approche pragmatique pour le centrage vertical (Pillow ne renvoie pas
    # facilement la hauteur du glyph) : on baisse de ~25% du badge_size.
    text_y = int(badge_size * 0.20)
    bo_draw.text(
        (text_x, text_y),
        rank_label,
        font=rank_font,
        fill=(255, 255, 255, 255),
    )
    bg.alpha_composite(badge_overlay, (badge_x, badge_y))

    # Power score sous le badge
    score_text = f"⚡ {power_score}"
    sx = badge_x
    sy = badge_y + badge_size + 10
    _draw_text_with_shadow(
        draw, (sx, sy), score_text, big_score_font,
        fill=(255, 220, 100, 255),
    )

    # --- Stats grid (rangée pleine largeur en bas) ---
    blocks = [
        ("PV", str(stats.get("max_hp", 0))),
        ("Atk", str(stats.get("attack", 0))),
        ("Def", str(stats.get("defense", 0))),
        ("Vit", str(stats.get("speed", 0))),
        ("Crit", f"{int(stats.get('crit_chance', 0))}%"),
        ("Esquive", f"{int(stats.get('dodge', 0))}%"),
    ]
    box_h = 70
    margin_x = 30
    spacing_x = 8
    available = WIDTH - 2 * margin_x
    box_w = (available - spacing_x * (len(blocks) - 1)) // len(blocks)
    stats_y = HEIGHT - box_h - 30

    cur_x = margin_x
    for label, value in blocks:
        _stat_block(
            draw,
            (cur_x, stats_y),
            label,
            value,
            label_font,
            value_font,
            box_size=(box_w, box_h),
        )
        cur_x += box_w + spacing_x

    # --- Or / XP en bas (compacts, sous le nom) ---
    info_y = name_y + 88
    _draw_text_with_shadow(
        draw, (name_x, info_y),
        f"💰 {gold:,}".replace(",", " ") + " or",
        subtitle_font,
        fill=(255, 215, 100, 255),
    )
    _draw_text_with_shadow(
        draw, (name_x + 240, info_y),
        f"✨ {xp:,}".replace(",", " ") + " XP",
        subtitle_font,
        fill=(180, 220, 255, 255),
    )

    # Sauvegarde
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    bg.convert("RGB").save(output_path, "PNG", optimize=True)
