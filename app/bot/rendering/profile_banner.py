"""Profile complet rendu en une seule image Pillow.

L'objectif : un /profile lisible d'un coup d'œil sans avoir à scroller
dans des fields d'embed. La bannière contient TOUT (identité, stats de
combat, stats de carrière) — l'embed Discord ne sert que de conteneur.

Layout (1024 × 920) :
    ┌────────────────────────────────────────────────────────┐
    │  HEADER 280 px                                         │
    │  Avatar │ Title • Name • Niveau X · Classe             │
    │         │ XP bar [████░░] 152/1520 (10%)               │
    │         │ 💰 or  ·  🔥 streak  ·  ⚔️ #N (WV-DD)         │
    │                                          ┌───────────┐ │
    │                                          │  RANK +   │ │
    │                                          │  ⚡ score  │ │
    │                                          └───────────┘ │
    ├────────────────────────────────────────────────────────┤
    │  COMBAT (220 px)                                       │
    │  4×2 grid : PV | Atk | Def | Vit                       │
    │             Crit% | Crit dmg | Esquive% | Régen        │
    ├────────────────────────────────────────────────────────┤
    │  CARRIÈRE (340 px)                                     │
    │  4×2 grid : Tués | Combats | Or carrière | Dégâts inf. │
    │             Encaissés | Soignés | Esquives | Skills    │
    └────────────────────────────────────────────────────────┘
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
HEIGHT = 800


# Palette de couleurs partagée — éviter les magic numbers éparpillés.
COLORS = {
    "bg_top": (15, 15, 30, 255),
    "bg_bottom": (40, 40, 80, 255),
    "panel_bg": (0, 0, 0, 100),
    "panel_border": (255, 255, 255, 35),
    "section_label": (200, 215, 235, 255),
    "section_separator": (255, 255, 255, 25),
    "text_primary": (255, 255, 255, 255),
    "text_secondary": (180, 200, 230, 255),
    "text_muted": (150, 165, 195, 255),
    "title_color": (212, 175, 55, 255),
    "gold_color": (255, 215, 100, 255),
    "xp_color": (180, 220, 255, 255),
    "rank_text": (255, 255, 255, 255),
    "shadow": (0, 0, 0, 200),
    "xp_bar_bg": (35, 45, 75, 255),
    "xp_bar_fill_start": (90, 160, 220, 255),
    "xp_bar_fill_end": (60, 220, 200, 255),
}


# Couleur principale du badge de rang selon la lettre (F → SSS).
_RANK_BASE_COLOR = {
    "F": (140, 140, 145),
    "E": (120, 180, 130),
    "D": (90, 160, 220),
    "C": (180, 130, 220),
    "B": (220, 140, 100),
    "A": (220, 200, 80),
    "S": (250, 70, 70),
}


def _rank_color(rank_label: str) -> tuple[int, int, int]:
    if not rank_label:
        return (140, 140, 145)
    return _RANK_BASE_COLOR.get(rank_label[0].upper(), (140, 140, 145))


def _gradient_background(width: int, height: int) -> Image.Image:
    bg = Image.new("RGBA", (width, height), COLORS["bg_top"])
    draw = ImageDraw.Draw(bg)
    top = COLORS["bg_top"]
    bottom = COLORS["bg_bottom"]
    for y in range(height):
        ratio = y / max(1, height - 1)
        r = int(top[0] + (bottom[0] - top[0]) * ratio)
        g = int(top[1] + (bottom[1] - top[1]) * ratio)
        b = int(top[2] + (bottom[2] - top[2]) * ratio)
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
    fill=COLORS["text_primary"],
    shadow=COLORS["shadow"],
    shadow_offset: tuple[int, int] = (2, 2),
) -> None:
    x, y = xy
    sx, sy = shadow_offset
    draw.text((x + sx, y + sy), text, font=font, fill=shadow)
    draw.text(xy, text, font=font, fill=fill)


def _format_int(n: int) -> str:
    """Espaces fines comme séparateurs (cohérent avec _format_int côté bot)."""
    return f"{n:,}".replace(",", " ")


def _draw_panel(
    base: Image.Image,
    origin: tuple[int, int],
    size: tuple[int, int],
    radius: int = 14,
    fill=None,
    border=None,
) -> None:
    """Carte arrondie semi-transparente posée sur l'image de base."""
    fill = fill or COLORS["panel_bg"]
    border = border or COLORS["panel_border"]
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.rounded_rectangle(
        [(0, 0), (size[0] - 1, size[1] - 1)],
        radius=radius,
        fill=fill,
        outline=border,
        width=1,
    )
    base.alpha_composite(overlay, origin)


