import discord

from app.bot.rules_gate import GatedView
from app.shared.formatters import discord_countdown


class EncounterView(GatedView):
    def __init__(self, cog, channel_id: int, timeout: float | None = 300):
        super().__init__(timeout=timeout)
        self.cog = cog
        # Zone (salon de spawn) de cet encounter : sert à cibler le bon
        # encounter côté cog, chaque zone tournant son combat en parallèle.
        self.channel_id = channel_id
        # État interne du bouton "Demander de l'aide" : usable une seule fois.
        self._help_used: bool = False
        # Lancer et Quitter n'apparaissent que s'il y a au moins un participant.
        # Au spawn, personne n'a rejoint → on les retire.
        self.remove_item(self.launch_encounter)
        self.remove_item(self.leave_encounter)

    def _is_registered(self, user_id: int) -> bool:
        encounter = self.cog.active_encounters.get(self.channel_id)
        return bool(encounter and user_id in encounter.participants)

    def sync(self) -> None:
        """Synchronise l'affichage/état des boutons avec l'état de l'encounter :
        - Lancer et Quitter présents seulement si ≥1 participant.
        - Demander de l'aide désactivé + relabellisé si déjà utilisé.
        Appeler avant de ré-éditer le message avec la view."""
        encounter = self.cog.active_encounters.get(self.channel_id)
        has_participants = bool(encounter and encounter.participants)
        self.clear_items()
        self.add_item(self.join_encounter)
        if has_participants:
            self.add_item(self.launch_encounter)
            self.add_item(self.leave_encounter)
        self.add_item(self.request_help)

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
            # Fait apparaître Lancer et Quitter maintenant qu'il y a du monde.
            self.sync()
            try:
                await interaction.message.edit(view=self)
            except discord.DiscordException:
                pass

        if success:
            # L'heure du combat : le joueur sait quand revenir le regarder
            # (il sera aussi mentionné au lancement).
            encounter = self.cog.active_encounters.get(self.channel_id)
            if encounter is not None:
                message += (f"\n⏳ Le combat se lance {discord_countdown(encounter.ends_at)}, "
                            "ou dès qu'un combattant clique sur **Lancer**. "
                            "Tu seras mentionné pour le suivre en direct.")
        await interaction.followup.send(message, ephemeral=True)

    @discord.ui.button(label="Lancer", style=discord.ButtonStyle.primary, emoji="🚀", row=0)
    async def launch_encounter(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        """Le groupe est prêt : pas besoin d'attendre la fin du temps pour rejoindre."""
        _, message = self.cog.request_launch(self.channel_id, interaction.user.id)
        await interaction.response.send_message(message, ephemeral=True)

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
            # Retire Lancer et Quitter s'il ne reste plus personne.
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
                "⚠️ L'appel à l'aide est déjà parti pour ce combat.",
                ephemeral=True,
            )
            return
        # Réservé aux inscrits (décision de l'auteur, 14/11/2026) : le bouton est
        # à côté de « Combattre » et mentionne tout le rôle chad — un passant le
        # pressait par erreur.
        if not self._is_registered(interaction.user.id):
            await interaction.response.send_message(
                "📣 Inscris-toi d'abord au combat (**Combattre**) : l'appel à l'aide est "
                "réservé à ceux qui se battent.",
                ephemeral=True,
            )
            return

        # Le rôle chad est la source de vérité : on tague @chad (mention du
        # rôle) au lieu de lister chaque pseudo.
        from app.infrastructure.config.settings import settings
        role = (
            interaction.guild.get_role(settings.chad_role_id)
            if (interaction.guild is not None and settings.chad_role_id)
            else None
        )

        # On marque l'aide comme demandée AVANT toute action côté Discord
        # pour éviter qu'un double-click ne génère deux notifications.
        self._help_used = True
        self.sync()  # désactive + relabellise le bouton (et garde Quitter cohérent)

        # Personne n'a le rôle (ou rôle non configuré) → message d'invitation.
        if role is None or not role.members:
            await interaction.response.edit_message(view=self)
            await interaction.followup.send(
                "📣 Aucun chad pour l'instant : `/chad` pour prendre le rôle "
                "et être prévenu.",
                ephemeral=False,
            )
            return

        content = (
            f"📣 Aventuriers : {role.mention} rassemblement ! "
            f"{interaction.user.mention} demande de l'aide pour le combat en cours."
        )

        # On édite la view (bouton désactivé/relabellisé) puis on poste l'appel.
        # allowed_mentions=roles pour que la mention du rôle ping réellement.
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(
            content,
            ephemeral=False,
            allowed_mentions=discord.AllowedMentions(roles=[role]),
        )
