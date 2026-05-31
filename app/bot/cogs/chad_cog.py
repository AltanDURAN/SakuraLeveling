"""Cog `/chad` — système d'inscription au tag des appels à l'aide.

Un "chad" est un joueur qui accepte d'être tagué quand quelqu'un clique
sur le bouton 'Demander de l'aide' d'un encounter (cf. encounter_cog).
La commande `/chad` est un toggle : si pas inscrit → propose de rejoindre
la liste, si déjà inscrit → propose de quitter.
"""

import discord
from discord import app_commands
from discord.ext import commands

from app.infrastructure.config.settings import settings
from app.infrastructure.db.repositories.help_subscriber_repository import (
    HelpSubscriberRepository,
)
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.session import get_db_session
from app.bot.cogs._mixins import BetaChannelOnlyMixin


class _ChadConfirmView(discord.ui.View):
    """View éphémère avec boutons Oui / Annuler."""

    def __init__(
        self,
        author_id: int,
        is_currently_subscribed: bool,
        timeout: float = 60.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.is_currently_subscribed = is_currently_subscribed

    async def _check_owner(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "❌ Cette confirmation ne vous est pas destinée.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Oui", style=discord.ButtonStyle.success, emoji="✅")
    async def confirm(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if not await self._check_owner(interaction):
            return

        with get_db_session() as session:
            profile = PlayerRepository(session).get_or_create_by_discord_id(
                discord_id=interaction.user.id,
                username=interaction.user.name,
                display_name=interaction.user.display_name,
            )
            repo = HelpSubscriberRepository(session)

            if self.is_currently_subscribed:
                repo.unsubscribe(profile.player.id)
                remaining = repo.list_all_discord_ids()
                mentions = (
                    " ".join(f"<@{did}>" for did in remaining)
                    if remaining
                    else "_aucun chad inscrit pour l'instant_"
                )
                msg = (
                    "✅ Vous ne serez plus notifié lorsqu'une personne demande de l'aide.\n"
                    f"Liste des chads actuelle : {mentions}"
                )
            else:
                repo.subscribe(profile.player.id)
                msg = (
                    "✅ Vous êtes inscrit chez les chads — vous serez tagué "
                    "quand quelqu'un cliquera sur **Demander de l'aide** dans "
                    "un encounter. Refaites `/chad` pour quitter la liste."
                )

        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content=msg, view=self)
        self.stop()

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary, emoji="🛑")
    async def cancel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if not await self._check_owner(interaction):
            return
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            content="🛑 Aucune modification.",
            view=self,
        )
        self.stop()


class ChadCog(BetaChannelOnlyMixin, commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="chad",
        description="Rejoindre / quitter la liste des chads (tagués sur les appels à l'aide)",
    )
    async def chad(self, interaction: discord.Interaction) -> None:
        with get_db_session() as session:
            profile = PlayerRepository(session).get_or_create_by_discord_id(
                discord_id=interaction.user.id,
                username=interaction.user.name,
                display_name=interaction.user.display_name,
            )
            repo = HelpSubscriberRepository(session)
            is_sub = repo.is_subscribed(profile.player.id)

        if is_sub:
            prompt = (
                "💪 Vous êtes actuellement inscrit chez les **chads**.\n"
                "Voulez-vous quitter cette liste ? Vous ne serez plus tagué "
                "lors des appels à l'aide."
            )
        else:
            prompt = (
                "💪 Voulez-vous rejoindre la liste des **chads** ?\n"
                "Vous serez tagué dans le canal d'encounter quand un joueur "
                "cliquera sur **Demander de l'aide**."
            )

        view = _ChadConfirmView(
            author_id=interaction.user.id,
            is_currently_subscribed=is_sub,
        )
        await interaction.response.send_message(
            prompt, view=view, ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ChadCog(bot))
