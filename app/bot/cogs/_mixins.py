"""Mixins partagés entre cogs Discord.

Mutualise les patterns recopiés dans plusieurs cogs (cf. audit F5 / dup
xcut-duplication : le bloc `interaction_check` "canal beta uniquement" était
recopié dans 11 cogs joueurs).
"""

from __future__ import annotations

import discord

from app.domain.entities.player_profile import PlayerProfile
from app.infrastructure.db.repositories.player_repository import PlayerRepository


class BetaChannelOnlyMixin:
    """Restreint les slash commands d'un cog au canal beta configuré.

    Usage :
        class MyCog(BetaChannelOnlyMixin, commands.Cog):
            ...

    L'ordre `Mixin, Cog` est important : Python résout `interaction_check`
    sur le mixin avant l'implémentation par défaut de `commands.Cog`.
    """

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Import paresseux pour éviter de plomber le module avec settings au
        # chargement (cohérent avec les anciennes implémentations locales).
        from app.infrastructure.config.settings import settings

        if interaction.channel_id in settings.command_channel_ids:
            return True

        message = (
            "🚧 Cette commande n'est pas autorisée ici.\n"
            "Utilisez le salon **général** (ou une zone de farm) pour les commandes."
        )
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
        return False


class PlayerLookupMixin:
    """`joueur` optionnel des commandes consultatives : soi par défaut
    (profil créé au besoin), sinon lecture seule ; message si le joueur visé
    n'a jamais joué. Partagé par ProfileCog, EquipmentCog, EconomyCog."""

    def _resolve_profile(
        self,
        interaction: discord.Interaction,
        target: discord.Member | None,
        session,
    ) -> tuple[PlayerProfile | None, discord.abc.User]:
        """Renvoie (profile, target_member). Si target est None, get_or_create
        le profil de l'auteur. Si target est spécifié, lookup pur (pas de
        création). Le profil est None si target n'a jamais joué."""
        repo = PlayerRepository(session)

        if target is None:
            target_member = interaction.user
            profile = repo.get_or_create_by_discord_id(
                discord_id=target_member.id,
                username=target_member.name,
                display_name=target_member.display_name,
            )
        else:
            target_member = target
            profile = repo.get_by_discord_id(target_member.id)

        return profile, target_member

    async def _send_no_profile_error(
        self,
        interaction: discord.Interaction,
        target_member,
    ) -> None:
        message = (
            f"❌ {target_member.display_name} n'a pas encore de profil joueur."
        )
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
