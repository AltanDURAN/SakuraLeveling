"""Rendu Pillow du /shop : une grille de CARTES d'objets (même style visuel
que les cards de /equipement). Une page par catégorie (onglets côté view).

Chaque carte : image de l'objet (assets/items/<code>.png) ou placeholder,
nom, rareté colorée, prix d'achat. Achat uniquement (pas de vente).

Rend en PNG bytes (pas de fichier disque → pas de race entre joueurs).
"""

from __future__ import annotations

import io
import math

from PIL import Image, ImageDraw

from app.bot.rendering.emoji_text import draw_text_with_emojis
from app.bot.rendering.equipment_image import _load_item_image
from app.bot.rendering.pillow_utils import (
    draw_sakura_petals,
    draw_text_with_shadow,
    gradient_background,
    try_font,
)
from app.domain.entities.shop_item import ShopItem
from app.shared.enums import CATEGORY_ICONS


WIDTH = 1024
MARGIN = 28
SPACING = 22
COLS = 3
HEADER_H = 110

# Thème boutique : plum/or sombre (cohérent avec l'or du shop).
_BG_TOP = (30, 20, 38, 255)
_BG_BOTTOM = (48, 30, 56, 255)
_PANEL_BG = (0, 0, 0, 160)
_PANEL_BORDER = (255, 255, 255, 45)
_TEXT = (255, 255, 255, 245)
_MUTED = (205, 200, 220, 255)
_GOLD = (255, 216, 110, 255)
_SHADOW = (0, 0, 0, 220)
_PETAL = (255, 180, 205, 60)

_RARITY_COLOR = {
    "common": (180, 190, 205, 255),
    "uncommon": (110, 205, 140, 255),
    "rare": (90, 160, 230, 255),
    "epic": (185, 120, 225, 255),
    "legendary": (240, 170, 70, 255),
}
_RARITY_LABEL = {
    "common": "Commun",
    "uncommon": "Peu commun",
    "rare": "Rare",
    "epic": "Épique",
    "legendary": "Légendaire",
}


def _fit(draw, text: str, font, max_w: int) -> str:
    """Tronque `text` avec … pour tenir dans max_w."""
    if draw.textlength(text, font=font) <= max_w:
        return text
    while text and draw.textlength(text + "…", font=font) > max_w:
        text = text[:-1]
    return text + "…"


