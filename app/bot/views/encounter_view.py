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
        await interaction.response.defer(ephemeral=True)

        success, message = await self.cog.register_participant(
            user_id=interaction.user.id,
            display_name=interaction.user.display_name,
            avatar_url=interaction.user.display_avatar.url,
        )

        if success:
            await self.cog.refresh_encounter_scene()

        await interaction.followup.send(message, ephemeral=True)

    @discord.ui.button(label="Quitter", style=discord.ButtonStyle.secondary, emoji="🚪")
    async def leave_encounter(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        success, message = await self.cog.unregister_participant(
            user_id=interaction.user.id,
        )

        if success:
            await self.cog.refresh_encounter_scene()

        await interaction.followup.send(message, ephemeral=True)