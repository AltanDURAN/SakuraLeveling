"""Scène de combat rendue en image (fond + monstre + HUD joueurs).

**Orientation adaptative** : le cadre est choisi d'après la forme réelle du
monstre (bbox du contenu non transparent). Un monstre nettement plus HAUT que
large sort en **portrait** (il remplit mieux le cadre → on le voit beaucoup
mieux, surtout sur mobile) ; sinon **paysage** (qui s'affiche grand sur PC).

Dans les deux cas : décor recadré/zoomé (sans distorsion), monstre dimensionné
d'après ses pixels réels (échelle relative préservée) et contenu ENTRE les deux
bandeaux, HUD auto-portant (haut = mob + barre de vie, bas = joueurs). Barres de
vie mob et joueurs : même règle couleur (vert→rouge selon les PV).
"""

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from app.bot.rendering.element_visuals import make_element_badge, tint_by_element
from app.bot.rendering.image_utils import (
    add_outline,
    crop_to_circle,
    download_image,
    get_hp_color,
    load_background,
)
from app.shared.paths import MOBS_ASSETS_DIR

_PANEL_FILL = (12, 10, 16, 165)
_PANEL_BORDER = (255, 255, 255, 32)

# Bascule en portrait si le contenu du monstre est au moins 1.2× plus haut que
# large. Réglable (plus grand = passe en portrait moins souvent).
_PORTRAIT_THRESHOLD = 1.2

# Le monstre est recadré sur ses pixels réels puis mis à l'échelle pour REMPLIR
# la zone disponible entre les deux bandeaux. `_SCALE_POWER` atténue l'écart de
# taille entre monstres selon la part de leur canvas qu'ils occupent :
#   0.0 = tous remplissent pareil (aucune différence d'échelle) ;
#   0.3 = remplissent presque, léger « petit reste un peu plus petit » (défaut) ;
#   1.0 = échelle stricte (un mob à 50% de son canvas = 50% de la taille).
_SCALE_POWER = 0.3

# Deux mises en page. `mob_max_span` = taille écran du plus grand côté pour un
# monstre qui remplit tout son canvas source ; l'échelle réelle est ensuite
# proportionnelle à la part du canvas occupée. Le monstre est borné pour rester
# entre `stage_top` et `stage_bottom` (entre les deux bandeaux).
_LANDSCAPE = {
    "W": 1536, "H": 1024,
    "top": (28, 22, 1508, 170), "bottom": (28, 846, 1508, 1010),
    "stage_top": 185, "stage_bottom": 838,
    "decor_zoom": 1.6,
    "title": 54, "stat": 36, "hp": 28, "badge": 104, "av_d": 96,
}
_PORTRAIT = {
    "W": 1024, "H": 1536,
    "top": (20, 18, 1004, 150), "bottom": (20, 1362, 1004, 1518),
    "stage_top": 165, "stage_bottom": 1356,
    "decor_zoom": 1.4,
    "title": 46, "stat": 30, "hp": 26, "badge": 96, "av_d": 88,
}


def _cover_fit(image: Image.Image, w: int, h: int) -> Image.Image:
    """Redimensionne pour COUVRIR (w, h) en gardant le ratio, puis recadre au
    centre. Pas de distorsion."""
    image = image.convert("RGBA")
    if image.size == (w, h):
        return image
    scale = max(w / image.width, h / image.height)
    nw, nh = max(w, int(image.width * scale)), max(h, int(image.height * scale))
    resized = image.resize((nw, nh), Image.LANCZOS)
    left, top = (nw - w) // 2, (nh - h) // 2
    return resized.crop((left, top, left + w, top + h))


def _zoom_decor(image: Image.Image, factor: float) -> Image.Image:
    """Recadre le centre (facteur de zoom) → décor « rapproché »."""
    if factor <= 1.0:
        return image
    cw, ch = int(image.width / factor), int(image.height / factor)
    cx, cy = (image.width - cw) // 2, (image.height - ch) // 2
    return image.crop((cx, cy, cx + cw, cy + ch))


