import discord


class EncounterView(discord.ui.View):
    def __init__(self, cog, timeout: float | None = 300):
        super().__init__(timeout=timeout)
        self.cog = cog

    @discord.ui.button(label="Combattre", style=discord.ButtonStyle.danger, emoji="⚔️")
    async def join_encounter(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        success, message = self.cog.register_participant(interaction.user.id)
        await interaction.response.send_message(message, ephemeral=True)