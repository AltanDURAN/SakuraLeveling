import discord

from app.infrastructure.db.repositories.help_subscriber_repository import (
    HelpSubscriberRepository,
)
from app.infrastructure.db.session import get_db_session


class EncounterView(discord.ui.View):
    def __init__(self, cog, channel_id: int, timeout: float | None = 300):
        super().__init__(timeout=timeout)
        self.cog = cog
        # Zone (salon de spawn) de cet encounter : sert à cibler le bon
        # encounter côté cog, chaque zone tournant son combat en parallèle.
        self.channel_id = channel_id
        # État interne du bouton "Demander de l'aide" : usable une seule fois.
        self._help_used: bool = False
        # Le bouton "Quitter" n'apparaît que s'il y a au moins un participant.
        # Au spawn, personne n'a rejoint → on le retire.
        self.remove_item(self.leave_encounter)

    def sync(self) -> None:
        """Synchronise l'affichage/état des boutons avec l'état de l'encounter :
        - Quitter présent seulement si ≥1 participant.
        - Demander de l'aide désactivé + relabellisé si déjà utilisé.
        Appeler avant de ré-éditer le message avec la view."""
        encounter = self.cog.active_encounters.get(self.channel_id)
        has_participants = bool(encounter and encounter.participants)
        present = self.leave_encounter in self.children
        if has_participants and not present:
            self.add_item(self.leave_encounter)
        elif not has_participants and present:
            self.remove_item(self.leave_encounter)

        if self._help_used:
            self.request_help.disabled = True
            self.request_help.label = "Aide demandée"
            self.request_help.emoji = "✅"

    @discord.ui.button(label="Combattre", style=discord.ButtonStyle.danger, emoji="⚔️", row=0)
    async def join_encounter(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        success, message = await self.cog.register_participant(
            channel_id=self.channel_id,
            user_id=interaction.user.id,
            display_name=interaction.user.display_name,
            avatar_url=interaction.user.display_avatar.url,
        )

        if success:
            await self.cog.refresh_encounter_scene(self.channel_id)
            # Fait apparaître le bouton Quitter maintenant qu'il y a du monde.
            self.sync()
            try:
                await interaction.message.edit(view=self)
            except discord.DiscordException:
                pass

        await interaction.followup.send(message, ephemeral=True)

    @discord.ui.button(label="Quitter", style=discord.ButtonStyle.secondary, emoji="🚪", row=0)
    async def leave_encounter(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        success, message = await self.cog.unregister_participant(
            channel_id=self.channel_id,
            user_id=interaction.user.id,
        )

        if success:
            await self.cog.refresh_encounter_scene(self.channel_id)
            # Retire le bouton Quitter s'il ne reste plus personne.
            self.sync()
            try:
                await interaction.message.edit(view=self)
            except discord.DiscordException:
                pass

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
        Cliquable une seule fois par encounter — après usage le bouton est
        désactivé et affiche « Aide demandée »."""
        if self._help_used:
            await interaction.response.send_message(
                "⚠️ L'appel à l'aide a déjà été lancé pour ce combat.",
                ephemeral=True,
            )
            return

        with get_db_session() as session:
            chad_discord_ids = HelpSubscriberRepository(session).list_all_discord_ids()

        # On marque l'aide comme demandée AVANT toute action côté Discord
        # pour éviter qu'un double-click ne génère deux notifications.
        self._help_used = True
        self.sync()  # désactive + relabellise le bouton (et garde Quitter cohérent)

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

        # On édite la view (bouton désactivé/relabellisé) puis on poste l'appel
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(content, ephemeral=False)
