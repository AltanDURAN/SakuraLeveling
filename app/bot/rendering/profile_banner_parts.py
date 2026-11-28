"""Pièces de la bannière `/profil` : palette, panneaux, barre d'XP, cartes de
stats, badge de rang, en-têtes de section, cosmétiques (fond, cadre, titre),
aura mythique. Sorties de `profile_banner.py` le 28/11/2026 (audit) : texte
inchangé ; la composition reste dans `profile_banner.compose_profile_banner`."""

from __future__ import annotations

import math
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from app.bot.rendering.emoji_text import (
    draw_text_with_emojis,
)
from app.bot.rendering.mythic_fx import MYTHIC_GOLD, MYTHIC_RED
from app.bot.rendering.image_utils import (
    add_outline,
)
from app.bot.rendering.pillow_utils import (
    draw_sakura_petals,
    draw_text_with_shadow as _shared_text_shadow,
    gradient_background,
    try_font,
)
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
    "mana": (90, 150, 255, 255),      # bleu mana
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
    "Ω": (240, 205, 120),  # Challenger — or lumineux
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


# ------------------------------------------------------------ cosmétiques --
# Les cosmétiques de Sorn (objets `cosmetic`, portés via /apparence) : leur
# apparence est décrite dans `stat_bonuses` de l'objet — un fond (dégradé +
# pétales, aurore), un cadre d'avatar (couleur, 2e anneau, halo) ou une
# couleur de titre (halo). Aucun effet en jeu.
def _rgba(color, alpha: int = 255) -> tuple[int, int, int, int]:
    color = list(color or (255, 255, 255))
    return (int(color[0]), int(color[1]), int(color[2]), int(color[3]) if len(color) > 3 else alpha)


def _cosmetic_background(width: int, height: int, look: dict | None, seed: int) -> Image.Image:
    """Fond de bannière : le dégradé et les pétales du cosmétique, sinon ceux
    par défaut ; « aurora » ajoute des voiles lumineux."""
    if not look:
        bg = _gradient_background(width, height)
        _draw_sakura_petals(bg, seed=seed)
        return bg
    bg = gradient_background(width, height, _rgba(look.get("top")), _rgba(look.get("bottom")))
    if look.get("aurora"):
        veil = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        vd = ImageDraw.Draw(veil)
        for i, color in enumerate(((90, 255, 200), (150, 110, 255), (90, 200, 255))):
            y = 60 + i * 70
            for x in range(-40, width + 40, 8):
                wave = int(28 * math.sin((x + i * 90) / 95))
                vd.ellipse([(x - 30, y + wave - 40), (x + 30, y + wave + 40)], fill=(*color, 40))
        bg.alpha_composite(veil.filter(ImageFilter.GaussianBlur(18)))
    palette = [_rgba(c) for c in look.get("petals") or []] or None
    draw_sakura_petals(bg, seed=seed, count=28, palette=palette)
    return bg


def _framed_avatar(avatar_circle: Image.Image, default_color, look: dict | None) -> tuple[Image.Image, int]:
    """Avatar cerclé : couleur du rang par défaut, ou le cadre porté (2e anneau,
    halo). Renvoie (image, marge à retirer de la position)."""
    if not look:
        return add_outline(avatar_circle, outline_size=7, outline_color=(*default_color[:3], 240)), 7
    framed = add_outline(avatar_circle, outline_size=7, outline_color=_rgba(look.get("color"), 245))
    margin = 7
    if look.get("ring2"):
        framed = add_outline(framed, outline_size=4, outline_color=_rgba(look.get("ring2"), 235))
        margin += 4
    if look.get("glow"):
        pad = 18
        size = framed.width + 2 * pad
        halo = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        ImageDraw.Draw(halo).ellipse([(pad - 6, pad - 6), (size - pad + 6, size - pad + 6)],
                                     fill=_rgba(look.get("color"), 150))
        halo = halo.filter(ImageFilter.GaussianBlur(10))
        halo.alpha_composite(framed, (pad, pad))
        framed, margin = halo, margin + pad
    return framed, margin


