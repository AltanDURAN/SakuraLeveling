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
from app.bot.rendering.pillow_utils import (
    draw_sakura_petals,
    draw_text_with_shadow as _shared_text_shadow,
    gradient_background,
    try_font,
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


def _draw_sakura_petals(
    base: Image.Image,
    seed: int = 42,
    count: int = 28,
) -> None:
    """Décor de fond : pétales de sakura en filigrane (palette par défaut)."""
    draw_sakura_petals(base, seed=seed, count=count)


def _add_vignette(base: Image.Image, intensity: float = 0.55) -> None:
    """Assombrit progressivement les bords/coins pour donner du relief
    à l'image. Itère sur des rectangles concentriques avec alpha croissant.
    """
    w, h = base.size
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)

    # 24 anneaux concentriques. Chaque anneau a une opacité croissante
    # vers les bords. Ça reste léger (max alpha ~50) — l'effet est subtil.
    steps = 24
    max_alpha = int(60 * intensity)
    for i in range(steps):
        ratio = i / max(1, steps - 1)
        # Pondération exponentielle pour concentrer l'assombrissement
        # vraiment dans les coins, pas au milieu.
        alpha = int(max_alpha * (ratio ** 2.4))
        if alpha <= 0:
            continue
        margin_x = int(w * 0.5 * (1 - ratio))
        margin_y = int(h * 0.5 * (1 - ratio))
        od.rectangle(
            [(margin_x, margin_y), (w - 1 - margin_x, h - 1 - margin_y)],
            outline=(0, 0, 0, alpha),
            width=2,
        )
    base.alpha_composite(overlay)


def _gradient_background(width: int, height: int) -> Image.Image:
    return gradient_background(
        width, height, COLORS["bg_top"], COLORS["bg_bottom"],
    )


def _try_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    return try_font(size, bold)


def _draw_text_with_shadow(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font,
    fill=COLORS["text_primary"],
    shadow=COLORS["shadow"],
    shadow_offset: tuple[int, int] = (2, 2),
) -> None:
    _shared_text_shadow(draw, xy, text, font, fill, shadow, shadow_offset)


