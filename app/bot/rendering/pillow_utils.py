"""Helpers Pillow partagés entre les rendus (banner profil, équipement,
encounters, etc).

Centralise les primitives qui étaient dupliquées entre `profile_banner.py`
et `equipment_image.py` :
- chargement de polices avec cache
- dégradé vertical
- texte avec ombre
- décoration de pétales sakura

Les versions plus élaborées (panneaux avec teinte d'accent, vignettes…)
restent dans leurs modules respectifs car spécifiques au look-and-feel
de chaque rendu.
"""

from __future__ import annotations

import math
import random
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont


@lru_cache(maxsize=64)
def try_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    """Charge une police DejaVu, retombe sur la police par défaut si
    DejaVu n'est pas installé. Cachée — Pillow alloue beaucoup à chaque
    `truetype()`, on évite la pénalité par render."""
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    try:
        return ImageFont.truetype(name, size)
    except Exception:
        return ImageFont.load_default()


def gradient_background(
    width: int,
    height: int,
    top: tuple[int, int, int, int],
    bottom: tuple[int, int, int, int],
) -> Image.Image:
    """Image RGBA avec dégradé vertical linéaire `top` → `bottom`."""
    bg = Image.new("RGBA", (width, height), top)
    draw = ImageDraw.Draw(bg)
    for y in range(height):
        ratio = y / max(1, height - 1)
        r = int(top[0] + (bottom[0] - top[0]) * ratio)
        g = int(top[1] + (bottom[1] - top[1]) * ratio)
        b = int(top[2] + (bottom[2] - top[2]) * ratio)
        draw.line((0, y, width, y), fill=(r, g, b, 255))
    return bg


def draw_text_with_shadow(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font,
    fill,
    shadow,
    shadow_offset: tuple[int, int] = (2, 2),
) -> None:
    """Texte avec ombre portée (deux passes : ombre offsetée puis texte)."""
    x, y = xy
    sx, sy = shadow_offset
    draw.text((x + sx, y + sy), text, font=font, fill=shadow)
    draw.text(xy, text, font=font, fill=fill)


def draw_sakura_petals(
    base: Image.Image,
    seed: int = 42,
    count: int = 28,
    palette: list[tuple[int, int, int, int]] | None = None,
    size_range: tuple[int, int] = (36, 72),
) -> None:
    """Décor de fond : fleurs de cerisier dispersées en filigrane.

    Chaque fleur = 5 ellipses superposées en éventail (silhouette de
    fleur 5 pétales) puis canvas pivoté pour casser la régularité.
    `seed` permet d'avoir un layout déterministe par joueur ou par card.
    """
    if palette is None:
        palette = [
            (255, 200, 215, 80),
            (255, 180, 200, 70),
            (255, 220, 230, 65),
            (250, 170, 200, 75),
        ]
    rng = random.Random(seed)
    w, h = base.size
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))

    for _ in range(count):
        size = rng.randint(*size_range)
        cx = rng.randint(-size // 2, w + size // 2)
        cy = rng.randint(-size // 2, h + size // 2)
        rotation = rng.randint(0, 359)
        color = rng.choice(palette)

        pad = int(size * 1.4)
        petal = Image.new("RGBA", (pad, pad), (0, 0, 0, 0))
        pd = ImageDraw.Draw(petal)
        center_x = pad // 2
        center_y = pad // 2
        petal_w = size // 3
        petal_h = int(size * 0.55)
        for i in range(5):
            angle = math.radians(-90 + i * 72)
            ex = center_x + int(size * 0.18 * math.cos(angle))
            ey = center_y + int(size * 0.18 * math.sin(angle))
            pd.ellipse(
                (
                    ex - petal_w // 2,
                    ey - petal_h // 2,
                    ex + petal_w // 2,
                    ey + petal_h // 2,
                ),
                fill=color,
            )

        rotated = petal.rotate(rotation, resample=Image.BICUBIC, expand=False)
        overlay.alpha_composite(
            rotated,
            (cx - rotated.width // 2, cy - rotated.height // 2),
        )

    base.alpha_composite(overlay)
