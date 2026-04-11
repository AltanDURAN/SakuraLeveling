from io import BytesIO
from pathlib import Path
import requests

from PIL import Image, ImageDraw, ImageFont, ImageFilter


def download_image(url: str) -> Image.Image:
    response = requests.get(url, timeout=15)
    response.raise_for_status()
    return Image.open(BytesIO(response.content)).convert("RGBA")


def load_background(background_path: str | None, size=(1024, 1536)) -> Image.Image:
    """
    Charge un fond si fourni, sinon crée un fond de test joli.
    """
    if background_path and Path(background_path).exists():
        return Image.open(background_path).convert("RGBA")

    # Fond de test
    bg = Image.new("RGBA", size, (30, 35, 55, 255))
    draw = ImageDraw.Draw(bg)

    # Dégradé simple vertical fond
    for y in range(size[1]):
        ratio = y / size[1]
        r = int(25 + ratio * 20)
        g = int(30 + ratio * 40)
        b = int(50 + ratio * 70)
        draw.line((0, y, size[0], y), fill=(r, g, b, 255))

    # Bandeau discret en bas
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_draw.rounded_rectangle(
        [(30, size[1] - 164), (size[0] - 30, size[1] - 30)],
        radius=35,
        fill=(0, 0, 0, 90)
    )
    bg = Image.alpha_composite(bg, overlay)

    return bg


def crop_to_circle(image: Image.Image, size: int) -> Image.Image:
    """
    Redimensionne et découpe l'image en cercle.
    """
    image = image.copy().convert("RGBA")

    # Crop carré centré
    min_side = min(image.width, image.height)
    left = (image.width - min_side) // 2
    top = (image.height - min_side) // 2
    image = image.crop((left, top, left + min_side, top + min_side))

    image = image.resize((size, size), Image.Resampling.LANCZOS)

    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, size, size), fill=255)

    circle = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    circle.paste(image, (0, 0), mask)
    return circle


