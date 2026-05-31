"""Mixins partagés entre cogs Discord.

Mutualise les patterns recopiés dans plusieurs cogs (cf. audit F5 / dup
xcut-duplication : le bloc `interaction_check` "canal beta uniquement" était
recopié dans 11 cogs joueurs).
"""

from __future__ import annotations

import discord


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

        if interaction.channel_id == settings.beta_channel_id:
            return True

        message = (
            "🚧 Le bot est actuellement en phase de test.\n"
            "Utilisez le channel beta dédié."
        )
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
        return False
