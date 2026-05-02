"""View paginée de l'inventaire (boutons par catégorie).

Chaque bouton bascule vers une catégorie d'items (armes, équipement,
accessoires, consommables, ressources, tout). La view est ephemeral et
non-persistante — on accepte qu'elle expire au timeout (5 min). Le viewer
reste l'auteur de la commande, pas restrictif sur les autres viewers
(consultation publique).
"""

from __future__ import annotations

import discord

from app.bot.embeds.inventory_embeds import PAGES, build_inventory_embed
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
        self.current_page = "weapon"

        # Boutons générés dynamiquement à partir de PAGES (chaque catégorie
        # qui contient au moins 1 item, plus la page "all").
        from app.bot.embeds.inventory_embeds import _filter_items_for_page

        for key, label, emoji in PAGES:
            count = (
                len(items)
                if key == "all"
                else len(_filter_items_for_page(items, key))
            )
            # On affiche tous les boutons même vides (sauf si l'inventaire est
            # entièrement vide, auquel cas la view ne sert à rien — on n'affiche
            # aucun bouton). Le bouton est marqué "(0)" pour info.
            if count == 0 and key != "all":
                # Cache les pages vides pour ne pas surcharger la barre
                continue

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
