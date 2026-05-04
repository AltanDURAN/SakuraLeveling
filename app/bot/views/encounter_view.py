import discord

from app.infrastructure.db.repositories.help_subscriber_repository import (
    HelpSubscriberRepository,
)
from app.infrastructure.db.session import get_db_session


class EncounterView(discord.ui.View):
    def __init__(self, cog, timeout: float | None = 300):
        super().__init__(timeout=timeout)
        self.cog = cog
        # État interne du bouton "Demander de l'aide" : usable une seule fois.
        self._help_used: bool = False

    @discord.ui.button(label="Combattre", style=discord.ButtonStyle.danger, emoji="⚔️", row=0)
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

    @discord.ui.button(label="Quitter", style=discord.ButtonStyle.secondary, emoji="🚪", row=0)
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

    @discord.ui.button(
        label="Demander de l'aide",
        style=discord.ButtonStyle.success,
        emoji="📣",
        row=0,
    )
    async def request_help(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        """Tag tous les chads inscrits dans le canal d'encounter.
        Cliquable une seule fois par encounter — le bouton est désactivé
        après le premier usage."""
        if self._help_used:
            await interaction.response.send_message(
                "⚠️ L'appel à l'aide a déjà été lancé pour ce combat.",
                ephemeral=True,
            )
            return

        with get_db_session() as session:
            chad_discord_ids = HelpSubscriberRepository(session).list_all_discord_ids()

        # On marque le bouton comme utilisé AVANT toute action côté Discord
        # pour éviter qu'un double-click ne génère deux notifications.
        self._help_used = True
        button.disabled = True

        if not chad_discord_ids:
            await interaction.response.edit_message(view=self)
            await interaction.followup.send(
                "📣 Aucun chad inscrit pour l'instant — utilisez `/chad` "
                "pour rejoindre la liste des notifiables.",
                ephemeral=False,
            )
            return

        mentions = " ".join(f"<@{did}>" for did in chad_discord_ids)
        content = (
            f"📣 Aventuriers : {mentions} rassemblement ! "
            f"{interaction.user.mention} demande de l'aide pour le combat en cours."
        )

        # On édite la view (bouton désactivé) puis on poste l'appel
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(content, ephemeral=False)