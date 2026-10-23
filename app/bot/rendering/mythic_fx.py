"""Effets visuels des pièces MYTHIQUES (équipement v2).

Une carte de pièce mythique reçoit un cadre animé : un liseré rouge mythique
lumineux, parcouru par deux éclats dorés qui tournent autour de la carte. Le
rendu de base (statique) est fait une seule fois ; seules les images de
l'animation sont recomposées, puis enregistrées en GIF (le format que Discord
anime dans un embed).

Pillow seul, sans numpy : le calcul reste léger (12 images, flou sur la seule
zone des cartes concernées).
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

MYTHIC_RED = (235, 70, 90)
MYTHIC_GOLD = (255, 214, 130)

FRAMES = 12
FRAME_MS = 90
_TRAIL = 24          # nombre de points de la traînée d'un éclat
_TRAIL_SPAN = 0.07   # longueur de la traînée, en fraction du périmètre
_PAD = 10            # marge autour de la carte pour le halo


def _perimeter_point(w: int, h: int, t: float, r: int) -> tuple[float, float]:
    """Point du contour (rectangle w×h aux coins arrondis de rayon r) à la
    fraction `t` du périmètre, dans le sens horaire depuis le haut gauche."""
    r = max(0, min(r, w // 2, h // 2))
    straight_w, straight_h, arc = w - 2 * r, h - 2 * r, math.pi * r / 2
    d = (t % 1.0) * 2 * (straight_w + straight_h + 2 * arc)
    # (longueur, fonction position) pour chaque morceau du contour
    pieces = (
        (straight_w, lambda u: (r + u, 0)),
        (arc, lambda u: _arc(w - r, r, r, -90 + 90 * u / arc if arc else 0)),
        (straight_h, lambda u: (w, r + u)),
        (arc, lambda u: _arc(w - r, h - r, r, 90 * u / arc if arc else 0)),
        (straight_w, lambda u: (w - r - u, h)),
        (arc, lambda u: _arc(r, h - r, r, 90 + 90 * u / arc if arc else 0)),
        (straight_h, lambda u: (0, h - r - u)),
        (arc, lambda u: _arc(r, r, r, 180 + 90 * u / arc if arc else 0)),
    )
    for length, at in pieces:
        if d <= length:
            return at(d)
        d -= length
    return r, 0


def _arc(cx: float, cy: float, r: float, deg: float) -> tuple[float, float]:
    a = math.radians(deg)
    return cx + r * math.cos(a), cy + r * math.sin(a)


def _static_glow(w: int, h: int, radius: int) -> Image.Image:
    """Liseré + halo rouge fixes, dessinés une fois par carte."""
    layer = Image.new("RGBA", (w + 2 * _PAD, h + 2 * _PAD), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    box = [(_PAD, _PAD), (_PAD + w - 1, _PAD + h - 1)]
    d.rounded_rectangle(box, radius=radius, outline=(*MYTHIC_RED, 200), width=6)
    halo = layer.filter(ImageFilter.GaussianBlur(5))
    d = ImageDraw.Draw(halo)
    d.rounded_rectangle(box, radius=radius, outline=(*MYTHIC_RED, 255), width=2)
    return halo


def _sparks(w: int, h: int, phase: float, radius: int) -> Image.Image:
    """Deux éclats dorés opposés, avec traînée, à la position `phase`."""
    layer = Image.new("RGBA", (w + 2 * _PAD, h + 2 * _PAD), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for head in (phase, phase + 0.5):
        for i in range(_TRAIL):
            k = i / _TRAIL                     # 0 = tête, 1 = bout de la traînée
            x, y = _perimeter_point(w - 1, h - 1, head - k * _TRAIL_SPAN, radius)
            r = 5 - 3 * k
            alpha = int(255 * (1 - k) ** 1.5)
            d.ellipse([(_PAD + x - r, _PAD + y - r), (_PAD + x + r, _PAD + y + r)],
                      fill=(*MYTHIC_GOLD, alpha))
    glow = layer.filter(ImageFilter.GaussianBlur(3))
    glow.alpha_composite(layer)
    return glow


def mythic_frames(base: Image.Image, boxes: list[tuple[int, int, int, int]],
                  *, radius: int = 16, frames: int = FRAMES) -> list[Image.Image]:
    """Images de l'animation : `base` + cadre animé sur chaque `box` (x, y, w, h)."""
    base = base.convert("RGBA")
    glows = [(_static_glow(w, h, radius), (x - _PAD, y - _PAD), (w, h)) for x, y, w, h in boxes]
    out = []
    for f in range(frames):
        frame = base.copy()
        for glow, origin, (w, h) in glows:
            frame.alpha_composite(glow, origin)
            frame.alpha_composite(_sparks(w, h, f / frames, radius), origin)
        out.append(frame.convert("RGB"))
    return out


def save_mythic_gif(base: Image.Image, boxes: list[tuple[int, int, int, int]],
                    output_path: str, *, radius: int = 16) -> str:
    """Enregistre l'animation en GIF à côté de `output_path` ; renvoie son chemin.

    Une seule palette pour toutes les images (calculée sur la première, qui
    contient déjà le rouge et l'or) : sinon les couleurs du fond « clignotent »
    d'une image à l'autre."""
    frames = mythic_frames(base, boxes, radius=radius)
    palette = frames[0].quantize(colors=255, method=Image.Quantize.MEDIANCUT)
    quantized = [fr.quantize(palette=palette, dither=Image.Dither.FLOYDSTEINBERG) for fr in frames]
    path = str(Path(output_path).with_suffix(".gif"))
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    quantized[0].save(path, save_all=True, append_images=quantized[1:],
                      duration=FRAME_MS, loop=0, optimize=True, disposal=1)
    return path
