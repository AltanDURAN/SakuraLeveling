"""View paginée de la liste des équipements possédés par un joueur.

Rendue en image Pillow (cohérent avec /equipement, /profile, /panoplie).
Une page = une catégorie d'équipement (12 catégories : casques, plastrons,
jambières, bottes, armes, boucliers, colliers, bracelets, bagues, ceintures,
capes, boucles d'oreilles). 12 boutons de navigation au pied du message.

Si une catégorie a > 9 items, navigation interne via boutons ◀ ▶.
"""

from __future__ import annotations

import discord

from app.bot.rendering.item_card_grid import (
    CardSpec,
    compose_card_grid_page,
    item_asset_path,
)
from app.domain.entities.player_equipment_item import PlayerEquipmentItem
from app.domain.entities.player_inventory_item import PlayerInventoryItem
from app.shared.emoji_mappings import format_stat_bonuses_short
from app.shared.enums import CATEGORY_ICONS
from app.shared.paths import GENERATED_LISTS_DIR


# Ordre canonique des catégories en bouton.
PAGES: list[tuple[str, str, str]] = [
    ("helmet",   "Casques",            "⛑️"),
    ("chest",    "Plastrons",          "👕"),
    ("legs",     "Jambières",          "👖"),
    ("boots",    "Bottes",             "🥾"),
    ("weapon",   "Armes",              "⚔️"),
    ("shield",   "Boucliers",          "🛡️"),
    ("necklace", "Colliers",           "📿"),
    ("bracelet", "Bracelets",          "⛓️"),
    ("ring",     "Bagues",             "💍"),
    ("belt",     "Ceintures",          "🎗️"),
    ("cape",     "Capes",              "🧣"),
    ("earring",  "Boucles d'oreilles", "👂"),
]


_CATEGORY_ACCENT: dict[str, tuple[int, int, int, int]] = {
    "helmet":   (235, 200, 100, 255),
    "chest":    (200, 130, 90, 255),
    "legs":     (130, 110, 90, 255),
    "boots":    (160, 100, 70, 255),
    "weapon":   (235, 100, 100, 255),
    "shield":   (90, 160, 230, 255),
    "necklace": (220, 180, 240, 255),
    "bracelet": (200, 220, 255, 255),
    "ring":     (255, 215, 100, 255),
    "belt":     (180, 160, 130, 255),
    "cape":     (160, 100, 200, 255),
    "earring":  (255, 200, 220, 255),
}


_PAGE_SIZE = 9  # 3 cols × 3 rows


def _equipped_def_ids(equipped: list[PlayerEquipmentItem]) -> set[int]:
    return {e.item_definition.id for e in equipped}


def _filter_for_category(
    items: list[PlayerInventoryItem], category: str,
) -> list[PlayerInventoryItem]:
    return sorted(
        [i for i in items if i.item_definition.category == category],
        key=lambda i: (-i.quantity, i.item_definition.name),
    )


def _build_card(
    inv_item: PlayerInventoryItem,
    equipped_def_ids: set[int],
    accent: tuple[int, int, int, int] | None,
) -> CardSpec:
    d = inv_item.item_definition
    lines: list[str] = []
    bonuses_text = format_stat_bonuses_short(d.stat_bonuses)
    if bonuses_text:
        lines.append(bonuses_text)
    if d.family:
        lines.append(f"Panoplie : {d.family}")
    badge = "✅" if d.id in equipped_def_ids else None
    qty = inv_item.quantity
    if qty > 1:
        # On préfixe le nom avec la quantité pour la clarté
        name = f"×{qty}  {d.name}"
    else:
        name = d.name
    return CardSpec(
        name=name,
        icon_emoji=CATEGORY_ICONS.get(d.category, "📦"),
        icon_path=item_asset_path(d.code),
        accent=accent,
        lines=lines,
        badge=badge,
        code=d.code,
    )


def _render_page(
    player_id: int,
    display_name: str,
    items: list[PlayerInventoryItem],
    equipped: list[PlayerEquipmentItem],
    category: str,
    page_index: int,
) -> tuple[str, int, int]:
    """Rend l'image et renvoie (path, total_pages, total_items)."""
    GENERATED_LISTS_DIR.mkdir(parents=True, exist_ok=True)
    cat_items = _filter_for_category(items, category)
    total = len(cat_items)
    total_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
    page_index = max(0, min(page_index, total_pages - 1))

    chunk = cat_items[page_index * _PAGE_SIZE:(page_index + 1) * _PAGE_SIZE]
    equipped_ids = _equipped_def_ids(equipped)
    accent = _CATEGORY_ACCENT.get(category)

    cards = [_build_card(it, equipped_ids, accent) for it in chunk]
    label, emoji = next(
        ((lbl, em) for cat, lbl, em in PAGES if cat == category),
        ("Items", "📦"),
    )
    title = f"🎒  Inventaire de {display_name}"
    page_suffix = f" — page {page_index + 1}/{total_pages}" if total_pages > 1 else ""
    subtitle = f"{emoji} {label} ({total}){page_suffix}"

    out = (
        GENERATED_LISTS_DIR
        / f"equipment_list_{player_id}_{category}_p{page_index + 1}.png"
    )
    compose_card_grid_page(
        str(out), title=title, subtitle=subtitle,
        cards=cards, cols=3, rows=3, seed=player_id,
    )
    return str(out), total_pages, total