def _format_int(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def _format_compact(n: int) -> str:
    """Format compact pour grands nombres : 1234 -> 1.2K, 12345 -> 12K,
    1234567 -> 1.2M, etc. Évite les dépassements de cards. Les valeurs
    < 1000 sont affichées en clair pour rester précises."""
    n = int(n)
    if n < 1_000:
        return str(n)
    if n < 10_000:
        # 1234 -> "1.2K", 9999 -> "9.9K". On enlève le ".0" trailing.
        s = f"{n / 1_000:.1f}".rstrip("0").rstrip(".")
        return f"{s}K"
    if n < 1_000_000:
        return f"{n // 1_000}K"
    if n < 10_000_000:
        s = f"{n / 1_000_000:.1f}".rstrip("0").rstrip(".")
        return f"{s}M"
    if n < 1_000_000_000:
        return f"{n // 1_000_000}M"
    s = f"{n / 1_000_000_000:.1f}".rstrip("0").rstrip(".")
    return f"{s}B"


def _draw_panel(
    base: Image.Image,
    origin: tuple[int, int],
    size: tuple[int, int],
    radius: int = 14,
    fill=None,
    border=None,
    accent: tuple[int, int, int, int] | None = None,
) -> None:
    """Carte arrondie semi-transparente avec léger dégradé vertical pour
    ajouter de la profondeur (un peu plus clair en haut, plus sombre en bas).
    Si `accent` est fourni, une barre verticale colorée à gauche de la
    carte (5 px) marque le type de stat. Quand un accent est fourni, on
    teinte aussi très légèrement le fond avec sa couleur, pour relier
    visuellement la barre et la card.
    """
    fill = fill or COLORS["panel_bg"]
    border = border or COLORS["panel_border"]
    w, h = size

    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)

    # Dégradé vertical : on dessine d'abord le panel plein, puis on
    # superpose une nappe transparente claire au sommet et sombre au
    # bas pour un effet de relief.
    od.rounded_rectangle(
        [(0, 0), (w - 1, h - 1)],
        radius=radius,
        fill=fill,
        outline=border,
        width=1,
    )

    # Voile teinté très subtilement par la couleur d'accent (ajoute
    # une touche de couleur au panel sans le surcharger).
    if accent is not None:
        ar, ag, ab, _ = accent
        tint = Image.new("RGBA", size, (0, 0, 0, 0))
        td = ImageDraw.Draw(tint)
        td.rounded_rectangle(
            [(0, 0), (w - 1, h - 1)],
            radius=radius,
            fill=(ar, ag, ab, 22),
        )
        overlay = Image.alpha_composite(overlay, tint)

    # Highlight haut (clair) + ombre bas (sombre) pour profondeur
    sheen = Image.new("RGBA", size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(sheen)
    sd.rounded_rectangle(
        [(0, 0), (w - 1, h // 2)],
        radius=radius,
        fill=(255, 255, 255, 14),
    )
    sd.rounded_rectangle(
        [(0, h // 2), (w - 1, h - 1)],
        radius=radius,
        fill=(0, 0, 0, 28),
    )
    overlay = Image.alpha_composite(overlay, sheen)

    if accent is not None:
        # Barre verticale d'accent à gauche
        accent_w = 5
        od2 = ImageDraw.Draw(overlay)
        od2.rounded_rectangle(
            [(0, 6), (accent_w, h - 7)],
            radius=accent_w // 2,
            fill=accent,
        )

    base.alpha_composite(overlay, origin)


def _draw_xp_bar(
    base: Image.Image,
    origin: tuple[int, int],
    size: tuple[int, int],
    progress: float,
    *,
    seed: int = 0,
) -> None:
    """Barre d'XP horizontale stylée :
       - fond sombre + bord blanc
       - remplissage gradient bleu → cyan
       - halo extérieur lumineux autour de la portion remplie
       - particules / sparkles dispersés sur le rempli
       - tête de progression brillante
    """
    import random
    progress = max(0.0, min(1.0, progress))
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)

    # Fond sombre arrondi
    od.rounded_rectangle(
        [(0, 0), (size[0] - 1, size[1] - 1)],
        radius=size[1] // 2,
        fill=COLORS["xp_bar_bg"],
        outline=(255, 255, 255, 60),
        width=1,
    )

    fill_w = int((size[0] - 4) * progress)
    if fill_w > 0:
        # Halo extérieur autour de la portion remplie : assombrissement
        # progressif sur 6 rangées au-dessus et au-dessous, qui simule
        # un effet "néon" cyan.
        glow = Image.new("RGBA", size, (0, 0, 0, 0))
        gld = ImageDraw.Draw(glow)
        glow_color = (100, 200, 255)
        for thickness in range(6, 0, -1):
            alpha = int(20 + (6 - thickness) * 8)
            gld.rounded_rectangle(
                [
                    (2 - thickness, 2 - thickness),
                    (fill_w + 2 + thickness, size[1] - 3 + thickness),
                ],
                radius=(size[1] - 4) // 2 + thickness,
                fill=None,
                outline=(glow_color[0], glow_color[1], glow_color[2], alpha),
                width=1,
            )
        overlay.alpha_composite(glow)

        # Remplissage gradient
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

        # Bande lumineuse horizontale en haut (effet "shine")
        shine_h = max(2, (size[1] - 4) // 4)
        for sy in range(shine_h):
            shine_alpha = int(140 - sy * 20)
            if shine_alpha <= 0:
                break
            gd.line(
                (0, sy, fill_w - 1, sy),
                fill=(255, 255, 255, shine_alpha),
            )

        mask = Image.new("L", gradient.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            [(0, 0), (gradient.size[0] - 1, gradient.size[1] - 1)],
            radius=(size[1] - 4) // 2,
            fill=255,
        )
        gradient.putalpha(mask)
        overlay.alpha_composite(gradient, (2, 2))

        # Particules / sparkles : petits points blancs aléatoires
        # dispersés sur la portion remplie. Donne un effet "magique".
        rng = random.Random(seed)
        n_particles = max(3, fill_w // 35)
        for _ in range(n_particles):
            px = rng.randint(8, max(8, fill_w - 4))
            py = rng.randint(4, size[1] - 6)
            radius = rng.choice([1, 1, 2])
            alpha = rng.randint(160, 230)
            od.ellipse(
                (px - radius, py - radius, px + radius, py + radius),
                fill=(255, 255, 255, alpha),
            )

        # Tête de progression : disque brillant à l'extrémité droite du
        # rempli, simule un "bulbe" de lumière qui suit la barre.
        head_x = fill_w + 2
        head_r = (size[1] - 4) // 2 + 2
        # Halo doux autour de la tête
        head_overlay = Image.new("RGBA", size, (0, 0, 0, 0))
        hod = ImageDraw.Draw(head_overlay)
        for r_offset in range(6, 0, -1):
            alpha = int(15 + (6 - r_offset) * 18)
            hod.ellipse(
                (
                    head_x - head_r - r_offset,
                    size[1] // 2 - head_r - r_offset,
                    head_x + head_r + r_offset,
                    size[1] // 2 + head_r + r_offset,
                ),
                fill=(180, 230, 255, alpha),
            )
        # Disque blanc plein au cœur de la tête
        hod.ellipse(
            (
                head_x - head_r // 2,
                size[1] // 2 - head_r // 2,
                head_x + head_r // 2,
                size[1] // 2 + head_r // 2,
            ),
            fill=(255, 255, 255, 240),
        )
        overlay.alpha_composite(head_overlay)

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
    """Badge en forme de fleur de sakura : 5 pétales arrondis disposés à
    72° autour d'un cercle central qui contient le rang. Le power_score
    s'affiche sous le rang en format ``[score]``.

    Les pétales prennent la couleur du rang ; le centre est sombre pour
    faire ressortir la lettre. Halo coloré autour pour l'effet "néon".
    """
    import math
    rc = _rank_color(rank_label)

    # Pas de halo lumineux autour du badge (retiré sur retour utilisateur).
    # Petite marge quand même pour les pétales qui débordent du `size`.
    halo_extra = 12
    canvas_size = size + 2 * halo_extra
    canvas = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    cd = ImageDraw.Draw(canvas)

    cx = halo_extra + size // 2
    cy = halo_extra + size // 2

    # ---- 5 pétales en fleur de sakura (version "ellipses") ----
    # Rose un peu plus vif que la version précédente : on glisse vers
    # le rose vif tout en gardant un look pâle "sakura".
    petal_color = (255, 175, 200, 250)
    petal_outline = (255, 225, 235, 230)
    highlight = (255, 150, 180, 140)

    petal_w = int(size * 0.42)
    petal_h = int(size * 0.55)
    # Distance du centre du pétale au centre de la fleur
    distance = int(size * 0.28)

    for i in range(5):
        angle_deg = -90 + i * 72  # premier pétale en haut, sens horaire
        angle_rad = math.radians(angle_deg)
        px = cx + int(distance * math.cos(angle_rad))
        py = cy + int(distance * math.sin(angle_rad))

        # On rend chaque pétale dans une image temporaire qu'on tourne.
        pad = max(petal_w, petal_h) * 2
        petal = Image.new("RGBA", (pad, pad), (0, 0, 0, 0))
        pd = ImageDraw.Draw(petal)
        # Pétale = ellipse simple — plus joli (silhouette douce et
        # arrondie) que la version polygone bilobée. Le contour blanc
        # rosé donne le look fleur de cerisier reconnaissable.
        pcx, pcy = pad // 2, pad // 2
        pd.ellipse(
            (pcx - petal_w // 2, pcy - petal_h // 2,
             pcx + petal_w // 2, pcy + petal_h // 2),
            fill=petal_color,
            outline=petal_outline,
            width=3,
        )
        # Touche claire à l'intérieur pour highlight
        inner_w = petal_w // 2
        inner_h = petal_h // 2
        pd.ellipse(
            (pcx - inner_w // 2, pcy - inner_h - 4,
             pcx + inner_w // 2, pcy + inner_h // 2 - 4),
            fill=highlight,
        )

        # Rotation : pointer la pointe vers l'extérieur. Le pétale est
        # vertical par défaut (long axis Y), donc l'angle de rotation
        # pour qu'il pointe à `angle_deg` du centre est `angle_deg + 90`.
        rotated = petal.rotate(
            -(angle_deg + 90),
            resample=Image.BICUBIC,
            expand=True,
        )
        canvas.alpha_composite(
            rotated,
            (px - rotated.width // 2, py - rotated.height // 2),
        )

    # ---- Cercle central avec rang ----
    inner_radius = int(size * 0.30)
    # Disque foncé semi-transparent
    cd.ellipse(
        (cx - inner_radius, cy - inner_radius,
         cx + inner_radius, cy + inner_radius),
        fill=(20, 18, 30, 235),
        outline=(255, 255, 255, 220),
        width=3,
    )

    # ---- Lettre du rang centrée ----
    # Adapte la taille de la police au nombre de caractères pour que
    # même "SSS+" tienne dans le cercle central.
    n_chars = len(rank_label)
    if n_chars <= 1:
        adaptive_size = 78
    elif n_chars == 2:
        adaptive_size = 66
    elif n_chars == 3:
        adaptive_size = 52
    else:
        adaptive_size = 42
    adaptive_rank_font = _try_font(adaptive_size, bold=True)

    rank_w = cd.textlength(rank_label, font=adaptive_rank_font)
    rank_x = cx - rank_w // 2
    # Lettre placée plus haut pour laisser de la place au score en dessous
    rank_y = cy - int(adaptive_size * 0.78)
    cd.text(
        (rank_x + 2, rank_y + 2),
        rank_label, font=adaptive_rank_font,
        fill=(0, 0, 0, 200),
    )
    cd.text(
        (rank_x, rank_y),
        rank_label, font=adaptive_rank_font,
        fill=COLORS["rank_text"],
    )

    # ---- Score sous le rang : format [XXX] doré ----
    score_text = f"[{power_score}]"
    score_w = cd.textlength(score_text, font=pwr_font)
    score_x = cx - score_w // 2
    # Espace clair sous la lettre du rang : 12% du badge size, peu importe
    # la taille adaptative de la lettre (évite chevauchement quand la
    # lettre est grande "F" comme quand elle est petite "SSS+").
    score_y = cy + int(size * 0.06)
    cd.text(
        (score_x + 1, score_y + 1),
        score_text, font=pwr_font,
        fill=(0, 0, 0, 200),
    )
    cd.text(
        (score_x, score_y),
        score_text, font=pwr_font,
        fill=COLORS["gold_color"],
    )

    base.alpha_composite(
        canvas, (origin[0] - halo_extra, origin[1] - halo_extra),
    )


def _draw_section_header(
    base: Image.Image,
    origin: tuple[int, int],
    label: str,
    font,
    line_width: int,
) -> None:
    """Titre de section avec emoji + ligne décorative en dessous.

    La ligne en dessous a un dégradé alpha des deux côtés (transparent au
    bord, opaque au centre du segment) pour un rendu plus soigné qu'un
    trait plat.
    """
    x, y = origin
    text_w = draw_text_with_emojis(
        base, (x, y), label, font, fill=COLORS["section_label"],
    )

    # Ligne décorative juste après le label : commence par un trait
    # solide aligné avec le texte, puis se prolonge en dégradé qui
    # s'estompe vers la droite — donne un look "underline glamour".
    line_y = y + font.size + 10
    line_height = 2

    # Trait sombre sous le label, qui s'estompe doucement
    overlay = Image.new("RGBA", (line_width, line_height + 1), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    fade_start = text_w + 16
    for px in range(line_width):
        if px < fade_start:
            alpha = 90  # solide sous le titre
        else:
            # Décroît linéairement après le texte
            ratio = 1.0 - (px - fade_start) / max(1, line_width - fade_start)
            alpha = int(90 * max(0.0, ratio))
        od.line(
            [(px, 0), (px, line_height - 1)],
            fill=(255, 255, 255, alpha),
            width=1,
        )
    base.alpha_composite(overlay, (x, line_y))


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

    # Pétales de sakura en filigrane — décor "anime" subtil avant tout
    # ce qui sera dessiné par-dessus. Seed dérivé du nom pour que chaque
    # profil ait sa disposition unique mais stable d'un appel à l'autre.
    _draw_sakura_petals(bg, seed=hash(display_name) & 0xFFFF)

    # Vignette douce dans les 4 coins pour ambiance "vue plongeante",
    # plus pro qu'un fond plat dégradé. On la rend très subtile pour
    # ne pas perdre en lisibilité au centre.
    _add_vignette(bg)

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
    # Card PV : "current/max" peut être long (ex 1.2K/1.5K), on rétrécit
    # pour éviter le débordement.
    value_font_compact = _try_font(32, bold=True)
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
    # Anneau de la couleur du rang : signal visuel immédiat du tier.
    # Le rang sert deux fois (badge + ring) — cohérent et sympa.
    rc = _rank_color(rank_label)
    avatar_outlined = add_outline(
        avatar_circle, outline_size=7,
        outline_color=(rc[0], rc[1], rc[2], 240),
    )
    bg.alpha_composite(avatar_outlined, (avatar_x - 7, avatar_y - 7))

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
    _draw_xp_bar(
        bg, (info_x, bar_y), (bar_w, bar_h), progress,
        seed=hash(display_name) & 0xFFFF,
    )
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
        (f"💰 {_format_compact(gold)} or", COLORS["gold_color"]),
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

    # Combat : valeurs principales en format compact (PV/Atk/Def peuvent
    # devenir gros en endgame), pourcentages restent en chiffres pleins
    # car ils sont bornés [0..200] selon les caps.
    # PV : on affiche "current/max" si current est connu (sinon juste max).
    max_hp_value = int(stats.get("max_hp", 0))
    current_hp_value = stats.get("current_hp")
    if current_hp_value is not None:
        hp_display = (
            f"{_format_compact(int(current_hp_value))}"
            f"/{_format_compact(max_hp_value)}"
        )
    else:
        hp_display = _format_compact(max_hp_value)
    combat_cards = [
        ("❤️", "PV", hp_display, "hp"),
        ("⚔️", "Attaque", _format_compact(int(stats.get("attack", 0))), "atk"),
        ("🛡️", "Défense", _format_compact(int(stats.get("defense", 0))), "def"),
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
        # PV peut afficher "current/max" → fonte rétrécie pour ne pas
        # déborder de la card.
        card_value_font = (
            value_font_compact if accent_key == "hp" else value_font
        )
        _draw_stat_card(
            bg, (x, y), (card_w, card_h),
            emoji, label, value, label_font, card_value_font,
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
    # Toutes les valeurs en compact (1.2K, 22K, 1.5M…) — assure que les
    # chiffres tiennent dans la card à value_font 42, même quand un joueur
    # accumule des millions de dégâts ou d'or.
    career_cards = [
        ("💀", "Tués",
         _format_compact(int(career.get("monsters_killed", 0))), "kills"),
        ("⚔️", "Combats",
         _format_compact(fought), "combats"),
        ("💰", "Or amassé",
         _format_compact(int(career.get("gold_earned_total", 0))), "gold"),
        ("💢", "Dmg inf.",
         _format_compact(int(career.get("damage_dealt_total", 0))), "dmg_dealt"),
        ("🛡️", "Dmg subis",
         _format_compact(int(career.get("damage_tanked_total", 0))), "dmg_tanked"),
        ("💚", "PV soignés",
         _format_compact(int(career.get("hp_healed_total", 0))), "healed"),
        ("🌀", "Esquives",
         _format_compact(int(career.get("dodges_total", 0))), "dodge"),
        # Winrate en pourcentage (au lieu de "87 / 20"). Plus parlant
        # d'un coup d'œil et tient toujours dans la card. Affiche "—" si
        # le joueur n'a pas encore combattu (évite division par zéro).
        ("🏆", "Winrate",
         f"{round(100 * won / fought)}%" if fought > 0 else "—",
         "trophy"),
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
