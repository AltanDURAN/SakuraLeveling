"""Rendu Pillow de la commande /equipement.

Trois pages :
    - Page 1 : équipement principal (6 slots : casque, plastron, jambières,
      bottes, main droite, main gauche)
    - Page 2 : équipement secondaire (collier, bracelet, bague, ceinture,
      cape, boucle d'oreille)
    - Page 3 : résumé des stats accumulées + bonus de panoplies actifs

Chaque slot affiche une grosse vignette de l'item (depuis assets/items/<code>.png)
ou un placeholder stylisé si l'image n'existe pas. Le rendu reste lisible
même quand Discord compresse l'image en thumbnail (~360 px de large).
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from app.bot.rendering.emoji_text import (
    draw_text_with_emojis,
    measure_text_with_emojis,
)
from app.bot.rendering.pillow_utils import (
    draw_sakura_petals,
    draw_text_with_shadow as _shared_text_shadow,
    gradient_background,
    try_font,
)
from app.domain.entities.player_equipment_item import PlayerEquipmentItem
from app.domain.services.set_bonus_service import SetBonuses
from app.domain.value_objects.stats import Stats
from app.shared.emoji_mappings import (
    bonus_emoji,
    format_stat_bonuses_short,
)
from app.shared.enums import (
    PRIMARY_SLOTS,
    SECONDARY_SLOTS,
    SLOT_ICONS,
    SLOT_LABELS,
)
from app.shared.paths import ITEMS_ASSETS_DIR


WIDTH = 1024
GRID_HEIGHT = 820    # pages 1 & 2 (3×2 grid avec fontes généreuses)
SUMMARY_HEIGHT = 960  # page 3 (stats + set bonuses)


_BG_TOP = (12, 14, 28, 255)
_BG_BOTTOM = (38, 42, 78, 255)
_PANEL_BG = (0, 0, 0, 160)
_PANEL_BORDER = (255, 255, 255, 50)
_TEXT_PRIMARY = (255, 255, 255, 245)
_TEXT_SECONDARY = (210, 225, 245, 255)
_TEXT_MUTED = (175, 190, 215, 255)
_GOLD = (255, 220, 110, 255)
_SHADOW = (0, 0, 0, 220)
_PINK_PETAL = (255, 175, 200, 65)

# Couleur d'accent par slot — petit indice visuel
_SLOT_ACCENT = {
    "casque":          (235, 200, 100, 255),
    "plastron":        (200, 130, 90, 255),
    "jambieres":       (130, 110, 90, 255),
    "bottes":          (160, 100, 70, 255),
    "main_droite":     (235, 100, 100, 255),
    "main_gauche":     (90, 160, 230, 255),
    "collier":         (220, 180, 240, 255),
    "bracelet":        (200, 220, 255, 255),
    "bague":           (255, 215, 100, 255),
    "ceinture":        (180, 160, 130, 255),
    "cape":            (160, 100, 200, 255),
    "boucle_oreille":  (255, 200, 220, 255),
}

# Slot data centralisée dans `app/shared/enums.py`
_SLOT_LABEL = SLOT_LABELS
_SLOT_EMOJI = SLOT_ICONS

_PRIMARY_SLOTS = [s.value for s in PRIMARY_SLOTS]
_SECONDARY_SLOTS = [s.value for s in SECONDARY_SLOTS]


def _try_font(size: int, bold: bool = False):
    """Alias local pour conserver la convention de nommage interne."""
    return try_font(size, bold)


def _gradient_bg(width: int, height: int) -> Image.Image:
    return gradient_background(width, height, _BG_TOP, _BG_BOTTOM)


def _add_petals_decoration(base: Image.Image, seed: int) -> None:
    """Mini-pétales en filigrane (cohérence avec la bannière /profile).
    Palette monochrome rose plus sobre que le banner de profil."""
    palette = [(_PINK_PETAL[0], _PINK_PETAL[1], _PINK_PETAL[2], _PINK_PETAL[3])]
    draw_sakura_petals(
        base, seed=seed, count=20,
        palette=palette, size_range=(34, 60),
    )


def _draw_panel(
    base: Image.Image,
    origin: tuple[int, int],
    size: tuple[int, int],
    *,
    radius: int = 16,
    accent: tuple[int, int, int, int] | None = None,
) -> None:
    """Carte arrondie semi-transparente avec barre d'accent verticale."""
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.rounded_rectangle(
        [(0, 0), (size[0] - 1, size[1] - 1)],
        radius=radius,
        fill=_PANEL_BG,
        outline=_PANEL_BORDER,
        width=1,
    )
    # Léger highlight au sommet pour relief
    od.rounded_rectangle(
        [(0, 0), (size[0] - 1, size[1] // 2)],
        radius=radius,
        fill=(255, 255, 255, 14),
    )
    if accent is not None:
        accent_w = 5
        od.rounded_rectangle(
            [(0, 8), (accent_w, size[1] - 9)],
            radius=accent_w // 2,
            fill=accent,
        )
    base.alpha_composite(overlay, origin)


def _draw_text_with_shadow(
    draw, xy, text, font, fill=_TEXT_PRIMARY, shadow=_SHADOW,
    shadow_offset=(2, 2),
):
    _shared_text_shadow(draw, xy, text, font, fill, shadow, shadow_offset)


def _load_item_image(item_code: str, size: int = 180) -> Image.Image | None:
    """Charge l'image de l'item depuis assets/items/<code>.png si elle
    existe, redimensionnée au carré demandé (lanczos). Renvoie None si
    le fichier n'existe pas — l'appelant dessinera un placeholder.
    """
    path = ITEMS_ASSETS_DIR / f"{item_code}.png"
    if not path.exists():
        # Tente .jpg en alternative
        path = ITEMS_ASSETS_DIR / f"{item_code}.jpg"
        if not path.exists():
            return None
    try:
        img = Image.open(path).convert("RGBA")
    except Exception:
        return None
    img.thumbnail((size, size), Image.Resampling.LANCZOS)
    # Centre dans un canvas carré
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    cx = (size - img.width) // 2
    cy = (size - img.height) // 2
    canvas.alpha_composite(img, (cx, cy))
    return canvas


def _draw_placeholder(
    base: Image.Image, origin: tuple[int, int], size: int,
    slot: str, has_item: bool,
    item_emoji: str | None = None,
) -> None:
    """Dessine un placeholder stylisé quand l'image de l'item est absente
    (ou que le slot est vide). Utilise `item_emoji` si fourni (ex : 🛡️
    pour un bouclier dans main_droite), sinon l'emoji canonique du slot.
    """
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    od = ImageDraw.Draw(img)
    # Cadre arrondi sombre
    od.rounded_rectangle(
        [(0, 0), (size - 1, size - 1)],
        radius=18,
        fill=(20, 22, 40, 200) if has_item else (10, 12, 22, 160),
        outline=(255, 255, 255, 35) if has_item else (255, 255, 255, 18),
        width=2,
    )
    # Si vide : grosse icône slot pâle. Si has_item : icône item + indication
    # "image manquante" (label "?" en bas).
    emoji_size = int(size * 0.52)
    label_emoji = item_emoji or _SLOT_EMOJI.get(slot, "•")
    draw_text_with_emojis(
        img,
        ((size - emoji_size) // 2, (size - emoji_size) // 2 - 6),
        label_emoji,
        _try_font(emoji_size),
        fill=(255, 255, 255, 100 if not has_item else 200),
        shadow=(0, 0, 0, 0),
        emoji_size=emoji_size,
    )
    if not has_item:
        font = _try_font(18, bold=True)
        text = "VIDE"
        text_w = od.textlength(text, font=font)
        od.text(
            ((size - text_w) // 2, size - 32),
            text, font=font, fill=(120, 130, 150, 255),
        )
    base.alpha_composite(img, origin)


def _format_stat_bonuses_short(stat_bonuses: dict | None) -> str:
    """Bonus compact `+N {emoji}` — l'emoji est plus rapide à scanner que
    "Atk" / "Def" / "Crit" et ne déborde pas de la card. Délègue au
    helper centralisé."""
    return format_stat_bonuses_short(stat_bonuses)


def _draw_slot_card(
    base: Image.Image,
    origin: tuple[int, int],
    size: tuple[int, int],
    slot: str,
    equipment: PlayerEquipmentItem | None,
    two_handed_locked: bool = False,
) -> None:
    """Card individuelle pour un slot équipement."""
    accent = _SLOT_ACCENT.get(slot)
    _draw_panel(base, origin, size, accent=accent)
    x, y = origin
    w, h = size

    # Header : emoji + label slot. Fonte généreuse pour rester lisible
    # quand Discord compresse en thumbnail (~360 px).
    header_label = f"{_SLOT_EMOJI.get(slot, '•')}  {_SLOT_LABEL.get(slot, slot)}"
    header_font = _try_font(24, bold=True)
    draw_text_with_emojis(
        base, (x + 18, y + 14), header_label, header_font,
        fill=_TEXT_PRIMARY,
    )

    # Image de l'item (ou placeholder)
    img_size = min(180, w - 30, h - 130)
    img_x = x + (w - img_size) // 2
    img_y = y + 56

    if two_handed_locked:
        # Slot main_gauche verrouillé par une arme 2-mains : placeholder
        # spécifique avec emoji 🔒.
        ph = Image.new("RGBA", (img_size, img_size), (0, 0, 0, 0))
        pd = ImageDraw.Draw(ph)
        pd.rounded_rectangle(
            [(0, 0), (img_size - 1, img_size - 1)],
            radius=18,
            fill=(40, 28, 16, 180),
            outline=(255, 200, 80, 80),
            width=2,
        )
        lock_size = int(img_size * 0.45)
        draw_text_with_emojis(
            ph,
            ((img_size - lock_size) // 2, (img_size - lock_size) // 2 - 8),
            "🔒",
            _try_font(lock_size),
            fill=(255, 200, 80, 220),
            shadow=(0, 0, 0, 0),
            emoji_size=lock_size,
        )
        font = _try_font(15, bold=True)
        text = "ARME À 2 MAINS"
        text_w = pd.textlength(text, font=font)
        pd.text(
            ((img_size - text_w) // 2, img_size - 28),
            text, font=font, fill=(255, 200, 80, 220),
        )
        base.alpha_composite(ph, (img_x, img_y))
        return

    item_img = None
    if equipment is not None:
        item_img = _load_item_image(equipment.item_definition.code, img_size)

    if item_img is not None:
        base.alpha_composite(item_img, (img_x, img_y))
    else:
        # Pour les slots main, l'emoji canonique (🗡️) ne reflète pas
        # toujours la nature de l'item équipé (bouclier, 2-mains…).
        # On passe l'emoji adapté à l'item via `item_display_emoji`.
        item_emoji = None
        if equipment is not None:
            from app.shared.emoji_mappings import item_display_emoji
            item_emoji = item_display_emoji(equipment.item_definition)
        _draw_placeholder(
            base, (img_x, img_y), img_size, slot,
            has_item=equipment is not None,
            item_emoji=item_emoji,
        )

    # Nom de l'item + bonus de stats sous l'image
    if equipment is not None:
        item = equipment.item_definition
        name_font = _try_font(24, bold=True)
        bonuses_font = _try_font(23, bold=True)
        draw = ImageDraw.Draw(base)

        name_y = img_y + img_size + 12
        # Tronque légèrement plus court pour fitter avec la fonte 24
        name = item.name if len(item.name) <= 20 else item.name[:19] + "…"
        _draw_text_with_shadow(
            draw, (x + 16, name_y), name, name_font,
        )

        # Bonus stats : multi-lignes pour ne RIEN tronquer (max 2 lignes
        # pour rester dans la card). On distribue les parts sur les
        # lignes selon la largeur pixel disponible.
        from app.shared.emoji_mappings import format_stat_bonuses_parts
        parts = format_stat_bonuses_parts(item.stat_bonuses)
        if parts:
            available_w = w - 32  # marge x+16 à droite
            sep = " · "
            sep_w = measure_text_with_emojis(sep, bonuses_font, bonuses_font.size)
            lines: list[list[str]] = [[]]
            current_w = 0
            for part in parts:
                part_w = measure_text_with_emojis(
                    part, bonuses_font, bonuses_font.size,
                )
                add_w = part_w + (sep_w if lines[-1] else 0)
                if current_w + add_w > available_w and lines[-1]:
                    if len(lines) >= 2:
                        # On a déjà 2 lignes — fini, on ne dépasse pas
                        # (les parts restantes sautent — extrêmement
                        # rare avec un cap raisonnable).
                        break
                    lines.append([])
                    current_w = part_w
                    lines[-1].append(part)
                else:
                    current_w += add_w
                    lines[-1].append(part)

            line_y = name_y + 30
            line_h = 26
            for i, line_parts in enumerate(lines):
                if not line_parts:
                    continue
                draw_text_with_emojis(
                    base, (x + 16, line_y + i * line_h),
                    sep.join(line_parts), bonuses_font, fill=_GOLD,
                )


def _draw_page_header(
    base: Image.Image, player_name: str, page_title: str,
) -> None:
    """Bandeau du haut. Utilise `draw_text_with_emojis` pour que les
    glyphes color emoji (⚔️ 📦 💍 📊 …) s'affichent correctement —
    sinon DejaVuSans rend les emojis en boîtes vides."""
    name_font = _try_font(34, bold=True)
    sub_font = _try_font(22, bold=True)
    draw_text_with_emojis(
        base, (30, 24), f"⚔️  Équipement de {player_name}".strip(), name_font,
        fill=_TEXT_PRIMARY, shadow=_SHADOW,
    )
    draw_text_with_emojis(
        base, (30, 64), page_title, sub_font,
        fill=_TEXT_SECONDARY, shadow=_SHADOW,
    )
    # Ligne de séparation
    draw = ImageDraw.Draw(base)
    draw.line(
        [(30, 100), (WIDTH - 30, 100)],
        fill=(255, 255, 255, 60), width=2,
    )


def _draw_page_footer(
    base: Image.Image, page_label: str,
) -> None:
    draw = ImageDraw.Draw(base)
    h = base.size[1]
    font = _try_font(16)
    text_w = draw.textlength(page_label, font=font)
    draw.text(
        (WIDTH - text_w - 30, h - 26),
        page_label, font=font, fill=_TEXT_MUTED,
    )


def compose_equipment_grid_page(
    output_path: str,
    player_name: str,
    equipped_items: list[PlayerEquipmentItem],
    *,
    page: int,  # 1 ou 2
    seed: int = 0,
) -> None:
    """Génère un PNG pour la page 1 (Principal) ou 2 (Secondaire)."""
    bg = _gradient_bg(WIDTH, GRID_HEIGHT)
    _add_petals_decoration(bg, seed)

    if page == 1:
        slots = _PRIMARY_SLOTS
        page_title = "📦 Équipement principal"
        page_label = "Page 1 / 3 — Principaux"
    else:
        slots = _SECONDARY_SLOTS
        page_title = "💍 Équipement secondaire"
        page_label = "Page 2 / 3 — Secondaires"

    _draw_page_header(bg, player_name, page_title)

    # Map slot -> equipment
    equipped_by_slot: dict[str, PlayerEquipmentItem] = {
        e.slot: e for e in equipped_items
    }
    main_hand_item = equipped_by_slot.get("main_droite")
    two_handed_active = bool(
        main_hand_item and main_hand_item.item_definition.requires_two_hands
    )

    margin = 30
    spacing = 14
    grid_top = 120
    cols = 3
    card_w = (WIDTH - 2 * margin - (cols - 1) * spacing) // cols
    card_h = (GRID_HEIGHT - grid_top - 40 - spacing) // 2

    for idx, slot in enumerate(slots):
        row = idx // cols
        col = idx % cols
        x = margin + col * (card_w + spacing)
        y = grid_top + row * (card_h + spacing)

        equipment = equipped_by_slot.get(slot)
        # Verrouillage main_gauche si 2-mains équipée à droite
        locked = (slot == "main_gauche" and two_handed_active and equipment is None)
        _draw_slot_card(
            bg, (x, y), (card_w, card_h),
            slot, equipment, two_handed_locked=locked,
        )

    _draw_page_footer(bg, page_label)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    bg.convert("RGB").save(output_path, "PNG", optimize=True)


def compose_equipment_summary_page(
    output_path: str,
    player_name: str,
    equipped_items: list[PlayerEquipmentItem],
    set_bonuses: SetBonuses,
    *,
    seed: int = 0,
) -> None:
    """Page 3 : résumé des stats apportées par l'équipement + bonus de
    panoplie actifs."""
    bg = _gradient_bg(WIDTH, SUMMARY_HEIGHT)
    _add_petals_decoration(bg, seed)
    _draw_page_header(
        bg, player_name, "📊 Résumé : stats et panoplies",
    )

    # ----- Stats totales depuis l'équipement -----
    totals = {
        "max_hp": 0, "attack": 0, "defense": 0, "speed": 0,
        "crit_chance": 0, "crit_damage": 0, "dodge": 0,
        "hp_regeneration": 0,
    }
    for eq in equipped_items:
        b = eq.item_definition.stat_bonuses or {}
        for k in totals.keys():
            totals[k] += int(b.get(k, 0) or 0)

    # Ajouter les bonus de panoplie sur le total affiché
    totals["max_hp"] += set_bonuses.max_hp_flat
    totals["attack"] += set_bonuses.attack_flat
    totals["defense"] += set_bonuses.defense_flat
    totals["speed"] += set_bonuses.speed_flat
    totals["crit_chance"] += set_bonuses.crit_chance_flat
    totals["crit_damage"] += set_bonuses.crit_damage_flat
    totals["dodge"] += set_bonuses.dodge_flat
    totals["hp_regeneration"] += set_bonuses.hp_regeneration_flat

    # Section "Stats apportées par l'équipement"
    section_font = _try_font(26, bold=True)
    section_y = 130
    draw = ImageDraw.Draw(bg)
    draw_text_with_emojis(
        bg, (30, section_y),
        "📈  STATS APPORTÉES (équipement + panoplies)",
        section_font, fill=_TEXT_SECONDARY, shadow=_SHADOW,
    )
    draw.line(
        [(30, section_y + 40), (WIDTH - 30, section_y + 40)],
        fill=(255, 255, 255, 50), width=2,
    )

    # Grille 4×2 des stats totales — cards plus hautes pour fontes plus grosses
    margin = 30
    spacing = 12
    grid_y = section_y + 54
    cols = 4
    card_w = (WIDTH - 2 * margin - (cols - 1) * spacing) // cols
    card_h = 110

    label_font = _try_font(24, bold=True)
    value_font = _try_font(38, bold=True)

    stat_cards = [
        ("❤️", "PV", _signed(totals["max_hp"]), "hp"),
        ("⚔️", "Atk", _signed(totals["attack"]), "atk"),
        ("🛡️", "Def", _signed(totals["defense"]), "def"),
        ("💨", "Vit", _signed(totals["speed"]), "speed"),
        ("🎯", "Crit %", _signed(totals["crit_chance"]) + "%", "crit"),
        ("💥", "Crit dmg", _signed(totals["crit_damage"]) + "%", "cdmg"),
        ("🌀", "Esquive", _signed(totals["dodge"]) + "%", "dodge"),
        ("✨", "Régen", _signed(totals["hp_regeneration"]), "regen"),
    ]
    for idx, (emoji, label, value, _) in enumerate(stat_cards):
        row = idx // cols
        col = idx % cols
        x = margin + col * (card_w + spacing)
        y = grid_y + row * (card_h + spacing)
        _draw_panel(bg, (x, y), (card_w, card_h))
        # emoji à gauche, plus gros pour matcher la card élargie
        emoji_size = 48
        draw_text_with_emojis(
            bg, (x + 14, y + (card_h - emoji_size) // 2 + 4),
            emoji, _try_font(emoji_size),
            fill=_TEXT_PRIMARY, shadow=None, emoji_size=emoji_size,
        )
        # label haut, valeur bas
        text_x = x + 14 + emoji_size + 12
        _draw_text_with_shadow(
            draw, (text_x, y + 16), label, label_font,
            fill=_TEXT_SECONDARY,
        )
        _draw_text_with_shadow(
            draw, (text_x, y + 16 + label_font.size + 8),
            value, value_font,
        )

    # ----- Section "Bonus de panoplie" -----
    sets_section_y = grid_y + 2 * (card_h + spacing) + 22
    draw_text_with_emojis(
        bg, (30, sets_section_y), "🌸  BONUS DE PANOPLIE",
        section_font, fill=_TEXT_SECONDARY, shadow=_SHADOW,
    )
    draw.line(
        [(30, sets_section_y + 40), (WIDTH - 30, sets_section_y + 40)],
        fill=(255, 255, 255, 50), width=2,
    )

    sets_y = sets_section_y + 50
    # Une ligne par panoplie : icône + nom + count à gauche, bonus actif
    # à droite. Pas de sous-ligne "prochain palier" (lisibilité).
    line_height = 64
    card_h = line_height - 8

    if not set_bonuses.active_sets:
        _draw_text_with_shadow(
            draw, (30, sets_y),
            "_Aucun équipement avec famille n'est porté._",
            _try_font(20),
            fill=_TEXT_MUTED,
        )
    else:
        for idx, active in enumerate(set_bonuses.active_sets):
            y = sets_y + idx * line_height
            if y + line_height > SUMMARY_HEIGHT - 50:
                break
            # Card pour la panoplie
            _draw_panel(bg, (30, y), (WIDTH - 60, card_h))

            # Icône + nom + count (gauche)
            head_text = (
                f"{active.family_icon}  {active.family_name}"
                f"  ·  {active.pieces_equipped} pièce(s)"
            )
            head_font = _try_font(28, bold=True)
            draw_text_with_emojis(
                bg, (50, y + 14), head_text, head_font,
                fill=_TEXT_PRIMARY,
            )

            # Bonus actif (droite, gros, en doré). Contient un emoji,
            # donc on passe par draw_text_with_emojis pour le rendu couleur.
            right_x = WIDTH - 30 - 18
            if active.active_bonus_type:
                bonus_label = _bonus_label_short(
                    active.active_bonus_type, active.active_bonus_value,
                )
                bonus_text = f"+{bonus_label}"
                bf = _try_font(30, bold=True)
                tw = measure_text_with_emojis(bonus_text, bf, bf.size)
                draw_text_with_emojis(
                    bg, (right_x - tw, y + 13),
                    bonus_text, bf, fill=_GOLD,
                )

    _draw_page_footer(bg, "Page 3 / 3 — Résumé")
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    bg.convert("RGB").save(output_path, "PNG", optimize=True)


def _signed(n: int) -> str:
    """Format '+5' ou '-3' (sans signe pour 0)."""
    if n > 0:
        return f"+{n}"
    if n < 0:
        return str(n)
    return "0"


def _bonus_label_short(bonus_type: str, value: int) -> str:
    """Format compact `{value} {emoji}` — l'appelant ajoute le préfixe '+'.
    L'emoji remplace le label texte ("défense" → 🛡️) pour rester compact
    et lisible en thumbnail Discord."""
    return f"{value} {bonus_emoji(bonus_type)}"