def _draw_title(bg: Image.Image, xy: tuple[int, int], text: str, font, look: dict | None) -> None:
    """Titre actif : or par défaut, ou la couleur portée (avec halo)."""
    color = _rgba(look.get("color")) if look else COLORS["title_color"]
    if look and look.get("glow"):
        layer = Image.new("RGBA", bg.size, (0, 0, 0, 0))
        draw_text_with_emojis(layer, xy, text, font, fill=(*color[:3], 255))
        glow = layer.filter(ImageFilter.GaussianBlur(7))
        bg.alpha_composite(glow)
        bg.alpha_composite(glow)
    draw_text_with_emojis(bg, xy, text, font, fill=color)


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
    fill_start: tuple[int, int, int] | None = None,
    fill_end: tuple[int, int, int] | None = None,
    glow_color: tuple[int, int, int] = (100, 200, 255),
) -> None:
    """Barre de progression horizontale stylée (XP par défaut, réutilisée
    pour PV/Mana via `fill_start`/`fill_end`/`glow_color`) :
       - fond sombre + bord blanc
       - remplissage gradient (bleu → cyan par défaut)
       - halo extérieur lumineux autour de la portion remplie
       - particules / sparkles dispersés sur le rempli
       - tête de progression brillante
    """
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
        c1 = fill_start if fill_start is not None else COLORS["xp_bar_fill_start"]
        c2 = fill_end if fill_end is not None else COLORS["xp_bar_fill_end"]
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


def _fit_classes(level_text: str, class_name: str | None, font, max_width: int) -> str:
    """« Niveau 30 · Gardien · Clerc +2 » : les classes qui tiennent avant le
    badge de rang, le reste en nombre."""
    classes = class_name.split(" · ") if class_name else []
    for shown in range(len(classes), 0, -1):
        hidden = len(classes) - shown
        text = f"{level_text}  ·  {' · '.join(classes[:shown])}" + (f" +{hidden}" if hidden else "")
        if font.getlength(text) <= max_width:
            return text
    return level_text


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
    # La puissance s'écrit en entier jusqu'à 99 999 : on réduit la police
    # plutôt que de déborder du cœur sombre de la fleur.
    while cd.textlength(score_text, font=pwr_font) > size * 0.44 and pwr_font.size > 14:
        pwr_font = pwr_font.font_variant(size=pwr_font.size - 1)
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


def _draw_mythic_aura(bg: Image.Image, center: tuple[int, int], radius: int) -> None:
    """Aura d'un porteur de pièce mythique : halo rouge, couronne de rayons
    dorés et anneau lumineux derrière l'avatar."""
    size = radius * 2 + 120
    c = size // 2
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    # Halo diffus
    d.ellipse([(c - radius - 34, c - radius - 34), (c + radius + 34, c + radius + 34)],
              fill=(*MYTHIC_RED, 150))
    # Rayons dorés, longueurs alternées
    for i in range(24):
        a = math.radians(i * 15)
        inner, outer = radius + 6, radius + (36 if i % 2 == 0 else 24)
        d.line([(c + inner * math.cos(a), c + inner * math.sin(a)),
                (c + outer * math.cos(a), c + outer * math.sin(a))],
               fill=(*MYTHIC_GOLD, 210), width=5)
    layer = layer.filter(ImageFilter.GaussianBlur(9))
    d = ImageDraw.Draw(layer)
    # Les mêmes rayons, nets et plus fins, par-dessus le flou
    for i in range(24):
        a = math.radians(i * 15)
        inner, outer = radius + 14, radius + (32 if i % 2 == 0 else 22)
        d.line([(c + inner * math.cos(a), c + inner * math.sin(a)),
                (c + outer * math.cos(a), c + outer * math.sin(a))],
               fill=(*MYTHIC_GOLD, 235), width=3)
    d.ellipse([(c - radius - 12, c - radius - 12), (c + radius + 12, c + radius + 12)],
              outline=(*MYTHIC_GOLD, 230), width=3)
    # L'aura déborde du haut de la bannière : paste accepte une origine
    # négative, alpha_composite non.
    overlay = Image.new("RGBA", bg.size, (0, 0, 0, 0))
    overlay.paste(layer, (center[0] - c, center[1] - c))
    bg.alpha_composite(overlay)
