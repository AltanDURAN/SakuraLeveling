from io import BytesIO
from pathlib import Path

import requests
from PIL import Image, ImageDraw


def download_image(url: str) -> Image.Image:
    response = requests.get(url, timeout=15)
    response.raise_for_status()
    return Image.open(BytesIO(response.content)).convert("RGBA")


def load_background(background_path: str | None, size=(1024, 1536)) -> Image.Image:
    """
    Charge un fond si fourni, sinon crée un fond de test.
    """
    if background_path and Path(background_path).exists():
        return Image.open(background_path).convert("RGBA")

    bg = Image.new("RGBA", size, (30, 35, 55, 255))
    draw = ImageDraw.Draw(bg)

    for y in range(size[1]):
        ratio = y / size[1]
        r = int(25 + ratio * 20)
        g = int(30 + ratio * 40)
        b = int(50 + ratio * 70)
        draw.line((0, y, size[0], y), fill=(r, g, b, 255))

    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_draw.rounded_rectangle(
        [(30, size[1] - 164), (size[0] - 30, size[1] - 30)],
        radius=35,
        fill=(0, 0, 0, 90),
    )
    bg = Image.alpha_composite(bg, overlay)

    return bg


def crop_to_circle(image: Image.Image, size: int) -> Image.Image:
    image = image.copy().convert("RGBA")

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


def lerp_color(
    color1: tuple[int, int, int],
    color2: tuple[int, int, int],
    t: float,
) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    return (
        int(color1[0] + (color2[0] - color1[0]) * t),
        int(color1[1] + (color2[1] - color1[1]) * t),
        int(color1[2] + (color2[2] - color1[2]) * t),
    )


def get_hp_color(current_hp: int, max_hp: int) -> tuple[int, int, int]:
    if max_hp <= 0:
        return (0, 0, 0)

    hp_ratio = max(0.0, min(1.0, current_hp / max_hp))

    if hp_ratio <= 0:
        return (0, 0, 0)

    dark_red = (120, 0, 0)
    red = (220, 20, 20)
    orange = (240, 100, 0)
    yellow = (240, 200, 50)
    green = (0, 180, 50)

    if hp_ratio <= 0.25:
        t = hp_ratio / 0.25
        return lerp_color(dark_red, red, t)
    elif hp_ratio <= 0.50:
        t = (hp_ratio - 0.25) / 0.25
        return lerp_color(red, orange, t)
    elif hp_ratio <= 0.75:
        t = (hp_ratio - 0.50) / 0.25
        return lerp_color(orange, yellow, t)
    else:
        t = (hp_ratio - 0.75) / 0.25
        return lerp_color(yellow, green, t)


def add_hue(
    image: Image.Image,
    color=(255, 0, 0),
    alpha=0.4,
) -> Image.Image:
    image = image.convert("RGBA")
    alpha = max(0.0, min(1.0, alpha))

    overlay = Image.new(
        "RGBA",
        image.size,
        (color[0], color[1], color[2], int(255 * alpha)),
    )

    return Image.alpha_composite(image, overlay)


def add_hp_hue(
    image: Image.Image,
    current_hp: int,
    max_hp: int,
    alpha: float = 0.30,
) -> Image.Image:
    hp_color = get_hp_color(current_hp, max_hp)
    if hp_color == (0, 0, 0):
        alpha = 0.80
    return add_hue(image, color=hp_color, alpha=alpha)


def add_outline(
    circle_img: Image.Image,
    outline_size: int = 6,
    outline_color=(255, 255, 255, 255),
) -> Image.Image:
    size = circle_img.width
    final_size = size + outline_size * 2

    result = Image.new("RGBA", (final_size, final_size), (0, 0, 0, 0))
    mask = Image.new("L", (final_size, final_size), 0)
    draw = ImageDraw.Draw(mask)

    draw.ellipse((0, 0, final_size - 1, final_size - 1), fill=255)

    outline_layer = Image.new("RGBA", (final_size, final_size), outline_color)
    result.paste(outline_layer, (0, 0), mask)

    result.paste(circle_img, (outline_size, outline_size), circle_img)
    return result