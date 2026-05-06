"""Profile complet rendu en une seule image Pillow stylée.

L'objectif : un /profile lisible d'un coup d'œil avec des emojis couleur
(via NotoColorEmoji), des couleurs d'accent par stat, et une typo
généreuse. Tout est dans l'image — l'embed Discord ne sert que de
conteneur.

Layout (1024 × 980) :
    ┌───────────────────────────────────────────────────────────┐
    │  HEADER (~310 px)                                         │
    │  Avatar (210) │ 🏷 Title • NAME • Niveau X · Classe        │
    │               │ 🟦 XP bar avec %                          │
    │               │ 💰 or  ·  🔥 Daily Streak  ·  ⚔ Duel  ·  📚│
    │                                            ┌────────────┐ │
    │                                            │  RANK BADGE│ │
    │                                            │  ⚡ PWR XXX │ │
    │                                            └────────────┘ │
    ├───────────────────────────────────────────────────────────┤
    │  ⚔ STATS DE COMBAT (~270 px)                              │
    │  4×2 grid coloré : ❤ PV | ⚔ Atk | 🛡 Def | 💨 Vit         │
    │                    🎯 Crit | 💥 Cdmg | 🌀 Esq | ✨ Régen   │
    ├───────────────────────────────────────────────────────────┤
    │  📈 STATISTIQUES DE CARRIÈRE (~280 px)                    │
    │  4×2 grid : 💀 Tués | ⚔ Combats | 💰 Or | 💢 Dmg inf      │
    │             🛡 Encaissés | 💚 Soignés | 🌀 Esquives | 🏆 V/D│
    └───────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.bot.rendering.emoji_text import (
    draw_text_with_emojis,
    measure_text_with_emojis,
)
from app.bot.rendering.image_utils import (
    add_outline,
    crop_to_circle,
    download_image,
)


WIDTH = 1024
HEIGHT = 1080


# Palette principale ---------------------------------------------------
# Contraste poussé pour la lecture en thumbnail Discord (~360 px). Les
# labels passent à blanc plein, les fonds des cards sont plus opaques.
COLORS = {
    "bg_top": (12, 14, 28, 255),
    "bg_bottom": (38, 42, 78, 255),
    "panel_bg": (0, 0, 0, 160),         # +30 d'opacité vs ancien (130)
    "panel_border": (255, 255, 255, 50),
    "section_label": (255, 255, 255, 245),
    "section_separator": (255, 255, 255, 60),
    "text_primary": (255, 255, 255, 245),
    "text_secondary": (210, 225, 245, 255),
    "text_muted": (175, 190, 215, 255),
    "title_color": (255, 210, 90, 255),
    "gold_color": (255, 220, 110, 255),
    "xp_color": (200, 235, 255, 255),
    "rank_text": (255, 255, 255, 255),
    "shadow": (0, 0, 0, 220),
    "xp_bar_bg": (35, 45, 75, 255),
    "xp_bar_fill_start": (90, 160, 220, 255),
    "xp_bar_fill_end": (60, 220, 200, 255),
    "xp_bar_glow": (130, 200, 255, 130),
}


# Couleurs d'accent par type de stat — appliquées sur la barre verticale
# des cards et le label, pour différencier visuellement les types.
_STAT_ACCENT = {
    "hp": (235, 80, 90, 255),         # rouge vif
    "atk": (255, 140, 50, 255),       # orange
    "def": (90, 160, 230, 255),       # bleu
    "speed": (120, 220, 200, 255),    # cyan
    "crit_chance": (255, 215, 100, 255),   # jaune
    "crit_damage": (220, 100, 220, 255),   # magenta
    "dodge": (180, 200, 255, 255),    # bleu pâle
    "regen": (120, 220, 130, 255),    # vert
    "kills": (220, 100, 100, 255),
    "combats": (255, 200, 100, 255),
    "gold": (255, 215, 100, 255),
    "dmg_dealt": (255, 130, 100, 255),
    "dmg_tanked": (130, 180, 230, 255),
    "healed": (120, 220, 130, 255),
    "trophy": (255, 200, 80, 255),
}


# Couleur principale du badge de rang selon la lettre (F → SSS).
_RANK_BASE_COLOR = {
    "F": (140, 140, 145),
    "E": (120, 200, 130),
    "D": (90, 160, 230),
    "C": (190, 130, 230),
    "B": (235, 150, 100),
    "A": (235, 210, 80),
    "S": (255, 70, 70),
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
    return f"{n:,}".replace(",", " ")


def _draw_panel(
    base: Image.Image,
    origin: tuple[int, int],
    size: tuple[int, int],
    radius: int = 14,
    fill=None,
    border=None,
    accent: tuple[int, int, int, int] | None = None,
) -> None:
    """Carte arrondie semi-transparente. Si `accent` est fourni, on dessine
    une barre verticale colorée à gauche de la carte (4 px de large) pour
    différencier visuellement le type de stat."""
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
    if accent is not None:
        # Barre verticale d'accent à gauche
        accent_w = 5
        od.rounded_rectangle(
            [(0, 6), (accent_w, size[1] - 7)],
            radius=accent_w // 2,
            fill=accent,
        )
    base.alpha_composite(overlay, origin)


def _draw_xp_bar(
    base: Image.Image,
    origin: tuple[int, int],
    size: tuple[int, int],
    progress: float,
) -> None:
    """Barre d'XP horizontale avec dégradé + petit halo de remplissage."""
    progress = max(0.0, min(1.0, progress))
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)

    od.rounded_rectangle(
        [(0, 0), (size[0] - 1, size[1] - 1)],
        radius=size[1] // 2,
        fill=COLORS["xp_bar_bg"],
        outline=(255, 255, 255, 50),
        width=1,
    )

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
    emoji: str,
    label: str,
    value: str,
    label_font,
    value_font,
    *,
    accent_key: str | None = None,
    emoji_size: int = 60,
) -> None:
    """Card avec :
       - barre verticale d'accent colorée à gauche
       - GROSSE icône emoji centrée verticalement à gauche
       - label en haut à droite (texte uni blanc)
       - valeur en gros en bas à droite (jaune / blanc selon contraste)
    """
    from app.bot.rendering.emoji_text import _render_emoji_cached

    accent = _STAT_ACCENT.get(accent_key) if accent_key else None
    _draw_panel(base, origin, size, accent=accent)
    x, y = origin
    w, h = size

    # Emoji à gauche, verticalement centré
    emoji_x = x + 16
    text_x = emoji_x + 18  # fallback si pas d'emoji
    emoji_img = _render_emoji_cached(emoji, emoji_size) if emoji else None
    if emoji_img is not None:
        emoji_y = y + (h - emoji_size) // 2
        base.alpha_composite(emoji_img, (emoji_x, emoji_y))
        text_x = emoji_x + emoji_size + 14

    # Texte aligné à droite de l'emoji : label haut, valeur bas
    draw = ImageDraw.Draw(base)
    label_y = y + 14
    value_y = y + h - value_font.size - 14
    _draw_text_with_shadow(
        draw, (text_x, label_y), label, label_font,
        fill=COLORS["text_primary"],
    )
    _draw_text_with_shadow(
        draw, (text_x, value_y), value, value_font,
    )


