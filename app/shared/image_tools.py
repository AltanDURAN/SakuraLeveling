"""Préparation des images déposées dans l'admin (audit d'ouverture, 07/11/2026).

Les images d'objets arrivent sur fond blanc, à 1 000 px et plus : elles
s'affichaient en carrés blancs dans une interface sombre et pesaient 160 Mo
pour un affichage de 180 px. On les détoure et on les réduit une fois pour
toutes, au dépôt.
"""

from __future__ import annotations

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageStat

#: Un pixel est du fond s'il est au moins aussi clair que ça sur ses trois couleurs.
WHITE_LEVEL = 232
#: Part du pourtour qui doit être blanche pour parler de fond blanc : un dessin
#: peut toucher un ou deux bords (personnage coupé en bas). Seul le blanc RELIÉ
#: au bord est retiré, le reste de l'image n'est jamais touché.
WHITE_BORDER_SHARE = 0.5
#: Blanc ENFERMÉ dans l'objet (centre d'un anneau, d'une sangle, d'un cadre) :
#: c'est le fond vu au travers s'il est franc, assez grand et cerné de sombre
#: (ces images ont un contour encré). Un reflet sur une dent ou une plume
#: blanche, entourés de clair, font partie de l'objet et restent.
HOLE_LEVEL = 250
HOLE_MIN_AREA = 0.0015    # part de l'image
HOLE_SURE_AREA = 0.03     # au-delà, aucun reflet n'est aussi grand : c'est un trou
HOLE_MAX_RIM = 120        # luminosité moyenne maximale du pourtour
#: Côté maximal d'une image d'objet (affichée à 180 px au plus).
ITEM_MAX_SIDE = 512
#: Côté maximal d'une image de monstre (le cadre de combat fait 1 080 px de large).
MOB_MAX_SIDE = 1024

_MARK = 128


def shrink(image: Image.Image, max_side: int) -> Image.Image:
    """L'image réduite à `max_side` (jamais agrandie)."""
    if max(image.size) <= max_side:
        return image
    out = image.copy()
    out.thumbnail((max_side, max_side), Image.LANCZOS)
    return out


def has_white_background(image: Image.Image) -> bool:
    """Fond blanc opaque : au moins `WHITE_BORDER_SHARE` du pourtour est blanc
    et sans transparence. (Jusqu'au 11/11/2026 : les quatre coins — un dessin
    coupé en bas, qui touchait un coin, gardait tout son papier.)"""
    rgba = image.convert("RGBA")
    w, h = rgba.size
    if w < 4 or h < 4:
        return False
    step = max(1, max(w, h) // 200)
    # Un pixel en retrait : un scan a parfois un liseré sombre sur le bord.
    points = [(x, y) for x in range(1, w - 1, step) for y in (1, h - 2)] + \
             [(x, y) for y in range(1, h - 1, step) for x in (1, w - 2)]
    pixels = rgba.load()
    white = sum(1 for p in points if pixels[p][3] > 200 and min(pixels[p][:3]) >= WHITE_LEVEL)
    return white >= WHITE_BORDER_SHARE * len(points)


def _background_mask(rgb: Image.Image) -> Image.Image:
    """Masque (255 = fond) : le blanc RELIÉ AU BORD, plus les trous francs."""
    red, green, blue = rgb.split()
    bright = ImageChops.darker(ImageChops.darker(red, green), blue)
    near = bright.point(lambda v: 255 if v >= WHITE_LEVEL else 0)
    w, h = near.size
    seeds = [(x, y) for x in range(0, w, 4) for y in (0, h - 1)] + \
            [(x, y) for y in range(0, h, 4) for x in (0, w - 1)]
    pixels = near.load()
    for seed in seeds:
        if pixels[seed] == 255:
            ImageDraw.floodfill(near, seed, _MARK)
    background = near.point(lambda v: 255 if v == _MARK else 0)
    return ImageChops.lighter(background, _holes(rgb, bright, background))


def _rim_brightness(region: Image.Image, luma: Image.Image) -> float:
    """Luminosité moyenne juste autour d'une plage (au-delà de son anticrénelage)."""
    rim = ImageChops.subtract(region.filter(ImageFilter.MaxFilter(9)), region.filter(ImageFilter.MaxFilter(5)))
    total = rim.histogram()[255]
    return ImageStat.Stat(luma, rim).mean[0] if total else 255.0


def _holes(rgb: Image.Image, bright: Image.Image, background: Image.Image) -> Image.Image:
    """Les trous de l'objet (cf. HOLE_LEVEL). L'érosion écarte d'abord les
    filets de blanc, trop fins pour être autre chose qu'un reflet."""
    candidates = ImageChops.subtract(bright.point(lambda v: 255 if v >= HOLE_LEVEL else 0), background)
    cores = candidates.filter(ImageFilter.MinFilter(5))
    luma = rgb.convert("L")
    image_area = bright.width * bright.height
    holes = Image.new("L", bright.size, 0)
    pixels = cores.load()
    for y in range(0, bright.height, 3):
        for x in range(0, bright.width, 3):
            if pixels[x, y] != 255:
                continue
            ImageDraw.floodfill(candidates, (x, y), _MARK)
            region = candidates.point(lambda v: 255 if v == _MARK else 0)
            area = region.histogram()[255]
            # Le trou est retiré des candidats et son cœur oublié dans tous les cas.
            candidates = ImageChops.subtract(candidates, region.point(lambda v: 255 if v else 0))
            candidates = candidates.point(lambda v: 0 if v == _MARK else v)
            cores = ImageChops.subtract(cores, region)
            pixels = cores.load()
            if area >= HOLE_SURE_AREA * image_area or (
                    area >= HOLE_MIN_AREA * image_area and _rim_brightness(region, luma) <= HOLE_MAX_RIM):
                holes = ImageChops.lighter(holes, region)
    return holes


def cut_out_white(image: Image.Image) -> Image.Image:
    """Enlève le fond blanc : bord adouci d'un pixel, sans liseré clair."""
    rgba = image.convert("RGBA")
    background = _background_mask(rgba.convert("RGB"))
    # Le fond grignote un pixel de bord (l'anticrénelage y mélange l'objet et
    # le blanc), puis la limite est adoucie.
    soft = background.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.GaussianBlur(0.7))
    rgba.putalpha(ImageChops.multiply(rgba.getchannel("A"), ImageChops.invert(soft)))
    return rgba


def prepare_item_image(image: Image.Image) -> Image.Image:
    """L'image d'un objet telle qu'on la range : réduite et détourée."""
    small = shrink(image.convert("RGBA"), ITEM_MAX_SIDE)
    return cut_out_white(small) if has_white_background(small) else small