class _PrevCategoryButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(
            style=discord.ButtonStyle.secondary, emoji="◀", row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view: EquipementListView = self.view  # type: ignore[assignment]
        view._shift_category(-1)
        await view._send_update(interaction)


class _CategoryLabelButton(discord.ui.Button):
    """Bouton désactivé qui sert juste à afficher la catégorie courante."""

    def __init__(self) -> None:
        super().__init__(
            style=discord.ButtonStyle.primary,
            label="—",
            disabled=True, row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()


class _NextCategoryButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(
            style=discord.ButtonStyle.secondary, emoji="▶", row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view: EquipementListView = self.view  # type: ignore[assignment]
        view._shift_category(+1)
        await view._send_update(interaction)


class _PrevPageButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(
            style=discord.ButtonStyle.secondary,
            emoji="⬅️", row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view: EquipementListView = self.view  # type: ignore[assignment]
        if view.page_index > 0:
            view.page_index -= 1
        await view._send_update(interaction)


class _PageLabelButton(discord.ui.Button):
    """Bouton désactivé affichant la pagination interne (page X/Y)."""

    def __init__(self) -> None:
        super().__init__(
            style=discord.ButtonStyle.secondary,
            label="1/1", disabled=True, row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()


class _NextPageButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(
            style=discord.ButtonStyle.secondary,
            emoji="➡️", row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view: EquipementListView = self.view  # type: ignore[assignment]
        view.page_index += 1
        await view._send_update(interaction)


class EquipementListView(discord.ui.View):
    def __init__(
        self,
        player_id: int,
        display_name: str,
        items: list[PlayerInventoryItem],
        equipped: list[PlayerEquipmentItem],
        timeout: float = 300.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.player_id = player_id
        self.display_name = display_name
        self.items = items
        self.equipped = equipped
        self.page_index = 0

        # Liste des catégories dans l'ordre canonique de PAGES — toutes
        # affichables (compteur 0 inclus) pour garder la nav prévisible.
        self.category_keys: list[str] = [c for c, _, _ in PAGES]

        present_categories = {
            i.item_definition.category for i in items
            if any(c == i.item_definition.category for c, _, _ in PAGES)
        }
        self.current_page = next(
            (c for c, _, _ in PAGES if c in present_categories),
            PAGES[0][0],
        )

        # Row 0 : navigation catégorie (◀ label ▶)
        self.prev_cat_btn = _PrevCategoryButton()
        self.cat_label_btn = _CategoryLabelButton()
        self.next_cat_btn = _NextCategoryButton()
        self.add_item(self.prev_cat_btn)
        self.add_item(self.cat_label_btn)
        self.add_item(self.next_cat_btn)

        # Row 1 : pagination interne (◀ X/Y ▶) — affichée toujours, désactivée
        # quand 1 seule page.
        self.prev_page_btn = _PrevPageButton()
        self.page_label_btn = _PageLabelButton()
        self.next_page_btn = _NextPageButton()
        self.add_item(self.prev_page_btn)
        self.add_item(self.page_label_btn)
        self.add_item(self.next_page_btn)

    def _shift_category(self, delta: int) -> None:
        """Avance/recule d'une catégorie dans l'ordre canonique."""
        n = len(self.category_keys)
        if n == 0:
            return
        try:
            idx = self.category_keys.index(self.current_page)
        except ValueError:
            idx = 0
        new_idx = (idx + delta) % n
        self.current_page = self.category_keys[new_idx]
        self.page_index = 0

    def _category_meta(self, key: str) -> tuple[str, str, int]:
        label, emoji = next(
            ((lbl, em) for cat, lbl, em in PAGES if cat == key),
            ("Items", "📦"),
        )
        count = sum(
            1 for i in self.items if i.item_definition.category == key
        )
        return label, emoji, count

    def _refresh_button_states(self, total_pages: int) -> None:
        # Mise à jour du label catégorie (toujours actif côté style).
        label, emoji, count = self._category_meta(self.current_page)
        self.cat_label_btn.label = f"{label} ({count})"
        self.cat_label_btn.emoji = emoji

        # Pagination interne
        self.page_label_btn.label = f"{self.page_index + 1}/{total_pages}"
        self.prev_page_btn.disabled = self.page_index == 0
        self.next_page_btn.disabled = self.page_index >= total_pages - 1

    def render_current(self) -> tuple[discord.Embed, discord.File, int, int]:
        path, total_pages, total = _render_page(
            self.player_id, self.display_name, self.items, self.equipped,
            self.current_page, self.page_index,
        )
        self._refresh_button_states(total_pages)

        filename = path.rsplit("/", 1)[-1]
        embed = discord.Embed(color=discord.Color.dark_blue())
        embed.set_image(url=f"attachment://{filename}")
        file = discord.File(path, filename=filename)
        return embed, file, total_pages, total

    async def _send_update(self, interaction: discord.Interaction) -> None:
        embed, file, _, _ = self.render_current()
        await interaction.response.edit_message(
            embed=embed, attachments=[file], view=self,
        )
