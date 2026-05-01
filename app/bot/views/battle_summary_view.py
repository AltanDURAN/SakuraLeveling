import discord

from app.bot.embeds.battle_summary_embeds import PAGES
from app.domain.value_objects.battle_summary import BattleSummary


class BattleSummaryView(discord.ui.View):
    """Vue paginée d'un résumé de combat (récompenses ↔ détails)."""

    def __init__(self, summary: BattleSummary, timeout: float = 600.0) -> None:
        super().__init__(timeout=timeout)
        self.summary = summary
        self.page_index = 0
        self._refresh_buttons()

    @property
    def current_embed(self) -> discord.Embed:
        _, builder = PAGES[self.page_index]
        return builder(self.summary)

    @property
    def page_label(self) -> str:
        label, _ = PAGES[self.page_index]
        return label

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
        # Bouton inactif servant d'indicateur de page.
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
