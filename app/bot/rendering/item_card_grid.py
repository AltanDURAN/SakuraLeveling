"""Rendu Pillow générique d'une grille de cards d'items.

Utilisé par `/craft_list`, `/forge_list` (recettes) et `/equipement_list`
(items possédés). Style cohérent avec `/equipement` : gradient sakura,
cards arrondies semi-transparentes, emojis couleur via NotoColorEmoji.

Une `CardSpec` décrit ce qu'on affiche dans une card ; le caller construit
la liste pour son contexte (recipe ou inventory item) puis appelle
`compose_card_grid_page(...)`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw

from app.bot.rendering.emoji_text import (
    draw_text_with_emojis,
    measure_text_with_emojis,
)
from app.bot.rendering.pillow_utils import (
    draw_sakura_petals,
    draw_text_with_shadow,
    gradient_background,
    try_font,
)
from app.shared.paths import ITEMS_ASSETS_DIR


WIDTH = 1024


# Palette alignée sur equipment_image.py / profile_banner.py
_BG_TOP = (12, 14, 28, 255)
_BG_BOTTOM = (38, 42, 78, 255)
_PANEL_BG = (0, 0, 0, 160)
_PANEL_BORDER = (255, 255, 255, 50)
_TEXT_PRIMARY = (255, 255, 255, 245)
_TEXT_SECONDARY = (210, 225, 245, 255)
_TEXT_MUTED = (175, 190, 215, 255)
_GOLD = (255, 220, 110, 255)
_GREEN = (140, 220, 130, 255)
_SHADOW = (0, 0, 0, 220)
_PINK_PETAL = (255, 175, 200, 65)


@dataclass
class CardSpec:
    """Spécification d'une card affichée dans la grille.

    `icon_emoji` est le glyphe à dessiner si `icon_path` est None ou absent.
    `accent` colore la barre verticale gauche de la card (signal visuel).
    `right_text` est dessiné right-aligné sur la même ligne que le nom
    (en or, gros) — typiquement les bonus de stat ("+5 ⚔️ · +3 🛡️").
    `lines` est la liste de petits textes affichés sous le nom (chacun
    peut contenir des emojis couleur — ex: ingrédients de craft).
    `badge` est un petit texte en haut à droite extrême (ex: "✅").
    """

    name: str
    icon_emoji: str = "•"
    icon_path: Path | None = None
    accent: tuple[int, int, int, int] | None = None
    right_text: str | None = None
    lines: list[str] = field(default_factory=list)
    badge: str | None = None
    code: str | None = None


def _draw_panel(
    base: Image.Image,
    origin: tuple[int, int],
    size: tuple[int, int],
    *,
    radius: int = 16,
    accent: tuple[int, int, int, int] | None = None,
) -> None:
    """Card arrondie semi-transparente. Style `/equipement`."""
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.rounded_rectangle(
        [(0, 0), (size[0] - 1, size[1] - 1)],
        radius=radius, fill=_PANEL_BG, outline=_PANEL_BORDER, width=1,
    )
    od.rounded_rectangle(
        [(0, 0), (size[0] - 1, size[1] // 2)],
        radius=radius, fill=(255, 255, 255, 14),
    )
    if accent is not None:
        od.rounded_rectangle(
            [(0, 8), (5, size[1] - 9)],
            radius=2, fill=accent,
        )
    base.alpha_composite(overlay, origin)


def _draw_card(
    base: Image.Image,
    origin: tuple[int, int],
    size: tuple[int, int],
    card: CardSpec,
    *,
    icon_size: int,
) -> None:
    x, y = origin
    w, h = size
    _draw_panel(base, origin, size, accent=card.accent)

    # Icône à gauche : asset PNG si dispo, sinon gros emoji centré dans
    # un carré semi-transparent.
    icon_origin = (x + 14, y + (h - icon_size) // 2)
    icon_drawn = False
    if card.icon_path and card.icon_path.exists():
        try:
            icon_img = Image.open(card.icon_path).convert("RGBA").resize(
                (icon_size, icon_size), Image.LANCZOS,
            )
            base.alpha_composite(icon_img, icon_origin)
            icon_drawn = True
        except Exception:
            icon_drawn = False
    if not icon_drawn:
        # Carré arrondi rempli + emoji centré
        ph = Image.new("RGBA", (icon_size, icon_size), (0, 0, 0, 0))
        pd = ImageDraw.Draw(ph)
        pd.rounded_rectangle(
            [(0, 0), (icon_size - 1, icon_size - 1)],
            radius=14, fill=(40, 50, 80, 200),
            outline=(255, 255, 255, 40), width=1,
        )
        emoji_size = int(icon_size * 0.65)
        draw_text_with_emojis(
            ph,
            ((icon_size - emoji_size) // 2, (icon_size - emoji_size) // 2 - 4),
            card.icon_emoji, try_font(emoji_size),
            fill=(255, 255, 255, 220), shadow=(0, 0, 0, 0),
            emoji_size=emoji_size,
        )
        base.alpha_composite(ph, icon_origin)

    # Texte à droite de l'icône
    text_x = x + 14 + icon_size + 18

    # Badge éventuel (✅) en extrême droite, sa largeur est réservée pour
    # éviter que right_text marche dessus.
    badge_w = 0
    if card.badge:
        bf = try_font(22, bold=True)
        badge_w = measure_text_with_emojis(card.badge, bf, bf.size)
        draw_text_with_emojis(
            base, (x + w - badge_w - 16, y + (h - bf.size) // 2 - 2),
            card.badge, bf, fill=_GOLD, shadow=_SHADOW,
        )

    # Stats (right_text) à droite, même ligne que le nom — en or, gros.
    right_w = 0
    if card.right_text:
        rf = try_font(22, bold=True)
        right_w = measure_text_with_emojis(card.right_text, rf, rf.size)
        right_x = x + w - right_w - 16 - (badge_w + 16 if badge_w else 0)
        draw_text_with_emojis(
            base, (right_x, y + 14), card.right_text, rf,
            fill=_GOLD, shadow=None,
        )

    # Nom à gauche (tronqué si déborde)
    name_font = try_font(24, bold=True)
    available_w = w - (icon_size + 14 + 18 + 16) - right_w - (
        badge_w + 16 if badge_w else 0
    ) - 12
    name = card.name
    # Tronque approximativement par mesure plutôt que par char count fixe
    while name and name_font.getlength(name) > available_w:
        name = name[:-1]
    if name != card.name:
        name = name[:-1] + "…"
    draw_text_with_emojis(
        base, (text_x, y + 14), name, name_font,
        fill=_TEXT_PRIMARY, shadow=_SHADOW,
    )

    # Ligne secondaire (1 max en mode slim) — typiquement ingrédients craft.
    if card.lines:
        line = card.lines[0]
        line_font = try_font(18)
        if line_font.getlength(line) > w - icon_size - 60:
            # Tronque grossièrement
            while line and line_font.getlength(line) > w - icon_size - 60:
                line = line[:-1]
            line = line[:-1] + "…"
        draw_text_with_emojis(
            base, (text_x, y + 14 + 32), line, line_font,
            fill=_TEXT_SECONDARY, shadow=None,
        )


def compose_card_grid_page(
    output_path: str,
    title: str,
    subtitle: str,
    cards: list[CardSpec],
    *,
    cols: int = 1,
    rows: int = 6,
    seed: int = 0,
) -> None:
    """Rend une page (max cols × rows cards). Si plus, le caller paginera.

    `title`/`subtitle` : bandeau en haut. `seed` : layout pétales déterministe.
    """
    margin = 30
    spacing = 8
    header_h = 110
    footer_h = 40
    icon_size = 60

    # Card slim avec stats à droite du nom : on tient une ligne nom+stats
    # + une ligne secondaire optionnelle (ingrédients) en 70 px.
    card_h = 70
    rows_used = min(rows, max(1, (len(cards) + cols - 1) // cols))
    height = (
        header_h + rows_used * (card_h + spacing) - spacing + footer_h + 30
    )
    height = max(height, 540)

    bg = gradient_background(WIDTH, height, _BG_TOP, _BG_BOTTOM)
    draw_sakura_petals(
        bg, seed=seed, count=18,
        palette=[(_PINK_PETAL[0], _PINK_PETAL[1], _PINK_PETAL[2], _PINK_PETAL[3])],
        size_range=(34, 60),
    )

    # ---- Header ----
    title_font = try_font(34, bold=True)
    sub_font = try_font(20, bold=True)
    draw_text_with_emojis(
        bg, (margin, 24), title, title_font,
        fill=_TEXT_PRIMARY, shadow=_SHADOW,
    )
    draw_text_with_emojis(
        bg, (margin, 70), subtitle, sub_font,
        fill=_TEXT_SECONDARY, shadow=_SHADOW,
    )
    draw = ImageDraw.Draw(bg)
    draw.line(
        [(margin, header_h - 6), (WIDTH - margin, header_h - 6)],
        fill=(255, 255, 255, 50), width=2,
    )

    # ---- Grid ----
    card_w = (WIDTH - 2 * margin - (cols - 1) * spacing) // cols
    for idx, card in enumerate(cards[: cols * rows]):
        row, col = divmod(idx, cols)
        x = margin + col * (card_w + spacing)
        y = header_h + row * (card_h + spacing)
        _draw_card(bg, (x, y), (card_w, card_h), card, icon_size=icon_size)

    # ---- Footer ----
    footer_text = f"{len(cards)} item(s) sur cette page"
    ff = try_font(15)
    fw = draw.textlength(footer_text, font=ff)
    draw_text_with_shadow(
        draw, ((WIDTH - fw) // 2, height - 28),
        footer_text, ff, fill=_TEXT_MUTED, shadow=_SHADOW,
    )

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    bg.convert("RGB").save(output_path, "PNG", optimize=True)


def item_asset_path(item_code: str) -> Path | None:
    """Renvoie le chemin de l'asset PNG d'un item s'il existe sur disque."""
    candidate = ITEMS_ASSETS_DIR / f"{item_code}.png"
    if candidate.exists():
        return candidate
    candidate = ITEMS_ASSETS_DIR / f"{item_code}.jpg"
    if candidate.exists():
        return candidate
    return None
