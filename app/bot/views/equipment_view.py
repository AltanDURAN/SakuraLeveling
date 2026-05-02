import discord

from app.bot.embeds.equipment_embeds import PAGES
from app.domain.entities.player_equipment_item import PlayerEquipmentItem


class EquipmentView(discord.ui.View):
    """Vue paginée 2 pages : équipement principal ↔ équipement secondaire."""

    def __init__(
        self,
        target_name: str,
        equipped_items: list[PlayerEquipmentItem],
        timeout: float = 600.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.target_name = target_name
        self.equipped_items = equipped_items
        self.page_index = 0
        self._refresh_buttons()

    @property
    def current_embed(self) -> discord.Embed:
        _, builder = PAGES[self.page_index]
        return builder(self.target_name, self.equipped_items)

    def _refresh_buttons(self) -> None:
        self.previous_button.disabled = self.page_index == 0
        self.next_button.disabled = self.page_index >= len(PAGES) - 1
        self.indicator.label = f"{self.page_index + 1} / {len(PAGES)}"

    @discord.ui.button(emoji="⬅️", style=discord.ButtonStyle.secondary)
    async def previous_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if self.page_index > 0:
            self.page_index -= 1
            self._refresh_buttons()
        await interaction.response.edit_message(embed=self.current_embed, view=self)

    @discord.ui.button(label="1 / 2", style=discord.ButtonStyle.primary, disabled=True)
    async def indicator(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.defer()

    @discord.ui.button(emoji="➡️", style=discord.ButtonStyle.secondary)
    async def next_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if self.page_index < len(PAGES) - 1:
            self.page_index += 1
            self._refresh_buttons()
        await interaction.response.edit_message(embed=self.current_embed, view=self)