def _draw_card(
    base: Image.Image,
    origin: tuple[int, int],
    size: tuple[int, int],
    shop_item: ShopItem,
) -> None:
    cw, ch = size
    item = shop_item.item_definition
    rarity = item.rarity or "common"
    accent = _RARITY_COLOR.get(rarity, _RARITY_COLOR["common"])

    # Panneau arrondi + barre d'accent rareté
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.rounded_rectangle([(0, 0), (cw - 1, ch - 1)], radius=18,
                         fill=_PANEL_BG, outline=_PANEL_BORDER, width=1)
    od.rounded_rectangle([(0, 0), (cw - 1, ch // 2)], radius=18, fill=(255, 255, 255, 12))
    od.rounded_rectangle([(0, 10), (5, ch - 11)], radius=2, fill=accent)
    base.alpha_composite(overlay, origin)

    ox, oy = origin
    # Image de l'objet (ou placeholder catégorie)
    img_size = min(cw - 70, ch - 150)
    img = _load_item_image(item.code, size=img_size)
    img_x = ox + (cw - img_size) // 2
    img_y = oy + 22
    if img is not None:
        base.alpha_composite(img, (img_x, img_y))
    else:
        ph = Image.new("RGBA", (img_size, img_size), (0, 0, 0, 0))
        pd = ImageDraw.Draw(ph)
        pd.rounded_rectangle([(0, 0), (img_size - 1, img_size - 1)], radius=16,
                             fill=(20, 16, 32, 200), outline=(255, 255, 255, 30), width=2)
        emoji = CATEGORY_ICONS.get(item.category, "📦")
        es = int(img_size * 0.5)
        draw_text_with_emojis(
            ph, ((img_size - es) // 2, (img_size - es) // 2 - 4),
            emoji, try_font(es), fill=(255, 255, 255, 205),
            shadow=(0, 0, 0, 0), emoji_size=es,
        )
        base.alpha_composite(ph, (img_x, img_y))

    d = ImageDraw.Draw(base)
    text_y = img_y + img_size + 12
    cx = ox + cw // 2

    # Nom (centré, tronqué)
    name_font = try_font(26, bold=True)
    name = _fit(d, item.name, name_font, cw - 28)
    nw = d.textlength(name, font=name_font)
    draw_text_with_shadow(d, (cx - nw / 2, text_y), name, name_font, _TEXT, _SHADOW)

    # Rareté (centrée, couleur rareté)
    rar_font = try_font(17, bold=True)
    rar = _RARITY_LABEL.get(rarity, rarity)
    rw = d.textlength(rar, font=rar_font)
    d.text((cx - rw / 2, text_y + 32), rar, font=rar_font, fill=accent)

    # Prix (centré, or)
    price_font = try_font(24, bold=True)
    price = f"{shop_item.buy_price:,}".replace(",", " ") + " or"
    pw = d.textlength(price, font=price_font)
    draw_text_with_shadow(d, (cx - pw / 2, text_y + 58), price, price_font, _GOLD, _SHADOW)


def compose_shop_page(
    category_label: str,
    category_emoji: str,
    shop_items: list[ShopItem],
    seed: int = 0,
) -> bytes:
    """Rend une page boutique (une catégorie) en PNG bytes."""
    items = sorted(shop_items, key=lambda s: s.buy_price)
    n = len(items)
    rows = max(1, math.ceil(n / COLS)) if n else 1

    card_w = (WIDTH - 2 * MARGIN - (COLS - 1) * SPACING) // COLS
    card_h = 330
    height = HEADER_H + rows * (card_h + SPACING) + MARGIN
    height = max(height, HEADER_H + card_h + MARGIN)

    base = gradient_background(WIDTH, height, _BG_TOP, _BG_BOTTOM)
    draw_sakura_petals(base, seed=seed or 7, count=18, palette=[_PETAL], size_range=(34, 64))
    d = ImageDraw.Draw(base)

    # En-tête
    title_font = try_font(38, bold=True)
    draw_text_with_emojis(
        base, (MARGIN, 28), f"🏪 Boutique", title_font,
        fill=_TEXT, shadow=_SHADOW, emoji_size=38,
    )
    sub_font = try_font(24, bold=True)
    draw_text_with_emojis(
        base, (MARGIN, 72), f"{category_emoji} {category_label}", sub_font,
        fill=_GOLD, shadow=_SHADOW, emoji_size=24,
    )
    d.line([(MARGIN, HEADER_H - 6), (WIDTH - MARGIN, HEADER_H - 6)], fill=(255, 255, 255, 40), width=2)

    if not items:
        msg = "Aucun article dans cette catégorie."
        f = try_font(26)
        mw = d.textlength(msg, font=f)
        d.text(((WIDTH - mw) / 2, HEADER_H + 80), msg, font=f, fill=_MUTED)
    else:
        for i, shop_item in enumerate(items):
            row, col = divmod(i, COLS)
            x = MARGIN + col * (card_w + SPACING)
            y = HEADER_H + row * (card_h + SPACING)
            _draw_card(base, (x, y), (card_w, card_h), shop_item)

    # Pied : rappel d'achat
    foot = "Achetez avec  /buy <objet> <quantité>"
    ff = try_font(20)
    fw = d.textlength(foot, font=ff)
    d.text(((WIDTH - fw) / 2, height - 30), foot, font=ff, fill=_MUTED)

    buf = io.BytesIO()
    base.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()
