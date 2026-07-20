from PIL import Image, ImageDraw, ImageFont

from app.bot.rendering.element_visuals import make_element_badge, tint_by_element
from app.bot.rendering.image_utils import (
    add_hp_hue,
    add_outline,
    crop_to_circle,
    download_image,
    get_hp_color,
    load_background,
)
from app.shared.paths import MOBS_ASSETS_DIR


def _draw_ratio_bar(base, draw, x1, y1, x2, y2, current, maximum) -> None:
    """Barre de vie arrondie, MÊME règle pour mob et joueurs : la couleur de
    remplissage suit le % de PV (vert plein → rouge à bas PV via get_hp_color),
    vide à 0%. Track sombre + fin liseré."""
    r = (y2 - y1) // 2
    draw.rounded_rectangle([x1, y1, x2, y2], radius=r,
                           fill=(22, 18, 26, 235), outline=(255, 255, 255, 45), width=2)
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
    players_power_score: str = "XXXX",
):
    """
    players = [
        {
            "avatar_url": "https://...",
            "current_hp": 100,
            "max_hp": 100,
            "name": "Jean-Yves",  # optionnel
        },
        ...
    ]

    mob = {
        "name": "Slime",
        "image_name": "slime.png",
        "current_hp": 30,
        "max_hp": 30,
        "attack": 6,
        "defense": 1,
        "power_score": "1K",  # optionnel
    }
    """
    background = load_background(background_path, size=(1024, 1536))
    result = background.copy()
    bg_width, bg_height = result.size

    draw = ImageDraw.Draw(result)

    try:
        title_font = ImageFont.truetype("DejaVuSans-Bold.ttf", 48)
        stat_font = ImageFont.truetype("DejaVuSans-Bold.ttf", 34)
        hp_font = ImageFont.truetype("DejaVuSans-Bold.ttf", 26)
    except Exception:
        title_font = ImageFont.load_default()
        stat_font = ImageFont.load_default()
        hp_font = ImageFont.load_default()

    if mob is not None:
        mob_name = mob.get("name", "Monstre")
        mob_current_hp = mob.get("current_hp", 0)
        mob_max_hp = mob.get("max_hp", 0)
        mob_image_name = mob.get("image_name")

        mob_avatar_size = 500
        mob_x = (bg_width - mob_avatar_size) // 2 + 40
        mob_y = 550

        try:
            if mob_image_name:
                mob_image_full_path = MOBS_ASSETS_DIR / mob_image_name
                raw_mob_image = Image.open(mob_image_full_path).convert("RGBA")
            else:
                raw_mob_image = Image.new(
                    "RGBA",
                    (mob_avatar_size, mob_avatar_size),
                    (120, 120, 120, 255),
                )
        except Exception as e:
            print(f"Erreur chargement image mob pour {mob_name} : {e}")
            raw_mob_image = Image.new(
                "RGBA",
                (mob_avatar_size, mob_avatar_size),
                (120, 120, 120, 255),
            )

        mob_img = raw_mob_image.resize((mob_avatar_size, mob_avatar_size))
        # Décline le monstre selon son élément (teinte générée). Neutre/""
        # → image inchangée.
        mob_element = mob.get("element") or ""
        if mob_element:
            mob_img = tint_by_element(mob_img, mob_element)
        result.alpha_composite(mob_img, (mob_x, mob_y))

        # ----- BANDEAU MOB (emplacement haut du cadre, position fixe) -----
        slot_left, slot_right = 70, 955

        # Badge d'élément à gauche (place fixe). Neutre → pas de badge.
        name_x = slot_left + 30
        if mob_element:
            badge = make_element_badge(mob_element, diameter=96)
            if badge is not None:
                result.alpha_composite(badge, (slot_left, 116))
                name_x = slot_left + 96 + 22

        # Nom + power score (power aligné à droite du bandeau)
        draw.text((name_x, 118), mob_name, font=title_font, fill=(255, 255, 255, 255))
        mob_power = mob.get("power_score", "")
        if mob_power:
            ptxt = f"[ {mob_power} ]"
            pw = draw.textlength(ptxt, font=stat_font)
            draw.text((slot_right - pw, 128), ptxt, font=stat_font, fill=(235, 226, 236, 255))

        # Barre de vie du mob : MÊME règle que les joueurs (vert→rouge selon %),
        # vide à 0%.
        bar_y1, bar_y2 = 170, 210
        _draw_ratio_bar(result, draw, name_x, bar_y1, slot_right, bar_y2,
                        mob_current_hp, mob_max_hp)
        hp_txt = f"{mob_current_hp} / {mob_max_hp}" if mob_current_hp > 0 else "Vaincu"
        htw = draw.textlength(hp_txt, font=hp_font)
        draw.text(((name_x + slot_right) / 2 - htw / 2, bar_y1 + 6),
                  hp_txt, font=hp_font, fill=(255, 255, 255, 255))

    if not players:
        result.save(output_path)
        print(f"Aucun player. Image sauvegardée : {output_path}")
        return

    # ----- BANDEAU JOUEURS (emplacement bas du cadre, position fixe) -----
    count = len(players)
    av_d = 104
    slot_x1, slot_x2 = 70, 955
    step = (slot_x2 - slot_x1) / max(1, count)
    av_y = 1322

    for i, player in enumerate(players):
        center_x = int(slot_x1 + step * (i + 0.5))
        try:
            raw_avatar = download_image(player["avatar_url"])
        except Exception:
            raw_avatar = Image.new("RGBA", (av_d, av_d), (120, 120, 120, 255))

        cur = int(player.get("current_hp", 0) or 0)
        mx = int(player.get("max_hp", 1) or 1)
        hue = add_hp_hue(raw_avatar, current_hp=cur, max_hp=mx, alpha=0.36)
        avatar = add_outline(crop_to_circle(hue, av_d), outline_size=3)
        result.alpha_composite(avatar, (center_x - avatar.width // 2, av_y))

        # Mini barre de vie (même règle vert→rouge que le mob).
        bar_y = av_y + avatar.height + 2
        _draw_ratio_bar(result, draw, center_x - 52, bar_y, center_x + 52, bar_y + 18, cur, mx)

        name = player.get("name", "")
        if name:
            nw = draw.textlength(name, font=hp_font)
            draw.text((center_x - nw / 2, bar_y + 20), name, font=hp_font,
                      fill=(240, 240, 245, 255))

    result.save(output_path)
    print(f"Image créée : {output_path}")