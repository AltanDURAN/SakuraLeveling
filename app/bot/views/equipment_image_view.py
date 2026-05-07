"""Vue paginée 3 pages pour /equipement, basée sur des images Pillow.

Page 1 : grille des 6 slots principaux (casque, plastron, …).
Page 2 : grille des 6 slots secondaires (collier, bracelet, …).
Page 3 : résumé des stats accumulées + bonus de panoplies actifs.

Chaque page est rendue à la volée à la demande, écrite sur disque dans
`assets/generated_equipment/`, puis attachée au message Discord.
"""

from __future__ import annotations

import discord

from app.bot.rendering.equipment_image import (
    compose_equipment_grid_page,
    compose_equipment_summary_page,
)
from app.domain.entities.player_equipment_item import PlayerEquipmentItem
from app.domain.services.set_bonus_service import SetBonuses
from app.shared.paths import GENERATED_EQUIPMENT_DIR


def _render_page(
    page_index: int,
    player_id: int,
    player_name: str,
    equipped_items: list[PlayerEquipmentItem],
    set_bonuses: SetBonuses,
    sets_definitions: dict[str, dict],
) -> str:
    """Rend la page demandée et renvoie le chemin disque."""
    GENERATED_EQUIPMENT_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"equipment_{player_id}_p{page_index + 1}.png"
    out = GENERATED_EQUIPMENT_DIR / filename

    if page_index in (0, 1):
        compose_equipment_grid_page(
            str(out),
            player_name=player_name,
            equipped_items=equipped_items,
            page=page_index + 1,
            seed=player_id,
        )
    else:
        compose_equipment_summary_page(
            str(out),
            player_name=player_name,
            equipped_items=equipped_items,
            set_bonuses=set_bonuses,
            sets_definitions=sets_definitions,
            seed=player_id,
        )
    return str(out)


class EquipmentImageView(discord.ui.View):
    PAGE_LABELS = ["Principaux", "Secondaires", "Résumé"]

    def __init__(
        self,
        *,
        player_id: int,
        player_name: str,
        equipped_items: list[PlayerEquipmentItem],
        set_bonuses: SetBonuses,
        sets_definitions: dict[str, dict],
        timeout: float = 600.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.player_id = player_id
        self.player_name = player_name
        self.equipped_items = equipped_items
        self.set_bonuses = set_bonuses
        self.sets_definitions = sets_definitions
        self.page_index = 0
        self._refresh_buttons()

    def _refresh_buttons(self) -> None:
        self.previous_button.disabled = self.page_index == 0
        self.next_button.disabled = self.page_index >= len(self.PAGE_LABELS) - 1
        self.indicator.label = (
            f"{self.PAGE_LABELS[self.page_index]} ({self.page_index + 1}/3)"
        )

    def render_current_page(self) -> tuple[discord.Embed, discord.File]:
        path = _render_page(
            self.page_index,
            self.player_id,
            self.player_name,
            self.equipped_items,
            self.set_bonuses,
            self.sets_definitions,
        )
        filename = path.rsplit("/", 1)[-1]
        embed = discord.Embed(color=discord.Color.dark_blue())
        embed.set_image(url=f"attachment://{filename}")
        file = discord.File(path, filename=filename)
        return embed, file

    async def _switch(self, interaction: discord.Interaction) -> None:
        embed, file = self.render_current_page()
        # Discord exige `attachments=[file]` pour remplacer le fichier joint.
        await interaction.response.edit_message(
            embed=embed, attachments=[file], view=self,
        )

    @discord.ui.button(emoji="⬅️", style=discord.ButtonStyle.secondary)
    async def previous_button(
        self, interaction: discord.Interaction, button: discord.ui.Button,
    ) -> None:
        if self.page_index > 0:
            self.page_index -= 1
            self._refresh_buttons()
        await self._switch(interaction)

    @discord.ui.button(label="—", style=discord.ButtonStyle.primary, disabled=True)
    async def indicator(
        self, interaction: discord.Interaction, button: discord.ui.Button,
    ) -> None:
        await interaction.response.defer()

    @discord.ui.button(emoji="➡️", style=discord.ButtonStyle.secondary)
    async def next_button(
        self, interaction: discord.Interaction, button: discord.ui.Button,
    ) -> None:
        if self.page_index < len(self.PAGE_LABELS) - 1:
            self.page_index += 1
            self._refresh_buttons()
        await self._switch(interaction)
