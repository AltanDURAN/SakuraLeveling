"""Scène de combat rendue en image (décor + monstre + HUD joueurs).

**Cadre fixe 4:5 vertical (1080×1350)** : c'est le format vertical qui
s'affiche le plus large sur PC (Discord plafonne la hauteur des images inline,
donc tous les formats verticaux finissent à la même hauteur — seule la largeur
varie) tout en restant franchement vertical sur mobile.

**Décor découplé du monstre** :
  - `spot` = environnement (background, crop, ground_y) — vient du couple
    (zone, élément) ; partagé par tous les monstres de cet élément dans la zone.
  - `placement` = placement du monstre (scale, offset_x, shadow) — propre au
    monstre ; ses pieds se posent sur `ground_y` du spot.
Sans spot/placement → rendu automatique (décor zoomé + monstre posé au sol).

Le HUD est auto-portant et dessiné PAR-DESSUS le monstre : bandeau haut (badge
d'élément + nom + power + barre de vie), bandeau bas (joueurs : avatar +
mini-barre de vie + nom). Barres mob et joueurs : même règle couleur.
"""

import logging

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from app.bot.rendering.element_visuals import make_element_badge, tint_by_element
from app.bot.rendering.image_utils import (
    add_outline,
    crop_to_circle,
    download_image,
    get_hp_color,
    load_background,
)
from app.shared.paths import LANDSCAPES_ASSETS_DIR, MOBS_ASSETS_DIR

_logger = logging.getLogger(__name__)

# --- Cadre fixe 4:5 ---
FRAME_W, FRAME_H = 1080, 1350
FRAME_RATIO = FRAME_H / FRAME_W

# Bandeaux HUD (positions fixes).
TOP_PANEL = (22, 18, FRAME_W - 22, 152)
BOTTOM_PANEL = (22, 1194, FRAME_W - 22, 1332)
# Zone utile pour le monstre (entre les deux bandeaux) — utilisée par le
# placement AUTOMATIQUE et comme repère dans l'éditeur.
STAGE_TOP, STAGE_BOTTOM = 152, 1194

_PANEL_FILL = (12, 10, 16, 165)
_PANEL_BORDER = (255, 255, 255, 32)
_AUTO_DECOR_ZOOM = 1.35   # zoom du décor quand aucune scène n'est composée
_AUTO_MOB_FILL = 0.92     # part de la zone occupée par le monstre en auto

_FONTS = {"title": 46, "stat": 30, "hp": 26, "badge": 96, "av_d": 88}


# --------------------------------------------------------------------------
# Helpers image
# --------------------------------------------------------------------------
def _cover_fit(image: Image.Image, w: int, h: int) -> Image.Image:
    """Redimensionne pour COUVRIR (w, h) en gardant le ratio, puis recadre au
    centre (pas de distorsion)."""
    image = image.convert("RGBA")
    if image.size == (w, h):
        return image
    scale = max(w / image.width, h / image.height)
    nw, nh = max(w, int(image.width * scale)), max(h, int(image.height * scale))
    resized = image.resize((nw, nh), Image.LANCZOS)
    left, top = (nw - w) // 2, (nh - h) // 2
    return resized.crop((left, top, left + w, top + h))


def crop_background(image: Image.Image, crop: dict) -> Image.Image:
    """Applique un cadrage en FRACTIONS sur l'image d'environnement et le
    ramène aux dimensions du cadre. `crop` = {x, y, w} (la hauteur découle du
    ratio du cadre). Partagé avec l'éditeur admin pour un WYSIWYG exact."""
    image = image.convert("RGBA")
    W, H = image.size
    cw = max(0.02, min(1.0, float(crop.get("w", 1.0) or 1.0)))
    px_w = cw * W
    px_h = px_w * FRAME_RATIO
    if px_h > H:  # le cadrage demandé dépasse en hauteur → on borne
        px_h = H
        px_w = px_h / FRAME_RATIO
    x = max(0.0, min(1.0, float(crop.get("x", 0.0) or 0.0))) * W
    y = max(0.0, min(1.0, float(crop.get("y", 0.0) or 0.0))) * H
    x = max(0.0, min(x, W - px_w))
    y = max(0.0, min(y, H - px_h))
    box = (int(round(x)), int(round(y)), int(round(x + px_w)), int(round(y + px_h)))
    return image.crop(box).resize((FRAME_W, FRAME_H), Image.LANCZOS)


