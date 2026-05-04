"""View paginée de l'inventaire (uniquement consommables et ressources).

Les équipements sont gérés séparément via /equipement_list.
La view est ephemeral et non-persistante — expire au timeout 5 min.
"""

from __future__ import annotations

import discord

from app.bot.embeds.inventory_embeds import (
    PAGES,
    _filter_items_for_page,
    _is_inventory_item,
    build_inventory_embed,
)
from app.domain.entities.player_inventory_item import PlayerInventoryItem


class InventoryView(discord.ui.View):
    def __init__(
        self,
        display_name: str,
        items: list[PlayerInventoryItem],
        timeout: float = 300.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.display_name = display_name
        self.items = items
        # Page par défaut : consommables (le PAGES[0] courant)
        self.current_page = PAGES[0][0] if PAGES else "consumable"

        # Si aucun item non-équipable, on n'affiche aucun bouton
        non_equipable_count = sum(1 for i in items if _is_inventory_item(i))
        if non_equipable_count == 0:
            return

        for key, label, emoji in PAGES:
            count = len(_filter_items_for_page(items, key))
            button = _PageButton(
                page_key=key,
                label=f"{label} ({count})",
                emoji=emoji,
            )
            self.add_item(button)

    def _build_embed(self) -> discord.Embed:
        return build_inventory_embed(
            self.display_name, self.items, page_key=self.current_page
        )


class _PageButton(discord.ui.Button):
    def __init__(self, page_key: str, label: str, emoji: str) -> None:
        super().__init__(
            style=discord.ButtonStyle.secondary,
            label=label,
            emoji=emoji,
        )
        self.page_key = page_key

    async def callback(self, interaction: discord.Interaction) -> None:
        view: InventoryView = self.view  # type: ignore[assignment]
        view.current_page = self.page_key
        await interaction.response.edit_message(embed=view._build_embed(), view=view)
