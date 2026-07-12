"""Cog `/chad` — toggle du rôle "chad".

Un "chad" est un membre qui accepte d'être tagué (mention du rôle @chad)
quand quelqu'un clique sur le bouton 'Demander de l'aide' d'un encounter
(cf. encounter_view). La commande `/chad` est un toggle du RÔLE Discord
`settings.chad_role_id` : si le membre a le rôle → propose de le retirer,
sinon → propose de l'ajouter. Le rôle est la source de vérité unique
(plus de liste en base).
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from app.infrastructure.config.settings import settings
from app.bot.cogs._mixins import BetaChannelOnlyMixin

_logger = logging.getLogger(__name__)


class _ChadConfirmView(discord.ui.View):
    """View éphémère avec boutons Oui / Annuler."""

    def __init__(
        self,
        author_id: int,
        role_id: int,
        is_currently_chad: bool,
        timeout: float = 60.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.role_id = role_id
        self.is_currently_chad = is_currently_chad

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

        member = interaction.user
        guild = interaction.guild
        role = guild.get_role(self.role_id) if guild is not None else None

        for child in self.children:
            child.disabled = True

        if role is None or not isinstance(member, discord.Member):
            await interaction.response.edit_message(
                content="❌ Rôle chad introuvable sur ce serveur.", view=self,
            )
            self.stop()
            return

        try:
            if self.is_currently_chad:
                await member.remove_roles(role, reason="/chad — quitte les chads")
                msg = (
                    "✅ Rôle **chad** retiré — vous ne serez plus tagué lors "
                    "des appels à l'aide. Refaites `/chad` pour le reprendre."
                )
            else:
                await member.add_roles(role, reason="/chad — rejoint les chads")
                msg = (
                    "✅ Rôle **chad** ajouté — vous serez tagué (via @chad) "
                    "quand un joueur cliquera sur **Demander de l'aide** dans "
                    "un encounter. Refaites `/chad` pour le retirer."
                )
        except discord.Forbidden:
            _logger.warning(
                "/chad : permissions insuffisantes pour gérer le rôle %s", self.role_id
            )
            msg = (
                "❌ Je n'ai pas la permission de gérer ce rôle. Vérifie que "
                "j'ai « Gérer les rôles » et que je suis au-dessus du rôle chad."
            )
        except discord.DiscordException:
            _logger.exception("/chad : échec du toggle de rôle")
            msg = "❌ Une erreur est survenue lors de la modification du rôle."

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
        description="Prendre / retirer le rôle chad (tagué @chad sur les appels à l'aide)",
    )
    async def chad(self, interaction: discord.Interaction) -> None:
        role_id = settings.chad_role_id
        guild = interaction.guild
        role = guild.get_role(role_id) if (guild is not None and role_id) else None

        if role is None:
            await interaction.response.send_message(
                "❌ Le rôle chad n'est pas configuré sur ce serveur.",
                ephemeral=True,
            )
            return

        is_chad = isinstance(interaction.user, discord.Member) and (
            interaction.user.get_role(role_id) is not None
        )

        if is_chad:
            prompt = (
                "💪 Vous avez actuellement le rôle **chad**.\n"
                "Voulez-vous le retirer ? Vous ne serez plus tagué (@chad) "
                "lors des appels à l'aide."
            )
        else:
            prompt = (
                "💪 Voulez-vous prendre le rôle **chad** ?\n"
                "Vous serez tagué (@chad) dans le canal d'encounter quand un "
                "joueur cliquera sur **Demander de l'aide**."
            )

        view = _ChadConfirmView(
            author_id=interaction.user.id,
            role_id=role_id,
            is_currently_chad=is_chad,
        )
        await interaction.response.send_message(
            prompt, view=view, ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ChadCog(bot))
