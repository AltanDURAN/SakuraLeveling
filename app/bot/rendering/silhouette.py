"""Silhouette d'un monstre pas encore vaincu (bestiaire à découvrir, 07/11/2026).

La forme du monstre, remplie d'un violet presque noir, cernée d'un halo lavande
pour se détacher sur le thème clair comme sur le thème sombre de Discord.
"""

from __future__ import annotations

import io
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageFilter

#: Une vignette d'embed s'affiche en 80 px : inutile d'envoyer plus.
SIZE = 256
PADDING = 14
FILL = (24, 18, 36)
GLOW = (222, 196, 255)
#: Nom neutre : le nom du fichier se lit dans Discord, il ne doit pas trahir le monstre.
FILENAME = "inconnu.png"


def silhouette_png(path: Path) -> bytes:
    """PNG de la silhouette ; mis en cache tant que l'image ne change pas."""
    return _render(str(path), path.stat().st_mtime)


@lru_cache(maxsize=64)
def _render(path: str, mtime: float) -> bytes:  # noqa: ARG001 — mtime : clé du cache
    with Image.open(path) as source:
        image = source.convert("RGBA")
    image.thumbnail((SIZE - 2 * PADDING, SIZE - 2 * PADDING), Image.LANCZOS)
    mask = Image.new("L", (SIZE, SIZE), 0)
    mask.paste(image.getchannel("A"), ((SIZE - image.width) // 2, (SIZE - image.height) // 2))
    return _from_mask(mask)


@lru_cache(maxsize=1)
def question_png() -> bytes:
    """Un grand « ? » au même style qu'une silhouette, pour un monstre d'une
    zone pas encore mise en place (28/11/2026, demande de l'auteur) : son
    image n'est qu'une ébauche, sa silhouette ne serait pas la vraie."""
    from PIL import ImageDraw

    from app.bot.rendering.pillow_utils import try_font
    from app.shared.paths import ASSETS_DIR

    try:
        from PIL import ImageFont
        font = ImageFont.truetype(str(ASSETS_DIR / "fonts" / "Bangers-Regular.ttf"), 230)
    except OSError:
        font = try_font(200, bold=True)
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).text((SIZE / 2, SIZE / 2 + 6), "?", font=font, anchor="mm", fill=255)
    return _from_mask(mask)


def _from_mask(mask: Image.Image) -> bytes:

    halo = mask.filter(ImageFilter.MaxFilter(7)).filter(ImageFilter.GaussianBlur(5))
    out = Image.new("RGBA", (SIZE, SIZE), GLOW + (0,))
    out.putalpha(halo.point(lambda a: a * 4 // 5))
    shape = Image.new("RGBA", (SIZE, SIZE), FILL + (255,))
    shape.putalpha(mask)
    out = Image.alpha_composite(out, shape)

    buffer = io.BytesIO()
    out.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