def mob_content(raw_mob: Image.Image) -> Image.Image:
    """Recadre le monstre sur ses pixels réels (bbox du non-transparent)."""
    raw_mob = raw_mob.convert("RGBA")
    bbox = raw_mob.getchannel("A").getbbox() or (0, 0, raw_mob.width, raw_mob.height)
    return raw_mob.crop(bbox)


def place_mob(content: Image.Image, placement: dict, ground_y: float) -> tuple[Image.Image, tuple[int, int]]:
    """Place le monstre : `scale` = hauteur du monstre / hauteur du cadre,
    `offset_x` = décalage horizontal (fraction, 0 = centré), `offset_y` =
    décalage vertical (fraction, <0 = plus haut, utile pour un monstre qui
    flotte). Les pieds se posent sur `ground_y` + `offset_y` (fractions)."""
    scale_frac = max(0.05, min(1.5, float(placement.get("scale", 0.62) or 0.62)))
    target_h = max(1, int(round(scale_frac * FRAME_H)))
    ratio = target_h / content.height
    nw = max(1, int(round(content.width * ratio)))
    img = content.resize((nw, target_h), Image.LANCZOS)
    cx = (0.5 + float(placement.get("offset_x", 0.0) or 0.0)) * FRAME_W
    base_y = float(ground_y if ground_y is not None else 0.86)
    fy = max(0.0, min(1.2, base_y + float(placement.get("offset_y", 0.0) or 0.0))) * FRAME_H
    return img, (int(round(cx - nw / 2)), int(round(fy - target_h)))


def _auto_place_mob(content: Image.Image) -> tuple[Image.Image, tuple[int, int]]:
    """Placement automatique (aucune scène composée) : le monstre remplit la
    zone entre les bandeaux, centré, posé au sol."""
    stage_h = (STAGE_BOTTOM - STAGE_TOP) * _AUTO_MOB_FILL
    ratio = min(stage_h / content.height, (FRAME_W * 0.86) / content.width)
    nw, nh = max(1, round(content.width * ratio)), max(1, round(content.height * ratio))
    img = content.resize((nw, nh), Image.LANCZOS)
    return img, ((FRAME_W - nw) // 2, STAGE_BOTTOM - nh)


def draw_contact_shadow(base: Image.Image, pos: tuple[int, int], size: tuple[int, int]) -> None:
    """Ombre de contact douce sous le monstre → il paraît posé DANS le décor."""
    nw, nh = size
    cx = pos[0] + nw / 2
    fy = pos[1] + nh
    rw = max(12.0, nw * 0.42)
    rh = max(7.0, nw * 0.10)
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).ellipse(
        [cx - rw, fy - rh, cx + rw, fy + rh], fill=(0, 0, 0, 115),
    )
    layer = layer.filter(ImageFilter.GaussianBlur(radius=max(4, rh * 0.8)))
    base.alpha_composite(layer)


def _panel(base: Image.Image, box, radius: int = 24) -> None:
    x1, y1, x2, y2 = box
    overlay = Image.new("RGBA", (x2 - x1, y2 - y1), (0, 0, 0, 0))
    ImageDraw.Draw(overlay).rounded_rectangle(
        [0, 0, x2 - x1 - 1, y2 - y1 - 1], radius=radius,
        fill=_PANEL_FILL, outline=_PANEL_BORDER, width=2,
    )
    base.alpha_composite(overlay, (x1, y1))


