"""View paginée de l'inventaire (uniquement consommables et ressources).

Les équipements sont gérés séparément via /equipement_list.
La view est ephemeral et non-persistante — expire au timeout 5 min.
"""

from __future__ import annotations

import discord

from app.bot.views._base import ExpiringView

from app.bot.embeds.inventory_embeds import (
    PAGES,
    _filter_items_for_page,
    _is_inventory_item,
    build_inventory_embed,
)
from app.domain.entities.player_inventory_item import PlayerInventoryItem


class InventoryView(ExpiringView):
    def __init__(
        self,
        display_name: str,
        items: list[PlayerInventoryItem],
        timeout: float = 300.0,
        seed: int = 0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.display_name = display_name
        self.items = items
        self.seed = seed
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

    def render(self, seed: int = 0) -> tuple[discord.Embed, list[discord.File]]:
        """La page en image (DA du bot, 21/11/2026), l'embed texte en repli.
        À appeler dans un thread."""
        from app.bot.embeds.screen_embed import image_embed
        from app.bot.rendering import screens

        label, emoji = next(((lab, emo) for key, lab, emo in PAGES if key == self.current_page), ("Inventaire", "🎒"))
        page = sorted(_filter_items_for_page(self.items, self.current_page),
                      key=lambda i: (-i.quantity, i.item_definition.name))
        slots = [screens.Slot(i.item_definition.code, i.item_definition.name, i.quantity) for i in page]
        empty = ("Rien dans cette catégorie pour l'instant."
                 if any(_is_inventory_item(i) for i in self.items)
                 else "Inventaire vide : les monstres lâchent des matériaux, Elna prépare des potions (/alchimiste).")
        screen = image_embed(screens.compose_inventory, f"inventory_{seed}_{self.current_page}",
                             discord.Color.green(), name=self.display_name, page_label=f"{emoji} {label}",
                             slots=slots, empty_text=empty, seed=seed)
        if screen is None:
            return self._build_embed(), []
        return screen[0], [screen[1]]


class _PageButton(discord.ui.Button):
    def __init__(self, page_key: str, label: str, emoji: str) -> None:
        super().__init__(
            style=discord.ButtonStyle.secondary,
            label=label,
            emoji=emoji,
        )
        self.page_key = page_key

    async def callback(self, interaction: discord.Interaction) -> None:
        import asyncio

        view: InventoryView = self.view  # type: ignore[assignment]
        view.current_page = self.page_key
        await interaction.response.defer()
        embed, files = await asyncio.to_thread(view.render, view.seed)
        await interaction.edit_original_response(embed=embed, attachments=files, view=view)