def _panel(base: Image.Image, box, radius: int) -> None:
    """Bandeau translucide arrondi (composé pour laisser voir le décor)."""
    x1, y1, x2, y2 = box
    overlay = Image.new("RGBA", (x2 - x1, y2 - y1), (0, 0, 0, 0))
    ImageDraw.Draw(overlay).rounded_rectangle(
        [0, 0, x2 - x1 - 1, y2 - y1 - 1], radius=radius,
        fill=_PANEL_FILL, outline=_PANEL_BORDER, width=2,
    )
    base.alpha_composite(overlay, (x1, y1))


def _draw_ratio_bar(base, draw, x1, y1, x2, y2, current, maximum) -> None:
    """Barre de vie arrondie, MÊME règle mob/joueurs : couleur selon le % de PV
    (vert plein → rouge à bas PV via get_hp_color), vide à 0%."""
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


def _choose_layout(mob):
    """Charge l'image du monstre (une fois) et choisit paysage/portrait d'après
    la forme réelle de son contenu. Renvoie (layout, raw_mob | None)."""
    raw = None
    if mob is not None and mob.get("image_name"):
        try:
            raw = Image.open(MOBS_ASSETS_DIR / mob["image_name"]).convert("RGBA")
        except Exception as e:
            print(f"Erreur chargement image mob : {e}")
            raw = None
        if raw is not None:
            bbox = raw.getchannel("A").getbbox()
            if bbox:
                cw, ch = bbox[2] - bbox[0], bbox[3] - bbox[1]
                if ch >= cw * _PORTRAIT_THRESHOLD:
                    return _PORTRAIT, raw
    return _LANDSCAPE, raw


