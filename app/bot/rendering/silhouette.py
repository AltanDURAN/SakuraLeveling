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

    halo = mask.filter(ImageFilter.MaxFilter(7)).filter(ImageFilter.GaussianBlur(5))
    out = Image.new("RGBA", (SIZE, SIZE), GLOW + (0,))
    out.putalpha(halo.point(lambda a: a * 4 // 5))
    shape = Image.new("RGBA", (SIZE, SIZE), FILL + (255,))
    shape.putalpha(mask)
    out = Image.alpha_composite(out, shape)

    buffer = io.BytesIO()
    out.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
