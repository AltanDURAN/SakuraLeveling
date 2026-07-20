"""Système visuel élémentaire des monstres.

Un même monstre (image N&B / niveaux de gris) est **décliné par élément** via
une teinte générée par code (désaturation → colorisation duotone), plus un
**badge d'élément** (icône emoji dans une pastille) posé toujours au même
endroit et à la même taille, quel que soit l'élément.

Générer les teintes par code (plutôt que 8 fichiers par mob) : 1 seule image
de base par monstre, N éléments gratuits, cohérence garantie.
"""

from __future__ import annotations

from PIL import Image, ImageDraw, ImageOps

from app.bot.rendering.emoji_text import draw_text_with_emojis, measure_text_with_emojis
from app.bot.rendering.pillow_utils import try_font
from app.shared.enums import ELEMENT_EMOJIS, ELEMENT_LABELS

# ---------------------------------------------------------------------------
# CODE COULEUR — 8 éléments, teintes distinctes (aucune paire proche), logiques.
#   feu=rouge · eau=bleu · plante=vert · lumiere=jaune/or brillant · terre=marron
#   glace=cyan clair · vent=turquoise (bien séparé du vert plante) · tenebre=sombre
# `ELEMENT_COLORS` = couleur "marque" : anneau du badge + libellé + pastille.
# ---------------------------------------------------------------------------
ELEMENT_COLORS: dict[str, tuple[int, int, int]] = {
    "feu":     (230, 66, 45),    # rouge vif
    "eau":     (34, 88, 200),    # bleu (plus foncé)
    "plante":  (40, 138, 60),    # vert (plus foncé)
    "vent":    (92, 216, 198),   # turquoise clair (≠ vert plante)
    "terre":   (120, 74, 40),    # marron (plus foncé)
    "glace":   (160, 228, 246),  # cyan très clair
    "lumiere": (255, 224, 110),  # jaune doré brillant
    "tenebre": (104, 92, 122),   # sombre (anneau lisible, peu violet)
}

# Réglage de la TEINTE du monstre (colorisation duotone). Par défaut :
# mid = couleur marque, dark_f = 0.20, light_f = 0.78. Override par élément :
#   - tenebre : mid quasi-noir + hautes lumières basses → "ombre", pas violet
#   - lumiere : hautes lumières poussées vers le blanc → plus brillant
#   - terre   : hautes lumières retenues → marron riche, pas beige délavé
_TINT_OVERRIDES: dict[str, dict] = {
    "tenebre": {"mid": (48, 45, 58), "dark_f": 0.11, "light_f": 0.42},
    "lumiere": {"light_f": 0.90},
    "terre":   {"light_f": 0.60},
}


def _tint_stops(element: str) -> tuple[tuple, tuple, tuple]:
    """(ombre, milieu, lumière) pour la colorisation duotone d'un élément."""
    brand = ELEMENT_COLORS[element]
    cfg = _TINT_OVERRIDES.get(element, {})
    mid = cfg.get("mid", brand)
    dark_f = cfg.get("dark_f", 0.20)
    light_f = cfg.get("light_f", 0.78)
    r, g, b = mid
    dark = (int(r * dark_f), int(g * dark_f), int(b * dark_f))
    light = (int(r + (255 - r) * light_f), int(g + (255 - g) * light_f), int(b + (255 - b) * light_f))
    return dark, mid, light


def tint_by_element(image: Image.Image, element: str) -> Image.Image:
    """Décline une image de monstre selon `element` : désaturation puis
    colorisation duotone avec la couleur de l'élément. Préserve la transparence.
    Élément inconnu / neutre ("") → image inchangée (RGBA)."""
    code = (element or "").strip().lower()
    rgba = image.convert("RGBA")
    if code not in ELEMENT_COLORS:
        return rgba
    alpha = rgba.getchannel("A")
    luminance = rgba.convert("L")
    dark, mid, light = _tint_stops(code)
    colored = ImageOps.colorize(luminance, black=dark, white=light, mid=mid).convert("RGBA")
    colored.putalpha(alpha)
    return colored


def make_element_badge(element: str, diameter: int = 130) -> Image.Image | None:
    """Pastille circulaire (fond sombre translucide + anneau couleur d'élément)
    avec l'icône emoji centrée. Taille FIXE quel que soit l'élément → position
    et dimensions identiques d'un élément à l'autre. None si élément neutre."""
    code = (element or "").strip().lower()
    emoji = ELEMENT_EMOJIS.get(code)
    color = ELEMENT_COLORS.get(code)
    if not emoji or color is None:
        return None

    badge = Image.new("RGBA", (diameter, diameter), (0, 0, 0, 0))
    d = ImageDraw.Draw(badge)
    ring = 6
    # disque de fond sombre translucide
    d.ellipse([0, 0, diameter - 1, diameter - 1], fill=(20, 20, 28, 205))
    # anneau de la couleur d'élément
    d.ellipse(
        [ring // 2, ring // 2, diameter - 1 - ring // 2, diameter - 1 - ring // 2],
        outline=(color[0], color[1], color[2], 255), width=ring,
    )
    # icône emoji centrée (taille fixe)
    emoji_size = int(diameter * 0.56)
    font = try_font(emoji_size)
    w = measure_text_with_emojis(emoji, font, emoji_size)
    x = (diameter - w) // 2
    y = (diameter - emoji_size) // 2 - int(diameter * 0.02)
    draw_text_with_emojis(badge, (x, y), emoji, font, emoji_size=emoji_size, shadow=None)
    return badge


def element_label(element: str) -> str:
    return ELEMENT_LABELS.get((element or "").strip().lower(), "Neutre")