def _draw_rank_badge(
    base: Image.Image,
    origin: tuple[int, int],
    size: int,
    rank_label: str,
    power_score: str,
    rank_font,
    pwr_font,
) -> None:
    """Médaille de rang : anneau coloré + lettre du rang + 'PWR XXX' en
    petit en bas du badge. Tout est contenu DANS le badge pour ne pas
    déborder sur la zone d'infos en dessous."""
    rc = _rank_color(rank_label)
    badge = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    bd = ImageDraw.Draw(badge)
    # Anneau extérieur coloré (épais pour bien ressortir)
    bd.ellipse(
        (0, 0, size - 1, size - 1),
        fill=(rc[0], rc[1], rc[2], 240),
        outline=(255, 255, 255, 255),
        width=6,
    )
    # Cercle intérieur foncé pour faire ressortir la lettre
    inset = 14
    bd.ellipse(
        (inset, inset, size - 1 - inset, size - 1 - inset),
        fill=(0, 0, 0, 210),
    )
    # Lettre du rang — légèrement remontée pour laisser de la place au PWR
    text_w = bd.textlength(rank_label, font=rank_font)
    text_x = (size - text_w) // 2
    text_y = int(size * 0.10)
    bd.text(
        (text_x, text_y), rank_label, font=rank_font,
        fill=COLORS["rank_text"],
    )
    # "PWR X.XK" en petit, sous la lettre, centré
    pwr_text = f"PWR  {power_score}"
    pwr_w = bd.textlength(pwr_text, font=pwr_font)
    pwr_x = (size - pwr_w) // 2
    pwr_y = int(size * 0.66)
    bd.text(
        (pwr_x, pwr_y), pwr_text, font=pwr_font,
        fill=COLORS["gold_color"],
    )
    base.alpha_composite(badge, origin)