def _fit_mob(raw_mob, element, L):
    """Dimensionne le monstre d'après ses pixels réels (échelle relative
    préservée), le borne entre les deux bandeaux, l'ancre au sol et le centre."""
    raw_mob = raw_mob.convert("RGBA")
    bbox = raw_mob.getchannel("A").getbbox() or (0, 0, raw_mob.width, raw_mob.height)
    content = raw_mob.crop(bbox)
    cw, ch = content.size
    canvas_dim = max(raw_mob.width, raw_mob.height)
    # Échelle pour REMPLIR la zone (entre les deux bandeaux), en gardant l'aspect.
    fill_scale = min((L["stage_bottom"] - L["stage_top"]) / ch, (L["W"] * 0.82) / cw)
    # Atténuation d'échelle selon la part du canvas occupée (voir _SCALE_POWER).
    frac = max(cw, ch) / canvas_dim
    scale = fill_scale * (frac ** _SCALE_POWER)
    nw, nh = max(1, round(cw * scale)), max(1, round(ch * scale))
    mob_img = content.resize((nw, nh), Image.LANCZOS)
    if element:
        mob_img = tint_by_element(mob_img, element)
    return mob_img, ((L["W"] - nw) // 2, L["stage_bottom"] - nh)


def compose_players_banner(
    players: list[dict],
    output_path: str = "result.png",
    background_path: str | None = None,
    mob: dict | None = None,
    players_power_score: str = "",
):
    """players = [{avatar_url, current_hp, max_hp, name}], mob = {name,
    image_name, current_hp, max_hp, element, power_score}. L'orientation
    (paysage/portrait) est choisie automatiquement selon la forme du monstre."""
    L, raw_mob = _choose_layout(mob)
    W, H = L["W"], L["H"]
    result = _cover_fit(_zoom_decor(load_background(background_path, size=(W, H)), L["decor_zoom"]), W, H)
    draw = ImageDraw.Draw(result)

    try:
        title_font = ImageFont.truetype("DejaVuSans-Bold.ttf", L["title"])
        stat_font = ImageFont.truetype("DejaVuSans-Bold.ttf", L["stat"])
        hp_font = ImageFont.truetype("DejaVuSans-Bold.ttf", L["hp"])
    except Exception:
        title_font = stat_font = hp_font = ImageFont.load_default()

    # ----- 1. Monstre (les bandeaux HUD passeront PAR-DESSUS) -----
    if mob is not None:
        if raw_mob is None:  # image absente/illisible → placeholder gris
            raw_mob = Image.new("RGBA", (600, 600), (120, 120, 120, 255))
        mob_img, mob_pos = _fit_mob(raw_mob, mob.get("element") or "", L)
        result.alpha_composite(mob_img, mob_pos)

    # ----- 2. Bandeau MOB (haut) : badge + nom + power + barre PV -----
    _panel(result, L["top"], radius=26)
    if mob is not None:
        pl, pt, pr, pb = L["top"]
        badge_d = L["badge"]
        name_x = pl + 32
        mob_element = mob.get("element") or ""
        if mob_element:
            badge = make_element_badge(mob_element, diameter=badge_d)
            if badge is not None:
                result.alpha_composite(badge, (pl + 20, pt + (pb - pt - badge_d) // 2))
                name_x = pl + 20 + badge_d + 20

        draw.text((name_x, pt + 14), mob.get("name", "Monstre"), font=title_font,
                  fill=(255, 255, 255, 255))
        mob_power = mob.get("power_score", "")
        if mob_power:
            ptxt = f"[ {mob_power} ]"
            draw.text((pr - 18 - draw.textlength(ptxt, font=stat_font), pt + 22),
                      ptxt, font=stat_font, fill=(235, 226, 236, 255))

        cur = int(mob.get("current_hp", 0) or 0)
        mx = int(mob.get("max_hp", 0) or 0)
        bar_y2, bar_y1 = pb - 16, pb - 56
        _draw_ratio_bar(result, draw, name_x, bar_y1, pr - 18, bar_y2, cur, mx)
        hp_txt = f"{cur} / {mx}" if cur > 0 else "Vaincu"
        draw.text(((name_x + pr - 18) / 2 - draw.textlength(hp_txt, font=hp_font) / 2,
                   bar_y1 + 6), hp_txt, font=hp_font, fill=(255, 255, 255, 255))

    # ----- 3. Bandeau JOUEURS (bas) : avatars + mini-barre PV + nom -----
    _panel(result, L["bottom"], radius=26)
    if players:
        bl, bt, br, bb = L["bottom"]
        count = len(players)
        slot_x1, slot_x2 = bl + 28, br - 28
        step = (slot_x2 - slot_x1) / max(1, count)
        av_d = max(48, min(L["av_d"], int(step) - 8))  # rétrécit si gros groupe
        bar_half = int(av_d * 0.58)
        av_y = bt + 8

        for i, player in enumerate(players):
            center_x = int(slot_x1 + step * (i + 0.5))
            try:
                raw_avatar = download_image(player["avatar_url"])
            except Exception:
                raw_avatar = Image.new("RGBA", (av_d, av_d), (120, 120, 120, 255))

            cur = int(player.get("current_hp", 0) or 0)
            mx = int(player.get("max_hp", 1) or 1)
            avatar = add_outline(crop_to_circle(raw_avatar, av_d), outline_size=3)
            result.alpha_composite(avatar, (center_x - avatar.width // 2, av_y))

            bar_y = av_y + avatar.height + 2
            _draw_ratio_bar(result, draw, center_x - bar_half, bar_y,
                            center_x + bar_half, bar_y + 18, cur, mx)

            name = player.get("name", "")
            if name:
                nw = draw.textlength(name, font=hp_font)
                draw.text((center_x - nw / 2, bar_y + 20), name, font=hp_font,
                          fill=(240, 240, 245, 255))

    # Léger renforcement de netteté (compense la vignette WebP de l'aperçu).
    final = result.convert("RGB").filter(
        ImageFilter.UnsharpMask(radius=2, percent=95, threshold=2)
    )
    final.save(output_path)
    print(f"Image créée : {output_path}")