def _draw_xp_bar(
    base: Image.Image,
    origin: tuple[int, int],
    size: tuple[int, int],
    progress: float,
) -> None:
    """Barre d'XP horizontale avec fond + dégradé de remplissage."""
    progress = max(0.0, min(1.0, progress))
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)

    # Fond
    od.rounded_rectangle(
        [(0, 0), (size[0] - 1, size[1] - 1)],
        radius=size[1] // 2,
        fill=COLORS["xp_bar_bg"],
        outline=(255, 255, 255, 40),
        width=1,
    )
    # Remplissage avec dégradé latéral
    fill_w = int((size[0] - 4) * progress)
    if fill_w > 0:
        gradient = Image.new("RGBA", (fill_w, size[1] - 4), (0, 0, 0, 0))
        gd = ImageDraw.Draw(gradient)
        c1 = COLORS["xp_bar_fill_start"]
        c2 = COLORS["xp_bar_fill_end"]
        for x in range(fill_w):
            ratio = x / max(1, fill_w - 1)
            r = int(c1[0] + (c2[0] - c1[0]) * ratio)
            g = int(c1[1] + (c2[1] - c1[1]) * ratio)
            b = int(c1[2] + (c2[2] - c1[2]) * ratio)
            gd.line((x, 0, x, size[1] - 4), fill=(r, g, b, 255))
        # Coins arrondis sur le remplissage via masque
        mask = Image.new("L", gradient.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            [(0, 0), (gradient.size[0] - 1, gradient.size[1] - 1)],
            radius=(size[1] - 4) // 2,
            fill=255,
        )
        gradient.putalpha(mask)
        overlay.alpha_composite(gradient, (2, 2))

    base.alpha_composite(overlay, origin)


def _draw_stat_card(
    base: Image.Image,
    origin: tuple[int, int],
    size: tuple[int, int],
    label: str,
    value: str,
    label_font,
    value_font,
    accent_color: tuple[int, int, int, int] | None = None,
) -> None:
    """Card de stat individuelle : petit label + grosse valeur."""
    _draw_panel(base, origin, size)
    draw = ImageDraw.Draw(base)
    x, y = origin
    _draw_text_with_shadow(
        draw, (x + 14, y + 8), label, label_font,
        fill=COLORS["text_secondary"],
    )
    _draw_text_with_shadow(
        draw, (x + 14, y + 30), value, value_font,
        fill=accent_color or COLORS["text_primary"],
    )


def _draw_rank_badge(
    base: Image.Image,
    origin: tuple[int, int],
    size: int,
    rank_label: str,
    rank_font,
) -> None:
    """Médaille de rang : disque coloré + lettre du rang centrée."""
    rc = _rank_color(rank_label)
    badge = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    bd = ImageDraw.Draw(badge)
    bd.ellipse(
        (0, 0, size - 1, size - 1),
        fill=(rc[0], rc[1], rc[2], 220),
        outline=(255, 255, 255, 255),
        width=4,
    )
    inset = 12
    bd.ellipse(
        (inset, inset, size - 1 - inset, size - 1 - inset),
        fill=(0, 0, 0, 180),
    )
    text_w = bd.textlength(rank_label, font=rank_font)
    text_x = (size - text_w) // 2
    text_y = int(size * 0.20)
    bd.text(
        (text_x, text_y), rank_label, font=rank_font,
        fill=COLORS["rank_text"],
    )
    base.alpha_composite(badge, origin)


def _draw_section_header(
    draw: ImageDraw.ImageDraw,
    origin: tuple[int, int],
    label: str,
    font,
    line_width: int,
) -> None:
    """Titre de section + ligne fine en dessous (séparateur visuel)."""
    x, y = origin
    _draw_text_with_shadow(
        draw, (x, y), label, font,
        fill=COLORS["section_label"],
    )
    draw.line(
        [(x, y + 32), (x + line_width, y + 32)],
        fill=COLORS["section_separator"], width=1,
    )