def lerp_color(color1: tuple[int, int, int], color2: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    """
    Interpolation linéaire entre deux couleurs RGB.
    t = 0 -> color1
    t = 1 -> color2
    """
    t = max(0.0, min(1.0, t))
    return (
        int(color1[0] + (color2[0] - color1[0]) * t),
        int(color1[1] + (color2[1] - color1[1]) * t),
        int(color1[2] + (color2[2] - color1[2]) * t),
    )


def get_hp_color(current_hp: int, max_hp: int) -> tuple[int, int, int]:
    """
    Retourne une couleur selon le % de vie :
    - 100%   -> vert
    - 75%    -> jaune
    - 50%    -> orange
    - 25%    -> rouge
    - 1%     -> rouge foncé
    - 0%     -> noir

    Variation progressive entre les paliers.
    """
    if max_hp <= 0:
        return (0, 0, 0)

    hp_ratio = max(0.0, min(1.0, current_hp / max_hp))

    # Cas spécial : mort
    if hp_ratio <= 0:
        return (0, 0, 0)

    # Couleurs de référence
    black = (0, 0, 0)
    dark_red = (120, 0, 0)
    red = (220, 20, 20)
    orange = (240, 100, 0)
    yellow = (240, 200, 50)
    green = (0, 180, 50)

    # Interpolation par segments
    if hp_ratio <= 0.25:
        # 0% -> noir | 25% -> rouge
        t = hp_ratio / 0.25
        return lerp_color(dark_red, red, t)

    elif hp_ratio <= 0.50:
        # 25% -> rouge | 50% -> orange
        t = (hp_ratio - 0.25) / 0.25
        return lerp_color(red, orange, t)

    elif hp_ratio <= 0.75:
        # 50% -> orange | 75% -> jaune
        t = (hp_ratio - 0.50) / 0.25
        return lerp_color(orange, yellow, t)

    else:
        # 75% -> jaune | 100% -> vert
        t = (hp_ratio - 0.75) / 0.25
        return lerp_color(yellow, green, t)


def add_hue(image: Image.Image, color=(255, 0, 0), alpha=0.4) -> Image.Image:
    """
    Ajoute une surcouche de couleur sur une image.
    """
    image = image.convert("RGBA")
    alpha = max(0.0, min(1.0, alpha))

    overlay = Image.new(
        "RGBA",
        image.size,
        (color[0], color[1], color[2], int(255 * alpha))
    )

    return Image.alpha_composite(image, overlay)


def add_hp_hue(image: Image.Image, current_hp: int, max_hp: int, alpha: float = 0.30) -> Image.Image:
    """
    Applique automatiquement une teinte selon les HP du joueur.
    """
    hp_color = get_hp_color(current_hp, max_hp)
    print(hp_color)
    if hp_color == (0, 0, 0) :
        alpha = 0.80
    return add_hue(image, color=hp_color, alpha=alpha)


def add_outline(circle_img: Image.Image, outline_size: int = 6, outline_color=(255, 255, 255, 255)) -> Image.Image:
    """
    Ajoute un contour autour de l'avatar circulaire.
    """
    size = circle_img.width
    final_size = size + outline_size * 2

    result = Image.new("RGBA", (final_size, final_size), (0, 0, 0, 0))
    mask = Image.new("L", (final_size, final_size), 0)
    draw = ImageDraw.Draw(mask)

    # Cercle externe = contour
    draw.ellipse((0, 0, final_size - 1, final_size - 1), fill=255)

    outline_layer = Image.new("RGBA", (final_size, final_size), outline_color)
    result.paste(outline_layer, (0, 0), mask)

    # Colle l'avatar au centre
    result.paste(circle_img, (outline_size, outline_size), circle_img)
    return result


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
        "image_url": "https://...",
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
        name_font = ImageFont.truetype("DejaVuSans-Bold.ttf", 20)
    except Exception:
        title_font = ImageFont.load_default()
        stat_font = ImageFont.load_default()
        name_font = ImageFont.load_default()

    # =========================
    # Affichage du mob
    # =========================
    if mob is not None:
        mob_name = mob.get("name", "Monstre")
        mob_current_hp = mob.get("current_hp", 0)
        mob_max_hp = mob.get("max_hp", 0)
        mob_attack = mob.get("attack", 0)
        mob_defense = mob.get("defense", 0)
        mob_image_url = mob.get("image_url")

        # Zone du mob
        mob_avatar_size = 220
        mob_x = (bg_width - mob_avatar_size) // 2
        mob_y = 600

        try:
            raw_mob_image = download_image(mob_image_url) if mob_image_url else Image.new(
                "RGBA", (mob_avatar_size, mob_avatar_size), (120, 120, 120, 255)
            )
        except Exception as e:
            print(f"Erreur téléchargement image mob pour {mob_name} : {e}")
            raw_mob_image = Image.new(
                "RGBA", (mob_avatar_size, mob_avatar_size), (120, 120, 120, 255)
            )

        # Mise en forme image du mob
        mob_img = raw_mob_image.convert("RGBA").resize((mob_avatar_size, mob_avatar_size))
        result.alpha_composite(mob_img, (mob_x, mob_y))

        # Position du rectangle
        x1 = 92
        y1 = 125
        x2 = x1 + 825
        y2 = y1 + 90
        
        #Calculer x2 en fonction des HP current

        draw.rounded_rectangle(
            [(x1, y1), (x2, y2)],
            radius=20,                 # arrondi des coins
            fill=(0, 200, 0, 255)      # vert (RGBA)
        )

        # Nom du mob
        mob_test = f"{mob_name} - [203k]"
        draw.text((130, 152), mob_test, font=title_font, fill=(255, 255, 255, 255))

    # =========================
    # Affichage des joueurs
    # =========================
    if not players:
        result.save(output_path)
        print(f"Aucun player. Image sauvegardée : {output_path}")
        return

    count = len(players)

    avatar_size = 100
    outline_size = 3
    bottom_margin = 63

    usable_width = bg_width - 80
    print(len(players))
    if len(players) > 4 :
        usable_width = usable_width - 120
        
    centers_x = [int((i + 1) * usable_width / (count + 1)) for i in range(count)]

    avatar_y = bg_height - bottom_margin - avatar_size

    for player, center_x in zip(players, centers_x):
        try:
            raw_avatar = download_image(player["avatar_url"])
        except Exception as e:
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
    
    draw.text((850, 1400), "[100M]", font=stat_font, fill=(255, 255, 255, 255))

    result.save(output_path)
    print(f"Image créée : {output_path}")

if __name__ == "__main__":
    players = [
        {
            "avatar_url": "https://cdn.discordapp.com/avatars/770707625033203793/2aa967457d2dd49a389c2daf9bf77370.webp?size=1024",
            "current_hp": 100,
            "max_hp": 100,
            "name": "Jean-Yves",
        },
        {
            "avatar_url": "https://cdn.discordapp.com/avatars/770707625033203793/2aa967457d2dd49a389c2daf9bf77370.webp?size=1024",
            "current_hp": 90,
            "max_hp": 100,
            "name": "Jean-Yves",
        },
        {
            "avatar_url": "https://cdn.discordapp.com/avatars/770707625033203793/2aa967457d2dd49a389c2daf9bf77370.webp?size=1024",
            "current_hp": 80,
            "max_hp": 100,
            "name": "Jean-Yves",
        },
        {
            "avatar_url": "https://cdn.discordapp.com/avatars/770707625033203793/2aa967457d2dd49a389c2daf9bf77370.webp?size=1024",
            "current_hp": 70,
            "max_hp": 100,
            "name": "Jean-Yves",
        },
        {
            "avatar_url": "https://cdn.discordapp.com/avatars/770707625033203793/2aa967457d2dd49a389c2daf9bf77370.webp?size=1024",
            "current_hp": 60,
            "max_hp": 100,
            "name": "Jean-Yves",
        },
        {
            "avatar_url": "https://cdn.discordapp.com/avatars/770707625033203793/2aa967457d2dd49a389c2daf9bf77370.webp?size=1024",
            "current_hp": 50,
            "max_hp": 100,
            "name": "Jean-Yves",
        },
        {
            "avatar_url": "https://cdn.discordapp.com/avatars/770707625033203793/2aa967457d2dd49a389c2daf9bf77370.webp?size=1024",
            "current_hp": 40,
            "max_hp": 100,
            "name": "Jean-Yves",
        },
        {
            "avatar_url": "https://cdn.discordapp.com/avatars/770707625033203793/2aa967457d2dd49a389c2daf9bf77370.webp?size=1024",
            "current_hp": 30,
            "max_hp": 100,
            "name": "Jean-Yves",
        },
        {
            "avatar_url": "https://cdn.discordapp.com/avatars/770707625033203793/2aa967457d2dd49a389c2daf9bf77370.webp?size=1024",
            "current_hp": 20,
            "max_hp": 100,
            "name": "Jean-Yves",
        },
        {
            "avatar_url": "https://cdn.discordapp.com/avatars/770707625033203793/2aa967457d2dd49a389c2daf9bf77370.webp?size=1024",
            "current_hp": 10,
            "max_hp": 100,
            "name": "Jean-Yves",
        },
        {
            "avatar_url": "https://cdn.discordapp.com/avatars/770707625033203793/2aa967457d2dd49a389c2daf9bf77370.webp?size=1024",
            "current_hp": 0,
            "max_hp": 100,
            "name": "Jean-Yves",
        }
    ]
    
    mob = {
        "name": "Gobelin Combattant",
        "image_url": "https://i.imgur.com/tLYX58K.jpeg",
        "current_hp": 30,
        "max_hp": 30,
        "attack": 6,
        "defense": 1,
    }

    compose_players_banner(
        players=players,
        mob=mob,
        output_path="players_banner.png",
        background_path="/home/machine/Desktop/SakuraLeveling/tests/sandbox/clairiere_sinistre.png",  # mets un chemin ici si tu veux ton propre fond
    )