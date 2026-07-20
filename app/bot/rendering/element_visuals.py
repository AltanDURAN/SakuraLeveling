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
#   feu=rouge · eau=bleu · plante=vert · lumiere=jaune/or · terre=brun
#   glace=cyan clair · vent=vert-air (lime) · tenebre=violet
# Réparties sur la roue chromatique pour rester lisibles d'un coup d'œil ; les
# deux plus proches (glace/eau) restent séparées par la teinte + l'icône.
# ---------------------------------------------------------------------------
ELEMENT_COLORS: dict[str, tuple[int, int, int]] = {
    "feu":     (230, 66, 45),    # rouge vif
    "terre":   (166, 107, 63),   # brun
    "lumiere": (245, 205, 60),   # jaune doré
    "vent":    (166, 217, 59),   # vert-air (lime)
    "plante":  (63, 176, 74),    # vert
    "glace":   (102, 208, 232),  # cyan clair
    "eau":     (46, 111, 230),   # bleu
    "tenebre": (155, 84, 214),   # violet
}


def _shades(color: tuple[int, int, int]) -> tuple[tuple, tuple]:
    """Ombre (bas) et lumière (haut) dérivées de la couleur d'élément, pour la
    colorisation duotone qui préserve le relief du monstre."""
    r, g, b = color
    dark = (int(r * 0.20), int(g * 0.20), int(b * 0.20))
    light = (int(r + (255 - r) * 0.78), int(g + (255 - g) * 0.78), int(b + (255 - b) * 0.78))
    return dark, light


def tint_by_element(image: Image.Image, element: str) -> Image.Image:
    """Décline une image de monstre selon `element` : désaturation puis
    colorisation duotone avec la couleur de l'élément. Préserve la transparence.
    Élément inconnu / neutre ("") → image inchangée (RGBA)."""
    color = ELEMENT_COLORS.get((element or "").strip().lower())
    rgba = image.convert("RGBA")
    if color is None:
        return rgba
    alpha = rgba.getchannel("A")
    luminance = rgba.convert("L")
    dark, light = _shades(color)
    colored = ImageOps.colorize(luminance, black=dark, white=light, mid=color).convert("RGBA")
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