def compose_profile_banner(
    output_path: str,
    *,
    display_name: str,
    avatar_url: str | None,
    level: int,
    xp_current: int,
    xp_required: int,
    gold: int,
    rank_label: str,
    power_score: str,
    class_name: str | None,
    stats: dict,
    career: dict | None = None,
    duel_position: int | None = None,
    duel_wins: int = 0,
    duel_losses: int = 0,
    daily_streak: int = 0,
    skill_points: int = 0,
    active_title: str | None = None,
) -> None:
    """Rend le profil complet en une image PNG.

    `xp_current` / `xp_required` : XP du joueur depuis le dernier passage de
    niveau et XP totale requise pour le suivant. Si `xp_required <= 0`,
    la barre est cachée (cas dégénéré).

    `career` : dict avec les clés `monsters_killed`, `combats_fought`,
    `combats_won`, `combats_lost`, `gold_earned_total`, `damage_dealt_total`,
    `damage_tanked_total`, `hp_healed_total`, `dodges_total`. Toutes
    optionnelles (0 par défaut). Si None, le bloc carrière est rempli avec
    des zéros (mais reste affiché pour ne pas créer de blanc).
    """
    bg = _gradient_background(WIDTH, HEIGHT)
    draw = ImageDraw.Draw(bg)

    # ----- Fonts ----- #
    name_font = _try_font(46, bold=True)
    title_font = _try_font(22)
    sub_font = _try_font(20)
    small_font = _try_font(15)
    label_font = _try_font(14)
    value_font = _try_font(22, bold=True)
    section_font = _try_font(20, bold=True)
    rank_font = _try_font(64, bold=True)
    score_font = _try_font(28, bold=True)
    xp_label_font = _try_font(14, bold=True)

    margin = 30
    header_y = margin
    header_height = 240
    section_combat_y = header_y + header_height + 12
    section_career_y = section_combat_y + 220 + 12

    # ----- HEADER ----- #
    avatar_size = 180
    avatar_x = margin + 8
    avatar_y = header_y + 20

    # Avatar circulaire
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
        avatar_circle, outline_size=6,
        outline_color=(255, 255, 255, 220),
    )
    bg.alpha_composite(avatar_outlined, (avatar_x - 6, avatar_y - 6))

    # Identity panel (à droite de l'avatar)
    info_x = avatar_x + avatar_size + 30
    info_y = avatar_y - 4

    if active_title:
        _draw_text_with_shadow(
            draw, (info_x, info_y - 26), active_title, title_font,
            fill=COLORS["title_color"],
        )
    _draw_text_with_shadow(
        draw, (info_x, info_y), display_name, name_font,
    )

    level_text = f"Niveau {level}"
    if class_name:
        level_text += f"  ·  {class_name}"
    _draw_text_with_shadow(
        draw, (info_x, info_y + 56), level_text, sub_font,
        fill=COLORS["text_secondary"],
    )

    # XP bar
    bar_y = info_y + 92
    bar_w = WIDTH - info_x - 200  # laisse de la place pour le badge
    bar_h = 22
    progress = (xp_current / xp_required) if xp_required > 0 else 0.0
    pct = int(round(progress * 100))
    _draw_xp_bar(bg, (info_x, bar_y), (bar_w, bar_h), progress)
    if xp_required > 0:
        xp_text = f"XP : {_format_int(xp_current)} / {_format_int(xp_required)}  ({pct}%)"
    else:
        xp_text = f"XP : {_format_int(xp_current)}"
    _draw_text_with_shadow(
        draw, (info_x, bar_y + bar_h + 6), xp_text, xp_label_font,
        fill=COLORS["xp_color"],
    )

    # Compactez infos en bas du header : or / streak / duel
    bottom_info_y = bar_y + bar_h + 38
    # Symboles Unicode bien supportés par DejaVuSans (★ ◆) ou simple texte
    # pour ne PAS finir en boîtes vides (cas des emojis couleur 🔥 ⚔️).
    parts: list[tuple[str, tuple[int, int, int, int]]] = [
        (f"★ {_format_int(gold)} or", COLORS["gold_color"]),
    ]
    if daily_streak > 0:
        parts.append((f"Streak  {daily_streak}", (255, 150, 80, 255)))
    if duel_position is not None:
        parts.append(
            (f"Duel  #{duel_position}  ({duel_wins}V-{duel_losses}D)",
             COLORS["text_secondary"]),
        )
    if skill_points > 0:
        parts.append((f"◆ {skill_points} SP libres", (180, 230, 220, 255)))

    cur_x = info_x
    for text, color in parts:
        _draw_text_with_shadow(draw, (cur_x, bottom_info_y), text, sub_font, fill=color)
        text_w = draw.textlength(text, font=sub_font)
        cur_x += int(text_w) + 24

    # Badge de rang à droite
    badge_size = 130
    badge_x = WIDTH - badge_size - margin - 8
    badge_y = avatar_y - 8
    _draw_rank_badge(bg, (badge_x, badge_y), badge_size, rank_label, rank_font)

    # Power score sous le badge — préfixe texte simple (le ⚡ Unicode
    # rend en boîte avec DejaVuSans, on évite).
    sx = badge_x
    sy = badge_y + badge_size + 12
    _draw_text_with_shadow(
        draw, (sx, sy), f"PWR  {power_score}", score_font,
        fill=COLORS["gold_color"],
    )

    # ----- COMBAT SECTION ----- #
    _draw_section_header(
        draw, (margin, section_combat_y), "STATS DE COMBAT",
        section_font, WIDTH - 2 * margin,
    )
    combat_grid_y = section_combat_y + 50
    grid_cols = 4
    spacing = 12
    available = WIDTH - 2 * margin - spacing * (grid_cols - 1)
    card_w = available // grid_cols
    card_h = 70

    # Labels en texte pur — Pillow + DejaVuSans n'a pas de glyphes emoji
    # couleur, ils apparaîtraient en boîtes vides. Le visuel reste parlant
    # avec une typo claire et le titre de section emoji-isé en haut.
    combat_cards = [
        ("PV max", _format_int(stats.get("max_hp", 0))),
        ("Attaque", _format_int(stats.get("attack", 0))),
        ("Défense", _format_int(stats.get("defense", 0))),
        ("Vitesse", str(stats.get("speed", 0))),
        ("Crit chance", f"{int(stats.get('crit_chance', 0))}%"),
        ("Crit dégâts", f"{int(stats.get('crit_damage', 100))}%"),
        ("Esquive", f"{int(stats.get('dodge', 0))}%"),
        ("Régen / min", str(stats.get("hp_regeneration", 0))),
    ]

    for idx, (label, value) in enumerate(combat_cards):
        row = idx // grid_cols
        col = idx % grid_cols
        x = margin + col * (card_w + spacing)
        y = combat_grid_y + row * (card_h + spacing)
        _draw_stat_card(
            bg, (x, y), (card_w, card_h),
            label, value, label_font, value_font,
        )

    # ----- CAREER SECTION ----- #
    _draw_section_header(
        draw, (margin, section_career_y), "STATISTIQUES DE CARRIÈRE",
        section_font, WIDTH - 2 * margin,
    )
    career_grid_y = section_career_y + 50
    career = career or {}
    fought = int(career.get("combats_fought", 0))
    won = int(career.get("combats_won", 0))
    lost = int(career.get("combats_lost", 0))
    win_rate = f" ({round(100 * won / fought)}%W)" if fought > 0 else ""

    career_cards = [
        ("Monstres tués", _format_int(int(career.get("monsters_killed", 0)))),
        ("Combats", f"{_format_int(fought)}{win_rate}"),
        ("Or amassé", _format_int(int(career.get("gold_earned_total", 0)))),
        ("Dégâts infligés", _format_int(int(career.get("damage_dealt_total", 0)))),
        ("Dégâts encaissés", _format_int(int(career.get("damage_tanked_total", 0)))),
        ("PV soignés", _format_int(int(career.get("hp_healed_total", 0)))),
        ("Esquives totales", _format_int(int(career.get("dodges_total", 0)))),
        ("Victoires / Défaites", f"{won}V / {lost}D"),
    ]

    for idx, (label, value) in enumerate(career_cards):
        row = idx // grid_cols
        col = idx % grid_cols
        x = margin + col * (card_w + spacing)
        y = career_grid_y + row * (card_h + spacing)
        _draw_stat_card(
            bg, (x, y), (card_w, card_h),
            label, value, label_font, value_font,
        )

    # Footer discret en bas (juste un trait léger pour fermer la composition)
    footer_y = HEIGHT - 18
    draw.line(
        [(margin, footer_y), (WIDTH - margin, footer_y)],
        fill=COLORS["section_separator"], width=1,
    )

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    bg.convert("RGB").save(output_path, "PNG", optimize=True)