def _draw_ratio_bar(base, draw, x1, y1, x2, y2, current, maximum) -> None:
    """Barre de vie : couleur selon le % de PV (vert plein → rouge), vide à 0%."""
    r = (y2 - y1) // 2
    draw.rounded_rectangle([x1, y1, x2, y2], radius=r,
                           fill=(22, 18, 26, 235), outline=(255, 255, 255, 55), width=2)
    ratio = max(0.0, min(1.0, current / maximum)) if maximum > 0 else 0.0
    fill_w = int((x2 - x1 - 6) * ratio)
    if fill_w > 6:
        color = get_hp_color(current, maximum)
        fill = Image.new("RGBA", (fill_w, y2 - y1 - 6), (color[0], color[1], color[2], 255))
        mask = Image.new("L", fill.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            [0, 0, fill_w - 1, fill.size[1] - 1], radius=(y2 - y1 - 6) // 2, fill=255)
        fill.putalpha(mask)
        base.alpha_composite(fill, (x1 + 3, y1 + 3))


def _load_mob_image(image_name: str | None) -> Image.Image:
    if image_name:
        try:
            return Image.open(MOBS_ASSETS_DIR / image_name).convert("RGBA")
        except Exception as e:
            _logger.warning("Chargement image mob %s échoué : %s", image_name, e)
    return Image.new("RGBA", (600, 600), (120, 120, 120, 255))


def render_scene(
    *,
    mob: dict | None,
    players: list[dict] | None = None,
    background_path: str | None = None,
    spot: dict | None = None,
    placement: dict | None = None,
) -> Image.Image:
    """Compose la scène complète et renvoie l'image (RGB). Utilisé par le bot
    ET par l'aperçu de l'éditeur admin → WYSIWYG garanti.

    `spot` = environnement (background, crop, ground_y). `placement` = placement
    du monstre (scale, offset_x, shadow). Sans eux → rendu automatique."""
    players = players or []
    mob = mob or None

    # ---- Décor (vient du spot) ----
    bg_path = background_path
    if spot and spot.get("background"):
        bg_path = str(LANDSCAPES_ASSETS_DIR / spot["background"])
    raw_bg = load_background(bg_path, size=(FRAME_W, FRAME_H))
    if spot and spot.get("crop"):
        result = crop_background(raw_bg, spot["crop"])
    else:
        zoomed = raw_bg
        if _AUTO_DECOR_ZOOM > 1.0:
            cw = int(raw_bg.width / _AUTO_DECOR_ZOOM)
            ch = int(raw_bg.height / _AUTO_DECOR_ZOOM)
            zoomed = raw_bg.crop(((raw_bg.width - cw) // 2, (raw_bg.height - ch) // 2,
                                  (raw_bg.width - cw) // 2 + cw, (raw_bg.height - ch) // 2 + ch))
        result = _cover_fit(zoomed, FRAME_W, FRAME_H)

    draw = ImageDraw.Draw(result)
    try:
        title_font = ImageFont.truetype("DejaVuSans-Bold.ttf", _FONTS["title"])
        stat_font = ImageFont.truetype("DejaVuSans-Bold.ttf", _FONTS["stat"])
        hp_font = ImageFont.truetype("DejaVuSans-Bold.ttf", _FONTS["hp"])
    except Exception:
        title_font = stat_font = hp_font = ImageFont.load_default()

    # ---- Monstre (le HUD passera par-dessus) ----
    if mob is not None:
        content = mob_content(_load_mob_image(mob.get("image_name")))
        if placement:
            ground_y = (spot or {}).get("ground_y", 0.86)
            mob_img, mob_pos = place_mob(content, placement, ground_y)
            shadow = placement.get("shadow", True)
        else:
            mob_img, mob_pos = _auto_place_mob(content)
            shadow = True
        if shadow:
            draw_contact_shadow(result, mob_pos, mob_img.size)
        element = mob.get("element") or ""
        if element:
            mob_img = tint_by_element(mob_img, element)
        result.alpha_composite(mob_img, mob_pos)

    # ---- Bandeau MOB (haut) ----
    _panel(result, TOP_PANEL)
    if mob is not None:
        pl, pt, pr, pb = TOP_PANEL
        badge_d = _FONTS["badge"]
        name_x = pl + 30
        element = mob.get("element") or ""
        if element:
            badge = make_element_badge(element, diameter=badge_d)
            if badge is not None:
                result.alpha_composite(badge, (pl + 18, pt + (pb - pt - badge_d) // 2))
                name_x = pl + 18 + badge_d + 18
        draw.text((name_x, pt + 12), mob.get("name", "Monstre"), font=title_font,
                  fill=(255, 255, 255, 255))
        power = mob.get("power_score", "")
        if power:
            ptxt = f"[ {power} ]"
            draw.text((pr - 16 - draw.textlength(ptxt, font=stat_font), pt + 20),
                      ptxt, font=stat_font, fill=(235, 226, 236, 255))
        cur = int(mob.get("current_hp", 0) or 0)
        mx = int(mob.get("max_hp", 0) or 0)
        bar_y2, bar_y1 = pb - 14, pb - 50
        _draw_ratio_bar(result, draw, name_x, bar_y1, pr - 16, bar_y2, cur, mx)
        hp_txt = f"{cur} / {mx}" if cur > 0 else "Vaincu"
        draw.text(((name_x + pr - 16) / 2 - draw.textlength(hp_txt, font=hp_font) / 2,
                   bar_y1 + 5), hp_txt, font=hp_font, fill=(255, 255, 255, 255))
        # Barre de BOUCLIER (bleu) par-dessus les PV — s'épuise avant les PV.
        shield = int(mob.get("shield", 0) or 0)
        if shield > 0 and mx > 0:
            sratio = max(0.0, min(1.0, shield / mx))
            sx1, sx2, sy1, sy2 = name_x, pr - 16, bar_y1 - 13, bar_y1 - 3
            draw.rounded_rectangle([sx1, sy1, sx2, sy2], radius=5, fill=(18, 22, 40, 190))
            fill_w = int((sx2 - sx1) * sratio)
            if fill_w > 4:
                draw.rounded_rectangle([sx1, sy1, sx1 + fill_w, sy2], radius=5, fill=(74, 150, 255, 240))
            draw.text((sx1 + 6, sy1 - 1), f"Bouclier {shield}", font=hp_font, fill=(190, 218, 255, 255))

    # ---- Bandeau JOUEURS (bas) ----
    _panel(result, BOTTOM_PANEL)
    if players:
        bl, bt, br, bb = BOTTOM_PANEL
        count = len(players)
        slot_x1, slot_x2 = bl + 24, br - 24
        step = (slot_x2 - slot_x1) / max(1, count)
        av_d = max(44, min(_FONTS["av_d"], int(step) - 8))
        bar_half = int(av_d * 0.58)
        av_y = bt + 8
        for i, player in enumerate(players):
            cx = int(slot_x1 + step * (i + 0.5))
            try:
                raw_avatar = download_image(player["avatar_url"])
            except Exception:
                raw_avatar = Image.new("RGBA", (av_d, av_d), (120, 120, 120, 255))
            cur = int(player.get("current_hp", 0) or 0)
            mx = int(player.get("max_hp", 1) or 1)
            avatar = add_outline(crop_to_circle(raw_avatar, av_d), outline_size=3)
            result.alpha_composite(avatar, (cx - avatar.width // 2, av_y))
            bar_y = av_y + avatar.height + 2
            _draw_ratio_bar(result, draw, cx - bar_half, bar_y, cx + bar_half, bar_y + 16, cur, mx)
            name = player.get("name", "")
            if name:
                draw.text((cx - draw.textlength(name, font=hp_font) / 2, bar_y + 18),
                          name, font=hp_font, fill=(240, 240, 245, 255))

    # Léger renforcement de netteté (compense la vignette WebP de l'aperçu).
    return result.convert("RGB").filter(
        ImageFilter.UnsharpMask(radius=2, percent=95, threshold=2)
    )


def compose_players_banner(
    players: list[dict],
    output_path: str = "result.png",
    background_path: str | None = None,
    mob: dict | None = None,
    players_power_score: str = "",
    spot: dict | None = None,
    placement: dict | None = None,
):
    """Point d'entrée du bot. `spot` (environnement du couple zone×élément) et
    `placement` (placement du monstre) sont résolus par l'appelant (encounter).
    Sans eux → rendu automatique (fallback)."""
    image = render_scene(
        mob=mob, players=players, background_path=background_path,
        spot=spot, placement=placement,
    )
    image.save(output_path)
    _logger.debug("Scène de combat générée : %s", output_path)
