"""Scène de combat rendue en image (fond + monstre + HUD joueurs).

Gabarit **3:2 paysage (1536×1024)** : s'affiche grand sur PC (Discord plafonne
la hauteur des images inline) tout en restant confortable sur mobile.

Le HUD est **auto-portant** : bandeaux dessinés par code (haut = mob, bas =
joueurs), indépendants du décor. Le fond de zone est recadré (cover) pour
remplir le paysage sans distorsion. Quand des fonds paysage « propres » (sans
cadre) seront fournis, le rendu sera parfait sans rien changer d'autre.
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

# Gabarit paysage 3:2.
SCENE_W, SCENE_H = 1536, 1024

# Bandeaux HUD (positions FIXES, quelle que soit la zone).
_TOP_PANEL = (28, 22, SCENE_W - 28, 170)
_BOTTOM_PANEL = (28, 846, SCENE_W - 28, 1010)
_MOB_SIZE = 520
_MOB_POS = ((SCENE_W - _MOB_SIZE) // 2, 250)
_PANEL_FILL = (12, 10, 16, 165)
_PANEL_BORDER = (255, 255, 255, 32)


def _cover_fit(image: Image.Image, w: int, h: int) -> Image.Image:
    """Redimensionne l'image pour COUVRIR (w, h) en gardant le ratio, puis
    recadre au centre. Pas de distorsion (contrairement à un étirement)."""
    image = image.convert("RGBA")
    if image.size == (w, h):
        return image
    scale = max(w / image.width, h / image.height)
    nw, nh = max(w, int(image.width * scale)), max(h, int(image.height * scale))
    resized = image.resize((nw, nh), Image.LANCZOS)
    left = (nw - w) // 2
    top = (nh - h) // 2
    return resized.crop((left, top, left + w, top + h))


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
    """Barre de vie arrondie, MÊME règle pour mob et joueurs : la couleur de
    remplissage suit le % de PV (vert plein → rouge à bas PV via get_hp_color),
    vide à 0%. Track sombre + fin liseré."""
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


def compose_players_banner(
    players: list[dict],
    output_path: str = "result.png",
    background_path: str | None = None,
    mob: dict | None = None,
    players_power_score: str = "",
):
    """players = [{avatar_url, current_hp, max_hp, name}], mob = {name,
    image_name, current_hp, max_hp, element, power_score}."""
    raw_bg = load_background(background_path, size=(SCENE_W, SCENE_H))
    result = _cover_fit(raw_bg, SCENE_W, SCENE_H)
    draw = ImageDraw.Draw(result)

    try:
        title_font = ImageFont.truetype("DejaVuSans-Bold.ttf", 54)
        stat_font = ImageFont.truetype("DejaVuSans-Bold.ttf", 36)
        hp_font = ImageFont.truetype("DejaVuSans-Bold.ttf", 28)
    except Exception:
        title_font = ImageFont.load_default()
        stat_font = ImageFont.load_default()
        hp_font = ImageFont.load_default()

    # Bandeaux HUD (auto-portants).
    _panel(result, _TOP_PANEL, radius=26)
    _panel(result, _BOTTOM_PANEL, radius=26)

    if mob is not None:
        mob_name = mob.get("name", "Monstre")
        mob_current_hp = int(mob.get("current_hp", 0) or 0)
        mob_max_hp = int(mob.get("max_hp", 0) or 0)
        mob_image_name = mob.get("image_name")
        mob_element = mob.get("element") or ""

        # ----- Monstre (centré, teinté selon l'élément) -----
        try:
            if mob_image_name:
                raw_mob = Image.open(MOBS_ASSETS_DIR / mob_image_name).convert("RGBA")
            else:
                raw_mob = Image.new("RGBA", (_MOB_SIZE, _MOB_SIZE), (120, 120, 120, 255))
        except Exception as e:
            print(f"Erreur chargement image mob pour {mob_name} : {e}")
            raw_mob = Image.new("RGBA", (_MOB_SIZE, _MOB_SIZE), (120, 120, 120, 255))

        # LANCZOS : indispensable pour une réduction violente (ex 4000→520) —
        # bien plus net que le bicubique par défaut.
        mob_img = raw_mob.resize((_MOB_SIZE, _MOB_SIZE), Image.LANCZOS)
        if mob_element:
            mob_img = tint_by_element(mob_img, mob_element)
        result.alpha_composite(mob_img, _MOB_POS)

        # ----- Bandeau MOB (haut) : badge élément + nom + power + barre PV -----
        p_left, p_top, p_right, p_bottom = _TOP_PANEL
        name_x = p_left + 34
        if mob_element:
            badge = make_element_badge(mob_element, diameter=104)
            if badge is not None:
                result.alpha_composite(badge, (p_left + 22, p_top + 22))
                name_x = p_left + 22 + 104 + 24

        draw.text((name_x, p_top + 20), mob_name, font=title_font, fill=(255, 255, 255, 255))
        mob_power = mob.get("power_score", "")
        if mob_power:
            ptxt = f"[ {mob_power} ]"
            pw = draw.textlength(ptxt, font=stat_font)
            draw.text((p_right - 20 - pw, p_top + 30), ptxt, font=stat_font,
                      fill=(235, 226, 236, 255))

        bar_y1, bar_y2 = p_top + 92, p_top + 132
        _draw_ratio_bar(result, draw, name_x, bar_y1, p_right - 20, bar_y2,
                        mob_current_hp, mob_max_hp)
        hp_txt = f"{mob_current_hp} / {mob_max_hp}" if mob_current_hp > 0 else "Vaincu"
        htw = draw.textlength(hp_txt, font=hp_font)
        draw.text(((name_x + p_right - 20) / 2 - htw / 2, bar_y1 + 6),
                  hp_txt, font=hp_font, fill=(255, 255, 255, 255))

    # ----- Bandeau JOUEURS (bas) : avatars alignés + mini-barre PV + nom -----
    if players:
        count = len(players)
        av_d = 96
        slot_x1, slot_x2 = _BOTTOM_PANEL[0] + 32, _BOTTOM_PANEL[2] - 32
        step = (slot_x2 - slot_x1) / max(1, count)
        av_y = _BOTTOM_PANEL[1] + 8

        for i, player in enumerate(players):
            center_x = int(slot_x1 + step * (i + 0.5))
            try:
                raw_avatar = download_image(player["avatar_url"])
            except Exception:
                raw_avatar = Image.new("RGBA", (av_d, av_d), (120, 120, 120, 255))

            cur = int(player.get("current_hp", 0) or 0)
            mx = int(player.get("max_hp", 1) or 1)
            # Pas de teinte PV sur l'avatar : la mini-barre de vie sous l'avatar
            # porte déjà l'info de PV (évite le doublon).
            avatar = add_outline(crop_to_circle(raw_avatar, av_d), outline_size=3)
            result.alpha_composite(avatar, (center_x - avatar.width // 2, av_y))

            bar_y = av_y + avatar.height + 2
            _draw_ratio_bar(result, draw, center_x - 54, bar_y, center_x + 54, bar_y + 18, cur, mx)

            name = player.get("name", "")
            if name:
                nw = draw.textlength(name, font=hp_font)
                draw.text((center_x - nw / 2, bar_y + 20), name, font=hp_font,
                          fill=(240, 240, 245, 255))

    # Léger renforcement de netteté : compense le ramollissement de la
    # vignette WebP que Discord génère pour l'aperçu inline. Dosé faible pour
    # ne pas créer d'artefacts sur la vue plein écran.
    final = result.convert("RGB").filter(
        ImageFilter.UnsharpMask(radius=2, percent=95, threshold=2)
    )
    final.save(output_path)
    print(f"Image créée : {output_path}")
