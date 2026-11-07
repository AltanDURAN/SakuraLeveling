"""Préparation des images d'objets : fond blanc retiré, trous de l'objet
ouverts, mais un reflet ou une plume blanche restent en place."""

from PIL import Image, ImageDraw

from app.shared.image_tools import cut_out_white, has_white_background, prepare_item_image, shrink


def _ring(hole=(255, 255, 255, 255)) -> Image.Image:
    image = Image.new("RGBA", (300, 300), (255, 255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.ellipse([30, 30, 270, 270], fill=(20, 12, 8, 255))     # contour encré
    draw.ellipse([100, 100, 200, 200], fill=hole)
    return image


def test_le_fond_blanc_est_retire():
    out = cut_out_white(_ring((120, 30, 30, 255)))
    assert out.getpixel((5, 5))[3] == 0
    assert out.getpixel((60, 150))[3] == 255


def test_le_centre_blanc_d_un_anneau_est_un_trou():
    out = cut_out_white(_ring())
    assert out.getpixel((150, 150))[3] == 0 and out.getpixel((60, 150))[3] == 255


def test_un_reflet_entoure_de_clair_reste_en_place():
    image = Image.new("RGBA", (300, 300), (255, 255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.ellipse([30, 30, 270, 270], fill=(20, 12, 8, 255))
    draw.ellipse([50, 50, 250, 250], fill=(225, 215, 190, 255))  # une dent, claire
    draw.ellipse([130, 130, 170, 170], fill=(255, 255, 255, 255))  # son reflet
    assert cut_out_white(image).getpixel((150, 150))[3] == 255


def test_une_image_deja_transparente_n_est_pas_retouchee():
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    ImageDraw.Draw(image).ellipse([10, 10, 50, 50], fill=(255, 255, 255, 255))
    assert not has_white_background(image)
    assert prepare_item_image(image).getpixel((30, 30))[3] == 255


def test_la_reduction_n_agrandit_jamais():
    assert shrink(Image.new("RGB", (100, 50)), 512).size == (100, 50)
    assert shrink(Image.new("RGB", (2048, 1024)), 512).size == (512, 256)