def _draw_section_header(
    base: Image.Image,
    origin: tuple[int, int],
    label: str,
    font,
    line_width: int,
) -> None:
    """Titre de section avec emoji + barre fine en dessous."""
    x, y = origin
    width_used = draw_text_with_emojis(
        base, (x, y), label, font, fill=COLORS["section_label"],
    )
    draw = ImageDraw.Draw(base)
    # Ligne après le label, dégradée pour un effet "souligné stylé"
    line_y = y + font.size + 8
    draw.line(
        [(x, line_y), (x + line_width, line_y)],
        fill=COLORS["section_separator"], width=2,
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
    bg = _gradient_background(WIDTH, HEIGHT)
    draw = ImageDraw.Draw(bg)

    # Fonts. Tailles "grosses" pour rester lisibles même quand Discord
    # compresse la bannière en thumbnail (~400 px de large), donc la
    # plupart des joueurs verront cette taille sans cliquer.
    name_font = _try_font(64, bold=True)
    title_font = _try_font(30, bold=True)
    sub_font = _try_font(30)
    info_font = _try_font(28, bold=True)
    label_font = _try_font(24, bold=True)
    value_font = _try_font(42, bold=True)
    section_font = _try_font(30, bold=True)
    rank_font = _try_font(80, bold=True)
    pwr_inner_font_size = 24  # utilisé plus bas dans l'appel au badge
    xp_label_font = _try_font(24, bold=True)

    margin = 30

    # ----- HEADER -----
    header_y = margin
    avatar_size = 210
    avatar_x = margin + 4
    avatar_y = header_y + 24

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

    info_x = avatar_x + avatar_size + 30
    info_y = avatar_y - 6

    # Title (emoji éventuel) en or au-dessus du nom
    if active_title:
        draw_text_with_emojis(
            bg, (info_x, info_y - 30), active_title, title_font,
            fill=COLORS["title_color"],
        )
    # Nom
    _draw_text_with_shadow(
        draw, (info_x, info_y), display_name, name_font,
    )

    # Niveau · Classe — placé sous le nom (qui fait `name_font.size` de haut)
    level_text = f"Niveau {level}"
    if class_name:
        level_text += f"  ·  {class_name}"
    level_y = info_y + name_font.size + 6
    _draw_text_with_shadow(
        draw, (info_x, level_y), level_text, sub_font,
        fill=COLORS["text_secondary"],
    )

    # Barre d'XP — full width depuis info_x jusqu'au début de la zone badge.
    bar_y = level_y + sub_font.size + 16
    bar_w = WIDTH - info_x - 220
    bar_h = 32
    # Cap au cas où l'XP a temporairement dépassé le seuil (bug historique
    # de level-up non appliqué) — on ne veut jamais afficher 105%.
    raw_progress = (xp_current / xp_required) if xp_required > 0 else 0.0
    progress = min(1.0, max(0.0, raw_progress))
    pct = int(round(progress * 100))
    _draw_xp_bar(bg, (info_x, bar_y), (bar_w, bar_h), progress)
    if xp_required > 0:
        xp_text = f"⚡ XP : {_format_int(xp_current)} / {_format_int(xp_required)}  ({pct}%)"
    else:
        xp_text = f"⚡ XP : {_format_int(xp_current)}"
    draw_text_with_emojis(
        bg, (info_x, bar_y + bar_h + 8), xp_text, xp_label_font,
        fill=COLORS["xp_color"],
    )

    # Ligne d'infos compactes (or, daily streak, duel, skill points)
    bottom_info_y = bar_y + bar_h + xp_label_font.size + 22
    parts: list[tuple[str, tuple[int, int, int, int]]] = [
        (f"💰 {_format_int(gold)} or", COLORS["gold_color"]),
    ]
    if daily_streak > 0:
        parts.append((f"🔥 Daily Streak : {daily_streak}", (255, 170, 90, 255)))
    if duel_position is not None:
        parts.append(
            (f"⚔️ Duel #{duel_position} ({duel_wins}V-{duel_losses}D)",
             COLORS["text_secondary"]),
        )
    if skill_points > 0:
        parts.append((f"📚 {skill_points} SP libres", (180, 230, 220, 255)))

    # Wrap automatique sur 2 lignes max — pour ne pas rentrer dans la
    # zone du badge à droite et garder tout lisible.
    badge_left_edge = WIDTH - 170 - margin - 4 - 20
    info_max_x = badge_left_edge
    line_height = info_font.size + 12
    cur_x = info_x
    cur_y = bottom_info_y
    second_line_started = False
    for text, color in parts:
        next_w = measure_text_with_emojis(text, info_font, info_font.size)
        # Si ça dépasse la limite à droite, on passe à la 2e ligne.
        if cur_x + next_w > info_max_x:
            if second_line_started:
                # 3e ligne refusée — on s'arrête (priorité gold > streak > duel > SP)
                break
            cur_x = info_x
            cur_y += line_height
            second_line_started = True
            # Si même seul sur la 2e ligne ça déborde encore, on coupe.
            if cur_x + next_w > info_max_x:
                continue
        draw_text_with_emojis(
            bg, (cur_x, cur_y), text, info_font, fill=color,
        )
        cur_x += next_w + 24
    bottom_info_end_y = cur_y + line_height  # pour positionner la section combat

    # Badge de rang à droite — la lettre + le PWR sont DANS le badge
    # pour ne pas déborder sur la ligne d'infos juste en dessous.
    badge_size = 200
    badge_x = WIDTH - badge_size - margin - 4
    badge_y = avatar_y - 14
    pwr_inner_font = _try_font(pwr_inner_font_size, bold=True)
    _draw_rank_badge(
        bg, (badge_x, badge_y), badge_size,
        rank_label, power_score, rank_font, pwr_inner_font,
    )

    # ----- COMBAT SECTION -----
    section_combat_y = max(bottom_info_end_y + 30, badge_y + badge_size + 30)
    _draw_section_header(
        bg, (margin, section_combat_y), "⚔️  STATS DE COMBAT",
        section_font, WIDTH - 2 * margin,
    )
    combat_grid_y = section_combat_y + 56
    grid_cols = 4
    spacing = 14
    available = WIDTH - 2 * margin - spacing * (grid_cols - 1)
    card_w = available // grid_cols
    card_h = 130

    combat_cards = [
        ("❤️", "PV max", _format_int(stats.get("max_hp", 0)), "hp"),
        ("⚔️", "Attaque", _format_int(stats.get("attack", 0)), "atk"),
        ("🛡️", "Défense", _format_int(stats.get("defense", 0)), "def"),
        ("💨", "Vitesse", str(stats.get("speed", 0)), "speed"),
        ("🎯", "Crit %", f"{int(stats.get('crit_chance', 0))}%", "crit_chance"),
        ("💥", "Crit dmg", f"{int(stats.get('crit_damage', 100))}%", "crit_damage"),
        ("🌀", "Esquive", f"{int(stats.get('dodge', 0))}%", "dodge"),
        ("✨", "Régen", str(stats.get("hp_regeneration", 0)), "regen"),
    ]

    for idx, (emoji, label, value, accent_key) in enumerate(combat_cards):
        row = idx // grid_cols
        col = idx % grid_cols
        x = margin + col * (card_w + spacing)
        y = combat_grid_y + row * (card_h + spacing)
        _draw_stat_card(
            bg, (x, y), (card_w, card_h),
            emoji, label, value, label_font, value_font,
            accent_key=accent_key,
        )

    # ----- CAREER SECTION -----
    section_career_y = combat_grid_y + 2 * (card_h + spacing) + 20
    _draw_section_header(
        bg, (margin, section_career_y), "📈  STATISTIQUES DE CARRIÈRE",
        section_font, WIDTH - 2 * margin,
    )
    career_grid_y = section_career_y + 50
    career = career or {}
    fought = int(career.get("combats_fought", 0))
    won = int(career.get("combats_won", 0))
    lost = int(career.get("combats_lost", 0))
    # Le %W est volontairement omis — la card V/D voisine montre
    # déjà "87V / 20D" donc le ratio est calculable d'un coup d'œil.

    # Labels courts pour rester DANS la largeur des cards (~225 px) avec
    # value_font 40 + label_font 22. "Dégâts encaissés" est trop long, on
    # raccourcit à "Dégâts subis" ; on supprime "totales" sur "Esquives"
    # (déjà dans la section "carrière" donc implicite).
    career_cards = [
        ("💀", "Tués",
         _format_int(int(career.get("monsters_killed", 0))), "kills"),
        ("⚔️", "Combats",
         _format_int(fought), "combats"),
        ("💰", "Or amassé",
         _format_int(int(career.get("gold_earned_total", 0))), "gold"),
        ("💢", "Dmg inf.",
         _format_int(int(career.get("damage_dealt_total", 0))), "dmg_dealt"),
        ("🛡️", "Dmg subis",
         _format_int(int(career.get("damage_tanked_total", 0))), "dmg_tanked"),
        ("💚", "PV soignés",
         _format_int(int(career.get("hp_healed_total", 0))), "healed"),
        ("🌀", "Esquives",
         _format_int(int(career.get("dodges_total", 0))), "dodge"),
        # "87 / 20" plutôt que "87V / 20D" : tient dans la card à value_font
        # 42, et le label "V / D" + l'icône 🏆 rendent l'ordre clair.
        ("🏆", "V / D",
         f"{won} / {lost}", "trophy"),
    ]

    for idx, (emoji, label, value, accent_key) in enumerate(career_cards):
        row = idx // grid_cols
        col = idx % grid_cols
        x = margin + col * (card_w + spacing)
        y = career_grid_y + row * (card_h + spacing)
        _draw_stat_card(
            bg, (x, y), (card_w, card_h),
            emoji, label, value, label_font, value_font,
            accent_key=accent_key,
        )

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    bg.convert("RGB").save(output_path, "PNG", optimize=True)
