"""Rendu de texte mixte texte + emojis couleur dans Pillow.

Pillow ne permet pas un *fallback* automatique entre une font texte
(DejaVuSans) et une font emoji couleur (NotoColorEmoji). On segmente
manuellement la chaîne, on rend chaque segment avec sa font, et on
compose horizontalement.

NotoColorEmoji n'expose qu'une taille de glyphe fixe (109 px). Pour
obtenir un emoji à la taille du texte courant, on rend dans une
image temporaire à 109 px puis on la redimensionne vers la taille
cible (proportionnellement à la hauteur de la font texte).

Cache LRU sur les rendus d'emoji (le même cœur ❤️ apparaît dans
plusieurs cartes — pas la peine de le re-générer à chaque appel).
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


_NOTO_PATH = Path("/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf")
_NOTO_NATIVE_SIZE = 109


def _load_emoji_font() -> ImageFont.ImageFont | None:
    if not _NOTO_PATH.exists():
        return None
    try:
        return ImageFont.truetype(str(_NOTO_PATH), _NOTO_NATIVE_SIZE)
    except Exception:
        return None


_EMOJI_FONT = _load_emoji_font()


# Heuristique large : tous les blocs Unicode contenant des emojis fréquents.
# On préfère la sur-couverture (mieux vaut tenter de rendre via NotoColorEmoji
# et fallback à du texte que l'inverse).
_EMOJI_PATTERN = re.compile(
    "("
    "[\U0001F300-\U0001F9FF]"     # symbols, pictographs, supplemental
    "|[\U0001FA00-\U0001FAFF]"    # symbols and pictographs extended-A
    "|[⌀-⏿]"            # misc technical (⌛ ⏳ …)
    "|[☀-⛿]"            # miscellaneous symbols (U+2600–26FF, ⚔ ⚙ …)
    "|[✀-➿]"            # dingbats (U+2700–27BF, ❤ ✨ …)
    "|[⬀-⯿]"            # misc symbols & arrows (⭐ ⬆ …)
    "|[\U0001F1E6-\U0001F1FF]"    # flags
    ")"
    "(?:️)?"                 # variation selector ignoré
    "(?:‍[\U0001F300-\U0001F9FF])*"  # zero-width joiner sequences
)


def split_emoji_segments(text: str) -> list[tuple[str, str]]:
    """Renvoie une liste de tuples (kind, value) où kind ∈ {"text", "emoji"}.

    Les segments adjacents de même kind sont fusionnés.
    """
    segments: list[tuple[str, str]] = []
    last_end = 0
    for match in _EMOJI_PATTERN.finditer(text):
        if match.start() > last_end:
            segments.append(("text", text[last_end:match.start()]))
        segments.append(("emoji", match.group(0)))
        last_end = match.end()
    if last_end < len(text):
        segments.append(("text", text[last_end:]))

    # Fusionne les "text" consécutifs (cas rare avec ZWJ partiels)
    merged: list[tuple[str, str]] = []
    for kind, value in segments:
        if merged and merged[-1][0] == kind == "text":
            merged[-1] = ("text", merged[-1][1] + value)
        else:
            merged.append((kind, value))
    return merged


@lru_cache(maxsize=128)
def _render_emoji_cached(emoji: str, target_height: int) -> Image.Image | None:
    """Rend un emoji à la hauteur cible via NotoColorEmoji.

    Renvoie None si la font n'est pas disponible (fallback texte côté
    appelant). Retourne une image RGBA cropée tight + redimensionnée.
    """
    if _EMOJI_FONT is None:
        return None
    canvas = Image.new("RGBA", (160, 160), (0, 0, 0, 0))
    d = ImageDraw.Draw(canvas)
    try:
        d.text((0, 0), emoji, font=_EMOJI_FONT, embedded_color=True)
    except Exception:
        return None

    bbox = canvas.getbbox()
    if bbox is None:
        return None
    canvas = canvas.crop(bbox)

    if canvas.height <= 0:
        return None
    ratio = target_height / canvas.height
    new_w = max(1, int(canvas.width * ratio))
    return canvas.resize((new_w, target_height), Image.Resampling.LANCZOS)


def measure_text_with_emojis(
    text: str, text_font: ImageFont.ImageFont, emoji_size: int,
) -> int:
    """Largeur en pixels qu'occuperait `text` rendu via `draw_text_with_emojis`."""
    dummy = Image.new("RGBA", (1, 1))
    d = ImageDraw.Draw(dummy)
    width = 0
    for kind, value in split_emoji_segments(text):
        if kind == "text":
            width += int(d.textlength(value, font=text_font))
        else:
            emoji_img = _render_emoji_cached(value, emoji_size)
            if emoji_img is None:
                width += int(d.textlength(value, font=text_font))
            else:
                width += emoji_img.width + 2  # petit gap entre emoji et texte
    return width


def draw_text_with_emojis(
    base: Image.Image,
    position: tuple[int, int],
    text: str,
    text_font: ImageFont.ImageFont,
    *,
    fill: tuple[int, int, int, int] = (255, 255, 255, 255),
    shadow: tuple[int, int, int, int] | None = (0, 0, 0, 200),
    shadow_offset: tuple[int, int] = (2, 2),
    emoji_size: int | None = None,
) -> int:
    """Rend `text` avec emojis sur `base`. Renvoie la largeur consommée.

    `text_font` : font des segments de texte.
    `emoji_size` : hauteur cible des emojis. Par défaut, on prend la
    hauteur en pixels approximative de `text_font.size`.
    """
    if emoji_size is None:
        # Approximation : taille de la font ~ hauteur des glyphes en ascii
        emoji_size = getattr(text_font, "size", 18)

    draw = ImageDraw.Draw(base)
    x, y = position
    cursor = x

    for kind, value in split_emoji_segments(text):
        if kind == "text":
            if shadow is not None:
                draw.text(
                    (cursor + shadow_offset[0], y + shadow_offset[1]),
                    value, font=text_font, fill=shadow,
                )
            draw.text((cursor, y), value, font=text_font, fill=fill)
            cursor += int(draw.textlength(value, font=text_font))
        else:
            emoji_img = _render_emoji_cached(value, emoji_size)
            if emoji_img is None:
                # Fallback : on dessine le caractère brut (probablement
                # une boîte vide mais l'erreur reste isolée).
                draw.text((cursor, y), value, font=text_font, fill=fill)
                cursor += int(draw.textlength(value, font=text_font))
            else:
                # Centrer l'emoji verticalement par rapport à la baseline
                # du texte (un peu plus haut visuellement)
                offset_y = max(0, (emoji_size // 8))
                base.alpha_composite(emoji_img, (cursor, y + offset_y))
                cursor += emoji_img.width + 2
    return cursor - x
