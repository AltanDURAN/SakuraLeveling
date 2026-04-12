from PIL import Image, ImageDraw, ImageFont

from app.bot.rendering.image_utils import (
    add_hp_hue,
    add_outline,
    crop_to_circle,
    download_image,
    load_background,
)
from app.shared.paths import MOBS_ASSETS_DIR


def compose_players_banner(
    players: list[dict],
    output_path: str = "result.png",
    background_path: str | None = None,
    mob: dict | None = None,
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
    }
    """
    background = load_background(background_path, size=(1024, 1536))
    result = background.copy()
    bg_width, bg_height = result.size

    draw = ImageDraw.Draw(result)

    try:
        title_font = ImageFont.truetype("DejaVuSans-Bold.ttf", 42)
        stat_font = ImageFont.truetype("DejaVuSans-Bold.ttf", 36)
    except Exception:
        title_font = ImageFont.load_default()
        stat_font = ImageFont.load_default()

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
        result.alpha_composite(mob_img, (mob_x, mob_y))

        x1 = 92
        y1 = 126
        y2 = y1 + 90

        hp_ratio = 0.0
        if mob_max_hp > 0:
            hp_ratio = max(0.0, min(1.0, mob_current_hp / mob_max_hp))

        x2 = x1 + int(825 * hp_ratio)

        mob_power = "XXX"
        mob_info = f"{mob_name} • [{mob_power}]"

        if mob_current_hp > 0 and x2 > x1:
            draw.rounded_rectangle(
                [(x1, y1), (x2, y2)],
                radius=20,
                fill=(0, 200, 0, 255),
            )
        else:
            mob_info = f"{mob_name} • [Mort]"

        draw.text((130, 152), mob_info, font=title_font, fill=(255, 255, 255, 255))

    if not players:
        result.save(output_path)
        print(f"Aucun player. Image sauvegardée : {output_path}")
        return

    count = len(players)
    avatar_size = 100
    outline_size = 3
    bottom_margin = 63

    usable_width = bg_width - 80
    if len(players) > 4:
        usable_width -= 120

    centers_x = [int((i + 1) * usable_width / (count + 1)) for i in range(count)]
    avatar_y = bg_height - bottom_margin - avatar_size

    for player, center_x in zip(players, centers_x):
        try:
            raw_avatar = download_image(player["avatar_url"])
        except Exception:
            raw_avatar = Image.new("RGBA", (avatar_size, avatar_size), (120, 120, 120, 255))

        hue = add_hp_hue(
            raw_avatar,
            current_hp=player["current_hp"],
            max_hp=player["max_hp"],
            alpha=0.36,
        )

        circle = crop_to_circle(hue, avatar_size)
        avatar = add_outline(circle, outline_size=outline_size)

        aw, ah = avatar.size
        avatar_x = center_x - aw // 2 + 31
        result.alpha_composite(avatar, (avatar_x, avatar_y))

    players_power = "[XXX]"
    draw.text((850, 1400), players_power, font=stat_font, fill=(255, 255, 255, 255))

    result.save(output_path)
    print(f"Image créée : {output_path}")